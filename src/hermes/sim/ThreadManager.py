import asyncio
import logging
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
        self._pipes = {}
        self.agent = None
        self.logger = logging.getLogger('ThreadManager')
        self.logger.disabled = True
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
            # Print task status
            self.logger.info(f"main_loop_forever: Have {len(self._tasks)} tasks to run")
            
            # Create real tasks from the coroutines if needed
            active_tasks = []
            for i, task in enumerate(self._tasks):
                if asyncio.iscoroutine(task):
                    task_obj = asyncio.create_task(task)
                    active_tasks.append(task_obj)
                else:
                    active_tasks.append(task)
            
            if not active_tasks:
                self.logger.info("No tasks to run, waiting indefinitely")
                await asyncio.Future()
            else:
                self.logger.info(f"Running {len(active_tasks)} active tasks")
                # This should keep tasks running until they complete or are cancelled
                await asyncio.gather(*active_tasks)
        except asyncio.CancelledError:
            self.logger.info("Tasks cancelled, shutting down...")
        except Exception as e:
            self.logger.info(f"Error in main loop: {e}")
            raise
        finally:
            self.logger.info("Cleaning up in main_loop_forever")
            self.stop_all()

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
        
        for port_pipes in self._pipes.values():
            for pipe in port_pipes:
                pipe.close()
    
    def register_port(self, port: BasePort) -> None:
        with self._ports_lock:
            self.ports[port.port_id] = port
            self._threads.append(port)
            
    def delete_port(self, port_id) -> bool:
        with self._ports_lock:
            if port_id in self.ports:
                ports_to_delete = self.ports[port_id]
            
                if ports_to_delete in self._threads:
                    self._threads.remove(ports_to_delete)
                
                del self.ports[port_id]
                del self._pipes[port_id]
                
                return True
            else:
                return False
        
    def register_pipes(self, port_id, pipes: list[PipeQueue]) -> None:
        self._pipes[port_id] = pipes

    def get_ports(self) -> Dict[str, BasePort]:
        with self._ports_lock:
            return dict(self.ports)
    
    def get_websocket_server(self) -> WebSocketServer:
        return self.websocket_server
    
    def add_websocket_server(self, websocket_server: WebSocketServer) -> None:
        self.websocket_server = websocket_server
        self.logger.info(f"Adding WebSocket server on {websocket_server.host}:{websocket_server.port}")
        
        # Store coroutines instead of trying to create tasks
        # The tasks will be created in main_loop_forever when the event loop is running
        self._tasks.append(self.websocket_server.start_server())
        self._tasks.append(periodic_status_update(self))
        self._tasks.append(process_commands(self, self.websocket_server.command_queue))
    
    def add_agent(self, agent: threading.Thread) -> None:
        self.agent = agent
        self._threads.append(agent)

    def get_agent(self) -> threading.Thread:
        return self.agent

