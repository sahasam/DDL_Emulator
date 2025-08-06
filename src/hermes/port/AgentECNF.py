import random
import logging
import time
from typing import List, Any, Optional
import uuid
import asyncio
from collections import deque
from dataclasses import dataclass
from hermes.model.messages import TreeBuild, TreeBuildAck, TreeEntry
from hermes.model.trees import PathTree
from hermes.port.protocol import LinkProtocol
from hermes.sim.ThreadManager import ThreadManager
import json
from hermes.sim.FSPStateColors import *

@dataclass
class DataPacket:
    """Generic data packet for network messaging"""
    source_id: str
    destination_id: str
    payload: Any
    message_id: str = None
    ttl: int = 10
    timestamp: float = None
    
    def __post_init__(self):
        if self.message_id is None:
            self.message_id = str(uuid.uuid4())
        if self.timestamp is None:
            self.timestamp = time.time()
    
    def to_bytes(self) -> bytes:
        data = {
            'source_id': self.source_id,
            'destination_id': self.destination_id,
            'payload': self.payload,
            'message_id': self.message_id,
            'ttl': self.ttl,
            'timestamp': self.timestamp
        }
        return f"DATA_PACKET {json.dumps(data)}".encode()
    
    @classmethod
    def from_bytes(cls, data: bytes):
        json_str = data.decode().replace("DATA_PACKET ", "", 1)
        parsed = json.loads(json_str)
        return cls(**parsed)


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
        self.logger.disabled = True

        self.thread_manager = thread_manager
        self.node_id = node_id

        self.trees = {}
        self.port_paths = {}
        self.running = False

        self.neighbors = {}  # 1 hop away

        self.link_events = asyncio.Queue()  # for establishing connections and TIKTYKTIK
        self.tree_events = asyncio.Queue()  # for tree build events
        self.message_events = asyncio.Queue()  # for DATA messages
        
        #TODO: remove fsp functionality later...
        self.fsp_events = asyncio.Queue()

        self.state_lock = asyncio.Lock()  # Lock for managing shared state
        self.message_inbox = deque(maxlen=1000)  # Limit size to prevent memory issues
        self.seen_invalidations = set()  # processed invalidation
        self.invalidation_ttl = 10  # max hops

        self._last_tree_change = time.time()
        self.message_handlers = {}
        self.fsp_context = {}
        

    def register_handler(self, message_type, handler_func):
        """Registers a handler for a specific message type"""
        self.message_handlers[message_type] = handler_func
        self.logger.info('Registered handler for message type: %s', message_type)
        
    def unregister_handler(self, message_type):
        """Unregister handler for message type"""
        if message_type in self.message_handlers:
            del self.message_handlers[message_type]
            self.logger.info('Unregistered handler for message type: %s', message_type)
            
        
    async def run(self):
        self.logger.info("Starting Agent")
        self.running = True
        ports = self.thread_manager.get_ports()

        for port_id, port in ports.items():
            if port.protocol_instance:
                state = port.protocol_instance.link_state
                self.logger.info(f"📡 Port {port_id} initial state: {state}")
            else:
                self.logger.info(f"📡 Port {port_id} has no protocol instance yet")

        if self.node_id in self.trees:
            self.logger.warning(
                f"⚠️ Tree for {self.node_id} already exists at startup: {self.trees[self.node_id]}"
            )
        else:
            self.logger.info(
                f"✅ No tree exists for {self.node_id} at startup (expected)"
            )

        tasks = [
            asyncio.create_task(
                self._handle_link_events()
            ),  # handles CONNECTED, DISCONNECTED, and TIKTYKTIK messages
            asyncio.create_task(
                self._handle_tree_events()
            ),  # handles TREE_BUILD and TREE_BUILD_ACK messages
            asyncio.create_task(
                self._handle_message_events()
            ),  # handles DATA messages
            asyncio.create_task(
                self._monitor_ports()
            ),  # provides information on events
            asyncio.create_task(
                self._handle_fsp_events()
            ) # TODO: remove this upon fms-- this utilizes the previous solution to monitor fsp events.
        ]
        try:
            await asyncio.gather(*tasks)

        except Exception as e:
            self.logger.error(f"Agent encountered an error: {e}", exc_info=True)

        finally:
            self.running = False
    
    # START OF FIRING SQUAD METHODS +====  
    async def _handle_fsp_events(self):
        """Handles FSP-related events """
        while self.running:
            event = await self.fsp_events.get()
            
            if event["data"].startswith(b"FSP_ACTIVATE"):
                await self._handle_fsp_activate(event)
            elif event["data"].startswith(b"FSP_ACTIVATE_ACK"):
                await self._handle_fsp_activate_ack(event)
            elif event["data"].startswith(b"FSP_STATE"):
                await self._handle_fsp_state_request(event)
            elif event["data"].startswith(b"FSP_STATE_ACK"):
                await self._handle_fsp_state_ack(event)
    
    async def _handle_fsp_activate(self, event):
        """Parses the FSP_ACTIVATE and forwards + tracks position"""
        parts = event["data"].decode().split()
        position = int(parts[1]) if len(parts) > 1 else 1
        from_port = event["port_id"]
        self.logger.info(f"FSP_ACTIVATE received: position: {position}")
        
        self.fsp_context = {
            'position': position,
            'right_port': None
        }
        if position == 1:
            self.fsp_context['left_port'] = None
        else:
            self.fsp_context['left_port'] = from_port
            
        
        next_port = self._get_other_connected_port(from_port)
        if next_port:
            self.fsp_context['right_port'] = next_port
            
            forward_message = f"FSP_ACTIVATE {position + 1}"
            await self._send_on_port(next_port, forward_message.encode())
            self.logger.info(f"Forwarded FSP_ACTIVATE to position {position + 1}")
        else:
            # this is the last on the chain
            ack_message = f"FSP_ACTIVATE_ACK {position}"
            self.fsp_context.update({
                'timestep': 0,
                'active': True,
                'max_time': (2 * position) - 2,
                'state': Q,
            })
            self.fsp_context['neighbors_ready'] = {
                    'left': False,
                    'right': True
            }
            
            await self._send_on_port(from_port, ack_message.encode())
            self.logger.info(f"Last cell  sending FSP_ACTIVATE_ACK with chain length {position}")

    async def _handle_fsp_activate_ack(self, event):
        """Handles FSP_ACTIVATE_ACK, which will ripple back. this WILL assign a default state to the cell (agent is an attribute of cell). assumes linear topology is in place"""
        parts = event["data"].decode().split()
        chain_length = int(parts[1]) if len(parts) > 1 else 1 
        from_port = event["port_id"]
        
        self.logger.info(f"FSP_ACTIVATE_ACK received: chain length is {chain_length}")

        if self.fsp_context['position'] == 1:
            initial_state = P0
            self.logger.info(f"General at pos {self.fsp_context['position']} set with state P0")
        else:
            initial_state = Q
            self.logger.info(f"Soldier at pos {self.fsp_context['position']} set with state Q")
        
        self.fsp_context.update({
            'timestep': 0,
            'state': initial_state,
            'active': True,
            'max_time': (2 * chain_length) - 2,
            'chain_length': chain_length
        })
    
        
        self.fsp_context['neighbors_ready'] = {}

        if self.fsp_context['left_port'] is not None:
            self.fsp_context['neighbors_ready']['left'] = False  # Waiting for left neighbor's state
        
        if self.fsp_context['right_port'] is not None:
            self.fsp_context['neighbors_ready']['right'] = False
            
        if self.fsp_context['position'] > 1:
        # Forward ACK back to left neighbor
            await self._send_on_port(self.fsp_context['left_port'], event["data"])
            self.logger.info(f"Forwarded FSP_ACTIVATE_ACK toward General")
        else:
            # We are the general - chain fully activated, start handshake!
            self.logger.info(f"General: Chain fully activated! Starting FSP handshake...")
            
        
        self.fsp_tables = self._load_fsp_tables(self.fsp_context['chain_length'])
        self.transition_lock = asyncio.Lock()
        
        await self._request_all_neighbor_states()
 
        
        
      
    async def _handle_fsp_state_request(self, event):
        """Handle neighbor asking for my state - wait for timestep completion"""
        parts = event["data"].decode().split() 
        requested_timestep = int(parts[1])
        from_port = event["port_id"]

        # need to put the shitter asyncio.Events()
        self.logger.info(f"FSP_STATE request from port {from_port} for timestep {requested_timestep}")           

        # handle <= --> <
        if self.fsp_context['timestep'] <= requested_timestep:
            await self._send_fsp_state_ack(from_port, requested_timestep)
            self.logger.info(f"Sent FSP_STATE_ACK to port {from_port}")   
        else:
            # We're ahead - this is an error but respond anyway
            self.logger.warning(f"Received request for T{requested_timestep} but we're at T{self.fsp_context['timestep']}")
            await self._send_fsp_state_ack(from_port, self.fsp_context['timestep'])
    
    async def _send_fsp_state_ack(self, from_port, timestep):
        """Send FSP_STATE_ACK with our current state to the requesting port"""
        current_state = self.fsp_context['state']
        ack_message = f"FSP_STATE_ACK {timestep} {current_state}"
        
        await self._send_on_port(from_port, ack_message.encode())
        self.logger.info(f"Sent FSP_STATE_ACK: T{timestep}, state={self.fsp_context.get("state", 'UNK')} to port {from_port}") 
        
    async def _handle_fsp_state_ack(self, event):
        """Handles FSP_STATE_ACK responses from neighbors"""
        parts = event["data"].decode().split()
        ack_timestep = int(parts[1])
        neighbor_state = int(parts[2])
        from_port = event["port_id"]
        
        self.logger.info(f"FSP_STATE_ACK from port {from_port}: T{ack_timestep}, state={neighbor_state}")

        if from_port == self.fsp_context['left_port']:
            neighbor_direction = 'left'
        elif from_port == self.fsp_context['right_port']:
            neighbor_direction = 'right'
        else:
            self.logger.warning(f"Received FSP_STATE_ACK from unknown port {from_port}")
            return
        
        if ack_timestep != self.fsp_context['timestep']:
            self.logger.warning(f"️Received ACK for T{ack_timestep} but expecting T{self.fsp_context['timestep']}")
            return
        
        if 'neighbor_states' not in self.fsp_context:
            self.fsp_context['neighbor_states'] = {}
        self.fsp_context['neighbor_states'][neighbor_direction] = neighbor_state
        
        if all(self.fsp_context['neighbors_ready'].values()):
            self.logger.info(f"All neighbors ready for T{self.fsp_context['timestep']} - advancing!")
            await self._advance_timestep()
        else:
            missing = [direction for direction, ready in self.fsp_context['neighbors_ready'].items() if not ready]
            self.logger.info(f"Still waiting for: {missing}")
        
        
    async def _advance_timestep(self):
        """Advance FSP state by one time step"""

        async with self.transition_lock:
            left_state = self._get_neighbor_state('left')
            right_state = self._get_neighbor_state('right')

            old_state = self.fsp_context['state']
            
            self.logger.info(f"🔍 {self.node_id} T{self.fsp_context['timestep']} transition input:")  
            self.logger.info(f"    - Left:  ({statename.get(left_state, 'UNK')})")
            self.logger.info(f"    - Current:  ({statename.get(old_state, 'UNK')})")
            self.logger.info(f"    - Right: ({statename.get(right_state, 'UNK')})")

            new_state = self._apply_fsp_transition(left_state, old_state, right_state) 

            self.logger.info(f"    - Result: ({new_state})")

            
        if new_state != old_state:
            self.fsp_context['state'] = new_state  
            self.logger.info(f"🔄 FSP {self.node_id} T{self.fsp_context['timestep']}: {statename.get(old_state, 'UNK')} → {statename.get(new_state, 'UNK')}")
        
        self.fsp_context['timestep'] += 1 
        
        for direction in self.fsp_context['neighbors_ready']:
            self.fsp_context['neighbors_ready'][direction] = False
            
        if self.fsp_context['timestep'] < self.fsp_context['max_time']:
            await self._request_all_neighbor_states()
        else:
            await self._check_fsp_completion()
    
    async def _check_fsp_completion(self):
        """Check FSP completion and report results"""
        if self.fsp_context['timestep'] >= self.fsp_context['max_time']:
            if self.fsp_state == T:
                self.logger.info(f"🔥🔥🔥 CELL {self.cell_id} FIRED SUCCESSFULLY! 🔥🔥🔥")
                # needs a fix here for cleanup for general
                self.am_general = False
                
            else:
                self.logger.info(f"⚠️ FSP completed but {self.cell_id} did not fire. Final state: {statename.get(self.fsp_state, 'UNK')}")
        else:
            self.logger.info(f"⏹️ FSP stopped early at time {self.fsp_time_step}")
        
        self.fsp_active = False
    
    def _get_neighbor_state(self, direction):
        """Get neighbor state from handshake data"""
        if 'neighbor_states' not in self.fsp_context:
            return xx  # No neighbor data yet
            
        return self.fsp_context['neighbor_states'].get(direction, xx)
        
        
    
    def _apply_fsp_transition(self, left_state, current_state, right_state):
        """Apply Wakesman FSP transition rules"""
        if not self.fsp_tables:
            return current_state
        
        prior = (left_state * 32) + right_state
        
        # Map states to table indices
        state_to_table = {
            Q: 0, R0: 1, R1: 2, P0: 3, P1: 4, B0: 5, B1: 6,
            A0: 7, A1: 8, A2: 9, A3: 10, A4: 11, A5: 12, A6: 13, A7: 14
        }
        
        if current_state in state_to_table:
            table_idx = state_to_table[current_state]
            return self.fsp_tables[table_idx].get(prior, Q)
        
        return current_state
    
    
    async def _request_all_neighbor_states(self):
        """Send FSP_STATE requests to all neighbors and reset readiness flags"""
        current_timestep = self.fsp_context['timestep']
        
        # Reset readiness flags - this creates the "block" until ACKs arrive
        for direction in self.fsp_context['neighbors_ready']:
            self.fsp_context['neighbors_ready'][direction] = False
        
        request_count = 0
        
        # Send request to left neighbor if exists
        if self.fsp_context['left_port'] is not None:
            request_msg = f"FSP_STATE {current_timestep}"
            await self._send_on_port(self.fsp_context['left_port'], request_msg.encode())
            self.logger.info(f"📤 Sent FSP_STATE request to LEFT neighbor for T{current_timestep}")
            request_count += 1
            
        # Send request to right neighbor if exists  
        if self.fsp_context['right_port'] is not None:
            request_msg = f"FSP_STATE {current_timestep}"
            await self._send_on_port(self.fsp_context['right_port'], request_msg.encode())
            self.logger.info(f"📤 Sent FSP_STATE request to RIGHT neighbor for T{current_timestep}")
            request_count += 1
        
        if request_count == 0:
            # No neighbors - can advance immediately (shouldn't happen in chain)
            self.logger.info(f"⚠️ No neighbors to request from - advancing immediately")
            await self._advance_fsp_state()
        else:
            self.logger.info(f"🚫 BLOCKED: Waiting for {request_count} neighbor ACKs for T{current_timestep}")
        
     
    # END OF FIRING SQUAD METHODS =========   

        
        
    def _get_other_connected_port(self, exclude_port):
        """This method ASSUMES a linear topology. It will return the next port not excluded, else None."""
        ports = self.thread_manager.get_ports()
        for port_id, port in ports.items():
            if (port_id != exclude_port and 
            port.protocol_instance and 
            port.protocol_instance.link_state == LinkProtocol.LinkState.CONNECTED):
                return port_id
        return None
                

    async def _handle_tree_events(self):
        """Handle tree-related packets like TREE_BUILD and TREE_BUILD_ACK"""
        while self.running:
            try:
                event = await self.tree_events.get()

                if event["data"].startswith(b"TREE_BUILD "):
                    await self._handle_tree_build(event)
                elif event["data"].startswith(b"TREE_BUILD_ACK "):
                    await self._handle_tree_build_ack(event)
                elif event["data"].startswith(b"TREE_BUILD_INVALIDATION "):
                    await self._handle_tree_invalidation(event)

            except:
                self.logger.error("Error handling tree events", exc_info=True)

    async def _handle_tree_build_ack(self, event):
        """Handles TREE_BUILD_ACK messages from other node"""
        try:
            ack_packet = TreeBuildAck.from_bytes(event["data"])
            port_id = event["port_id"]

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
            neighbors=ack_packet.neighbors + self._get_current_neighbors(),
        )

        await self._send_on_port(tree_entry.rootward_portid, forwarded_ack.to_bytes())

    async def _update_neighbor_info(self, port_id: str, neighbor_list: List[str]):
        """Update our knowledge of what neighbors this port can reach (LOV)"""

        # Store neighbor information for this port
        if port_id not in self.neighbors:
            self.neighbors[port_id] = {}

        self.neighbors[port_id].update(
            {
                "reachable_neighbors": neighbor_list,
                "last_updated": time.time(),
                "hop_distance": 1,  # These are 1-hop neighbors via this port
            }
        )

        self.logger.info(f"Updated neighbor info for port {port_id}: {neighbor_list}")

    async def _handle_tree_build(self, event: TreeBuild):
        """Handle TREE_BUILD messages from other nodes."""

        tb_packet = TreeBuild.from_bytes(event["data"])
        port_id = event["port_id"]

        if await self._should_join_tree(tb_packet, port_id):
            await self._join_tree(tb_packet, port_id)
        else:
            self.logger.info(
                f"Ignoring TREE_BUILD for {tb_packet.tree_id} (already have better path)"
            )

    async def _join_tree(self, tb_packet: TreeBuild, port_id: str):
        """Join a tree and send ACK with our neighbor info (fixed version)"""

        async with self.state_lock:
            # Update our tree entry
            self.trees[tb_packet.tree_id] = TreeEntry(
                rootward_portid=port_id,
                hops=tb_packet.hops + 1,
                tree_instance_id=tb_packet.tree_instance_id,
                leafward_portids=[],
            )

            self.logger.info(f"Created tree entry: {self.trees[tb_packet.tree_id]}")

            # Send ACK back to parent with our neighbor information
            ack_packet = TreeBuildAck(
                tree_id=tb_packet.tree_id,
                tree_instance_id=tb_packet.tree_instance_id,
                hops=tb_packet.hops + 1,
                path=[port_id],  # Start path with our port to parent
                neighbors=self._get_current_neighbors(),  # Our neighbor list
            )

            await self._send_on_port(port_id, ack_packet.to_bytes())

            # Forward to other ports
            await self._forward_tree_build(tb_packet, port_id)

    async def _forward_tree_build(self, tb_packet: TreeBuild, exclude_port: str):
        """Forward TREE_BUILD packet to other ports, excluding the one we received it on"""

        forwarded_packet = TreeBuild(
            tree_id=tb_packet.tree_id,
            tree_instance_id=tb_packet.tree_instance_id,
            hops=tb_packet.hops + 1,
            neighbors=self._get_current_neighbors(),
        )

        self.logger.info(f"Forwarded packet: {forwarded_packet}")

        ports = self.thread_manager.get_ports()

        forwarded_count = 0
        for port_id, port in ports.items():
            
            if (
                port.port_id != exclude_port
                and port.protocol_instance
                and port.protocol_instance.link_state
                == LinkProtocol.LinkState.CONNECTED
            ):

                await self._send_on_port(port_id, forwarded_packet.to_bytes())
                forwarded_count += 1
            else:
                self.logger.info(
                    f"❌ Skipping port {port_id} - excluded or not connected"
                )

    def _get_current_neighbors(self):
        neighbors = []
        ports = self.thread_manager.get_ports()

        for port_id, port in ports.items():
            if (
                port.protocol_instance
                and port.protocol_instance.link_state
                == LinkProtocol.LinkState.CONNECTED
            ):
                # Extract neighbor cell ID from port connection
                neighbor_info = self.neighbors.get(port_id)
                if neighbor_info and "cell_id" in neighbor_info:
                    neighbors.append(neighbor_info["cell_id"])
                else:
                    neighbors.append(f"neighbor_via_{port_id}")

        return neighbors
    
    def _load_fsp_tables(self, chain_length):
        """Load Wakesman FSP transition tables"""
        try:
            import sys
            import os
            from hermes.sim.wakesman_fsp import process_csv_for_run
            
            # ADD DEBUGGING TO CHECK CONSTANTS:
            self.logger.info(f"🔍 Checking state constants:")
            self.logger.info(f"    Q={Q}, T={T}, P0={P0}, P1={P1}")
            self.logger.info(f"    B0={B0}, B1={B1}, R0={R0}, R1={R1}")
            self.logger.info(f"    A0={A0}, A1={A1}, A2={A2}, A3={A3}")
            self.logger.info(f"    A4={A4}, A5={A5}, A6={A6}, A7={A7}")
            self.logger.info(f"    xx={xx}")
            
            tables = process_csv_for_run(chain_length)
            
            # CHECK P0 TABLE ENTRIES:
            if tables and len(tables) > 3:
                p0_table = tables[3]  # P0 table is at index 3
                self.logger.info(f"🔍 P0 table has {len(p0_table)} entries")
                
                # Check for the specific transitions Alice should make:
                p0_left_p0_right = (P0 * 32) + P0  # Should give T
                p0_left_q_right = (P0 * 32) + Q    # Current Alice case
                p0_left_a2_right = (P0 * 32) + A2  # Current Alice case
                
                self.logger.info(f"    Key for (P0,P0,P0): {p0_left_p0_right} -> {p0_table.get(p0_left_p0_right, 'MISSING')}")
                self.logger.info(f"    Key for (P0,P0,Q): {p0_left_q_right} -> {p0_table.get(p0_left_q_right, 'MISSING')}")
                self.logger.info(f"    Key for (P0,P0,A2): {p0_left_a2_right} -> {p0_table.get(p0_left_a2_right, 'MISSING')}")
            
            return tables
        except ImportError as e:
            self.logger.info(f"⚠️ Could not load FSP tables: {e}")
            return None
    

    async def _should_join_tree(self, tb_packet: TreeBuild, port_id: str) -> bool:
        """Simplified tree joining logic - prioritize connectivity over optimization"""

        # First time seeing this tree - always join
        if tb_packet.tree_id not in self.trees:
            self.logger.info(
                f"SHOULD_JOIN: First time seeing tree {tb_packet.tree_id} - YES"
            )
            return True

        existing_tree = self.trees[tb_packet.tree_id]

        # Different instance (tree rebuild) - always join
        if tb_packet.tree_instance_id != existing_tree.tree_instance_id:
            self.logger.info(
                f"SHOULD_JOIN: New instance of tree {tb_packet.tree_id} - YES"
            )
            return True

        # Same path from same port (refresh) - always join
        if port_id == existing_tree.rootward_portid:
            self.logger.info(f"SHOULD_JOIN: Refresh from same port {port_id} - YES")
            return True

        # NEW: Accept any path that's better or equal
        new_hops = tb_packet.hops + 1
        if new_hops < existing_tree.hops:
            self.logger.info(f"SHOULD_JOIN: Better or equal path - YES")
            self.logger.info(
                f"  Current hops: {existing_tree.hops}, new hops: {new_hops}"
            )
            return True

        # Only reject if worse
        self.logger.info(f"SHOULD_JOIN: Rejecting worse path - NO")
        self.logger.info(f"  Current hops: {existing_tree.hops}, new hops: {new_hops}")
        return False

    async def _handle_link_events(self):
        while self.running:
            try:
                event = await self.link_events.get()

                if event["type"] == "CONNECTED":
                    self.logger.info(f"Handling CONNECTED event: {event}")
                    await self._handle_connected(event)
                elif event["type"] == "DISCONNECTED":
                    self.logger.info(f"Handling DISCONNECTED event: {event}")
                    await self._handle_disconnected(event)
                elif event["type"] == "PEER_UNRESPONSIVE":
                    await self._handle_peer_unresponsive(event)
                elif event["type"] == "PEER_RESPONSIVE":
                    await self._handle_peer_recovered(event)
                elif event["type"] == "UNKNOWN_MESSAGE":
                    # Handle unknown message types
                    self.logger.warning(
                        f"Received unknown message type: {event.get('data', 'No data')}"
                    )
                else:
                    self.logger.warning(f"Unhandled event type: {event['type']}")

            except Exception as e:
                self.logger.error(f"Error handling link events: {e}", exc_info=True)

    async def _handle_peer_unresponsive(self, event):
        """Handle peer becoming unresponsive - invalidate trees but keep connection ready"""
        port_id = event["port_id"]
        self.logger.warning(
            f"🟡 Peer unresponsive on port {port_id} - marking as degraded"
        )

        # Invalidate trees using this port, but don't remove port state completely
        async with self.state_lock:
            trees_to_invalidate = []
            for tree_id, tree_entry in self.trees.items():
                if tree_entry.rootward_portid == port_id:
                    trees_to_invalidate.append(tree_id)
                    self.logger.info(
                        f"Tree {tree_id} affected by unresponsive port {port_id}"
                    )

            # Create invalidation messages (same pattern as disconnection)
            for tree_id in trees_to_invalidate:
                tree_entry = self.trees[tree_id]
                invalidation_msg = f"TREE_BUILD_INVALIDATION {tree_id} {tree_entry.tree_instance_id} {self.invalidation_ttl}".encode()
                invalidation_id = f"{tree_id}:{tree_entry.tree_instance_id}"

                # Mark as seen and broadcast
                self.seen_invalidations.add(invalidation_id)

                # Send to other ports (not the unresponsive one)
                ports = self.thread_manager.get_ports()
                for check_port_id, port in ports.items():
                    if (
                        check_port_id != port_id
                        and port.protocol_instance
                        and port.protocol_instance.link_state
                        == LinkProtocol.LinkState.CONNECTED
                    ):
                        await self._send_on_port(check_port_id, invalidation_msg)

                # Remove the tree
                del self.trees[tree_id]

    async def _handle_peer_recovered(self, event):
        """Handle peer recovery - rebuild trees"""
        port_id = event["port_id"]
        self.logger.info(f"🟢 Peer recovered on port {port_id} - rebuilding trees")

        await self._trigger_tree_healing(failed_port=None)
    
    async def _handle_data_packet(self, event):
        """Handle incoming data packets"""
        try:
            packet = DataPacket.from_bytes(event["data"])
            
            if packet.destination_id == self.node_id:
                # Message for us - process it
                await self._process_received_packet(packet)
            else:
                # Forward the packet
                packet.ttl -= 1
                if packet.ttl > 0:
                    await self._route_packet(packet)
                    
        except Exception as e:
            self.logger.error(f"Error handling data packet: {e}")

    async def _handle_message_events(self):
        while self.running:
            try:
                event = await self.message_events.get()

                await self._handle_data_packet(event)

                self.logger.info("Received DATA message: %s", event["data"])

            except:
                self.logger.error("Error handling message events", exc_info=True)

    async def _handle_tree_invalidation(self, event):
        """Handle tree invalidation with flood control to prevent infinite loops"""
        try:
            data_str = event["data"].decode()
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

            from_port_id = event["port_id"]

            self.logger.info(
                f"Processing TREE_BUILD_INVALIDATION for tree {tree_id} "
                f"from port {from_port_id}, TTL={ttl}, ID={invalidation_id}"
            )

            #  Check if we've already seen this invalidation
            if invalidation_id in self.seen_invalidations:
                self.logger.info(
                    f"Already processed invalidation {invalidation_id} - ignoring"
                )
                return

            # Check TTL
            if ttl <= 0:
                self.logger.info(
                    f"TTL expired for invalidation {invalidation_id} - not forwarding"
                )
                return

            # Mark this invalidation as seen
            self.seen_invalidations.add(invalidation_id)
            self.logger.info(f"Marked invalidation {invalidation_id} as seen")

            # Process the invalidation locally
            invalidated_locally = False
            if tree_id in self.trees:
                tree_entry = self.trees[tree_id]

                # if tree_id == self.node_id:
                #     self.logger.info(
                #         f"Ignoring invalidation for our own tree {tree_id} - we are the root"
                #     )
                if tree_entry.tree_instance_id == tree_instance_id:
                    self.logger.info(f"Invalidating local tree {tree_id}")
                    del self.trees[tree_id]
                    self._last_tree_change = time.time()  # Update last change time
                    invalidated_locally = True
                    self.logger.info(f"✅ Invalidated and removed tree {tree_id}")
                else:
                    self.logger.info(
                        f"Instance mismatch for tree {tree_id}: "
                        f"received {tree_instance_id}, have {tree_entry.tree_instance_id}"
                    )
            else:
                self.logger.info(f"Don't have tree {tree_id} locally")

            new_ttl = ttl - 1
            if new_ttl > 0:
                forwarded_msg = f"TREE_BUILD_INVALIDATION {tree_id} {tree_instance_id} {new_ttl}".encode()

                ports = self.thread_manager.get_ports()
                forwarded_count = 0

                for port_id, port in ports.items():
                    if (
                        port_id != from_port_id
                        and port.protocol_instance
                        and port.protocol_instance.link_state
                        == LinkProtocol.LinkState.CONNECTED
                    ):

                        self.logger.info(
                            f"Forwarding invalidation {invalidation_id} to port {port_id} with TTL={new_ttl}"
                        )
                        await self._send_on_port(port_id, forwarded_msg)
                        forwarded_count += 1

                self.logger.info(f"Forwarded invalidation to {forwarded_count} ports")

            if invalidated_locally:
                healing_delay = random.uniform(0.1, 0.5)
                asyncio.create_task(self._delayed_healing_trigger(healing_delay))
            else:
                self.logger.info(
                    f"TTL would be 0 - not forwarding invalidation {invalidation_id}"
                )

        except Exception as e:
            self.logger.error(
                f"Error handling TREE_BUILD_INVALIDATION: {e}", exc_info=True
            )

    async def _delayed_healing_trigger(self, delay: float):
        await asyncio.sleep(delay)
        await self._trigger_tree_healing()

    async def _monitor_ports(self):
        """Monitor ports for events (simplified debug version)"""
        self.logger.info("Port monitoring started")

        # Do one-time queue inspection
        if not hasattr(self, "_queue_inspected"):
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
                    if signal is not None and signal != b"":
                        # Log the signal
                        self.logger.info(
                            f"*** SIGNAL RECEIVED on port {portid}: {signal}"
                        )
                        await self.link_events.put(
                            {
                                "type": signal.decode(),
                                "port_id": portid,
                                "timestamp": time.time(),
                            }
                        )
                except Exception as e:
                    if (
                        "Empty" not in str(e)
                        and "empty" not in str(e)
                        and "timeout" not in str(e).lower()
                    ):
                        self.logger.debug(
                            f"Signal queue exception on port {portid}: {e}"
                        )

                # Check read queue
                try:
                    data = port.io.read_q.get()

                    self.logger.info(
                        f"*** DATA RECEIVED on port {portid}: {data[:50]}..."
                    )
                    event = {"data": data, "port_id": portid}

                    if data.startswith(b"TREE_BUILD_INVALIDATION"):
                        self.logger.info(
                            f"Routing TREE_BUILD_INVALIDATION to tree_events from port {portid}"
                        )
                        await self.tree_events.put(event)
                    elif data.startswith(b"TREE_BUILD_ACK"):
                        self.logger.info(
                            f"Routing TREE_BUILD_ACK to tree_events from port {portid}"
                        )
                        await self.tree_events.put(event)
                    elif data.startswith(b"TREE_BUILD"):
                        self.logger.info(
                            f"Routing TREE_BUILD to tree_events from port {portid}"
                        )
                        await self.tree_events.put(event)
                    elif data.startswith(b"DATA_PACKET"):
                        self.logger.info(
                            f"Routing DATA_MESSAGE to message_events from port {portid}"
                        )
                        await self.message_events.put(event)
                        
                    # REMOVE UPON COMPLETION OF FMS: this introduces a lower level abstration JUST for the firing state problem.
                    elif data.startswith(b"FSP_"):
                        await self.fsp_events.put(event)
                    else:
                        self.logger.info(
                            f"Routing unknown message to link_events from port {portid}: {data[:20]}"
                        )
                        event["type"] = "UNKNOWN_MESSAGE"
                        event["timestamp"] = time.time()
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
            self.logger.info(
                f"signal_q methods: {[m for m in dir(port.io.signal_q) if not m.startswith('_')]}"
            )

            # Test if queue has data checking methods
            if hasattr(port.io.signal_q, "qsize"):
                self.logger.info(f"signal_q size: {port.io.signal_q.qsize()}")
            if hasattr(port.io.signal_q, "empty"):
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
            self.logger.warning(
                f"Port {port_id} not found for sending. Available ports: {available_ports}"
            )

    def stop(self):
        """Stop the agent thread"""
        self.logger.info("Stopping Agent")
        self.running = False

    async def _handle_data_message(self, event):
        """Handle data message routing"""
        self.logger.info(f"Handling data message: {event['data']}")
        # TODO: Implement data message routing logic
        pass
    
    async def send_message(self, destination_id: str, payload: Any) -> bool:
        """Send a message to a destination node"""
        packet = DataPacket(
            source_id=self.node_id,
            destination_id=destination_id,
            payload=payload
        )
        return await self._route_packet(packet)

    async def _route_packet(self, packet: DataPacket) -> bool:
        """Route packet using routing table"""
        snapshot = self.get_snapshot()
        routing_table = snapshot['routing_table']
        
        if packet.destination_id in routing_table:
            route = routing_table[packet.destination_id]
            next_port = route['next_hop_port']
            await self._send_on_port(next_port, packet.to_bytes())
            return True
        
        self.logger.warning(f"No route to {packet.destination_id}")
        return False

    async def _process_received_packet(self, packet: DataPacket):
        """Store received messages in inbox (upgraded with handler system)"""
        payload = packet.payload
        handled = False
        
        if isinstance(payload, str):
            try:
                import json
                payload = json.loads(payload)
                packet.payload = payload
            except json.JSONDecodeError:
                pass
        
        if isinstance(payload, dict):
            msg_type = payload.get('type')
            if msg_type and msg_type in self.message_handlers:
                try:
                    handled = await self.message_handlers[msg_type](packet)
                    if handled:
                        self.logger.debug(f"Message type '{msg_type}' handled by registered handler")
                        return
                except Exception as e:
                    self.logger.error(f"Error in handler for '{msg_type}': {e}")

        self.message_inbox.append(packet)
        self.logger.info(f"Message from {packet.source_id} added to inbox")

    def clear_messages(self):
        """Clear all messages from inbox"""
        count = len(self.message_inbox)
        self.message_inbox.clear()
        return count


    def get_messages(self, from_node: str = None) -> List[DataPacket]:
        """Get messages, optionally filtered by sender"""
        if from_node:
            return [msg for msg in self.message_inbox if msg.source_id == from_node]
        return list(self.message_inbox)

    def pop_message(self) -> Optional[DataPacket]:
        """Get and remove oldest message"""
        return self.message_inbox.popleft() if self.message_inbox else None
    async def _handle_disconnected(self, event):
        """Handle disconnection (fixed version with proper error handling)"""
        port_id = event["port_id"]
        self.logger.info(
            f"🔴 === HANDLING DISCONNECTION for port {port_id} on {self.node_id} ==="
        )

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
                        self.logger.info(
                            f"Tree {tree_id} needs invalidation (rootward port {port_id} disconnected)"
                        )

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
                            if (
                                check_port_id != port_id
                                and port.protocol_instance
                                and port.protocol_instance.link_state
                                == LinkProtocol.LinkState.CONNECTED
                            ):

                                invalidation_tasks.append(
                                    (check_port_id, invalidation_msg)
                                )
                                self.logger.info(
                                    f"Will send invalidation {invalidation_id} to port {check_port_id} with TTL={self.invalidation_ttl}"
                                )

                        # Remove the tree
                        del self.trees[tree_id]
                        self.logger.info(
                            f"✅ Invalidated tree {tree_id} due to port {port_id} disconnection"
                        )

                    except Exception as e:
                        self.logger.error(
                            f"Error processing tree {tree_id} for invalidation: {e}"
                        )

                # Clean up port paths
                if port_id in self.port_paths:
                    self.logger.info(f"Removing port path for {port_id}")
                    del self.port_paths[port_id]

            # Send invalidations outside the lock to avoid deadlock
            self.logger.info(f"Sending {len(invalidation_tasks)} invalidation messages")

            for port, msg in invalidation_tasks:
                try:
                    self.logger.info(
                        f"Sending invalidation to port {port}: {msg[:50]}..."
                    )
                    await self._send_on_port(port, msg)
                    self.logger.info(
                        f"✅ Successfully sent invalidation to port {port}"
                    )
                except Exception as e:
                    self.logger.error(
                        f"❌ Failed to send invalidation to port {port}: {e}"
                    )
                    # Continue with other invalidations even if one fails

            if trees_to_invalidate:
                self.logger.info(
                    f" Triggering tree healing for {self.node_id} after disconnection"
                )
                await self._trigger_tree_healing(failed_port=port_id)
            self.logger.info(
                f"🔴 === FINISHED HANDLING DISCONNECTION for port {port_id} on {self.node_id} ==="
            )

        except Exception as e:
            self.logger.error(
                f"❌ CRITICAL ERROR in _handle_disconnected for port {port_id}: {e}",
                exc_info=True,
            )
            # Log the current state for debugging
            self.logger.error(f"Current trees: {list(self.trees.keys())}")
            self.logger.error(f"Current neighbors: {list(self.neighbors.keys())}")
            self.logger.error(f"Current port_paths: {list(self.port_paths.keys())}")
        
    async def _handle_connected(self, event):
        """Handle port connection event with cross-partition topology sync"""
        port_id = event["port_id"]
        self.logger.info(
            f"🔥 === HANDLING CONNECTION EVENT for port {port_id} on {self.node_id} ==="
        )

        # Show current state BEFORE processing
        self.logger.info(f"Current trees BEFORE connection: {list(self.trees.keys())}")
        self.logger.info(f"Self tree exists: {self.node_id in self.trees}")

        base_delay = hash(self.node_id) % 5  # 0-4 seconds based on node_id
        jitter = random.uniform(0.5, 1.5)
        total_delay = jitter + base_delay

        self.logger.info(
            f"⏱️ Waiting {total_delay:.2f} seconds before processing connection..."
        )
        await asyncio.sleep(total_delay)

        self.logger.info(f"✅ Port {port_id} connected - processing now")

        async with self.state_lock:
            self.logger.info(f"Current trees AFTER delay: {list(self.trees.keys())}")

            # Ensure we have our own tree
            if self.node_id not in self.trees:
                tree_instance_id = str(uuid.uuid4())
                self.trees[self.node_id] = TreeEntry(
                    rootward_portid="",
                    hops=0,
                    tree_instance_id=tree_instance_id,
                    leafward_portids=[],
                )
                self.logger.info(
                    f"🌳 Created NEW tree rooted at cell {self.node_id} with instance {tree_instance_id}"
                )
            else:
                existing_tree = self.trees[self.node_id]
                self.logger.info(
                    f"🌳 Tree for {self.node_id} already exists: {existing_tree}"
                )

            # Get current neighbors for all broadcasts
            current_neighbors = self._get_current_neighbors()
            self.logger.info(f"👥 Current neighbors for broadcast: {current_neighbors}")

            # Get connected ports
            ports = self.thread_manager.get_ports()
            connected_ports = {}
            
            for pid, port in ports.items():
                port_state = "UNKNOWN"
                if port.protocol_instance:
                    port_state = port.protocol_instance.link_state

                self.logger.info(
                    f"🔍 Checking port {pid}: protocol_instance={port.protocol_instance is not None}, link_state={port_state}"
                )

                if (
                    port.protocol_instance
                    and port.protocol_instance.link_state == LinkProtocol.LinkState.CONNECTED
                ):
                    connected_ports[pid] = port
                    self.logger.info(f"✅ Port {pid} is connected and ready for broadcast")
                else:
                    self.logger.info(f"⏭️ Skipping port {pid} - not connected (state: {port_state})")

            # NEW: Broadcast ALL trees we know about (topology sync)
            trees_to_broadcast = list(self.trees.keys())
            self.logger.info(f"🌐 Broadcasting {len(trees_to_broadcast)} trees: {trees_to_broadcast}")

            total_broadcasts = 0
            for tree_id in trees_to_broadcast:
                tree_entry = self.trees[tree_id]
                
                # Use correct hop count for each tree
                tb_packet = TreeBuild(
                    tree_id=tree_id,
                    tree_instance_id=tree_entry.tree_instance_id,
                    hops=tree_entry.hops,  # Use actual distance, not 0!
                    neighbors=current_neighbors,
                )

                self.logger.info(
                    f"📦 Broadcasting tree {tree_id} (hops={tree_entry.hops}, "
                    f"instance={tree_entry.tree_instance_id[:8]}...)"
                )

                packet_bytes = tb_packet.to_bytes()
                tree_broadcast_count = 0

                # Send to all connected ports
                for pid in connected_ports.keys():
                    self.logger.info(f"📡 Sending tree {tree_id} to port {pid}")
                    await self._send_on_port(pid, packet_bytes)
                    tree_broadcast_count += 1
                    total_broadcasts += 1

                self.logger.info(
                    f"✅ Broadcasted tree {tree_id} to {tree_broadcast_count} ports"
                )

                # Small stagger between tree broadcasts to avoid overwhelming network
                if len(trees_to_broadcast) > 1:
                    await asyncio.sleep(0.1)

            self.logger.info(
                f"🌐 === TOPOLOGY SYNC COMPLETE: {total_broadcasts} total broadcasts ==="
            )

        self.logger.info(
            f"🔥 === FINISHED HANDLING CONNECTION for port {port_id} on {self.node_id} ==="
        )

    # async def _handle_connected(self, event):
    #     """Handle port connection event (enhanced debug version)"""
    #     port_id = event["port_id"]
    #     self.logger.info(
    #         f"🔥 === HANDLING CONNECTION EVENT for port {port_id} on {self.node_id} ==="
    #     )

    #     # Show current state BEFORE processing
    #     self.logger.info(f"Current trees BEFORE connection: {list(self.trees.keys())}")
    #     self.logger.info(f"Self tree exists: {self.node_id in self.trees}")

    #     base_delay = hash(self.node_id) % 5  # 0-4 seconds based on node_xid
    #     jitter = random.uniform(0.5, 1.5)
    #     total_delay = jitter + base_delay

    #     self.logger.info(
    #         f"⏱️ Waiting {total_delay:.2f} seconds before processing connection..."
    #     )
    #     await asyncio.sleep(total_delay)

    #     self.logger.info(f"✅ Port {port_id} connected - processing now")

    #     async with self.state_lock:
    #         self.logger.info(f"Current trees AFTER delay: {list(self.trees.keys())}")

    #         if self.node_id not in self.trees:
    #             tree_instance_id = str(uuid.uuid4())
    #             self.trees[self.node_id] = TreeEntry(
    #                 rootward_portid="",
    #                 hops=0,
    #                 tree_instance_id=tree_instance_id,
    #                 leafward_portids=[],
    #             )
    #             self.logger.info(
    #                 f"🌳 Created NEW tree rooted at cell {self.node_id} with instance {tree_instance_id}"
    #             )
    #             should_broadcast = True
    #         else:
    #             existing_tree = self.trees[self.node_id]
    #             self.logger.info(
    #                 f"🌳 Tree for {self.node_id} already exists, but broadcasting anyways: {existing_tree}"
    #             )
    #             should_broadcast = True

    #         self.logger.info(f"📡 Should broadcast: {should_broadcast}")

    #         if should_broadcast:
    #             current_neighbors = self._get_current_neighbors()
    #             self.logger.info(
    #                 f"👥 Current neighbors for broadcast: {current_neighbors}"
    #             )

    #             tb_packet = TreeBuild(
    #                 tree_id=self.node_id,
    #                 tree_instance_id=self.trees[self.node_id].tree_instance_id,
    #                 hops=0,
    #                 neighbors=current_neighbors,
    #             )

    #             self.logger.info(f"📦 Created TREE_BUILD packet: {tb_packet}")
    #             packet_bytes = tb_packet.to_bytes()
    #             self.logger.info(f"📦 Packet bytes: {packet_bytes}")

    #             ports = self.thread_manager.get_ports()
    #             broadcast_count = 0

    #             for pid, port in ports.items():
    #                 port_state = "UNKNOWN"
    #                 if port.protocol_instance:
    #                     port_state = port.protocol_instance.link_state

    #                 self.logger.info(
    #                     f"🔍 Checking port {pid}: protocol_instance={port.protocol_instance is not None}, link_state={port_state}"
    #                 )

    #                 if (
    #                     port.protocol_instance
    #                     and port.protocol_instance.link_state
    #                     == LinkProtocol.LinkState.CONNECTED
    #                 ):

    #                     self.logger.info(
    #                         f"📡 Broadcasting TREE_BUILD to connected port {pid}"
    #                     )
    #                     await self._send_on_port(pid, packet_bytes)
    #                     broadcast_count += 1
    #                 else:
    #                     self.logger.info(
    #                         f"⏭️ Skipping port {pid} - not connected (state: {port_state})"
    #                     )

    #             self.logger.info(
    #                 f"📡 Broadcasted TREE_BUILD to {broadcast_count} ports"
    #             )
    #         else:
    #             self.logger.info("🚫 No broadcast needed - tree already exists")

    #     self.logger.info(
    #         f"🔥 === FINISHED HANDLING CONNECTION for port {port_id} on {self.node_id} ==="
    #     )

    async def _trigger_tree_healing(self, failed_port=None):

        self.logger.info("🔄 === Triggering tree healing process ===")

        try:

            if self.node_id in self.trees:
                our_tree = self.trees[self.node_id]

                if our_tree.rootward_portid == "":
                    self.logger.info(
                        f"🔄 Broadcasting our tree {self.node_id} to stimulate healing"
                    )

                    current_neighbors = self._get_current_neighbors()

                    tb_packet = TreeBuild(
                        tree_id=self.node_id,
                        tree_instance_id=our_tree.tree_instance_id,
                        hops=0,
                        neighbors=current_neighbors,
                    )

                    ports = self.thread_manager.get_ports()
                    healing_broadcast = 0

                    for port_id, port in ports.items():
                        if (
                            port_id != failed_port
                            and port.protocol_instance
                            and port.protocol_instance.link_state
                            == LinkProtocol.LinkState.CONNECTED
                        ):

                            self.logger.info(
                                f"🔄 Sending healing TREE_BUILD to port {port_id}"
                            )
                            await self._send_on_port(port_id, tb_packet.to_bytes()),
                            healing_broadcast += 1

                    self.logger.info(
                        f"🔄 Broadcasted healing TREE_BUILD to {healing_broadcast} ports"
                    )

                    await asyncio.sleep(0.2)

                else:
                    self.logger.info(
                        f"🔄 We're not root of our tree - cannot initiate healing broadcast"
                    )
            else:
                async with self.state_lock:
                    if self.node_id not in self.trees:
                        tree_instance_id = str(uuid.uuid4())
                        self.trees[self.node_id] = TreeEntry(
                            rootward_portid="",
                            hops=0,
                            tree_instance_id=tree_instance_id,
                            leafward_portids=[],
                        )
                        self._last_tree_change = time.time()
                        self.logger.info(
                            f"🔄 Created healing tree {self.node_id} with instance {tree_instance_id}"
                        )

                        # Now broadcast it
                        await self._trigger_tree_healing(failed_port)
        except Exception as e:
            self.logger.error(f"❌ Error during tree healing: {e}", exc_info=True)

        self.logger.info(f"🔄 === FINISHED TREE HEALING ===")

    def get_snapshot(self):
        """Get minimal snapshot for DAG construction and routing table generation."""

        # Get connected ports and their neighbors
        ports = self.thread_manager.get_ports()
        connected_neighbors = {}

        for port_id, port in ports.items():
            if (
                port.protocol_instance
                and port.protocol_instance.link_state
                == LinkProtocol.LinkState.CONNECTED
            ):

                # Extract neighbor ID from port connection
                neighbor_info = getattr(port.protocol_instance, "neighbor_portid", None)
                if neighbor_info:
                    neighbor_id = neighbor_info.split(":")[0]
                    connected_neighbors[port_id] = neighbor_id

        # Build tree information for routing
        trees = {}
        for tree_id, tree_entry in self.trees.items():
            trees[tree_id] = {
                "root_id": tree_id,
                "hops_to_root": tree_entry.hops,
                "parent_port": tree_entry.rootward_portid,
                "child_ports": list(tree_entry.leafward_portids),
                "is_root": tree_entry.rootward_portid == "",
                "instance_id": tree_entry.tree_instance_id,
            }

        # Build routing table: for each known node, how to reach it
        routing_table = {}

        # Add direct neighbors (1 hop)
        for port_id, neighbor_id in connected_neighbors.items():
            routing_table[neighbor_id] = {
                "next_hop_port": port_id,
                "hops": 1,
                "via_tree": None,  # Direct connection
            }

        # Add tree-based routes (multi-hop)
        for tree_id, tree_info in trees.items():
            if tree_id != self.node_id and tree_info["hops_to_root"] > 0:
                routing_table[tree_id] = {
                    "next_hop_port": tree_info["parent_port"],
                    "hops": tree_info["hops_to_root"],
                    "via_tree": tree_id,
                }

        return {
            "node_id": self.node_id,
            "timestamp": time.time(),
            "trees": trees,
            "direct_neighbors": list(connected_neighbors.values()),
            "routing_table": routing_table,
            "connected_ports": list(connected_neighbors.keys()),
        }