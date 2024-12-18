from ddl.sim import link_sim, bridge_sim, sim_from_config

import argparse
import yaml

def load_config(config_file):
    """
    Load and parse a YAML configuration file.
    
    Args:
        config_file (str): Path to the YAML configuration file
        
    Returns:
        dict: Parsed configuration data
    """
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
    parser.add_argument('--config-file', '-c', type=str, help='Path to the YAML configuration file')
    parser.add_argument('--mode', choices=['a', 'b'], default='a', help='Symmetry Break (a or b)')
    parser.add_argument('--interface', choices=['bridge0', 'local', 'localsingle'], default='local', help='Network interface to use')
    parser.add_argument('--debug', action='store_true', help='Flag to enable local process testing')
    
    args = parser.parse_args()

    if args.config_file:
        config = load_config(args.config_file)
        sim_from_config(config)

    elif args.interface == "local":
        link_sim()

    elif args.interface == "bridge0":
        # get bridge0 interface ip
        # Mac-Mini bridge0 ip: 169.254.103.201 (Manually set)
        dst = '169.254.103.201' 
        bridge_sim(is_client=(args.mode == "b"), addr=(dst, 55555))
