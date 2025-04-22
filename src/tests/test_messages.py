import pytest
from hermes.model.messages import RTPPacket, TreeBuild, TreeBuildAck

def test_tree_build_serialization():
    """Test that TreeBuild messages serialize and deserialize correctly"""
    # Create a test message
    tb = TreeBuild(
        tree_id="test_tree",
        sending_node_id="node1",
        hops=3,
        path=["node1:port1", "node2:port2"]
    )
    
    # Convert to bytes
    data = tb.to_bytes()
    
    # Convert back from bytes
    tb_decoded = TreeBuild.from_bytes(data)
    
    # Verify all fields match
    assert tb_decoded.tree_id == "test_tree"
    assert tb_decoded.sending_node_id == "node1" 
    assert tb_decoded.hops == 3
    assert tb_decoded.path == ["node1:port1", "node2:port2"]

def test_tree_build_empty_path():
    """Test TreeBuild serialization with empty path"""
    tb = TreeBuild(
        tree_id="test_tree",
        sending_node_id="node1",
        hops=0,
        path=[]
    )
    
    data = tb.to_bytes()
    tb_decoded = TreeBuild.from_bytes(data)
    
    assert tb_decoded.path == []
    assert tb_decoded.hops == 0

def test_tree_build_invalid_format():
    """Test that invalid TreeBuild messages raise ValueError"""
    invalid_data = b"TREE_BUILD missing_fields"
    
    with pytest.raises(ValueError):
        TreeBuild.from_bytes(invalid_data)

def test_tree_build_ack_serialization():
    """Test that TreeBuildAck messages serialize and deserialize correctly"""
    # Create test message
    tba = TreeBuildAck(
        tree_id="test_tree",
        hops=2,
        path=["node1:port1", "node2:port2"]
    )
    
    # Convert to bytes
    data = tba.to_bytes()
    
    # Convert back from bytes  
    tba_decoded = TreeBuildAck.from_bytes(data)
    
    # Verify fields match
    assert tba_decoded.tree_id == "test_tree"
    assert tba_decoded.hops == 2
    assert tba_decoded.path == ["node1:port1", "node2:port2"]

def test_tree_build_ack_empty_path():
    """Test TreeBuildAck serialization with empty path"""
    tba = TreeBuildAck(
        tree_id="test_tree", 
        hops=0,
        path=[]
    )
    
    data = tba.to_bytes()
    tba_decoded = TreeBuildAck.from_bytes(data)
    
    assert tba_decoded.path == []
    assert tba_decoded.hops == 0

def test_tree_build_ack_invalid_format():
    """Test that invalid TreeBuildAck messages raise ValueError"""
    invalid_data = b"TREE_BUILD_ACK missing_fields"
    
    with pytest.raises(ValueError):
        TreeBuildAck.from_bytes(invalid_data)

def test_rtp_packet_serialization():
    """Test that RTPPacket messages serialize and deserialize correctly"""
    # Create test message
    rtp = RTPPacket(
        tree_id="test_tree",
        is_rootward=True,
        hops=3
    )
    
    # Convert to bytes
    data = rtp.to_bytes()
    
    # Convert back from bytes
    rtp_decoded = RTPPacket.from_bytes(data)
    
    # Verify fields match
    assert rtp_decoded.tree_id == "test_tree"
    assert rtp_decoded.is_rootward == True
    assert rtp_decoded.hops == 3

def test_rtp_packet_leafward():
    """Test RTPPacket serialization with leafward direction"""
    rtp = RTPPacket(
        tree_id="test_tree",
        is_rootward=False, 
        hops=2
    )
    
    data = rtp.to_bytes()
    rtp_decoded = RTPPacket.from_bytes(data)
    
    assert rtp_decoded.is_rootward == False
    assert rtp_decoded.hops == 2

def test_rtp_packet_invalid_format():
    """Test that invalid RTPPacket messages raise ValueError"""
    invalid_data = b"RTP missing_fields"
    
    with pytest.raises(ValueError):
        RTPPacket.from_bytes(invalid_data)

