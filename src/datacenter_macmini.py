from datacenter import ProtoDatacenter
import asyncio
from time import sleep
from flask import Flask, jsonify
import threading
import sys
import socket
import uuid
import tempfile
import os

app = Flask(__name__)
dc = None
shutdown_flag = False
restart_flag = False
current_cell_name = None
current_topology_yaml = None
datacenter_thread = None

def get_unique_name():
    """Generate a unique name for this machine"""
    # Option 1: hostname + short UUID
    hostname = socket.gethostname().replace('.', '-').replace('_', '-')
    short_uuid = str(uuid.uuid4())[:8]
    return f"{hostname}-{short_uuid}"
    
    # Option 2: Just use hostname (simpler but less unique)
    # return socket.gethostname().replace('.', '-').replace('_', '-')
    
    # Option 3: MAC address based (most unique)
    # import uuid
    # return f"node-{uuid.getnode():x}"

def create_topology_yaml(cell_name, rpc_port=9000):
    """Create topology YAML as string"""
    return f"""topology:
  cells:
    - id: {cell_name}
      rpc_port: {rpc_port}
      host: "localhost"
  bindings:
    - cell_id: {cell_name}
      portname: en1
      addr: en1
    
    - cell_id: {cell_name}
      portname: en2
      addr: en2
"""

def load_topology_from_string(dc, topology_yaml):
    """Load topology from string by creating a temp file"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        f.write(topology_yaml)
        temp_path = f.name
    
    try:
        dc.load_topology(temp_path)
    finally:
        os.unlink(temp_path)  # Clean up temp file

def shutdown_datacenter():
    """Gracefully shutdown the datacenter"""
    global dc, shutdown_flag
    if dc:
        print("Shutting down datacenter...")
        for cell_id in list(dc.cells.keys()):
            try:
                # Fixed: added parentheses to actually call the method
                asyncio.run(dc.cells[cell_id].shutdown())
            except Exception as e:
                print(f"Error shutting down cell {cell_id}: {e}")
        print("Datacenter shutdown complete")
        dc = None
    shutdown_flag = True

def restart_datacenter():
    """Restart datacenter with previous config"""
    global dc, shutdown_flag, restart_flag, current_cell_name, current_topology_yaml, datacenter_thread
    
    # Shutdown current instance
    shutdown_datacenter()
    
    # Wait a moment for cleanup
    sleep(0.5)
    
    # Reset flags
    shutdown_flag = False
    restart_flag = True
    
    # Start new datacenter thread
    datacenter_thread = threading.Thread(target=run_datacenter, daemon=True)
    datacenter_thread.start()
    
    print("Datacenter restart initiated")

@app.route('/shutdown', methods=['POST'])
def shutdown():
    """POST endpoint to trigger datacenter shutdown"""
    try:
        shutdown_datacenter()
        return jsonify({"status": "success", "message": "Datacenter shutdown initiated"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/restart', methods=['POST'])
def restart():
    """POST endpoint to restart datacenter with previous config"""
    try:
        if not current_cell_name:
            return jsonify({"status": "error", "message": "No previous configuration to restart with"}), 400
        
        restart_datacenter()
        return jsonify({
            "status": "success", 
            "message": f"Datacenter restart initiated with cell name: {current_cell_name}"
        }), 200
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
            "current_cell_name": current_cell_name,
            "can_restart": current_cell_name is not None
        }), 200
    else:
        return jsonify({
            "status": "not_initialized" if not shutdown_flag else "shutdown",
            "current_cell_name": current_cell_name,
            "can_restart": current_cell_name is not None
        }), 503

def run_datacenter():
    """Run the main datacenter loop"""
    global dc, shutdown_flag, restart_flag, current_cell_name, current_topology_yaml
    try:
        print("datacenter is starting up...")
        dc = ProtoDatacenter()
        
        # Use previous config if restarting, otherwise generate new
        if restart_flag and current_cell_name and current_topology_yaml:
            print(f"Restarting with previous cell name: {current_cell_name}")
            cell_name = current_cell_name
            topology_yaml = current_topology_yaml
            restart_flag = False
        else:
            # Generate unique cell name and topology
            cell_name = get_unique_name()
            topology_yaml = create_topology_yaml(cell_name)
            
            # Store for potential restart
            current_cell_name = cell_name
            current_topology_yaml = topology_yaml
            
            print(f"Generated unique cell name: {cell_name}")
        
        print("loading topology from generated config...")
        load_topology_from_string(dc, topology_yaml)
        
        while not shutdown_flag:
            sleep(0.1)
            
    except KeyboardInterrupt:
        print("Received interrupt signal")
    finally:
        if not shutdown_flag and not restart_flag:  # Only shutdown if not already done via POST or restart
            shutdown_datacenter()

if __name__ == "__main__":
    # Start datacenter in a separate thread
    datacenter_thread = threading.Thread(target=run_datacenter, daemon=True)
    datacenter_thread.start()
    
    # Start Flask server
    print("Starting datacenter API server on http://localhost:6000")
    print("Endpoints:")
    print("  GET  /status   - Check datacenter status")
    print("  POST /shutdown - Shutdown datacenter")
    print("  POST /restart  - Restart with previous config")
    app.run(host='0.0.0.0', port=6000, debug=False)