from datacenter import ProtoDatacenter
import asyncio
import json
import websockets.server
from time import sleep
from flask import Flask, jsonify, request
import threading
import socket
import uuid
import tempfile
import os
from typing import Set

app = Flask(__name__)
dc = None
shutdown_flag = False
current_cell_name = None
websocket_clients: Set = set()

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

def shutdown_datacenter():
    """Gracefully shutdown the datacenter"""
    global dc, shutdown_flag
    if dc:
        print("Shutting down datacenter...")
        for cell_id in list(dc.cells.keys()):
            try:
                asyncio.run(dc.cells[cell_id].shutdown())
            except Exception as e:
                print(f"Error shutting down cell {cell_id}: {e}")
        print("Datacenter shutdown complete")
        dc = None
    shutdown_flag = True

@app.route('/shutdown', methods=['POST'])
def shutdown():
    """POST endpoint to trigger datacenter shutdown"""
    try:
        shutdown_datacenter()
        return jsonify({"status": "success", "message": "Datacenter shutdown initiated"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    """GET endpoint to check datacenter status"""
    global dc
    if dc and hasattr(dc, 'cells'):
        cell_names = list(dc.cells.keys())
        return jsonify({
            "status": "running" if not shutdown_flag else "shutdown",
            "cells": cell_names,
            "cell_count": len(cell_names),
            "current_cell_name": current_cell_name
        }), 200
    else:
        return jsonify({
            "status": "not_initialized" if not shutdown_flag else "shutdown",
            "current_cell_name": current_cell_name
        }), 503

@app.route('/manual_fsp', methods=['POST'])
def manual_fsp():
    """POST endpoint to trigger manual FSP"""
    global dc
    try:
        if not dc:
            return jsonify({"status": "error", "message": "Datacenter not initialized"}), 503
        
        # Get 'general' parameter from JSON body
        data = request.get_json() or {}
        general = data.get('general', True)  # Default to True if not specified
        
        result = dc.trigger_manual_fsp(general)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

async def broadcast_fsp_update(data):
    """Broadcast FSP updates to all connected WebSocket clients"""
    if not websocket_clients:
        return

    message = {"type": "fsp_status_update", "data": data}
    
    disconnected = set()
    for client in list(websocket_clients):
        try:
            await client.send(json.dumps(message))
        except Exception as e:
            disconnected.add(client)
    
    websocket_clients -= disconnected

async def periodic_fsp_updates():
    """Send periodic FSP updates - 20Hz"""
    while not shutdown_flag:
        try:
            if dc:
                fsp_status = dc.get_all_fsp_status()
                if fsp_status.get("success"):
                    await broadcast_fsp_update(fsp_status["data"])
            await asyncio.sleep(0.05)  # 50ms = 20Hz
        except Exception as e:
            print(f"Error in FSP update: {e}")
            await asyncio.sleep(1)

async def handle_websocket_client(websocket, path):
    """Handle WebSocket connections and commands"""
    websocket_clients.add(websocket)
    print(f"WebSocket client connected: {websocket.remote_address}")
    
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                command = data.get("command")
                params = data.get("params", {})
                
                if command == "manual_fsp":
                    general = params.get("general", True)
                    result = dc.trigger_manual_fsp(general)
                    
                    response = {
                        "type": "command_response",
                        "command": "manual_fsp",
                        "result": result,
                        "success": result.get("success", True),
                    }
                    await websocket.send(json.dumps(response))
                else:
                    error_response = {
                        "type": "error",
                        "message": f"Unknown command: {command}",
                    }
                    await websocket.send(json.dumps(error_response))
                    
            except json.JSONDecodeError:
                error_response = {
                    "type": "error",
                    "message": "Invalid JSON message",
                }
                await websocket.send(json.dumps(error_response))
            except Exception as e:
                error_response = {
                    "type": "error",
                    "message": str(e),
                }
                await websocket.send(json.dumps(error_response))
                
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        websocket_clients.discard(websocket)
        print(f"WebSocket client disconnected: {websocket.remote_address}")

def start_websocket_server():
    """Start WebSocket server in its own thread"""
    def run_websocket():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def start_server():
            server = await websockets.server.serve(
                handle_websocket_client,
                "localhost",
                8765,
                ping_interval=None,
                ping_timeout=None,
            )
            print("WebSocket server started on ws://localhost:8765")
            
            # Start periodic FSP updates
            asyncio.create_task(periodic_fsp_updates())
            
            await server.wait_closed()
        
        try:
            loop.run_until_complete(start_server())
        except Exception as e:
            print(f"WebSocket server error: {e}")
        finally:
            loop.close()
    
    websocket_thread = threading.Thread(target=run_websocket, daemon=True)
    websocket_thread.start()

async def run_datacenter():
    """Run the main datacenter loop"""
    global dc, shutdown_flag, current_cell_name
    try:
        print("Datacenter is starting up...")
        dc = ProtoDatacenter()
        
        # Generate unique cell name and auto-load topology
        cell_name = get_unique_name()
        topology_yaml = create_topology_yaml(cell_name)
        current_cell_name = cell_name
        
        print(f"Generated unique cell name: {cell_name}")
        print("Loading topology from generated config...")
        await load_topology_from_string(dc, topology_yaml)
        
        while not shutdown_flag:
            sleep(0.1)
            
    except KeyboardInterrupt:
        print("Received interrupt signal")
    finally:
        if not shutdown_flag:
            shutdown_datacenter()

if __name__ == "__main__":
    # Start datacenter in a separate thread
    datacenter_thread = threading.Thread(
        target=lambda: asyncio.run(run_datacenter()), 
        daemon=True
    )
    datacenter_thread.start()
    
    # Start WebSocket server
    start_websocket_server()
    
    # Start Flask server
    print("Starting datacenter API server on http://localhost:6000")
    print("Endpoints:")
    print("  GET  /status      - Check datacenter status")
    print("  POST /shutdown    - Shutdown datacenter")
    print("  POST /manual_fsp  - Trigger manual FSP")
    print("WebSocket server on ws://localhost:8765")
    print("  - FSP status broadcasts (20Hz)")
    print("  - manual_fsp command support")
    app.run(host='0.0.0.0', port=6000, debug=False)