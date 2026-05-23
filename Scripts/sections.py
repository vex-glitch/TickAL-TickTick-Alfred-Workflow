#!/usr/bin/env python3
"""
sections.py — Alfred Script Filter
Displays sections (columns) for a TickTick list.
Arrives here via ⌥⏎ on a list item in lists.py.

If the list only has unsectioned content (no real sections, or only a single
"Not Sectioned" column), skips the section picker and renders tasks directly.
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
except Exception as e:
    emit_error(f"Import failed: {e} | SRC_DIR={SRC_DIR}")
    sys.exit(0)

# ── Priority labels (mirrored from tasks.py) ─────────────────────────────────
PRIORITY = {0: "", 1: "🟡 ", 3: "🟠 ", 5: "🔴 "}

# ── Data ─────────────────────────────────────────────────────────────────────
def get_project_data(list_id):
    cache_key = f"project_data_{list_id}"
    data = cache_store.get(cache_key)
    if data is None:
        data = TickTickAPI(cfg.get_token()).get_project_data(list_id)
        cache_store.set(cache_key, data)
    return data

def get_sections(list_id):
    return sorted(
        get_project_data(list_id).get("columns", []),
        key=lambda s: s.get("sortOrder", 0)
    )

def get_tasks(list_id):
    return get_project_data(list_id).get("tasks", [])

# ── Task renderer (used when skipping section picker) ────────────────────────
def render_tasks(list_id, all_tasks, column_ids, section_id, section_name, query):
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

    tasks = [t for t in tasks if t.get("status", 0) == 0 and not t.get("parentId")]

    items = []
    for t in tasks:
        tid   = t["id"]
        name  = t.get("title", "Untitled")
        tags  = t.get("tags") or []
        tag_str = " # " + " ".join(tags) if tags else ""
        title = PRIORITY.get(t.get("priority", 0), "") + name + tag_str
        due   = t.get("dueDate", "")[:10] if t.get("dueDate") else ""

        sub_count = sum(1 for s in all_tasks
                        if s.get("parentId") == tid and s.get("status", 0) == 0)
        count_str = f"{sub_count} subtask{'s' if sub_count != 1 else ''}  " if sub_count else ""

        sub = (f"Due {due}  " if due else "") + count_str + \
              "Open  ⌘ Add  ⇧ Done  ⌥ Browse  ⌥⌘ URL  ⌃ Modify"

        link = f"ticktick:///webapp/#p/{list_id}/tasks/{tid}"

        items.append(alfred.item(
            title=title,
            subtitle=sub,
            arg=f"open:{link}",
            mods={
                "cmd":      {"arg": "", "subtitle": "Add subtask"},
                "shift":    {"arg": f"complete:{list_id}:{tid}:{name}", "subtitle": "Complete task"},
                "alt":      {"arg": "", "subtitle": "Browse subtasks"},
                "ctrl+shift": {"arg": f"pomodoro:{list_id}:{tid}", "subtitle": "Start Pomodoro"},
                "alt+cmd":  {"arg": f"copy:{link}", "subtitle": "Copy link to task"},
                "ctrl":     {"arg": "", "subtitle": "Change attributes"},
            },
            variables={"task_id": tid, "task_title": name, "task_list_id": list_id},
        ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items:
        label = section_name or "this list"
        list_link = f"ticktick:///webapp/#p/{list_id}/tasks"
        items.append(alfred.item(
            title=f'No tasks matching "{query}"' if query else f"No tasks in {label}",
            subtitle="⇧⌘ Back",
            arg=f"open:{list_link}",
            valid=True,
            variables={"list_id": list_id, "task_list_id": list_id},
        ))

    print(alfred.output(items, skipknowledge=True))

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    list_id   = os.environ.get("list_id", "")
    list_name = os.environ.get("list_name", "List")
    folder_id = os.environ.get("folder_id", "")
    query     = sys.argv[1] if len(sys.argv) > 1 else ""

    # When first arriving from lists.py, $1 == list_id — treat as empty search
    if query == list_id:
        query = ""

    # When triggered via ET (go back from tasks), env vars are gone.
    # Recover list_id from temp file written by the go-back Run Script.
    if not list_id:
        try:
            with open("/tmp/ticktick_reattribute.txt") as _f:
                _parts = _f.read().strip().split(":", 1)
                if len(_parts) >= 1 and _parts[0]:
                    list_id = _parts[0]
        except Exception:
            pass

    try:
        sections  = get_sections(list_id)
        all_tasks = get_tasks(list_id)
        column_ids = {s["id"] for s in sections}

        # Orphaned tasks: no columnId or columnId doesn't belong to this list
        orphaned = [t for t in all_tasks
                    if not t.get("parentId")
                    and t.get("status", 0) == 0
                    and (not t.get("columnId") or t.get("columnId") not in column_ids)]

        # Check if a real "Not Sectioned" column exists
        unsectioned_col = next(
            (s for s in sections
             if "not" in s.get("name", "").lower() and "section" in s.get("name", "").lower()),
            None
        )

        # ── Skip section picker if only unsectioned content exists ────────────
        # Condition: no real sections at all, OR only a single "Not Sectioned" column
        only_unsectioned = (
            len(sections) == 0 or
            (len(sections) == 1 and unsectioned_col is not None)
        )

        if only_unsectioned:
            if unsectioned_col:
                sid   = unsectioned_col["id"]
                sname = unsectioned_col["name"]
            else:
                sid   = "UNSECTIONED"
                sname = "Not sectioned"
            render_tasks(list_id, all_tasks, column_ids, sid, sname, query)
            return

        # ── Normal section picker ─────────────────────────────────────────────
        items = []

        # Custom "Not sectioned" item for orphaned tasks (only if no real column covers it)
        has_unsectioned_col = unsectioned_col is not None
        if orphaned and not has_unsectioned_col:
            count_str = f"{len(orphaned)} task{'s' if len(orphaned) != 1 else ''}  "
            items.append(alfred.item(
                uid="unsectioned",
                title="Not sectioned",
                subtitle=f"{count_str}⌥ Browse",
                arg="",
                mods={
                    "alt": {"arg": "", "subtitle": "Browse unsectioned tasks"},
                },
                variables={"section_id": "UNSECTIONED", "section_name": "Not sectioned", "folder_id": folder_id},
            ))

        for s in sections:
            sid   = s["id"]
            sname = s.get("name", "Unnamed Section")
            section_link = f"ticktick:///webapp/#p/{list_id}/tasks/{sid}"
            list_link    = f"ticktick:///webapp/#p/{list_id}/tasks"

            is_unsectioned_col = "not" in sname.lower() and "section" in sname.lower()

            task_count = sum(1 for t in all_tasks
                             if t.get("columnId") == sid
                             and not t.get("parentId")
                             and t.get("status", 0) == 0)

            if is_unsectioned_col:
                task_count += len(orphaned)

            count_str = f"{task_count} task{'s' if task_count != 1 else ''}  " if task_count else ""

            items.append(alfred.item(
                uid=f"section-{sid}",
                title=sname,
                subtitle=f"{count_str}Open  ⌘ Add  ⌥ Browse  ⌥⌘ URL",
                arg=f"open:{list_link}",
                mods={
                    "cmd":     {"arg": "", "subtitle": f"Add task to {sname}"},
                    "alt":     {"arg": "", "subtitle": f"Browse tasks in {sname}"},
                    "alt+cmd": {"arg": f"copy:{section_link}", "subtitle": f"Copy link to {sname}"},
                },
                variables={"section_id": sid, "section_name": sname, "folder_id": folder_id},
            ))

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

        list_link = f"ticktick:///webapp/#p/{list_id}/tasks"
        if not sections:
            items.append(alfred.item(
                uid="no-sections",
                title=f"No sections in {list_name}",
                subtitle="⇧⌘ Back",
                arg=f"open:{list_link}",
                valid=True,
                variables={"list_id": list_id, "list_name": list_name, "folder_id": folder_id},
            ))
        elif not items and query:
            items.append(alfred.item(
                uid="no-results",
                title=f'No sections matching "{query}"',
                subtitle="⇧⌘ Back",
                arg=f"open:{list_link}",
                valid=True,
                variables={"list_id": list_id, "list_name": list_name, "folder_id": folder_id},
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
