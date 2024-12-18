"""
sim.py

Right now: spin up the logs, loops, and prompting to run the single-link simulation

Eventual Goal: Given an arbitrary description of a network topology with virtual links, real links, and unconnected links,
create all threads, event loops, and logs for simulation
"""
from ddl.port import ThreadedUDPPort

import asyncio
import time
import logging

def setup_logger(name, log_file, level=logging.INFO):
    """Set up a logger for a specific thread."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # File handler for the specific log file
    handler = logging.FileHandler(log_file, mode="w+")
    formatter = logging.Formatter('%(asctime)s - %(threadName)s - %(message)s')
    handler.setFormatter(formatter)
    
    # Add the handler to the logger
    logger.addHandler(handler)
    return logger

def print_menu(single_port=False, is_client=False):
    print("\nAvailable commands:")
    if single_port:
        role = "client" if is_client else "server"
        print(f"1. Drop next packet on {role}")
    else:
        print("1. Drop next packet on server")
        print("2. Drop next packet on client")
    print("q. Quit")
    print("\nEnter command: ", end='', flush=True)

def handle_user_input(thread1, thread2=None):
    single_port = thread2 is None
    is_client = thread1.is_client if single_port else False
    
    while True:
        print_menu(single_port, is_client)
        try:
            cmd = input().strip().lower()
            if cmd == 'q':
                raise KeyboardInterrupt
            elif cmd == '1':
                thread1.drop_one_packet()
                if single_port:
                    role = "client" if is_client else "server"
                    print(f"{role.capitalize()} will drop next packet")
                else:
                    print("Server will drop next packet")
            elif cmd == '2' and not single_port:
                thread2.drop_one_packet()
                print("Client will drop next packet")
            else:
                print("Invalid command")
        except EOFError:
            break

def sim_from_config(config):
    threads = []
    loops = []
    for port in config['ports']:
        loop = asyncio.new_event_loop()
        logger = setup_logger(port['name'], f"logs/ports.log")
        
        threads.append(ThreadedUDPPort(loop, logger, port['type'] == 'client', (port['ip'], port['port'])))
        loops.append(loop)
    
    print("*"*45)
    for thread in threads:
        print(thread.get_pretty_link_details())
    print("*"*45)


def link_sim():
    try:
        loop1 = asyncio.new_event_loop()
        loop2 = asyncio.new_event_loop()
        logger = setup_logger("LinkSim", "logs/sim.log")

        thread1 = ThreadedUDPPort(loop1, logger, False, ('127.0.0.1', 55555), name="Server")
        thread2 = ThreadedUDPPort(loop2, logger, True, ('127.0.0.1', 55555), name="Client")

        print("*"*44)
        print(thread1.get_pretty_link_details())
        print(thread2.get_pretty_link_details())
        print("*"*44)

        thread1.start()
        time.sleep(0.1)
        thread2.start()

        handle_user_input(thread1, thread2)

    except KeyboardInterrupt:
        print("\nGracefully shutting down...")

        for loop in [loop1, loop2]:
            loop.call_soon_threadsafe(loop.stop)
        
        thread1.join()
        thread2.join()

def bridge_sim(is_client=False, addr=('169.254.103.201', 55555)):
    try:
        loop = asyncio.new_event_loop()
        logger = setup_logger("BridgeSim", "logs/sim.log")

        thread = ThreadedUDPPort(loop, logger, is_client, addr, name="Bridge")
        thread.start()

        handle_user_input(thread)
    except KeyboardInterrupt:
        print("\nGracefully shutting down...")

        loop.call_soon_threadsafe(loop.stop)
        
        thread.join()