"""
server.py

UDP server that listens for external connections on 0.0.0.0:6363 and handles up to 5 concurrent clients.
Implements a JSON messaging protocol for client requests and server state updates.
"""

import asyncio
import threading
import websockets
import queue
import json
import logging
from typing import Optional, Dict, Any

class WebSocketServer(threading.Thread):
    def __init__(self, host: str="0.0.0.0", port: int=6363, max_connections: int=5, logger: logging.Logger=None, **kwargs):
        super().__init__(**kwargs)
        self.host = host
        self.port = port
        self.max_connections = max_connections
        self.active_connections = set()
        self.logger = logger 
        self.running = False
        self.loop = None # Event loop for the server
        self.daemon = True # Thread will exit when the main thread exits
    
    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.start_server())
    
    def stop(self):
        self.running = False
    
    async def handle_client(self, websocket: websockets.WebSocketServerProtocol, path: str):
        """Handle incoming client connections"""
        self.logger.info(f"New client connected: {websocket.remote_address}")

        try:
            client_id = f"client_{len(self.active_connections)}"
            self.active_connections.add(client_id)
            self.logger.info(f"Client {client_id} connected")

            async for message in websocket:
                try:
                    data = json.loads(message)

                    self.message_queue.put({
                        "client_id": client_id,
                        "message": data
                    })

                    await websocket.send(json.dumps({"status": "message received"}))
                except json.JSONDecodeError:
                    self.logger.error(f"Invalid JSON message from {client_id}: {message}")
        finally:
            self.active_connections.remove(client_id)
            self.logger.info(f"Client {client_id} disconnected")

    async def start_server(self):
        async with websockets.server(self.handle_client, self.host, self.port, max_connections=self.max_connections):
            self.running = True
            print(f"WebSocket server listening on {self.host}:{self.port}")
            await asyncio.Future() # run until stopped