from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class PortCommand:
    port_name: str
    action: str
    parameters: Dict[str, Any] = None