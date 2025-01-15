from unittest.mock import patch
import pytest
import asyncio
import logging

from hermes.port import ThreadedUDPPort, DropMode
from hermes.protocol import ABPProtocol, DropConfig

class MockTransport:
    def __init__(self):
        self.packets = []
        
    def sendto(self, data, addr=None):
        self.packets.append(data)
        
    def close(self):
        pass

class MockProtocol(ABPProtocol):
    def __init__(self, *args, **kwargs):
        self.received_packets = []
        # Skip the parent class __init__ to avoid creating async tasks
        self.logger = kwargs.get('logger')
        self.is_client = kwargs.get('is_client', False)
        self.drop_config = DropConfig()
        # Add statistics attribute
        self.statistics = {
            'events': 0,
            'packets_sent': 0,
            'packets_received': 0
        }
        
    def datagram_received(self, data, addr):
        self.received_packets.append(data)
        
    def drop_one_packet(self):
        self.drop_config.mode = DropMode.ONE

@pytest.fixture(scope="function")
def event_loop_policy():
    """Create an instance of the default event loop for each test case."""
    policy = asyncio.DefaultEventLoopPolicy()
    return policy

@pytest.fixture
def logger():
    logger = logging.getLogger('test_logger')
    logger.setLevel(logging.DEBUG)
    return logger

@pytest.fixture(scope="function")
def udp_port(event_loop, logger):
    """Create a UDP port fixture with async context."""
    port = ThreadedUDPPort(
        loop=event_loop,
        logger=logger,
        is_client=True,
        addr=('127.0.0.1', 55555),
        name='test_port'
    )
    port.transport = MockTransport()
    return port

def test_port_initialization(udp_port):
    """Test that port initializes with correct attributes"""
    assert udp_port.addr == ('127.0.0.1', 55555)
    assert udp_port.name == 'test_port'
    assert udp_port.is_client
    assert udp_port.daemon

@pytest.mark.asyncio
async def test_drop_one_packet(udp_port, logger):
    """Test that drop_one_packet sets correct drop mode"""
    udp_port.protocol_instance = MockProtocol(logger=logger)
    udp_port.drop_one_packet()
    
    # Give the event loop a chance to process the callback
    await asyncio.sleep(0)
    
    assert udp_port.protocol_instance.drop_config.mode == DropMode.ONE

def test_set_disconnected(udp_port, logger):
    """Test set_disconnected functionality"""
    udp_port.protocol_instance = MockProtocol(logger=logger)
    
    # Test disconnect
    udp_port.set_disconnected(True)
    assert udp_port.protocol_instance.drop_config.mode == DropMode.ALL
    
    # Test reconnect
    udp_port.set_disconnected(False)
    assert udp_port.protocol_instance.drop_config.mode == DropMode.NONE

def test_get_snapshot(udp_port, logger):
    """Test snapshot generation"""
    udp_port.protocol_instance = MockProtocol(logger=logger)
    snapshot = udp_port.get_snapshot()
    
    expected_keys = {'name', 'ip', 'port', 'type', 'link'}
    assert set(snapshot.keys()) == expected_keys
    assert snapshot['name'] == 'test_port'
    assert snapshot['ip'] == '127.0.0.1'
    assert snapshot['port'] == 55555
    assert snapshot['type'] == 'client'

@pytest.mark.asyncio
async def test_run_link(udp_port):
    loop = asyncio.get_running_loop()
    """Test run_link creates endpoint and handles disconnection"""
    # Patch the create_datagram_endpoint method on the event loop instance
    with patch.object(loop, 'create_datagram_endpoint') as mock_create_endpoint:
        # Setup mock endpoint
        mock_create_endpoint.return_value = (udp_port.transport, MockProtocol(logger=udp_port.logger))
        
        # Create a future that we'll cancel to simulate disconnection
        disconnect_future = loop.create_task(udp_port.run_link())
        
        # Let it run briefly
        await asyncio.sleep(0.1)
        
        # Cancel the future
        disconnect_future.cancel()
        
        try:
            await disconnect_future
        except asyncio.CancelledError:
            pass
        
        # Verify endpoint was created
        mock_create_endpoint.assert_called_once()
