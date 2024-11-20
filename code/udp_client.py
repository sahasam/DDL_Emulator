import asyncio

from protocol import ABPProtocol

async def main(interface='local', remote_addr=('127.0.0.1',55555)):
    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    print( "*************************************")
    print( "* Starting Client                   *")
    print(f"* target          {remote_addr}     *")
    print(f"* interface       {interface}       *")
    print(f"* protocol        AlternatingBit    *")
    print( "*************************************")
    loop = asyncio.get_running_loop()

    transport, protocol = await loop.create_datagram_endpoint(
        lambda: ABPProtocol(is_alice=True),
        remote_addr=remote_addr)

    try:
        await protocol.on_con_lost
    finally:
        transport.close()

if __name__ == "__main__":
    asyncio.run(main())
