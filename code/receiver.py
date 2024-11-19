from scapy.layers.l2 import Ether
from scapy.packet import bind_layers
from scapy.sendrecv import sniff

from protocol import AlternatingBitProtocol, ABPState

def packet_handler(state, pkt):
    abp = pkt[AlternatingBitProtocol]
    print(f"Received data: seq={abp.value}, bit={abp.bit}")

def receiver_main(args):
    state = ABPState()
    bind_layers(Ether, AlternatingBitProtocol, type=0x88B5)

    try:
        sniff(
            lfilter=lambda p: AlternatingBitProtocol in p and not p[AlternatingBitProtocol].is_ack,
            prn=lambda p: packet_handler(state, p),
            iface=args.interface
        )
    except KeyboardInterrupt:
        print("\nStopping receiver...")