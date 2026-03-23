#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Launch Agent Framework DevUI for interactive agent debugging.

Registers SAP specialist agents from the Agent Framework for visual
debugging, tracing, and interactive testing via the DevUI web interface.
"""

from __future__ import annotations
import argparse
import os
import sys
from agent_framework.azure import AzureOpenAIChatClient
from agent_framework_devui import serve


def main() -> None:
    """Parse CLI args and launch DevUI."""
    parser = argparse.ArgumentParser(description="SAP Agent DevUI server")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--tracing", action="store_true", help="Enable OpenTelemetry tracing")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")

    if not endpoint or not deployment:
        print(
            "ERROR: Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT "
            "environment variables.",
            file=sys.stderr,
        )
        sys.exit(1)

    client_kwargs: dict = {"endpoint": endpoint, "deployment_name": deployment}
    if api_key:
        client_kwargs["api_key"] = api_key

    client = AzureOpenAIChatClient(**client_kwargs)

    triage = client.as_agent(
        name="Triage-Agent",
        description="Evidence collection, analysis, diagnostics.",
        instructions="You are the Triage specialist for SAP infrastructure on Azure.",
    )
    staf = client.as_agent(
        name="STAF-Agent",
        description="Test execution, job status and results.",
        instructions="You are the STAF specialist for SAP HA testing.",
    )
    ops = client.as_agent(
        name="Ops-Agent",
        description="Schedule CRUD, triggering, inspection.",
        instructions="You are the Operations specialist for SAP test scheduling.",
    )

    print(f"Starting DevUI on http://{args.host}:{args.port}")
    print("Registered agents: Triage-Agent, STAF-Agent, Ops-Agent")

    serve(
        entities=[triage, staf, ops],
        port=args.port,
        host=args.host,
        auto_open=not args.no_open,
        instrumentation_enabled=args.tracing,
    )


if __name__ == "__main__":
    main()
