"""
sim.py

Right now: spin up the logs, loops, and prompting to run the single-link simulation

Eventual Goal: Given an arbitrary description of a network topology with virtual links, real links, and unconnected links,
create all threads, event loops, and logs for simulation
"""
from collections import defaultdict
from hermes.algorithm import PipeQueue, TreeAlgorithm
from hermes.port import AlphabetPort, PortConfig, PortIO, SymmetricPort, ThreadedUDPPort, LivenessPort, TreePort
from hermes.server import WebSocketServer

import asyncio
import time
import logging

from hermes.util import get_ipv6_neighbors

class Sim:
    def __init__(self, log_dir='/opt/hermes/logs', protocol='liveness'):
        self.threads = []
        self.loops = []
        self.queues = []
        self.ports = {}  # name -> port mapping
        self.command_queue = asyncio.Queue()
        self.server = None
        self.log_dir = log_dir
        self.protocol = protocol
        self.log_level = defaultdict(lambda: logging.INFO)
        self.tree = {
            'nodes': ["ME"],
            'edges': [],
        }
        self._stop_event = asyncio.Event()
    
    def _setup_logger(self, name, log_file, stdout=False, level=logging.INFO):
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
    
    def _create_port(self, port_config: dict):
        loop = asyncio.new_event_loop()
        logger = self._setup_logger(
            name=port_config['name'],
            log_file=f"{self.log_dir}/{port_config['name']}.log",
            stdout=False,
            level=self.log_level[port_config['name']]
        )
        
        read_q = PipeQueue()
        write_q = PipeQueue()
        signal_q = PipeQueue()
        self.queues.extend([read_q, write_q, signal_q])

        return SymmetricPort(
                config=PortConfig(
                    loop=loop,
                    logger=logger,
                    interface=port_config['interface'],
                    name=port_config['name']
                ),
                io=PortIO(
                    read_q=read_q,
                    write_q=write_q, 
                    signal_q=signal_q
                )
            )

    @classmethod
    def from_config(cls, config):
        """Given a config, create all threads, log files, and event loops for the simulation"""
        sim = cls()

        # Extract config settings with defaults
        config_settings = config.get('config', {})
        sim.log_dir = config_settings.get('log_dir', '/opt/hermes/logs')
        sim.protocol = config_settings.get('protocol', 'liveness')
        
        # set log levels
        for name, level in config_settings.get('log_level', {}).items():
            sim.log_level[name] = getattr(logging, level.upper())

        # Create the WebSocket server
        sim.server = WebSocketServer(
            command_queue=sim.command_queue,
            logger=sim._setup_logger(
                name="WebSocketServer",
                log_file=f"{sim.log_dir}/websocket_server.log",
                stdout=True,
                level=sim.log_level['websocket_server']
            )
        )
        # sim.threads.append(TreeAlgorithm(port_manager=sim.port_manager))

        for port_config in config['ports']:
            if port_config.get('type', '') == 'disconnected':
                continue
            
            # Create a new event loop and logger for each port
            port_thread = sim._create_port(port_config)
            sim.threads.append(port_thread)
        
        return sim
    
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
                        elif action == 'DISCONNECT':
                            port.set_disconnected(True)
                        elif action == 'CONNECT':
                            port.set_disconnected(False)
                        else:
                            raise ValueError(f"Invalid action: {action}")
                except Exception as e:
                    print(f"Error processing command: {e}")

    async def send_updates(self):
        while not self._stop_event.is_set():
            await asyncio.sleep(0.05)
            snapshots = [port.get_snapshot() for port in self.ports.values()]
            tree = (self.tree['nodes'], self.tree['edges'])
            await self.websocket_server.send_updates(snapshots, tree)
    
    def start(self):
        try:
            for thread in self.threads:
                thread.start()
                time.sleep(0.05)
            
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
        # if self.port_manager:
        #     self.port_manager._stop_event.set()
        self._stop_event.set()
        
        for queue in self.queues:
            queue.close()
        
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
    