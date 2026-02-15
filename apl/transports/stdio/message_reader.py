import asyncio
import json
import sys
from typing import AsyncIterator


async def create_stdin_reader() -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)
    return reader


async def read_json_lines(reader: asyncio.StreamReader) -> AsyncIterator[dict]:
    while True:
        line = await reader.readline()
        if not line:
            break
        yield json.loads(line.decode())
