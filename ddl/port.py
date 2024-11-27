"""
port.py

Represent a single terminal of the emulated network. One port represents one port thread on a machine,
and handles raw packets asynchronously from the rest of the system. The port abstraction allows the
emulation to manually inject all different types of faults as present in clos networks or perr-to-peer links.

The port abstraction is intended to be symmetric to all layers above, but due to limitations of UDP as
the link prtocol, the client/server interactions are hidden below.
"""
from ddl.protocol import ABPProtocol, DropMode

import threading
import asyncio

class ThreadedUDPPort(threading.Thread):
    def __init__(self, loop, logger, is_client, addr, **kwargs):
        super().__init__(**kwargs)
        self.loop = loop
        self.logger = logger
        self.is_client = is_client
        self.addr = addr
        self.remote_addr = addr if is_client else None
        self.local_addr = addr if not is_client else None
        self.protocol_instance = None
    
    def get_pretty_link_details(self):
        return "* UDP {:<5} * Address: {:>12}:{:<5} *" \
                .format("Client" if self.is_client else "Server", *self.addr)

    def run(self):
        self.loop.run_until_complete(self.loop.create_task(self.run_link()))
    
    async def run_link(self):
        while True:
            try:
                transport, self.protocol_instance = await self.loop.create_datagram_endpoint(
                    lambda: ABPProtocol(logger=self.logger, is_client=self.is_client), 
                    remote_addr=self.remote_addr,
                    local_addr=self.local_addr
                )
                await self.protocol_instance.disconnected_future
            finally:
                transport.close()
                print("Resetting connection")
                await asyncio.sleep(1)
    
    def drop_one_packet(self):
        if self.protocol_instance:
            self.loop.call_soon_threadsafe(self.protocol_instance.set_drop_mode(DropMode.ONE))

