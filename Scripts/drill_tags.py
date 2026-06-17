#!/usr/bin/env python3
"""
drill_tags.py — Alfred Script Filter  ("Drill by tag" for a list)

Two screens in one filter (advance with ⏎, same pattern as reschedule.py):
  Screen 1 — Tag picker
    Lists the tags used by the list's top-level incomplete tasks (with counts).
    ⏎ on a tag autocompletes "<tag> " and advances to screen 2.
  Screen 2 — Tasks under the chosen tag
    Lists the list's top-level incomplete tasks carrying that tag. Task rows
    mirror sections.py exactly (arg=open:…, same mods/variables), so the
    node's output wiring (Enter→open, ⌘→Actions, ⌥→subtasks, …) behaves like
    every other task-listing Script Filter.

Arrives via ⌥⏎ on a list item (list_id rides in as an Alfred variable).
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
    from display import build_subtitle, fmt_tags, MOD_BACK
except Exception as e:
    emit_error(f"Import failed: {e} | SRC_DIR={SRC_DIR}")
    sys.exit(0)

PRIORITY = {0: "", 1: "🟡 ", 3: "🟠 ", 5: "🔴 "}

# 🔥CRM: on this list's tag screen, ⌘⏎ on a tag opens the CRM add pre-tagged, and
# the tag list is restricted to the 🔥CRM tag group — bookings also carry status /
# people / place tags, which would otherwise clutter the CRM search.
CRM_ID   = "69fed9d51fe6d10d8510bf15"
CRM_TAGS = {"🔥lead", "🔥consultation", "🔥ongoing", "🔥tattoo", "🔥prepare"}

# ── Data ─────────────────────────────────────────────────────────────────────
def get_project_data(list_id):
    cache_key = f"project_data_{list_id}"
    data = cache_store.get(cache_key)
    if data is None:
        data = TickTickAPI(cfg.get_token()).get_project_data(list_id)
        cache_store.set(cache_key, data)
    return data

def get_tasks(list_id):
    return get_project_data(list_id).get("tasks", [])

def tag_counts(all_tasks):
    """Distinct tags among incomplete top-level tasks → {tag: count}."""
    counts = {}
    for t in all_tasks:
        if t.get("status", 0) != 0 or t.get("parentId"):
            continue
        for tag in (t.get("tags") or []):
            counts[tag] = counts.get(tag, 0) + 1
    return counts

# ── Screen 1: tag picker ─────────────────────────────────────────────────────
def render_tags(list_id, all_tasks, query):
    counts = tag_counts(all_tasks)
    items = []
    for tag in sorted(counts):
        if list_id == CRM_ID and tag.lower() not in CRM_TAGS:
            continue   # CRM search surfaces only the 🔥CRM tag group
        item = alfred.item(
            uid=f"tag-{tag}",
            title=fmt_tags([tag]) or f"#{tag}",
            subtitle=build_subtitle(counts[tag], child_label="Task", actions=True),
            arg="", valid=False,
            autocomplete=f"{tag} ",   # ⏎ → advance to this tag's tasks
            variables={"list_id": list_id, "task_list_id": list_id},
        )
        # 🔥CRM: ⇧⌘⏎ on a tag opens the CRM add pre-tagged (booking flow). Wire the
        # drill node → Call ET "Add" (pass variables) on a ⇧⌘ modifier filter;
        # list_id + prefill_tag + item_type ride along. TEMPORARY — to be reworked
        # in the restructure session.
        if list_id == CRM_ID:
            item["mods"] = {"cmd+shift": {
                "arg": "add", "valid": True,
                "subtitle": f"⇧⌘ Add a 🔥CRM booking tagged {fmt_tags([tag]) or '#'+tag}",
                "variables": {"list_id": CRM_ID, "task_list_id": CRM_ID,
                              "list_name": "🔥CRM", "prefill_tag": tag,
                              "item_type": "list"},
            }}
        items.append(item)
    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])
    if not items:
        list_link = f"ticktick:///webapp/#p/{list_id}/tasks"
        items = [alfred.item(
            title=f'No tags matching "{query}"' if query else "No tags in this list",
            subtitle=MOD_BACK, arg=f"open:{list_link}", valid=True,
            variables={"list_id": list_id, "task_list_id": list_id},
        )]
    print(alfred.output(items, skipknowledge=True))

# ── Screen 2: tasks under the chosen tag ─────────────────────────────────────
def render_tasks(list_id, all_tasks, tag, query):
    tasks = [t for t in all_tasks
             if t.get("status", 0) == 0 and not t.get("parentId")
             and tag in (t.get("tags") or [])]

    items = []
    for t in tasks:
        tid   = t["id"]
        name  = t.get("title", "Untitled")
        tags  = t.get("tags") or []
        tag_str = " " + fmt_tags(tags) if tags else ""
        title = PRIORITY.get(t.get("priority", 0), "") + name + tag_str
        due   = t.get("dueDate", "")[:10] if t.get("dueDate") else ""

        sub_count = sum(1 for s in all_tasks
                        if s.get("parentId") == tid and s.get("status", 0) == 0)
        sub = (f"Due {due}  " if due else "") + build_subtitle(sub_count, actions=True)

        link = f"ticktick:///webapp/#p/{list_id}/tasks/{tid}"
        items.append(alfred.item(
            title=title,
            subtitle=sub,
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
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])
    if not items:
        list_link = f"ticktick:///webapp/#p/{list_id}/tasks"
        items = [alfred.item(
            title=f'No tasks tagged {tag}' + (f' matching "{query}"' if query else ""),
            subtitle=MOD_BACK, arg=f"open:{list_link}", valid=True,
            variables={"list_id": list_id, "task_list_id": list_id},
        )]
    print(alfred.output(items, skipknowledge=True))

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    list_id = os.environ.get("list_id", "") or os.environ.get("task_list_id", "")
    raw     = sys.argv[1] if len(sys.argv) > 1 else ""

    # First arrival from the list passes its arg through; normalise to empty.
    # "tags" is the routing sentinel the everything_search list row sends so the
    # conditional's Tags branch fires — it isn't a real tag-filter query.
    if raw in (list_id, "tags") or raw.startswith("open:"):
        raw = ""

    # Recover list_id from the temp file if env was lost (e.g. via go-back ET).
    if not list_id:
        try:
            with open("/tmp/ticktick_reattribute.txt") as _f:
                parts = _f.read().strip().split(":", 1)
                if parts and parts[0]:
                    list_id = parts[0]
        except Exception:
            pass

    try:
        all_tasks = get_tasks(list_id)
        tags      = set(tag_counts(all_tasks).keys())

        # Screen 2 once a known tag is committed (tag followed by a space).
        first, sep, rest = raw.partition(" ")
        if sep and first in tags:
            render_tasks(list_id, all_tasks, first, rest.strip())
        else:
            render_tags(list_id, all_tasks, raw.strip())

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
