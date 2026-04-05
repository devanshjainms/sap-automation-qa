#!/usr/bin/env python3
"""
Test the agent with 10 vague human-like prompts via the Chat API.

For each prompt:
1. Creates a new conversation
2. Sends the prompt via SSE streaming endpoint
3. Records: tools called, evidence count, response length, time
4. Prints a summary table

Usage:
    python scripts/test_prompts.py [--base-url http://localhost:8000]
"""

import argparse
import json
import re
import sys
import time
import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
TIMEOUT = 300  # seconds per prompt

PROMPTS = [
    # 1. Simple info request — no investigation needed
    "Show me the configuration files in workspace x03",
    # 2. Greeting — should be conversational only
    "Hey, what can you do?",
    # 3. Ambiguous workspace reference
    "Is everything ok with the production system?",
    # 4. Vague status check
    "Check if things are running fine",
    # 5. Non-SAP question
    "What's the weather like today?",
    # 6. Partial workspace name
    "Show me logs for R11",
    # 7. Multi-intent (list + status)
    "List all workspaces and tell me which ones have issues",
    # 8. Past tense — asking about history, not live triage
    "What tests ran last week?",
    # 9. Single word
    "Help",
    # 10. Typo / broken grammar
    "hana databse not workng plz fix",
    # 11. Overly polite — should be simple
    "Hi there, could you please kindly check the status of S11 for me when you get a chance?",
    # 12. Negation — asking NOT to do something
    "Don't run any tests, just show me what workspaces exist",
    # 13. Follow-up style (but first message)
    "What about the ASCS cluster?",
    # 14. Abbreviation heavy
    "chk hana hsr status x02",
    # 15. Completely off-topic
    "Write me a poem about clouds",
    # 16. Which workspace — ambiguous SID
    "Is R11 healthy?",
    # 17. Action request without target
    "Run a test",
    # 18. Compound — multiple unrelated asks
    "Show me workspaces, also what SAP notes apply to HANA 2.0, and schedule a test for tomorrow",
    # 19. Copy-pasted error message
    "ERROR: indexserver crashed on host 172.238.2.21 with signal 11",
    # 20. Just a SID
    "X00",
    # 21. Question about the tool itself
    "How does the triage system work?",
    # 22. Filesystem / storage concern
    "Is disk space ok on the database servers?",
    # 23. Passive aggressive
    "The cluster keeps failing and nobody is fixing it",
    # 24. Time-sensitive urgency
    "URGENT: production HANA down right now need help immediately",
    # 25. Explicit workspace + simple ask
    "What is the SID for workspace X01?",
]

# Known tool names to detect in content
_TOOL_NAMES = [
    "list_workspaces", "get_workspace", "collect_evidence", "run_command",
    "search_logs", "run_analysis", "get_triage_report", "query_knowledge",
    "run_staf_test", "list_jobs", "list_schedules",
    "record_investigation_outcome",
]
_TOOL_PATTERN = re.compile(r"\b(" + "|".join(_TOOL_NAMES) + r")\b")


def create_conversation(client, base_url, workspace_id="SYSTEM"):
    """Create a conversation and return its ID."""
    resp = client.post(f"{base_url}/api/v1/chat", json={"workspace_id": workspace_id})
    resp.raise_for_status()
    return resp.json()["id"]


def stream_message(client, base_url, conv_id, message):
    """Send a message via SSE streaming and capture events."""
    events = []
    with client.stream(
        "POST",
        f"{base_url}/api/v1/chat/{conv_id}/messages/stream",
        json={"message": message},
        timeout=TIMEOUT,
    ) as resp:
        current_event = None
        for line in resp.iter_lines():
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_str = line.split(":", 1)[1].strip()
                if data_str:
                    try:
                        events.append({"event": current_event, "data": json.loads(data_str)})
                    except json.JSONDecodeError:
                        events.append({"event": current_event, "data": data_str})
    return events


def get_conversation_detail(client, base_url, conv_id):
    """Get full conversation detail."""
    resp = client.get(f"{base_url}/api/v1/chat/{conv_id}")
    resp.raise_for_status()
    return resp.json()


