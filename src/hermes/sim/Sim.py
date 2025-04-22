"""
sim.py

Right now: spin up the logs, loops, and prompting to run the single-link simulation

Eventual Goal: Given an arbitrary description of a network topology with virtual links, real links, and unconnected links,
create all threads, event loops, and logs for simulation
"""
import asyncio
from collections import defaultdict
import logging
import logging.config
import uuid

from hermes.faults.FaultInjector import ThreadSafeFaultInjector
from hermes.model.ports import PortConfig, PortIO
from hermes.port.Agent import Agent
from hermes.port.Port import UDPPort
from hermes.port.Protocol import EthernetProtocol
from hermes.sim.WebSocketServer import WebSocketServer
from hermes.sim.PipeQueue import PipeQueue
from hermes.sim.ThreadManager import ThreadManager


class Sim:
    """
    Sim is the main class for the simulation. It is responsible for creating all threads, log files, and event loops for the simulation.
    """
    def __init__(self, log_dir='/opt/hermes/logs', protocol='liveness'):
        self.thread_manager = ThreadManager()

        self.log_dir = log_dir # Directory where log files will be stored
        self.log_level = defaultdict(lambda: logging.INFO) # Default logging levels for different components
        self.node_id = uuid.uuid4()


    @classmethod
    def from_config(cls, config):
        """Given a config, create all threads, log files, and event loops for the simulation"""
        sim = cls()
        sim.configure_logging()

        # Extract config settings with defaults
        config_settings = config.get('config', {})
        sim.log_dir = config_settings.get('log_dir', '/opt/hermes/logs')
        sim.protocol = config_settings.get('protocol', 'liveness')
        if 'node_id' in config_settings:
            sim.node_id = config_settings['node_id']
        
        sim.thread_manager.add_websocket_server(WebSocketServer())
        sim.thread_manager.add_agent(Agent(sim.node_id, sim.thread_manager))


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
                'Port': {
                    'level': 'INFO',
                    'handlers': ['console', 'port_log'],
                    'propagate': False,
                },
                'Protocol': {
                    'level': 'INFO',
                    'handlers': ['console', 'port_log'],
                    'propagate': False,
                },
                'WebSocketServer': {
                    'level': 'INFO',
                    'handlers': ['websocket_log'],
                    'propagate': False,
                },
                'Agent': {
                    'level': 'INFO',
                    'handlers': ['console'],
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
        faultInjector = ThreadSafeFaultInjector()
        self.thread_manager.register_pipes([read_q, write_q, signal_q])
        self.thread_manager.register_port(
            UDPPort(
                config=PortConfig(
                    logger=None,
                    interface=port_config['interface'],
                    port_id=f"{self.node_id}:{port_config['name']}",
                    name=port_config['name']
                ),
                io=PortIO(
                    read_q=read_q,
                    write_q=write_q, 
                    signal_q=signal_q
                ),
                faultInjector=faultInjector,
                protocolClass=EthernetProtocol
            )
        )


    async def run(self):
        asyncio.get_event_loop().set_debug(True)
        self.thread_manager.start_all()
        self.thread_manager._setup_signal_handlers()
        await self.thread_manager.main_loop_forever()