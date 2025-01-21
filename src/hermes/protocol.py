from abc import ABC
import asyncio
from hashlib import sha256
import random
import struct
import time
from enum import Enum

from hermes.machines.data import Data, Hyperdata, PacketBuilder
from hermes.machines.statemachine import AlphabetStateMachine, LivenessStateMachine, StateMachine, StateMachineFactory, TwoPhaseCommitPipeStateMachine
from hermes.machines.common import SMP, Identity
from hermes.algorithm import PipeQueue


class ABPState:
    def __init__(self):
        self.send_bit = 0
        self.send_value = 0
        self.expected_bit = 0

class DropMode(Enum):
    NONE = 0
    ONE = 1
    ALL = 2

class DropConfig:
    def __init__(self):
        self.mode = DropMode.NONE
    
    def __str__(self):
        return f"DropConfig(mode={self.mode})"
    
    def __repr__(self):
        return self.__str__()

class DDLSymmetric(asyncio.DatagramProtocol):
    def __init__(self, logger=None, is_client=False):
        super().__init__()
        self.drop_config = DropConfig()
        self.logger = logger
        self.is_client = is_client
        self.disconnected_future = asyncio.Future()
        self.statistics = {
            'events': 0,
            'round_trip_latency': 0,
            'pps': 0
        }
        self.logger.info(f"Started Connection Instance. is_client={is_client}")
        self._last_recv_time = time.time()

        asyncio.create_task(self.update_statistics(refresh=0.1))
        # if (is_client):
            # asyncio.create_task(self.check_timeout())
    
    def set_drop_mode(self, mode):
        self.drop_config.mode = mode
    
    def _should_drop_packet(self):
        if self.drop_config.mode != DropMode.NONE:
            if self.drop_config.mode == DropMode.ONE:
                self.drop_config.mode = DropMode.NONE
            self.logger.debug("Dropping packet DropMode={}".format(self.drop_config.mode))
            return True
        return False

    def connection_lost(self, exc):
        self.logger.info("Connection lost {}".format(exc))
        if not self.disconnected_future.done():
            self.disconnected_future.set_result(True)

    def connection_made(self, transport):
        self.logger.info("Connection made")
        self.transport = transport

    def error_received(self, exc):
        self.disconnected_future.set_result(True)
        self.logger.error('Error received: {}'.format(exc))

    async def check_timeout(self, timeout=1):
        self.logger.info("Started timeout routine")
        while not self.disconnected_future.done():
            elapsed_time = time.time() - self._last_recv_time
            if elapsed_time > timeout:
                self.logger.info("Timeout'd")
                if self.transport:
                    self.reset_protocol()
                    self.transport.sendto(self.create_packet())
            
            await asyncio.sleep(timeout)
    
    def get_link_status(self):
        return {
            "status": "connected" if self.statistics['events'] > 0 else "disconnected",
            "statistics": self.statistics
        }
    
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> bool:
        if self._should_drop_packet():
            return True
        
        self.statistics['events'] += 1
        self._last_recv_time = time.time()
        return False
    
    async def update_statistics(self, refresh=0.1):
        prev_stats_update_time = time.time()
        while not self.disconnected_future.done():
            elapsed_time = time.time() - prev_stats_update_time
            if elapsed_time == 0:
                continue

            prev_stats_update_time = time.time()
            if self.statistics['events'] > 0:
                self.statistics['round_trip_latency'] = round((elapsed_time / self.statistics['events'])*1e6, 2)
                self.statistics['pps'] = round((self.statistics['events'] / elapsed_time), 2)
            else:
                self.statistics['round_trip_latency'] = 999999
                self.statistics['pps'] = 0

            self.logger.info("STATS events={} round_trip_latency_us={:.2f} pps={:.2f}".format(
                self.statistics['events'],
                self.statistics['round_trip_latency']*1e6,
                self.statistics['pps']
            ))
            self.statistics['events'] = 0
            await asyncio.sleep(refresh)
    
    def create_packet(self):
        raise NotImplementedError


