from typing import OrderedDict

import asyncio

from hermes.machines.common import SMP, Identity, State, Q
from hermes.machines.data import Data, Hyperdata, PacketBuilder
from hermes.machines.transitions import ReadPipeQueueTransition, Transition, DirectTransition, ReadQueueTransition, WritePipeQueueTransition, WriteQueueTransition
from hermes.algorithm import PipeQueue

class StateMachine:
    """
    A state machine is a collection of transitions.
    Each transition is a function that takes a hyperdata object and returns a new hyperdata object.
    Depending on the type of transition, each stage of the state machine can require input actions that are
    executed by the state machine.
    """
    def __init__(self, states_type: type[State], transitions: dict[State, Transition], protocol: SMP, logger=None):
        self.transitions = transitions
        self.protocol = protocol
        self.states_type = states_type
        self.state = states_type.initial_state()
        self.updates = 0
        self.last_data = {}
        self.logger = logger

    def evaluate_transition(self, hyperdata: Hyperdata | None, content: Data=None) -> bytes | None:
        _tuple = self.transitions[hyperdata.state].evaluate_sync(content=content)
        if _tuple is None:
            return None

        _state, _content = _tuple

        return PacketBuilder() \
            .with_hyperdata(Hyperdata(owner=hyperdata.owner.flip(), protocol=self.protocol, state=_state)) \
            .with_content(_content) \
            .build()
    
    def initiate(self) -> bytes:
        raise NotImplementedError
    
    def reset(self):
        self.state = self.states_type.initial_state()


class LivenessStateMachine(StateMachine):
    class S(State):
        S1 = (0, "INIT")
        S2 = 1
    
    def __init__(self, logger=None):
        super().__init__(self.S, {
            self.S.S1: DirectTransition(self.S.S2, logger=logger),
            self.S.S2: DirectTransition(self.S.S1, logger=logger),
        }, SMP.LIVENESS, logger=logger)
    
    def initiate(self) -> bytes:
        return PacketBuilder() \
            .with_hyperdata(Hyperdata(owner=Identity.ME, protocol=SMP.LIVENESS, state=self.S.S1)) \
            .build()


class TwoPhaseCommitStateMachine(StateMachine):
    class S(State):
        READ = (0, "INIT")
        WRITE = 1
        A1 = 2
        A2 = 3
    
    def __init__(self, read_q: Q, write_q: Q, logger=None):
        super().__init__(self.S, {
            self.S.READ: ReadQueueTransition(self.S.WRITE, write_q, logger=logger),
            self.S.WRITE: WriteQueueTransition(self.S.A1, read_q, logger=logger),
            self.S.A1: DirectTransition(self.S.A2, logger=logger),
            self.S.A2: DirectTransition(self.S.READ, logger=logger),
        }, SMP.TWO_PHASE_COMMIT, logger=logger)
        self.read_q = read_q,
        self.write_q = write_q
    
    def initiate(self) -> bytes | None:
        if self.write_q.empty():
            if self.logger is not None:
                self.logger.debug(f"[TWO_PHASE_COMMIT] Initiate: Write queue is empty")
            return None
        
        content = self.write_q.get_nowait()
        if self.logger is not None:
            self.logger.debug(f"[TWO_PHASE_COMMIT] Initiate: Sending data: {content}")
        
        return PacketBuilder() \
            .with_hyperdata(Hyperdata(owner=Identity.NOT_ME, protocol=SMP.TWO_PHASE_COMMIT, state=self.S.WRITE)) \
            .with_content(Data(content=bytes(content, 'utf-8'))) \
            .build() \
            .to_bytes()

