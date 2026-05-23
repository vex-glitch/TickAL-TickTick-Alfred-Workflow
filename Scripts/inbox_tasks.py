#!/usr/bin/env python3
"""
inbox_tasks.py — Alfred Script Filter
Displays tasks in the TickTick Inbox.
Finds the Inbox project ID directly from cache — does not rely on env vars.
"""
import sys
import os
import json
import traceback

# ── Fallback error output ────────────────────────────────────────────────────
def emit(items):
    print(json.dumps({"items": items}))

def emit_error(msg):
    emit([{"uid": "err", "title": "TickTick Error", "subtitle": msg, "valid": False}])

# ── Path setup ───────────────────────────────────────────────────────────────
try:
    SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
    WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
    SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
    sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
    sys.path.insert(0, SRC_DIR)
except Exception as e:
    emit_error(f"Path setup failed: {e}")
    sys.exit(0)

# ── Imports ──────────────────────────────────────────────────────────────────
try:
    import config as cfg
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
    from api import TickTickAPI
    from display import build_title, build_subtitle
except Exception as e:
    emit_error(f"Import failed: {e} | SRC_DIR={SRC_DIR}")
    sys.exit(0)

# ── Inbox is a special project not returned by /project ──────────────────────
INBOX_API_ID = "inbox"   # literal string accepted by the TickTick API

# ── Data ─────────────────────────────────────────────────────────────────────
def get_tasks():
    cache_key = "project_data_inbox"
    data = cache_store.get(cache_key)
    if data is None:
        data = TickTickAPI(cfg.get_token()).get_project_data(INBOX_API_ID)
        cache_store.set(cache_key, data)
    return data.get("tasks", [])

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # Strip "inbox" if Alfred passed it as the routing arg
    raw_query = sys.argv[1] if len(sys.argv) > 1 else ""
    query = "" if raw_query.strip().lower() == "inbox" else raw_query

    try:
        all_tasks = get_tasks()

        # Only incomplete top-level tasks
        tasks = [t for t in all_tasks if t.get("status", 0) == 0 and not t.get("parentId")]

        items = []
        for t in tasks:
            tid      = t["id"]
            real_pid = t.get("projectId", INBOX_API_ID)
            name     = t.get("title", "Untitled")

            sub_count = sum(1 for s in all_tasks
                            if s.get("parentId") == tid and s.get("status", 0) == 0)

            link = f"ticktick:///webapp/#p/{real_pid}/tasks/{tid}"

            items.append(alfred.item(
                title=build_title(t, "Inbox"),
                subtitle=build_subtitle(sub_count),
                arg=f"open:{link}",
                mods={
                    "cmd":     {"arg": "",                                  "subtitle": "Add subtask"},
                    "shift":   {"arg": f"complete:{real_pid}:{tid}:{name}", "subtitle": "Complete task"},
                    "alt":     {"arg": "",                                  "subtitle": "Browse subtasks"},
                    "alt+cmd": {"arg": f"copy:{link}",                      "subtitle": "Copy link to task"},
                    "ctrl":    {"arg": "",                                  "subtitle": "Change attributes"},
                },
                variables={"task_id": tid, "task_title": name, "task_list_id": real_pid},
            ))

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: search_key(x.get("variables", {}).get("task_title", x["title"])))

        if not items:
            items.append(alfred.item(
                title=f'No tasks matching "{query}"' if query else "Inbox is empty",
                valid=False,
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
