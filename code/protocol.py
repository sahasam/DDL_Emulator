from threading import Event
from scapy.packet import Packet
from scapy.fields import LongField, StrFixedLenField, BitField

class ABPState:
    def __init__(self):
        self.send_bit = 0
        self.send_value = 0
        self.expected_bit = 0
        self.expected_value = 0
        self.shutdown = Event()

class AlternatingBitProtocol(Packet):
    name = "AlternatingBitProtocol"
    fields_desc = [
        LongField("value", 0),
        StrFixedLenField("padding", b'\x00'*55, length=55),
        BitField("is_ack", 0, 7),
        BitField("bit", 0, 1)
    ]