#!/usr/bin/env python3
"""
main_menu.py — Alfred Script Filter
Main entry point for the TickTick workflow.
Replaces the static List Filter to enable modifier key support on Calendar.

Args passed to Alfred:
  search   → Call ET 1Search
  cal      → Open Calendar (default view)
  cal_d    → Open Calendar → Day view
  cal_w    → Open Calendar → Week view
  cal_m    → Open Calendar → Month view
  cal_y    → Open Calendar → Year view
  view     → Call ET 1Smart
  filters  → Call ET 1Filters
  open     → Call ET 1Open
  add      → Call ET 1Add
  drill    → Call ET 1Drill
  update   → Call ET 1Update
"""
import sys
import os
import json

# ── Path setup ───────────────────────────────────────────────────────────────
try:
    SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
    WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
    SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
    sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
    sys.path.insert(0, SRC_DIR)
except Exception as e:
    print(json.dumps({"items": [{"title": "Path error", "subtitle": str(e), "valid": False}]}))
    sys.exit(0)

try:
    import alfred
    import fuzzy as fuzz
except Exception as e:
    print(json.dumps({"items": [{"title": "Import error", "subtitle": str(e), "valid": False}]}))
    sys.exit(0)

# ── Menu items ────────────────────────────────────────────────────────────────
def build_items():
    return [
        alfred.item(
            uid="search",
            title="Search",
            subtitle="Choose the criteria",
            arg="search",
        ),
        alfred.item(
            uid="calendar",
            title="Calendar...",
            subtitle="Open  ⌃ Year  ⌥ Month  ⌘⇧ Day  ⇧ Week",
            arg="cal",
            mods={
                "cmd+shift": {"arg": "cal_1", "subtitle": "Open Day view"},
                "shift":     {"arg": "cal_w", "subtitle": "Open Week view"},
                "alt":       {"arg": "cal_m", "subtitle": "Open Month view"},
                "ctrl":      {"arg": "cal_y", "subtitle": "Open Year view"},
            },
        ),
        alfred.item(
            uid="view",
            title="View...",
            subtitle="Choose...  Browse: ⇧ Today  ⌘ Tmrw  ⌥ 7D  ⌃ Inbox  —  Open: ⌘⇧ Today  ⌥⌘ Tmrw  ⌃⌥ 7D  ⌃⇧ Inbox",
            arg="view",
            mods={
                "shift":     {"arg": "view_today",    "subtitle": "Browse Today"},
                "cmd":       {"arg": "view_tomorrow", "subtitle": "Browse Tomorrow"},
                "alt":       {"arg": "view_7",        "subtitle": "Browse 7 Days"},
                "ctrl":      {"arg": "view_inbox",    "subtitle": "Browse Inbox"},
                "cmd+shift": {"arg": "open:ticktick://v1/show?smartlist=today",    "subtitle": "Open Today"},
                "cmd+alt":   {"arg": "open:ticktick://v1/show?smartlist=tomorrow", "subtitle": "Open Tomorrow"},
                "ctrl+alt":  {"arg": "open:ticktick://v1/show?smartlist=next_7_days", "subtitle": "Open 7 Days"},
                "ctrl+shift":{"arg": "open:ticktick:///webapp/#p/inbox/tasks",       "subtitle": "Open Inbox"},
            },
        ),
        alfred.item(
            uid="filters",
            title="Filters...",
            subtitle="View filters and act on them",
            arg="filters",
        ),
        alfred.item(
            uid="add",
            title="Add...",
            subtitle="Task, list, note, project",
            arg="add",
        ),
        alfred.item(
            uid="drill",
            title="Drill",
            subtitle="Drill Sergeant",
            arg="drill",
        ),
        alfred.item(
            uid="update",
            title="Update",
            subtitle="Sync, set filters, set tags...",
            arg="update",
        ),
        alfred.item(
            uid="tt_quick_add",
            title="Quick Add",
            subtitle="TickTick quick add window",
            arg="tts:quick_add",
        ),
        alfred.item(
            uid="tt_mini_window",
            title="Mini Window",
            subtitle="TickTick mini window",
            arg="tts:mini_window",
        ),
        alfred.item(
            uid="tt_pomo",
            title="Pomodoro",
            subtitle="TickTick Pomodoro timer",
            arg="tts:pomo",
        ),
        alfred.item(
            uid="tt_sticky",
            title="Sticky Note",
            subtitle="TickTick sticky note",
            arg="tts:sticky",
        ),
    ]

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    stripped = raw.strip()
    # Treat Alfred placeholder values (e.g. "...", "…") as empty
    import re
    query = stripped if re.search(r'[a-zA-Z0-9]', stripped) else ""

    try:
        items = build_items()

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

        if not items:
            items = [alfred.item(
                title=f'No options matching "{query}"',
                valid=False,
            )]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        import traceback
        print(json.dumps({"items": [{
            "title": "Error in main_menu.py",
            "subtitle": f"{type(e).__name__}: {e}  |  {traceback.format_exc()}",
            "valid": False,
        }]}))


if __name__ == "__main__":
    main()
