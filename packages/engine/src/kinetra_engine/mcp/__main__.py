"""`python -m kinetra_engine.mcp --project car.kinetra.json`: the core of one project with its MCP server on stdio (G-08).

The client (Claude Code: `claude mcp add kinetra -- uv run python -m kinetra_engine.mcp --project <file>`) starts this process.
It opens the project file (C-03), holds it in a `Hub` (C-05a), serves the document channel the Studio screen follows on
`ws://127.0.0.1:<port>` and answers MCP on stdin/stdout. stdout carries MCP messages only: anything else the process prints goes to
stderr, where the channel's address is logged too. Edits live in the hub; saving them is not this command's (the hub does not save).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from kinetra_core import open_project
from kinetra_engine.protocol import Hub

from .server import McpServer, serve_stdio

log = logging.getLogger("kinetra_engine.mcp")


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m kinetra_engine.mcp", description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, help="the project file to open (.kinetra.json, C-03)")
    parser.add_argument("--id", default="studio", help="the project id on the document channel (default: studio)")
    parser.add_argument("--port", type=int, default=0, help="port of the document channel on 127.0.0.1 (default: a free one)")
    parser.add_argument(
        "--allowed-origin",
        action="append",
        default=[],
        help="Origin header of a page that may follow the document (repeat); clients that send none are always allowed",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace, stdout_fd: int) -> None:
    hub = Hub({args.id: open_project(args.project).project})
    server = McpServer(hub, args.id)
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    out = os.fdopen(stdout_fd, "wb", buffering=0)
    transport, protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, out)
    writer = asyncio.StreamWriter(transport, protocol, None, loop)
    async with hub.serve("127.0.0.1", args.port, allowed_origins=[None, *args.allowed_origin]) as channel:
        port = channel.sockets[0].getsockname()[1]
        log.info("document channel ws://127.0.0.1:%d project %s", port, args.id)
        await serve_stdio(server, reader, writer)
    transport.close()


def main(argv: list[str] | None = None) -> None:
    args = _arguments(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="kinetra: %(message)s")
    # stdout is the MCP stream: keep its descriptor for the transport and send every stray print to stderr instead
    stdout_fd = os.dup(sys.stdout.fileno())
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    asyncio.run(_run(args, stdout_fd))


if __name__ == "__main__":
    main()
