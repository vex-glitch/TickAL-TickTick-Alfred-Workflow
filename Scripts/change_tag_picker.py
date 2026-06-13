#!/usr/bin/env python3
"""
change_tag_picker.py — Alfred Script Filter
Tag picker for adding a tag to a task.
Reads task_id, task_list_id from env vars.
Outputs arg: attr_tag:{list_id}:{task_id}:{tag_name}
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

try:
    import config as cfg
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    list_id    = os.environ.get("task_list_id", os.environ.get("list_id", ""))
    tid        = os.environ.get("task_id", "")
    task_title = os.environ.get("task_title", "task")
    old_tag    = os.environ.get("old_tag", "")   # set by tag_manager.py when changing
    query      = sys.argv[1] if len(sys.argv) > 1 else ""

    if not list_id or not tid:
        try:
            with open("/tmp/ticktick_reattribute.txt") as _f:
                _parts = _f.read().strip().split(":", 1)
                if len(_parts) == 2:
                    list_id, tid = _parts[0], _parts[1]
        except Exception:
            pass

    try:
        tags = cache_store.get("tags") or cfg.get_tags()
        if not tags:
            print(alfred.output([alfred.item(
                title="No tags cached — run sync first",
                valid=False,
            )], skipknowledge=True))
            return

        replacing = f"Replace #{old_tag} with" if old_tag else "Add tag"

        items = []
        for tag in tags:
            if tag == old_tag:
                continue  # skip replacing with the same tag
            items.append(alfred.item(
                title=f"#{tag}",
                subtitle=f"{replacing} #{tag}  ⌘⇧ 🔙",
                arg=tag,
                variables={"task_list_id": list_id, "task_id": tid, "old_tag": old_tag},
            ))

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

        if not items:
            items.append(alfred.item(
                title=f'No tags matching "{query}"' if query else "No tags — run Sync first",
                subtitle="⌘⇧ 🔙",
                arg="",
                valid=True,
                variables={"task_list_id": list_id, "task_id": tid},
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
