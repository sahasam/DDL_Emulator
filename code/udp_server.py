import asyncio
from protocol import ABPProtocol

async def main(interface, local_addr=('127.0.0.1', 55555)):
    print( "*************************************")
    print( "* Starting Server")
    print(f"* listening       {local_addr}")
    print(f"* interface       {interface}")
    print(f"* protocol        AlternatingBit")
    print( "*************************************")
    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_running_loop()

    # One protocol instance will be created to serve all
    # client requests.
    protocol = ABPProtocol(loop, is_client=False)

    while True:
        try:
            transport, protocol_instance = await asyncio.wait_for(
                loop.create_datagram_endpoint(
                    lambda: protocol, local_addr=local_addr
                ),
                timeout=1
            )
            await protocol_instance.on_con_lost
        except Exception as e:
            print(f"Error during connection: {e}")
        finally:
            transport.close()
            print("Reconnecting...")
            await asyncio.sleep(1)
        



if __name__ == "__main__":
    asyncio.run(main())