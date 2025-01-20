"""
port.py

Represent a single terminal of the emulated network. One port represents one port thread on a machine,
and handles raw packets asynchronously from the rest of the system. The port abstraction allows the
emulation to manually inject all different types of faults as present in clos networks or perr-to-peer links.

The port abstraction is intended to be symmetric to all layers above, but due to limitations of UDP as
the link prtocol, the client/server interactions are hidden below.
"""
from dataclasses import dataclass
from asyncio import AbstractEventLoop
import logging
from typing import Optional, Tuple
from hermes.machines.data import Data
from hermes.algorithm import PipeQueue
from hermes.protocol import ABPProtocol, AlphabetProtocol, LivenessProtocol, DropMode, TreeProtocol

import threading
import asyncio

from hermes.util import get_ipv6_neighbors

class ThreadedUDPPort(threading.Thread):
    def __init__(self, loop, logger, is_client, addr, name, **kwargs):
        super().__init__(**kwargs)
        self.loop = loop
        self.logger = logger
        self.is_client = is_client
        self.addr = addr
        self.name = name
        self.remote_addr = addr if is_client else None
        self.local_addr = addr if not is_client else None
        self.protocol_instance = None
        self.daemon = True
    
    def get_pretty_link_details(self):
        return "* UDP {:<5} * Interface: {:>7} * Address: {:>12}:{:<5} *" \
                .format("Client" if self.is_client else "Server", self.name, *self.addr)

    def run(self):
        self.loop.run_until_complete(self.loop.create_task(self.run_link()))
    
    async def run_link(self):
        while True:
            transport = None
            try:
                transport, self.protocol_instance = await self.loop.create_datagram_endpoint(
                    lambda: ABPProtocol(logger=self.logger, is_client=self.is_client), 
                    remote_addr=self.remote_addr,
                    local_addr=self.local_addr
                )
                await self.protocol_instance.disconnected_future
            finally:
                if transport:
                    transport.close()
                print(f"Resetting {'Client to' if self.is_client else 'Server on'} {self.addr}")
                await asyncio.sleep(1)
    
    def drop_one_packet(self):
        try:
            if self.protocol_instance:
                self.loop.call_soon_threadsafe(
                    self.protocol_instance.set_drop_mode,
                    DropMode.ONE
                )
        except Exception as e:
            self.logger.error(f"Error dropping packet on {self.name}: {e}")
    
    def set_disconnected(self, disconnected):
        if disconnected:
            self.protocol_instance.set_drop_mode(DropMode.ALL)
        else:
            self.protocol_instance.set_drop_mode(DropMode.NONE)
    
    def get_snapshot(self):
        return {
            "name": self.name,
            "ip": self.addr[0],
            "port": self.addr[1],
            "type": "client" if self.is_client else "server",
            "link": self.protocol_instance.get_link_status()
        }

class LivenessPort(ThreadedUDPPort):
    def __init__(self, loop, logger, is_client, addr, name, **kwargs):
        super().__init__(loop, logger, is_client, addr, name, **kwargs)
    
    async def run_link(self):
        while True:
            transport = None
            try:
                transport, self.protocol_instance = await self.loop.create_datagram_endpoint(
                    lambda: LivenessProtocol(logger=self.logger, is_client=self.is_client), 
                    remote_addr=self.remote_addr,
                    local_addr=self.local_addr
                )
                await self.protocol_instance.disconnected_future
            finally:
                if transport:
                    transport.close()
                print(f"Resetting {'Client to' if self.is_client else 'Server on'} {self.addr}")
                await asyncio.sleep(1)

class AlphabetPort(LivenessPort):
    def __init__(self, loop, logger, is_client, addr, name, **kwargs):
        super().__init__(loop, logger, is_client, addr, name, **kwargs)

    async def run_link(self):
        while True:
            transport = None
            try:
                transport, self.protocol_instance = await self.loop.create_datagram_endpoint(
                    lambda: AlphabetProtocol(logger=self.logger, is_client=self.is_client), 
                    remote_addr=self.remote_addr,
                    local_addr=self.local_addr
                )
                await self.protocol_instance.disconnected_future
            finally:
                if transport:
                    transport.close()
                print(f"Resetting {'Client to' if self.is_client else 'Server on'} {self.addr}")
                await asyncio.sleep(1)

