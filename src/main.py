import asyncio
from hermes.sim.Sim import Sim

import argparse
import yaml
from multiprocessing import Process

def load_config(config_file):
    """Load and parse a YAML configuration file. """
    try:
        with open(config_file, 'r') as file:
            config = yaml.safe_load(file)
            return config
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file: {e}")
        return None
    except FileNotFoundError:
        print(f"Configuration file {config_file} not found")
        return None
    
def run_sim_from_config(path: str):
    """Single thread simulation run from a configuration file."""
    config = load_config(path)
    sim = Sim.from_config(config)
    asyncio.run(sim.run())
        
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Alternating Bit Protocol Implementation')
    parser.add_argument(
        '--config_files', '-c',
        nargs='+',
        type=str,
        help="Paths to YAML configuration files (space-separated.)"
    )
    
    args = parser.parse_args()

    processes = []
    for path in args.config_files:
        p = Process(target=run_sim_from_config, args=(path,))
        p.start()
        print(f"Started simulation process for {path} with PID {p.pid}")
        processes.append(p)
    
    for p in processes:
        p.join()
        print(f"Simulation process for {p.pid} has finished.")
        
        
