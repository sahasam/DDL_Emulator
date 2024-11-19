from scapy.layers.l2 import Ether
from scapy.packet import bind_layers
from scapy.sendrecv import sendp

from protocol import AlternatingBitProtocol, ABPState

import time


def sender_main(args):
    state = ABPState()
    bind_layers(Ether, AlternatingBitProtocol, type=0x88B5)

    while not state.shutdown.is_set():
        pkt = Ether(dst="ff:ff:ff:ff:ff:ff", type=0x88B5)/AlternatingBitProtocol(
            value=100,
            is_ack=0,
            bit=0
        )
        sendp(pkt, iface=args.interface)
        print(f"Sent data: value={state.send_value} bit={state.send_bit}")
        time.sleep(0.1)