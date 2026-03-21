# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""MCP server package — spec-compliant MCP server using the official SDK.

Runs as a standalone service on port 8001, separate from the core
FastAPI REST API (port 8000). Uses ``mcp.server.fastmcp.FastMCP``
with Streamable HTTP transport.
"""
