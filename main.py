from ddl.port import ThreadedUDPPort
from ddl.sim import link_sim, bridge_sim

from signal import pause
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Alternating Bit Protocol Implementation')
    parser.add_argument('--mode', choices=['a', 'b'], default='a', help='Symmetry Break (a or b)')
    parser.add_argument('--interface', choices=['bridge0', 'local', 'localsingle'], default='local', help='Network interface to use')
    parser.add_argument('--debug', action='store_true', help='Flag to enable local process testing')
    
    args = parser.parse_args()

    if args.interface == "local":
        link_sim()

    elif args.interface == "bridge0":
        # get bridge0 interface ip
        # Mac-Mini bridge0 ip: 169.254.103.201 (Manually set)
        dst = '169.254.103.201' 
        bridge_sim(is_client=(args.mode == "b"), addr=(dst, 55555))
