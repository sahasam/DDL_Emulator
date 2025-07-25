import asyncio
from enum import Enum
import logging
from typing import Callable, Optional

from hermes.faults.FaultInjector import ThreadSafeFaultInjector
from hermes.model.ports import PortIO
from hermes.model.types import IPV6_ADDR

class LinkProtocol(asyncio.DatagramProtocol):
    """
    LinkProtocol abstracts the connection/timeout logic for handing the L4 Thunderbolt Link Connection.
    Subclasses only need to implement the _handle_normal_packet method and can focus only
    on the actual packet handling state machines.
    """
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
        self.io = io
        self.name = name
        self.sending_addr = sending_addr
        self.is_client = is_client
        self.faultInjector = faultInjector

        self.neighbor_portid: Optional[str] = None

        self._ping_alive_task: Optional[asyncio.Task] = None
        self._timeout_task: Optional[asyncio.Task] = None
        self._packet_handler: Callable[[bytes, IPV6_ADDR], None] = self._handle_handshake if is_client else self._handle_server_handshake

        self.link_state = self.LinkState.DISCONNECTED
        self.disconnected_future = asyncio.Future()
        self.transport = self._last_received = 0.0
    def connection_made(self, transport):
        self.transport = transport

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
            try:
                _loop = asyncio.get_event_loop()
                self.logger.info(f"Starting Ping alive task: {self._ping_alive_task}")
                self._ping_alive_task = _loop.create_task(self._ping_alive())
                # Ensure the task is actually running
                if self._ping_alive_task.done():
                    raise Exception("Ping alive task failed to start")
                self.logger.info("Ping alive task started successfully")
            except Exception as e:
                self.logger.error(f"Failed to start ping alive task: {e}", exc_info=True)
                self.transport.close()
                return
    
    def _handle_handshake(self, data, addr):
        """Handle packets during client handshake phase"""
        if data.startswith(b"YESIAM "):
            self.neighbor_portid = data.split(b" ")[1].decode('utf-8')
            self.link_state = self.LinkState.CONNECTED
            if self._ping_alive_task:
                self._ping_alive_task.cancel()
            # Switch to normal packet handling
            self._packet_handler = self._handle_normal_packet
            self.io.signal_q.put(b"CONNECTED")
            # Start send task
            _loop = asyncio.get_event_loop()
            self._timeout_task = _loop.create_task(self._connection_timeout())
            self.on_connected()

    def _handle_server_handshake(self, data, addr):
        """Handle packets during server handshake phase"""
        if data.startswith(b"AREYOUTHERE "):
            self.neighbor_portid = data.split(b" ")[1].decode('utf-8')
            self.link_state = self.LinkState.CONNECTED
            self.sending_addr = addr
            self.transport.sendto(b"YESIAM " + self.name.encode('utf-8'), addr)
            # Switch to normal packet handling
            self._packet_handler = self._handle_normal_packet
            self.io.signal_q.put(b"CONNECTED")
            # Start send task
            _loop = asyncio.get_event_loop()
            self._timeout_task = _loop.create_task(self._connection_timeout())
            self.on_connected()

    
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
                self.transport.sendto(b"AREYOUTHERE " + self.name.encode('utf-8'))
        except asyncio.CancelledError:
            self.logger.info("Ping alive task cancelled")
        except Exception as e:
            self.logger.error(f"Error in _ping_alive: {e}", exc_info=True)

    async def _connection_timeout(self):
        try:
            while True:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL*1.5)
                now = asyncio.get_event_loop().time()
                if now - self._last_received > self.HEARTBEAT_INTERVAL*1.5:
                    self.logger.error("Connection timed out")
                    self.transport.close()
        except asyncio.CancelledError:
            self.logger.info("Connection timeout task cancelled")
        except Exception as e:
            self.logger.error(f"Error in _connection_timeout: {e}", exc_info=True)

    def datagram_received(self, data, addr):
        self._last_received = asyncio.get_event_loop().time()
        try:
            self._packet_handler(data, addr)
        except Exception as e:
            self.logger.error(f"Datagram Processing failed: {e}", exc_info=True)
      
    def connection_lost(self, exc):
        self.logger.info(f"Connection lost: {exc}")
        self.link_state = self.LinkState.DISCONNECTED

        if not self.disconnected_future.done():
            self.disconnected_future.set_result(None)
        if self._ping_alive_task:
            self._ping_alive_task.cancel()
        if self._timeout_task:
            self._timeout_task.cancel()
        self.on_disconnected()
        self.io.signal_q.put(b"DISCONNECTED")

    def _handle_normal_packet(self, data, addr):
        """Handle normal data packets after handshake"""
        raise NotImplementedError("Subclasses must implement this method")
    
    def on_connected(self):
        """Callback for when the connection is established"""
        raise NotImplementedError("Subclasses must implement this method")
    
    def on_disconnected(self):
        """Callback for when the connection is lost"""
        raise NotImplementedError("Subclasses must implement this method")