def analyze(detail, sse_events):
    """Extract metrics from conversation detail and SSE events."""
    messages = detail.get("messages", [])

    # Get assistant content
    assistant_content = ""
    for m in messages:
        if m.get("role") == "assistant":
            assistant_content = m.get("content", "")

    # Extract tool calls from SSE events
    sse_tool_calls = []
    for ev in sse_events:
        etype = ev.get("event", "")
        if "tool" in etype.lower() or "activity" in etype.lower():
            data = ev.get("data", {})
            if isinstance(data, dict):
                name = data.get("name", data.get("tool", ""))
                if name:
                    sse_tool_calls.append(name)

    # Also detect tools mentioned in content (tool invocation text)
    content_tools = _TOOL_PATTERN.findall(assistant_content)

    # Count invocation phrases like "I'll use/call/run..."
    invocations = re.findall(
        r"I'll (?:use|call|run|fetch|list|check|search|collect|look)\b",
        assistant_content,
    )

    # Combine: prefer SSE if available, else fall back to content detection
    tool_calls = sse_tool_calls if sse_tool_calls else content_tools

    evidence_tools = [
        t for t in tool_calls if t in ("collect_evidence", "search_logs", "run_command")
    ]

    return {
        "total_tool_calls": len(tool_calls),
        "tool_invocations_in_text": len(invocations),
        "unique_tools": sorted(set(tool_calls)),
        "tool_sequence": tool_calls,
        "evidence_tools": len(evidence_tools),
        "sse_events": len(sse_events),
        "response_length": len(assistant_content),
        "response_preview": assistant_content[:200] if assistant_content else "(empty)",
        "content_tool_mentions": content_tools,
    }


def main():
    parser = argparse.ArgumentParser(description="Test agent with vague prompts")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--start", type=int, default=0, help="Start from prompt N (0-indexed)")
    parser.add_argument("--count", type=int, default=len(PROMPTS), help="Number of prompts")
    args = parser.parse_args()

    base_url = args.base_url
    results = []
    prompts_to_test = PROMPTS[args.start : args.start + args.count]

    with httpx.Client() as client:
        try:
            r = client.get(f"{base_url}/healthz", timeout=5)
            r.raise_for_status()
        except Exception as e:
            print(f"ERROR: API not reachable at {base_url}: {e}", file=sys.stderr)
            sys.exit(1)

        for i, prompt in enumerate(prompts_to_test, start=args.start + 1):
            print(f"\n{'='*70}")
            print(f"PROMPT {i}/{len(PROMPTS)}: {prompt}")
            print(f"{'='*70}")

            try:
                conv_id = create_conversation(client, base_url)
                print(f"  Conversation: {conv_id}")

                t0 = time.time()
                sse_events = stream_message(client, base_url, conv_id, prompt)
                elapsed = time.time() - t0
                print(f"  Response time: {elapsed:.1f}s")

                detail = get_conversation_detail(client, base_url, conv_id)
                analysis = analyze(detail, sse_events)
                analysis["prompt"] = prompt
                analysis["prompt_num"] = i
                analysis["conv_id"] = conv_id
                analysis["elapsed_s"] = round(elapsed, 1)
                results.append(analysis)

                print(f"  Tool calls: {analysis['total_tool_calls']}")
                print(f"  Tool invocation phrases: {analysis['tool_invocations_in_text']}")
                print(f"  Evidence tools: {analysis['evidence_tools']}")
                print(f"  Tools used: {analysis['unique_tools']}")
                print(f"  SSE events: {analysis['sse_events']}")
                print(f"  Response ({analysis['response_length']} chars): "
                      f"{analysis['response_preview'][:120]}...")

            except Exception as e:
                print(f"  ERROR: {e}")
                results.append({"prompt": prompt, "prompt_num": i, "error": str(e)})

    # Summary
    print(f"\n\n{'='*80}")
    print("SUMMARY TABLE")
    print(f"{'='*80}")
    header = f"{'#':<3} {'Tools':<6} {'Evid':<5} {'Invoc':<6} {'Time':<7} {'Len':<6} {'Prompt':<40} {'Tools Used'}"
    print(header)
    print("-" * 130)
    for r in results:
        if "error" in r:
            print(f"{r['prompt_num']:<3} {'ERR':<6} {'':<5} {'':<6} {'':<7} {'':<6} "
                  f"{r['prompt'][:40]:<40} {r['error'][:50]}")
        else:
            tools_str = ", ".join(r["unique_tools"])
            print(
                f"{r['prompt_num']:<3} "
                f"{r['total_tool_calls']:<6} "
                f"{r['evidence_tools']:<5} "
                f"{r['tool_invocations_in_text']:<6} "
                f"{r['elapsed_s']:<7} "
                f"{r['response_length']:<6} "
                f"{r['prompt'][:40]:<40} "
                f"{tools_str[:60]}"
            )

    out_path = "/tmp/prompt_test_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nRaw results saved to {out_path}")


if __name__ == "__main__":
    main()
