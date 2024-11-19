import socket
from protocol import ABPPacket

class ThunderboltLink:
    def __init__(self, iface="bridge0"):
        self.iface = iface
        # Create raw socket bound to the bridge interface
        self.sock = socket.socket(socket.AF_NDRV, socket.SOCK_RAW, 0)
        try:
            self.sock.bind(str.encode(self.iface))
        except socket.error as e:
            print(f"Error binding to interface: {e}")
            raise
    
    def send_packet(self, pkt: ABPPacket):
        """
        Send a custom packet with specified flags
        """
        self.sock.send(pkt.to_bytes())
    
