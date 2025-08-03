import socket
import xmlrpc.client
import subprocess
import time
import tempfile
import os
import traceback
import yaml
import asyncio


class ProtoDatacenter:
    def __init__(self):
        self.cells = {}
        self.processes = {}
        self.cell_managers = {}
        self.cell_locations = {}
        self.links = {}

    def _get_cell_manager(self, host):
        """Get/create connections to cell manager on host"""

        if host not in self.cell_managers:
            url = f"http://{host}:8000"
            try:
                self.cell_managers[host] = xmlrpc.client.ServerProxy(url)
                self.cell_managers[host].list_cells()  # Test connection
                print(f"Connected to cell manager at {url}")

            except Exception as e:
                print(f"Failed to connect to cell manager at {url}: {e}")
                raise

        return self.cell_managers[host]

    def _is_local_host(self, host):
        """Check if host refers to local machine"""
        return host in ["localhost", "127.0.0.1", "::1"]

    async def _add_local_cell(
        self, cell_id: str, rpc_port: int, host="localhost"
    ) -> dict:
        """Add a cell either locally or remotely"""
        try:
            cell_script = "src/cell.py"
            cmd = [
                "python3",
                cell_script,
                "--cell-id",
                cell_id,
                "--rpc-port",
                str(rpc_port),
            ]

            log_file = f"cell_{cell_id}.log"

            print(
                f"Starting cell {cell_id} on port {rpc_port} with command: {' '.join(cmd)}"
            )
            with open(log_file, "w") as f:
                process = await asyncio.create_subprocess_exec(
                    *cmd, stdout=f, stderr=asyncio.subprocess.STDOUT
                )

            self.processes[cell_id] = {"process": process, "log_file": log_file}

            # Give the process a moment to start
            await asyncio.sleep(1.0)
            if process.returncode is not None:
                try:
                    with open(log_file, "r") as f:
                        output = f.read()
                    print(f"Cell process died. Log output:\n{output}")
                    return {
                        "success": False,
                        "message": f"Cell process for {cell_id} died. Check log file {log_file}",
                    }
                except FileNotFoundError:
                    print(f"Cell process died and no log file found")
                    return {
                        "success": False,
                        "message": f"Cell process for {cell_id} died and no log file found.",
                    }

            url = f"http://localhost:{rpc_port}"
            proxy = xmlrpc.client.ServerProxy(url)

            result = proxy.heartbeat()
            print(f"Connected to cell {cell_id} at port {rpc_port}: {result}")

            self.cells[cell_id] = proxy
            self.cell_locations[cell_id] = host

            return {"success": True, "message": f"Cell {cell_id} added successfully."}

        except Exception as e:
            print(f"Failed to connect to cell {cell_id} at port {rpc_port}: {e}")
            return {
                "success": False,
                "message": f"Failed to connect to cell {cell_id} at port {rpc_port}: {e}",
            }

    def _add_remote_cell(self, cell_id: str, rpc_port: int, host: str) -> dict:
        """Add cell on a remote Mac Mini"""
        try:
            cell_manager = self._get_cell_manager(host)

            print(f"Starting remote cell {cell_id} on {host} at port {rpc_port}")
            result = cell_manager.start_cell(cell_id, rpc_port)
            print(f"Remote cell manager response: {result}")

            time.sleep(2)

            url = f"http://{host}:{rpc_port}"
            proxy = xmlrpc.client.ServerProxy(url)

            heartbeat_result = proxy.heartbeat()
            print(
                f"Connected to remote cell {cell_id} at {host}:{rpc_port}: {heartbeat_result}"
            )

            self.cells[cell_id] = proxy
            self.cell_locations[cell_id] = host

            return {
                "success": True,
                "message": f"Cell {cell_id} added successfully on {host}.",
            }

        except Exception as e:
            print(
                f"Failed to create local "
                f"cell {cell_id} on {host} at port {rpc_port}: {e}"
            )

    async def add_cell(self, cell_id: str, rpc_port: int, host="localhost") -> dict:
        """Connects to a cell"""
        if self._is_local_host(host):
            return await self._add_local_cell(cell_id, rpc_port, host)
        else:
            return self._add_remote_cell(cell_id, rpc_port, host)

    async def remove_cell(self, cell_id: int) -> dict:
        """Remove and shutdown a cell"""
        if cell_id not in self.cell_locations:
            return {"success": False, "message": f"Cell {cell_id} is not connected."}

        host = self.cell_locations[cell_id]

        try:
            if cell_id in self.cells:
                try:
                    self.cells[cell_id].shutdown()
                except:
                    pass
                finally:
                    del self.cells[cell_id]

            if self._is_local_host(host):
                return await self._remove_local_cell(cell_id)
            else:
                return self._remove_remote_cell(cell_id, host)

        except Exception as e:
            print(f"Error removing cell {cell_id}: {e}")
            return {"success": False, "message": f"Error removing cell {cell_id}: {e}"}

    async def _remove_local_cell(self, cell_id: str) -> dict:
        """Remove local cell"""
        if cell_id in self.processes:
            process_info = self.processes[cell_id]

            process_info["process"].terminate()
            await process_info["process"].wait()

            try:
                os.remove(process_info["log_file"])
                print(f"Removed log file {process_info['log_file']}")
            except FileNotFoundError:
                pass

            del self.processes[cell_id]

        if cell_id in self.cell_locations:
            del self.cell_locations[cell_id]

        print(f"Local cell {cell_id} removed successfully.")
        return {
            "success": True,
            "message": f"Local cell {cell_id} removed successfully.",
        }

    def _remove_remote_cell(self, cell_id: str, host: str) -> dict:
        """Remove remote cell via cell manager"""
        try:
            cell_manager = self._get_cell_manager(host)
            result = cell_manager.stop_cell(cell_id)
            print(f"Remote cell manager response: {result}")

            if cell_id in self.cell_locations:
                del self.cell_locations[cell_id]

            return {
                "success": True,
                "message": f"Remote cell {cell_id} removed successfully.",
            }

        except Exception as e:
            print(f"Failed to remove remote cell {cell_id} on {host}: {e}")
            return {
                "success": False,
                "message": f"Failed to remove remote cell {cell_id} on {host}: {e}",
            }

    def create_link(
        self, cell1_id, port1_name, cell2_id, port2_name, port1_addr, port2_addr
    ) -> dict:
        """Create a link between two cells"""
        if cell1_id not in self.cells or cell2_id not in self.cells:
            print(f"One or both cells {cell1_id}, {cell2_id} are not connected.")
            return {
                "success": False,
                "message": f"One or both cells {cell1_id}, {cell2_id} are not connected.",
            }

        try:
            config1 = {"interface": port1_addr}
            result1 = self.cells[cell1_id].bind_port(port1_name, config1)
            print(f"Cell {cell1_id} bind result: {result1}")

            config2 = {"interface": port2_addr}
            result2 = self.cells[cell2_id].bind_port(port2_name, config2)

            print(f"Cell {cell2_id} bind result: {result2}")

            self.links[(cell1_id, port1_name, cell2_id, port2_name)] = (
                port1_addr,
                port2_addr,
            )

            return {
                "success": True,
                "message": f"Linked {cell1_id}:{port1_name} and {cell2_id}:{port2_name}",
            }

        except Exception as e:
            print(f"Failed to create link between {cell1_id} and {cell2_id}: {e}")
            return {
                "success": False,
                "message": f"Failed to create link between {cell1_id} and {cell2_id}: {e}",
            }

    def check_status(self):
        """Check status of all cells (local and remote)"""
        print("\n--- Cell Status ---")
        output = ["--- Cell Status ---"]
        try:
            for cell_id, proxy in self.cells.items():
                host = self.cell_locations.get(cell_id, "unknown")
                try:
                    status = proxy.heartbeat()
                    print(f"Cell {cell_id} ({host}): {status}")
                    output.append(f"Cell {cell_id} ({host}): {status}")

                except Exception as e:
                    print(f"Cell {cell_id} ({host}) is unreachable: {e}")
                    output.append(f"Cell {cell_id} ({host}) is unreachable: {e}")

            return {"success": True, "message": "\n".join(output)}

        except Exception as e:
            print(f"Failed to check status: {e}")
            traceback.print_exc()
            return {"success": False, "message": f"Failed to check status: {e}"}

    def check_port_status(self, cell_id, port_name) -> dict:
        """Checks the status of a specific port"""
        if cell_id not in self.cells:
            print(f"Cell {cell_id} is not connected.")
            return

        try:
            status = self.cells[cell_id].link_status(port_name)
            print(f"Port {port_name} on cell {cell_id}: {status}")
            return {
                "success": True,
                "message": f"Port {port_name} on cell {cell_id}: {status}",
            }
        except Exception as e:
            print(f"Failed to check port {port_name} on cell {cell_id}: {e}")
            return {
                "success": False,
                "message": f"Failed to check port {port_name} on cell {cell_id}: {e}",
            }

    def bind_port(self, cell_id: str, port_name: str, addr: str) -> dict:
        if cell_id not in self.cells:
            print(f"Cell {cell_id} is not connected.")
            return {"success": False, "message": f"Cell {cell_id} is not connected."}

        if port_name in self.cells[cell_id].ports:
            print(f"Cell {cell_id} already has port {port_name} bound.")
            return {
                "success": False,
                "message": f"Cell {cell_id} already has port {port_name} bound.",
            }

        try:
            print(f"Binding port {port_name} on cell {cell_id} to address {addr}")
            result = self.cells[cell_id].bind_port(port_name, {"interface": addr})

            print(f"Port bind result: {result}")
            return {
                "success": True,
                "message": f"Port {port_name} on cell {cell_id} bound to {addr}",
            }

        except Exception as e:
            print(f"Failed to bind port {port_name} on cell {cell_id}: {e}")
            return {
                "success": False,
                "message": f"Failed to bind port {port_name} on cell {cell_id}: {e}",
            }

    def unbind_port(self, cell_id: str, port_name: str) -> dict:
        if cell_id not in self.cells:
            print(f"Cell {cell_id} is not connected.")
            return {"success": False, "message": f"Cell {cell_id} is not connected."}

        if port_name not in self.cells[cell_id].ports:
            print(f"Cell {cell_id} does not have port {port_name} bound.")
            return {
                "success": False,
                "message": f"Cell {cell_id} does not have port {port_name} bound.",
            }

        try:
            result = self.cells[cell_id].unbind_port(port_name)
            print(f"Port {port_name} on cell {cell_id} unbound: {result}")
            return {
                "success": True,
                "message": f"Port {port_name} on cell {cell_id} unbound successfully.",
            }

        except:
            print(f"Failed to unbind port {port_name} on cell {cell_id}")
            return {
                "success": False,
                "message": f"Failed to unbind port {port_name} on cell {cell_id}",
            }

    def unlink(
        self, cell1_id: str, port1_name: str, cell2_id: str, port2_name: str
    ) -> dict:
        """Unlink two ports between cells"""
        if cell1_id not in self.cells or cell2_id not in self.cells:
            print(f"One or both cells {cell1_id}, {cell2_id} are not connected.")
            return {
                "success": False,
                "message": f"One or both cells {cell1_id}, {cell2_id} are not connected.",
            }

        try:
            result1 = self.cells[cell1_id].unbind_port(port1_name)
            print(f"Cell {cell1_id} unbind result: {result1}")

            result2 = self.cells[cell2_id].unbind_port(port2_name)
            print(f"Cell {cell2_id} unbind result: {result2}")

            link_key = (cell1_id, port1_name, cell2_id, port2_name)
            if link_key in self.links:
                del self.links[link_key]
                print(f"Unlinked {cell1_id}:{port1_name} and {cell2_id}:{port2_name}")
            else:
                print(
                    f"No link found between {cell1_id}:{port1_name} and {cell2_id}:{port2_name}"
                )

            return {
                "success": True,
                "message": f"Unlinked {cell1_id}:{port1_name} and {cell2_id}:{port2_name}",
            }

        except Exception as e:
            print(f"Failed to unlink between {cell1_id} and {cell2_id}: {e}")
            return {
                "success": False,
                "message": f"Failed to unlink between {cell1_id} and {cell2_id}: {e}",
            }

    def get_logs(self, cell_id: str) -> str:
        """Fetch logs from a cell"""
        if hasattr(self, "processes") and cell_id in self.processes:

            log_file = self.processes[cell_id]["log_file"]
            try:
                with open(log_file, "r") as f:
                    lines = f.readlines()
                    print(f"=== Last 20 Lines from {cell_id} ===")
                    for line in lines[-20:]:
                        print(line.strip())

                    return "".join(lines).strip()
            except FileNotFoundError:
                print(f"Log file for cell {cell_id} not found.")
                return "Cell not found or no logs available."
        else:
            print(f"Cell {cell_id} not found or no logs available.")
            return "Cell not found or no logs available."

    def get_metrics(self, cell_id) -> dict:
        """Get metrics from a cell (works for both local and remote)"""
        if cell_id not in self.cells:
            print(f"Cell {cell_id} is not connected.")
            return {"success": False, "message": f"Cell {cell_id} is not connected."}

        try:
            metrics = self.cells[cell_id].get_metrics()
            host = self.cell_locations.get(cell_id, "unknown")
            print(f"Metrics for cell {cell_id} ({host}): {metrics}")
            return {"success": True, **metrics}
        except Exception as e:
            print(f"Failed to get metrics for cell {cell_id}: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "message": f"Failed to get metrics for cell {cell_id}: {e}",
            }

    def inject_fault(self, cell_id, port_name, fault_type, **kwargs) -> dict:
        """Inject a fault into a cell (works for both local and remote)"""
        if cell_id not in self.cells:
            print(f"Cell {cell_id} is not connected.")
            return {"success": False, "message": f"Cell {cell_id} is not connected."}

        try:
            print(
                f"Injecting fault '{fault_type}' into cell {cell_id} on port {port_name} with args: {kwargs}"
            )
            result = self.cells[cell_id].inject_fault(port_name, fault_type, kwargs)
            host = self.cell_locations.get(cell_id, "unknown")
            print(f"Fault injected into cell {cell_id} ({host}): {result}")
            return {
                "success": True,
                "message": f"Fault injected into cell {cell_id} ({host}): {result}",
            }

        except Exception as e:
            print(f"Failed to inject fault into cell {cell_id}: {e}")
            return {
                "success": False,
                "message": f"Failed to inject fault into cell {cell_id}: {e}",
            }

    def clear_fault(self, cell_id, port_name) -> dict:
        """Clear a fault in a cell (works for both local and remote)"""
        if cell_id not in self.cells:
            print(f"Cell {cell_id} is not connected.")
            return {"success": False, "message": f"Cell {cell_id} is not connected."}

        try:
            result = self.cells[cell_id].clear_fault(port_name)
            host = self.cell_locations.get(cell_id, "unknown")
            print(f"Fault cleared in cell {cell_id} ({host}): {result}")
            return {
                "success": True,
                "message": f"Fault cleared in cell {cell_id} ({host}): {result}",
            }

        except Exception as e:
            print(f"Failed to clear fault in cell {cell_id}: {e}")
            return {
                "success": False,
                "message": f"Failed to clear fault in cell {cell_id}: {e}",
            }

    async def load_topology(self, topology_file) -> dict:
        """Load topology with support for remote hosts"""
        try:
            with open(topology_file, "r") as f:
                config = yaml.safe_load(f)

            topology = config["topology"]

            print("--- Creating Cells ---")
            tasks = []
            for cell_config in topology.get("cells", []):
                cell_id = cell_config["id"]
                rpc_port = cell_config["rpc_port"]
                host = cell_config.get("host", "localhost")  # Default to localhost

                print(f"Scheduling cell {cell_id} creation on {host}:{rpc_port}")
                tasks.append(self.add_cell(cell_id, rpc_port, host))

            results = await asyncio.gather(*tasks)

            for result, config in zip(results, topology.get("cells", [])):
                if not result["success"]:
                    cid = config["id"]
                    h = config.get("host", "localhost")
                    p = config["rpc_port"]
                    print(f"Failed to create cell {cid} on {h}:{p}")
                    return {
                        "success": False,
                        "message": f"Failed to create cell {cid} on {h}:{p}",
                    }

            print("--- Creating Links ---")
            for link_index, link_config in enumerate(topology.get("links", [])):
                success = self._configure_link_from_config(link_config, link_index)
                if not success:
                    print(f"Failed to create link {link_index} from config")
                    return {
                        "success": False,
                        "message": f"Failed to create link {link_index} from config",
                    }

            print("--- Creating bindings (if supplied) ---")
            for cell_bindings in topology.get("bindings", []):
                cell_id = cell_bindings["cell_id"]
                port_name = cell_bindings["portname"]
                addr = cell_bindings.get("addr", {})
                self.cells[cell_id].bind_port(port_name, addr)

            print("--- Topology Loaded Successfully ---")
            return {"success": True, "message": "Topology loaded successfully."}

        except Exception as e:
            print(f"Failed to load topology from {topology_file}: {e}")
            traceback.print_exc()
            return {"success": False, "message": f"Failed to load topology: {e}"}

    def _configure_link_from_config(self, link_config, link_index):
        """Create links based on transport type with host validation"""
        cell1 = link_config["cell1"]
        port1 = link_config["port1"]
        cell2 = link_config["cell2"]
        port2 = link_config["port2"]

        transport = link_config.get("transport", "udp")
        config = link_config.get("config", {})

        print(
            f"Creating {transport} link {link_index} between {cell1}:{port1} and {cell2}:{port2}"
        )

        if transport == "udp":
            return self._configure_udp_link(
                cell1, port1, cell2, port2, config, link_index
            )
        elif transport == "interface":
            return self._configure_interface_link(
                cell1, port1, cell2, port2, config, link_index
            )
        else:
            print(f"Unsupported transport type: {transport}")
            return False

    def _configure_udp_link(self, cell1, port1, cell2, port2, config, link_index):
        """Create a UDP link between two cells (must be on same host)"""
        # Validate both cells are on same host
        host1 = self.cell_locations.get(cell1)
        host2 = self.cell_locations.get(cell2)

        # if host1 != host2:
        #     print(f"ERROR: UDP links only work between cells on the same host. {cell1} is on {host1}, {cell2} is on {host2}")
        #     return False

        if "addr1" in config and "addr2" in config:
            addr1 = config["addr1"]
            addr2 = config["addr2"]
        else:
            base_port = 5000 + link_index * 2
            addr1 = f"127.0.0.1:{base_port}:{base_port + 1}"
            addr2 = f"127.0.0.1:{base_port+1}:{base_port}"

        return self.create_link(cell1, port1, cell2, port2, addr1, addr2)

    def _configure_interface_link(self, cell1, port1, cell2, port2, config, link_index):
        """Create a network interface link (can work across hosts)"""
        interface1 = config.get("interface1", f"en0")
        interface2 = config.get("interface2", f"en1")

        try:
            config1 = {"interface": interface1}
            result1 = self.cells[cell1].bind_port(port1, config1)
            print(f"Cell {cell1} bind result: {result1}")

            config2 = {"interface": interface2}
            result2 = self.cells[cell2].bind_port(port2, config2)
            print(f"Cell {cell2} bind result: {result2}")

            # Track the link
            self.links[(cell1, port1, cell2, port2)] = (interface1, interface2)

            return True
        except Exception as e:
            print(f"Failed to create interface link between {cell1} and {cell2}: {e}")
            return False
    def broadcast_message(self, from_cell_id, payload) -> dict:
        """Broadcast message from one cell to all other cells"""
        if from_cell_id not in self.cells:
            return {'success': False, 'message': f'Source cell {from_cell_id} not connected'}
        
        results = []
        for target_cell_id in self.cells:
            if target_cell_id != from_cell_id:
                result = self.send_message(from_cell_id, target_cell_id, payload)
                results.append(f"{target_cell_id}: {result['message']}")
        
        return {'success': True, 'message': f'Broadcast from {from_cell_id} to {len(results)} cells', 'results': results}
    
    def get_messages(self, cell_id, from_node=None) -> dict:
        """Get messages from a cell"""
        if cell_id not in self.cells:
            return {'success': False, 'message': f'Cell {cell_id} not connected'}
        
        try:
            # Convert None to empty string for XML-RPC
            from_node_param = from_node if from_node is not None else ""
            response = self.cells[cell_id].get_messages(from_node_param)
            
            if isinstance(response, dict) and "error" in response:
                print(f"Error getting messages from {cell_id}: {response['error']}")
                return {'success': False, 'message': response['error']}
            
            messages = response if isinstance(response, list) else []
            print(f"Messages for {cell_id}: {len(messages)} messages")
            for msg in messages:
                print(f"  From {msg.get('source', 'unknown')}: {msg.get('payload', '')}")
            return {'success': True, 'messages': messages}
            
        except Exception as e:
            print(f"Failed to get messages from {cell_id}: {e}")
            return {'success': False, 'message': f'Failed to get messages: {e}'}
    def clear_messages(self, cell_id) -> dict:
        """Clear all messages from a cell"""
        if cell_id not in self.cells:
            return {'success': False, 'message': f'Cell {cell_id} not connected'}
        
        try:
            response = self.cells[cell_id].clear_messages()
            
            if isinstance(response, dict) and "error" in response:
                print(f"Error clearing messages from {cell_id}: {response['error']}")
                return {'success': False, 'message': response['error']}
            
            print(f"Cleared messages from {cell_id}: {response['message']}")
            return {'success': True, 'message': response['message']}
            
        except Exception as e:
            print(f"Failed to clear messages from {cell_id}: {e}")
            return {'success': False, 'message': f'Failed to clear messages: {e}'}

    def pop_message(self, cell_id) -> dict:
        """Get and remove oldest message from a cell"""
        if cell_id not in self.cells:
            return {'success': False, 'message': f'Cell {cell_id} not connected'}
        
        try:
            response = self.cells[cell_id].pop_message()
            
            if isinstance(response, dict) and "error" in response:
                print(f"Error popping message from {cell_id}: {response['error']}")
                return {'success': False, 'message': response['error']}
            
            if response and response.get('message') == "No messages available":
                print(f"No messages available for {cell_id}")
                return {'success': True, 'message': None}
            
            print(f"Popped message from {cell_id}: {response}")
            return {'success': True, 'message': response}
            
        except Exception as e:
            print(f"Failed to pop message from {cell_id}: {e}")
            return {'success': False, 'message': f'Failed to pop message: {e}'}
    
    def send_message(self, from_cell_id, to_cell_id, payload) -> dict:
        """Send message from one cell to another"""
        if from_cell_id not in self.cells:
            return {'success': False, 'message': f'Source cell {from_cell_id} not connected'}
        
        try:
            result = self.cells[from_cell_id].send_message(to_cell_id, payload)
            print(f"Message sent from {from_cell_id} to {to_cell_id}: {result}")
            return {'success': True, 'message': result}
        except Exception as e:
            print(f"Failed to send message from {from_cell_id} to {to_cell_id}: {e}")
            return {'success': False, 'message': f'Failed to send message: {e}'}

    def get_topology_status(self) -> dict:
        """Get current topology status including host information"""
        try:
            status = {"cells": {}, "cell_managers": {}, "links": len(self.links)}

            # Cell status with host info
            for cell_id, proxy in self.cells.items():
                host = self.cell_locations.get(cell_id, "unknown")
                try:
                    heartbeat = proxy.heartbeat()
                    status["cells"][cell_id] = {
                        "host": host,
                        "status": "alive",
                        "heartbeat": heartbeat,
                    }
                except:
                    status["cells"][cell_id] = {"host": host, "status": "unreachable"}

            for host, manager in self.cell_managers.items():
                try:
                    cells = manager.list_cells()
                    status["cell_managers"][host] = {
                        "status": "connected",
                        "managed_cells": cells,
                    }
                except:
                    status["cell_managers"][host] = {"status": "unreachable"}

            return {"success": True, "data": status}

        except Exception as e:
            return {"success": False, "message": f"Failed to get topology status: {e}"}

    def trigger_manual_fsp(self, cell_id) -> dict:
        """Manually trigger FSP with specified cell as general"""
        if cell_id not in self.cells:
            return {'success': False, 'message': f'Cell {cell_id} not connected'}
        
        try:
            result = self.cells[cell_id].trigger_manual_fsp_as_general()
            return {'success': True, 'general': cell_id, 'result': result}
        except Exception as e:
            return {'success': False, 'message': f'Error triggering manual FSP: {e}'}
  

    def get_all_fsp_status(self) -> dict:
        """Get FSP status from all cells"""
        statuses = {}
        
        for cell_id in self.cells:
            try:
                status = self.cells[cell_id].get_fsp_status()
                statuses[cell_id] = status
            except Exception as e:
                statuses[cell_id] = {'error': str(e)}
        
        return {"success": True, "data": statuses}

