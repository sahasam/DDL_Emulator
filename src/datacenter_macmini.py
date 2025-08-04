import asyncio
import json
import websockets.server
import tempfile
from datacenter import ProtoDatacenter
from typing import Set
import threading
import time
import socket
import uuid
import os
import signal

class DataCenterServer:
    def __init__(self, host="localhost", port=8765):
        self.host = host
        self.port = port
        self.dc = ProtoDatacenter()
        self.websocket_clients: Set = set()
        self.shutdown_event = asyncio.Event()
        self.server = None

    async def start(self):
        """Start the websocket server"""
        async def handle_client(websocket, path):
            self.websocket_clients.add(websocket)
            print(f"Client connected: {websocket.remote_address}")

            self.periodic_task = asyncio.create_task(self.periodic_updates())

            try:
                async for message in websocket:
                    await self.handle_message(websocket, message)

            except websockets.exceptions.ConnectionClosed:
                print(f"Client disconnected: {websocket.remote_address}")
            except Exception as e:
                print(f"Error handling client: {e}")

            finally:
                self.websocket_clients.discard(websocket)
                print(f"Client removed: {websocket.remote_address}")

        # Start the WebSocket server
        self.server = await websockets.server.serve(
            handle_client,
            self.host,
            self.port,
            ping_interval=None,
            ping_timeout=None,
        )
        print(f"WebSocket server started on ws://{self.host}:{self.port}")

    async def stop(self):
        """Stop the server and cleanup"""
        print("Stopping server...")
        self.shutdown_event.set()

        if hasattr(self, 'periodic_task'):
            self.periodic_task.cancel()
        
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        
        await self.teardown_all_cells()
        print("Server stopped successfully.")

    async def handle_message(self, websocket, message):
        """Handle incoming websocket messages"""
        try:
            data = json.loads(message)
            command = data.get("command")
            params = data.get("params", {})

            result = await self.execute_command(command, params)

            response = {
                "type": "command_response",
                "command": command,
                "result": result,
                "success": result.get("success", True),
            }

            await websocket.send(json.dumps(response))

        except Exception as e:
            error_response = {
                "type": "error",
                "message": str(e),
            }
            try:
                await websocket.send(json.dumps(error_response))
            except:
                print(f"Failed to send error response: {e}")

    async def execute_command(self, command, params):
        """Executes a datacenter command and return results"""
        try:
            if command == "get_status":
                status = {}
                for cell_id, proxy in self.dc.cells.items():
                    try:
                        # Make this async if proxy.heartbeat() is async
                        status[cell_id] = proxy.heartbeat()
                    except:
                        status[cell_id] = "unreachable"

                return {"success": True, "data": status}

            elif command == "get_metrics":
                cell_id = params.get("cell_id")

                if cell_id in self.dc.cells:
                    try:
                        metrics = self.dc.cells[cell_id].get_metrics()
                        return metrics
                    except Exception as e:
                        return {
                            "success": False,
                            "message": f"Failed to get metrics: {str(e)}",
                        }
                else:
                    return {"success": False, "message": f"Cell {cell_id} not found."}
                
            elif command == "shutdown":
                try:
                    # Trigger shutdown
                    asyncio.create_task(self.stop())
                    return {"success": True, "message": "Datacenter shutdown initiated."}
                except Exception as e:
                    return {"success": False, "message": f"Issue with shutdown: {e}"}

            elif command == "teardown":
                try:
                    for cell_id in list(self.dc.cells.keys()):
                        await self.dc.remove_cell(cell_id)
                    return {"success": True, "message": "All cells removed successfully."}
                except Exception as e:
                    return {"success": False, "message": f"Teardown failed: {str(e)}"}

            elif command == 'manual_fsp':
                try:
                    cell_name = next(iter(self.dc.cells))
                    result = self.dc.trigger_manual_fsp(cell_name)
                    return result
                except Exception as e:
                    return {"success": False, "message": f"Manual FSP failed: {str(e)}"}
                
            elif command == 'all_fsp_status':
                try:
                    result = self.dc.get_all_fsp_status()
                    return result
                except Exception as e:
                    return {"success": False, "message": f"Get FSP status failed: {str(e)}"}
            
            elif command == "upload_topology":
                try:
                    filename = params["filename"]
                    content = params["content"]

                    import tempfile
                    import os

                    temp_dir = tempfile.gettempdir()
                    file_path = os.path.join(temp_dir, f"uploaded_{filename}")

                    with open(file_path, "w") as f:
                        f.write(content)

                    await self.teardown_all_cells()

                    success = await self.dc.load_topology(file_path)

                    os.remove(file_path)

                    return {
                        "success": (
                            success.get("success", False)
                            if isinstance(success, dict)
                            else success
                        ),
                        "message": (
                            success.get("message", "Topology uploaded successfully.")
                            if isinstance(success, dict)
                            else (
                                "Topology uploaded successfully."
                                if success
                                else "Failed to upload topology."
                            )
                        ),
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "message": f"Error uploading topology: {str(e)}",
                    }
            
            elif command == "get_messages":
                try:
                    cell_id = params["cell_id"]
                    from_cell = params.get("from_cell", None)
                    result = self.dc.get_messages(cell_id, from_cell)
                    return result
                except Exception as e:
                    return {
                        "success": False,
                        "message": f"Get messages failed: {str(e)}",
                    }
            
            elif command == "restart":
                try:
                    # Teardown all current cells first
                    for cell_id in list(self.dc.cells.keys()):
                        await self.dc.remove_cell(cell_id)
                    
                    # Generate new topology
                    cell_name = get_unique_name()  # ← Use cell_name consistently
                    topology_yaml = create_topology_yaml(cell_name)
                    await load_topology_from_string(self.dc, topology_yaml)
                    return {"success": True, "message": f"Datacenter restarted successfully with cell: {cell_name}"}
                
                except Exception as e:
                    return {"success": False, "message": f"Restart failed: {str(e)}"}

            elif command == "broadcast_message":
                try:
                    cell_id = params["cell_id"]
                    message = params["message"]
                    result = self.dc.broadcast_message(cell_id, message)
                    return result
                except Exception as e:
                    return {
                        "success": False,
                        "message": f"Broadcast message failed: {str(e)}",
                    }

            elif command == "clear_messages":
                try:
                    cell_id = params["cell_id"]
                    result = self.dc.clear_messages(cell_id)
                    return result
                except Exception as e:
                    return {
                        "success": False,
                        "message": f"Clear messages failed: {str(e)}",
                    }
            
            
            elif command == "get_topology":
                result = self.dc.get_topology_status()
                return result

            else:
                return {"success": False, "message": f"Unknown command: {command}"}

                

        except Exception as e:
            return {"success": False, "message": str(e)}

    async def teardown_all_cells(self):
        """Clean shutdown of all cells"""
        try:
            for cell_id in list(self.dc.cells.keys()):
                await self.dc.remove_cell(cell_id)
            print("All cells removed successfully.")
        except Exception as e:
            print(f"Error during teardown: {e}")
    
    async def broadcast_update(self, update_type, data):
        if not self.websocket_clients:
            return

        message = {"type": update_type, "timestamp": time.time(), "data": data}

        disconnected = set()
        for client in list(self.websocket_clients):  # Create a copy to iterate over
            try:
                await client.send(json.dumps(message))
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)
            except Exception as e:
                print(f"Error broadcasting to client: {e}")
                disconnected.add(client)

        self.websocket_clients -= disconnected

            
    async def periodic_updates(self):
        """Send periodic updates - runs in the same event loop as WebSocket server"""
        metrics_counter = 0
        while True:
            try:
                # Send FSP updates every 50ms (20Hz)
                try:
                    fsp_status = self.dc.get_all_fsp_status()
                    if fsp_status.get("success"):
                        await self.broadcast_update("fsp_status_update", fsp_status["data"])
                except Exception as e:
                    print(f"Error getting FSP status: {e}")
                
                # Send metrics updates every 500ms (every 10th iteration)
                metrics_counter += 1
                if metrics_counter >= 10:
                    all_metrics = {}
                    for cell_id, proxy in self.dc.cells.items():
                        try:
                            metrics = proxy.get_metrics()
                            all_metrics[cell_id] = metrics
                        except Exception as e:
                            all_metrics[cell_id] = {"error": "unreachable"}

                    await self.broadcast_update("metrics_update", all_metrics)
                    metrics_counter = 0

                await asyncio.sleep(0.05)  # 50ms = 20Hz for FSP updates

            except Exception as e:
                print(f"Error in periodic update: {e}")
                await asyncio.sleep(5)
           

