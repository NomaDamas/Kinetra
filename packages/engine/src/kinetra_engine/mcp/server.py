"""The command layer as an MCP server (G-08): the edit tools of G-02a, queries of G-02b and run/verdict requests of G-02c,
offered to an outside agent (Claude Code and the like) over the Model Context Protocol. Edits are published as `Origin.MCP`.

    server = McpServer(hub, "car")                   # one project of a `Hub` (C-05a)
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})   # one JSON-RPC message in, its reply out
    await serve_stdio(server, reader, writer)        # the stdio transport: one JSON-RPC message per line

Rules (`docs/architecture/mcp-server.md`):

- **The same tools, the same path.** `tools/list` is `edit_tools.specs()`, `run_specs()` and `query_specs()` as MCP tools
  (name, description, the argument schema as `inputSchema`), nothing added or left out. Edit calls go through `HubEditTools`
  with `Origin.MCP`; queries go through `HubQueryTools.call`; run and verdict calls go through the same `RunTools.call` as
  the in-app agent. One `QueryTools` is shared by queries and run requests, so a terminal run stream is recorded for
  `rollout_summary`. The server holds no project and edits nothing itself.
- **No invented verdicts, no constants.** No tool has a field for changing a planet constant or verdict. A preview is labelled
  as not a verdict, and a core without J-01's judge explicitly refuses `request_verdict` instead of substituting a run.
- **A refused call is a tool result, not a protocol error.** The validator's reasons go back as `isError: true` with the
  tool result's `to_json()` both as text and as `structuredContent`, so the calling model can read why and try again. An unknown tool,
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
from kinetra_engine.agent import QUERY_TOOL_NAMES, RUN_TOOL_NAMES, EditTools, HubEditTools, HubQueryTools, Judge, QueryTools, RunTools, query_specs, run_specs, specs
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
    """The MCP server of one project of a `Hub`. Transport-free: handlers take one decoded JSON-RPC message and return its reply
    (or `None` for a notification or a response). Use `handle_async` on the event loop that runs the hub; it keeps edit calls on
    that loop (`Hub.publish` queues on it) and moves blocking run/verdict calls to a worker thread."""

    def __init__(
        self,
        hub: Hub,
        project_id: str,
        *,
        tools: EditTools | None = None,
        judge: Judge | None = None,
        queries: QueryTools | None = None,
    ):
        self._project_id = project_id
        self._tools = HubEditTools(hub, project_id, origin=Origin.MCP, tools=tools)
        self._query_tools = HubQueryTools(hub, project_id, tools=queries)
        self._run_tools = RunTools(hub, project_id, judge=judge, queries=self._query_tools.tools)
        self._listing = [
            {"name": spec["function"]["name"], "description": spec["function"]["description"], "inputSchema": spec["function"]["parameters"]}
            for spec in [*specs(), *run_specs(), *query_specs()]
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

    async def handle_async(self, message: Any) -> dict | None:
        """Answer on the event loop, moving run and judge work to a worker thread so Hub connections stay responsive."""
        if (
            isinstance(message, dict)
            and message.get("method") == "tools/call"
            and isinstance(message.get("params"), dict)
            and message["params"].get("name") in RUN_TOOL_NAMES
        ):
            return await asyncio.to_thread(self.handle, message)
        return self.handle(message)

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
                    f"Edit the Kinetra Studio project {self._project_id!r}. Every edit call becomes one command checked by the "
                    "project's validator and shown on the Studio screen at once; a refused call changes nothing and says why. "
                    "Parts are placed by snap point (or on the ground), never by free coordinates. Query tools read the current "
                    "project and recorded runs without publishing. A requested run is one preview, never a verdict; its summary "
                    "is queryable after it ends. Only the core's judge can answer a verdict request; a core without one refuses. "
                    "Verdicts and planet constants cannot be changed here."
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
        if name in RUN_TOOL_NAMES:
            selected = self._run_tools
        elif name in QUERY_TOOL_NAMES:
            selected = self._query_tools
        else:
            selected = self._tools
        outcome = selected.call(name, arguments).to_json()
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
            reply = await _answer(server, line)
            if reply is not None:
                writer.write(_encode(reply))
        await writer.drain()


async def _answer(server: McpServer, line: bytes) -> dict | None:
    if not line.strip():
        return None
    if len(line) > MAX_LINE_BYTES:
        return _error(None, INVALID_REQUEST, f"message longer than {MAX_LINE_BYTES} bytes")
    try:
        message = json.loads(line)
    except (ValueError, RecursionError):
        return _error(None, PARSE_ERROR, "the line is not UTF-8 JSON")
    return await server.handle_async(message)
