#!/usr/bin/env python3

"""
cell.py - individual cell that can be controlled via XML - RPC
"""

from xmlrpc.server import SimpleXMLRPCServer
import threading
import argparse
import time

from hermes.sim.Sim import Sim

class Cell:
    def __init__(self, cell_id, rpc_port):
        self.cell_id = cell_id
        self.rpc_port = rpc_port
        self.sim = None
        self.rpc_server = None
        self.running = False
        
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
            self.sim.thread_manager.register_pipes([read_q, write_q, signal_q])
            
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
        pass
    
    def link_status(self, port_name):
        """Get status of a port"""
        pass
        
    
    def heartbeat(self):
        """Health check"""
        return f"alive:{self.cell_id}"
    
    def shutdown(self):
        """Cell shutdown"""
        print(f"Shutting down cell {self.cell_id}")
        self.running = False
        if self.rpc_server:
            threading.Thread(target=self.rpc_server.shutdown, daemon=True).start()
        
        return "Shutting down..."
    
    
def main():
    parser = argparse.ArgumentParser(description='Network Cell')
    parser.add_argument('--cell-id', required=True, help='Unique cell identifier')
    parser.add_argument('--rpc-port', type=int, required=True, help='XML-RPC port')
    
    args = parser.parse_args()

    cell = Cell(args.cell_id, args.rpc_port)
    cell.start()
        
if __name__ == "__main__":
    main()