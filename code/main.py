from sender import sender_main
from receiver import receiver_main

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Alternating Bit Protocol Implementation')
    parser.add_argument('--mode', choices=['send', 'receive'], help='Operation mode')
    parser.add_argument('--interface', default='bridge0', help='Network interface to use')
    
    args = parser.parse_args()
    if args.mode == "send":
        sender_main(args)
    else:
        receiver_main(args)
