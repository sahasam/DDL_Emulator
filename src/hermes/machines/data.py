from dataclasses import dataclass
from enum import Enum
import struct

from hermes.machines.common import Identity, SMP

@dataclass
class Data:
    content: bytes = b""

    def to_bytes(self) -> bytes:
        return self.content

    def __add__(self, other: 'Data') -> 'Data':
        return Data(self.to_bytes() + other.to_bytes())

@dataclass
class Hyperdata(Data):
    owner: Identity = None
    protocol: SMP = None 
    state: int = None
    
    @classmethod
    def from_bytes(cls, data: bytes):
        _owner, _protocol, _state = struct.unpack(">BHB", data[:4])
        hyperdata = cls()
        hyperdata.owner = Identity(_owner)
        hyperdata.protocol = SMP(_protocol) 
        hyperdata.state = _state
        return hyperdata

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