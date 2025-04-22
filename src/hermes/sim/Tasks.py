
import asyncio
import queue

from hermes.model.messages import PortCommand

async def periodic_status_update(thread_manager, period:float = 0.1) -> None:
    """Periodically update the status of the simulation"""
    try:
        while True:
            await asyncio.sleep(period)
            ports = thread_manager.get_ports()
        port_status = {}
        for port in ports.values():
            port_status[port.name] = port.get_status()
        
        thread_manager.get_websocket_server().broadcast_status(port_status)
    except asyncio.CancelledError:
        thread_manager.get_logger().info("Periodic status update task cancelled")
    except Exception as e:
        thread_manager.get_logger().error(f"Error in periodic_status_update: {str(e)}", exc_info=True)

async def execute_command(thread_manager,command: PortCommand) -> bool:
    """Execute a command on a specific port"""
    port = thread_manager.get_ports().get(command.port_name)
    if not port:
        return False
        
    actions = {
        'DROP': port.drop_packet,
        'CONNECT': lambda: port.set_disconnected(False),
        'DISCONNECT': lambda: port.set_disconnected(True)
    }
    
    if action := actions.get(command.action):
        await action()
        return True
    return False

async def process_commands(thread_manager, command_queue: queue.Queue) -> None:
    """Process commands from the command queue"""
    while True:
        try:
            command = command_queue.get() # Blocking call
            await execute_command(thread_manager, command)
        except Exception as e:
            print(f"Error processing command: {e}")
        except asyncio.CancelledError: # close the task when the sim is stopped
            break