def help():
    print("Datacenter Controller")
    print("Commands:")
    print("  add <cell_id> <rpc_port> [<host>]")
    print("  remove <cell_id>")
    print("  link <cell1> <port1> <cell2> <port2> <addr1> <addr2>")
    print("  unlink <cell1> <port1> <cell2> <port2>")
    print("  status")
    print("  topology_status")
    print("  port <cell_id> <port_name>")
    print("  logs <cell_id>")
    print("  get_metrics <cell_id>")
    print("  inject_fault <cell_id> <port_name> <fault_type> [<args>]")
    print("      fault_type: drop|delay|disconnect")
    print("  clear_fault <cell_id> <port_name>")
    print("  lt <topology_file>")
    print("  send <from_cell> <to_cell> <message>")
    print("  messages <cell_id> [<from_node>]")
    print("  pop <cell_id>")
    print("  clear_messages <cell_id>")
    print("  broadcast <from_cell> <message>")
    print("  teardown")
    print("  cleanup")
    print("  establish_topology")
    print("  fsp_status")
    print(' clear_messages <cell_id>')
    print("  quit")


async def main():
    dc = ProtoDatacenter()

    help()

    while True:
        try:
            cmd = input("\n> ").strip().split()

            if not cmd:
                continue

            if cmd[0] == "quit":
                for process in dc.processes.values():
                    if process["process"].poll() is None:
                        process["process"].terminate()
                        process["process"].wait()
                        print(f"Terminated process for cell {process['log_file']}")
                break

            elif cmd[0] == "add" and len(cmd) == 3:
                cell_id, rpc_port = cmd[1], int(cmd[2])
                await dc.add_cell(cell_id, rpc_port)

            elif cmd[0] == "remove" and len(cmd) == 2:
                cell_id = cmd[1]
                await dc.remove_cell(cell_id)

            elif cmd[0] == "logs" and len(cmd) == 2:
                cell_id = cmd[1]
                dc.get_logs(cell_id)
            elif cmd[0] == "get_metrics" and len(cmd) == 2:
                cell_id = cmd[1]
                dc.get_metrics(cell_id)
            elif cmd[0] == "cleanup":
                if hasattr(dc, "processes"):
                    for cell_id, info in dc.processes.items():
                        try:
                            os.remove(info["log_file"])
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

            elif cmd[0] == "link" and len(cmd) == 7:
                cell1, port1, cell2, port2, addr1, addr2 = cmd[1:]
                dc.create_link(cell1, port1, cell2, port2, addr1, addr2)

            elif cmd[0] == "status":
                dc.check_status()

            elif cmd[0] == "port" and len(cmd) == 3:
                cell_id, port_name = cmd[1], cmd[2]
                dc.check_port_status(cell_id, port_name)

            elif cmd[0] == "unlink" and len(cmd) == 5:
                cell1, port1, cell2, port2 = cmd[1:]
                dc.unlink(cell1, port1, cell2, port2)

            elif cmd[0] == "inject_fault" and len(cmd) >= 4:
                cell_id, port_name, fault_type = cmd[1:4]
                kwargs = {}

                if fault_type == "drop" and len(cmd) == 5:
                    kwargs["drop_rate"] = float(cmd[4])
                elif fault_type == "delay" and len(cmd) == 5:
                    kwargs["delay_ms"] = int(cmd[4])
                elif fault_type == "disconnect" and len(cmd) == 5:
                    pass

                dc.inject_fault(cell_id, port_name, fault_type, **kwargs)
            elif cmd[0] == 'clear_messages' and len(cmd) == 2:
                cell_id = cmd[1]
                dc.clear_messages(cell_id)
            elif cmd[0] == "clear_fault" and len(cmd) == 3:
                cell_id, port_name = cmd[1:]
                dc.clear_fault(cell_id, port_name)

            elif cmd[0] == "lt" and len(cmd) == 2:
                topology_file = cmd[1]
                await dc.load_topology(topology_file)

            elif cmd[0] == "teardown":
                await dc.teardown()
                    
                
            elif cmd[0] == 'send' and len(cmd) >= 4:
                from_cell, to_cell = cmd[1], cmd[2]
                payload = ' '.join(cmd[3:])  # Join remaining args as message
                dc.send_message(from_cell, to_cell, payload)

            elif cmd[0] == 'messages' and len(cmd) >= 2:
                cell_id = cmd[1]
                from_node = cmd[2] if len(cmd) == 3 else None
                dc.get_messages(cell_id, from_node)

            elif cmd[0] == 'pop' and len(cmd) == 2:
                cell_id = cmd[1]
                dc.pop_message(cell_id)

            elif cmd[0] == 'broadcast' and len(cmd) >= 3:
                from_cell = cmd[1]
                payload = ' '.join(cmd[2:])
                dc.broadcast_message(from_cell, payload)
            
          

            elif cmd[0] == 'fsp_status':
                statuses = dc.get_all_fsp_status()
                for cell_id, status in statuses.items():
                    print(f"{cell_id}: {status}")

            elif cmd[0] == 'manual_fsp' and len(cmd) == 2:
                cell_id = cmd[1]
                result = dc.trigger_manual_fsp(cell_id)
                print(f"Manual FSP result: {result}")

            elif cmd[0] == "help":
                help()

            else:
                print("Invalid command. Type 'quit' to exit.")

        except KeyboardInterrupt:
            print("\nExiting...")
            await dc.teardown()
           

            break

        except Exception as e:
            await dc.teardown()
            
            
            print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
