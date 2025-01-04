from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable

from hermes.machines.common import Identity, SMP
from hermes.machines.data import Hyperdata

class Transition:
    def __init__(
        self,
        current_state: Enum,
        next_state: Enum,
        error_state: Enum
    ):
        self.current_state = current_state
        self.next_state = next_state
        self.error_state = error_state


class StateMachine(ABC):
    def __init__(self, transitions: list[Transition]):
        self.transitions = {transition.current_state: transition for transition in transitions}

    @abstractmethod
    def evaluate_transition(self, hyperdata: Hyperdata, success_criteria: Callable[[Hyperdata], bool]) -> None:
        raise NotImplementedError
    
    @abstractmethod
    def to_hyperdata(self) -> Hyperdata:
        raise NotImplementedError


class LivenessStateMachine(StateMachine):
    class LivenessState(Enum):
        S1 = 0
        S2 = 1
        S3 = 2

        @classmethod
        def initial_state(cls):
            return cls.S1
    
    def __init__(self, owner: Identity):
        super().__init__([
            Transition(self.LivenessState.S1, self.LivenessState.S2, self.LivenessState.S2),
            Transition(self.LivenessState.S2, self.LivenessState.S3, self.LivenessState.S3),
            Transition(self.LivenessState.S3, self.LivenessState.S1, self.LivenessState.S1)
        ])
        self.owner = owner
        self.protocol = SMP.LIVENESS
        self.updates = 0
        self.state = self.LivenessState.initial_state()
    
    def evaluate_transition(self, hyperdata: Hyperdata, success_criteria: Callable[[Hyperdata], bool]) -> Hyperdata:
        self.state = self.transitions[self.LivenessState(hyperdata.state)].next_state
        self.updates += 1
        return self.to_hyperdata()
    
    def to_hyperdata(self) -> Hyperdata:
        hyperdata = Hyperdata()
        hyperdata.protocol = self.protocol
        hyperdata.state = self.state
        hyperdata.owner = self.owner
        return hyperdata
    
    def reset(self):
        self.state = self.LivenessState.initial_state()
        self.updates = 0
