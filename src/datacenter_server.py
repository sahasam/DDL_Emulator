import asyncio
import json
import websockets
from datacenter import ProtoDatacenter
from typing import Set
import threading
import time

class DataCenterServer:
    def __init__(self, host='localhost', port=8765):
        self.host = host
        self.port = port
        self.dc = ProtoDatacenter()
        self.websocket_clients = Set[websockets.WebSocketServerProtocol] = set()
        
        
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
                        
                except websocket.exceptions.ConnectionClosed:
                    print(f'Client disconnected: {websocket.remote_address}')
                    
                finally:
                    self.websocket_clients.discard(websocket)
                    print(f'Client removed: {websocket.remote_address}')
                    
            start_server = websockets.serve(handle_client, self.host, self.port)
            print(f'Server started on {self.host}:{self.port}')
            loop.run_until_complete(start_server)
            loop.run_forever()
            
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        self.start_periodic_updates()
    
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
            await websocket.send(json.dumps(error_response))
            
    async def execute_command(self, command, params):
        """Executes a datacenter command and return results"""
        
        try:
            if command == 'add_cell':
                cell_id = params['cell_id']
                rpc_port = params.get('rpc_port', None)
                success = self.dc.add_cell(cell_id, rpc_port)
                
                return {
                    'success': success,
                    'message': f'Cell {cell_id} added successfully.' if success else 'Failed to add cell.'
                }
                
            elif command == 'remove_cell':
                cell_id = params['cell_id']
                success = self.dc.remove_cell(cell_id)
                
                return {
                    'success': success,
                    'message': f'Cell {cell_id} removed successfully.' if success else 'Failed to remove cell.'
                }
            
            elif command == 'create_link':
                result = self.dc.create_link(
                    params['cell1'], params['port1'],
                    params['cell2'], params['port2'],
                    params['addr1'], params['addr2']
                )
                return {
                    'success': result,
                    'message': 'Link created successfully.' if result else 'Failed to create link.'
                }
                
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
                    metrics = self.cells[cell_id].get_metrics()
                    return {'success': True, 'data': metrics}
                else:
                    return {'success': False, 'message': f'Cell {cell_id} not found.'}
                
            elif command == 'inject_fault':
                result = self.dc.cells[params['cell_id']].inject_fault(
                    params['port_name'], params['fault_type'], params['fault_params']
                )
                return {
                    'success': True,
                    'message': result
                }

            elif command == 'clear_faults':
                result = self.dc.cells[params['cell_id']].clear_faults(params['port_name'])
                return {
                    'success': True,
                    'message': result
                }
            
            # TODO: add links   
            elif command == 'get_topology':
                topology = {
                    'cells': list(self.dc.cells.keys()),
                    'links': []
                }
                return {'success': True, 'data': topology}

            elif command == 'unlink':
                try:
                    result = self.dc.unlink(
                        params['cell1'], params['port1'],
                        params['cell2'], params['port2']
                    )
                    return {'success': True, 'message': 'Link unlinked successfully.' if result else 'Failed to unlink.'}
                except Exception as e:
                    return {'success': False, 'message': str(e)}
                
            elif command == 'get_logs':
                try:
                    result = self.dc.get_logs(params['cell_id'])
                    
                    return {'success': True, 'data': result}
                
                except Exception as e:
                    return {'success': False, 'message': str(e)}
                
            elif command == 'teardown':
                try:
                    for cell_id in list(self.dc.cells.keys()):
                        self.dc.remove_cell(cell_id)
                        
                    return {'success': True, 'message': 'All cells removed successfully.'}
                except Exception as e:
                    return {'success': False, 'message': str(e)}
                
                
            else:
                return {'success': False, 'message': f'Unknown command: {command}'}
            
        except Exception as e:
            return {'success': False, 'message': str(e)}
        
    async def broadcast_update(self, update_type, data):
        
        if not self.websocket_clients:
            return
        
        message = {
            'type': update_type,
            'timestamp': time.time(),
            'data': data
        }

        disconnected = set()
        for client in self.websocket_clients:
            try:
                await client.send(json.dumps(message))
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)
                
        self.websocket_clients -= disconnected
        
    def start_periodic_updates(self):
        
        def update_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def send_updates():
                while True:
                    try:
                        
                        all_metrics = {}
                        for cell_id, proxy in self.dc.cells.items():
                            try:
                                metrics = await proxy.get_metrics()
                                all_metrics[cell_id] = metrics
                            except Exception as e:
                                all_metrics[cell_id] = {'error': 'unreachable'}

                        await self.broadcast_update('metrics_update', all_metrics)
                        await asyncio.sleep(2)  

                    except Exception as e:
                        print(f"Error in periodic update: {e}")
                        await asyncio.sleep(5)
                        
            loop.run_until_complete(send_updates())
            
        update_thread = threading.Thread(target=update_loop, daemon=True)
        update_thread.start()
                        
    
def main():
    server = DataCenterServer()
    server.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Server shutting down...")  
if __name__ == "__main__":
    