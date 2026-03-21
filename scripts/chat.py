#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Interactive CLI for the SAP Agent chat — tests the full stack.

Requires the API server (port 8000) and MCP server (port 8001)
to be running.  Set ``STAF_API_URL`` to override the default.

Usage::

    python scripts/chat.py                          # new conversation
    python scripts/chat.py --workspace MY_WORKSPACE
    python scripts/chat.py --conversation <id>      # resume
    python scripts/chat.py --stream                 # enable SSE streaming
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_API = "http://localhost:8000"


def _api(base: str, method: str, path: str, body: dict | None = None) -> dict:
    """Make an HTTP request to the STAF API and return parsed JSON."""
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    with urlopen(req, timeout=120) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def _stream(base: str, path: str, body: dict) -> None:
    """Stream SSE events and print tokens as they arrive."""
    url = f"{base}{path}"
    data = json.dumps(body).encode()
    req = Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")
    with urlopen(req, timeout=300) as resp:  # noqa: S310
        buffer = ""
        for raw_line in resp:
            line = raw_line.decode()
            buffer += line
            if line == "\n" and buffer.strip():
                _handle_sse_block(buffer)
                buffer = ""
        if buffer.strip():
            _handle_sse_block(buffer)
    print()


def _handle_sse_block(block: str) -> None:
    """Parse and display one SSE event block."""
    event_type = ""
    data_str = ""
    for line in block.strip().splitlines():
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_str = line[len("data:"):].strip()

    if not data_str:
        return
    try:
        payload = json.loads(data_str)
    except json.JSONDecodeError:
        return

    if event_type == "token":
        text = payload.get("text") or payload.get("content", "")
        print(text, end="", flush=True)
    elif event_type == "done":
        text = payload.get("text") or payload.get("content", "")
        if text:
            print(f"\n{text}")
    elif event_type == "error":
        print(f"\n[ERROR] {payload.get('message', payload)}", file=sys.stderr)


def _create_conversation(base: str, workspace_id: str) -> str:
    """Create a new conversation and return its ID."""
    result = _api(base, "POST", "/api/v1/chat", {"workspace_id": workspace_id})
    conv_id = result.get("id", result.get("conversation_id", ""))
    title = result.get("title", "New conversation")
    print(f"Created conversation: {conv_id}  ({title})")
    return conv_id


def _send_message(base: str, conv_id: str, message: str, stream: bool) -> None:
    """Send a user message and display the response."""
    path = f"/api/v1/chat/{conv_id}/messages"
    body = {"message": message}
    if stream:
        _stream(base, f"{path}/stream", body)
    else:
        result = _api(base, "POST", path, body)
        content = result.get("content", json.dumps(result, indent=2))
        print(f"\nAssistant: {content}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive CLI for the SAP Agent chat",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API,
        help=f"STAF API base URL (default: {DEFAULT_API})",
    )
    parser.add_argument(
        "--workspace",
        default="SYSTEM",
        help="Workspace ID for a new conversation (default: SYSTEM)",
    )
    parser.add_argument(
        "--conversation",
        default="",
        help="Resume an existing conversation by ID",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Use SSE streaming for responses",
    )
    args = parser.parse_args()

    base = args.api_url.rstrip("/")

    # Verify connectivity
    try:
        _api(base, "GET", "/healthz")
    except (URLError, ConnectionError) as exc:
        print(f"Cannot reach API at {base}/healthz: {exc}", file=sys.stderr)
        print("Start the API server first (port 8000) and MCP server (port 8001).")
        sys.exit(1)

    # Create or resume conversation
    conv_id = args.conversation
    if not conv_id:
        try:
            conv_id = _create_conversation(base, args.workspace)
        except HTTPError as exc:
            print(f"Failed to create conversation: {exc}", file=sys.stderr)
            sys.exit(1)

    print(f"Conversation: {conv_id}")
    print("Type your message (Ctrl+D or 'exit' to quit).\n")

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                break
            if not user_input or user_input.lower() in ("exit", "quit"):
                break
            try:
                _send_message(base, conv_id, user_input, args.stream)
            except HTTPError as exc:
                body = exc.read().decode() if hasattr(exc, "read") else ""
                print(f"\n[API Error {exc.code}] {body}", file=sys.stderr)
            except URLError as exc:
                print(f"\n[Connection Error] {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        pass

    print("\nGoodbye.")


if __name__ == "__main__":
    main()
