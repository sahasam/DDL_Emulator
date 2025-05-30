from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class PortCommand:
    port_name: str
    action: str
    parameters: Dict[str, Any] = None

@dataclass
class TreeBuild:
    tree_id: str            # the name of the tree, generally the node_id:port_id
    tree_instance_id: str   # the instance id of the tree, used to invalidate old trees
    hops: int               # the number of hops to the root of the tree

    def to_bytes(self) -> bytes:
        return f"TREE_BUILD {self.tree_id} {self.tree_instance_id} {self.hops}".encode('utf-8')
    
    @staticmethod
    def from_bytes(data: bytes):
        parts = data.decode('utf-8').split(maxsplit=3)  # Split into max 4 parts to keep path as one piece
        if len(parts) != 4:
            raise ValueError(f"Invalid TreeBuild message format: {data}")
        
        return TreeBuild(
            tree_id=parts[1],
            tree_instance_id=parts[2],
            hops=int(parts[3]),
        )

@dataclass
class TreeBuildAck:
    tree_id: str            # the name of the tree, generally the node_id:port_id
    tree_instance_id: str   # the instance id of the tree, used to invalidate old trees
    hops: int               # the number of hops to the root of the tree
    path: List[str]         # the path to the root of the tree

    def to_bytes(self):
        path_str = ",".join(self.path)
        return f"TREE_BUILD_ACK {self.tree_id} {self.tree_instance_id} {self.hops} [{path_str}]".encode('utf-8')

    @staticmethod
    def from_bytes(data: bytes):
        parts = data.decode('utf-8').split(maxsplit=4)
        if len(parts) != 5:
            raise ValueError(f"Invalid TreeBuildAck message format: {data}")
        
        # Extract the path list
        path_str = parts[4].strip('[]')
        path = path_str.split(',') if path_str else []
        
        return TreeBuildAck(
            tree_id=parts[1],
            tree_instance_id=parts[2],
            hops=int(parts[3]),
            path=path
        )


@dataclass
class TreeBuildInvalidation:
    tree_id: str
    tree_instance_id: str
    rootward: bool

    def to_bytes(self):
        return f"TREE_BUILD_INVALIDATION {self.tree_id} {self.tree_instance_id} {self.rootward}".encode('utf-8')
    
    @staticmethod
    def from_bytes(data: bytes):
        parts = data.decode('utf-8').split(maxsplit=3)
        if len(parts) != 4:
            raise ValueError(f"Invalid TreeBuildInvalidation message format: {data}")
        
        return TreeBuildInvalidation(
            tree_id=parts[1],
            tree_instance_id=parts[2],
            rootward=parts[3] == "True",
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
