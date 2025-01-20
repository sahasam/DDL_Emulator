import asyncio
import subprocess
from typing import Optional, List

async def run_subprocess(command: list, timeout: int = 10) -> str:
    """Runs a subprocess command asynchronously with a timeout."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        
        if proc.returncode != 0:
            raise Exception(f"Command failed: {stderr.decode()}")
        
        return stdout.decode()
    except asyncio.TimeoutError:
        print(f"Command timed out after {timeout} seconds")
        return ""
    except Exception as e:
        print(f"Error running subprocess: {e}")
        return ""

async def ping_broadcast(interface: str, broadcast_address: str) -> bool:
    """Pings the link-local broadcast address for the given interface."""
    command = ['ping6', '-c', '3', f'{broadcast_address}%{interface}']
    try:
        await run_subprocess(command, timeout=5)  # 5 seconds timeout for ping
        return True  # Successfully pinged
    except Exception as e:
        print(f"Ping failed: {e}")
        return False

async def get_ipv6_neighbors(interface: str) -> Optional[List[str]]:
    """Fetches IPv6 neighbor link-local addresses for a specific interface."""
    
    # Step 1: Get local IPv6 address of the interface using ifconfig
    command = ['ifconfig', interface]
    output = await run_subprocess(command, timeout=5)
    
    if not output:
        print(f"Failed to get details for interface {interface}.")
        return None
    
    local_ipv6 = None
    local_addresses = []
    
    # Extract the local IPv6 address (usually starts with 'fe80::')
    for line in output.splitlines():
        if "inet6" in line:
            parts = line.split()
            local_ipv6 = parts[1]  # The second part is the IPv6 address
            # Strip the interface identifier (%interface) for comparison
            local_address_normalized = local_ipv6.split('%')[0]
            local_addresses.append(local_address_normalized)
    
    if len(local_addresses) > 2:
        raise Exception(f"More than two IPv6 addresses found on interface {interface}.")
    
    # Step 2: Ping the link-local all nodes address to trigger neighbor discovery
    broadcast_address = 'ff02::1'  # Link-local all nodes address
    ping_result = await ping_broadcast(interface, broadcast_address)
    if not ping_result:
        print(f"Failed to ping broadcast address {broadcast_address} on interface {interface}.")
        return None

    # Step 3: Run `ip -6 neighbor show` to list discovered neighbors
    command = ['ip', '-6', 'neighbor', 'show', 'dev', interface]
    output = await run_subprocess(command, timeout=5)  # 5 seconds timeout for ip -6 neighbor
    
    if not output:
        print("No neighbor entries found.")
        return None
    
    # Extract link-local neighbors (addresses starting with 'fe80::')
    neighbors = []
    for line in output.splitlines():
        if 'fe80::' in line:  # Only look for link-local addresses
            parts = line.split()
            ipv6_address = parts[0]
            # Normalize the neighbor address by stripping the interface identifier
            ipv6_address_normalized = ipv6_address.split('%')[0]
            
            if ipv6_address_normalized not in local_addresses:
                neighbors.append((ipv6_address, 'neighbor'))
            else:
                neighbors.append((ipv6_address, 'local'))

    # Avoid duplicating local addresses
    for local_address in local_addresses:
        if local_address not in [item[0] for item in neighbors]:
            neighbors.append((local_address, 'local'))

    # Sort all addresses lexicographically and assign client/server based on order
    all_addresses = [item[0] for item in neighbors]
    all_addresses.sort()

    # Create a dict for easy lookup
    address_types = {item[0]: item[1] for item in neighbors}
    
    # Add 'client' or 'server' based on lexicographical order
    sorted_neighbors = []
    for address in all_addresses:
        address_type = address_types[address]
        # Assign "client" if the address comes before the local addresses lexicographically
        if address in local_addresses:
            sorted_neighbors.append((address, address_type, "server"))
        else:
            sorted_neighbors.append((address, address_type, "client"))

    return sorted_neighbors if sorted_neighbors else None

def main(interface: str):
    """Main function to fetch IPv6 neighbors on a given interface."""
    try:
        result = asyncio.run(get_ipv6_neighbors(interface))

        if result:
            print(f"IPv6 addresses on {interface}:")
            for ipv6_address, address_type, role in result:
                print(f"{address_type.capitalize()} ({role}): {ipv6_address}")
        else:
            print(f"No IPv6 addresses found on {interface}.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Specify the interface to query (e.g., 'eth0', 'en0', etc.)
    interface = 'en3'  # Replace with your interface name (e.g., 'eth0', 'en0', etc.)
    main(interface)
