from dataclasses import dataclass, field
import logging
import threading
import time
from typing import List
import uuid

from hermes.model.messages import RTPPacket, TreeBuild, TreeBuildAck, TreeBuildInvalidation
from hermes.model.trees import PathTree
from hermes.port.protocol import LinkProtocol
from hermes.sim.ThreadManager import ThreadManager


@dataclass
class TreeEntry:
    rootward_portid: str
    hops: int
    tree_instance_id: str
    leafward_portids: List[str] = field(default_factory=list)

    def to_dict(self):
        """Convert the dataclass to a dictionary for JSON serialization"""
        return {
            'rootward_portid': self.rootward_portid,
            'hops': self.hops,
            'tree_instance_id': self.tree_instance_id
        }
    
    def __str__(self):
        return str(self.to_dict())
    
    def __repr__(self):
        return self.__str__()
    
    # This allows direct conversion via json.dumps
    def __json__(self):
        return self.to_dict()
    


class Agent(threading.Thread):
    """
    Agent is a thread that operates on top of the ports.

    This simple agent is responsible for:
    1. Receiving TREE_BUILD and TREE_BUILD_ACK messages from other nodes, building the tree structure.
    2. Managing the trees in the face of port connections and disconnections.
    3. RTP/LTP

    This agent is written synchronously (not ideal), but it models asynchronous behavior of the ports and port forwarding.
    """
    def __init__(self, node_id: str, thread_manager: ThreadManager):
        super().__init__()
        self.logger = logging.getLogger("Agent")
        self.thread_manager = thread_manager
        self.node_id = node_id
        self.trees = {}
        self.port_paths = {}
        self.stop_event = threading.Event()

    def _broadcast_tree_build(self, exclude_portid: str, tb_packet: TreeBuild):
        for portid, port in self.thread_manager.get_ports().items():
            if portid != exclude_portid and port.protocol_instance and port.protocol_instance.link_state == LinkProtocol.LinkState.CONNECTED:
                port.io.write_q.put(tb_packet.to_bytes())

    def run(self):
        self.logger.info("Agent started")
        while not self.stop_event.is_set():
            ports = self.thread_manager.get_ports()
            
            total_signals = sum(not port.io.signal_q.empty() for port in ports.values())
            if total_signals > 0:
                self.logger.info(f"Agent -- Processing {total_signals} signals from ports")

            for portid, port in ports.items():
                if not port.io.signal_q.empty():
                    signal = port.io.signal_q.get()
                    self.logger.info(f"{port.name} -- Received signal: {signal}")
                    if signal == b"CONNECTED":
                        self.logger.info(f"{port.name} -- Sending TREE_BUILD")
                        port.tree_instance_id = uuid.uuid4().hex
                        tb_packet = TreeBuild(
                            tree_id=port.port_id,
                            tree_instance_id=port.tree_instance_id,
                            hops=0,
                        )
                        # FIX: Ensure port_paths entry is created BEFORE sending packet
                        self.port_paths[portid] = PathTree(port.port_id, port.tree_instance_id)
                        port.io.write_q.put(tb_packet.to_bytes())
                        
                        # Also send existing trees to new port
                        for tree_id, tree in self.trees.items():
                            tb_packet = TreeBuild(
                                tree_id=tree_id,
                                tree_instance_id=tree.tree_instance_id,
                                hops=tree.hops,
                            )
                            port.io.write_q.put(tb_packet.to_bytes())
                    elif signal == b"DISCONNECTED": # Remove all trees that have this port as rootward
                        trees_to_remove = [tree_id for tree_id, tree in self.trees.items() if tree.rootward_portid == portid]
                        for tree_id in trees_to_remove:
                            self.logger.info(f"{port.name} -- Removing tree {tree_id} due to port disconnection")
                            tb_invalidation_packet = TreeBuildInvalidation(
                                tree_id=tree_id,
                                tree_instance_id=self.trees[tree_id].tree_instance_id,
                                rootward=False,
                            )
                            if self.trees[tree_id].hops == 1:
                                self.logger.info(f"{port.name} -- Sending TREE_BUILD_INVALIDATION for tree {tree_id} to leafward ports: {self.trees[tree_id].leafward_portids}")
                                for leafward_portid in self.trees[tree_id].leafward_portids:
                                    ports[leafward_portid].io.write_q.put(tb_invalidation_packet.to_bytes())
                            del self.trees[tree_id]
                            if tree_id in self.port_paths:
                                del self.port_paths[tree_id]

                if not port.io.read_q.empty():
                    data = port.io.read_q.get()
                    if data.startswith(b"TREE_BUILD "):
                        tb_packet = TreeBuild.from_bytes(data)
                        if tb_packet.tree_id not in self.trees:
                            self.logger.info(f"{port.name} -- Received TREE_BUILD for new tree: {tb_packet.tree_id}")
                            self.trees[tb_packet.tree_id] = TreeEntry(
                                rootward_portid=portid,
                                hops=tb_packet.hops + 1,
                                tree_instance_id=tb_packet.tree_instance_id,
                            )
                            tba_packet = TreeBuildAck(
                                tree_id=tb_packet.tree_id,
                                tree_instance_id=tb_packet.tree_instance_id,
                                hops=tb_packet.hops + 1,
                                path=[portid]
                            )
                            port.io.write_q.put(tba_packet.to_bytes())
                            tb_packet_new = TreeBuild(
                                tree_id=tb_packet.tree_id,
                                tree_instance_id=tb_packet.tree_instance_id,
                                hops=tb_packet.hops + 1,
                            )
                            self._broadcast_tree_build(portid, tb_packet_new)
                        elif tb_packet.tree_instance_id != self.trees[tb_packet.tree_id].tree_instance_id:
                            self.logger.info(f"{port.name} -- Received TREE_BUILD for known tree: {tb_packet.tree_id}, but with different instance id.")
                            self.trees[tb_packet.tree_id] = TreeEntry(
                                rootward_portid=portid,
                                hops=tb_packet.hops + 1,
                                tree_instance_id=tb_packet.tree_instance_id
                            )
                        elif portid == self.trees[tb_packet.tree_id].rootward_portid:
                            self.logger.info(f"{port.name} -- Received TREE_BUILD for known tree: {tb_packet.tree_id}. Ignoring.")
                    
                    # In Agent.run(), TREE_BUILD_ACK handling section:
                    elif data.startswith(b"TREE_BUILD_ACK "):
                        tba_packet = TreeBuildAck.from_bytes(data)
                        
                        if tba_packet.tree_id == port.port_id and tba_packet.tree_instance_id == port.tree_instance_id:
                            self.logger.info(f"{port.name} -- Received TREE_BUILD_ACK for own tree: {tba_packet.tree_id}/{tba_packet.tree_instance_id} -- {tba_packet.hops} hops -- {tba_packet.path}")
                            if portid in self.port_paths:
                                self.port_paths[portid].accumulate_path(tba_packet.path)
                            else:
                                self.logger.warning(f"Missing port_paths entry for {portid}")
                                
                        elif tba_packet.tree_id == port.port_id and tba_packet.tree_instance_id != port.tree_instance_id:
                            self.logger.info(f"{port.name} -- Received TREE_BUILD_ACK for known tree: {tba_packet.tree_id}, but with different instance id. Ignoring.")
                            
                        else:
                            if tba_packet.tree_id in self.trees:
                                self.logger.info(f"{port.name} -- Forwarding TREE_BUILD_ACK for other tree: {tba_packet.tree_id}")
                                self.trees[tba_packet.tree_id].leafward_portids.append(portid)
                                rootward_port = ports[self.trees[tba_packet.tree_id].rootward_portid]
                                tba_packet.path = [portid] + tba_packet.path
                                rootward_port.io.write_q.put(tba_packet.to_bytes())
                            else:
                                # Tree was deleted (invalidated) while ACK was in flight
                                self.logger.debug(f"{port.name} -- Received TREE_BUILD_ACK for deleted tree: {tba_packet.tree_id}")
                    
                    elif data.startswith(b"TREE_BUILD_INVALIDATION "):
                        tb_invalidation_packet = TreeBuildInvalidation.from_bytes(data)
                        if tb_invalidation_packet.tree_id in self.trees:
                            self.logger.info(f"{port.name} -- Forwarding TREE_BUILD_INVALIDATION for tree: {tb_invalidation_packet.tree_id} leafward: {tb_invalidation_packet.rootward}")
                            for leafward_portid in self.trees[tb_invalidation_packet.tree_id].leafward_portids:
                                ports[leafward_portid].io.write_q.put(tb_invalidation_packet.to_bytes())
                            del self.trees[tb_invalidation_packet.tree_id]
                        else:
                            self.logger.info(f"{port.name} -- Received TREE_BUILD_INVALIDATION for unknown tree: {tb_invalidation_packet.tree_id}")
                    
                    elif data.startswith(b"RTP "):
                        rtp_packet = RTPPacket.from_bytes(data.content)
                        if rtp_packet.tree_id not in self.trees:
                            self.logger.info(f"{port.name} -- Received RTP for unknown tree: {rtp_packet.tree_id}")

            time.sleep(0.01) # unlock the GIL
            
    def stop(self):
        """Stop the agent thread"""
        self.logger.info("Stopping Agent")
        self.stop_event.set()
        self.join()

    def get_snapshot(self):
        """Get a JSON-serializable snapshot of the agent state"""
        trees_dict = {}
        for tree_id, tree_entry in self.trees.items():
            # Convert TreeEntry to a simple dict for JSON serialization
            trees_dict[tree_id] = tree_entry.to_dict()
        
        return {
            'node_id': self.node_id,
            'trees': trees_dict,
            'port_paths': {tree_id: tree.serialize() for tree_id, tree in self.port_paths.items()}
        }
