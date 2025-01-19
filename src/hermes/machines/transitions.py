from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

from hermes.machines.common import Q, State
from hermes.machines.data import Data
from hermes.algorithm import PipeQueue


class Transition(ABC):
    @abstractmethod
    def evaluate_sync(self, content: Data=None) -> None | Enum:
        raise NotImplementedError

class DirectTransition(Transition):
    def __init__(self, next_state: State, logger=None):
        self.next_state = next_state
        self.logger = logger
    
    def evaluate_sync(self, content: Data=None) -> None | tuple[Enum, Data]:
        if self.logger is not None:
            self.logger.debug(f"[DIRECT_TRANSITION] Transitioning to {self.next_state}")
        return self.next_state, None

class ReadQueueTransition(Transition):
    def __init__(self, next_state: Enum, queue: Q, logger=None):
        self.next_state = next_state
        self.queue = queue
        self.logger = logger
    
    def evaluate_sync(self, content: Data=None) -> None | tuple[Enum, Data]:
        """
        Returns the next state and the data to be sent to the next state.
        If the parent state machine is not ready to transition, returns None.
        """
        if self.queue.empty():
            if self.logger is not None:
                self.logger.debug(f"[READ_QUEUE_TRANSITION] Queue is empty")
            return None
        if self.logger is not None:
            self.logger.debug(f"[READ_QUEUE_TRANSITION] Transitioning to {self.next_state}")
        return (self.next_state, self.queue.get_nowait())

class WriteQueueTransition(Transition):
    def __init__(self, next_state: Enum, queue: Q, logger=None):
        self.next_state = next_state
        self.queue = queue
        self.logger = logger
    
    def evaluate_sync(self, content: Data=None) -> None | tuple[Enum, Data]:
        self.queue.put_nowait(content)
        if self.logger:
            self.logger.debug(f"[WRITE_QUEUE_TRANSITION] Transitioning to {self.next_state}")
        return (self.next_state, None)

class ReadPipeQueueTransition(Transition):
    def __init__(self, next_state: Enum, queue: PipeQueue, logger=None):
        self.next_state = next_state
        self.queue = queue
        self.logger = logger
    
    def evaluate_sync(self, content: Optional[Data]=None) -> Optional[tuple[Enum, Data]]:
        """
        Returns the next state and the data to be sent to the next state.
        If the parent state machine is not ready to transition, returns None.
        """
        data = self.queue.get()
        if data is None:
            if self.logger is not None:
                self.logger.debug(f"[READ_PIPE_QUEUE_TRANSITION] No data available")
            return None
        if self.logger is not None:
            self.logger.debug(f"[READ_PIPE_QUEUE_TRANSITION] Got data: {data}")
        return (self.next_state, data)

class WritePipeQueueTransition(Transition):
    def __init__(self, next_state: Enum, queue: PipeQueue, logger=None):
        self.next_state = next_state
        self.queue = queue
        self.logger = logger
    
    def evaluate_sync(self, content: Optional[Data]=None) -> Optional[tuple[Enum, Data]]:
        """
        Writes content to the pipe queue and transitions to the next state.
        """
        self.queue.put(content)
        if self.logger is not None:
            self.logger.debug(f"[WRITE_PIPE_QUEUE_TRANSITION] Wrote data: {content}")
        return (self.next_state, None)

