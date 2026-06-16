#!/usr/bin/env python3
"""
filter_all.py — Alfred Script Filter
Fuzzy search across ALL tasks at every depth: tasks, subtasks,
sub-subtasks, and deeper. Shows breadcrumb so you know where each lives.
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
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
    from display import build_title, build_subtitle, join_breadcrumb, search_key
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

# ── Breadcrumb builder ────────────────────────────────────────────────────────
def get_breadcrumb(task, task_by_id):
    """
    Build 'List>Section>Parent1>Parent2' breadcrumb for any task depth.
    Walks the parentId chain upward to find all ancestors.
    The section name comes from the topmost ancestor's _columnName.
    """
    ancestor_titles = []
    current = task
    seen    = set()

    while current.get("parentId"):
        pid = current["parentId"]
        if pid in seen:
            break
        seen.add(pid)
        parent = task_by_id.get(pid)
        if not parent:
            break
        ancestor_titles.append(parent.get("title", "?"))
        current = parent

    # current is now the topmost ancestor (or the task itself if top-level)
    col_name  = current.get("_columnName", "")
    list_name = task.get("_projectName", "")

    ancestor_titles.reverse()
    return join_breadcrumb(list_name, col_name, *ancestor_titles)

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""

    try:
        all_tasks = cache_store.get("all_tasks") or []

        # All incomplete tasks at every depth
        tasks = [t for t in all_tasks if t.get("status", 0) == 0]

        task_by_id = {t["id"]: t for t in all_tasks}

        items = []

        for t in tasks:
            tid  = t["id"]
            pid  = t.get("_projectId", t.get("projectId", ""))
            name = t.get("title", "Untitled")

            breadcrumb = get_breadcrumb(t, task_by_id)
            sub_count  = sum(1 for s in all_tasks
                             if s.get("parentId") == tid and s.get("status", 0) == 0)

            link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"

            items.append(alfred.item(
                title=build_title(t),
                subtitle=build_subtitle(sub_count, breadcrumb=breadcrumb),
                arg=f"open:{link}",
                mods={
                    "cmd":     {"arg": ""},
                    "shift":   {"arg": f"complete:{pid}:{tid}:{name}"},
                    "alt":     {"arg": ""},
                    "alt+cmd": {"arg": f"copy:{link}"},
                    "ctrl":    {"arg": ""},
                },
                variables={"task_id": tid, "task_title": name, "task_list_id": pid},
            ))

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: search_key(x.get("variables", {}).get("task_title", x["title"])))

        if not items:
            items.append(alfred.item(
                title=f'No tasks matching "{query}"' if query else "No tasks found — run sync first",
                valid=False,
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
