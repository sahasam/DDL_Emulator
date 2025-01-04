from abc import ABC, abstractmethod
from enum import Enum
from asyncio import Event

class Identity(Enum):
    ME = 0
    NOT_ME = 1

class SMP(Enum):
    LIVENESS = 0
    TWO_PHASE_COMMIT = 1

class TokenEvent(Event):
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