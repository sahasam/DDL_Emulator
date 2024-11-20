from udp_client import main as c_main
from udp_server import main as s_main
import argparse
import psutil
import asyncio
import threading
import signal
import socket
import time

def get_ip_address(interface_name):
    try:
        # Get the network interfaces and their addresses
        addrs = psutil.net_if_addrs()
        
        # Check if the specified interface exists
        if interface_name not in addrs:
            raise ValueError(f"Interface '{interface_name}' not found.")
        
        # Get the addresses for the interface
        for addr in addrs[interface_name]:
            if addr.family == socket.AF_INET:  # IPv4 address
                return addr.address
        
        # If no IPv4 address is found
        raise ValueError(f"No IPv4 address found for interface '{interface_name}'.")
    
    except Exception as e:
        return str(e)

def run_async_in_thread(loop, coro):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(coro)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Alternating Bit Protocol Implementation')
    parser.add_argument('--mode', choices=['a', 'b'], default='a', help='Symmetry Break (a or b)')
    parser.add_argument('--interface', choices=['bridge0', 'local'], default='local', help='Network interface to use')
    parser.add_argument('--debug', action='store_true', help='Flag to enable local process testing')
    
    args = parser.parse_args()

    if args.interface == "local":
        try:
            loop1 = asyncio.new_event_loop()
            loop2 = asyncio.new_event_loop()
            
            thread1 = threading.Thread(target=run_async_in_thread, args=(loop1, s_main(args.interface, local_addr=('127.0.0.1', 55555))))
            thread2 = threading.Thread(target=run_async_in_thread, args=(loop2, c_main(args.interface, remote_addr=('127.0.0.1', 55555))))

            thread1.start()
            time.sleep(0.1) # make sure server starts
            thread2.start()

            signal.pause()
        except KeyboardInterrupt:
            print("\nGracefully shutting down...")

            for loop in [loop1, loop2]:
                loop.call_soon_threadsafe(loop.stop)
            
            thread1.join()
            thread2.join()

    elif args.interface == "bridge0":
        # get bridge0 interface ip
        dst = get_ip_address("bridge0")
        loop = asyncio.get_event_loop()
        if args.mode == "a":
            loop.run_until_complete(c_main(args.interface, remote_addr=(dst, 55555)))
        elif args.mode == "b":
            loop.run_until_complete(s_main(args.interface, local_addr=(dst, 55555)))
