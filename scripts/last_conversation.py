#!/usr/bin/env python3
"""Fetch the last conversation and its messages from the SQLite DB as raw JSON.

Usage:
    sudo python3 scripts/last_conversation.py          # pretty JSON to stdout
    sudo python3 scripts/last_conversation.py --raw     # compact JSON (one line)
    sudo python3 scripts/last_conversation.py > log.log # save to file

Always fetches the most recently updated conversation.
"""

import json
import sqlite3
import sys

DB_PATH = "/var/lib/docker/volumes/deploy_sap-qa-data/_data/conversations.db"


def main() -> None:
    raw = "--raw" in sys.argv

    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        print(f"Cannot open DB (try with sudo): {exc}", file=sys.stderr)
        sys.exit(1)

    conn.row_factory = sqlite3.Row

    conv = conn.execute(
        "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    if not conv:
        print("{}")
        conn.close()
        return

    messages = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY timestamp",
        (conv["id"],),
    ).fetchall()

    def parse_json_field(val):
        if not val:
            return None
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val

    result = {**dict(conv)}
    result["triage_session_ids"] = parse_json_field(result.get("triage_session_ids"))
    result["metadata"] = parse_json_field(result.get("metadata"))
    result["messages"] = []
    for msg in messages:
        m = {**dict(msg)}
        m["metadata"] = parse_json_field(m.get("metadata"))
        result["messages"].append(m)

    indent = None if raw else 2
    json.dump(result, sys.stdout, indent=indent, ensure_ascii=False)
    print()
    conn.close()


if __name__ == "__main__":
    main()
