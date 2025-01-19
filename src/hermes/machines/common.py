import asyncio
from enum import Enum

class Identity(Enum):
    ME = 0
    NOT_ME = 1

    def __int__(self):
        return self._value_
    
    def flip(self):
        return Identity(1 - int(self))

class SMP(Enum):
    LIVENESS = 0
    TWO_PHASE_COMMIT = 1
    TWO_PHASE_COMMIT_PIPE_QUEUE = 2

class TokenEvent(asyncio.Event):
    def __init__(self):
        self._packet = None
        super().__init__()

    def set(self, packet):
        self._packet = packet
        super().set()

    def clear(self):
        self._packet = None
        super().clear()

    async def wait(self):
        await super().wait()
        return self._packet

class Q(asyncio.Queue):
    def __init__(self, *args, **kwargs):
        super().__init__(maxsize=2, *args, **kwargs)

class State(Enum):
    @classmethod
    def initial_state(cls):
        for state in cls:
            if isinstance(state.value, tuple) and len(state.value) > 1 and state.value[1] == "INIT":
                return state
        raise NotImplementedError("No initial state defined")
    
    def __int__(self):
        if isinstance(self.value, tuple):
            return self.value[0]
        elif isinstance(self.value, (int, float)):
            return self.value
        raise ValueError(f"Cannot convert {self.value} of type {type(self.value)} to int")

    @classmethod
    def _missing_(cls, value):
        # Handle conversion from int to State
        if isinstance(value, int):
            for member in cls:
                if int(member) == value:
                    return member
        return None