#!/usr/bin/env python3

"""
cell.py - individual cell that can be controlled via XML - RPC
"""

from xmlrpc.server import SimpleXMLRPCServer
import threading
import argparse
import time
import asyncio
from hermes.sim.Sim import Sim
from hermes.port.AgentECNF import Agent

from hermes.faults.FaultInjector import FaultState

class Cell:
    def __init__(self, cell_id, rpc_port, bind_addr="localhost"):
        self.cell_id = cell_id
        self.rpc_port = rpc_port
        self.sim = None
        self.rpc_server = None
        self.running = False
        self.port_queues = {}
        self.bind_addr = bind_addr
        
        self.metric_cache = {}
        
    def start(self):
        """Start the cell with XML-RPC server."""
        self.start_time = time.time()
        self.sim = Sim()
        self.sim.configure_logging()
        self.agent = Agent(self.cell_id, self.sim.thread_manager)
        self.agent_thread = threading.Thread(target=self._run_agent, daemon=True)
        
        self.agent_thread.start()
        # start rpc server
        time.sleep(0.2)

        self._start_rpc_server()

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.shutdown()


    def _run_agent(self):
        """Run the async agent in its own event loop"""
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run the agent
            loop.run_until_complete(self.agent.run())
        except Exception as e:
            print(f"Agent error: {e}")
        finally:
            loop.close()       
             
    def _start_rpc_server(self):
        """Start the XML-RPC server in the background"""
        
        def run_server():
            self.running = True
            self.rpc_server = SimpleXMLRPCServer((self.bind_addr, self.rpc_port), allow_none=True, logRequests=False)
            
            self.rpc_server.register_function(self.bind_port, "bind_port")
            self.rpc_server.register_function(self.unbind_port, "unbind_port")
            self.rpc_server.register_function(self.shutdown, "shutdown")
            self.rpc_server.register_function(self.heartbeat, "heartbeat")
            self.rpc_server.register_function(self.link_status, "link_status")
            self.rpc_server.register_function(self.get_metrics, "get_metrics")
            self.rpc_server.register_function(self.inject_fault, "inject_fault")
            self.rpc_server.register_function(self.clear_fault, "clear_fault")
            
            print(f"XML-RPC server started on port {self.rpc_port}")
            self.rpc_server.serve_forever()

        
        rpc_thread = threading.Thread(target=run_server, daemon=True)
        rpc_thread.start()   
            
    def bind_port(self, port_name, port_config):
        """Bind a new port"""
        try:
            from hermes.model.ports import PortConfig, PortIO
            from hermes.port.Port import UDPPort
            from hermes.sim.PipeQueue import PipeQueue
            from hermes.faults.FaultInjector import ThreadSafeFaultInjector

            print(f"bind_port called: {port_name}, {port_config}")
            
            signal_q = PipeQueue()
            read_q = PipeQueue()
            write_q = PipeQueue()
            
            port_config = PortConfig(
                logger=None,
                interface=port_config.get('interface', port_name),
                port_id=f"{self.cell_id}:{port_name}",
                name=port_name
            )           
            
            port_io = PortIO(
                read_q=read_q,
                write_q=write_q,
                signal_q=signal_q
            )
            
            port = UDPPort(
                config=port_config,
                io=port_io,
                faultInjector=ThreadSafeFaultInjector(),
            )

            self.sim.thread_manager.register_port(port)
            port_key = f"{self.cell_id}:{port_name}"
            self.sim.thread_manager.register_pipes(port_key, [signal_q, read_q, write_q])
            port.start()
            
            print(f"Port {port_name} started successfully")
            
            return f"Bound port {port_name} with config {port_config} successfully"


        except Exception as e:

            print(f"Error creating port {port_name}: {e}")
            import traceback
            traceback.print_exc()
            return f"Error binding {port_name}: {str(e)}"

    def unbind_port(self, port_name):
        """Unbind an existing port"""
        try:
            ports = self.sim.thread_manager.get_ports()
            port_key = f"{self.cell_id}:{port_name}"
            
            if port_key not in ports:
                return f"Port {port_name} is not bound"
            
            port = ports[port_key]
            
            port.stop()  # Signal the port to stop
            port.join(timeout=2.0)
            

            success = self.sim.thread_manager.delete_port(port_key)
            
            return f'Port {port_name} unbound successfully' if success else f'Failed to unbind port {port_name}'
        
        except Exception as e:
            return f"Error unbinding {port_name}: {str(e)}"
        
    
    def link_status(self, port_name):
        """Get status of a port"""
        try:
            ports = self.sim.thread_manager.get_ports()

            port_key = f"{self.cell_id}:{port_name}"
            
            if port_key not in ports:
                return "unbound"
            
            port = ports[port_key]
            
            if not port.is_alive():
                return "dead"
            
            if hasattr(port, 'protocol_instance') and port.protocol_instance:
                if hasattr(port.protocol_instance, 'link_state'):
                    return port.protocol_instance.link_state.value
                
            return "bound"
        
        except Exception as e:
            return f'error: {str(e)}'
                            
            
    
    def heartbeat(self):
        """Health check"""
        return f"alive:{self.cell_id}"
    
    def shutdown(self):
        """Cell shutdown"""
        print(f"Shutting down cell {self.cell_id}")
        self.running = False

        # Stop the agent
        if hasattr(self, 'agent'):
            self.agent.stop()  # This sets agent.running = False
        
        # Wait for agent thread to finish
        if hasattr(self, 'agent_thread') and self.agent_thread.is_alive():
            self.agent_thread.join(timeout=2.0) 
            print(f"Agent for cell {self.cell_id} stopped")
            
        if self.rpc_server:
            threading.Thread(target=self.rpc_server.shutdown, daemon=True).start()
        
        return "Shutting down..."
        
    def get_metrics(self):
        """Get real-time metrics from the cell"""
        try:
            metrics = {
                'cell_id': self.cell_id,
                'uptime': time.time() - getattr(self, 'start_time', time.time()),
                'ports': {},
                'agent': {}
            }
            
            # Enhanced Port metrics with networking data
            ports = self.sim.thread_manager.get_ports()
            for port_id, port in ports.items():
                port_info = {
                    'name': port.name,
                    'port_id': port_id,
                    'status': 'alive' if port.is_alive() else 'dead',
                    'packets_sent': 0,
                    'packets_received': 0,
                    'bytes_sent': 0,
                    'bytes_received': 0,
                    'last_activity': 'never',
                    'connection_time': 0
                }
                
                # Get link state
                if hasattr(port, 'protocol_instance') and port.protocol_instance:
                    protocol = port.protocol_instance
                    
                    if hasattr(protocol, 'link_state'):
                        link_state = protocol.link_state
                        if hasattr(link_state, 'value'):
                            port_info['link_state'] = str(link_state.value)
                        else:
                            port_info['link_state'] = str(link_state)
                    else:
                        port_info['link_state'] = 'unknown'
                    
                    # Get protocol statistics if available
                    if hasattr(protocol, 'statistics'):
                        stats = protocol.statistics
                        port_info.update({
                            'packets_sent': stats.get('packets_sent', 0),
                            'packets_received': stats.get('packets_received', 0),
                            'bytes_sent': stats.get('bytes_sent', 0),
                            'bytes_received': stats.get('bytes_received', 0),
                            'events': stats.get('events', 0),
                            'round_trip_latency': stats.get('round_trip_latency', 0),
                            'packets_dropped_in': stats.get('packets_dropped_in', 0),
                            'packets_dropped_out': stats.get('packets_dropped_out', 0),
                            'packets_delayed_in': stats.get('packets_delayed_in', 0),
                            'packets_delayed_out': stats.get('packets_delayed_out', 0)
                        })
                    
                    # Get extended protocol statistics if this is EthernetProtocolExtended
                    if hasattr(protocol, 'get_link_status'):
                        try:
                            link_status = protocol.get_link_status()
                            if 'statistics' in link_status:
                                extended_stats = link_status['statistics']
                                # Merge extended statistics
                                port_info.update(extended_stats)
                        except Exception as e:
                            print(f"Error getting extended link status: {e}")
                    
                    # Get queue lengths (important for debugging)
                    if hasattr(port, 'io'):
                        port_info.update({
                            'read_queue_size': port.io.read_q.qsize() if hasattr(port.io.read_q, 'qsize') else 0,
                            'write_queue_size': port.io.write_q.qsize() if hasattr(port.io.write_q, 'qsize') else 0,
                            'signal_queue_size': port.io.signal_q.qsize() if hasattr(port.io.signal_q, 'qsize') else 0
                        })
                    
                    if hasattr(port, 'faultInjector') and port.faultInjector:
                        fault_state = port.faultInjector.get_state()
                        port_info['fault_injection'] = {
                            'active': fault_state.is_active,
                            'drop_rate': fault_state.drop_rate,
                            'delay_ms': fault_state.delay_ms
                        }
                    
                    if hasattr(protocol, 'faultInjector') and protocol.faultInjector:
                        protocol_fault_state = protocol.faultInjector.get_state()
                        port_info['protocol_fault_injection'] = {
                            'active': protocol_fault_state.is_active,
                            'drop_rate': protocol_fault_state.drop_rate,
                            'delay_ms': protocol_fault_state.delay_ms
                        }
                    
                    # Get neighbor information
                    if hasattr(protocol, 'neighbor_portid'):
                        port_info['neighbor_portid'] = str(protocol.neighbor_portid) if protocol.neighbor_portid else 'none'
                        
                else:
                    port_info['link_state'] = 'no_protocol'
                    
                metrics['ports'][port_id] = port_info
            
            # Enhanced Agent metrics with tree details
            if (hasattr(self, 'agent') and hasattr(self, 'agent_thread') and 
                self.agent_thread.is_alive() and self.agent.running):
                try:
                    snapshot = self.agent.get_snapshot()
                    
                    # Trees are now already dictionaries, no need for to_dict()
                    trees_info = snapshot.get('trees', {})
                    
                    # Port paths processing (unchanged)
                    port_paths_info = {}
                    for path_id, path_data in snapshot.get('port_paths', {}).items():
                        if hasattr(path_data, 'serialize'):
                            try:
                                port_paths_info[path_id] = path_data.serialize()
                            except:
                                port_paths_info[path_id] = str(path_data)
                        else:
                            port_paths_info[path_id] = str(path_data)
                    
                    # Build comprehensive agent metrics with all new snapshot data
                    metrics['agent'] = {
                        'status': 'running',
                        'trees_count': len(trees_info),
                        'trees': trees_info,
                        'node_id': str(snapshot.get('node_id', '')),
                        'port_paths': port_paths_info,
                        
                        # Add new enhanced snapshot data
                        'topology': snapshot.get('topology', {}),
                        'routing_tables': snapshot.get('routing_tables', {}),
                        'neighbors': snapshot.get('neighbors', {}),
                        'network_graph': snapshot.get('network_graph', {}),
                        'dag_metadata': snapshot.get('dag_metadata', {}),
                        
                        # Computed metrics
                        'total_leafward_connections': sum(
                            len(tree.get('leafward_portids', [])) 
                            for tree in trees_info.values() 
                            if isinstance(tree, dict)
                        ),
                        'direct_neighbors_count': len(
                            snapshot.get('neighbors', {}).get('immediate_neighbors', [])
                        ),
                        'reachable_nodes_count': len(
                            snapshot.get('topology', {}).get('reachable_nodes', [])
                        ),
                        'root_trees_count': len(
                            snapshot.get('dag_metadata', {}).get('root_trees', [])
                        )
                    }

                except Exception as e:
                    metrics['agent'] = {
                        'status': 'running',
                        'error': str(e),
                        'error_details': f"Snapshot error: {str(e)}"
                    }
            else:
                agent_status = 'stopped'
                if hasattr(self, 'agent_thread'):
                    if not self.agent_thread.is_alive():
                        agent_status = 'thread_dead'
                    elif not getattr(self, 'agent', None):
                        agent_status = 'agent_missing'
                    elif not getattr(self.agent, 'running', False):
                        agent_status = 'agent_not_running'
                
                metrics['agent'] = {
                    'status': agent_status,
                    'debug_info': {
                        'has_agent': hasattr(self, 'agent'),
                        'has_agent_thread': hasattr(self, 'agent_thread'),
                        'thread_alive': hasattr(self, 'agent_thread') and self.agent_thread.is_alive(),
                        'agent_running': hasattr(self, 'agent') and getattr(self.agent, 'running', False)
                    }
                }

            return metrics
                    
        except Exception as e:
            return {'error': str(e), 'cell_id': self.cell_id}
                
    def inject_fault(self, port_name, fault_type, params):
        """Fault injection for a specific port"""
        
        try:
            ports = self.sim.thread_manager.get_ports()
            port_key = f"{self.cell_id}:{port_name}"
            
            if port_key not in ports:
                return f"Port {port_name} is not bound"
            
            port = ports[port_key]
            
            if fault_type == 'drop':
                drop_rate = params.get('drop_rate', 0.1)
                fault_state = FaultState(is_active=True, drop_rate=drop_rate, delay_ms=port.faultInjector._state.delay_ms)
                port.faultInjector.update_state(fault_state)
                
                return f"Injecting {drop_rate * 100}% drop fault on port {port_name}"
            
            elif fault_type == 'delay':
                delay_ms = params.get('delay_ms', 100)
                fault_state = FaultState(is_active=True, drop_rate=port.faultInjector._state.drop_rate, delay_ms=delay_ms)
                port.faultInjector.update_state(fault_state)
                return f"Injecting {delay_ms}ms delay fault on port {port_name}"
            
            elif fault_type == 'disconnect':
                port.set_disconnected(True)
                port.faultInjector.update_state(FaultState(is_active=True, drop_rate=0.0, delay_ms=0))
                if hasattr(port, 'protocol_instance') and port.protocol_instance:
                    if hasattr(port.protocol_instance, 'transport') and port.protocol_instance.transport:
                        port.protocol_instance.transport.close()
                        
                
                return f"Disconnected port {port_name} - transport closed"
            
            else:
                return f"Unknown fault type: {fault_type}"
        except Exception as e:
            return f"Error injecting fault on {port_name}: {str(e)}"
        
    def clear_fault(self, port_name):
        """Clear fault injections for a specific port."""       
        try:
            ports = self.sim.thread_manager.get_ports()
            port_key = f"{self.cell_id}:{port_name}"
            
            if port_key not in ports:
                return f"Port {port_name} is not bound"
            
            port = ports[port_key]
            
            fault_state = FaultState(is_active=False, drop_rate=0.0, delay_ms=0)
            port.faultInjector.update_state(fault_state)
            
            port.set_disconnected(False)
            
            return f"Cleared faults on port {port_name}"

        except Exception as e:
            return f"Error clearing faults on {port_name}: {str(e)}"




def main():
    parser = argparse.ArgumentParser(description='Network Cell')
    parser.add_argument('--cell-id', required=True, help='Unique cell identifier')
    parser.add_argument('--rpc-port', type=int, required=True, help='XML-RPC port')
    parser.add_argument('--bind-addr', default="localhost", help='Address to bind XML-RPC server (default: localhost)')

    
    args = parser.parse_args()

    cell = Cell(args.cell_id, args.rpc_port, args.bind_addr)
    cell.start()
        
if __name__ == "__main__":
    main()