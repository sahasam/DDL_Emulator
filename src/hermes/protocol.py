from abc import ABC
import asyncio
import struct
import time
from enum import Enum

from hermes.machines.data import Hyperdata, PacketBuilder
from hermes.machines.statemachine import AlphabetStateMachine, LivenessStateMachine, StateMachine
from hermes.machines.common import SMP, Identity


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
        if (is_client):
            asyncio.create_task(self.check_timeout())
    
    def set_drop_mode(self, mode):
        self.drop_config.mode = mode
    
    def should_drop_packet(self):
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
            "status": "connected" if not self.disconnected_future.done() else "disconnected",
            "statistics": self.statistics
        }
    
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self.should_drop_packet():
            return
        
        self.statistics['events'] += 1
        self._last_recv_time = time.time()
    
    async def update_statistics(self, refresh=0.1):
        prev_stats_update_time = time.time()
        while not self.disconnected_future.done():
            elapsed_time = time.time() - prev_stats_update_time
            if elapsed_time == 0:
                continue

            prev_stats_update_time = time.time()
            if self.statistics['events'] > 0:
                self.statistics['round_trip_latency'] = (elapsed_time / self.statistics['events'])
                self.statistics['pps'] = (self.statistics['events'] / elapsed_time)
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
        super().datagram_received(data, addr)

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
        self.state_machine = state_machine()
    
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
    
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        super().datagram_received(data, addr)
        self._handle_init_packet(data, addr)
    
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
    
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        # record link metrics, drop packet if necessary, handle init packet
        super().datagram_received(data, addr)

        if self._handle_init_packet(data, addr):
            return

        hyperdata, content = PacketBuilder.from_bytes(data)
        new_data = self.state_machine.evaluate_transition(hyperdata, content)
        self.transport.sendto(new_data.to_bytes(), addr)

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
        # record link metrics, drop packet if necessary, handle init packet
        super().datagram_received(data, addr)

        if self._handle_init_packet(data, addr):
            return

        hyperdata, content = Hyperdata.from_bytes(data, self.state_machine.states_type)
        new_hyperdata = self.state_machine.evaluate_transition(hyperdata, content)
        self.transport.sendto(new_hyperdata.to_bytes(), addr)

    def _handle_init_packet(self, data: bytes, addr: tuple[str, int]) -> bool:
        if not (data == b"INIT" or data == b"INIT_ACK"):
            return False
        
        if data == b"INIT":
            self.transport.sendto(b"INIT_ACK", addr)
    
        packet = PacketBuilder() \
            .with_hyperdata(Hyperdata(owner=Identity.ME, protocol=SMP.LIVENESS, state=LivenessStateMachine.S.S1)) \
            .build()
        self.transport.sendto(packet.to_bytes(), addr)
        return True
