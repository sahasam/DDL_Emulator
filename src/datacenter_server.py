import asyncio
import json
import websockets.server
from datacenter import ProtoDatacenter
from typing import Set
import threading
import time

class DataCenterServer:
    def __init__(self, host='localhost', port=8765):
        self.host = host
        self.port = port
        self.dc = ProtoDatacenter()
        self.websocket_clients: Set = set()
        
    def __del__(self):
        """Destructor to ensure proper cleanup"""
        print("DataCenterServer is being deleted. Cleaning up...")
        self.teardown_all_cells()
        print("All cells removed successfully.")
        
    def start(self):
        def run_server():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def handle_client(websocket, path):
                self.websocket_clients.add(websocket)
                print(f'Client connected: {websocket.remote_address}')
                
                try:
                    async for message in websocket:
                        print(f'Received message: {message}')
                        await self.handle_message(websocket, message)
                        
                except websockets.exceptions.ConnectionClosed:
                    print(f'Client disconnected: {websocket.remote_address}')
                except Exception as e:
                    print(f'Error handling client: {e}')
                    
                finally:
                    self.websocket_clients.discard(websocket)
                    print(f'Client removed: {websocket.remote_address}')
            
            async def start_server_async():
                # Start the WebSocket server
                server = await websockets.server.serve(
                    handle_client, 
                    self.host, 
                    self.port,
                    ping_interval=None,  # Disable ping
                    ping_timeout=None    # Disable ping timeout
                )
                print(f'WebSocket server started on ws://{self.host}:{self.port}')
                
                # Start periodic updates in the same event loop
                asyncio.create_task(self.periodic_updates())
                
                # Keep the server running
                await server.wait_closed()
            
            # Run the async function
            try:
                loop.run_until_complete(start_server_async())
            except KeyboardInterrupt:
                print("Server interrupted")
            finally:
                loop.close()
            
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
    
    async def handle_message(self, websocket, message):
        """Handle incoming websocket messages"""
        try:
            data = json.loads(message)
            command = data.get('command')
            params = data.get('params', {})
            
            result = await self.execute_command(command, params)
            
            response = {
                'type': 'command_response',
                'command': command,
                'result': result,
                'success': result.get('success', True),
            }
            
            await websocket.send(json.dumps(response))
            
        except Exception as e:
            error_response = {
                'type': 'error',
                'message': str(e),
            }
            try:
                await websocket.send(json.dumps(error_response))
            except:
                print(f"Failed to send error response: {e}")
    
    async def execute_command(self, command, params):
        """Executes a datacenter command and return results"""
        try:
            if command == 'add_cell':
                cell_id = params['cell_id']
                rpc_port = params.get('rpc_port', None)
                host = params.get('host', 'localhost')
                result = self.dc.add_cell(cell_id, rpc_port, host)
                
                return result
                
            elif command == 'remove_cell':
                cell_id = params['cell_id']
                result = self.dc.remove_cell(cell_id)
                
                return result
            
            elif command == 'create_link':
                result = self.dc.create_link(
                    params['cell1'], params['port1'],
                    params['cell2'], params['port2'],
                    params['addr1'], params['addr2']
                )
                return result
                
            elif command == 'get_status':
                status = {}
                for cell_id, proxy in self.dc.cells.items():
                    try:
                        status[cell_id] = proxy.heartbeat()
                    except:
                        status[cell_id] = 'unreachable'
                        
                return {'success': True, 'data': status}
            
            elif command == 'get_metrics':
                cell_id = params.get('cell_id')
                
                if cell_id in self.dc.cells:
                    try:
                        metrics = self.dc.cells[cell_id].get_metrics()  
                        return metrics
                    except Exception as e:
                        return {'success': False, 'message': f'Failed to get metrics: {str(e)}'}
                else:
                    return {'success': False, 'message': f'Cell {cell_id} not found.'}
                
            elif command == 'inject_fault':
                try:
                    fault_params = params.get('fault_params', {})
                    result = self.dc.inject_fault(params['cell_id'], params['port_name'], params['fault_type'], **fault_params)
                    return result
                except Exception as e:
                    return {'success': False, 'message': f'Fault injection failed: {str(e)}'}

            elif command == 'clear_fault':  
                try:
                    result = self.dc.clear_fault(params['cell_id'], params['port_name'])
                    
                    return result
                except Exception as e:
                    return {'success': False, 'message': f'Clear fault failed: {str(e)}'}
            
            elif command == 'get_topology':
                result = self.dc.get_topology_status()
                return result

            elif command == 'unlink':
                result = self.dc.unlink(
                    params['cell1'], params['port1'],
                    params['cell2'], params['port2']
                )
                return result
                
            elif command == 'get_logs':
                cell_id = params['cell_id']
                self.dc.get_logs(cell_id) 
                return {
                    'success': True, 
                    'message': f'Logs for {cell_id} printed to server console'
                }
                
            elif command == 'teardown':
                for cell_id in list(self.dc.cells.keys()):
                    self.dc.remove_cell(cell_id)
                        
                return {'success': True, 'message': 'All cells removed successfully.'}
            
            elif command == 'upload_topology':
                try:
                    filename = params['filename']
                    content = params['content']
                    
                    import tempfile
                    import os
                    
                    temp_dir = tempfile.gettempdir()
                    file_path = os.path.join(temp_dir, f'uploaded_{filename}')

                    with open(file_path, 'w') as f:
                        f.write(content)
                        
                    self.teardown_all_cells()  # Ensure all cells are removed before loading new topology
                        
                    success = self.dc.load_topology(file_path)  # Changed from upload_topology
                    
                    os.remove(file_path)  # Clean up the temporary file
                    
                    return {
                        'success': success.get('success', False) if isinstance(success, dict) else success,
                        'message': success.get('message', 'Topology uploaded successfully.') if isinstance(success, dict) else ('Topology uploaded successfully.' if success else 'Failed to upload topology.')
                    }
                except Exception as e:
                    return {'success': False, 'message': f'Error uploading topology: {str(e)}'}
                
            elif command == 'save_topology':
                try:
                    filename = params.get('filename', 'topology.yaml')
                    
                    # Generate current topology
                    topology = {
                        'topology': {
                            'cells': [
                                {'id': cell_id, 'rpc_port': 'unknown'} 
                                for cell_id in self.dc.cells.keys()
                            ],
                            'links': []  # You'd need to track these
                        }
                    }
                    
                    import yaml
                    yaml_content = yaml.dump(topology, default_flow_style=False)
                    
                    return {
                        'success': True,
                        'data': yaml_content,
                        'filename': filename
                    }
                    
                except Exception as e:
                    return {'success': False, 'message': f'Save failed: {str(e)}'}
            else:
                return {'success': False, 'message': f'Unknown command: {command}'}
            
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def teardown_all_cells(self):
        try:
            for cell_id in list(self.dc.cells.keys()):
                self.dc.remove_cell(cell_id)
                
        except Exception as e:
            print(f"Error during teardown: {e}")
        
    async def broadcast_update(self, update_type, data):
        if not self.websocket_clients:
            return
        
        message = {
            'type': update_type,
            'timestamp': time.time(),
            'data': data
        }

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
        while True:
            try:
                all_metrics = {}
                for cell_id, proxy in self.dc.cells.items():
                    try:
                        metrics = proxy.get_metrics()
                        all_metrics[cell_id] = metrics
                    except Exception as e:
                        all_metrics[cell_id] = {'error': 'unreachable'}

                await self.broadcast_update('metrics_update', all_metrics)
                await asyncio.sleep(0.5)  

            except Exception as e:
                print(f"Error in periodic update: {e}")
                await asyncio.sleep(5)

def main():
    server = DataCenterServer()
    server.start()
    
    print("DataCenter server is running...")
    print("Press Ctrl+C to stop the server.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down server...")
        print("Server shutdown complete.")
       
if __name__ == "__main__":
    main()