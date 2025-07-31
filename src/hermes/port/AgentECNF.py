import random
from dataclasses import dataclass, field
import logging
import threading
import time
from typing import List
import uuid
import asyncio

# from hermes.model.messages import RTPPacket, TreeBuild, TreeBuildAck, TreeBuildInvalidation
from hermes.model.trees import PathTree
from hermes.port.protocol import LinkProtocol
from hermes.sim.ThreadManager import ThreadManager

@dataclass
class TreeBuild:
    tree_id: str
    tree_instance_id: str
    hops: int
    neighbors: List[str] = field(default_factory=list)  # ✅ Add this
    
    def to_bytes(self):
        neighbors_str = ",".join(self.neighbors)
        return f"TREE_BUILD {self.tree_id} {self.tree_instance_id} {self.hops} {neighbors_str}".encode()
    
    @classmethod
    def from_bytes(cls, data: bytes):
        parts = data.decode().split(" ", 4)
        neighbors = parts[4].split(",") if len(parts) > 4 and parts[4] else []
        return cls(
            tree_id=parts[1],
            tree_instance_id=parts[2], 
            hops=int(parts[3]),
            neighbors=neighbors
        )

@dataclass
class TreeBuildAck:
    tree_id: str
    tree_instance_id: str
    hops: int
    path: List[str] = field(default_factory=list)
    neighbors: List[str] = field(default_factory=list)  # ✅ Add neighbor list
    
    def to_bytes(self):
        path_str = ",".join(self.path)
        neighbors_str = ",".join(self.neighbors)
        return f"TREE_BUILD_ACK {self.tree_id} {self.tree_instance_id} {self.hops} {path_str} {neighbors_str}".encode()
    
    @classmethod
    def from_bytes(cls, data: bytes):
        parts = data.decode().split(" ", 5)
        path = parts[4].split(",") if len(parts) > 4 and parts[4] else []
        neighbors = parts[5].split(",") if len(parts) > 5 and parts[5] else []
        return cls(
            tree_id=parts[1],
            tree_instance_id=parts[2],
            hops=int(parts[3]),
            path=path,
            neighbors=neighbors
        )

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
    


