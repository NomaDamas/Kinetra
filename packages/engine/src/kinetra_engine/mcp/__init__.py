"""The command layer as an MCP server (G-08): the G-02a edit tools over MCP stdio, published as `Origin.MCP`. `server.py`;
`python -m kinetra_engine.mcp` runs it (`__main__.py`)."""

from .server import MAX_LINE_BYTES, PROTOCOL_VERSIONS, McpServer, serve_stdio

__all__ = ["MAX_LINE_BYTES", "PROTOCOL_VERSIONS", "McpServer", "serve_stdio"]
