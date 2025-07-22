import socket
import xmlrpc.client
import subprocess
import time
import tempfile
import os
import traceback

class ProtoDatacenter:
    def __init__(self):
        self.cells = {}
        self.processes = {}
         
    def add_cell(self, cell_id, rpc_port):
        """Connects to a cell"""
        try:
            cell_script = "src/cell.py"
            cmd = ['python3', cell_script, "--cell-id", cell_id, "--rpc-port", str(rpc_port)]
            
            log_file = f'cell_{cell_id}.log'
            
            print(f"Starting cell {cell_id} on port {rpc_port} with command: {' '.join(cmd)}")
            with open(log_file, 'w') as f:
                process = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
                
            # Store both process and log file (don't overwrite!)
            self.processes[cell_id] = {'process': process, 'log_file': log_file}
            
            time.sleep(2)
            
            # Check if process died
            if process.poll() is not None:
                # Process died - read the log file instead
                try:
                    with open(log_file, 'r') as f:
                        output = f.read()
                    print(f"Cell process died. Log output:\n{output}")
                    return False
                except FileNotFoundError:
                    print(f"Cell process died and no log file found")
                    return False
            
            # Try to connect
            url = f'http://localhost:{rpc_port}'
            proxy = xmlrpc.client.ServerProxy(url)
            
            result = proxy.heartbeat()
            
            print(f"Connected to cell {cell_id} at port {rpc_port}: {result}")
            
            self.cells[cell_id] = proxy
            
            return True

        except Exception as e:
            print(f"Failed to connect to cell {cell_id} at port {rpc_port}: {e}")
            return False

    def remove_cell(self, cell_id):
        """Remove and shutdown a cell"""
        if cell_id in self.cells:
            try:
                self.cells[cell_id].shutdown()  # Fixed typo
            except:
                pass
            finally:
                del self.cells[cell_id]
                
        if hasattr(self, 'processes') and cell_id in self.processes:
            process_info = self.processes[cell_id]
            process_info['process'].terminate()
            process_info['process'].wait()
            
            # Clean up log file
            try:
                import os
                os.remove(process_info['log_file'])
                print(f"Removed log file: {process_info['log_file']}")
            except FileNotFoundError:
                pass
                
            del self.processes[cell_id]
            
        print(f"Cell {cell_id} removed successfully.")
        
             
                    
                      
    def create_link(self, cell1_id, port1_name, cell2_id, port2_name, port1_addr, port2_addr):
        """Create a link between two cells"""
        if cell1_id not in self.cells or cell2_id not in self.cells:
            print(f"One or both cells {cell1_id}, {cell2_id} are not connected.")
            return False
        
        try:
            config1 = {"interface": port1_addr}
            result1 = self.cells[cell1_id].bind_port(port1_name, config1)
            print(f"Cell {cell1_id} bind result: {result1}")
            
            config2 = {"interface": port2_addr}
            result2 = self.cells[cell2_id].bind_port(port2_name, config2)
            print(f"Cell {cell2_id} bind result: {result2}")
            
            return True
        
        except Exception as e:
            print(f"Failed to create link between {cell1_id} and {cell2_id}: {e}")
            return False
        
    def check_status(self):
        """checks status of all cells"""
        print("\n--- Cell Status ---")
        for cell_id, proxy in self.cells.items():
            try:
                status = proxy.heartbeat()
                print(f"Cell {cell_id}: {status}")
            except Exception as e:
                print(f"Cell {cell_id} is unreachable: {e}")
                
    def check_port_status(self, cell_id, port_name):
        """Checks the status of a specific port"""
        if cell_id not in self.cells:
            print(f"Cell {cell_id} is not connected.")
            return
        
        try:
            status = self.cells[cell_id].link_status(port_name)
            print(f"Port {port_name} on cell {cell_id}: {status}")
        except Exception as e:
            print(f"Failed to check port {port_name} on cell {cell_id}: {e}")
            
    def unlink(self, cell1_id, port1_name, cell2_id, port2_name):
        """Unlink two ports between cells"""
        if cell1_id not in self.cells or cell2_id not in self.cells:
            print(f"One or both cells {cell1_id}, {cell2_id} are not connected.")
            return False
        
        try:
            result1 = self.cells[cell1_id].unbind_port(port1_name)
            print(f"Cell {cell1_id} unbind result: {result1}")
            
            result2 = self.cells[cell2_id].unbind_port(port2_name)
            print(f"Cell {cell2_id} unbind result: {result2}")
            
            return True
        
        except Exception as e:
            print(f"Failed to unlink between {cell1_id} and {cell2_id}: {e}")
            return False
        
   
    def get_logs(self, cell_id):
        """Fetch logs from a cell"""
        if hasattr(self, 'processes') and cell_id in self.processes:
            
            log_file = self.processes[cell_id]['log_file']
            try:
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    print(f"=== Last 20 Lines from {cell_id} ===")
                    for line in lines[-20:]:
                        print(line.strip())
            except FileNotFoundError:
                print(f"Log file for cell {cell_id} not found.")
        else:
            print(f'Cell {cell_id} not found or no logs available.')
            
        
    def get_metrics(self, cell_id):
        """Get metrics from a cell"""
        if cell_id not in self.cells:
            print(f"Cell {cell_id} is not connected.")
            return
        
        try:
            metrics = self.cells[cell_id].get_metrics()
            print(f"Metrics for cell {cell_id}: {metrics}")
        except Exception as e:
            print(f"Failed to get metrics for cell {cell_id}: {e}")
            traceback.print_exc()
            
