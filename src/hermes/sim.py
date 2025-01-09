"""
sim.py

Right now: spin up the logs, loops, and prompting to run the single-link simulation

Eventual Goal: Given an arbitrary description of a network topology with virtual links, real links, and unconnected links,
create all threads, event loops, and logs for simulation
"""
from collections import defaultdict
from hermes.port import ThreadedUDPPort, LivenessPort
from hermes.server import WebSocketServer

import asyncio
import time
import logging

class Sim:
    def __init__(self, log_dir='/opt/hermes/logs', protocol='liveness'):
        self.threads = []
        self.loops = []
        self.port_manager = PortManager()
        self.server = None
        self.log_dir = log_dir
        self.protocol = protocol
        self.log_level = defaultdict(lambda: logging.INFO)
    
    def setup_logger(self, name, log_file, stdout=False, level=logging.INFO):
        """Set up a logger for a specific thread."""
        logger = logging.getLogger(name)
        logger.setLevel(level)
        
        if stdout:
             logger.addHandler(logging.StreamHandler())
        
        # File handler for the specific log file. Overwrites existing file
        handler = logging.FileHandler(log_file, mode="w+")
        formatter = logging.Formatter('%(asctime)s - %(threadName)s - %(message)s')
        handler.setFormatter(formatter)
    
        logger.addHandler(handler)
        return logger
    

    @classmethod
    def from_config(cls, config):
        """Given a config, create all threads, log files, and event loops for the simulation"""
        sim = cls()
        if 'config' in config:
            sim.log_dir = config['config']['log_dir']
            sim.protocol = config['config']['protocol']
            for name, level in config['config']['log_level'].items():
                sim.log_level[name] = getattr(logging, level.upper())

        sim.server = WebSocketServer(
            command_queue=sim.port_manager.command_queue,
            logger=sim.setup_logger("WebSocketServer", f"{sim.log_dir}/websocket_server.log", stdout=True, level=sim.log_level['websocket_server'])
        )
        sim.port_manager.websocket_server = sim.server

        for port in config['ports']:
            if port['type'] == 'disconnected':
                continue
            
            loop = asyncio.new_event_loop()
            logger = sim.setup_logger(port['name'], f"{sim.log_dir}/{port['name']}.log", level=sim.log_level[port['name']])
            port_thread = None
            if sim.protocol == 'liveness':
                port_thread = LivenessPort(loop, logger, port['type'] == 'client', (port['ip'], port['port'] or 55555), name=port['name'])
            elif sim.protocol == 'abp':
                port_thread = ThreadedUDPPort(loop, logger, port['type'] == 'client', (port['ip'], port['port'] or 55555), name=port['name'])
            else:
                raise ValueError(f"Invalid protocol: {sim.protocol}")
            
            sim.port_manager.add_port(port['name'], port_thread)
            sim.threads.append(port_thread)
            sim.loops.append(loop)
        
        return sim
    

    def start(self):
        try:
            for thread in self.threads:
                thread.start()
                time.sleep(0.1)
            
            loop = asyncio.get_event_loop()
            self.port_manager.start()
            server_task = loop.create_task(self.server.start_server())
            
            # Store tasks for cleanup
            self._tasks = [server_task]
            try:
                loop.run_forever()
            finally:
                # Cancel all tasks first
                for task in self._tasks:
                    task.cancel()
                # Wait for all tasks to complete
                loop.run_until_complete(self._shutdown(loop))
                
        except Exception as e:
            logging.error(f"Error in main loop: {e}")
        finally:
            self._cleanup()

    async def _shutdown(self, loop):
        """Perform graceful shutdown of async tasks"""
        tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    
    def _cleanup(self):
        """Clean up threads and loops"""
        print("\nPerforming cleanup...")
        # Stop the port manager
        if self.port_manager:
            self.port_manager._stop_event.set()
        
        # Close all thread transports
        for thread in self.threads:
            if thread.protocol_instance and thread.protocol_instance.transport:
                thread.protocol_instance.transport.close()
        
        # Stop and close all event loops
        for loop in self.loops:
            try:
                loop.call_soon_threadsafe(loop.stop)
                loop.close()
            except Exception as e:
                logging.error(f"Error closing loop: {e}")
        
        # Join all threads
        for thread in self.threads:
            thread.join()

class PortManager:
    def __init__(self, ports:dict[str, ThreadedUDPPort]={}):
        self.command_queue = asyncio.Queue()
        self.ports = ports
        self._stop_event = asyncio.Event()
        self.websocket_server = None
    
    def add_port(self, name, port):
        self.ports[name] = port
    
    def start(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self.process_commands())
        loop.create_task(self.send_updates())
        
    async def process_commands(self):
        while not self._stop_event.is_set():
            # Process all available messages
            while True:
                try:
                    cmd = await self.command_queue.get()
                    port_name = cmd.get('port')
                    action = cmd.get('action')
                    
                    if port_name in self.ports:
                        port = self.ports[port_name]
                        if action == 'DROP':
                            port.drop_one_packet()
                        else:
                            raise ValueError(f"Invalid action: {action}")
                except Exception as e:
                    print(f"Error processing command: {e}")

    async def send_updates(self):
        while not self._stop_event.is_set():
            await asyncio.sleep(0.1)
            snapshots = {}
            for name, port in self.ports.items():
                snapshots[name] = port.get_snapshot()

            await self.websocket_server.send_updates(snapshots)