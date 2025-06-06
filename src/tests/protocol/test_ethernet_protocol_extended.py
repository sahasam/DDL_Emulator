import logging
import time
from typing import Optional

from hermes.faults.FaultInjector import ThreadSafeFaultInjector
from hermes.model.ports import PortConfig, PortIO
from hermes.port.Port import UDPPort
from hermes.port.protocol import EthernetProtocolExtended
from hermes.sim.PipeQueue import PipeQueue
from hermes.model.types import IPV6_ADDR

_pipe_queues = []
_ports = []

class TrackingEthernetProtocolExtended(EthernetProtocolExtended):
    def __init__(self,
                 io: PortIO,
                 name: str,
                 sending_addr: IPV6_ADDR,
                 is_client: bool,
                 faultInjector: Optional[ThreadSafeFaultInjector]=None):
        super().__init__(io, name, sending_addr, is_client, faultInjector)
        self.received_packets = []
        self.sent_packets = []

    def datagram_received(self, data, addr):
        self.received_packets.append(data)
        super().datagram_received(data, addr)

    def connection_made(self, transport):
        super().connection_made(transport)

        orig_sendto = transport.sendto

        def wrapped_sendto(data, addr=None):
            self.sent_packets.append(data)
            return orig_sendto(data, addr)

        transport.sendto = wrapped_sendto

        

def getPorts(portName1: str, portName2: str):
    """Test that two ports are able to establish a stable connection"""
    signal_q1 = PipeQueue()
    read_q1 = PipeQueue()
    write_q1 = PipeQueue()
    signal_q2 = PipeQueue()
    read_q2 = PipeQueue()
    write_q2 = PipeQueue()
    portConfig1 = PortConfig(
        logger=logging.getLogger(f"Port.{portName1}"),
        interface="127.0.0.1:45454:45455",
        port_id=portName1,
        name=portName1,
    )
    portConfig2 = PortConfig(
        logger=logging.getLogger(f"Port.{portName2}"),
        interface="127.0.0.1:45455:45454",
        port_id=portName2,
        name=portName2,
    )
    port1 = UDPPort(
        config=portConfig1,
        io=PortIO(
            read_q=read_q1,
            write_q=write_q1,
            signal_q=signal_q1,
        ),
        faultInjector=ThreadSafeFaultInjector(),
        protocolClass=TrackingEthernetProtocolExtended
    )
    port2 = UDPPort(
        config=portConfig2,
        io=PortIO(
            read_q=read_q2,
            write_q=write_q2,
            signal_q=signal_q2,
        ),  
        faultInjector=ThreadSafeFaultInjector(),
        protocolClass=TrackingEthernetProtocolExtended
    )

    _pipe_queues.extend([signal_q1, read_q1, write_q1, signal_q2, read_q2, write_q2])
    _ports.extend([port1, port2])
    return port1, port2

def cleanup():
    for port in _ports:
        port.stop_event.set()
        port._loop.stop()

    for port in _ports:
        port.join(timeout=0.5)

    for pipe in _pipe_queues:
        pipe.close()

def test_connection():
    """Test that two ports are able to establish a stable connection"""
    port1, port2 = getPorts("port1", "port2")
    port1.start()
    port2.start()

    # Wait for the ports to connect
    time.sleep(1)

    assert port2.io.read_q.get() == b"HEARTBEAT"
    assert port1.io.read_q.get() == b"HEARTBEAT"

    print()
    print("port1 send:", port1.protocol_instance.sent_packets)
    print("port1 recv:", port1.protocol_instance.received_packets)
    print("port1 send:", port2.protocol_instance.sent_packets)
    print("port2 recv:", port2.protocol_instance.received_packets)

    cleanup()


def test_send_recv_on_connection():
    """Test that two ports are able to establish a stable connection"""
    port1, port2 = getPorts("port1", "port2")
    port1.start()
    port2.start()

    # Wait for the ports to connect
    time.sleep(1)

    port1.io.write_q.put(b"PORT1_SENDING")
    port2.io.write_q.put(b"PORT2_SENDING")
    time.sleep(0.2)

    assert b"PORT2_SENDING" in port1.protocol_instance.received_packets
    assert b"PORT1_SENDING" in port2.protocol_instance.received_packets

    cleanup()

    print()
    print("port1 send:", port1.protocol_instance.sent_packets)
    print("port1 recv:", port1.protocol_instance.received_packets)
    print("port1 send:", port2.protocol_instance.sent_packets)
    print("port2 recv:", port2.protocol_instance.received_packets)

