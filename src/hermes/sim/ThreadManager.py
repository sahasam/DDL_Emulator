import asyncio
import signal
import sys
import threading
import time
from typing import Dict, Type

from hermes.sim.PipeQueue import PipeQueue
from hermes.sim.WebSocketServer import WebSocketServer
from hermes.port.Port import BasePort
from hermes.sim.Tasks import periodic_status_update, process_commands

class ThreadManager:
    def __init__(self):
        self._threads = []
        self.ports = {}
        self._ports_lock = threading.Lock()
        self._tasks = []
        self._pipes = []

        self._port_subscribers = []
        self.websocket_server = None

    def add_thread(self, thread):
        self._threads.append(thread)

    def start_all(self):
        for thread in self._threads:
            time.sleep(0.1)
            thread.start()
    
    async def main_loop_forever(self):
        try:
            # Wait for any task to complete (which won't happen normally)
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            print("Tasks cancelled, shutting down...")
        finally:
            # Always clean up, even if exceptions occur
            self.stop_all()
            sys.exit(0)

    def _setup_signal_handlers(self):
        # Register signal handlers at the global level
        def signal_handler(sig, frame):
            print("\nShutdown signal received in global handler, cleaning up...")
            self.stop_all()
            sys.exit(0)
        # Register the handler for SIGINT
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def stop_all(self):
        # Close all ports' event loops from main thread
        for name, port in self.ports.items():
            if hasattr(port, '_loop') and port._loop.is_running():
                port.stop_event.set()
                port._loop.stop()
    
        for thread in self._threads:
            thread.join(timeout=0.5)
        
        for pipe in self._pipes:
            pipe.close()
    
    def register_port(self, port: BasePort) -> None:
        with self._ports_lock:
            self.ports[port.port_id] = port
            self._threads.append(port)
    
    def register_pipes(self, pipes: list[PipeQueue]) -> None:
        self._pipes.extend(pipes)

    def get_ports(self) -> Dict[str, BasePort]:
        with self._ports_lock:
            return dict(self.ports)
    
    def get_websocket_server(self) -> WebSocketServer:
        return self.websocket_server
    
    def add_websocket_server(self, websocket_server: WebSocketServer) -> None:
        self.websocket_server = websocket_server
        self._tasks.append(self.websocket_server.start_server())
        self._tasks.append(periodic_status_update(self))
        self._tasks.append(process_commands(self, self.websocket_server.command_queue))
    
    def add_agent(self, agent: threading.Thread) -> None:
        self._threads.append(agent)

