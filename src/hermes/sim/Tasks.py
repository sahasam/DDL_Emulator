
import asyncio
import queue

from hermes.model.messages import PortCommand

async def periodic_status_update(thread_manager, period:float = 0.1) -> None:
    thread_manager.logger.info("Starting periodic status update task")
    try:
        while True:
            await asyncio.sleep(period)
            ports = thread_manager.get_ports()
            port_status = {}
            for port in ports.values():
                port_status[port.name] = port.get_snapshot()
            
            agent = thread_manager.get_agent()
            agent_snapshot = agent.get_snapshot()
            
            await thread_manager.get_websocket_server().send_updates(port_status, agent_snapshot)
    except asyncio.CancelledError:
        thread_manager.logger.info("Periodic status update task cancelled")
    except Exception as e:
        thread_manager.logger.error(f"Error in periodic_status_update: {str(e)}", exc_info=True)

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
    thread_manager.logger.info("Starting process_commands task")
    try:
        while True:
            if not command_queue.empty():
                command = command_queue.get()
                await execute_command(thread_manager, command)
            else:
                await asyncio.sleep(0.01)
    except Exception as e:
        thread_manager.logger.error(f"Error processing command: {str(e)}", exc_info=True)
    except asyncio.CancelledError: # close the task when the sim is stopped
        pass
