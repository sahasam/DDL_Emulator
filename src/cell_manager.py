"""
A lightweight daemon to facilitate the creation of cells. 
"""

import subprocess
from xmlrpc.server import SimpleXMLRPCServer
import socket

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()

class CellManagerServer:
    def __init__(self):
        self.running_cells = {}

    def __del__(self):
        if self.running_cells:
            for cell in self.running_cells.keys():
                self.stop_cell(cell)

            print("Teardown complete")
        
        
    def start_cell(self, cell_id: str, rpc_port: int, bind_addr="0.0.0.0"):
        """Starts a cell on this machine"""
        print(f"Received a command to start a cell {cell_id} at port {rpc_port}")
        
        if cell_id in self.running_cells:
            print(f"Cell is already running")
            return f"Cell {cell_id} is already running."
        
        cmd = [
            'python3', 'src/cell.py',
            '--cell_id', cell_id,
            '--rpc_port', str(rpc_port),
            '--bind_addr', bind_addr
        ]

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.running_cells[cell_id] = process
            print(f"Cell {cell_id} started on port {rpc_port}.")
            return f"Cell {cell_id} started on port {rpc_port}."
        
        except Exception as e:
            return f"Failed to start cell {cell_id}: {str(e)}"
        
    def stop_cell(self, cell_id: str):
        """Stops a running cell"""

        print(f"Received a command to stop cell {cell_id}")
        
        if cell_id not in self.running_cells:
            print(f"Cell {cell_id} is not running")
            return f"Cell {cell_id} is not running."
        
        process = self.running_cells[cell_id]
        process.terminate()
        process.wait()
        
        del self.running_cells[cell_id]
        print(f"Cell {cell_id} has stopped successfully")
        return f"Cell {cell_id} stopped successfully."
    
    def list_cells(self):
        """Lists all running cells"""

        print("received a command to list all cells...")
        
        if not self.running_cells:
            print("No cells are currently running")
            return "No cells are currently running."
        
        cell_list = []
        for cell_id, process in self.running_cells.items():
            cell_list.append(f"Cell ID: {cell_id}, PID: {process.pid}")

        print(f"Cell list is {"\n".join(cell_list)}")
        
        return "\n".join(cell_list)

        
    
    
if __name__ == "__main__":
    server = SimpleXMLRPCServer(('0.0.0.0', 8000))
    print(f"Server starting at port 8000...")
    print(f'ip address for this instance is at {get_local_ip()}')


    server.register_instance(CellManagerServer())
    server.serve_forever()
    