def main():
    dc = ProtoDatacenter()
    
    print("Simple Datacenter Controller")
    print("Commands:")
    print("  add <cell_id> <rpc_port>")
    print("  remove <cell_id>")
    print("  link <cell1> <port1> <cell2> <port2> <addr1> <addr2>")
    print("  unlink <cell1> <port1> <cell2> <port2>")
    print("  status")
    print("  port <cell_id> <port_name>")
    print("  logs <cell_id>")
    print("  get_metrics <cell_id>")
    print("  cleanup")
    print("  quit")
    
    while True:
        try:
            cmd = input("\n> ").strip().split()
            
            if not cmd:
                continue
            
            if cmd[0] == 'quit':
                for process in dc.processes.values():
                    if process['process'].poll() is None:
                        process['process'].terminate()
                        process['process'].wait()
                        print(f"Terminated process for cell {process['log_file']}")
                break
            
            elif cmd[0] == 'add' and len(cmd) == 3:
                cell_id, rpc_port = cmd[1], int(cmd[2])
                dc.add_cell(cell_id, rpc_port)
                
            elif cmd[0] == 'remove' and len(cmd) == 2:
                cell_id = cmd[1]
                dc.remove_cell(cell_id)
                
            elif cmd[0] == 'logs' and len(cmd) == 2:
                cell_id = cmd[1]
                dc.get_logs(cell_id)
            elif cmd[0] == 'get_metrics' and len(cmd) == 2:
                cell_id = cmd[1]
                dc.get_metrics(cell_id)
            elif cmd[0] == 'cleanup':
                if hasattr(dc, 'processes'):
                    for cell_id, info in dc.processes.items():
                        try:
                            os.remove(info['log_file'])
                            print(f"Removed {info['log_file']}")
                        except FileNotFoundError:
                            pass
                
                import glob
                for log_file in glob.glob("cell_*.log"):
                    try:
                        os.remove(log_file)
                        print(f"Removed orphaned {log_file}")
                    except:
                        pass
                
            elif cmd[0] == 'link' and len(cmd) == 7:
                cell1, port1, cell2, port2, addr1, addr2 = cmd[1:]
                dc.create_link(cell1, port1, cell2, port2, addr1, addr2)
                
            elif cmd[0] == 'status':
                dc.check_status()
                
            elif cmd[0] == 'port' and len(cmd) == 3:
                cell_id, port_name = cmd[1], cmd[2]
                dc.check_port_status(cell_id, port_name)
                
            elif cmd[0] == 'unlink' and len(cmd) == 5:
                cell1, port1, cell2, port2 = cmd[1:]
                dc.unlink(cell1, port1, cell2, port2)
            
            
            else:
                print("Invalid command. Type 'quit' to exit.")
        
        except KeyboardInterrupt:
            print("\nExiting...")
            for process in dc.processes.values():
                if process['process'].poll() is None:
                    process['process'].terminate()
                    process['process'].wait()
                    print(f"Terminated process for cell {process['log_file']}")
            
            break

        except Exception as e:
            for process in dc.processes.values():
                if process['process'].poll() is None:
                    process['process'].terminate()
                    process['process'].wait()
                    print(f"Terminated process for cell {process['log_file']}")
            
            print(f"Error: {e}")
            
           
            
if __name__ == "__main__":
    main()