class TwoPhaseCommitPipeQueueStateMachine(StateMachine):
    class S(State):
        READ = (0, "INIT")
        WRITE = 1
        A1 = 2
        A2 = 3

    def __init__(self, read_q: PipeQueue, write_q: PipeQueue, logger=None):
        super().__init__(self.S, {
            self.S.READ: ReadPipeQueueTransition(self.S.WRITE, write_q, logger=logger),
            self.S.WRITE: WritePipeQueueTransition(self.S.A1, read_q, logger=logger),
            self.S.A1: DirectTransition(self.S.A2, logger=logger),
            self.S.A2: DirectTransition(self.S.READ, logger=logger),
        }, SMP.TWO_PHASE_COMMIT_PIPE_QUEUE, logger=logger)
        self.read_q = read_q,
        self.write_q = write_q
    
    def initiate(self) -> bytes | None:
        if self.write_q.empty():
            if self.logger is not None:
                self.logger.debug(f"[TWO_PHASE_COMMIT_PIPE_QUEUE] Initiate: Write queue is empty")
            return None

        content = self.write_q.get()
        if self.logger is not None:
            self.logger.debug(f"[TWO_PHASE_COMMIT_PIPE_QUEUE] Initiate: Sending data: {content}")
        
        return PacketBuilder() \
            .with_hyperdata(Hyperdata(owner=Identity.NOT_ME, protocol=SMP.TWO_PHASE_COMMIT_PIPE_QUEUE, state=self.S.WRITE)) \
            .with_content(content) \
            .build() \
            .to_bytes()

class AlphabetStateMachine(StateMachine):
    def __init__(self, logger=None):
        self.read_q = Q()
        self.write_q = Q()
        self.logger = logger
        self.state_machines = OrderedDict({
            SMP.TWO_PHASE_COMMIT: TwoPhaseCommitStateMachine(self.read_q, self.write_q, logger=logger),
            SMP.LIVENESS: LivenessStateMachine(logger=logger)
        })
        self.letter = 'a'
        asyncio.create_task(self.alphabet())

    async def alphabet(self) -> None:
        """Generate the alphabet sequence."""
        while True:
            # If we have a Data object, extract the content
            current_letter = await self.read_q.get()
            self.logger.debug(f"[ALPHABET][alphabet] current_letter={current_letter}")
            current_letter = current_letter.content.decode('utf-8')
            
            next_ord = ord(current_letter) + 1
            if next_ord > ord('z'):
                next_ord = ord('a')
            
            next_letter = chr(next_ord)
            self.logger.debug(f"[ALPHABET][alphabet] next_letter={next_letter}")
            await self.write_q.put(Data(content=next_letter.encode('utf-8')))
            self.letter = next_letter

    def evaluate_transition(self, hyperdata: Hyperdata, content: Data=None) -> bytes:
        # Store the hyperdata in the corresponding state machine
        target_sm = self.state_machines.get(hyperdata.protocol)
        if not target_sm:
            raise ValueError(f"No state machine found for protocol {hyperdata.protocol}")
        self.logger.debug(f"[ALPHABET] hyperdata={hyperdata} content={content} target_sm={target_sm}")
        target_sm.last_data = (hyperdata, content)

        # Evaluate state machines in priority order (earlier in ordered dict = higher priority)
        if self.state_machines[SMP.TWO_PHASE_COMMIT].last_data is not None:
            self.logger.debug(f"[ALPHABET] Two Phase Commit Packet Data Found")
            _hyperdata, _content = self.state_machines[SMP.TWO_PHASE_COMMIT].last_data
            if _hyperdata is not None:
                result = self.state_machines[SMP.TWO_PHASE_COMMIT].evaluate_transition(_hyperdata, _content)
                if result is not None:
                    self.logger.debug(f"[ALPHABET] Transitioning TWO_PHASE_COMMIT {_hyperdata.state} -> {_hyperdata.state}")
                    self.state_machines[SMP.TWO_PHASE_COMMIT].last_data = None
                    return result
                else:
                    self.logger.debug(f"[ALPHABET] Failed to transition two-phase-commit")

        if self.state_machines[SMP.LIVENESS].last_data is not None:
            self.logger.debug(f"[ALPHABET] Liveness token used instead")
            _hyperdata, _content = self.state_machines[SMP.LIVENESS].last_data
            self.state_machines[SMP.LIVENESS].last_data = None
            return self.state_machines[SMP.LIVENESS].evaluate_transition(_hyperdata)
        elif self.state_machines[SMP.LIVENESS].last_data is None:
            self.logger.debug(f"[ALPHABET] Liveness token created")
            return self.state_machines[SMP.LIVENESS].initiate()
        
        raise ValueError("Should not make it here")
        
    
    def initiate(self) -> bytes:
        self.write_q.put_nowait('a')
        self.logger.debug("[ALPHABET] Initializing Packet")
        return self.state_machines[SMP.TWO_PHASE_COMMIT].initiate()
    
    def reset(self):
        for _, sm in self.state_machines.items():
            sm.reset()



