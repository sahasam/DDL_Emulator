from threading import Event
import asyncio
import struct
import time

class ABPState:
    def __init__(self):
        self.send_bit = 0
        self.send_value = 0
        self.expected_bit = 0
        self.shutdown = Event()

class ABPProtocol:
    def __init__(self, loop, is_client=False):
        self.state = ABPState()
        self.on_con_lost = asyncio.Future()
        self.transport = None
        self.is_alice = is_client

        self.event_count = 0
        self.update_pps_task = asyncio.run_coroutine_threadsafe(self.update_pps(), loop)

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
    
    async def update_pps(self):
        last_report_time = time.time()
        while True:
            # Calculate elapsed time and PPS
            elapsed_time = time.time() - last_report_time
            if elapsed_time > 0:
                last_report_time = time.time()
                pps = self.event_count / elapsed_time
                self.event_count = 0

                # Clear the terminal line and print PPS
                print(f"\rEvents per second: {pps:.2f}", end="")
            await asyncio.sleep(1)
    
    async def check_timeout(self):
        while True:
            elapsed_time = time.time() - self.last_received_packet_time
            if elapsed_time > 1:
                print(f"\nConnection timed out. Attempting to reconnect... (Attempt {self.reconnect_attempts + 1})")
                await self.reconnect()
            await asyncio.sleep(1)  # Check every second
    
    async def reconnect(self):
        while True:
            self.reconnect_attempts += 1
            try:
                # Example reconnection logic
                if self.transport:
                    self.transport.close()  # Close existing transport
                # Recreate transport here (replace with actual reconnect logic)
                loop = asyncio.get_event_loop()
                self.transport, _ = await loop.create_datagram_endpoint(
                    lambda: self, remote_addr=('localhost', 12345)
                )
                print("Reconnected successfully.")
            except Exception as e:
                print(f"Reconnect failed: {e}")
                await asyncio.sleep(1)  # Exponential backoff