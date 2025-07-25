import asyncio
import time
from typing import Optional
from hermes.faults.FaultInjector import ThreadSafeFaultInjector
from hermes.model.ports import PortIO
from hermes.model.types import IPV6_ADDR
from hermes.port.protocol import LinkProtocol
import random

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
                'events': 0,
                'packets_dropped_in': 0,
                'packets_dropped_out': 0,
                'packets_delayed_in': 0,
                'packets_delayed_out': 0
            }
    def on_connected(self):
        """Implementation of required abstract method"""
        self.logger.info("Executing onConnected function")
        self.statistics['connection_time'] = time.time()
        self._send_task = asyncio.get_event_loop().create_task(self._process_send())
        self._send_heartbeat_task = asyncio.get_event_loop().create_task(self._send_heartbeat())

    def on_disconnected(self):
        """Implementation of required abstract method"""
        if self._send_task:
            self._send_task.cancel()
        if self._send_heartbeat_task:
            self._send_heartbeat_task.cancel()
           
    def _handle_normal_packet(self, data, addr):
        """Handle normal data packets after handshake"""
        # Track received statistics
        if data == b'HEARTBEAT':
            self._process_received_packet(data, addr)
            return
        if self._should_drop_packet("in"):
            return # packet is droped
        
        delay_ms = self._get_delay_ms("in")
        if delay_ms > 0:
            asyncio.create_task(self._delayed_handle_packet(data, addr, delay_ms))
            return
        
        self._process_received_packet(data, addr)
        
        
    def _should_drop_packet(self, direction="in") -> bool:
        if not self.faultInjector:
            return False
        
        fault_state = self.faultInjector.get_state()
        if not fault_state.is_active or fault_state.drop_rate <= 0:
            return False
        
        should_drop = random.random() < fault_state.drop_rate
        if should_drop:
            self.statistics[f'packets_dropped_{direction}'] += 1
            self.logger.info(f"FAULT INJECTION: Dropped {direction}bound packet (drop_rate={fault_state.drop_rate})")
        return should_drop
    
        
    async def _delayed_handle_packet(self, data, addr, delay_ms):
        """Handles packet after delay"""
        await asyncio.sleep(delay_ms / 1000.0)
        self._process_received_packet(data, addr)
        
    def _process_received_packet(self, data, addr):
        """Normal packet processing logic"""
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
                    
                    if self._should_drop_packet("out"):
                        continue
                    
                    delay_ms = self._get_delay_ms("out")
                    if delay_ms > 0:
                        asyncio.create_task(self._delayed_send(data, delay_ms))
                        continue
                    
                    self._actual_send(data)
                
                await asyncio.sleep(0)  
        except asyncio.CancelledError:
            self.logger.info("Process send cancelled")
        except Exception as e:
            self.logger.error(f"Error in _process_send_client: {e}", exc_info=True)

    def _actual_send(self, data):
        """Actually send the data packet"""
        if self.is_client:
            self.transport.sendto(data)
        else:
            self.transport.sendto(data, self.sending_addr)
        
        # Track sent statistics
        self.statistics['data_packets_sent'] += 1
        self.statistics['packets_sent'] += 1
        self.statistics['bytes_sent'] += len(data)
        self.statistics['last_activity'] = time.time()
                    
    async def _send_heartbeat(self):
        """Sends a periodict heartbeat to peer with fault injection"""

        try:
            while True:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                
                if self._should_drop_packet("out"):
                    continue
                
                heartbeat_data = b"HEARTBEAT"
                
                delay_ms = self._get_delay_ms("out")
                if delay_ms > 0:
                    asyncio.create_task(self._delayed_send_heartbeat(heartbeat_data, delay_ms))
                    continue
                
                self._actual_send_heartbeat(heartbeat_data)
                
        except asyncio.CancelledError:
            self.logger.info("Heartbeat send task cancelled")
            
        except Exception as e:
            self.logger.error(f"Error in _send_heartbeat: {e}", exc_info=True)
            
    async def _delayed_send_heartbeat(self, data, delay_ms):
        """Sends heartbeat after a delay"""
        await asyncio.sleep(delay_ms / 1000.0)
        self._actual_send_heartbeat(data)
        
    def _actual_send_heartbeat(self, data):
        """Actually sends the heartbeat packet"""
        if self.is_client:
            self.transport.sendto(data)
        else:
            self.transport.sendto(data, self.sending_addr)
        
        # Track heartbeat statistics
        self.statistics['heartbeats_sent'] += 1
        self.statistics['packets_sent'] += 1
        self.statistics['bytes_sent'] += len(data)
        self.statistics['last_activity'] = time.time()
        
    def _get_delay_ms(self, direction="in") -> int:
        if not self.faultInjector:
            return 0
        
        fault_state = self.faultInjector.get_state()
        if not fault_state.is_active or fault_state.delay_ms <= 0:
            return 0
        
        self.statistics[f'packets_delayed_{direction}'] += 1
        self.logger.info(f"FAULT INJECTION: Delaying {direction}bound packet by {fault_state.delay_ms} ms")
        return fault_state.delay_ms

                
                

   
    def get_link_status(self):
        uptime = time.time() - self.statistics['connection_time'] if self.statistics['connection_time'] > 0 else 0
        
        # Add fault injection status to link status
        fault_status = {}
        if self.faultInjector:
            fault_state = self.faultInjector.get_state()
            fault_status = {
                'fault_injection_active': fault_state.is_active,
                'drop_rate': fault_state.drop_rate,
                'delay_ms': fault_state.delay_ms,
                'packets_dropped_in': self.statistics['packets_dropped_in'],
                'packets_dropped_out': self.statistics['packets_dropped_out'],
                'packets_delayed_in': self.statistics['packets_delayed_in'],
                'packets_delayed_out': self.statistics['packets_delayed_out']
            }
        
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
                "events": self.statistics['events'],
                **fault_status  # Include fault injection statistics
            }
        }