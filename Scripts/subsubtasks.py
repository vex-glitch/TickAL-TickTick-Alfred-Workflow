#!/usr/bin/env python3
"""
subsubtasks.py — Alfred Script Filter
Displays sub-subtasks of a chosen subtask.
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
    import config as cfg
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
    from api import TickTickAPI
    from display import build_title, build_subtitle, col_lookup, list_name_for, join_breadcrumb, search_key, MOD_BACK
except Exception as e:
    emit_error(f"Import failed: {e} | SRC_DIR={SRC_DIR}")
    sys.exit(0)

# ── Data ─────────────────────────────────────────────────────────────────────
def get_all_tasks(list_id):
    cache_key = f"project_data_{list_id}"
    data = cache_store.get(cache_key)
    if data is None:
        data = TickTickAPI(cfg.get_token()).get_project_data(list_id)
        cache_store.set(cache_key, data)
    return data.get("tasks", [])

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    list_id    = os.environ.get("task_list_id", os.environ.get("list_id", ""))
    task_id    = os.environ.get("task_id", "")       # ID of the parent subtask
    task_title = os.environ.get("task_title", "task") # title of the parent subtask
    query      = sys.argv[1] if len(sys.argv) > 1 else ""

    try:
        all_tasks = get_all_tasks(list_id)

        # Build column name lookup
        data           = cache_store.get(f"project_data_{list_id}")
        col_name_by_id = col_lookup(data)
        lname          = list_name_for(list_id, cache_store.get("projects") or [])

        # Walk up the parent chain to build a full breadcrumb:
        # List>Section>GrandparentTask>ParentSubtask
        task_by_id     = {t["id"]: t for t in all_tasks}
        parent_subtask = task_by_id.get(task_id)
        gp_col         = ""
        gp_title       = ""

        if parent_subtask:
            gp_id = parent_subtask.get("parentId")
            if gp_id:
                grandparent = task_by_id.get(gp_id)
                if grandparent:
                    gp_col   = col_name_by_id.get(grandparent.get("columnId") or "", "")
                    gp_title = grandparent.get("title", "")

        # Breadcrumb: List>Section>GrandparentTask>ParentSubtask
        breadcrumb = join_breadcrumb(lname, gp_col, gp_title, task_title)

        # Sub-subtasks: children of the parent subtask
        subtasks = [
            t for t in all_tasks
            if t.get("parentId") == task_id and t.get("status", 0) == 0
        ]

        items = []

        for t in subtasks:
            tid  = t["id"]
            name = t.get("title", "Untitled")

            sub_count = sum(1 for s in all_tasks
                            if s.get("parentId") == tid and s.get("status", 0) == 0)

            link = f"ticktick:///webapp/#p/{list_id}/tasks/{tid}"

            items.append(alfred.item(
                title=build_title(t),
                subtitle=build_subtitle(sub_count, breadcrumb=breadcrumb, actions=True),
                arg=f"open:{link}",
                mods={
                    "cmd":        {"arg": ""},
                    "shift":      {"arg": f"complete:{list_id}:{tid}:{name}"},
                    "alt":        {"arg": ""},
                    "ctrl+shift": {"arg": f"pomodoro:{list_id}:{tid}"},
                    "alt+cmd":    {"arg": f"copy:{link}"},
                    "ctrl":       {"arg": ""},
                },
                variables={"task_id": tid, "task_title": name, "task_list_id": list_id},
            ))

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: search_key(x.get("variables", {}).get("task_title", x["title"])))

        if not items:
            link = f"ticktick:///webapp/#p/{list_id}/tasks/{task_id}"
            items.append(alfred.item(
                title=f'No subtasks matching "{query}"' if query else f'No subtasks in "{task_title}"',
                subtitle=MOD_BACK,
                arg=f"open:{link}",
                valid=True,
                variables={"task_id": task_id, "task_title": task_title, "task_list_id": list_id},
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
