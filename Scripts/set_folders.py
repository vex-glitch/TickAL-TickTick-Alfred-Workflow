#!/usr/bin/env python3
"""
set_folders.py — Alfred Script Filter
Shows all TickTick folders (grouped by groupId) so the user can name them.
Each result shows the lists inside that folder as the subtitle.
⏎ on any → passes groupId to name_folder.py to give it a name.

Run Update → Sync first to populate the projects cache.
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
    import fuzzy as fuzz
except Exception as e:
    print(json.dumps({"items": [{"title": "Import error", "subtitle": str(e), "valid": False}]}))
    sys.exit(0)

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    import re
    query = raw.strip() if re.search(r'[a-zA-Z0-9]', raw) else ""

    try:
        projects = cache_store.get("projects") or []

        if not projects:
            print(alfred.output([alfred.item(
                title="No data — run Update → Sync first",
                valid=False,
            )], skipknowledge=True))
            return

        # Group lists by groupId
        groups = defaultdict(list)
        for p in projects:
            gid = p.get("groupId")
            if gid:
                groups[gid].append(p.get("name", "Untitled"))

        if not groups:
            print(alfred.output([alfred.item(
                title="No folders found in your TickTick data",
                subtitle="Folders only appear if your lists are organised into groups in TickTick",
                valid=False,
            )], skipknowledge=True))
            return

        saved_folders = cfg.get_folders()

        def _folder_order(name):
            """Extract (sort_int, clean_name) from strict '1) Name' prefix only."""
            import re
            m = re.match(r'^(\d+)\)\s(.+)$', name.strip())
            if m:
                return int(m.group(1)), m.group(2).strip()
            return 9999, name.strip()

        def _group_sort_key(gid):
            raw = saved_folders.get(gid, "")
            return _folder_order(raw)[0] if raw else 9999

        items = []
        for gid in sorted(groups, key=_group_sort_key):
            list_names = groups[gid]
            saved_name = saved_folders.get(gid)
            if saved_name:
                sort_n, clean = _folder_order(saved_name)
                title  = clean
                status = f"✓ {clean}"
            else:
                title  = "Unnamed folder"
                status = "⚠ Not named yet — e.g. '1 Manager'"
            subtitle = f"{status}  —  {' · '.join(list_names)}  |  ⌘ 🗑️"

            items.append(alfred.item(
                uid=f"folder-{gid}",
                title=title,
                subtitle=subtitle,
                arg="",
                variables={"folder_group_id": gid},
                mods={
                    "cmd": {
                        "arg": "delete_folder",
                    }
                },
            ))

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

        if not items:
            items = [alfred.item(
                title=f'No folders matching "{query}"',
                valid=False,
            )]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        print(json.dumps({"items": [{
            "title": "Error in set_folders.py",
            "subtitle": f"{type(e).__name__}: {e} | {traceback.format_exc()}",
            "valid": False,
        }]}))


if __name__ == "__main__":
    main()
