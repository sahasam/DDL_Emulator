import asyncio
from ddl.protocol import ABPProtocol

async def main(interface, logger, local_addr=('127.0.0.1', 55555)):
    print( "*************************************")
    print( "* Starting Server")
    print(f"* listening       {local_addr}")
    print(f"* interface       {interface}")
    print(f"* protocol        AlternatingBit")
    print( "*************************************")
    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_running_loop()

    while True:
        try:
            transport, protocol_instance = await loop.create_datagram_endpoint(
                lambda: ABPProtocol(logger),
                local_addr=local_addr
            )
            await protocol_instance.disconnected_future
        finally:
            transport.close()
            print("Reconnecting...")
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())