def get_unique_name():
    """Generate a unique name for this machine"""
    hostname = socket.gethostname().replace('.', '-').replace('_', '-')
    short_uuid = str(uuid.uuid4())[:8]
    return f"{hostname}-{short_uuid}"

def create_topology_yaml(cell_name, rpc_port=9000):
    """Create topology YAML as string"""
    return f"""topology:
  cells:
    - id: {cell_name}
      rpc_port: {rpc_port}
      host: "localhost"
  bindings:
    - cell_id: {cell_name}
      portname: en4
      addr: en4
  
    - cell_id: {cell_name}
      portname: en3
      addr: en3
    
    - cell_id: {cell_name}
      portname: en2
      addr: en2
"""

async def load_topology_from_string(dc, topology_yaml):
    """Load topology from string by creating a temp file"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        f.write(topology_yaml)
        temp_path = f.name
    
    try:
        await dc.load_topology(temp_path)
    finally:
        os.unlink(temp_path)

async def main():
    server = DataCenterServer()
    
    # Setup signal handlers for graceful shutdown
    def signal_handler():
        print("Received shutdown signal")
        asyncio.create_task(server.stop())
    
    # Register signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_event_loop().add_signal_handler(sig, signal_handler)
    
    try:
        # Start the server
        await server.start()
        
        
        # Generate and load topology
        cell_name = get_unique_name()
        topology_yaml = create_topology_yaml(cell_name)
        print(f"Generated unique cell name: {cell_name}")
        print("Loading topology from generated config...")
        await load_topology_from_string(server.dc, topology_yaml)
        
        print("DataCenter server is running...")
        print("Press Ctrl+C to stop the server.")
        
        # Wait for shutdown
        await server.shutdown_event.wait()
        
    except Exception as e:
        print(f"Server error: {e}")
    finally:
        await server.stop()

if __name__ == "__main__":
    asyncio.run(main())