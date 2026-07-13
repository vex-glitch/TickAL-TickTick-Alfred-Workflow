#!/usr/bin/env python3
"""
move_list_picker.py - Alfred Script Filter
Multi-mode picker for moving/re-parenting a task.

Mirrors the add-flow ~ location menu:
  Empty query → scope menu (📋 List / 📑 Section / 🧬 Task); picking a row
                autocompletes its prefix and drills into that sub-picker.
  l <query>   → list picker    (move to another list)
  s <query>   → section picker  (move to a section, any list)
  t <query>   → task picker     (make a subtask of another task)

arg output (consumed by Args & Vars node → move_action.py):
  list:{new_pid}
  section:{list_id}:{section_id}
  task:{parent_list_id}:{parent_tid}
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

try:
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

# ── Back chord ───────────────────────────────────────────────────────────────
def back_mod(list_id, tid):
    """⌃⇧ back must work even on invalid rows - a mod-level valid=True
    overrides the row's valid=False (Alfred ignores action chords on invalid
    rows). Mod variables REPLACE item-level ones, so carry the full context."""
    return {"ctrl": {"valid": True, "arg": "",
                           "subtitle": "🔙 Back to ⌘ Actions",
                           "variables": {"task_list_id": list_id,
                                         "task_id": tid}}}

# ── Scope menu (mirrors the add-flow ~ location menu) ─────────────────────────
SCOPE_ROWS = [
    ("l", "📋", "List",    "Move to another list"),
    ("s", "📑", "Section", "Move to another section"),
    ("t", "🧬", "Task",    "Make it a subtask"),
]

def scope_menu(back):
    """Idle (empty) state → the three-scope menu. Picking a row autocompletes
    its prefix and drills into that sub-picker (same UX as add's ~ menu).
    Typing with no prefix defaults to list-filtering (handled in main)."""
    items = []
    for letter, emoji, name, hint in SCOPE_ROWS:
        items.append(alfred.item(
            title=f"{emoji} {name}",
            subtitle=hint,
            valid=False,
            autocomplete=f"{letter} ",
            mods=back,
        ))
    return items

# ── Scope detection ──────────────────────────────────────────────────────────
def detect_scope(query):
    """Return ('list'|'section'|'task'|None, stripped_query)."""
    q = query.lower()
    for letter, scope in (("l", "list"), ("s", "section"), ("t", "task")):
        if q.startswith(f"{letter} "):
            return scope, query[2:].strip()
    return None, query

# ── Pickers ──────────────────────────────────────────────────────────────────
def list_picker(query, list_id, task_title, back):
    cached = cache_store.get("projects")
    if not cached:
        return [alfred.item(title="No lists cached · run sync first", valid=False,
                            mods=back)]

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
            subtitle=f"🏠 Move \"{task_title}\" here  ⌃ 🔙",
            arg=f"list:{pid}",
            mods=back,
            variables={"task_list_id": list_id},
        ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items:
        msg = f'No lists matching "{query}"' if query else "No other lists found"
        return [alfred.item(title=msg, valid=False, mods=back)]
    return items


def section_picker(query, task_title, back):
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
                subtitle=f"🏠 Move \"{task_title}\" here  ⌃ 🔙",
                arg=f"section:{pid}:{cid}",
                mods=back,
            ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items:
        msg = f'No sections matching "{query}"' if query else "No sections cached · run Sync first"
        return [alfred.item(title=msg, valid=False, mods=back)]
    return items


def task_picker(query, current_tid, task_title, back):
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
            subtitle = f"↳ {parent_title}  {lname}  |  Make \"{task_title}\" a subtask  ⌃ 🔙"
        else:
            subtitle = f"{lname}  |  Make \"{task_title}\" a subtask  ⌃ 🔙"

        items.append(alfred.item(
            title=name,
            subtitle=subtitle,
            arg=f"task:{pid}:{tid}",
            mods=back,
        ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items:
        msg = f'No tasks matching "{query}"' if query else "No tasks cached · run Sync first"
        return [alfred.item(title=msg, valid=False, mods=back)]
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
        stripped = raw_query.strip()
        back     = back_mod(list_id, tid)

        # Idle (empty) → scope menu (all options visible)
        if not stripped:
            print(alfred.output(scope_menu(back), skipknowledge=True))
            return

        scope, query = detect_scope(raw_query)
        if scope == "section":
            items = section_picker(query, task_title, back)
        elif scope == "task":
            items = task_picker(query, tid, task_title, back)
        elif scope == "list":
            items = list_picker(query, list_id, task_title, back)
        else:
            # Typing with no scope prefix → default to list, filter by query
            items = list_picker(stripped, list_id, task_title, back)

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