class Agent:
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
        self.running = False

        self.neighbors = {} # 1 hop away
        
        self.link_events = asyncio.Queue() # for establishing connections and TIKTYKTIK
        self.tree_events = asyncio.Queue() # for tree build events
        self.message_events = asyncio.Queue() # for DATA messages

        self.state_lock = asyncio.Lock()  # Lock for managing shared state

        self.seen_invalidations = set() # processed invalidation
        self.invalidation_ttl = 10 # max hops
        
        self._last_tree_change = time.time()

    async def run(self):
        self.logger.info("Starting Agent")
        self.running = True
        ports = self.thread_manager.get_ports()
        self.logger.info(f"🔍 Initial ports for {self.node_id}: {list(ports.keys())}")

        for port_id, port in ports.items():
            if port.protocol_instance:
                state = port.protocol_instance.link_state
                self.logger.info(f"📡 Port {port_id} initial state: {state}")
            else:
                self.logger.info(f"📡 Port {port_id} has no protocol instance yet")
        
        if self.node_id in self.trees:
            self.logger.warning(f"⚠️ Tree for {self.node_id} already exists at startup: {self.trees[self.node_id]}")
        else:
            self.logger.info(f"✅ No tree exists for {self.node_id} at startup (expected)")
        
        tasks = [
            asyncio.create_task(self._handle_link_events()), # handles CONNECTED, DISCONNECTED, and TIKTYKTIK messages
            asyncio.create_task(self._handle_tree_events()), # handles TREE_BUILD and TREE_BUILD_ACK messages
            asyncio.create_task(self._handle_message_events()), # handles DATA messages
            asyncio.create_task(self._monitor_ports()), # provides information on events 
        ]
        try:
            await asyncio.gather(*tasks)
        
        except Exception as e:
            self.logger.error(f"Agent encountered an error: {e}", exc_info=True)
            
        finally:
            self.running = False
            
            
    async def _handle_tree_events(self):
        while self.running:
            try:
                event =  await self.tree_events.get()
                
                if event['data'].startswith(b"TREE_BUILD "):
                    await self._handle_tree_build(event)
                elif event['data'].startswith(b"TREE_BUILD_ACK "):
                    await self._handle_tree_build_ack(event)
                elif event['data'].startswith(b"TREE_BUILD_INVALIDATION "):
                    await self._handle_tree_invalidation(event)
                    
            except:
                self.logger.error("Error handling tree events", exc_info=True)

    async def _handle_tree_build_ack(self, event):
        try:
            ack_packet = TreeBuildAck.from_bytes(event['data']) 
            port_id = event['port_id']
            
            self.logger.info("Received TREE_BUILD_ACK from %s: %s", port_id, ack_packet)
            
            if ack_packet.neighbors:
                await self._update_neighbor_info(port_id, ack_packet.neighbors)
                
            # store neigbor information in tree entry based on LOV principle
            if ack_packet.tree_id == self.node_id:
                await self._handle_own_tree_ack(ack_packet, port_id)
            else:
                # someone elses ack
                await self._forward_tree_ack(ack_packet, port_id)
        except Exception as e:
            self.logger.error(f"Error handling TREE_BUILD_ACK: {e}", exc_info=True)
    
    async def _handle_own_tree_ack(self, ack_packet: TreeBuildAck, port_id: str):
        self.logger.info(f"Received ACK from our tree from port {port_id}: {ack_packet}")
        
        if port_id in self.port_paths:
            self.port_paths[port_id].accumulate_path(ack_packet.path)
    async def _forward_tree_ack(self, ack_packet: TreeBuildAck, from_port_id: str):
        """Forward ACK toward root, accumulating path and neighbor info"""
        
        if ack_packet.tree_id not in self.trees:
            self.logger.warning(f"Received ACK for unknown tree {ack_packet.tree_id}")
            return
        
        tree_entry = self.trees[ack_packet.tree_id]
        
        # Add this child to our leafward ports
        if from_port_id not in tree_entry.leafward_portids:
            tree_entry.leafward_portids.append(from_port_id)
        
        # Forward ACK to our parent with accumulated info
        forwarded_ack = TreeBuildAck(
            tree_id=ack_packet.tree_id,
            tree_instance_id=ack_packet.tree_instance_id,
            hops=ack_packet.hops,
            path=[tree_entry.rootward_portid] + ack_packet.path, 
            neighbors=ack_packet.neighbors + self._get_current_neighbors()  
        )
        
        await self._send_on_port(tree_entry.rootward_portid, forwarded_ack.to_bytes())
            
        
    async def _update_neighbor_info(self, port_id: str, neighbor_list: List[str]):
        """Update our knowledge of what neighbors this port can reach (LOV)"""
        
        # Store neighbor information for this port
        if port_id not in self.neighbors:
            self.neighbors[port_id] = {}
        
        self.neighbors[port_id].update({
            'reachable_neighbors': neighbor_list,
            'last_updated': time.time(),
            'hop_distance': 1  # These are 1-hop neighbors via this port
        })
        
        self.logger.info(f"Updated neighbor info for port {port_id}: {neighbor_list}")
                    
                    
                
                
            
  
                
    async def _handle_tree_build(self, event: TreeBuild):

        tb_packet = TreeBuild.from_bytes(event['data'])
        port_id = event['port_id']
        
        self.logger.info("Received TREE_BUILD from %s: %s", port_id, tb_packet)
        
        if await self._should_join_tree(tb_packet, port_id):
            await self._join_tree(tb_packet, port_id)
        else:
            self.logger.info(f"Ignoring TREE_BUILD for {tb_packet.tree_id} (already have better path)")
            
    async def _join_tree(self, tb_packet: TreeBuild, port_id: str):
        """Join a tree and send ACK with our neighbor info (fixed version)"""
        self.logger.info(f"=== JOINING TREE {tb_packet.tree_id} ===")
        self.logger.info(f"Tree instance: {tb_packet.tree_instance_id}")
        self.logger.info(f"Hops: {tb_packet.hops} -> {tb_packet.hops + 1}")
        self.logger.info(f"Via port: {port_id}")
        
        async with self.state_lock:
            # Update our tree entry
            self.trees[tb_packet.tree_id] = TreeEntry(
                rootward_portid=port_id,
                hops=tb_packet.hops + 1,
                tree_instance_id=tb_packet.tree_instance_id,
                leafward_portids=[]
            )

            self.logger.info(f"Created tree entry: {self.trees[tb_packet.tree_id]}")

            
            # Send ACK back to parent with our neighbor information
            ack_packet = TreeBuildAck(
                tree_id=tb_packet.tree_id,
                tree_instance_id=tb_packet.tree_instance_id,
                hops=tb_packet.hops + 1,
                path=[port_id],  # Start path with our port to parent
                neighbors=self._get_current_neighbors()  # Our neighbor list
            )
            self.logger.info(f"Sending TREE_BUILD_ACK: {ack_packet}")
 
            await self._send_on_port(port_id, ack_packet.to_bytes())

            self.logger.info(f"Now forwarding tree build to other ports...")
            # Forward to other ports
            await self._forward_tree_build(tb_packet, port_id)
            
            self.logger.info(f"=== FINISHED JOINING TREE {tb_packet.tree_id} ===")

    
    async def _forward_tree_build(self, tb_packet: TreeBuild, exclude_port: str):
        self.logger.info(f"=== FORWARDING TREE_BUILD for {tb_packet.tree_id} ===")
        self.logger.info(f"Original hops: {tb_packet.hops}, excluding port: {exclude_port}")
        
        forwarded_packet = TreeBuild(
            tree_id=tb_packet.tree_id,
            tree_instance_id=tb_packet.tree_instance_id,
            hops=tb_packet.hops + 1,
            neighbors= self._get_current_neighbors()
        )
        
        self.logger.info(f"Forwarded packet: {forwarded_packet}")
        
        ports = self.thread_manager.get_ports()
        self.logger.info(f"Available ports: {list(ports.keys())}")
        
        forwarded_count = 0
        for port_id, port in ports.items():
            port_state = "UNKNOWN"
            if port.protocol_instance:
                port_state = port.protocol_instance.link_state
                
            self.logger.info(f"Checking port {port_id}: exclude={port_id == exclude_port}, state={port_state}")
            
            if (port.port_id != exclude_port and \
            port.protocol_instance and 
            port.protocol_instance.link_state == LinkProtocol.LinkState.CONNECTED):
            
                self.logger.info(f"✅ Forwarding TREE_BUILD for {tb_packet.tree_id} to port {port_id}")
                await self._send_on_port(port_id, forwarded_packet.to_bytes())
                forwarded_count += 1
            else:
                self.logger.info(f"❌ Skipping port {port_id} - excluded or not connected")
                
        self.logger.info(f"Forwarded TREE_BUILD to {forwarded_count} ports")
        self.logger.info(f"=== END FORWARDING for {tb_packet.tree_id} ===")

                
    def _get_current_neighbors(self):
        neighbors = []
        ports = self.thread_manager.get_ports()
        
        for port_id, port in ports.items():
            if (port.protocol_instance and 
                port.protocol_instance.link_state == LinkProtocol.LinkState.CONNECTED):
                
                # Extract neighbor cell ID from port connection
                neighbor_info = self.neighbors.get(port_id)
                if neighbor_info and 'cell_id' in neighbor_info:
                    neighbors.append(neighbor_info['cell_id'])
                else:
                    neighbors.append(f"neighbor_via_{port_id}")
        
        return neighbors
    
    async def _should_join_tree(self, tb_packet: TreeBuild, port_id: str) -> bool:
        """Simplified tree joining logic - prioritize connectivity over optimization"""
        
        # First time seeing this tree - always join
        if tb_packet.tree_id not in self.trees:
            self.logger.info(f"SHOULD_JOIN: First time seeing tree {tb_packet.tree_id} - YES")
            return True
        
        existing_tree = self.trees[tb_packet.tree_id]
        
        # Different instance (tree rebuild) - always join  
        if tb_packet.tree_instance_id != existing_tree.tree_instance_id:
            self.logger.info(f"SHOULD_JOIN: New instance of tree {tb_packet.tree_id} - YES")
            return True
        
        # Same path from same port (refresh) - always join
        if port_id == existing_tree.rootward_portid:
            self.logger.info(f"SHOULD_JOIN: Refresh from same port {port_id} - YES")
            return True
        
        # NEW: Accept any path that's better or equal
        new_hops = tb_packet.hops + 1
        if new_hops <= existing_tree.hops:
            self.logger.info(f"SHOULD_JOIN: Better or equal path - YES")
            self.logger.info(f"  Current hops: {existing_tree.hops}, new hops: {new_hops}")
            return True
        
        # Only reject if worse
        self.logger.info(f"SHOULD_JOIN: Rejecting worse path - NO")
        self.logger.info(f"  Current hops: {existing_tree.hops}, new hops: {new_hops}")
        return False
                        
    async def _handle_link_events(self):
        while self.running:
            try:
                event = await self.link_events.get()
                
                if event['type'] == 'CONNECTED':
                    self.logger.info(f"Handling CONNECTED event: {event}")
                    await self._handle_connected(event)
                elif event['type'] == 'DISCONNECTED':
                    self.logger.info(f"Handling DISCONNECTED event: {event}")
                    await self._handle_disconnected(event)
                elif event['type'] == 'TIKTYKTIK':
                    self.logger.info(f"Handling TIKTYKTIK event: {event}")
                    await self._handle_tiktyktik(event)

                elif event['type'] == 'UNKNOWN_MESSAGE':
                    # Handle unknown message types
                    self.logger.warning(f"Received unknown message type: {event.get('data', 'No data')}")
                else:
                    self.logger.warning(f"Unhandled event type: {event['type']}")
                    
            except Exception as e:
                self.logger.error(f"Error handling link events: {e}", exc_info=True)
    
    async def _handle_message_events(self):
        while self.running:
            try:
                event = await self.message_events.get()
                
                await self._handle_data_message(event)
                
                self.logger.info("Received DATA message: %s", event['data'])
                
            except:
                self.logger.error("Error handling message events", exc_info=True)
                
    async def _handle_tree_invalidation(self, event):
        """Handle tree invalidation with flood control to prevent infinite loops"""
        try:
            data_str = event['data'].decode()
            parts = data_str.split(" ")
            
            if len(parts) < 4:
                # Old format without TTL - add TTL
                tree_id = parts[1]
                tree_instance_id = parts[2]
                ttl = self.invalidation_ttl
                invalidation_id = f"{tree_id}:{tree_instance_id}"
            else:
                # New format with TTL
                tree_id = parts[1]
                tree_instance_id = parts[2]
                ttl = int(parts[3])
                invalidation_id = f"{tree_id}:{tree_instance_id}"
            
            from_port_id = event['port_id']

            self.logger.info(f"Processing TREE_BUILD_INVALIDATION for tree {tree_id} "
                            f"from port {from_port_id}, TTL={ttl}, ID={invalidation_id}")

            # FLOOD CONTROL: Check if we've already seen this invalidation
            if invalidation_id in self.seen_invalidations:
                self.logger.info(f"Already processed invalidation {invalidation_id} - ignoring")
                return
                
            # FLOOD CONTROL: Check TTL 
            if ttl <= 0:
                self.logger.info(f"TTL expired for invalidation {invalidation_id} - not forwarding")
                return
                
            # Mark this invalidation as seen
            self.seen_invalidations.add(invalidation_id)
            self.logger.info(f"Marked invalidation {invalidation_id} as seen")

            # Process the invalidation locally
            invalidated_locally = False
            if tree_id in self.trees:
                tree_entry = self.trees[tree_id]
                
                if tree_entry.tree_instance_id == tree_instance_id:
                    self.logger.info(f"Invalidating local tree {tree_id}")
                    del self.trees[tree_id]
                    self._last_tree_change = time.time()  # Update last change time
                    invalidated_locally = True
                    self.logger.info(f"✅ Invalidated and removed tree {tree_id}")
                else:
                    self.logger.info(f"Instance mismatch for tree {tree_id}: "
                                f"received {tree_instance_id}, have {tree_entry.tree_instance_id}")
            else:
                self.logger.info(f"Don't have tree {tree_id} locally")

            # CONTROLLED FLOODING: Forward with decremented TTL
            new_ttl = ttl - 1
            if new_ttl > 0:
                # Create forwarded message with decremented TTL
                forwarded_msg = f"TREE_BUILD_INVALIDATION {tree_id} {tree_instance_id} {new_ttl}".encode()
                
                ports = self.thread_manager.get_ports()
                forwarded_count = 0
                
                for port_id, port in ports.items():
                    # Skip the port the message came from and only send to connected ports
                    if (port_id != from_port_id and 
                        port.protocol_instance and 
                        port.protocol_instance.link_state == LinkProtocol.LinkState.CONNECTED):
                        
                        self.logger.info(f"Forwarding invalidation {invalidation_id} to port {port_id} with TTL={new_ttl}")
                        await self._send_on_port(port_id, forwarded_msg)
                        forwarded_count += 1
                
                self.logger.info(f"Forwarded invalidation to {forwarded_count} ports")
            else:
                self.logger.info(f"TTL would be 0 - not forwarding invalidation {invalidation_id}")
                        
        except Exception as e:
            self.logger.error(f"Error handling TREE_BUILD_INVALIDATION: {e}", exc_info=True)          
    async def _monitor_ports(self):
        """Monitor ports for events (simplified debug version)"""
        self.logger.info("Port monitoring started")
        
        # Do one-time queue inspection
        if not hasattr(self, '_queue_inspected'):
            self._queue_inspected = True
            await self._inspect_queue_methods()
        
        loop_count = 0
        
        while self.running:
            loop_count += 1
            if loop_count % 1000 == 0:  # Log every 1000 iterations
                self.logger.debug(f"Monitor loop iteration {loop_count}")
                
            ports = self.thread_manager.get_ports()
            
            for portid, port in ports.items():
                # Check signal queue first
                try:
                    # Use the original pattern but with better exception handling
                    signal = port.io.signal_q.get()
                    if signal is not None and signal != b'':
                        # Log the signal
                        self.logger.info(f"*** SIGNAL RECEIVED on port {portid}: {signal}")
                        await self.link_events.put({
                            'type': signal.decode(),
                            'port_id': portid,
                            'timestamp': time.time()
                        })
                except Exception as e:
                    if "Empty" not in str(e) and "empty" not in str(e) and "timeout" not in str(e).lower():
                        self.logger.debug(f"Signal queue exception on port {portid}: {e}")
                    
                # Check read queue
                try:
                    data = port.io.read_q.get()
                    
                    self.logger.info(f"*** DATA RECEIVED on port {portid}: {data[:50]}...")
                    event = {'data': data, 'port_id': portid}
                    
                    if data.startswith(b'TREE_BUILD_INVALIDATION'):
                        self.logger.info(f"Routing TREE_BUILD_INVALIDATION to tree_events from port {portid}")
                        await self.tree_events.put(event)
                    elif data.startswith(b'TREE_BUILD_ACK'):
                        self.logger.info(f"Routing TREE_BUILD_ACK to tree_events from port {portid}")
                        await self.tree_events.put(event)
                    elif data.startswith(b'TREE_BUILD'):
                        self.logger.info(f"Routing TREE_BUILD to tree_events from port {portid}")
                        await self.tree_events.put(event)
                    elif data.startswith(b'DATA_MESSAGE'):
                        self.logger.info(f"Routing DATA_MESSAGE to message_events from port {portid}")
                        await self.message_events.put(event)
                    else:
                        self.logger.info(f"Routing unknown message to link_events from port {portid}: {data[:20]}")
                        event['type'] = 'UNKNOWN_MESSAGE'
                        event['timestamp'] = time.time()
                        await self.link_events.put(event)
                except Exception as e:
                    # Only log if it's not a simple "empty queue" error
                    if "Empty" not in str(e) and "empty" not in str(e):
                        self.logger.debug(f"Read queue exception on port {portid}: {e}")
            
            await asyncio.sleep(0.01)  # Small yield

    async def _inspect_queue_methods(self):
        """One-time inspection of queue methods"""
        ports = self.thread_manager.get_ports()
        if ports:
            port_id, port = next(iter(ports.items()))
            
            self.logger.info(f"=== QUEUE INSPECTION for port {port_id} ===")
            self.logger.info(f"signal_q type: {type(port.io.signal_q)}")
            self.logger.info(f"signal_q methods: {[m for m in dir(port.io.signal_q) if not m.startswith('_')]}")
            
            # Test if queue has data checking methods
            if hasattr(port.io.signal_q, 'qsize'):
                self.logger.info(f"signal_q size: {port.io.signal_q.qsize()}")
            if hasattr(port.io.signal_q, 'empty'):
                self.logger.info(f"signal_q empty: {port.io.signal_q.empty()}")
                
            self.logger.info("=== END QUEUE INSPECTION ===")         
                    
                    
    async def _send_on_port(self, port_id: str, data: bytes):
        """Send data on specific port (debug version)"""
        self.logger.info(f"Attempting to send data on port {port_id}: {data[:100]}...")
        
        ports = self.thread_manager.get_ports()
        self.logger.info(f"Available ports: {list(ports.keys())}")
        
        if port_id in ports:
            port = ports[port_id]
            self.logger.info(f"Port {port_id} found - putting data in write queue")
            
            try:
                port.io.write_q.put(data)  # This should not be awaited
                self.logger.info(f"Successfully queued data for port {port_id}")
                await asyncio.sleep(0)  # Yield to allow sending
            except Exception as e:
                self.logger.error(f"Error sending data on port {port_id}: {e}")
        else:
            available_ports = list(ports.keys())
            self.logger.warning(f"Port {port_id} not found for sending. Available ports: {available_ports}")
                    
    
            
    def stop(self):
        """Stop the agent thread"""
        self.logger.info("Stopping Agent")
        self.running = False
        
    
    
    async def _handle_data_message(self, event):
        """Handle data message routing"""
        self.logger.info(f"Handling data message: {event['data']}")
        # TODO: Implement data message routing logic
        pass

    async def _handle_tiktyktik(self, event):
        """Handle TIKTYKTIK messages (future implementation)"""
        self.logger.info(f"Received TIKTYKTIK message: {event}")
        # TODO: Implement TIKTYKTIK protocol
        pass
    async def _handle_disconnected(self, event):
        """Handle disconnection (fixed version with proper error handling)"""
        port_id = event['port_id']
        self.logger.info(f"🔴 === HANDLING DISCONNECTION for port {port_id} on {self.node_id} ===")
        
        try:
            async with self.state_lock:
                # Clean up neighbors
                if port_id in self.neighbors:
                    self.logger.info(f"Removing neighbor info for port {port_id}")
                    del self.neighbors[port_id]
                
                # Find trees that need invalidation
                trees_to_invalidate = []
                for tree_id, tree_entry in self.trees.items():
                    if tree_entry.rootward_portid == port_id:
                        trees_to_invalidate.append(tree_id)
                        self.logger.info(f"Tree {tree_id} needs invalidation (rootward port {port_id} disconnected)")
                
                # Prepare invalidation messages and clean up trees
                invalidation_tasks = []
                for tree_id in trees_to_invalidate:
                    try:
                        tree_entry = self.trees[tree_id]
                        
                        # NEW: Create invalidation message with TTL
                        invalidation_msg = f"TREE_BUILD_INVALIDATION {tree_id} {tree_entry.tree_instance_id} {self.invalidation_ttl}".encode()
                        invalidation_id = f"{tree_id}:{tree_entry.tree_instance_id}"
                        
                        # Mark as seen to prevent processing our own invalidation
                        self.seen_invalidations.add(invalidation_id)
                        
                        # FIXED: Send invalidation to ALL connected ports except the failed one
                        ports = self.thread_manager.get_ports()
                        for check_port_id, port in ports.items():
                            # Skip the failed port and only send to connected ports
                            if (check_port_id != port_id and 
                                port.protocol_instance and 
                                port.protocol_instance.link_state == LinkProtocol.LinkState.CONNECTED):
                                
                                invalidation_tasks.append((check_port_id, invalidation_msg))
                                self.logger.info(f"Will send invalidation {invalidation_id} to port {check_port_id} with TTL={self.invalidation_ttl}")
                        
                        # Remove the tree
                        del self.trees[tree_id]
                        self.logger.info(f"✅ Invalidated tree {tree_id} due to port {port_id} disconnection")
                        
                    except Exception as e:
                        self.logger.error(f"Error processing tree {tree_id} for invalidation: {e}")
                    
                # Clean up port paths
                if port_id in self.port_paths:
                    self.logger.info(f"Removing port path for {port_id}")
                    del self.port_paths[port_id]
            
            # Send invalidations outside the lock to avoid deadlock
            self.logger.info(f"Sending {len(invalidation_tasks)} invalidation messages")
            
            for port, msg in invalidation_tasks:
                try:
                    self.logger.info(f"Sending invalidation to port {port}: {msg[:50]}...")
                    await self._send_on_port(port, msg)
                    self.logger.info(f"✅ Successfully sent invalidation to port {port}")
                except Exception as e:
                    self.logger.error(f"❌ Failed to send invalidation to port {port}: {e}")
                    # Continue with other invalidations even if one fails
            
            self.logger.info(f"🔴 === FINISHED HANDLING DISCONNECTION for port {port_id} on {self.node_id} ===")
            
        except Exception as e:
            self.logger.error(f"❌ CRITICAL ERROR in _handle_disconnected for port {port_id}: {e}", exc_info=True)
            # Log the current state for debugging
            self.logger.error(f"Current trees: {list(self.trees.keys())}")
            self.logger.error(f"Current neighbors: {list(self.neighbors.keys())}")
            self.logger.error(f"Current port_paths: {list(self.port_paths.keys())}")
            
            # Don't re-raise - we want the agent to continue running
            # but log that disconnection handling failed
    async def _handle_connected(self, event):
        """Handle port connection event (enhanced debug version)"""
        port_id = event['port_id']
        self.logger.info(f"🔥 === HANDLING CONNECTION EVENT for port {port_id} on {self.node_id} ===")
        
        # Show current state BEFORE processing
        self.logger.info(f"Current trees BEFORE connection: {list(self.trees.keys())}")
        self.logger.info(f"Self tree exists: {self.node_id in self.trees}")
        
        base_delay = hash(self.node_id) % 5  # 0-4 seconds based on node_xid
        jitter = random.uniform(0.5, 1.5)
        total_delay = jitter + base_delay
        
        self.logger.info(f"⏱️ Waiting {total_delay:.2f} seconds before processing connection...")
        await asyncio.sleep(total_delay)
        
        self.logger.info(f"✅ Port {port_id} connected - processing now")
        
        async with self.state_lock:
            self.logger.info(f"Current trees AFTER delay: {list(self.trees.keys())}")
            
            if self.node_id not in self.trees:
                tree_instance_id = str(uuid.uuid4())
                self.trees[self.node_id] = TreeEntry(
                    rootward_portid="",
                    hops=0,
                    tree_instance_id=tree_instance_id,
                    leafward_portids=[]
                )
                self.logger.info(f"🌳 Created NEW tree rooted at cell {self.node_id} with instance {tree_instance_id}")
                should_broadcast = True
            else:
                existing_tree = self.trees[self.node_id] 
                self.logger.info(f"🌳 Tree for {self.node_id} already exists: {existing_tree}")
                should_broadcast = False
                
            self.logger.info(f"📡 Should broadcast: {should_broadcast}")
                
            if should_broadcast:
                current_neighbors = self._get_current_neighbors()
                self.logger.info(f"👥 Current neighbors for broadcast: {current_neighbors}")
                
                tb_packet = TreeBuild(
                    tree_id=self.node_id,
                    tree_instance_id=self.trees[self.node_id].tree_instance_id,
                    hops=0,
                    neighbors=current_neighbors
                )
                
                self.logger.info(f"📦 Created TREE_BUILD packet: {tb_packet}")
                packet_bytes = tb_packet.to_bytes()
                self.logger.info(f"📦 Packet bytes: {packet_bytes}")
                
                ports = self.thread_manager.get_ports()
                broadcast_count = 0
                
                for pid, port in ports.items():
                    port_state = "UNKNOWN"
                    if port.protocol_instance:
                        port_state = port.protocol_instance.link_state
                    
                    self.logger.info(f"🔍 Checking port {pid}: protocol_instance={port.protocol_instance is not None}, link_state={port_state}")
                    
                    if (port.protocol_instance and 
                        port.protocol_instance.link_state == LinkProtocol.LinkState.CONNECTED):
                        
                        self.logger.info(f"📡 Broadcasting TREE_BUILD to connected port {pid}")
                        await self._send_on_port(pid, packet_bytes)
                        broadcast_count += 1
                    else:
                        self.logger.info(f"⏭️ Skipping port {pid} - not connected (state: {port_state})")
                
                self.logger.info(f"📡 Broadcasted TREE_BUILD to {broadcast_count} ports")
            else:
                self.logger.info("🚫 No broadcast needed - tree already exists")
        
        self.logger.info(f"🔥 === FINISHED HANDLING CONNECTION for port {port_id} on {self.node_id} ===")

    def get_snapshot(self):
        """Get a comprehensive snapshot for DAG construction (thread-safe version)"""
        
        # Use a copy of trees to avoid race conditions with invalidation
        # This ensures we get a consistent snapshot even if trees are being modified
        current_trees = dict(self.trees)  # Create a copy
        current_neighbors = dict(self.neighbors)  # Create a copy
        current_port_paths = dict(self.port_paths)  # Create a copy
        
        # Fix tree serialization with current state
        trees_dict = {}
        for tree_id, tree_entry in current_trees.items():
            trees_dict[tree_id] = {
                'rootward_portid': tree_entry.rootward_portid,
                'hops': tree_entry.hops,
                'tree_instance_id': tree_entry.tree_instance_id,
                'leafward_portids': list(tree_entry.leafward_portids),  # Create copy
                'is_root': tree_entry.rootward_portid == "",
                'children_count': len(tree_entry.leafward_portids),
                'status': 'active'  # Add status field
            }
        
        # Build components in correct order with current state
        topology_info = self._build_topology_view(current_trees, current_neighbors)
        neighbor_info = self._build_neighbor_summary(current_trees, current_neighbors)
        routing_tables = self._build_routing_tables(current_trees, topology_info)
        network_graph = self._build_network_graph(current_trees, neighbor_info)
        
        # Add timestamp and state info
        snapshot_time = time.time()
        
        return {
            'node_id': self.node_id,
            'timestamp': snapshot_time,
            'trees': trees_dict,
            'trees_count': len(trees_dict),
            'port_paths': {tree_id: tree.serialize() for tree_id, tree in current_port_paths.items()},
            'topology': topology_info,
            'routing_tables': routing_tables, 
            'neighbors': neighbor_info,
            'network_graph': network_graph,
            'dag_metadata': self._build_dag_metadata(current_trees, current_neighbors),
            
            # Add state tracking for debugging
            'invalidation_state': {
                'seen_invalidations_count': len(getattr(self, 'seen_invalidations', set())),
                'recent_invalidations': list(getattr(self, 'seen_invalidations', set()))[-10:],  # Last 10
            },
            'agent_state': {
                'running': self.running,
                'link_events_pending': getattr(self.link_events, '_qsize', lambda: 0)(),
                'tree_events_pending': getattr(self.tree_events, '_qsize', lambda: 0)(),
                'message_events_pending': getattr(self.message_events, '_qsize', lambda: 0)(),
            }
        }

    def _build_topology_view(self, current_trees, current_neighbors):
        """Build complete topology view from this node's perspective"""
        topology = {
            'direct_connections': {},  # port_id -> neighbor_cell_id
            'reachable_nodes': set(),  # all nodes reachable via any tree
            'tree_roots': list(current_trees.keys())
        }
        
        # Extract direct connections from ports
        ports = self.thread_manager.get_ports()
        for port_id, port in ports.items():
            if (port.protocol_instance and 
                port.protocol_instance.link_state == LinkProtocol.LinkState.CONNECTED):
                
                neighbor_info = getattr(port.protocol_instance, 'neighbor_portid', None)
                if neighbor_info:
                    neighbor_cell = neighbor_info.split(':')[0]
                    topology['direct_connections'][port_id] = neighbor_cell
                    topology['reachable_nodes'].add(neighbor_cell)
        
        # Add all tree roots as reachable nodes (this represents the full network)
        for tree_id in current_trees.keys():
            topology['reachable_nodes'].add(tree_id)
        
        # Convert set to list for JSON serialization
        topology['reachable_nodes'] = list(topology['reachable_nodes'])
        return topology

    def _build_neighbor_summary(self, current_trees, current_neighbors):
        """Summarize neighbor information for DAG construction"""
        neighbor_summary = {
            'immediate_neighbors': [],
            'neighbor_details': {},
            'connectivity_matrix': {},
            'tree_neighbors': {}  # neighbors learned via trees
        }
        
        # Direct neighbors from ports
        ports = self.thread_manager.get_ports()
        for port_id, port in ports.items():
            if (port.protocol_instance and 
                port.protocol_instance.link_state == LinkProtocol.LinkState.CONNECTED):
                
                neighbor_info = getattr(port.protocol_instance, 'neighbor_portid', None)
                if neighbor_info:
                    neighbor_cell = neighbor_info.split(':')[0]
                    neighbor_port = neighbor_info.split(':')[1]
                    
                    if neighbor_cell not in neighbor_summary['immediate_neighbors']:
                        neighbor_summary['immediate_neighbors'].append(neighbor_cell)
                    
                    neighbor_summary['neighbor_details'][neighbor_cell] = {
                        'connected_via_port': port_id,
                        'neighbor_port': neighbor_port,
                        'link_state': 'connected',
                        'connection_type': 'direct'
                    }
        
        # Add neighbors learned via spanning trees
        for tree_id, tree_entry in current_trees.items():
            if tree_id != self.node_id:  # Don't include ourselves
                neighbor_summary['tree_neighbors'][tree_id] = {
                    'hops_away': tree_entry.hops,
                    'next_hop_port': tree_entry.rootward_portid,
                    'tree_instance': tree_entry.tree_instance_id,
                    'is_direct': tree_entry.hops == 1
                }
        
        # Build connectivity matrix between all known nodes
        all_known_nodes = set(neighbor_summary['immediate_neighbors'])
        all_known_nodes.update(neighbor_summary['tree_neighbors'].keys())
        all_known_nodes.add(self.node_id)
        
        for node in all_known_nodes:
            neighbor_summary['connectivity_matrix'][node] = {
                'reachable': True,
                'hops': 0 if node == self.node_id else neighbor_summary['tree_neighbors'].get(node, {}).get('hops_away', float('inf')),
                'via_tree': node in neighbor_summary['tree_neighbors']
            }
        
        return neighbor_summary

    def _build_routing_tables(self, current_trees, topology_info):
        """Build routing tables for each tree"""
        routing_tables = {}
        
        for tree_id, tree_entry in current_trees.items():
            routing_tables[tree_id] = {
                'to_root': {
                    'next_hop_port': tree_entry.rootward_portid,
                    'hops_to_root': tree_entry.hops,
                    'path_to_root': []  # Could extract from port_paths
                },
                'leafward_routes': {}
            }
            
            # Add routes to children
            for child_port in tree_entry.leafward_portids:
                if child_port in topology_info['direct_connections']:
                    child_node = topology_info['direct_connections'][child_port]
                    routing_tables[tree_id]['leafward_routes'][child_node] = {
                        'next_hop_port': child_port,
                        'hops': 1
                    }
        
        return routing_tables

    def _build_network_graph(self, current_trees, neighbor_info):
        """Build network graph structure for frontend"""
        graph = {
            'nodes': [self.node_id],
            'edges': [],
            'adjacency_list': {self.node_id: []}
        }
        
        # Add all known nodes (immediate + tree neighbors)
        all_neighbors = set(neighbor_info['immediate_neighbors'])
        all_neighbors.update(neighbor_info.get('tree_neighbors', {}).keys())
        
        for neighbor in all_neighbors:
            if neighbor not in graph['nodes']:
                graph['nodes'].append(neighbor)
        
        # Add direct connection edges
        for neighbor in neighbor_info['immediate_neighbors']:
            edge = {
                'source': self.node_id,
                'target': neighbor,
                'type': 'physical_link',
                'weight': 1
            }
            graph['edges'].append(edge)
            
            if self.node_id not in graph['adjacency_list']:
                graph['adjacency_list'][self.node_id] = []
            graph['adjacency_list'][self.node_id].append(neighbor)
        
        # Add tree-based connections (logical topology)
        for tree_neighbor, tree_info in neighbor_info.get('tree_neighbors', {}).items():
            if tree_info['hops_away'] == 1:  # Direct tree connections
                # Only add if not already a physical link
                existing_edge = any(
                    (edge['source'] == self.node_id and edge['target'] == tree_neighbor) or
                    (edge['source'] == tree_neighbor and edge['target'] == self.node_id)
                    for edge in graph['edges']
                )
                
                if not existing_edge:
                    edge = {
                        'source': self.node_id,
                        'target': tree_neighbor,
                        'type': 'tree_link',
                        'weight': tree_info['hops_away']
                    }
                    graph['edges'].append(edge)
        
        return graph

    def _build_dag_metadata(self, current_trees, current_neighbors):
        """Metadata specifically for DAG construction"""
        neighbor_summary = self._build_neighbor_summary(current_trees, current_neighbors)
        
        return {
            'total_trees': len(current_trees),
            'root_trees': [tid for tid, tree in current_trees.items() if tree.rootward_portid == ""],
            'leaf_trees': [tid for tid, tree in current_trees.items() if not tree.leafward_portids],
            'tree_depths': {tid: tree.hops for tid, tree in current_trees.items()},
            'connectivity_degree': len(neighbor_summary['immediate_neighbors']),
            'tree_connectivity_degree': len(neighbor_summary.get('tree_neighbors', {})),
            'total_known_nodes': len(current_trees),
            'routing_complexity': sum(len(tree.leafward_portids) for tree in current_trees.values()),
            'network_diameter': max([tree.hops for tree in current_trees.values()], default=0),
            'is_network_complete': len(current_trees) >= 4,
            
            # Add real-time state
            'snapshot_consistency': {
                'trees_active': len(current_trees),
                'neighbors_connected': len([n for n in neighbor_summary['immediate_neighbors']]),
                'last_tree_change': getattr(self, '_last_tree_change', time.time())
            }
        }