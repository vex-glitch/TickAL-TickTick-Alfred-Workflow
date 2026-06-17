#!/usr/bin/env python3
"""
crm_menu.py — Alfred Script Filter (the 🔥CRM hub)

The CRM hotkey / "CRM…" main-menu row opens this: two options, both scoped to the
🔥CRM list (its id rides on as a variable). Type "a" / "s" to pick (fuzzy).

  • Add    → arg "add"  → ET "Add" with list_id=CRM → the normal add flow pinned
             to CRM: auto-attaches a clipboard image, the [[ picker scopes to CRM
             bookings, and a booking tag triggers the "Prepare for …" follow-up.
  • Search → arg "tags" → the tag-drill (drill_tags.py) scoped to CRM. "tags" is
             the sentinel drill_tags already normalises to an empty query.

Wiring: this filter's output → a Conditional — add → ET "Add", tags → the
drill/tags ET — both passing variables (so list_id reaches the target).
"""
import sys
import os
import json
import re

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

CRM_ID   = "69fed9d51fe6d10d8510bf15"
CRM_NAME = "🔥CRM"
# item_type=list marks this as "adding INTO the CRM list" — so the add window
# shows "Adding to 🔥CRM" (not the generic / create-a-list/note/project hint) and
# the / menu offers task attributes, not the top-level creation modes.
CRM_VARS = {"list_id": CRM_ID, "task_list_id": CRM_ID, "list_name": CRM_NAME,
            "item_type": "list"}


def build_items():
    return [
        alfred.item(
            uid="crm-add",
            title="Add",
            subtitle="New booking in 🔥CRM — clipboard image, [[ links, and a Prepare follow-up",
            arg="add",
            variables=CRM_VARS,
        ),
        alfred.item(
            uid="crm-search",
            title="Search",
            subtitle="Drill 🔥CRM by tag",
            arg="tags",
            variables=CRM_VARS,
        ),
    ]


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    stripped = raw.strip()
    # Treat Alfred placeholder values (e.g. "…", "...") as empty, like main_menu.py.
    query = stripped if re.search(r'[a-zA-Z0-9]', stripped) else ""
    try:
        items = build_items()
        if query:
            # Narrow only when a real term actually matches — a 2-row menu should
            # never disappear, so an empty filter result falls back to all rows.
            filtered = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])
            if filtered:
                items = filtered
        print(alfred.output(items, skipknowledge=True))
    except Exception as e:
        import traceback
        print(json.dumps({"items": [{
            "title": "Error in crm_menu.py",
            "subtitle": f"{type(e).__name__}: {e}  |  {traceback.format_exc()}",
            "valid": False,
        }]}))


if __name__ == "__main__":
    main()
