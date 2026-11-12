"""G-02b-f: read-only queries over MCP and automatic recording of real MCP-requested runs (#558)."""

from __future__ import annotations

import asyncio
import json

from kinetra_core import Project, RunKind
from kinetra_engine.agent import QUERY_TOOL_NAMES, EditTools, QueryTools, query_specs
from kinetra_engine.mcp import McpServer
from kinetra_engine.protocol import Hub
from kinetra_engine.run import PreviewRun

PLATE = {"part": "plate", "place": {"type": "on_ground"}, "material": "al6061-t6"}


def plate_project() -> Project:
    result = EditTools().run(Project.model_validate({"world": {"planet": "earth"}}), "add_part", PLATE)
    assert result.ok, result.reasons
    return result.project


def rpc(ident, method, params=None):
    message = {"jsonrpc": "2.0", "id": ident, "method": method}
    if params is not None:
        message["params"] = params
    return message


def started(hub: Hub, queries: QueryTools) -> McpServer:
    server = McpServer(hub, "desk", queries=queries)
    reply = server.handle(rpc(0, "initialize", {"protocolVersion": "2025-11-25"}))
    assert "result" in reply
    return server


def call(server: McpServer, ident, name: str, arguments: dict) -> dict:
    reply = server.handle(rpc(ident, "tools/call", {"name": name, "arguments": arguments}))
    assert "result" in reply, reply
    return reply["result"]


def state(hub: Hub):
    document = hub.documents["desk"]
    return document.project, document.revision, document.history, document.verdict


def test_mcp_tools_list_contains_the_query_specs_without_changing_them():
    listed = started(Hub({"desk": plate_project()}), QueryTools()).handle(rpc(1, "tools/list"))["result"]["tools"]
    expected = [
        {"name": spec["function"]["name"], "description": spec["function"]["description"], "inputSchema": spec["function"]["parameters"]}
        for spec in query_specs()
    ]
    assert listed[-len(expected):] == expected
    assert tuple(tool["name"] for tool in listed[-len(expected):]) == QUERY_TOOL_NAMES


def test_mcp_query_results_are_query_tools_results_and_publish_nothing():
    hub = Hub({"desk": plate_project()})
    queries = QueryTools()
    server = started(hub, queries)
    before = state(hub)
    for ident, name in enumerate(QUERY_TOOL_NAMES, 1):
        expected = queries.run(hub.documents["desk"].project, name, {}).to_json()
        result = call(server, ident, name, {})
        assert result["structuredContent"] == expected
        assert json.loads(result["content"][0]["text"]) == expected
        assert result["isError"] is (not expected["ok"])
    assert state(hub) == before


def test_mcp_a_requested_run_is_queryable_as_the_same_complete_stream():
    hub = Hub({"desk": plate_project()})
    queries = QueryTools()
    server = started(hub, queries)
    before = state(hub)

    async def request_run():
        reply = await server.handle_async(
            rpc(1, "tools/call", {"name": "request_run", "arguments": {"duration_s": 0.05, "seed": 3}})
        )
        assert "result" in reply, reply
        return reply["result"]["structuredContent"]

    run = asyncio.run(request_run())
    assert run["ok"]
    started_run = run["run"]["started"]
    direct = PreviewRun(
        hub.documents["desk"].project,
        run_id=started_run["run_id"],
        project_id="desk",
        revision=started_run["revision"],
        duration_s=0.05,
        seed=3,
        kind=RunKind.PREVIEW,
    )
    *frames, ended = list(direct)
    expected_store = QueryTools()
    expected_store.record(direct.started, frames, ended)
    expected = expected_store.run(hub.documents["desk"].project, "rollout_summary", {"run_id": started_run["run_id"]}).to_json()

    result = call(server, 2, "rollout_summary", {"run_id": started_run["run_id"]})
    assert expected["ok"]
    assert result["structuredContent"] == expected
    assert result["structuredContent"]["data"]["frames"] == len(frames)
    assert result["isError"] is False
    latest = call(server, 3, "rollout_summary", {})
    assert latest["structuredContent"] == expected
    assert state(hub) == before
