# Hermes

Hermes is a network simulation framework for testing and developing network protocols.

## Usage

```python
from hermes.sim import Sim

sim = Sim.from_config("config.json")
sim.start()
```

## Config

The config is a Yaml file that describes the simulation process. You can run an entire network in a single simulation, or just run the ports and threads of a single node.

