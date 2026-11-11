"""The command layer as an MCP server (G-08): the edit tools of G-02a, offered to an outside agent (Claude Code and the like)
over the Model Context Protocol, published into the document as `Origin.MCP`.

    server = McpServer(hub, "car")                   # one project of a `Hub` (C-05a)
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})   # one JSON-RPC message in, its reply out
    await serve_stdio(server, reader, writer)        # the stdio transport: one JSON-RPC message per line

Rules (`docs/architecture/mcp-server.md`):

- **The same tools, the same path.** `tools/list` is `edit_tools.specs()` as MCP tools (name, description, the argument schema as
  `inputSchema`), nothing added or left out. `tools/call` is `HubEditTools(hub, project_id, origin=Origin.MCP).call(name,
  arguments)`: the very call the in-app agent makes, so the argument schema, the `validate_command` check (C-02c) and the
  document's own check in `Hub.publish` are the same ones, and every subscriber (the Studio screen) gets the `applied` with
  `origin: "mcp"`. There is no other way in: the server holds no project and edits nothing itself.
- **No verdicts, no constants.** The tools have no field for a planet constant or a verdict (G-02a); the server adds no tool, so a
  verdict cannot be changed through MCP (out of scope of G-08, and refused by the closed `Command` union anyway).
- **A refused call is a tool result, not a protocol error.** The validator's reasons go back as `isError: true` with the
  `ToolResult.to_json()` both as text and as `structuredContent`, so the calling model can read why and try again. An unknown tool,
  arguments that are not an object, and a malformed message are JSON-RPC errors (MCP 2025-11-25, "Error Handling").
- **Local only.** The transport is stdio: the client starts this process and is its only peer; there is no listening socket for
  MCP. (The document channel the screen follows is `Hub.serve`, loopback by default, C-05a.)

Implemented by hand, not with the MCP Python SDK: the server needs four methods of one transport, and the SDK (`mcp` 2.3.0 on PyPI,
MIT) requires an HTTP and auth stack (starlette, uvicorn, httpx2, sse-starlette, python-multipart, pyjwt[crypto], opentelemetry-api,
jsonschema, anyio, ...) that the stdio tools do not use.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from importlib.metadata import version
from typing import Any

from kinetra_core import Origin
from kinetra_engine.agent import EditTools, HubEditTools, specs
from kinetra_engine.protocol import Hub

log = logging.getLogger(__name__)

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18")
"""MCP revisions this server speaks, newest first. A client asking for another one is answered with the newest (MCP
"Version Negotiation"); it decides whether to go on. Older revisions are left out on purpose: 2025-03-26 allowed JSON-RPC batches,
which are refused here."""

MAX_LINE_BYTES = 2**20
"""Longest message line read from stdin (bytes), the same bound as the document channel's `MAX_MESSAGE_BYTES` (C-05a). A longer line
is discarded whole and answered with an `invalid request` error without an id."""

SERVER_NAME = "kinetra"

# JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

_CHUNK = 65536


def _error(ident: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}


def _result(ident: Any, result: Mapping[str, Any]) -> dict:
    return {"jsonrpc": "2.0", "id": ident, "result": dict(result)}


def _is_id(value: Any) -> bool:
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


class McpServer:
    """The MCP server of one project of a `Hub`. Transport-free: `handle` takes one decoded JSON-RPC message and returns the reply
    (or `None` for a notification or a response). Call it from the event loop that runs the hub (`Hub.publish` queues on it)."""

    def __init__(self, hub: Hub, project_id: str, *, tools: EditTools | None = None):
        self._project_id = project_id
        self._tools = HubEditTools(hub, project_id, origin=Origin.MCP, tools=tools)
        self._listing = [
            {"name": spec["function"]["name"], "description": spec["function"]["description"], "inputSchema": spec["function"]["parameters"]}
            for spec in specs()
        ]
        self._names = frozenset(tool["name"] for tool in self._listing)
        self.protocol_version: str | None = None
        """The revision agreed in `initialize`; `None` before it."""

    def handle(self, message: Any) -> dict | None:
        """Answer one JSON-RPC message. Never raises: a failure inside a method is an `internal error` reply."""
        if isinstance(message, list):
            return _error(None, INVALID_REQUEST, "JSON-RPC batches are not supported (MCP 2025-06-18 and later)")
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, INVALID_REQUEST, "not a JSON-RPC 2.0 message")
        method = message.get("method")
        if method is None:
            return None  # a response to a request of ours; this server sends none
        has_id = "id" in message
        ident = message.get("id")
        if not isinstance(method, str) or (has_id and not _is_id(ident)):
            return _error(ident if _is_id(ident) else None, INVALID_REQUEST, "a request needs a string method and a string or integer id")
        params = message.get("params", {})
        if not has_id:
            return None  # notifications: initialized, cancelled, ...: nothing to answer, nothing to do
        if not isinstance(params, dict):
            return _error(ident, INVALID_PARAMS, "params must be an object")
        try:
            return self._request(ident, method, params)
        except Exception:
            log.exception("mcp: internal error in %s", method)
            return _error(ident, INTERNAL_ERROR, "internal error")

    def _request(self, ident: Any, method: str, params: dict) -> dict:
        if method == "ping":
            return _result(ident, {})
        if method == "initialize":
            return self._initialize(ident, params)
        if self.protocol_version is None:
            return _error(ident, INVALID_REQUEST, "the session is not initialized; send initialize first")
        if method == "tools/list":
            return _result(ident, {"tools": self._listing})
        if method == "tools/call":
            return self._call(ident, params)
        return _error(ident, METHOD_NOT_FOUND, f"method {method[:64]!r} is not served")

    def _initialize(self, ident: Any, params: dict) -> dict:
        asked = params.get("protocolVersion")
        self.protocol_version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _result(
            ident,
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": version("kinetra-engine")},
                "instructions": (
                    f"Edit the Kinetra Studio project {self._project_id!r}. Every tool call becomes one command checked by the "
                    "project's validator and shown on the Studio screen at once; a refused call changes nothing and says why. "
                    "Parts are placed by snap point (or on the ground), never by free coordinates. Verdicts and planet constants "
                    "cannot be changed here."
                ),
            },
        )

    def _call(self, ident: Any, params: dict) -> dict:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or name not in self._names:
            return _error(ident, INVALID_PARAMS, f"unknown tool {str(name)[:64]!r}; tools/list names the tools")
        if not isinstance(arguments, dict):
            return _error(ident, INVALID_PARAMS, "arguments must be an object")
        outcome = self._tools.call(name, arguments).to_json()
        return _result(
            ident,
            {
                "content": [{"type": "text", "text": json.dumps(outcome, ensure_ascii=False)}],
                "structuredContent": outcome,
                "isError": not outcome["ok"],
            },
        )


def _encode(reply: dict) -> bytes:
    # ASCII on the wire: json.dumps then escapes every control character (the line never holds a newline of its own, stdio
    # framing) and every non-ASCII one, a lone surrogate included (`"\ud800"` from a JSON string echoed back in a reason),
    # which UTF-8 cannot encode; the line is then valid UTF-8 whatever text a reply carries
    return json.dumps(reply, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"


async def serve_stdio(server: McpServer, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Run the stdio transport until `reader` ends: one UTF-8 JSON-RPC message per line in, one per line out (MCP "stdio").
    Only MCP messages are written to `writer`."""
    buffer = bytearray()
    discarding = False
    while True:
        chunk = await reader.read(_CHUNK)
        if not chunk:
            break
        buffer += chunk
        while True:
            end = buffer.find(b"\n")
            if end < 0:
                if len(buffer) > MAX_LINE_BYTES:
                    if not discarding:
                        writer.write(_encode(_error(None, INVALID_REQUEST, f"message longer than {MAX_LINE_BYTES} bytes")))
                    discarding = True
                    buffer.clear()
                break
            line = bytes(buffer[:end])
            del buffer[: end + 1]
            if discarding:  # the tail of an overlong line
                discarding = False
                continue
            reply = _answer(server, line)
            if reply is not None:
                writer.write(_encode(reply))
        await writer.drain()


def _answer(server: McpServer, line: bytes) -> dict | None:
    if not line.strip():
        return None
    if len(line) > MAX_LINE_BYTES:
        return _error(None, INVALID_REQUEST, f"message longer than {MAX_LINE_BYTES} bytes")
    try:
        message = json.loads(line)
    except (ValueError, RecursionError):
        return _error(None, PARSE_ERROR, "the line is not UTF-8 JSON")
    return server.handle(message)
