"""
sim.py

Right now: spin up the logs, loops, and prompting to run the single-link simulation

Eventual Goal: Given an arbitrary description of a network topology with virtual links, real links, and unconnected links,
create all threads, event loops, and logs for simulation
"""
import asyncio
from collections import defaultdict
from hermes.port import PortConfig, PortIO, SymmetricPort
from hermes.sim.WebSocketServer import WebSocketServer
from hermes.sim.PipeQueue import PipeQueue
from hermes.sim.ThreadManager import ThreadManager

import logging
import logging.config


class Sim:
    """
    Sim is the main class for the simulation. It is responsible for creating all threads, log files, and event loops for the simulation.
    """
    def __init__(self, log_dir='/opt/hermes/logs', protocol='liveness'):
        self.thread_manager = ThreadManager()

        self.log_dir = log_dir # Directory where log files will be stored
        self.log_level = defaultdict(lambda: logging.INFO) # Default logging levels for different components
        

    @classmethod
    def from_config(cls, config):
        """Given a config, create all threads, log files, and event loops for the simulation"""
        sim = cls()
        sim.configure_logging()

        # Extract config settings with defaults
        config_settings = config.get('config', {})
        sim.log_dir = config_settings.get('log_dir', '/opt/hermes/logs')
        sim.protocol = config_settings.get('protocol', 'liveness')
        
        sim.thread_manager.add_websocket_server(WebSocketServer())

        for port_config in config['ports']:
            if port_config.get('type', '') == 'disconnected':
                continue
            # Create a port, with pipes and a thread. Add the port to the thread manager
            sim._create_port(port_config)
        
        return sim
    

    def configure_logging(self):
        logging.config.dictConfig({
            'version': 1,
            'disable_existing_loggers': False,

            'formatters': {
                'standard': {
                    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                },
            },

            'handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'standard',
                    'level': 'INFO',
                },
                'port_log': {
                    'class': 'logging.FileHandler',
                    'formatter': 'standard',
                    'level': 'INFO',
                    'filename': 'port.log',
                },
                'websocket_log': {
                    'class': 'logging.FileHandler',
                    'formatter': 'standard',
                    'level': 'INFO',
                    'filename': 'websocket.log',
                },
            },

            'loggers': {
                'Port.alice': {
                    'level': 'INFO',
                    'handlers': ['console', 'port_log'],
                    'propagate': False,
                },
                'Port.bob': {
                    'level': 'INFO',
                    'handlers': ['console', 'port_log'],
                    'propagate': False,
                },
                'Port.charlie': {
                    'level': 'INFO',
                    'handlers': ['console', 'port_log'],
                    'propagate': False,
                },
                'WebSocketServer': {
                    'level': 'INFO',
                    'handlers': ['websocket_log'],
                    'propagate': False,
                },
            },

            'root': {
                'level': 'WARNING',
                'handlers': [],
            },
        })
    

    def _create_port(self, port_config: dict):
        read_q = PipeQueue()
        write_q = PipeQueue()
        signal_q = PipeQueue()
        self.thread_manager.register_pipes([read_q, write_q, signal_q])
        self.thread_manager.register_port(
            SymmetricPort(
                config=PortConfig(
                    logger=None,
                    interface=port_config['interface'],
                    name=port_config['name']
                ),
                io=PortIO(
                    read_q=read_q,
                    write_q=write_q, 
                    signal_q=signal_q
                )
            )
        )


    async def run(self):
        asyncio.get_event_loop().set_debug(True)
        self.thread_manager.start_all()
        self.thread_manager._setup_signal_handlers()
        await self.thread_manager.main_loop_forever()