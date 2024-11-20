from sender import sender_main
from receiver import receiver_main

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Alternating Bit Protocol Implementation')
    parser.add_argument('--mode', choices=['s', 'r'], help='Operation mode')
    parser.add_argument('--interface', default='bridge0', help='Network interface to use')
    parser.add_argument('--onlocal', action='store_true', help='Flag to enable local process testing')
    
    args = parser.parse_args()

    if args.mode == "send":
        sender_main(interface=args.interface, onlocal=args.onlocal)
    else:
        receiver_main(interface=args.interface, onlocal=args.onlocal)
