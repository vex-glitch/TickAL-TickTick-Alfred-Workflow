#!/usr/bin/env python3
"""
folders.py — Alfred Script Filter
Displays TickTick folders.
⏎ → drill into lists in that folder (passes groupId to lists.py)
"""
import sys
import os
import json
import traceback

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    from script_base import bootstrap, emit, emit_error, WORKFLOW_DIR, SRC_DIR
    bootstrap()
except Exception as e:
    print(json.dumps({"items": [{"uid": "err", "title": "TickTick Error",
                                 "subtitle": f"Path setup failed: {e}", "valid": False}]}))
    sys.exit(0)

# ── Imports ──────────────────────────────────────────────────────────────────
try:
    import cache as cache_store
    import config as cfg
    import alfred
    import fuzzy as fuzz
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""

    try:
        items = []
        folders = cfg.get_folders()  # {groupId: name}

        # ── Inbox (special: goes directly to tasks, bypasses lists.py) ───────
        inbox_id = None
        cached_projects = cache_store.get("projects")
        if cached_projects:
            for p in cached_projects:
                if p.get("kind") == "INBOX" or (
                    p.get("name", "").lower() == "inbox" and not p.get("groupId")
                ):
                    inbox_id = p["id"]
                    break

        items.append(alfred.item(
            title="📥 Inbox",
            subtitle="⏎ ⤵️  ⌘⇧ 🔙",
            arg="inbox",
            variables={"list_id": inbox_id or "", "list_name": "Inbox", "folder_id": ""},
        ))

        # ── Folders from config ───────────────────────────────────────────────
        if not folders:
            items.append(alfred.item(
                title="No folders configured",
                subtitle="Run Update → Set Folders to set up your folders",
                valid=False,
            ))
        else:
            import re

            def _folder_order(name):
                """Extract (sort_int, clean_name) from strict '1) Name' prefix.
                Only matches exactly: digits ) space — e.g. '1) 1️⃣ Admin'.
                Anything else is returned as-is with sort_n=9999.
                """
                m = re.match(r'^(\d+)\)\s(.+)$', name.strip())
                if m:
                    return int(m.group(1)), m.group(2).strip()
                return 9999, name.strip()

            sorted_folders = sorted(folders.items(), key=lambda kv: _folder_order(kv[1])[0])

            for group_id, raw_name in sorted_folders:
                _, clean = _folder_order(raw_name)
                items.append(alfred.item(
                    uid=f"folder-{group_id}",
                    title=clean,
                    subtitle="⏎ ⤵️  ⌘⇧ 🔙",
                    arg="",
                    variables={"folder_id": group_id, "folder_name": clean},
                ))

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

        if not items:
            items = [alfred.item(
                uid="no-results",
                title=f'No folders matching "{query}"',
                valid=False,
            )]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
