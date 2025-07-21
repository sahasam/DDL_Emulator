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
        self.agents = {}
        
        
    def start(self):
        """Start the cell with XML-RPC server."""
        self.sim = Sim()
        self.sim.configure_logging()
        
        # start rpc server
        self._start_rpc_server()
        
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
            
            self.rpc_server.register_function(self.add_agent, "add_agent")
            self.rpc_server.register_function(self.stop_agent, "stop_agent")
            self.rpc_server.register_function(self.list_agents, "list_agents")
            self.rpc_server.register_function(self.agent_status, "agent_status")
            
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

        for agent_name in list(self.agents.keys()):
            self.stop_agent(agent_name)
            
        if self.rpc_server:
            threading.Thread(target=self.rpc_server.shutdown, daemon=True).start()
        
        return "Shutting down..."
    
    def add_agent(self, agent_name):
        """Adds a new agent to the cell"""
        if agent_name in self.agents:
            return f"Agent {agent_name} already exists"
        
        agent = Agent(self.cell_id, self.sim.thread_manager)
        
        self.agents[agent_name] = agent
        
        if not agent.is_alive():
            agent.start()
            return f"Agent {agent_name} added and started successfully"
        else:
            return f"Agent {agent_name} is already running"          
    
    def stop_agent(self, agent_name):
        """Stops an agent in the cell."""
        
        if agent_name not in self.agents:
            return f"Agent {agent_name} does not exist"
        
        agent = self.agents[agent_name]
        
        if agent.is_alive():
            agent.stop()
            agent.join(timeout=2.0)
            
        del self.agents[agent_name]
        return f'Agent {agent_name} stopped and removed successfully'
    
    def list_agents(self):
        """Lists all available agents"""
        if not self.agents:
            return "No agents available"
        
        results = []
        for name, agent in self.agents.items():
            status = "running" if agent.is_alive() else "stopped"
            results.append(f"Agent {name}: {status}")
            
        return ", ".join(results)
    
    def agent_status(self, agent_name):
        """Get status of an agent"""
        if agent_name not in self.agents:
            return f"Agent {agent_name} does not exist"
        
        agent = self.agents[agent_name]
        
        return f"Agent {agent_name}: running" if agent.is_alive() else f"Agent {agent_name}: stopped"
        
    
def main():
    parser = argparse.ArgumentParser(description='Network Cell')
    parser.add_argument('--cell-id', required=True, help='Unique cell identifier')
    parser.add_argument('--rpc-port', type=int, required=True, help='XML-RPC port')
    
    args = parser.parse_args()

    cell = Cell(args.cell_id, args.rpc_port)
    cell.start()
        
if __name__ == "__main__":
    main()