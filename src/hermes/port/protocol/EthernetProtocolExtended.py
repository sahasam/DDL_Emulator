import asyncio
import time
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
        
        # Add statistics tracking
        self.statistics = {
            'packets_sent': 0,
            'packets_received': 0,
            'bytes_sent': 0,
            'bytes_received': 0,
            'heartbeats_sent': 0,
            'heartbeats_received': 0,
            'data_packets_sent': 0,
            'data_packets_received': 0,
            'connection_time': 0,
            'last_activity': time.time(),
            'events': 0
        }
    
    def on_connected(self):
        self.logger.info("Executing onConnected function")
        self.statistics['connection_time'] = time.time()  # Track connection time
        self._send_task = asyncio.get_event_loop().create_task(self._process_send())
        self._send_heartbeat_task = asyncio.get_event_loop().create_task(self._send_heartbeat())

    def on_disconnected(self):
        if self._send_task:
            self._send_task.cancel()
        if self._send_heartbeat_task:
            self._send_heartbeat_task.cancel()
            
    def _handle_normal_packet(self, data, addr):
        """Handle normal data packets after handshake"""
        # Track received statistics
        self.statistics['packets_received'] += 1
        self.statistics['bytes_received'] += len(data)
        self.statistics['last_activity'] = time.time()
        self.statistics['events'] += 1
        
        if data == b"HEARTBEAT":
            self.statistics['heartbeats_received'] += 1
        else:
            self.statistics['data_packets_received'] += 1
            
        self.io.read_q.put(data)

    async def _process_send(self):
        """Process sending packets to the peer"""
        self.logger.info(f"Process send started")
        try:
            while True:
                if not self.io.write_q.empty():
                    data = self.io.write_q.get()
                    
                    # Send the packet
                    if self.is_client:
                        self.transport.sendto(data)
                    else:
                        self.transport.sendto(data, self.sending_addr)
                    
                    # Track sent statistics
                    self.statistics['data_packets_sent'] += 1
                    self.statistics['packets_sent'] += 1
                    self.statistics['bytes_sent'] += len(data)
                    self.statistics['last_activity'] = time.time()
                    
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
                heartbeat_data = b"HEARTBEAT"
                
                if self.is_client:
                    self.transport.sendto(heartbeat_data)
                else:
                    self.transport.sendto(heartbeat_data, self.sending_addr)
                
                # Track heartbeat statistics
                self.statistics['heartbeats_sent'] += 1
                self.statistics['packets_sent'] += 1
                self.statistics['bytes_sent'] += len(heartbeat_data)
                self.statistics['last_activity'] = time.time()
                
        except asyncio.CancelledError:
            self.logger.info("Heartbeat task cancelled")
        except Exception as e:
            self.logger.error(f"Error in _send_heartbeat: {str(e)}", exc_info=True)

    def get_link_status(self):
        uptime = time.time() - self.statistics['connection_time'] if self.statistics['connection_time'] > 0 else 0
        
        return {
            "protocol": "EthernetProtocolExtended",
            "status": self.link_state.value,
            "statistics": {
                "packets_sent": self.statistics['packets_sent'],
                "packets_received": self.statistics['packets_received'],
                "bytes_sent": self.statistics['bytes_sent'],
                "bytes_received": self.statistics['bytes_received'],
                "heartbeats_sent": self.statistics['heartbeats_sent'],
                "heartbeats_received": self.statistics['heartbeats_received'],
                "data_packets_sent": self.statistics['data_packets_sent'],
                "data_packets_received": self.statistics['data_packets_received'],
                "uptime_seconds": uptime,
                "last_activity_ago": time.time() - self.statistics['last_activity'],
                "events": self.statistics['events']
            }
        }