from ddl.port import ThreadedPort

from signal import pause
import argparse
import asyncio
import time
import logging

def setup_logger(name, log_file, level=logging.INFO):
    """Set up a logger for a specific thread."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # File handler for the specific log file
    handler = logging.FileHandler(log_file, mode="w")
    formatter = logging.Formatter('%(asctime)s - %(threadName)s - %(message)s')
    handler.setFormatter(formatter)
    
    # Add the handler to the logger
    logger.addHandler(handler)
    return logger

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Alternating Bit Protocol Implementation')
    parser.add_argument('--mode', choices=['a', 'b'], default='a', help='Symmetry Break (a or b)')
    parser.add_argument('--interface', choices=['bridge0', 'local', 'localsingle'], default='local', help='Network interface to use')
    parser.add_argument('--debug', action='store_true', help='Flag to enable local process testing')
    
    args = parser.parse_args()

    if args.interface == "local":
        try:
            loop1 = asyncio.new_event_loop()
            loop2 = asyncio.new_event_loop()
            logger1 = setup_logger("ServerThread", "logs/server_thread.log")
            logger2 = setup_logger("ClientThread", "logs/client_thread.log")

            thread1 = ThreadedPort(loop1, logger1, False, ('127.0.0.1', 55555))
            thread2 = ThreadedPort(loop2, logger2, True, ('127.0.0.1', 55555))

            thread1.start()
            time.sleep(0.1)
            thread2.start()

            pause()
        except KeyboardInterrupt:
            print("\nGracefully shutting down...")

            for loop in [loop1, loop2]:
                loop.call_soon_threadsafe(loop.stop)
            
            thread1.join()
            thread2.join()

    elif args.interface == "bridge0":
        # get bridge0 interface ip
        # Mac-Mini bridge0 ip: 169.254.103.201 (Manually set)
        try:
            dst = '169.254.103.201' 
            loop = asyncio.get_event_loop()
            if args.mode == "a":
                logger = setup_logger("ClientThread", "logs/client_thread.log")
                t = ThreadedPort(loop, logger, True, (dst, 55555))
                t.start()
            elif args.mode == "b":
                logger = setup_logger("ServerThread", "logs/server_thread.log")
                t = ThreadedPort(loop, logger, True, (dst, 55555))
                t.start()

            pause()
        except KeyboardInterrupt:
            print("\nGracefully shutting down...")
            loop.call_soon_threadsafe(loop.stop)
            t.join()
