#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Launch Agent Framework DevUI backed by real SAP multi-agent workflow."""

from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from agent_framework_devui import DevServer
from src.agents.agent import SapAgentFactory
from src.core.services.mcp_config_loader import load_mcp_servers_config

logger = logging.getLogger(__name__)

STAF_MCP_URL = os.environ.get("STAF_MCP_URL", "http://localhost:8001")
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))


async def _build_factory() -> SapAgentFactory:
    """Create and connect the agent factory with MCP tools.

    :returns: Initialised factory with MCP connections.
    """
    mcp_config = load_mcp_servers_config()
    return await SapAgentFactory.create(
        mcp_url=STAF_MCP_URL.rstrip("/") + "/mcp",
        mcp_config=mcp_config,
        endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        deployment_name=os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
        api_key=os.environ.get("AZURE_OPENAI_API_KEY", "") or None,
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
    )


def main() -> None:
    """Parse CLI args and launch DevUI with real agents."""
    parser = argparse.ArgumentParser(description="SAP Agent DevUI server")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument(
        "--tracing",
        action="store_true",
        help="Enable OpenTelemetry tracing",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Don't auto-open browser",
    )
    args = parser.parse_args()

    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
    if not endpoint or not deployment:
        print(
            "ERROR: Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT "
            "environment variables.",
            file=sys.stderr,
        )
        sys.exit(1)

    factory = asyncio.run(_build_factory())
    agent = factory.create_agent()

    print(f"Starting DevUI on http://{args.host}:{args.port} " f"(tools: {factory.tool_counts})")

    server = DevServer(
        port=args.port,
        host=args.host,
        cors_origins=["*"],
        ui_enabled=True,
        mode="developer",
    )
    server.set_pending_entities([agent])

    app = server.create_app()

    import uvicorn

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
