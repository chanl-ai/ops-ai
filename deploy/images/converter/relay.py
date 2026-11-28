"""A TCP relay for the development converter (make converter-up): the converter runs on an internal Docker network
with no route out, and this relay, on that network and the host's, is the one way in. It forwards bytes and opens
nothing itself. Standard library only.

    python relay.py <listen port> <converter host> <converter port>
"""

from __future__ import annotations

import asyncio
import sys


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


async def main(listen: int, host: str, port: int) -> None:
    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            up_reader, up_writer = await asyncio.open_connection(host, port)
        except OSError:
            writer.close()
            return
        await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer), return_exceptions=True)

    server = await asyncio.start_server(serve, "0.0.0.0", listen)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]), sys.argv[2], int(sys.argv[3])))
