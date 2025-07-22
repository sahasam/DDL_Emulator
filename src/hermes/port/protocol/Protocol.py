import asyncio
from enum import Enum
import logging
from typing import Callable, Optional
import time
from hermes.faults.FaultInjector import ThreadSafeFaultInjector
from hermes.model.ports import PortIO
from hermes.model.types import IPV6_ADDR
    

class EthernetProtocol(asyncio.DatagramProtocol):
    class LinkState(Enum):
        HANSHAKING = 'handshaking'
        CONNECTED = 'connected'
        DISCONNECTED = 'disconnected'

    def __init__(self,
                 io: PortIO,
                 name: str,
                 sending_addr: IPV6_ADDR,
                 is_client: bool,
                 faultInjector: Optional[ThreadSafeFaultInjector]=None):
        super().__init__()
        self.HEARTBEAT_INTERVAL = 0.25

        self.logger = logging.getLogger(f"Protocol.{name}")
        self.logger.info(f"Protocol {name} initialized")
        self.name = name
        self.faultInjector = faultInjector
        self.io = io
        self.link_state = self.LinkState.DISCONNECTED
        self.sending_addr = sending_addr
        self.is_client = is_client

        self.statistics = {
            'packet_sent': 0,
            'packet_received': 0,
            'bytes_sent': 0,
            'bytes_received': 0,
            'heartbeat_sent': 0,
            'heartbeat_received': 0,
            'data_packets_sent': 0,
            'data_packets_received': 0,
            'connection_time': 0,
            'last_activity': time.time(),
            'handshake_attempts': 0,
            'events': 0
        }

        self._ping_alive_task: Optional[asyncio.Task] = None
        self._send_task: Optional[asyncio.Task] = None
        self._timeout_task: Optional[asyncio.Task] = None
        self._send_heartbeat_task: Optional[asyncio.Task] = None
        self._last_received: float = 0.0
        self.neighbor_portid: Optional[str] = None

        self.disconnected_future = asyncio.Future()
        self._packet_handler = self._handle_handshake if is_client else self._handle_server_handshake

        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        self.statistics['connection_time'] = time.time()

        sock = transport.get_extra_info('socket')
        local_addr = sock.getsockname()
        peer_addr = transport.get_extra_info('peername')
        
        # Get more socket details for debugging
        sock_family = sock.family
        sock_type = sock.type
        sock_proto = sock.proto

        self.logger.info(f"Connection made:")
        self.logger.info(f"  Local address: {local_addr}")
        self.logger.info(f"  Peer address: {peer_addr}")
        self.logger.info(f"  Sending address: {self.sending_addr}")
        self.logger.info(f"  Socket family: {sock_family}, type: {sock_type}, proto: {sock_proto}")
        self.logger.info(f"  Socket fileno: {sock.fileno()}")

        if self.is_client:
            _loop = asyncio.get_event_loop()
            self._ping_alive_task = _loop.create_task(self._ping_alive())
    
    async def _send_heartbeat(self):
        """Send a periodic heartbeat to the peer"""
        try:
            while True:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                if self.is_client:
                    self.transport.sendto(b"HEARTBEAT")
                else:
                    self.transport.sendto(b"HEARTBEAT", self.sending_addr)
                    
                # tracking statistics
                self.statistics['heartbeat_sent'] += 1
                self.statistics['packets_sent'] += 1
                self.statistics['bytes_sent'] += len(b"HEARTBEAT")
                
        except asyncio.CancelledError:
            self.logger.info("Heartbeat task cancelled")
        except Exception as e:
            self.logger.error(f"Error in _send_heartbeat: {str(e)}", exc_info=True)
    
    async def _heartbeat_timeout(self):
        """Check if the heartbeat has timed out"""
        try:
            while True:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL*1.5)
                now = asyncio.get_event_loop().time()
                if now - self._last_received > self.HEARTBEAT_INTERVAL*1.5:
                    self.logger.error("Connection timed out")
                    self.transport.close()
        except asyncio.CancelledError:
            self.logger.info("Heartbeat timeout task cancelled")
        except Exception as e:
            self.logger.error(f"Error in _heartbeat_timeout: {str(e)}", exc_info=True)
                
    def datagram_received(self, data, addr):
        self._last_received = asyncio.get_event_loop().time()
        
        self.statistics['packet_received'] += 1
        self.statistics['bytes_received'] += len(data)
        self.statistics['last_activity'] = time.time()
        self.statistics['events'] += 1
        
        if data == b"HEARTBEAT":
            self.statistics['heartbeat_received'] += 1
            return
        
        self.statistics['data_packets_received'] += 1
        self._packet_handler(data, addr)
    
    def _handle_handshake(self, data, addr):
        """Handle packets during client handshake phase"""
        if data.startswith(b"YESIAM "):
            self.neighbor_portid = data.split(b" ")[1].decode('utf-8')
            self.link_state = self.LinkState.CONNECTED
            self._ping_alive_task.cancel()
            # Switch to normal packet handling
            self._packet_handler = self._handle_normal_packet
            self.io.signal_q.put(b"CONNECTED")
            # Start send task
            _loop = asyncio.get_event_loop()
            self._send_task = _loop.create_task(self._process_send_client())
            self._send_heartbeat_task = _loop.create_task(self._send_heartbeat())
            self._timeout_task = _loop.create_task(self._heartbeat_timeout())

    def _handle_server_handshake(self, data, addr):
        """Handle packets during server handshake phase"""
        if data.startswith(b"AREYOUTHERE "):
            self.neighbor_portid = data.split(b" ")[1].decode('utf-8')
            self.link_state = self.LinkState.CONNECTED
            self.sending_addr = addr
            response_data = b"YESTHISIS " + self.name.encode('utf-8')
            self.transport.sendto(response_data, addr)
            
            self.statistics['packets_sent'] += 1
            self.statistics['bytes_sent'] += len(response_data)
            
            # Switch to normal packet handling
            self._packet_handler = self._handle_normal_packet
            # Start send task
            _loop = asyncio.get_event_loop()
            self._send_task = _loop.create_task(self._process_send_server())
            self._send_heartbeat_task = _loop.create_task(self._send_heartbeat())
            self._timeout_task = _loop.create_task(self._heartbeat_timeout())
            self.io.signal_q.put(b"CONNECTED")

    def _handle_normal_packet(self, data, addr):
        """Handle normal data packets after handshake"""
        self.io.read_q.put(data)
    
    async def _ping_alive(self):
        """Continually send ping messages to the peer"""
        self.logger.info(f"Ping alive task started")
        start_time = asyncio.get_event_loop().time()
        try:
            while True:
                await asyncio.sleep(0.5)
                if asyncio.get_event_loop().time() - start_time > 10.0:
                    self.logger.info("ping alive timeout")
                    self.transport.close()
                    return
                ping_data = b"AREYOUTHERE " + self.name.encode('utf-8')
                self.transport.sendto(ping_data)
            
                self.statistics['handshake_attempts'] += 1
                self.statistics['packets_sent'] += 1
                self.statistics['bytes_sent'] += len(ping_data)
                
                self.logger.info(f"Ping alive -- sending AREYOUTHERE")
        except asyncio.CancelledError:
            self.logger.info("Ping alive task cancelled")
        except Exception as e:
            self.logger.error(f"Error in _ping_alive: {e}", exc_info=True)

    async def _process_send_client(self):
        """Continually send data from the write queue to the transport if connected"""
        self.logger.info(f"Process send started")
        try:
            while True:
                if not self.io.write_q.empty():
                    data = self.io.write_q.get()
                    self.transport.sendto(data)
                    
                    self.statistics['data_packets_sent'] += 1
                    self.statistics['packets_sent'] += 1
                    self.statistics['bytes_sent'] += len(data)
                    self.statistics['last_activity'] = time.time()
                    
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            self.logger.info("Process send cancelled")
        except Exception as e:
            self.logger.error(f"Error in _process_send_client: {e}", exc_info=True)
    
    async def _process_send_server(self):
        """Continually send data from the write queue to the transport if connected"""
        self.logger.info(f"Process send started")
        try:
            while True:
                if not self.io.write_q.empty():
                    data = self.io.write_q.get()
                    self.transport.sendto(data, self.sending_addr)
                    
                    self.statistics['data_packets_sent'] += 1
                    self.statistics['packets_sent'] += 1
                    self.statistics['bytes_sent'] += len(data)
                    self.statistics['last_activity'] = time.time()
                    
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            self.logger.info("Process send cancelled")
        except Exception as e:
            self.logger.error(f"Error in _process_send_client: {e}", exc_info=True)
    
    def get_link_status(self):
        uptime = time.time() - self.statistics['connection_time']
        
        return {
            "protocol": "EthernetProtocol",
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
