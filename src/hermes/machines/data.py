from dataclasses import dataclass
import struct
from typing import Literal

from hermes.machines.common import Identity, SMP

@dataclass
class Data:
    content: bytes = b""

    def to_bytes(self) -> bytes:
        return self.content

    def __add__(self, other) -> 'Data':
        if other is None:
            return self

        return Data(self.to_bytes() + other.to_bytes())

class TreeBuildData(Data):
    type: Literal["TREE_BUILD"] = "TREE_BUILD"
    tree_id: str = None
    hop_count: int = 0
    ttl: int = 0
    def __init__(self, tree_id: str = None, hop_count: int = 0, ttl: int = 0, **kwargs):
        super().__init__()
        self.tree_id = tree_id
        self.hop_count = hop_count
        self.ttl = ttl

    def to_bytes(self) -> bytes:
        # Pack type (as 12 bytes string) and tree_id (as 20 bytes string) (4 byte int for hop_count)
        return struct.pack(">13s20sII", 
            self.type.encode(), 
            self.tree_id.encode(),
            self.hop_count,
            self.ttl
        )
    
    def __str__(self):
        return f"TreeBuildData(tree_id={self.tree_id}) ttl={self.ttl} hop_count={self.hop_count}"
    
    @classmethod
    def from_bytes(cls, data: bytes) -> 'TreeBuildData':
        type_str, tree_id, hop_count, ttl = struct.unpack(">13s20sII", data)
        return cls(tree_id=tree_id.decode().strip('\x00'), hop_count=hop_count, ttl=ttl)

class TreeBoundaryData(Data):
    type: Literal["TREE_BOUNDARY"] = "TREE_BOUNDARY"
    tree_id: str = None
    node_hop: list[str] = None

    def __init__(self, tree_id: str = None, node_hop: list[str] | None = None, **kwargs):
        super().__init__()
        self.tree_id = tree_id
        self.node_hop = node_hop if node_hop is not None else []
        # Ignore any extra kwargs since 'type' is a class constant

    def to_bytes(self) -> bytes:
        # Ensure we don't exceed 5 nodes
        if len(self.node_hop) > 5:
            raise ValueError("node_hop cannot contain more than 5 nodes")
            
        # Pack type (as 13 bytes string) and tree_id (as 20 bytes string)
        # For node_hop, first pack the count, then each node name padded to 20 bytes
        # We'll reserve space for 5 nodes (100 bytes total) and pad with nulls
        base = struct.pack(">13s20sI", 
            self.type.encode(), 
            self.tree_id.encode(),
            len(self.node_hop)
        )
        
        # Pack the actual nodes (up to 5)
        node_data = b''.join(
            struct.pack(">20s", node.encode()) 
            for node in self.node_hop
        )
        # Pad remaining slots with null bytes
        padding = b'\x00' * (100 - len(node_data))  # 100 = 5 nodes * 20 bytes
        
        return base + node_data + padding
    
    def __str__(self):
        return f"TreeBoundaryData(tree_id={self.tree_id}, node_hop={self.node_hop})"
    
    def __repr__(self):
        return f"TreeBoundaryData(tree_id={self.tree_id}, node_hop={self.node_hop})"
    
    @classmethod
    def from_bytes(cls, data: bytes) -> 'TreeBoundaryData':
        # First 37 bytes contain type, tree_id, and node count
        type_str, tree_id, node_count = struct.unpack(">13s20sI", data[:37])
        
        if node_count > 5:
            raise ValueError("Invalid node_count: cannot exceed 5")
            
        node_hop = []
        offset = 37
        # Only unpack the number of nodes indicated by node_count
        for _ in range(node_count):
            node, = struct.unpack(">20s", data[offset:offset+20])
            node_hop.append(node.decode().strip('\x00'))
            offset += 20
            
        return cls(tree_id=tree_id.decode().strip('\x00'), node_hop=node_hop)

@dataclass
class Hyperdata(Data):
    owner: Identity = None
    protocol: SMP = None 
    state: int = None
    
    def to_bytes(self) -> bytes:
        state_value = int(self.state)
        return struct.pack(">BHB", self.owner.value, self.protocol.value, state_value)

    @classmethod
    def from_bytes(cls, data: bytes) -> 'Hyperdata':
        owner, protocol, state = struct.unpack(">BHB", data)
        return cls(owner=Identity(owner), protocol=SMP(protocol), state=state)

    def __str__(self):
        return f"Hyperdata(owner={self.owner}, protocol={self.protocol}, state={self.state})"

class PacketBuilder:
    def __init__(self):
        self.hyperdata = Data()
        self.content = Data()

    def with_hyperdata(self, hyperdata: Hyperdata) -> 'PacketBuilder':
        self.hyperdata = hyperdata
        return self

    def with_content(self, content: Data) -> 'PacketBuilder':
        self.content = content
        return self

    def build(self) -> Data:
        if self.hyperdata is None:
            raise ValueError("Hyperdata is required")
        
        packet = self.hyperdata + self.content
        return packet

    @classmethod
    def from_bytes(cls, data: bytes) -> tuple[Data | TreeBuildData | TreeBoundaryData | None]:
        content = None
        if data is not None and len(data) > 0:
            content_bytes = data
            # Try to detect the message type
            if len(content_bytes) >= 13:  # minimum size for type field
                type_str = content_bytes[:13].strip(b'\x00').decode()
                if type_str == "TREE_BUILD":
                    content = TreeBuildData.from_bytes(content_bytes)
                elif type_str == "TREE_BOUNDARY":
                    content = TreeBoundaryData.from_bytes(content_bytes)
                else:
                    content = Data(content_bytes)
            else:
                content = Data(content_bytes)
        return content