import asyncio
from protocol import ABPProtocol

async def main(local_addr=('127.0.0.1', 55555)):
    print("Starting UDP server")
    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_running_loop()

    # One protocol instance will be created to serve all
    # client requests.
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: ABPProtocol(),
        local_addr=local_addr)

    try:
        await asyncio.sleep(3600)  # Serve for 1 hour.
    finally:
        transport.close()

if __name__ == "__main__":
    asyncio.run(main())