class TreePort(LivenessPort):
    def __init__(self, loop, logger, is_client, addr, name, read_q, write_q, signal_q, **kwargs):
        super().__init__(loop, logger, is_client, addr, name, **kwargs)

        self.read_q = read_q
        self.write_q = write_q
        self.signal_q = signal_q
    
    async def run_link(self):
        while True:
            try:
                transport, self.protocol_instance = await self.loop.create_datagram_endpoint(
                    lambda: TreeProtocol(
                        read_q=self.read_q,
                        write_q=self.write_q,
                        signal_q=self.signal_q,
                        logger=self.logger,
                        is_client=self.is_client
                    ), 
                    remote_addr=self.remote_addr,
                    local_addr=self.local_addr
                )
                self.signal_q.put(Data(content=b"CONNECTED"))
                await self.protocol_instance.disconnected_future
            finally:
                if transport:
                    transport.close()
                self.signal_q.put(Data(content=b"DISCONNECTED"))
                await asyncio.sleep(1)

@dataclass
class PortConfig:
    loop: AbstractEventLoop
    logger: logging.Logger
    interface: str
    name: str


class SymmetricPort(ThreadedUDPPort):
    def __init__(self, config: PortConfig, read_q: PipeQueue, write_q: PipeQueue, signal_q: PipeQueue, **kwargs):
        # Pass **kwargs to the parent class constructor
        super().__init__(config.loop, config.logger, False, None, config.name, **kwargs)
        
        # Initialize the instance variables
        self.config = config
        self.read_q = read_q
        self.write_q = write_q
        self.signal_q = signal_q

        self.is_client = False
        self.remote_addr = None
        self.local_addr = None
        
    
    def extract_running_details(self, result) -> Tuple[bool, Optional[Tuple[str, int]], Optional[Tuple[str, int]]]:
        is_client = False
        remote_addr = None
        local_addr = None
        
        # Loop through the result to extract relevant details
        for ipv6_address, address_type, role in result:
            if address_type == 'local':
                if role == 'client':
                    # If local address is a client, set is_client to True
                    is_client = True
                    # Find the server address (role == 'server') and set remote_addr
                    for server_ipv6, server_type, server_role in result:
                        if server_role == 'server' and server_type == 'neighbor':
                            remote_addr = (server_ipv6 + f"%{self.config.interface}", 55555)  # Use server address for remote
                            break
                elif role == 'server':
                    # If local address is a server, set local_addr
                    local_addr = (ipv6_address + f"%{self.config.interface}", 55555)
        
        # Return the tuple with the flags and addresses
        return is_client, remote_addr, local_addr

    
    async def run_link(self):
        while True:
            neighbor_connected = False

            while not neighbor_connected:
                try:
                    result = await get_ipv6_neighbors(self.config.interface)

                    if result:
                        self.is_client, self.remote_addr, self.local_addr = self.extract_running_details(result)
                        self.config.logger.info(f"Found Neighbor. result={result}")
                        self.config.logger.info(f"Found Neighbor. Running Details: is_client={self.is_client}, remote_addr={self.remote_addr}, local_addr={self.local_addr}")
                        neighbor_connected = True
                        continue
                    else:
                        self.config.logger.info(f"No IPv6 addresses found on {self.config.interface}. Retrying...")
                
                except Exception as e:
                    self.config.logger.info(f"Error: {e}")
                    asyncio.run(asyncio.sleep(0.5))

            try:
                transport, self.protocol_instance = await self.loop.create_datagram_endpoint(
                    lambda: TreeProtocol(
                        read_q=self.read_q,
                        write_q=self.write_q,
                        signal_q=self.signal_q,
                        logger=self.config.logger,
                        is_client=self.is_client
                    ), 
                    remote_addr=self.remote_addr,
                    local_addr=self.local_addr
                )
                self.signal_q.put(Data(content=b"CONNECTED"))
                await self.protocol_instance.disconnected_future
            finally:
                if transport:
                    transport.close()
                self.signal_q.put(Data(content=b"DISCONNECTED"))
                await asyncio.sleep(1)

    def get_snapshot(self):
        if self.remote_addr == None and self.local_addr == None:
            return {
                "name": self.name,
                "ip": "disconnected",
                "port": "disconnected",
                "type": "client" if self.is_client else "server",
                "link": "NONE"
            }

        return {
            "name": self.name,
            "ip": self.remote_addr[0] if self.is_client else self.local_addr[0],
            "port": self.remote_addr[1] if self.is_client else self.local_addr[1],
            "type": "client" if self.is_client else "server",
            "link": self.protocol_instance.get_link_status()
        }
