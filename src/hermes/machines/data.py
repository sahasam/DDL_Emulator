import struct

from hermes.machines.common import Identity, SMP
from abc import ABC, abstractmethod

class Data(ABC):
    @abstractmethod
    def to_bytes(self) -> bytes:
        raise NotImplementedError

    def __add__(self, other: 'Data') -> 'Data':
        return Data(self.to_bytes() + other.to_bytes())

class Hyperdata(Data):
    def __init__(self):
        self.owner = None
        self.protocol = None 
        self.state = None
    
    @classmethod
    def from_bytes(cls, data: bytes):
        owner, protocol, state = struct.unpack(">BHB", data[:4])
        hyperdata = cls()
        hyperdata.owner = Identity(owner)
        hyperdata.protocol = SMP(protocol) 
        hyperdata.state = state
        return hyperdata

    def to_bytes(self) -> bytes:
        state_value = self.state.value if hasattr(self.state, 'value') else self.state
        return struct.pack(">BHB", self.owner.value, self.protocol.value, state_value)

class Content(Data):
    def __init__(self, content: bytes):
        self.content = content
    
    def to_bytes(self) -> bytes:
        return self.content
