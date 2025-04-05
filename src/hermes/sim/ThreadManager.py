import asyncio
import time
from typing import Dict

from hermes.sim.PipeQueue import PipeQueue
from hermes.sim.WebSocketServer import WebSocketServer
from hermes.port import ThreadedUDPPort
from hermes.sim.Tasks import periodic_status_update, process_commands

class ThreadManager:
    def __init__(self):
        self._threads = []
        self.ports = {}
        self._tasks = []
        self._pipes = []

        self.websocket_server = None

    def add_thread(self, thread):
        self._threads.append(thread)

    def start_all(self):
        for thread in self._threads:
            time.sleep(0.1)
            thread.start()
    
    async def main_loop_forever(self):
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            pass

    def stop_all(self):
        for thread in self._threads:
            thread.join()
        
        for pipe in self._pipes:
            pipe.close()
    
    def register_port(self, port: ThreadedUDPPort) -> None:
        self.ports[port.name] = port
        self._threads.append(port)
    
    def register_pipes(self, pipes: list[PipeQueue]) -> None:
        self._pipes.extend(pipes)

    def get_ports(self) -> Dict[str, ThreadedUDPPort]:
        return self.ports
    
    def get_websocket_server(self) -> WebSocketServer:
        return self.websocket_server
    
    def add_websocket_server(self, websocket_server: WebSocketServer) -> None:
        self.websocket_server = websocket_server
        self._tasks.append(self.websocket_server.start_server())
        self._tasks.append(periodic_status_update(self))
        self._tasks.append(process_commands(self, self.websocket_server.command_queue))
