#!/usr/bin/env python3
"""
tag_manager.py — Alfred Script Filter
Consolidated tag management: view, add, change, remove.

Default (no prefix): lists current tags assigned to the task
  ⏎         → remove this tag
  ⌘⏎        → change this tag (routes to change_tag_picker.py SF)
  ⌃⏎        → remove ALL tags

# <query>   → tag picker for adding a new tag
  ⏎         → add this tag

Alfred wiring after this SF:
  arg == "changetag"         → change_tag_picker.py SF
  arg starts with "attr_tag" → dispatch.py
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
    import config as cfg
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
    from api import TickTickAPI
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

# ── Helpers ──────────────────────────────────────────────────────────────────
def get_current_tags(pid, tid):
    """Return current tags for the task. all_tasks → project_data → API."""
    all_tasks = cache_store.get("all_tasks") or []
    task = next((t for t in all_tasks if t.get("id") == tid), None)
    if task:
        return task.get("tags") or []
    pdata = cache_store.get(f"project_data_{pid}")
    if pdata:
        task = next((t for t in pdata.get("tasks", []) if t.get("id") == tid), None)
        if task:
            return task.get("tags") or []
    try:
        task = TickTickAPI(cfg.get_token()).get_task(pid, tid)
        return task.get("tags") or []
    except Exception:
        return []

def get_all_tags():
    return cache_store.get("tags") or cfg.get_tags() or []

# ── Scope detection ──────────────────────────────────────────────────────────
def detect_mode(raw_query):
    """
    Returns ('add', fragment) for # prefix, or ('current', query) for default.
    Returns ('hint', None) for bare # with no space (shows hint).
    """
    q = raw_query
    if q == "#":
        return "hint", None
    if q.startswith("# "):
        return "add", q[2:]  # preserve trailing space — parse_add_fragment needs it
    if q.startswith("#") and " " not in q:
        return "hint", None
    return "current", q

# ── Views ─────────────────────────────────────────────────────────────────────
def current_tags_view(query, pid, tid, task_title):
    current = get_current_tags(pid, tid)

    if not current:
        return [alfred.item(
            title="No tags assigned",
            subtitle="Type # to add a tag  ⌘⇧ 🔙",
            valid=False,
        )]

    mods_hint = "# Add tag  ⏎ Remove  ⌘⏎ Change  ⌃⏎ Clear all"
    items = []
    for tag in current:
        items.append(alfred.item(
            uid=f"curtag-{tag}",
            title=tag,
            subtitle=f"{mods_hint}  ⌘⇧ 🔙",
            arg=f"attr_tag_remove:{pid}:{tid}:{tag}",
            valid=True,
            mods={
                "cmd":  {"arg": "changetag",                   "subtitle": f"Change #{tag}"},
                "ctrl": {"arg": f"attr_tag_clear:{pid}:{tid}", "subtitle": "Remove all tags"},
            },
            variables={"task_list_id": pid, "task_id": tid, "old_tag": tag},
        ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items:
        items = [alfred.item(title=f'No tags matching "{query}"', valid=False)]

    return items


def parse_add_fragment(fragment_str):
    """
    Parse the string after '# ' into confirmed tags and current search fragment.
    Tags are single words separated by spaces. A trailing space means the last
    word is confirmed; no trailing space means last word is still being typed.

    '# shop prep'   → confirmed=["shop"],  fragment="prep"
    '# shop prep '  → confirmed=["shop","prep"], fragment=""
    '# '            → confirmed=[],  fragment=""
    """
    if not fragment_str:
        return [], ""
    parts = fragment_str.split(" ")
    if fragment_str.endswith(" "):
        confirmed = [p for p in parts if p]
        return confirmed, ""
    else:
        confirmed = [p for p in parts[:-1] if p]
        return confirmed, parts[-1]


def add_tag_view(fragment_str, pid, tid, task_title):
    confirmed, current_fragment = parse_add_fragment(fragment_str)
    confirmed_set = set(confirmed)

    all_tags     = get_all_tags()
    current_tags = get_current_tags(pid, tid)
    current_set  = set(current_tags)

    items = []

    # ── Confirm item ─────────────────────────────────────────────────────────
    if confirmed:
        tags_display = "  ".join(f"#{t}" for t in confirmed)
        arg_tags     = ",".join(confirmed)
        items.append(alfred.item(
            title=f"Add {len(confirmed)} tag{'s' if len(confirmed) > 1 else ''}: {tags_display}",
            subtitle="⏎ Confirm and close  ⌘⇧ 🔙",
            arg=f"attr_tags_multi:{pid}:{tid}:{arg_tags}",
            valid=True,
            variables={"task_list_id": pid, "task_id": tid},
        ))

    # ── Available tags ────────────────────────────────────────────────────────
    for tag in all_tags:
        if tag in confirmed_set:
            continue  # already queued — hide it
        already = tag in current_set
        # Build new autocomplete query with this tag appended
        new_confirmed = confirmed + [tag]
        new_query = "# " + " ".join(new_confirmed) + " "
        item = alfred.item(
            uid=f"addtag-{tag}",
            title=f"#{tag}",
            subtitle=("Already tagged  ⌘⇧ 🔙" if already
                      else "⏎ Queue  ⌘⇧ 🔙"),
            arg="",
            valid=False,
            variables={"task_list_id": pid, "task_id": tid},
        )
        item["autocomplete"] = new_query
        items.append(item)

    # ── Filter by current fragment ────────────────────────────────────────────
    tag_items  = [i for i in items if (i.get("uid") or "").startswith("addtag-")]
    rest_items = [i for i in items if not (i.get("uid") or "").startswith("addtag-")]
    if current_fragment:
        tag_items = fuzz.filter_and_score(current_fragment, tag_items,
                                          key_fn=lambda x: x["title"])

    items = rest_items + tag_items

    if not items:
        msg = (f'No tags matching "{current_fragment}"' if current_fragment
               else "No tags cached — run Sync first")
        items = [alfred.item(title=msg, valid=False)]

    return items


def hint_view():
    item = alfred.item(
        title="#  Add tag",
        subtitle="Add space after # to search and add a tag",
        valid=False,
    )
    item["autocomplete"] = "# "
    return [item]


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    pid        = os.environ.get("task_list_id", os.environ.get("list_id", ""))
    tid        = os.environ.get("task_id", "")
    task_title = os.environ.get("task_title", "task")
    raw_query  = sys.argv[1] if len(sys.argv) > 1 else ""

    if not pid or not tid:
        try:
            with open("/tmp/ticktick_reattribute.txt") as _f:
                parts = _f.read().strip().split(":", 1)
                if len(parts) == 2:
                    pid, tid = parts[0], parts[1]
        except Exception:
            pass

    try:
        mode, fragment = detect_mode(raw_query)

        if mode == "hint":
            items = hint_view()
        elif mode == "add":
            items = add_tag_view(fragment, pid, tid, task_title)
        else:
            items = current_tags_view(fragment, pid, tid, task_title)

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
