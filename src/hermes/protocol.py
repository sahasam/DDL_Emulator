import asyncio
import struct
import time
from enum import Enum

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
        self.logger.info("Started Connection Instance. is_client={}".format(is_client))
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
        if (self.is_client):
            self.transport.sendto(self.create_packet()) 
        else:
            self.state.send_bit = 1

    def error_received(self, exc):
        self.disconnected_future.set_result(True)
        self.logger.error('Error received: {}'.format(exc))

    async def check_timeout(self, timeout=0.1):
        self.logger.info("Started timeout routine")
        while not self.disconnected_future.done():
            elapsed_time = time.time() - self._last_recv_time
            if elapsed_time > timeout:
                self.logger.info("Timeout'd")
                if self.transport:
                    self.reset_protocol()
                    self.transport.sendto(self.create_packet())
            
            await asyncio.sleep(timeout)

    async def update_statistics(self, refresh=0.1):
        prev_stats_update_time = time.time()
        while not self.disconnected_future.done():
            elapsed_time = time.time() - prev_stats_update_time
            if elapsed_time == 0:
                continue

            prev_stats_update_time = time.time()
            if self.statistics['events'] > 0:
                self.statistics['round_trip_latency'] = (elapsed_time / self.statistics['events'])
            else:
                self.statistics['round_trip_latency'] = float('inf')
            self.statistics['pps'] = (self.statistics['events'] / elapsed_time)

            self.logger.info("STATS events={} round_trip_latency_us={:.2f} pps={:.2f}".format(
                self.statistics['events'],
                self.statistics['round_trip_latency']*1e6,
                self.statistics['pps']
            ))
            self.statistics['events'] = 0
            await asyncio.sleep(refresh)


class ABPProtocol(DDLSymmetric):
    def __init__(self, logger=None, is_client=False, iface_name=None):
        super().__init__(logger=logger, is_client=is_client)
        self.state = ABPState()
    
    def datagram_received(self, data, addr):
        if self.should_drop_packet():
            return

        rvalue, rbit = self.unpack_packet(data)
        if (rbit == self.state.expected_bit):
            self.statistics['events'] += 1
            self._last_recv_time = time.time()

            self.state.send_bit = 1 - self.state.send_bit
            self.state.expected_bit = 1 - self.state.expected_bit
            self.state.send_value = rvalue + 1
            self.logger.debug("RECV rvalue={} rbit={} svalue={} sbit={}"
                    .format(rvalue, rbit, self.state.send_value, self.state.send_bit))
        
        self.transport.sendto(self.create_packet(), addr)
    
    def reset_protocol(self):
        self.state = ABPState()
    
    def create_packet(self):
        return struct.pack(">I59xc", self.state.send_value, self.state.send_bit.to_bytes(1, 'big'))
    
    def unpack_packet(self, data: bytes):
        rvalue, rbit = struct.unpack(">I59xc", data)
        rbit = int.from_bytes(rbit, 'big')
        return rvalue, rbit

