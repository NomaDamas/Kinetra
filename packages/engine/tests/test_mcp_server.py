"""G-08: the command layer as an MCP server. The G-02a edit tools over MCP, the same checks as the agent, published through
`Hub.publish` as `origin: "mcp"`, seen by every subscriber of the document channel (the Studio screen).

    uv run pytest packages/engine -q -k mcp

No model is called: the MCP client here is the test, speaking JSON-RPC as Claude Code does (MCP 2025-11-25).
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter
from websockets.asyncio.client import connect

from kinetra_core import PLANET_CONSTANT_NAMES, PROTOCOL_VERSION, CommandBatch, Origin, Project, ServerMessage, save_project
from kinetra_core.validator import VERDICT_FIELD_NAMES
from kinetra_engine.agent import TOOL_NAMES, EditTools, HubEditTools, specs
from kinetra_engine.mcp import MAX_LINE_BYTES, PROTOCOL_VERSIONS, McpServer, serve_stdio
from kinetra_engine.protocol import Hub

SERVER = TypeAdapter(ServerMessage)
NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)
GROUND = {"type": "on_ground"}
PLATE = {"part": "plate", "place": GROUND, "material": "al6061-t6"}


def empty():
    return Project.model_validate({"world": {"planet": "earth"}})


@pytest.fixture(scope="module")
def tools():
    return EditTools(clock=lambda: NOW)


def rpc(ident, method, params=None):
    message = {"jsonrpc": "2.0", "id": ident, "method": method}
    if params is not None:
        message["params"] = params
    return message


def started(hub, tools, project="desk"):
    server = McpServer(hub, project, tools=tools)
    reply = server.handle(rpc(0, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}))
    assert "result" in reply
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    return server


def call(server, ident, name, arguments):
    reply = server.handle(rpc(ident, "tools/call", {"name": name, "arguments": arguments}))
    assert reply["id"] == ident and "result" in reply, reply
    return reply["result"]


# --- lifecycle --------------------------------------------------------------------------------------------------------------


def test_mcp_initialize_agrees_on_a_revision_and_offers_tools_only(tools):
    server = McpServer(Hub({"desk": empty()}), "desk", tools=tools)
    reply = server.handle(rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "c", "version": "1"}}))
    result = reply["result"]
    assert reply["id"] == 1 and result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "kinetra" and "desk" in result["instructions"]
    other = McpServer(Hub({"desk": empty()}), "desk", tools=tools)
    assert other.handle(rpc(1, "initialize", {"protocolVersion": "2024-11-05"}))["result"]["protocolVersion"] == PROTOCOL_VERSIONS[0] == "2025-11-25"


def test_mcp_before_initialize_only_ping_is_answered(tools):
    server = McpServer(Hub({"desk": empty()}), "desk", tools=tools)
    assert server.handle(rpc(1, "ping")) == {"jsonrpc": "2.0", "id": 1, "result": {}}
    for method in ("tools/list", "tools/call"):
        reply = server.handle(rpc(2, method, {"name": "add_part", "arguments": PLATE}))
        assert reply["error"]["code"] == -32600 and "initialize" in reply["error"]["message"]
    assert server.protocol_version is None


# --- the tools are G-02a's ----------------------------------------------------------------------------------------------------


def test_mcp_tools_list_is_the_edit_tools_schema_and_nothing_else(tools):
    listed = started(Hub({"desk": empty()}), tools).handle(rpc(1, "tools/list"))["result"]["tools"]
    assert tuple(t["name"] for t in listed) == TOOL_NAMES
    for tool, spec in zip(listed, specs(), strict=True):
        assert tool == {"name": spec["function"]["name"], "description": spec["function"]["description"], "inputSchema": spec["function"]["parameters"]}
        assert tool["inputSchema"]["type"] == "object"

    def names(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties":
                    yield from value
                yield from names(value)
        elif isinstance(node, list):
            for item in node:
                yield from names(item)

    # out of scope (G-08): changing a verdict through MCP; nor can a call carry a planet constant
    assert not (set(PLANET_CONSTANT_NAMES) | set(VERDICT_FIELD_NAMES)) & set(names(listed))
    assert not any("verdict" in t["name"] for t in listed)


def test_mcp_add_part_is_published_as_mcp_and_the_screen_sees_it(tools):
    async def main():
        hub = Hub({"desk": empty()})
        async with hub.serve("127.0.0.1", 0, allowed_origins=[None]) as channel:
            async with connect(f"ws://127.0.0.1:{channel.sockets[0].getsockname()[1]}") as screen:
                await screen.send(json.dumps({"type": "hello", "protocol": PROTOCOL_VERSION}))
                await screen.recv()
                await screen.send(json.dumps({"type": "subscribe", "project": "desk"}))
                snapshot = SERVER.validate_json(await asyncio.wait_for(screen.recv(), 5))
                assert snapshot.type == "snapshot" and snapshot.revision == 0

                result = call(started(hub, tools), 7, "add_part", PLATE)
                assert result["isError"] is False
                out = result["structuredContent"]
                assert out["ok"] and out["revision"] == 1 and out["effects"]["added"]["instances"] == ["plate-1"]
                assert json.loads(result["content"][0]["text"]) == out and result["content"][0]["type"] == "text"

                applied = SERVER.validate_json(await asyncio.wait_for(screen.recv(), 5))
                assert applied.type == "applied" and applied.origin is Origin.MCP and applied.revision == 1
                assert [i.id for i in applied.changes.instances] == ["plate-1"]
                doc = hub.documents["desk"]
                assert doc.history.entries[0].origin is Origin.MCP and isinstance(doc.history.entries[0].command, CommandBatch)

    asyncio.run(main())


CALLS = [
    ("add_part", PLATE),
    ("add_part", PLATE),  # the second plate overlaps the first: the validator refuses (overlap)
    ("add_part", {**PLATE, "gravity": 3.7}),  # a planet constant: no such field
    ("add_part", {**PLATE, "verdict": "valid"}),  # a verdict: no such field
    ("add_part", {"part": "no-such-part", "place": GROUND}),
    ("add_part", {"part": "plate", "place": {"type": "on_ground", "x": "1"}}),  # a string for a number
    ("set_parameter", {"instance": "plate-1", "name": "thickness", "value": 0.004}),
    ("set_parameter", {"instance": "plate-1", "name": "thickness", "value": -1.0}),  # out of the part's range
    ("set_material", {"instance": "plate-1", "material": "unobtainium"}),
    ("remove_part", {"instance": "plate-9"}),
    ("remove_part", {"instance": "plate-1"}),
]


def test_mcp_calls_pass_the_same_checks_as_the_agent_and_a_refusal_changes_nothing(tools):
    agent_hub, mcp_hub = Hub({"desk": empty()}), Hub({"desk": empty()})
    agent, server = HubEditTools(agent_hub, "desk", tools=tools), started(mcp_hub, tools)
    refused = 0
    for n, (name, arguments) in enumerate(CALLS):
        expected = agent.call(name, arguments).to_json()
        before = mcp_hub.documents["desk"].revision
        result = call(server, n, name, arguments)
        assert result["structuredContent"] == expected, (name, arguments)
        assert result["isError"] is (not expected["ok"])
        assert mcp_hub.documents["desk"].project == agent_hub.documents["desk"].project
        if not expected["ok"]:
            refused += 1
            assert expected["reasons"] and mcp_hub.documents["desk"].revision == before
    assert refused == 8
    origins = {e.origin for e in mcp_hub.documents["desk"].history.entries}
    assert origins == {Origin.MCP} and {e.origin for e in agent_hub.documents["desk"].history.entries} == {Origin.AGENT}


def test_mcp_protocol_errors_are_json_rpc_errors(tools):
    server = started(Hub({"desk": empty()}), tools)

    def code(message):
        return server.handle(message)["error"]["code"]

    assert code(rpc(1, "tools/call", {"name": "no_such_tool", "arguments": {}})) == -32602
    assert code(rpc(2, "tools/call", {"name": "add_part", "arguments": "{}"})) == -32602
    assert code(rpc(3, "tools/call", {"arguments": {}})) == -32602
    assert code(rpc(4, "resources/list")) == -32601
    assert code(rpc(5, "tools/list", [1])) == -32602
    assert code([rpc(6, "ping")]) == -32600
    assert code({"jsonrpc": "1.0", "id": 7, "method": "ping"}) == -32600
    assert code({"jsonrpc": "2.0", "id": True, "method": "ping"}) == -32600
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}) is None
    assert server.handle({"jsonrpc": "2.0", "id": 8, "result": {}}) is None
    assert server.handle(rpc("s", "ping"))["id"] == "s"
    assert server.handle(rpc(9, "tools/call", {"name": "add_part", "arguments": PLATE}))["result"]["isError"] is False


# --- stdio transport --------------------------------------------------------------------------------------------------------


class _Sink:
    def __init__(self):
        self.data = bytearray()

    def write(self, data):
        self.data += data

    async def drain(self):
        pass


def test_mcp_stdio_is_one_message_per_line(tools):
    async def main():
        server = McpServer(Hub({"desk": empty()}), "desk", tools=tools)
        reader = asyncio.StreamReader()
        lines = [
            json.dumps(rpc(1, "initialize", {"protocolVersion": "2025-11-25"})),
            "",
            "{not json",
            "x" * (MAX_LINE_BYTES + 10),  # longer than allowed: discarded whole, one error, the next line is read
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps(rpc(2, "tools/call", {"name": "add_part", "arguments": {**PLATE, "source": "line one\nline two"}})),
        ]
        reader.feed_data(("\n".join(lines) + "\n").encode())
        reader.feed_eof()
        sink = _Sink()
        await serve_stdio(server, reader, sink)
        return [json.loads(line) for line in bytes(sink.data).decode().splitlines()]

    replies = asyncio.run(main())
    assert [r.get("id") for r in replies] == [1, None, None, 2]
    assert replies[1]["error"]["code"] == -32700 and replies[2]["error"]["code"] == -32600
    assert replies[3]["result"]["structuredContent"]["ok"]


def test_mcp_a_lone_surrogate_in_a_message_never_stops_the_server(tools):
    """JSON may spell a lone surrogate (`"\\ud800"`), which UTF-8 cannot encode. A request id is echoed back verbatim, so a reply
    can carry one; it must still go out (escaped), and the server must go on reading."""

    async def main():
        server = McpServer(Hub({"desk": empty()}), "desk", tools=tools)
        reader = asyncio.StreamReader()
        lines = [
            r'{"jsonrpc":"2.0","id":"\ud800","method":"initialize","params":{"protocolVersion":"2025-11-25"}}',
            r'{"jsonrpc":"2.0","id":"\udfff","method":"tools/call","params":{"name":"\ud800","arguments":{}}}',
            r'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"remove_part","arguments":{"instance":"\ud800"}}}',
            r'{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"add_part","arguments":{"part":"plate","place":{"type":"on_ground"},"source":"\ud83d"}}}',
            json.dumps(rpc(5, "tools/call", {"name": "add_part", "arguments": PLATE})),
        ]
        reader.feed_data(("\n".join(lines) + "\n").encode())
        reader.feed_eof()
        sink = _Sink()
        await serve_stdio(server, reader, sink)
        return bytes(sink.data)

    data = asyncio.run(main())
    assert data.isascii()
    replies = [json.loads(line) for line in data.decode("utf-8").splitlines()]
    assert [r["id"] for r in replies] == ["\ud800", "\udfff", 3, 4, 5]
    assert replies[0]["result"]["protocolVersion"] == "2025-11-25" and replies[1]["error"]["code"] == -32602
    assert replies[2]["result"]["isError"] and replies[3]["result"]["isError"]  # a lone surrogate is not a valid string argument
    assert replies[4]["result"]["structuredContent"]["ok"]


def test_mcp_the_command_runs_the_core_on_stdio_and_the_screen_follows(tmp_path):
    path = tmp_path / "desk.kinetra.json"
    save_project(empty(), path)

    async def main():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "kinetra_engine.mcp", "--project", str(path), "--id", "desk",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        try:
            port = None
            while port is None:
                line = (await asyncio.wait_for(proc.stderr.readline(), 30)).decode()
                assert line, "the server ended before it opened the document channel"
                if m := re.search(r"ws://127\.0\.0\.1:(\d+) project desk", line):
                    port = int(m.group(1))
            async with connect(f"ws://127.0.0.1:{port}") as screen:
                await screen.send(json.dumps({"type": "hello", "protocol": PROTOCOL_VERSION}))
                await screen.recv()
                await screen.send(json.dumps({"type": "subscribe", "project": "desk"}))
                assert SERVER.validate_json(await asyncio.wait_for(screen.recv(), 5)).type == "snapshot"

                async def ask(message):
                    proc.stdin.write((json.dumps(message) + "\n").encode())
                    await proc.stdin.drain()
                    if "id" in message:
                        return json.loads(await asyncio.wait_for(proc.stdout.readline(), 30))

                init = await ask(rpc(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}))
                assert init["result"]["serverInfo"]["name"] == "kinetra"
                await ask({"jsonrpc": "2.0", "method": "notifications/initialized"})
                assert len((await ask(rpc(2, "tools/list")))["result"]["tools"]) == len(TOOL_NAMES)
                reply = await ask(rpc(3, "tools/call", {"name": "add_part", "arguments": PLATE}))
                assert reply["result"]["structuredContent"]["revision"] == 1
                applied = SERVER.validate_json(await asyncio.wait_for(screen.recv(), 5))
                assert applied.type == "applied" and applied.origin is Origin.MCP and [i.id for i in applied.changes.instances] == ["plate-1"]
            proc.stdin.close()
            assert await asyncio.wait_for(proc.stdout.read(), 30) == b""  # nothing but the three replies on stdout
            assert await asyncio.wait_for(proc.wait(), 30) == 0
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()

    asyncio.run(main())
