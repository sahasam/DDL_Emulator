import socket
import xmlrpc.client
import subprocess
import time

class ProtoDatacenter:
    def __init__(self):
        self.cells = {}
        self.processes = {}
         
    def add_cell(self, cell_id, rpc_port):
        """Connects to a cel"""
        try:
            cell_script = "src/cell.py"
            cmd = ['python3', cell_script, "--cell-id", cell_id, "--rpc-port", str(rpc_port)]
            
            print(f"Starting cell {cell_id} on port {rpc_port} with command: {' '.join(cmd)}")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # if hasattr(self, 'processes'):
            #     self.processes = {}
                
            self.processes[cell_id] = process
            
            time.sleep(3)
            
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                print(f"Cell output: {stdout.decode()}")
                print(f"Cell error: {stderr.decode()}")
            
            
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
                self.cells[cell_id].shutown()
            except:
                pass
            finally:
                del self.cells[cell_id]
                
            if hasattr(self, 'processes') and cell_id in self.processes:
                self.processes[cell_id].terminate()
                self.processes[cell_id].wait()
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
        
    def agent_add(self, cell_id, agent_name):
        """Adds an agent to a cell"""
        if cell_id not in self.cells:
            print(f"Cell {cell_id} is not connected.")
            return
        
        try:
            result = self.cells[cell_id].add_agent(agent_name)
            print(f"Agent {agent_name} added to cell {cell_id}: {result}")
        except Exception as e:
            print(f"Failed to add agent {agent_name} to cell {cell_id}: {e}")
            
    def agent_start(self, cell_id, agent_name):
        """Starts an agent to a cell"""
        
        if cell_id not in self.cells:
            print(f"Cell {cell_id} is not connected.")
            return
        
        try:
            result = self.cells[cell_id].start_agent(agent_name)
            print(f"Agent {agent_name} started in cell {cell_id}: {result}")
            
        except Exception as e:
            print(f"Failed to start agent {agent_name} in cell {cell_id}: {e}")
            
    def agent_stop(self, cell_id, agent_name):
        """Stop agent for a cell"""
        if cell_id not in self.cells:
            print(f"Cell {cell_id} is not connected.")
            return
        
        try:
            result = self.cells[cell_id].stop_agent(agent_name)
            print(f"Agent {agent_name} stopped in cell {cell_id}: {result}")
            
        except Exception as e:
            print(f"Failed to stop agent {agent_name} in cell {cell_id}: {e}")
            
    def agent_list(self, cell_id):
        """Lists all available agents in a cell"""
        
        if cell_id not in self.cells:
            print(f"Cell {cell_id} is not connected.")
            return
        
        try:
            result = self.cells[cell_id].list_agents()
            print(f"Agents in cell: {result}")
            
        except Exception as e:
            print(f"Failed to list agents in cell {cell_id}: {e}")
            
    def agent_status(self, cell_id, agent_name):
        """Get status of an agent in a cell"""
        if cell_id not in self.cells:
            print(f"Cell {cell_id} is not connected.")
            return
        
        try:
            status = self.cells[cell_id].agent_status(agent_name)
            print(f"Agent {agent_name} status in cell {cell_id}: {status}")
        except Exception as e:
            print(f"Failed to get status of agent {agent_name} in cell {cell_id}: {e}")
            
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
    print("  agent_add <cell_id> <agent_name>")
    print("  agent_stop <cell_id> <agent_name>")
    print("  agent_list <cell_id>")
    print("  agent_status <cell_id> <agent_name>")
    print("  quit")
    
    while True:
        try:
            cmd = input("\n> ").strip().split()
            
            if not cmd:
                continue
            
            if cmd[0] == 'quit':
                break
            
            elif cmd[0] == 'add' and len(cmd) == 3:
                cell_id, rpc_port = cmd[1], int(cmd[2])
                dc.add_cell(cell_id, rpc_port)
                
            elif cmd[0] == 'remove' and len(cmd) == 2:
                cell_id = cmd[1]
                dc.remove_cell(cell_id)
                
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
            
            elif cmd[0] == 'agent_add' and len(cmd) == 3:
                cell_id, agent_name = cmd[1], cmd[2]
                dc.agent_add(cell_id, agent_name)
                
            elif cmd[0] == 'agent_stop' and len(cmd) == 3:
                cell_id, agent_name = cmd[1], cmd[2]
                dc.agent_stop(cell_id, agent_name)
                
            elif cmd[0] == 'agent_list' and len(cmd) == 2:
                cell_id = cmd[1]
                dc.agent_list(cell_id)
                
            elif cmd[0] == 'agent_status' and len(cmd) == 3:
                cell_id, agent_name = cmd[1], cmd[2]
                dc.agent_status(cell_id, agent_name)
                
            else:
                print("Invalid command. Type 'quit' to exit.")
        
        except KeyboardInterrupt:
            print("\nExiting...")
            break

        except Exception as e:
            print(f"Error: {e}")
            
            
if __name__ == "__main__":
    main()
        