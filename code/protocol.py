from threading import Event
import asyncio
import struct

class ABPState:
    def __init__(self):
        self.send_bit = 0
        self.send_value = 0
        self.expected_bit = 0
        self.shutdown = Event()

class ABPProtocol:
    def __init__(self, is_alice=False):
        self.state = ABPState()
        self.on_con_lost = asyncio.Future()
        self.transport = None
        self.is_alice = is_alice
    
    def datagram_received(self, data, addr):
        rvalue, rbit = self.unpack_packet(data)

        if (rbit == self.state.expected_bit):
            self.state.send_bit = 1 - self.state.send_bit
            self.state.expected_bit = 1 - self.state.expected_bit
            self.state.send_value = rvalue + 1
        
        self.transport.sendto(self.create_packet(), addr)
    
    def create_packet(self):
        print(f"Sending: rvalue={self.state.send_value}, rbit={self.state.send_bit}")
        return struct.pack(">I59xc", self.state.send_value, self.state.send_bit.to_bytes(1, 'big'))
    
    def unpack_packet(self, data: bytes):
        rvalue, rbit = struct.unpack(">I59xc", data)
        rbit = int.from_bytes(rbit, 'big')
        print(f"Received: rvalue={rvalue}, rbit={rbit}, expected_bit={self.state.expected_bit}")
        return rvalue, rbit

    def error_received(self, exc):
        print('Error received:', exc)

    def connection_lost(self, exc):
        print("Connection closed")
        self.on_con_lost.set_result(True)

    def connection_made(self, transport):
        self.transport = transport
        if (self.is_alice):
            self.transport.sendto(self.create_packet()) 
        else:
            self.state.send_bit = 1