from enum import Enum
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
    def from_bytes(cls, data: bytes, state_type: Enum):
        owner, protocol, state = struct.unpack(">BHB", data[:4])
        hyperdata = cls()
        hyperdata.owner = Identity(owner)
        hyperdata.protocol = SMP(protocol) 
        hyperdata.state = state_type(state)
        return hyperdata

    def to_bytes(self) -> bytes:
        state_value = self.state.value if hasattr(self.state, 'value') else self.state
        return struct.pack(">BHB", self.owner.value, self.protocol.value, state_value)
    
    def __str__(self):
        return f"Hyperdata(owner={self.owner}, protocol={self.protocol}, state={self.state})"

class Content(Data):
    def __init__(self, content: bytes):
        self.content = content
    
    def to_bytes(self) -> bytes:
        return self.content
