#!/usr/bin/env python3
"""
tasks.py — Alfred Script Filter
If list_id env var is set: shows tasks for that list, optionally filtered to a section.
If list_id is not set: fuzzy search across all tasks in all lists.
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
    from display import build_title, build_subtitle, col_lookup, list_name_for, join_breadcrumb, search_key, MOD_BACK
except Exception as e:
    emit_error(f"Import failed: {e} | SRC_DIR={SRC_DIR}")
    sys.exit(0)

# ── Data ─────────────────────────────────────────────────────────────────────
def get_list_tasks(list_id):
    cache_key = f"project_data_{list_id}"
    data = cache_store.get(cache_key)
    if data is None:
        data = TickTickAPI(cfg.get_token()).get_project_data(list_id)
        cache_store.set(cache_key, data)
    return data

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    list_id      = os.environ.get("list_id", "")
    section_id   = os.environ.get("section_id", "")
    section_name = os.environ.get("section_name", "")
    query        = sys.argv[1] if len(sys.argv) > 1 else ""
    if query == "inbox":   # routed from folders.py, not a real search term
        query = ""

    # When triggered via ET (go back from subtasks), env vars are gone.
    # Recover list_id from temp file written by the go-back Run Script.
    if not list_id:
        try:
            with open("/tmp/ticktick_reattribute.txt") as _f:
                _parts = _f.read().strip().split(":", 1)
                if len(_parts) == 2:
                    list_id = _parts[0]
        except Exception:
            pass

    try:
        # ── Scoped mode: specific list ────────────────────────────────────────
        if list_id:
            data          = get_list_tasks(list_id)
            all_tasks     = data.get("tasks", [])
            col_name_by_id = col_lookup(data)
            column_ids     = set(col_name_by_id.keys())
            lname          = list_name_for(list_id, cache_store.get("projects") or [])

            # Filter to section if one was chosen
            if section_id == "UNSECTIONED":
                tasks = [t for t in all_tasks
                         if not t.get("columnId") or t.get("columnId") not in column_ids]
            elif section_id:
                tasks = [t for t in all_tasks if t.get("columnId") == section_id]
                if "not" in section_name.lower() and "section" in section_name.lower():
                    orphaned = [t for t in all_tasks
                                if not t.get("columnId") or t.get("columnId") not in column_ids]
                    seen = {t["id"] for t in tasks}
                    tasks = tasks + [t for t in orphaned if t["id"] not in seen]
            else:
                tasks = all_tasks

            # Only incomplete top-level tasks
            tasks = [t for t in tasks if t.get("status", 0) == 0 and not t.get("parentId")]

            items = []
            for t in tasks:
                tid  = t["id"]
                name = t.get("title", "Untitled")

                if section_id and section_id != "UNSECTIONED":
                    bc_section = section_name
                else:
                    bc_section = col_name_by_id.get(t.get("columnId") or "", "")
                breadcrumb = join_breadcrumb(lname, bc_section)

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
                label = section_name or "this list"
                list_link = f"ticktick:///webapp/#p/{list_id}/tasks"
                items.append(alfred.item(
                    title=f'No tasks matching "{query}"' if query else f"No tasks in {label}",
                    subtitle=MOD_BACK,
                    arg=f"open:{list_link}",
                    valid=True,
                    variables={"task_list_id": list_id, "list_id": list_id, "section_id": section_id},
                ))

        # ── Global mode: all lists ────────────────────────────────────────────
        else:
            all_tasks = cache_store.get("all_tasks") or []

            tasks = [
                t for t in all_tasks
                if t.get("status", 0) == 0 and not t.get("parentId")
            ]

            items = []
            for t in tasks:
                tid  = t["id"]
                pid  = t.get("_projectId", t.get("projectId", ""))
                name = t.get("title", "Untitled")

                lname      = t.get("_projectName", "")
                col_name   = t.get("_columnName", "")
                breadcrumb = join_breadcrumb(lname, col_name)

                sub_count = sum(1 for s in all_tasks
                                if s.get("parentId") == tid and s.get("status", 0) == 0)
                link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"

                items.append(alfred.item(
                    title=build_title(t),
                    subtitle=build_subtitle(sub_count, breadcrumb=breadcrumb, actions=True),
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
                    title=f'No tasks matching "{query}"' if query else "No tasks found — run Sync first",
                    valid=False,
                ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
