from abc import ABC, abstractmethod
from enum import Enum
from typing import OrderedDict

import asyncio

from hermes.machines.common import SMP
from hermes.machines.data import Data, Hyperdata, PacketBuilder

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

class Transition(ABC):
    @abstractmethod
    def evaluate_sync(self) -> None | Enum:
        raise NotImplementedError

class DirectTransition(Transition):
    def __init__(
        self,
        next_state: State,
    ):
        self.next_state = next_state
    
    def evaluate_sync(self) -> None | Enum:
        return self.next_state

class ReadQueueTransition(Transition):
    def __init__(self, next_state: Enum, queue: asyncio.Queue):
        self.next_state = next_state
        self.queue = queue
    
    def evaluate_sync(self) -> None | tuple[Enum, Data]:
        """
        Returns the next state and the data to be sent to the next state.
        If the parent state machine is not ready to transition, returns None.
        """
        if self.queue.empty():
            return None
        return (self.next_state, self.queue.get_nowait())

class WriteQueueTransition(Transition):
    def __init__(self, next_state: Enum, queue: asyncio.Queue):
        self.next_state = next_state
        self.queue = queue
    
    def evaluate_sync(self) -> None | Enum:
        self.queue.put_nowait(None)
        return self.next_state



class StateMachine:
    """
    A state machine is a collection of transitions.
    Each transition is a function that takes a hyperdata object and returns a new hyperdata object.
    Depending on the type of transition, each stage of the state machine can require input actions that are
    executed by the state machine.
    """
    def __init__(self, states_type: type[State], transitions: dict[State, Transition], protocol: SMP):
        self.transitions = transitions
        self.protocol = protocol
        self.states_type = states_type
        self.state = states_type.initial_state()
        self.updates = 0
        self.last_hyperdata = None

    def evaluate_transition(self, hyperdata: Hyperdata, content: Data=None) -> bytes:
        self.state = self.transitions[self.states_type(hyperdata.state)].evaluate_sync()
        if self.state is None:
            raise ValueError("No state transition found")

        return PacketBuilder() \
            .with_hyperdata(Hyperdata(owner=hyperdata.owner.flip(), protocol=self.protocol, state=self.state)) \
            .with_content(content) \
            .build()
    
    def reset(self):
        self.state = self.states_type.initial_state()


class LivenessStateMachine(StateMachine):
    class S(State):
        S1 = (0, "INIT")
        S2 = 1
    
    def __init__(self):
        super().__init__(self.S, {
            self.S.S1: DirectTransition(self.S.S2),
            self.S.S2: DirectTransition(self.S.S1),
        }, SMP.LIVENESS)


class TwoPhaseCommitStateMachine(StateMachine):
    class S(State):
        S1 = (0, "INIT")
        S2 = 1
        S3 = 2
        S4 = 3
    
    def __init__(self, read_q: Q, write_q: Q):
        super().__init__(self.S, {
            self.S.S1: ReadQueueTransition(self.S.S2, write_q),
            self.S.S2: WriteQueueTransition(self.S.S3, read_q),
            self.S.S3: DirectTransition(self.S.S4),
            self.S.S4: DirectTransition(self.S.S1),
        }, SMP.TWO_PHASE_COMMIT)

class AlphabetStateMachine(StateMachine):
    def __init__(self):
        self.read_q = Q()
        self.write_q = Q()
        self.state_machines = OrderedDict({
            SMP.TWO_PHASE_COMMIT: TwoPhaseCommitStateMachine(self.read_q, self.write_q),
            SMP.LIVENESS: LivenessStateMachine()
        })
        asyncio.create_task(self.alphabet())

    async def alphabet(self):
        current_letter = 'a'
        while True:
            self.write_q.put_nowait(current_letter)
            current_letter = await self.read_q.get()
            next_ord = ord(current_letter) + 1
            if next_ord > ord('z'):
                current_letter = 'a'
            else:
                current_letter = chr(next_ord)

    def evaluate_transition(self, hyperdata: Hyperdata, content: Data=None) -> bytes:
        # Store the hyperdata in the corresponding state machine
        target_sm = self.state_machines.get(hyperdata.protocol)
        if not target_sm:
            raise ValueError(f"No state machine found for protocol {hyperdata.protocol}")
        target_sm.last_hyperdata = hyperdata

        # Evaluate state machines in priority order (earlier in ordered dict = higher priority)
        for _, sm in self.state_machines.items():
            if sm.last_hyperdata is not None:
                try:
                    result = sm.evaluate_transition(sm.last_hyperdata, content)
                    if result is not None:
                        sm.last_hyperdata = None
                        return result
                except:
                    continue

        # If we get here, no state machine produced a result
        raise ValueError("No state machine was able to process its hyperdata")
    
    def reset(self):
        for _, sm in self.state_machines.items():
            sm.reset()

