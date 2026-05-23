#!/usr/bin/env python3
"""
move_list_picker.py — Alfred Script Filter
Multi-mode picker for moving/re-parenting a task.

Empty / partial-prefix → shows scope hints
Default (no prefix)    → list picker  (move to another list)
S <query>              → section picker (move to a section, any list)
T <query>              → task picker   (make a subtask of another task)

arg output (consumed by Args & Vars node → move_action.py):
  list:{new_pid}
  section:{list_id}:{section_id}
  task:{parent_list_id}:{parent_tid}
"""
import sys
import os
import json
import traceback

# ── Path setup ───────────────────────────────────────────────────────────────
def emit(items):
    print(json.dumps({"items": items}))

def emit_error(msg):
    emit([{"uid": "err", "title": "TickTick Error", "subtitle": msg, "valid": False}])

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
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

# ── Prefix hint system ───────────────────────────────────────────────────────
PREFIX_HINTS = [
    ("s", "S", "Section"),
    ("t", "T", "Task"),
]

EMPTY_SUBTITLE = "Scope Prefix: S Section · T Task"

def get_hint_items(raw_query):
    """Return hint items for empty or partial-prefix input, else None."""
    q = raw_query.lower()

    if not q:
        return [alfred.item(
            title="Type or press space to filter lists…",
            subtitle=EMPTY_SUBTITLE,
            valid=False,
        )]

    if " " in q:
        return None  # has space → scoped or plain search, no hints

    matches = [(key, label, desc) for key, label, desc in PREFIX_HINTS if key.startswith(q)]
    if not matches:
        return None

    items = []
    for key, label, desc in matches:
        item = alfred.item(
            title=f"{label}  {desc}",
            subtitle=f"Add space after {label.lower()} to move to a {desc}",
            valid=False,
        )
        item["autocomplete"] = f"{key} "
        items.append(item)
    return items

# ── Scope detection ──────────────────────────────────────────────────────────
def detect_scope(query):
    """Return ('section'|'task'|None, stripped_query)."""
    q = query.lower()
    if q.startswith("s "):
        return "section", query[2:].strip()
    if q.startswith("t "):
        return "task", query[2:].strip()
    return None, query

# ── Pickers ──────────────────────────────────────────────────────────────────
def list_picker(query, list_id, task_title):
    cached = cache_store.get("projects")
    if not cached:
        return [alfred.item(title="No lists cached — run sync first", valid=False)]

    projects = sorted(
        [p for p in cached if p.get("kind") != "SMART_LIST"],
        key=lambda p: p.get("sortOrder", 0),
    )

    items = []
    for p in projects:
        pid  = p["id"]
        if pid == list_id:
            continue  # skip current list
        name = p["name"]
        items.append(alfred.item(
            title=name,
            subtitle=f"Move \"{task_title}\" to {name}  ⇧⌘ Back",
            arg=f"list:{pid}",
            variables={"task_list_id": list_id},
        ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items:
        msg = f'No lists matching "{query}"' if query else "No other lists found"
        return [alfred.item(title=msg, valid=False)]
    return items


def section_picker(query, task_title):
    projects = cache_store.get("projects") or []
    items = []

    for p in projects:
        if p.get("kind") == "SMART_LIST":
            continue
        pid   = p["id"]
        pname = p["name"]
        pdata = cache_store.get(f"project_data_{pid}")
        if not pdata:
            continue
        for col in pdata.get("columns", []) or []:
            cid   = col.get("id", "")
            cname = col.get("name", "").strip()
            if not cname or cname.lower() == "not sectioned":
                continue
            items.append(alfred.item(
                title=f"{cname} | {pname}",
                subtitle=f"Move \"{task_title}\" to {cname}  ⇧⌘ Back",
                arg=f"section:{pid}:{cid}",
            ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items:
        msg = f'No sections matching "{query}"' if query else "No sections cached — run Sync first"
        return [alfred.item(title=msg, valid=False)]
    return items


def task_picker(query, current_tid, task_title):
    all_tasks = cache_store.get("all_tasks") or []
    task_map  = {t["id"]: t for t in all_tasks}

    items = []
    for t in all_tasks:
        if t.get("status", 0) != 0:
            continue
        if t["id"] == current_tid:
            continue  # can't make a task its own parent
        tid   = t["id"]
        pid   = t.get("projectId") or t.get("_projectId", "")
        name  = t.get("title", "Untitled")
        lname = t.get("_projectName", "")

        # Build breadcrumb showing parent chain
        parent_id = t.get("parentId", "")
        if parent_id and parent_id in task_map:
            parent_title = task_map[parent_id].get("title", "")
            subtitle = f"↳ {parent_title}  ·  {lname}  ·  Make \"{task_title}\" a subtask  ⇧⌘ Back"
        else:
            subtitle = f"{lname}  ·  Make \"{task_title}\" a subtask  ⇧⌘ Back"

        items.append(alfred.item(
            title=name,
            subtitle=subtitle,
            arg=f"task:{pid}:{tid}",
        ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items:
        msg = f'No tasks matching "{query}"' if query else "No tasks cached — run Sync first"
        return [alfred.item(title=msg, valid=False)]
    return items


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    list_id    = os.environ.get("task_list_id", os.environ.get("list_id", ""))
    tid        = os.environ.get("task_id", "")
    task_title = os.environ.get("task_title", "task")
    raw_query  = sys.argv[1] if len(sys.argv) > 1 else ""

    # Fall back to temp file if env vars are missing
    if not list_id or not tid:
        try:
            with open("/tmp/ticktick_reattribute.txt") as _f:
                _parts = _f.read().strip().split(":", 1)
                if len(_parts) == 2:
                    list_id, tid = _parts[0], _parts[1]
        except Exception:
            pass

    try:
        hints = get_hint_items(raw_query)
        if hints is not None:
            print(alfred.output(hints, skipknowledge=True))
            return

        scope, query = detect_scope(raw_query)

        if scope == "section":
            items = section_picker(query, task_title)
        elif scope == "task":
            items = task_picker(query, tid, task_title)
        else:
            items = list_picker(query, list_id, task_title)

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
