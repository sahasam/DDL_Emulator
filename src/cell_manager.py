"""
A lightweight daemon to facilitate the creation of cells. 
"""

import subprocess
import xmlrpc

class CellManagerServer:
    def __init__(self):
        self.running_cells = {}
        
        
    def start_cell(self, cell_id: str, rpc_port: int, bind_addr="0.0.0.0"):
        """Starts a cell on this machine"""
        
        if cell_id in self.running_cells:
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
            return f"Cell {cell_id} started on port {rpc_port}."
        
        except Exception as e:
            return f"Failed to start cell {cell_id}: {str(e)}"
        
    def stop_cell(self, cell_id: str):
        """Stops a running cell"""
        
        if cell_id not in self.running_cells:
            return f"Cell {cell_id} is not running."
        
        process = self.running_cells[cell_id]
        process.terminate()
        process.wait()
        
        del self.running_cells[cell_id]
        return f"Cell {cell_id} stopped successfully."
    
    def list_cells(self):
        """Lists all running cells"""
        
        if not self.running_cells:
            return "No cells are currently running."
        
        cell_list = []
        for cell_id, process in self.running_cells.items():
            cell_list.append(f"Cell ID: {cell_id}, PID: {process.pid}")
        
        return "\n".join(cell_list)
    
    
if __name__ == "__main__":
    server = xmlrpc.server.SimpleXMLRPCServer(('0.0.0.0', 8000))
    server.register_instance(CellManagerServer())
    server.serve_forever()
    