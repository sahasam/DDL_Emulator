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
    class State(Enum):
        S1 = 0
        S2 = 1

        @classmethod
        def initial_state(cls):
            return cls.S1
    
    def __init__(self):
        super().__init__([
            Transition(self.State.S1, self.State.S2, self.State.S2),
            Transition(self.State.S2, self.State.S1, self.State.S1),
        ])
        self.protocol = SMP.LIVENESS
        self.updates = 0
        self.state = self.State.initial_state()
    
    def evaluate_transition(self, hyperdata: Hyperdata, success_criteria: Callable[[Hyperdata], bool]) -> Hyperdata:
        self.state = self.transitions[self.State(hyperdata.state)].next_state
        self.updates += 1
        return self.to_hyperdata(Identity(1 - hyperdata.owner._value_))
    
    def to_hyperdata(self, owner: Identity) -> Hyperdata:
        hyperdata = Hyperdata()
        hyperdata.protocol = self.protocol
        hyperdata.state = self.state
        hyperdata.owner = owner
        return hyperdata
    
    def reset(self):
        self.state = self.State.initial_state()
        self.updates = 0
