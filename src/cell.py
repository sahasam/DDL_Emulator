#!/usr/bin/env python3

"""
cell.py - individual cell that can be controlled via XML - RPC
"""

from xmlrpc.server import SimpleXMLRPCServer
import threading
import argparse
import time

from hermes.sim.Sim import Sim
from hermes.port.Agent import Agent

class Cell:
    def __init__(self, cell_id, rpc_port):
        self.cell_id = cell_id
        self.rpc_port = rpc_port
        self.sim = None
        self.rpc_server = None
        self.running = False
        self.port_queues = {}
        
        
    def start(self):
        """Start the cell with XML-RPC server."""
        self.start_time = time.time()
        self.sim = Sim()
        self.sim.configure_logging()
        
        # start rpc server
        self._start_rpc_server()
        self.agent = Agent(self.cell_id, self.sim.thread_manager)
        
        if not self.agent.is_alive():
            self.agent.start()
            print(f"Agent started for cell {self.cell_id}")
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.shutdown()
        
        # start event loop
        
    def _start_rpc_server(self):
        """Start the XML-RPC server in the background"""
        
        def run_server():
            self.running = True
            self.rpc_server = SimpleXMLRPCServer(("localhost", self.rpc_port), allow_none=True, logRequests=False)
            
            self.rpc_server.register_function(self.bind_port, "bind_port")
            self.rpc_server.register_function(self.unbind_port, "unbind_port")
            self.rpc_server.register_function(self.shutdown, "shutdown")
            self.rpc_server.register_function(self.heartbeat, "heartbeat")
            self.rpc_server.register_function(self.link_status, "link_status")
            
            # self.rpc_server.register_function(self.add_agent, "add_agent")
            # self.rpc_server.register_function(self.stop_agent, "stop_agent")
            # self.rpc_server.register_function(self.list_agents, "list_agents")
            # self.rpc_server.register_function(self.agent_status, "agent_status")
            self.rpc_server.register_function(self.get_metrics, "get_metrics")
            
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

        if hasattr(self, 'agent') and self.agent.is_alive():
            self.agent.stop()
            self.agent.join(timeout=2.0) 
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
            
            # Port metrics - only return serializable data
            ports = self.sim.thread_manager.get_ports()
            for port_id, port in ports.items():
                port_info = {
                    'name': port.name,
                    'status': 'alive' if port.is_alive() else 'dead'
                }
                
                # Safely get link state as string
                if hasattr(port, 'protocol_instance') and port.protocol_instance:
                    if hasattr(port.protocol_instance, 'link_state'):
                        # Convert enum to string if needed
                        link_state = port.protocol_instance.link_state
                        if hasattr(link_state, 'value'):
                            port_info['link_state'] = str(link_state.value)
                        else:
                            port_info['link_state'] = str(link_state)
                    else:
                        port_info['link_state'] = 'unknown'
                else:
                    port_info['link_state'] = 'no_protocol'
                    
                metrics['ports'][port_id] = port_info
            
            # Agent metrics - only return serializable data
            if hasattr(self, 'agent') and self.agent.is_alive():
                try:
                    snapshot = self.agent.get_snapshot()
                    
                    trees_info = {}
                    for tree_id, tree_data in snapshot.get('trees', {}).items():
                        if hasattr(tree_data, 'to_dict'):
                            trees_info[tree_id] = tree_data.to_dict()
                        else:
                            trees_info[tree_id] = str(tree_data)
                            
                            
                    port_paths_info = {}
                    for path_id, path_data in snapshot.get('port_paths', {}).items():
                        if hasattr(path_data, 'serialize'):
                            try:
                                port_paths_info[path_id] = path_data.serialize()
                            except:
                                port_paths_info[path_id] = str(path_data)
                        else:
                            port_paths_info[path_id] = str(path_data)
                            
                    metrics['agent'] = {
                        'status': 'running',
                        'trees_count': len(trees_info),
                        'trees': trees_info,
                        'node_id': str(snapshot.get('node_id', '')),
                        'port_paths': port_paths_info
                    }
           
                except Exception as e:
                        metrics['agent'] = {
                            'status': 'running',
                            'error': str(e)
                        }
                else:
                    metrics['agent'] = {'status': 'stopped'}
            
                return metrics
            
        except Exception as e:
            return {'error': str(e), 'cell_id': self.cell_id}






def main():
    parser = argparse.ArgumentParser(description='Network Cell')
    parser.add_argument('--cell-id', required=True, help='Unique cell identifier')
    parser.add_argument('--rpc-port', type=int, required=True, help='XML-RPC port')
    
    args = parser.parse_args()

    cell = Cell(args.cell_id, args.rpc_port)
    cell.start()
        
if __name__ == "__main__":
    main()