import asyncio
import time
import json
import traceback
from hermes.sim.FSPStateColors import *

class FSPTopologyMixin:
    def __init__(self):
        self.fsp_topology_established = False
        self.fsp_chain_topology = None
        self.am_general = False
        self.topology_authority_lock = asyncio.Lock()
        self.fsp_state = Q
        self.fsp_time_step = 0
        self.fsp_active = False
        self.fsp_transition_lock = asyncio.Lock()
        self.fsp_tables = None
        self.fsp_max_time = 0
    
    def _initialize_fsp_with_info(self, fsp_info):
        
        if not fsp_info:
            self.logger.info(f"❌ FSP initialization failed: no info provided")
            return False
        
        if fsp_info['is_general']:
            self.fsp_state = P0  # General starts in P0
            self.logger.info(f"General {self.cell_id} (pos {fsp_info['position']}) initialized with state P0")
        else:
            self.fsp_state = Q   # All others start in Q
            self.logger.info(f"{fsp_info['role']} {self.cell_id} (pos {fsp_info['position']}) initialized with state Q")
            
        self.fsp_max_time = (2 * fsp_info['chain_length']) - 2

        self.fsp_time_step = 0
        self.fsp_neighbor_states = {}
        
        self.fsp_tables = self._load_fsp_tables(fsp_info['chain_length'])
        self._register_fsp_handlers()
        
        
        return True
    
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
    
    def _register_fsp_handlers(self):
        """Register FSP message handlers with agent"""
        if hasattr(self.agent, 'register_handler'):
            self.agent.register_handler('fsp_state_update', self._handle_fsp_state_update)
            self.agent.register_handler('fsp_start_command', self._handle_fsp_start_command)
            self.agent.register_handler('chain_topology_assignment', self.handle_topology_assignment)
            self.logger.info(f"✅ FSP handlers registered for {self.cell_id}")
    
    def _cleanup_fsp_handlers(self):
        """Unregister FSP handlers"""
        if hasattr(self, 'agent'):
            self.agent.unregister_handler('fsp_state_update')
            self.agent.unregister_handler('fsp_start_command') 
            self.agent.unregister_handler('chain_topology_assignment')

            
    
    async def _begin_fsp_state_machine(self):
        """Start the main FSP state machine loop"""
        self.fsp_active = True
        self.logger.info(f"🚀 Starting FSP state machine for {self.cell_id}")
        
        # Initial state broadcast
        #await self._broadcast_fsp_state() # removing this since broadcast should happen before the current state.
        
        # Start the state machine task
        asyncio.create_task(self._fsp_state_machine_loop())

    async def _fsp_state_machine_loop(self):
        """Main FSP state machine execution loop"""
        await asyncio.sleep(1)
        while self.fsp_active and self.fsp_time_step < self.fsp_max_time:
            try:
                await self._broadcast_fsp_state()  # Ensure we broadcast current state
                if await self._wait_for_neighbor_sync(timeout=10.0):
                    await self._advance_fsp_state()
                else:
                    self.logger.info(f"FSP timeout at step {self.fsp_time_step}")
                    break
                
                await asyncio.sleep(0.3)  # Let messages propagate
            except Exception as e:
                self.logger.info(f"❌ FSP state machine error: {e}")
                break
        
        await self._check_fsp_completion()
    
    async def _wait_for_neighbor_sync(self, timeout=10.0):
        """Wait for all neighbors to reach current time step"""
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            if self._all_neighbors_ready():
                return True
            await asyncio.sleep(0.1)
            
        return False
    
    def _all_neighbors_ready(self):
        """Check if all neighbors are at current time step or higher"""
        fsp_info = self.fsp_snapshot()
        if not fsp_info:
            return False
        
        left_neighbor = fsp_info['left_neighbor']
        if left_neighbor:
            if left_neighbor not in self.fsp_neighbor_states:
                return False
            if self.fsp_neighbor_states[left_neighbor]['time_step'] < self.fsp_time_step:
                return False
            
        right_neighbor = fsp_info['right_neighbor']
        if right_neighbor:
            if right_neighbor not in self.fsp_neighbor_states:
                return False
            if self.fsp_neighbor_states[right_neighbor]['time_step'] < self.fsp_time_step:
                return False
            
        return True
    
    async def _advance_fsp_state(self):
        """Advance FSP state by one time step"""
        
        async with self.fsp_transition_lock:
            left_state = self._get_neighbor_state('left')
            right_state = self._get_neighbor_state('right')
            
            old_state = self.fsp_state

            self.logger.info(f"🔍 {self.cell_id} T{self.fsp_time_step} transition input:")
            self.logger.info(f"    - Left: {statename.get(left_state, 'UNK')} ({left_state})")
            self.logger.info(f"    - Current: {statename.get(old_state, 'UNK')} ({old_state})")
            self.logger.info(f"    - Right: {statename.get(right_state, 'UNK')} ({right_state})")

            new_state = self._apply_fsp_transition(left_state, self.fsp_state, right_state)

            self.logger.info(f"    - Result: {statename.get(new_state, 'UNK')} ({new_state})")


            if new_state != old_state:
                self.fsp_state = new_state
                self.logger.info(f"🔄 FSP {self.cell_id} T{self.fsp_time_step}: {statename.get(old_state, 'UNK')} → {statename.get(new_state, 'UNK')}")
            
            self.fsp_time_step += 1
            
            # await self._broadcast_fsp_state() 
    
    def _get_neighbor_state(self, direction):
        """Get neighbor state for current time step"""
        fsp_info = self.fsp_snapshot()
        if not fsp_info:
            return Q # quiet state
        
        neighbor_id = fsp_info[f"{direction}_neighbor"]
        if not neighbor_id:
            if direction == 'left' and fsp_info['position'] == 1:
                return xx  # Position 1 (general) has xx on left  
            elif direction == 'right' and fsp_info['position'] == fsp_info['chain_length']:
                return xx  # Last position has xx on right
            else:
                return xx  # Other boundaries use xx
        
            
        if neighbor_id in self.fsp_neighbor_states:
            neighbor_info = self.fsp_neighbor_states[neighbor_id]
            if neighbor_info['time_step'] >= self.fsp_time_step:
                return neighbor_info['state']
        
        return Q # default to quiet if neighbor not ready
    
    async def _broadcast_fsp_state(self):
        """Broadcast current FSP state to neighbors"""
        fsp_info = self.fsp_snapshot()
        if not fsp_info:
            return
        
        state_msg = {
            'type': 'fsp_state_update',
            'state': self.fsp_state,
            'time_step': self.fsp_time_step,
            'position': fsp_info['position']
        }
        
        for direction in ['left', 'right']:
            neighbor = fsp_info.get(f"{direction}_neighbor")
            if neighbor:
                await self.agent.send_message(neighbor, state_msg)
                self.logger.info(f"📡 {self.cell_id} broadcasted FSP state: {statename.get(self.fsp_state, 'UNK')} at T{self.fsp_time_step} to {neighbor}") 
    
        
    async def _handle_fsp_state_update(self, packet):
        """Handle FSP state updates from neighbors"""
        if not self.fsp_active:
            return False
        
        payload = packet.payload
        sender = packet.source_id
        sender_state = payload.get('state', Q)
        sender_time_step = payload.get('time_step', 0)
        
        # Update neighbor state tracking
        self.fsp_neighbor_states[sender] = {
            'state': sender_state,
            'time_step': sender_time_step,
            'timestamp': asyncio.get_event_loop().time()
        }
        
        self.logger.info(f"🔄 FSP neighbor update: {sender} -> {statename.get(sender_state, 'UNK')} at T{sender_time_step}")
        return True


    async def _handle_fsp_start_command(self, packet):
        """Handle FSP start command from general"""
        if not self.fsp_topology_established:
            return False
        
        payload = packet.payload
        from_general = payload.get('from_general')
        
        if from_general != self.fsp_chain_topology['general']:
            self.logger.info(f"⚠️ FSP start command from {from_general} but general is {self.fsp_chain_topology['general']}")
            return False
        
        self.logger.info(f"📢 {self.cell_id} received FSP start command from general {from_general}")
        
        # Initialize and start FSP
        fsp_info = self.fsp_snapshot()
        self._initialize_fsp_with_info(fsp_info)
        await self._begin_fsp_state_machine()
        
        return True

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
            
    async def _check_fsp_completion(self):
        """Check FSP completion and report results"""
        if self.fsp_time_step >= self.fsp_max_time:
            if self.fsp_state == T:
                self.logger.info(f"🔥🔥🔥 CELL {self.cell_id} FIRED SUCCESSFULLY! 🔥🔥🔥")
                # needs a fix here for cleanup for general
                self.am_general = False
                
            
            else:
                self.logger.info(f"⚠️ FSP completed but {self.cell_id} did not fire. Final state: {statename.get(self.fsp_state, 'UNK')}")
        else:
            self.logger.info(f"⏹️ FSP stopped early at time {self.fsp_time_step}")
        
        self.fsp_active = False

    async def establish_chain_authority(self):
        """Determine if we are the general and establish chain topology"""
        snapshot = self.agent.get_snapshot()
        
        if await self._should_become_general(snapshot):
            self.am_general = True
            await self._perform_general_duties()
        else:
            await self._wait_for_topology_assignment()
    
            
    async def _should_become_general(self, snapshot):
        """Determine if this cell should become the general"""
        # Don't just check for 1 neighbor - check if we should be the general at position 1
        all_reachable = set(snapshot['routing_table'].keys())
        all_reachable.add(snapshot['node_id'])
        
        # Find the two edge nodes (cells with only 1 neighbor each)
        # The general should be the node adjacent to the "left" edge
        
        # For now, let's use a simpler rule: smallest cell ID with exactly 1 neighbor
        # But we'll adjust positions later
        if len(snapshot['direct_neighbors']) != 1:
            return False
        
        if snapshot['node_id'] == min(all_reachable):
            print(f"🎯 {self.cell_id} declaring itself GENERAL")
            return True

        return False
    
    async def _perform_general_duties(self):
        """General discovers topology, broadcasting it to all cells"""

        chain_topology = await self._discover_complete_chain()
        
        if not chain_topology:
            self.logger.info(f"General failed to discover valid chain topology")
            return
        
        await self._broadcast_chain_topology(chain_topology)
        
        self.fsp_chain_topology = chain_topology
        self.fsp_topology_established = True
        
        self.logger.info(f"✅ General established chain: {' → '.join(chain_topology['chain_order'])}")

    # TODO: Must be fixed
    async def _verify_linear_topology(self, all_nodes):
        return True
    
    async def _discover_complete_chain(self):
        """General discovers the complete chain by asking all nodes"""
        snapshot = self.agent.get_snapshot()
        all_nodes = set(snapshot['routing_table'].keys())
        all_nodes.add(snapshot['node_id'])

        if not await self._verify_linear_topology(all_nodes):
            return None
        
        chain_order = [self.cell_id]
        visited_nodes = {self.cell_id}  # Track what we've visited
        current_node = self.cell_id
        
        while len(chain_order) < len(all_nodes):
            # Pass visited_nodes (what we've seen), not all_nodes
            next_node = await self._find_next_in_chain(current_node, visited_nodes)
            if not next_node:
                break
            
            chain_order.append(next_node)
            visited_nodes.add(next_node)  # Add to visited set
            current_node = next_node
            
        if len(chain_order) != len(all_nodes):
            self.logger.info(f"❌ Chain discovery failed: found {len(chain_order)} of {len(all_nodes)} nodes")
            return None
        
        topology = {
            'chain_order': chain_order,
            'chain_length': len(chain_order),
            'general': self.cell_id,
            'positions': {},
            'neighbors': {}
        }

        for i, node in enumerate(chain_order):
            topology['positions'][node] = i + 1
            topology['neighbors'][node] = {
                'left': chain_order[i-1] if i > 0 else None,
                'right': chain_order[i+1] if i < len(chain_order)-1 else None
            }
        
        return topology
    
    #TODO: FIX THIS TO USE ACTUAL NEIGHBORS
    async def _find_next_in_chain(self, current_node, visited_nodes):
        """Find the next node in the chain from current position"""
        snapshot = self.agent.get_snapshot()
        
        candidates = []
        for node in snapshot['routing_table']:
            if node not in visited_nodes:  # Skip already visited nodes
                hops = snapshot['routing_table'][node]['hops']
                candidates.append((hops, node))
        
        if candidates:
            candidates.sort()
            # Return the closest unvisited node
            return candidates[0][1]
        
        return None

    
    async def _broadcast_chain_topology(self, topology):
        """General broadcasts complete topology to all cells"""
        topology_msg = {
            'type': 'chain_topology_assignment',
            'topology': topology,
            'from_general': self.cell_id,
            'timestamp': time.time()
        }

        for node in topology['chain_order']:
            if node != self.cell_id:
                await self.agent.send_message(node, topology_msg)
        
        self.logger.info(f"📡 General broadcasted topology to {len(topology['chain_order'])-1} cells")

    async def _wait_for_topology_assignment(self, timeout=15.0):
        """Non-general cells waiting for topology from general"""
        self.logger.info(f"🔄 {self.cell_id} waiting for topology assignment from general...")

        start_time = asyncio.get_event_loop().time()
        check_count = 0
        
        while not self.fsp_topology_established:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                self.logger.info(f"⏳ {self.cell_id} timeout waiting for topology assignment after {elapsed:.1f}s")
                return False
            
            check_count += 1
            if check_count % 10 == 0:  # Log every 5 seconds
                self.logger.info(f"🔄 {self.cell_id} still waiting for topology... ({elapsed:.1f}s elapsed)")
            
            await asyncio.sleep(0.5)
        
        self.logger.info(f"✅ {self.cell_id} received topology assignment!")
        return True
    
    async def handle_topology_assignment(self, packet):
        """Handle topology assignment from general"""
        payload = packet.payload
        
        if payload.get('type') != 'chain_topology_assignment':
            return False
        
        async with self.topology_authority_lock:
            topology = payload.get('topology')
            from_general = payload.get('from_general')
            
            if from_general != topology['general']:
                self.logger.info(f"⚠️ Topology from {from_general} but claims general is {topology['general']}")
                return False
            
            self.fsp_chain_topology = topology
            self.fsp_topology_established = True
            my_position = topology['positions'][self.cell_id]
            neighbors = topology['neighbors'][self.cell_id]
            
            self.logger.info(f"✅ {self.cell_id} received topology: Position {my_position}")
            self.logger.info(f"   Left: {neighbors['left']}, Right: {neighbors['right']}")

            return True
        
    

    def fsp_snapshot(self):
        """Get our FSP role and neighbors from the established topology"""
        if not self.fsp_topology_established:
            return None
        
        topology = self.fsp_chain_topology
        my_position = topology['positions'][self.cell_id]
        neighbors = topology['neighbors'][self.cell_id]
        
        # Correct role assignment for Wakesman FSP
        if my_position == 1 and self.am_general:
            role = 'general'  # Leftmost position is the general
        elif my_position == topology['chain_length']:
            role = 'right_edge'  # Rightmost position
        else:
            role = 'soldier'  # Everyone else is a soldier

        return {
            'position': my_position,
            'role': role,
            'left_neighbor': neighbors['left'],
            'right_neighbor': neighbors['right'],
            'chain_length': topology['chain_length'],
            'is_general': self.am_general
        }
    
    def get_fsp_status(self):
        """Get current FSP status"""
        try:
            if not hasattr(self, 'fsp_topology_established'):
                return {"error": "FSP not initialized"}
            
            fsp_info = self.fsp_snapshot() if self.fsp_topology_established else None
            
            return {
                "topology_established": self.fsp_topology_established,
                "fsp_active": getattr(self, 'fsp_active', False),
                "current_state": statename.get(getattr(self, 'fsp_state', Q), 'Q'),
                "time_step": getattr(self, 'fsp_time_step', 0),
                "max_time": getattr(self, 'fsp_max_time', 0),
                "role": fsp_info.get('role') if fsp_info else 'unknown',
                "position": fsp_info.get('position') if fsp_info else -1,
                "is_general": getattr(self, 'am_general', False)
            }
        except Exception as e:
            return {"error": f"Error getting FSP status: {e}"}

    def trigger_manual_fsp_as_general(self):
        """Manually trigger FSP with this cell as the general"""
        try:
            if not hasattr(self, 'agent_loop'):
                return {"error": "Agent loop not available"}
            
            # Force this cell to be the general
            self.am_general = True
            self.logger.info(f"🎯 {self.cell_id} manually designated as GENERAL")
            
            future = asyncio.run_coroutine_threadsafe(
                self._start_manual_fsp_as_general(),
                self.agent_loop
            )
            result = future.result(timeout=10.0)
            
            return {"success": result, "message": "Manual FSP triggered as general" if result else "FSP failed to start"}
        except Exception as e:
            return {"error": f"Error triggering manual FSP: {e}"}
    async def _general_start_fsp(self):
        """General starts FSP across entire chain"""
        start_msg = {
        'type': 'fsp_start_command',
        'from_general': self.cell_id,
        'timestamp': time.time()
        }
        
        for node in self.fsp_chain_topology['chain_order']:
            if node != self.cell_id:
                await self.agent.send_message(node, start_msg)
                
        await self._begin_fsp_state_machine()
        self.logger.info(f"🔥 General {self.cell_id} initiated FSP across chain!")

    async def _start_manual_fsp_as_general(self):
        """Start FSP as manually designated general"""
        # Skip automatic general selection - we're already designated
        # Just do topology discovery and broadcasting
        await self._perform_general_duties()
        
        if not self.fsp_topology_established:
            self.logger.info(f"⚠️ {self.cell_id} failed to establish FSP topology")
            return False
        
        # Initialize FSP with topology
        fsp_info = self.fsp_snapshot()
        self._initialize_fsp_with_info(fsp_info)
        
        # Start FSP across entire chain
        await self._general_start_fsp()
        return True
    
    

            