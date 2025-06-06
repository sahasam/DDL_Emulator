import asyncio
from typing import Optional

from hermes.faults.FaultInjector import ThreadSafeFaultInjector
from hermes.model.ports import PortIO
from hermes.model.types import IPV6_ADDR
from hermes.port.protocol import LinkProtocol


class EthernetProtocolExtended(LinkProtocol):
    def __init__(self,
                 io: PortIO,
                 name: str,
                 sending_addr: IPV6_ADDR,
                 is_client: bool,
                 faultInjector: Optional[ThreadSafeFaultInjector]=None):
        super().__init__(io, name, sending_addr, is_client, faultInjector)
        self._send_task: Optional[asyncio.Task] = None
        self._send_heartbeat_task: Optional[asyncio.Task] = None
    
    def on_connected(self):
        self.logger.info("Executing onConnected function")
        self._send_task = asyncio.get_event_loop().create_task(self._process_send())
        self._send_heartbeat_task = asyncio.get_event_loop().create_task(self._send_heartbeat())

    def on_disconnected(self):
        if self._send_task:
            self._send_task.cancel()
        if self._send_heartbeat_task:
            self._send_heartbeat_task.cancel()
            
    def _handle_normal_packet(self, data, addr):
        """Handle normal data packets after handshake"""
        self.io.read_q.put(data)

    async def _process_send(self):
        """Process sending packets to the peer"""
        self.logger.info(f"Process send started")
        try:
            while True:
                if not self.io.write_q.empty():
                    data = self.io.write_q.get()
                    if self.is_client:
                        self.transport.sendto(data)
                    else:
                        self.transport.sendto(data, self.sending_addr)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            self.logger.info("Process send cancelled")
        except Exception as e:
            self.logger.error(f"Error in _process_send_client: {e}", exc_info=True)
                    
    
    async def _send_heartbeat(self):
        """Send a periodic heartbeat to the peer"""
        try:
            while True:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                if self.is_client:
                    self.transport.sendto(b"HEARTBEAT")
                else:
                    self.transport.sendto(b"HEARTBEAT", self.sending_addr)
        except asyncio.CancelledError:
            self.logger.info("Heartbeat task cancelled")
        except Exception as e:
            self.logger.error(f"Error in _send_heartbeat: {str(e)}", exc_info=True)

    def get_link_status(self):
        return {
            "protocol": "EthernetProtocol",
            "status": self.link_state.value,
        }
