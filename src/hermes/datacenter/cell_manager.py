
import subprocess
from xmlrpc.server import SimpleXMLRPCServer
import socket

"""
A lightweight daemon to facilitate the creation of cells. DEPRECATED
"""
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()

class CellManagerServer:
    def __init__(self):  # Fixed: was **init**
        self.running_cells = {}
        
    def __del__(self):  # Fixed: was **del**
        if self.running_cells:
            for cell in self.running_cells.keys():
                self.stop_cell(cell)
            print("Teardown complete")
        
    def start_cell(self, cell_id: str, rpc_port: int, bind_addr="0.0.0.0"):
        """Starts a cell on this machine"""
        print(f"Received a command to start a cell {cell_id} at port {rpc_port}")
        print(f"Command will use bind_addr: {bind_addr}")
        
        if cell_id in self.running_cells:
            print(f"Cell is already running")
            return f"Cell {cell_id} is already running."
        
        cmd = [
            'python3', 'src/cell.py',
            '--cell-id', cell_id,
            '--rpc-port', str(rpc_port),
            '--bind-addr', bind_addr
        ]
        
        print(f"Executing command: {' '.join(cmd)}")
        
        try:
            # Create log files to capture stdout/stderr
            stdout_file = f'/tmp/cell_{cell_id}_stdout.log'
            stderr_file = f'/tmp/cell_{cell_id}_stderr.log'
            
            with open(stdout_file, 'w') as out, open(stderr_file, 'w') as err:
                process = subprocess.Popen(cmd, stdout=out, stderr=err)
            
            self.running_cells[cell_id] = {
                'process': process,
                'stdout_log': stdout_file,
                'stderr_log': stderr_file
            }
            
            print(f"Cell {cell_id} started on port {rpc_port}.")
            print(f"Logs: stdout={stdout_file}, stderr={stderr_file}")
            return f"Cell {cell_id} started on port {rpc_port}."
        
        except Exception as e:
            print(f"Failed to start cell {cell_id}: {str(e)}")
            return f"Failed to start cell {cell_id}: {str(e)}"
        
    def stop_cell(self, cell_id: str):
        """Stops a running cell"""
        print(f"Received a command to stop cell {cell_id}")
        
        if cell_id not in self.running_cells:
            print(f"Cell {cell_id} is not running")
            return f"Cell {cell_id} is not running."
        
        cell_info = self.running_cells[cell_id]
        process = cell_info['process']
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
        for cell_id, cell_info in self.running_cells.items():
            process = cell_info['process']
            status = "running" if process.poll() is None else "stopped"
            cell_list.append(f"Cell ID: {cell_id}, PID: {process.pid}, Status: {status}")
            
        print(f"Cell list is {chr(10).join(cell_list)}")  # Using chr(10) instead of \n in f-string
        return "\n".join(cell_list)
    
    def get_cell_logs(self, cell_id: str):
        """Get logs for a specific cell"""
        if cell_id not in self.running_cells:
            return f"Cell {cell_id} is not running."
        
        cell_info = self.running_cells[cell_id]
        try:
            with open(cell_info['stdout_log'], 'r') as f:
                stdout = f.read()
            with open(cell_info['stderr_log'], 'r') as f:
                stderr = f.read()
            return f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
        except Exception as e:
            return f"Error reading logs: {str(e)}"

if __name__ == "__main__":  # Fixed: was **name**
    server = SimpleXMLRPCServer(('0.0.0.0', 8000))
    print(f"Server starting at port 8000...")
    print(f'IP address for this instance is at {get_local_ip()}')
    server.register_instance(CellManagerServer())
    server.serve_forever()