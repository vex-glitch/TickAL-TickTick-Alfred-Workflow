#!/usr/bin/env python3
"""
add_list.py — Alfred Script Filter
Creates a new TickTick list (project).

Note: The TickTick Open API does not support folder assignment at creation time.
Lists are always created at root level — move to a folder manually in TickTick.
"""
import sys
import os
import json
import base64
import traceback

# ── Path setup ───────────────────────────────────────────────────────────────
try:
    SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
    WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
    SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
    sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
    sys.path.insert(0, SRC_DIR)
except Exception as e:
    print(json.dumps({"items": [{"title": "Path error", "subtitle": str(e), "valid": False}]}))
    sys.exit(0)

try:
    import alfred
except Exception as e:
    print(json.dumps({"items": [{"title": "Import error", "subtitle": str(e), "valid": False}]}))
    sys.exit(0)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""

    if query.startswith("addlist:"):
        query = ""

    try:
        name = ' '.join(query.split())

        if not name:
            items = [alfred.item(
                title="Type a list name…",
                subtitle="Create  Lists are created at root level",
                valid=False,
            )]
        else:
            payload = {"name": name}
            encoded = base64.b64encode(json.dumps(payload).encode()).decode()
            items = [alfred.item(
                title=f"Create list: {name}",
                subtitle="Create  Move to a folder in TickTick afterwards",
                arg=f"create_list:{encoded}",
                valid=True,
            )]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        print(json.dumps({"items": [{
            "title": "Error in add_list.py",
            "subtitle": f"{type(e).__name__}: {e}  |  {traceback.format_exc()}",
            "valid": False,
        }]}))


if __name__ == "__main__":
    main()
