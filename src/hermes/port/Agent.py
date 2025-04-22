import logging
import threading
import time
from hermes.model.messages import RTPPacket, TreeBuild, TreeBuildAck
from hermes.sim.ThreadManager import ThreadManager

class Agent(threading.Thread):
    def __init__(self, node_id: str, thread_manager: ThreadManager):
        super().__init__()
        self.logger = logging.getLogger("Agent")
        self.thread_manager = thread_manager
        self.node_id = node_id
        self.trees = {}
    
    def _broadcast_tree_build(self, exclude_portid: str, tb_packet: TreeBuild):
        for portid, port in self.thread_manager.get_ports().items():
            if portid == exclude_portid:
                continue
            port.io.write_q.put(tb_packet.to_bytes())

    def run(self):
        self.logger.info("Agent started")
        while True:
            ports = self.thread_manager.get_ports()
            for portid, port in ports.items():
                if not port.io.signal_q.empty():
                    signal = port.io.signal_q.get()
                    self.logger.info(f"{port.name} -- Received signal: {signal}")
                    if signal == b"CONNECTED":
                        self.logger.info(f"{port.name} -- Sending TREE_BUILD")
                        tb_packet = TreeBuild(
                            tree_id=port.port_id,
                            sending_node_id=self.node_id,
                            hops=0,
                            path=[]
                        )
                        port.io.write_q.put(tb_packet.to_bytes())

                if not port.io.read_q.empty():
                    data = port.io.read_q.get()
                    if data.startswith(b"TREE_BUILD "):
                        tb_packet = TreeBuild.from_bytes(data)
                        if tb_packet.tree_id not in self.trees:
                            self.logger.info(f"{port.name} -- Received TREE_BUILD for unknown tree: {tb_packet.tree_id}")
                            self.trees[tb_packet.tree_id] = {
                                "rootward": (portid, tb_packet.hops),
                                "leafward": None
                            }
                            tba_packet = TreeBuildAck(
                                tree_id=tb_packet.tree_id,
                                hops=tb_packet.hops + 1,
                                path=tb_packet.path + [portid]
                            )
                            port.io.write_q.put(tba_packet.to_bytes())
                            tb_packet_new = TreeBuild(
                                tree_id=tb_packet.tree_id,
                                sending_node_id=tb_packet.sending_node_id,
                                hops=tb_packet.hops + 1,
                                path=tb_packet.path + [portid]
                            )
                            self._broadcast_tree_build(portid, tb_packet_new)
                        elif portid not in self.trees[tb_packet.tree_id]:
                            self.logger.info(f"{port.name} -- Received TREE_BUILD for known tree: {tb_packet.tree_id}")
                            self.trees[tb_packet.tree_id][portid] = tb_packet.hops
                    
                    elif data.startswith(b"TREE_BUILD_ACK "):
                        tba_packet = TreeBuildAck.from_bytes(data)
                        if tba_packet.tree_id == port.port_id:
                            self.logger.info(f"{port.name} -- Received TREE_BUILD_ACK for own tree: {tba_packet.tree_id} -- {tba_packet.hops} hops -- {tba_packet.path}")
                        else:
                            self.logger.info(f"{port.name} -- Forwarding TREE_BUILD_ACK for other tree: {tba_packet.tree_id}")
                            rootward_portid = self.trees[tba_packet.tree_id]["rootward"][0]
                            rootward_port = ports[rootward_portid]
                            rootward_port.io.write_q.put(tba_packet.to_bytes())
                    
                    elif data.startswith(b"RTP "):
                        rtp_packet = RTPPacket.from_bytes(data.content)
                        if rtp_packet.tree_id not in self.trees:
                            self.logger.info(f"{port.name} -- Received RTP for unknown tree: {rtp_packet.tree_id}")
                            continue
            time.sleep(0.01) # unlock the GIL
