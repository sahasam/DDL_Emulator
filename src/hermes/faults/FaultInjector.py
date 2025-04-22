from dataclasses import dataclass
import threading

@dataclass
class FaultState:
    """Thread-safe container for fault injection state"""
    is_active: bool = False
    drop_rate: float = 0.0
    delay_ms: int = 0

    def __str__(self):
        return f"FaultState(is_active={self.is_active}, drop_rate={self.drop_rate}, delay_ms={self.delay_ms})"
    
    def __repr__(self):
        return self.__str__()

class ThreadSafeFaultInjector:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = FaultState()
    
    def get_state(self) -> FaultState:
        with self._lock:
            # Return a copy to prevent external modifications
            return FaultState(
                is_active=self._state.is_active,
                drop_rate=self._state.drop_rate,
                delay_ms=self._state.delay_ms
            )
    
    def update_state(self, new_state: FaultState):
        with self._lock:
            self._state = new_state