class TwoPhaseCommitPipeStateMachine(StateMachine):
    def __init__(self, read_q: PipeQueue, write_q: PipeQueue, logger=None):
        self.logger = logger
        self.read_q = read_q
        self.write_q = write_q
        self.state_machines = OrderedDict({
            SMP.TWO_PHASE_COMMIT_PIPE_QUEUE: TwoPhaseCommitPipeQueueStateMachine(self.read_q, self.write_q, logger=logger),
            SMP.LIVENESS: LivenessStateMachine(logger=logger)
        })
        # Initialize last_data for each state machine
        for sm in self.state_machines.values():
            sm.last_data = {}

    def evaluate_transition(self, hyperdata: Hyperdata, content: Data=None) -> bytes:
        # Store the hyperdata in the corresponding state machine
        target_sm = self.state_machines.get(hyperdata.protocol)
        if not target_sm:
            raise ValueError(f"No state machine found for protocol {hyperdata.protocol}")
        self.logger.debug(f"[ALPHABET] hyperdata={hyperdata} content={content} target_sm={target_sm}")
        target_sm.last_data[hyperdata.owner] = (hyperdata, content)

        # Evaluate state machines in priority order (earlier in ordered dict = higher priority)
        if self.state_machines[SMP.TWO_PHASE_COMMIT_PIPE_QUEUE].last_data[hyperdata.owner] is not None:
            self.logger.debug(f"[ALPHABET] Two Phase Commit Packet Data Found")
            _hyperdata, _content = self.state_machines[SMP.TWO_PHASE_COMMIT_PIPE_QUEUE].last_data[hyperdata.owner]
            if _hyperdata is not None:
                result = self.state_machines[SMP.TWO_PHASE_COMMIT_PIPE_QUEUE].evaluate_transition(_hyperdata, _content)
                if result is not None:
                    self.logger.debug(f"[ALPHABET] Transitioning TWO_PHASE_COMMIT {_hyperdata.state} -> {_hyperdata.state}")
                    self.state_machines[SMP.TWO_PHASE_COMMIT_PIPE_QUEUE].last_data[hyperdata.owner] = None
                    return result
                else:
                    self.logger.debug(f"[ALPHABET] Failed to transition two-phase-commit")

        if hyperdata.owner in self.state_machines[SMP.LIVENESS].last_data and self.state_machines[SMP.LIVENESS].last_data[hyperdata.owner] is not None:
            self.logger.debug(f"[ALPHABET] Liveness token used instead")
            _hyperdata, _content = self.state_machines[SMP.LIVENESS].last_data[hyperdata.owner]
            self.state_machines[SMP.LIVENESS].last_data[hyperdata.owner] = None
            return self.state_machines[SMP.LIVENESS].evaluate_transition(_hyperdata)
        else:
            self.logger.debug(f"[ALPHABET] Liveness token created")
            return self.state_machines[SMP.LIVENESS].initiate()
        
    
    def initiate(self) -> bytes:
        self.write_q.put(Data(content=b'a'))
        self.logger.debug("[ALPHABET] Initializing Packet")
        return self.state_machines[SMP.TWO_PHASE_COMMIT_PIPE_QUEUE].initiate()
    
    def reset(self):
        for _, sm in self.state_machines.items():
            sm.reset()

class StateMachineFactory:
    _state_machine_map = {
        SMP.LIVENESS: LivenessStateMachine,
        SMP.TWO_PHASE_COMMIT: TwoPhaseCommitStateMachine,
        SMP.TWO_PHASE_COMMIT_PIPE_QUEUE: TwoPhaseCommitPipeQueueStateMachine
    }

    @classmethod
    def get_state_type(cls, protocol: SMP) -> type[State]:
        """Returns the State enum class for the given protocol."""
        state_machine_class = cls._state_machine_map.get(protocol)
        if not state_machine_class:
            raise ValueError(f"No state machine found for protocol {protocol}")
        return state_machine_class.S