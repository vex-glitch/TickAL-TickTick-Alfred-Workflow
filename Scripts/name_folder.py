#!/usr/bin/env python3
"""
name_folder.py — Alfred Script Filter
User types a name for the selected folder.
Shows the lists inside the folder as a reminder.
⏎ → saves the mapping via save_folder_action.py.
"""
import sys
import os
import json
import traceback
from collections import defaultdict

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
    import cache as cache_store
    import config as cfg
    import alfred
except Exception as e:
    print(json.dumps({"items": [{"title": "Import error", "subtitle": str(e), "valid": False}]}))
    sys.exit(0)

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    import re
    raw      = sys.argv[1] if len(sys.argv) > 1 else ""
    stripped = raw.strip()
    # Ignore groupId passed as initial query (24-char hex string)
    query    = "" if re.match(r'^[0-9a-f]{20,}$', stripped) else stripped
    group_id = os.environ.get("folder_group_id", "")

    try:
        # Find lists in this folder
        projects   = cache_store.get("projects") or []
        list_names = [p["name"] for p in projects if p.get("groupId") == group_id]
        lists_hint = " · ".join(list_names) if list_names else "No lists found"

        name = query.strip()

        if not name:
            items = [alfred.item(
                title="Type a folder name…",
                subtitle=f"Prefix 1) for hierarchy order, e.g. '1) 1️⃣ Admin'  —  Lists: {lists_hint}",
                valid=False,
            )]
        else:
            items = [alfred.item(
                title=f"Name folder: {name}",
                subtitle=f"Lists: {lists_hint}  —  ⏎ to save",
                arg=name,
                variables={"folder_group_id": group_id, "folder_name": name},
            )]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        print(json.dumps({"items": [{
            "title": "Error in name_folder.py",
            "subtitle": f"{type(e).__name__}: {e} | {traceback.format_exc()}",
            "valid": False,
        }]}))


if __name__ == "__main__":
    main()
