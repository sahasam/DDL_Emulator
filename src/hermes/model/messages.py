from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class PortCommand:
    port_name: str
    action: str
    parameters: Dict[str, Any] = None

@dataclass
class TreeBuild:
    tree_id: str
    sending_node_id: str
    hops: int
    path: List[str]

    def to_bytes(self) -> bytes:
        # Convert path list to comma-separated string
        path_str = ",".join(self.path)
        return f"TREE_BUILD {self.tree_id} {self.sending_node_id} {self.hops} [{path_str}]".encode('utf-8')
    
    @staticmethod
    def from_bytes(data: bytes):
        parts = data.decode('utf-8').split(maxsplit=4)  # Split into max 4 parts to keep path as one piece
        if len(parts) != 5:
            raise ValueError(f"Invalid TreeBuild message format: {data}")
        
        # Extract the path list
        path_str = parts[4].strip('[]')  # Remove brackets
        path = path_str.split(',') if path_str else []
        
        return TreeBuild(
            tree_id=parts[1],
            sending_node_id=parts[2],
            hops=int(parts[3]),
            path=path
        )

@dataclass
class TreeBuildAck:
    tree_id: str
    hops: int
    path: List[str]

    def to_bytes(self):
        path_str = ",".join(self.path)
        return f"TREE_BUILD_ACK {self.tree_id} {self.hops} [{path_str}]".encode('utf-8')

    @staticmethod
    def from_bytes(data: bytes):
        parts = data.decode('utf-8').split(maxsplit=3)
        if len(parts) != 4:
            raise ValueError(f"Invalid TreeBuildAck message format: {data}")
        
        # Extract the path list
        path_str = parts[3].strip('[]')
        path = path_str.split(',') if path_str else []
        
        return TreeBuildAck(
            tree_id=parts[1],
            hops=int(parts[2]),
            path=path
        )

@dataclass
class RTPPacket:
    """Remote Token Ping Packet --- RTP will ping pong with the trees leaves"""
    tree_id: str
    is_rootward: bool # which direction the packet should be forwarded
    hops: int

    def to_bytes(self):
        return f"RTP {self.tree_id} {self.is_rootward} {self.hops}".encode('utf-8')
    
    @staticmethod
    def from_bytes(data: bytes):
        parts = data.decode('utf-8').split(maxsplit=3)  
        
        if len(parts) != 4:
            raise ValueError(f"Invalid RTPPacket message format: {data}")
        
        return RTPPacket(
            tree_id=parts[1],
            is_rootward=parts[2] == "True",
            hops=int(parts[3])
        )