class ABPProtocol(DDLSymmetric):
    def __init__(self, logger=None, is_client=False):
        super().__init__(logger=logger, is_client=is_client)
        self.state = ABPState()
    
    def connection_made(self, transport):
        super().connection_made(transport)
        if (self.is_client):
            self.transport.sendto(self.create_packet()) 
        else:
            self.state.send_bit = 1
    
    def datagram_received(self, data, addr):
        # record link metrics, drop packet if necessary
        if super().datagram_received(data, addr):
            return

        rvalue, rbit = self.unpack_packet(data)
        if (rbit == self.state.expected_bit):
            self.state.send_bit = 1 - self.state.send_bit
            self.state.expected_bit = 1 - self.state.expected_bit
            self.state.send_value = rvalue + 1
            self.logger.debug("RECV rvalue={} rbit={} svalue={} sbit={}"
                    .format(rvalue, rbit, self.state.send_value, self.state.send_bit))
        
        self.transport.sendto(self.create_packet(), addr)
    
    def reset_protocol(self):
        self.state = ABPState()
    
    def create_packet(self):
        #return struct.pack(">I59xc", self.state.send_value, self.state.send_bit.to_bytes(1, 'big'))
        return struct.pack(">Ic", self.state.send_value, self.state.send_bit.to_bytes(1, 'big'))
    
    def unpack_packet(self, data: bytes):
        #rvalue, rbit = struct.unpack(">I59xc", data)
        rvalue, rbit = struct.unpack(">Ic", data)
        rbit = int.from_bytes(rbit, 'big')
        return rvalue, rbit


class BidirectionalProtocol(DDLSymmetric):
    def __init__(self, state_machine: type[StateMachine], logger=None, is_client=False):
        super().__init__(logger, is_client=is_client)
        self.state_machine = state_machine(logger=logger)
        self.drops = 0
    
    def connection_made(self, transport):
        super().connection_made(transport)
        if (self.is_client):
            self.transport.sendto(b"INIT")
    
    def _handle_init_packet(self, data: bytes, addr: tuple[str, int]) -> bool:
        if not (data == b"INIT" or data == b"INIT_ACK"):
            return False
        
        if data == b"INIT":
            self.transport.sendto(b"INIT_ACK", addr)
    
        packet = PacketBuilder() \
            .with_hyperdata(Hyperdata(owner=Identity.ME, protocol=self.state_machine.protocol, state=self.state_machine.state)) \
            .build()
        self.transport.sendto(packet.to_bytes(), addr)
        return True
    
    def _should_drop_packet(self):
        if self.drop_config.mode != DropMode.NONE:
            if self.drop_config.mode == DropMode.ONE:
                self.drops = 2
                self.drop_config.mode = DropMode.NONE
            self.logger.debug("Dropping packet DropMode={}".format(self.drop_config.mode))
            return True
        return False
    
    def set_drop_mode(self, mode: DropMode):
        self.drop_config.mode = mode
    
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> bool:
        if super().datagram_received(data, addr):
            return True
        
        if self.drops > 0:
            self.drops -= 1
            return True

        return self._handle_init_packet(data, addr)
    
    def reset_protocol(self):
        self.state_machine.reset()
    
    def create_packet(self):
        return b"INIT"

class LivenessProtocol(BidirectionalProtocol):
    def __init__(
        self,
        logger=None,
        is_client=False
    ):
        super().__init__(LivenessStateMachine, logger=logger, is_client=is_client)

    def __repr__(self):
        return f"LivenessProtocol(state_machine={self.state_machine}, is_client={self.is_client})"
    
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> bool:
        # record link metrics, drop packet if necessary, handle init packet
        if super().datagram_received(data, addr):
            return True

        hyperdata, content = PacketBuilder.from_bytes(data)
        new_data = self.state_machine.evaluate_transition(hyperdata, content)
        self.transport.sendto(new_data.to_bytes(), addr)
        return True


