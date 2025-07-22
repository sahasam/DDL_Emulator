"""
port.py

Represent a single terminal of the emulated network. One port represents one port thread on a machine,
and handles raw packets asynchronously from the rest of the system. The port abstraction allows the
emulation to manually inject all different types of faults as present in clos networks or perr-to-peer links.

The port abstraction is intended to be symmetric to all layers above, but due to limitations of UDP as
the link prtocol, the client/server interactions are hidden below.
"""
from typing import Optional, Tuple, Type
from hermes.faults.FaultInjector import ThreadSafeFaultInjector
from hermes.model.ports import PortConfig, PortIO
from hermes.model.types import IPV6_ADDR
from hermes.port.protocol import LinkProtocol, EthernetProtocolExtended

import logging
import threading
import asyncio

from hermes.util import get_ipv6_neighbors

class BasePort(threading.Thread):
    def __init__(self,
                 config: PortConfig,
                 io: PortIO,
                 faultInjector: Optional[ThreadSafeFaultInjector]=None,
                 **kwargs):
        super().__init__(**kwargs)
        self._loop = asyncio.new_event_loop()
        self.stop_event = asyncio.Event()
        self.faultInjector = faultInjector
        # Create a handler for the logger that works with asyncio
        self.logger = logging.getLogger("Port." + config.port_id)

        self.config = config
        self.io = io

        self.tree_instance_id: Optional[str] = None

        self.protocol_instance = None
        self.daemon = True
    
    def run(self):
        """Main loop for the port thread."""
        self.logger.info(f"Starting port thread for {self.name}")
        asyncio.set_event_loop(self._loop)
        
        async def main_runner():
            """Coroutine to run the port's main logic."""
            run_link_task = self._loop.create_task(self.run_link())
            
            await self.stop_event.wait()  # Wait until stop_event is set
            
            self.logger.info(f"Stop event received, cancelling tasks for {self.port_id}")
            
            run_link_task.cancel()
            
            
            try:
                await run_link_task
            except asyncio.CancelledError:
                self.logger.info(f"Run link task cancelled for {self.port_id}")
                
        
        try:
            self._loop.run_until_complete(main_runner())
        except Exception as e:
            self.logger.error(f"Fatal error in port thread {self.port_id}: {e}", exc_info=True)
        
        finally:
            self.logger.info(f"Shutting down and closing event loop for {self.port_id}")
            tasks = asyncio.all_tasks(loop=self._loop)
            for task in tasks:
                task.cancel()
                
            async def gather_cancelled():
                await asyncio.gather(*tasks, return_exceptions=True)
            
            self._loop.run_until_complete(gather_cancelled())
            self._loop.close()
    # def run(self):
    #     """
    #     Main loop for the port thread.
    #     """
    #     self.logger.info(f"Starting UDP port thread for {self.name}")
    #     asyncio.set_event_loop(self._loop)
        
    #     try:
    #         # Create tasks explicitly
    #         run_link_task = self._loop.create_task(self.run_link())

    #         while not self.stop_event.is_set():
    #             try:
    #                 # Wait for either task to complete
    #                 self._loop.run_until_complete(
    #                     asyncio.wait_for(
    #                         self.stop_event.wait(),
    #                         timeout=None
    #                     )
    #                 )
    #             except asyncio.TimeoutError:
    #                 continue
    #             except Exception as e:
    #                 self.logger.error(f"Error in port thread {self.port_id}: {e}")
    #                 continue
            
    #         # Close any open transport
    #         run_link_task.cancel()
                
    #     except Exception as e:
    #         self.logger.error(f"Error in port thread {self.port_id}: {e}")
    #     finally:
    #         self.logger.info(f"Shutting down UDP port thread for {self.port_id}")
    #         self._loop.close()
    
    async def run_link(self):
        raise NotImplementedError("Subclasses must implement run_link")
    
    def drop_one_packet(self):
        pass
    
    def set_disconnected(self, disconnected):
        pass
    
    def get_snapshot(self):
        return {
            "name": self.name,
            "ip": self.addr[0],
            "port": self.addr[1],
            "type": "client" if self.is_client else "server",
            "link": self.protocol_instance.get_link_status()
        }
    
    def get_pretty_link_details(self):
        return "* UDP {:<5} * Interface: {:>7} * Address: {:>12}:{:<5} *" \
                .format("Client" if self.is_client else "Server", self.port_id, *self.addr)
    
    def stop(self):
        """Thread-safe method to signal the port's event loop to stop."""
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self.stop_event.set)



