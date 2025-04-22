from dataclasses import dataclass
import logging

from hermes.sim.PipeQueue import PipeQueue


@dataclass
class PortConfig:
    logger: logging.Logger
    interface: str
    port_id: str
    name: str # deprecated

@dataclass
class PortIO:
    read_q: PipeQueue
    write_q: PipeQueue
    signal_q: PipeQueue