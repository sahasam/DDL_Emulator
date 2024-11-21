from threading import Event
import asyncio
import struct
import time

class ABPState:
    def __init__(self):
        self.send_bit = 0
        self.send_value = 0
        self.expected_bit = 0

class ABPProtocol:
    def __init__(self, loop, is_client=False):
        print("constructing")
        self.state = ABPState()
        self.transport = None
        self.is_client = is_client
        self.client_disconnected = asyncio.Future()

        self.event_count = 0
        self.update_pps_task = asyncio.create_task(self.update_pps())

        self.last_received_packet_time = time.time()
        if (is_client):
            asyncio.create_task(self.check_timeout())

    
    def datagram_received(self, data, addr):
        rvalue, rbit = self.unpack_packet(data)

        if (rbit == self.state.expected_bit):
            self.last_received_packet_time = time.time()
            self.event_count += 1

            self.state.send_bit = 1 - self.state.send_bit
            self.state.expected_bit = 1 - self.state.expected_bit
            self.state.send_value = rvalue + 1
        
        self.transport.sendto(self.create_packet(), addr)
    
    def create_packet(self):
        return struct.pack(">I59xc", self.state.send_value, self.state.send_bit.to_bytes(1, 'big'))
    
    def unpack_packet(self, data: bytes):
        rvalue, rbit = struct.unpack(">I59xc", data)
        rbit = int.from_bytes(rbit, 'big')
        return rvalue, rbit

    def error_received(self, exc):
        self.client_disconnected.set_result(True)
        print('Error received:', exc)

    def connection_lost(self, exc):
        self.client_disconnected.set_result(True)
        print(f"Connection closed {exc}")

    def connection_made(self, transport):
        print("Connection made")
        self.transport = transport
        if (self.is_client):
            self.transport.sendto(self.create_packet()) 
        else:
            self.state.send_bit = 1
    
    async def update_pps(self):
        last_report_time = time.time()
        while not self.client_disconnected.done():
            # Calculate elapsed time and PPS
            elapsed_time = time.time() - last_report_time
            if elapsed_time > 0:
                last_report_time = time.time()
                pps = self.event_count / elapsed_time
                self.event_count = 0

                # Clear the terminal line and print PPS
                print(f"Events per second: {pps:.2f}")
            await asyncio.sleep(1)
    
    async def check_timeout(self):
        while not self.client_disconnected.done():
            elapsed_time = time.time() - self.last_received_packet_time
            if elapsed_time > 1:
                print("closing...")
                if self.transport:
                    self.transport.close()
            
            await asyncio.sleep(1)