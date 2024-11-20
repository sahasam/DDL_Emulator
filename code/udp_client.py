import asyncio

from protocol import ABPProtocol

async def main(remote_addr=('127.0.0.1',55555)):
    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_running_loop()

    transport, protocol = await loop.create_datagram_endpoint(
        lambda: ABPProtocol(is_alice=True),
        remote_addr=remote_addr)

    try:
        await protocol.on_con_lost
    finally:
        transport.close()

asyncio.run(main())
