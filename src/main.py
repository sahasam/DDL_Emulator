from hermes.sim import Sim

import argparse
import yaml

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Alternating Bit Protocol Implementation')
    parser.add_argument('--config_file', '-c', type=str, help='Path to the YAML configuration file')
    parser.add_argument('--log_dir', '-l', type=str, default='/opt/hermes/logs', 
                        help='Directory for log files (default: /opt/hermes/logs)')
    args = parser.parse_args()

    if args.config_file:
        config = load_config(args.config_file)
        Sim.from_config(config, log_dir=args.log_dir).start()
        
