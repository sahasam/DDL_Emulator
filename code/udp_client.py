import asyncio

from protocol import ABPProtocol

async def main(interface='local', remote_addr=('127.0.0.1',55555)):
    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    print( "*************************************")
    print( "* Starting Client")
    print(f"* target          {remote_addr}")
    print(f"* interface       {interface}")
    print(f"* protocol        AlternatingBit")
    print( "*************************************")
    loop = asyncio.get_running_loop()
    
    while True:
        try:
            transport, protocol_instance = await loop.create_datagram_endpoint(
                lambda: ABPProtocol(loop, is_client=True), remote_addr=remote_addr
            )
            await protocol_instance.client_disconnected
        finally:
            transport.close()
            print("Resetting connection")
            await asyncio.sleep(1)
        

if __name__ == "__main__":
    asyncio.run(main())
