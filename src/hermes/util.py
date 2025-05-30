import asyncio
from typing import Optional, List, Tuple

from hermes.model.types import IPV6_ADDR

async def run_subprocess(command: list, timeout: int = 10) -> str:
    """Runs a subprocess command asynchronously with a timeout."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        
        if proc.returncode != 0:
            # Check if the error message matches the specific error you want to catch
            error_message = stderr.decode().strip()
            if "Can't assign requested address" in error_message:
                # Handle the specific error, maybe log it or just return a fallback value
                return ""  # or return a fallback value, depending on your use case
            else:
                # Raise for other types of errors
                raise Exception(f"Command failed with error: {error_message}")
        
        return stdout.decode()
    except asyncio.TimeoutError:
        print(f"Command timed out after {timeout} seconds")
        return ""
    except asyncio.CancelledError:
        print("Command failed...")
        return ""
    except Exception as e:
        # print(f"Error running subprocess: {e}")
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
    if len(local_addresses) == 0:
        return None
    
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
        return None
    
    # Extract link-local neighbors (addresses starting with 'fe80::')
    neighbors = []
    for line in output.splitlines():
        if 'fe80::' in line:  # Only look for link-local addresses
            parts = line.split()
            ipv6_address = parts[0]

            # Skip non-REACHABLE, non-PERMANENT entries
            valid_states = ['REACHABLE','PERMANENT']
            if not any(state in line for state in valid_states):
                print(f"Skipping neighbor {ipv6_address} - not in valid state")
                continue
            
            if ipv6_address not in local_addresses:
                neighbors.append((ipv6_address, 'neighbor'))
            else:
                neighbors.append((ipv6_address, 'local'))
    
    # Determine client/server roles based on address comparison
    sorted_neighbors = []
    if len(neighbors) != 2:
        return None
    
    if neighbors[0][1] == neighbors[1][1]:
        print(f"Error: Both neighbors are {neighbors[0][1]}")
        print(f"Neighbors: {neighbors}")
        print(f"Local addresses: {local_addresses}")
        print(f"ip -6 neighbor show dev {interface}  -- Output: {output}")
        return None
        
    addr1, type1 = neighbors[0]
    addr2, type2 = neighbors[1]
    
    sorted_neighbors.append((addr1, type1, "client" if addr1 < addr2 else "server"))
    sorted_neighbors.append((addr2, type2, "client" if addr2 < addr1 else "server"))

    return sorted_neighbors if sorted_neighbors else None
    

if __name__ == "__main__":
    # Specify the interface to query (e.g., 'eth0', 'en0', etc.)
    interface = 'en4'  # Replace with your interface name (e.g., 'eth0', 'en0', etc.)
    
    while True:
        try:
            result = asyncio.run(get_ipv6_neighbors(interface))

            if result:
                print(f"IPv6 addresses on {interface}:")
                for ipv6_address, address_type, role in result:
                    print(f"{address_type.capitalize()} ({role}): {ipv6_address}")
            else:
                print(f"No IPv6 addresses found on {interface}. Retrying...")
        
        except Exception as e:
            print(f"Error: {e}")
            # Optionally, wait or handle retries in case of an error
            print("Retrying after an error...")

        # Add a sleep here to avoid tight looping and unnecessary CPU usage
        asyncio.run(asyncio.sleep(1))  # Wait for 2 seconds before retrying (you can adjust the time)