class UDPPort(BasePort):
    def __init__(self,
                 config: PortConfig,
                 io: PortIO,
                 faultInjector: Optional[ThreadSafeFaultInjector]=None,
                 protocolClass: Optional[Type[LinkProtocol]]=None,
                 **kwargs):
        # Pass **kwargs to the parent class constructor
        super().__init__(config, io, faultInjector, **kwargs)
        self.port_id = config.port_id
        self.name = config.name
        self.protocolClass = protocolClass or EthernetProtocolExtended
        # Check if interface is a virtual address (e.g. "127.0.0.1:45454" or "127.0.0.1:45454:45455")
        self.is_virtual = ":" in self.config.interface
        if self.is_virtual:
            parts = self.config.interface.split(":")
            if len(parts) == 3:
                # If two ports are specified, use them as local and remote ports
                self.local_port = int(parts[1])
                self.remote_port = int(parts[2])
            else:
                raise ValueError("Virtual interface must be in format 'host:local_port:remote_port'")
            self.host = parts[0]
    
    async def wait_for_connection(self) -> Tuple[bool, Optional[IPV6_ADDR], Optional[IPV6_ADDR]]:
        try:
            while True:
                if self.is_virtual:
                    # For virtual connections, use the configured ports
                    local_addr = (self.host, self.local_port)
                    remote_addr = (self.host, self.remote_port)
                    
                    # The port with the lower port number is the server
                    self.is_client = self.local_port > self.remote_port
                    
                    self.remote_addr = remote_addr
                    self.local_addr = local_addr
                    self.logger.info(f"Virtual connection setup - local: {local_addr}, remote: {remote_addr}, is_client: {self.is_client}")
                    return (self.is_client, self.remote_addr, self.local_addr)
                else:
                    # For real ethernet interfaces, use IPv6 neighbor discovery
                    result = await get_ipv6_neighbors(self.config.interface)
                    if result:
                        self.is_client, self.remote_addr, self.local_addr = self.extract_running_details(result)
                        self.logger.info(f"Found Neighbor. result={result}")
                        return (self.is_client, self.remote_addr, self.local_addr)
                await asyncio.sleep(1)  # Add delay between retries
        except asyncio.CancelledError:
            self.logger.info(f"Wait for connection cancelled for {self.port_id}")
            return
        except Exception as e:
            self.logger.error(f"Error waiting for connection for {self.port_id}: {e}")
            return

    async def run_link(self):
        self.logger.info(f"{self.port_id} -- Running link")
        try:
            while True:
                (is_client, remote_addr, local_addr) = await self.wait_for_connection()
                self.logger.info(f"{self.port_id} -- Waiting for connection complete")

                transport = None
                try:
                    self.logger.info(f"{self.port_id} -- Creating datagram endpoint with local_addr={local_addr}, remote_addr={remote_addr if is_client else None}")
                    transport, self.protocol_instance = await self._loop.create_datagram_endpoint(
                        lambda: self.protocolClass(
                            io=self.io,
                            name=self.config.port_id,
                            sending_addr=remote_addr,
                            is_client=is_client,
                            faultInjector=self.faultInjector
                        ), 
                        remote_addr=remote_addr if is_client else None,
                        local_addr=local_addr,  
                        reuse_port=True
                    )
                    self.logger.info(f"{self.port_id} -- Transport opened successfully")
                    
                    if not self.protocol_instance:
                        raise Exception("Protocol instance not created")
                        
                    self.logger.info(f"{self.port_id} -- Waiting for disconnected future")
                    await self.protocol_instance.disconnected_future
                    self.logger.info(f"{self.port_id} -- Disconnected future completed")
                except Exception as e:
                    self.logger.error(f"Error in run_link for {self.port_id}: {str(e)}", exc_info=True)
                    if transport:
                        transport.close()
                    self.protocol_instance = None
                    await asyncio.sleep(1)
                    continue
                finally:
                    self.logger.info(f"{self.port_id} -- Transport closed")
                    if transport:
                        transport.close()
                    self.protocol_instance = None
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            self.logger.info(f"Run link cancelled for {self.port_id}")
            return
        except Exception as e:
            self.logger.error(f"Error in run_link for {self.port_id}: {str(e)}", exc_info=True)
            return
    
    def extract_running_details(self, result) -> Tuple[bool, IPV6_ADDR, IPV6_ADDR]:
        is_client = False
        remote_addr = None
        local_addr = None
        self.logger.info(f"Result: {result}")
        
        # Loop through the result to extract relevant details
        for ipv6_address, address_type, role in result:
            if role == 'client' and address_type == 'local':
                is_client = True
                local_addr = (ipv6_address + f"%{self.config.interface}", 55555)
            elif role == 'client' and address_type == 'neighbor':
                is_client = False
                remote_addr = (ipv6_address + f"%{self.config.interface}", 55555)
            elif role == 'server' and address_type == 'local':
                local_addr = (ipv6_address + f"%{self.config.interface}", 55555)
            elif role == 'server' and address_type == 'neighbor':
                remote_addr = (ipv6_address + f"%{self.config.interface}", 55555)
        
        # Return the tuple with the flags and addresses
        self.logger.info(f"is_client: {is_client}, remote_addr: {remote_addr}, local_addr: {local_addr}")
        return is_client, remote_addr, local_addr

    def get_snapshot(self):
        if self.protocol_instance is None:
            return {
                "name": self.port_id,
                "link": {
                    "protocol": "EthernetProtocol",
                    "status": "disconnected",
                }
            }

        return {
            "name": self.port_id,
            "connection": {
                "local_address": str(self.local_addr),
                "neighbor_address": str(self.remote_addr),
                "neighbor_portid": self.protocol_instance.neighbor_portid,
                "is_client": self.is_client,
            },
            "link": {
                "protocol": "EthernetProtocol",
                "status": self.protocol_instance.link_state.value,
            }
        }
