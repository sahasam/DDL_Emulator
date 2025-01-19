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

class TreePacketData(Data):
    type: Literal["TREE_BUILD", "TREE_BOUNDARY"] = None


@dataclass
class Hyperdata(Data):
    owner: Identity = None
    protocol: SMP = None 
    state: int = None
    
    def to_bytes(self) -> bytes:
        state_value = int(self.state)
        return struct.pack(">BHB", self.owner.value, self.protocol.value, state_value)
    
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
    def from_bytes(cls, data: bytes) -> tuple[Hyperdata, Data | None]:
        hyperdata = Hyperdata.from_bytes(data[:4])
        content = Data()
        if len(data) > 4:
            content = Data(data[4:])
        return hyperdata, content