class AlphabetProtocol(BidirectionalProtocol):
    def __init__(
        self,
        logger=None,
        is_client=False
    ):
        super().__init__(AlphabetStateMachine, logger=logger, is_client=is_client)

    def __repr__(self):
        return f"LivenessProtocol(state_machine={self.state_machine}, is_client={self.is_client})"
    
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.logger.debug(f"[ALPHABET_PROTOCOL] ---- Received packet: {data} ---- ")
        # record link metrics, drop packet if necessary, handle init packet
        if self._handle_init_packet(data, addr):
            return
        super().datagram_received(data, addr)

        hyperdata, content = self._parse_hyperdata(data)
        new_data = self.state_machine.evaluate_transition(hyperdata, content)
        self.logger.debug(f"[DATAGRAM] Received: {hyperdata}. sending: {new_data}")
        self.transport.sendto(new_data.to_bytes(), addr)

    def _handle_init_packet(self, data: bytes, addr: tuple[str, int]) -> bool:
        # First check if this is an init packet at all
        if not data.startswith(b"INIT"):
            return False
        
        try:
            # Try to split and decode just the command portion
            parts = data.split(b" ", 1)
            command = parts[0].decode('utf-8')
            session_id = parts[1].decode('utf-8') if len(parts) > 1 else None
            
            self.logger.debug(f"[ALPHABET_PROTOCOL] Received init packet: command={command} session_id={session_id}")
            
            if command == "INIT":
                self.logger.debug(f"[ALPHABET_PROTOCOL] Sending INIT_ACK")
                self.transport.sendto(b"INIT_ACK " + session_id.encode('utf-8'), addr)
            elif command == "INIT_ACK":
                if not session_id == self.session_id:
                    return True  # Cancel session by dropping packet

            self.logger.debug(f"[ALPHABET_PROTOCOL] Sending initiate packet")
            self.transport.sendto(self.state_machine.initiate(), addr)
            return True
            
        except (ValueError, UnicodeDecodeError) as e:
            self.logger.error(f"Error handling init packet: {e}")
            return False
    
    def connection_made(self, transport):
        self.transport = transport
        if (self.is_client):
            self.session_id = sha256(random.randbytes(16)).hexdigest()
            self.logger.debug(f"[ALPHABET_PROTOCOL] Sending INIT {self.session_id}")
            self.transport.sendto(b"INIT " + self.session_id.encode('utf-8'))
    
    def _parse_hyperdata(self, data: bytes) -> tuple[Hyperdata, Data]:
        _owner, _protocol, _state = struct.unpack(">BHB", data[:4])
        state_type = StateMachineFactory.get_state_type(SMP(_protocol))
        remaining_data = data[4:] if len(data) > 4 else None
        return Hyperdata(owner=Identity(_owner), protocol=SMP(_protocol), state=state_type(_state)), Data(remaining_data)


