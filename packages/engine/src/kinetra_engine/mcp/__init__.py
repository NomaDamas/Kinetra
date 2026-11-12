"""The command layer as an MCP server (G-08): G-02a edits, G-02b queries and G-02c run/verdict requests over MCP stdio.
Edits are published as `Origin.MCP`; `python -m kinetra_engine.mcp` runs the server (`__main__.py`)."""

from .server import MAX_LINE_BYTES, PROTOCOL_VERSIONS, McpServer, serve_stdio

__all__ = ["MAX_LINE_BYTES", "PROTOCOL_VERSIONS", "McpServer", "serve_stdio"]