class TreeProtocol(DDLSymmetric):
    def __init__(
        self,
        read_q: PipeQueue=None,
        write_q: PipeQueue=None,
        signal_q: PipeQueue=None,
        logger=None,
        is_client=False
    ):
        super().__init__(logger, is_client=is_client)
        self.state_machine = TwoPhaseCommitPipeStateMachine(read_q, write_q, logger=logger)
        self.read_q = read_q
        self.write_q = write_q
        self.signal_q = signal_q
        self.drops = 0
        self.timed_out = False
        if (is_client):
            asyncio.create_task(self.check_timeout_client())
        else:
            asyncio.create_task(self.check_timeout_server())

    def __repr__(self):
        return f"LivenessProtocol(state_machine={self.state_machine}, is_client={self.is_client})"
    
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.logger.debug(f"[LINK_PROTOCOL] ---- Received packet: {data} ---- ")
        if self.drops > 0:
            self.drops -= 1
            return
        if self._handle_init_packet(data, addr):
            return
        super().datagram_received(data, addr)

        hyperdata, content = self._parse_hyperdata(data)
        new_data = self.state_machine.evaluate_transition(hyperdata, content)
        self.logger.debug(f"[DATAGRAM] Received: {hyperdata}. sending: {new_data}")
        self.transport.sendto(new_data.to_bytes(), addr)

    def _handle_init_packet(self, data: bytes, addr: tuple[str, int]) -> bool:
        # First check if this is an init packet at all
        if not data.startswith(b"INIT"):
            return False
        
        try:
            # Try to split and decode just the command portion
            parts = data.split(b" ", 1)
            command = parts[0].decode('utf-8')
            session_id = parts[1].decode('utf-8') if len(parts) > 1 else None
            
            self.logger.debug(f"[LINK_PROTOCOL] Received init packet: command={command} session_id={session_id}")
            
            if command == "INIT":
                self.logger.debug(f"[LINK_PROTOCOL] Sending INIT_ACK")
                self.transport.sendto(b"INIT_ACK " + session_id.encode('utf-8'), addr)
            elif command == "INIT_ACK":
                if not session_id == self.session_id:
                    return True  # Cancel session by dropping packet

            self.logger.debug(f"[LINK_PROTOCOL] Sending initiate packet")
            self.transport.sendto(self.state_machine.initiate(), addr)
            return True
            
        except (ValueError, UnicodeDecodeError) as e:
            self.logger.error(f"Error handling init packet: {e}")
            return False
    
    def connection_made(self, transport):
        self.transport = transport
        if (self.is_client):
            self.session_id = sha256(random.randbytes(16)).hexdigest()
            self.logger.debug(f"[LINK_PROTOCOL] Sending INIT {self.session_id}")
            self.transport.sendto(b"INIT " + self.session_id.encode('utf-8'))
    
    def _parse_hyperdata(self, data: bytes) -> tuple[Hyperdata, Data]:
        _owner, _protocol, _state = struct.unpack(">BHB", data[:4])
        state_type = StateMachineFactory.get_state_type(SMP(_protocol))
        remaining_data = data[4:] if len(data) > 4 else None
        return Hyperdata(owner=Identity(_owner), protocol=SMP(_protocol), state=state_type(_state)), Data(remaining_data)
    
    def _should_drop_packet(self):
        if self.drop_config.mode != DropMode.NONE:
            if self.drop_config.mode == DropMode.ONE:
                self.drops = 2
                self.drop_config.mode = DropMode.NONE
            self.logger.debug("Dropping packet DropMode={}".format(self.drop_config.mode))
            return True
        return False
    
    def set_drop_mode(self, mode: DropMode):
        self.drop_config.mode = mode
    
    def reset_protocol(self):
        self.state_machine.reset()
    
    def create_packet(self):
        self.session_id = sha256(random.randbytes(16)).hexdigest()
        self.logger.debug(f"[LINK_PROTOCOL] Sending INIT {self.session_id}")
        return b"INIT " + self.session_id.encode('utf-8')
    
    async def check_timeout_client(self, timeout=0.1):
        self.logger.info("Started timeout routine")
        while not self.disconnected_future.done():
            elapsed_time = time.time() - self._last_recv_time
            if elapsed_time > timeout:
                self.logger.info("Timeout'd")
                if self.transport and self.is_client:
                    self.transport.close()
                else:
                    self.signal_q.put(Data(content=b"DISCONNECTED"))
            
            await asyncio.sleep(timeout)
    
    async def check_timeout_server(self, timeout=0.1):
        self.logger.info("Started timeout routine")
        while not self.disconnected_future.done():
            elapsed_time = time.time() - self._last_recv_time
            if elapsed_time > 5:
                self.logger.info("Server shutting down")
                self.transport.close()
                return

            if elapsed_time > timeout:
                if not self.timed_out:
                    self.logger.info("Server timeout'd")
                    self.signal_q.put(Data(content=b"DISCONNECTED"))
                    self.timed_out = True
            else:
                if self.timed_out:
                    self.logger.info("Server reconnected")
                    self.signal_q.put(Data(content=b"CONNECTED")) 
                    self.timed_out = False
            
            await asyncio.sleep(timeout)
        
    

