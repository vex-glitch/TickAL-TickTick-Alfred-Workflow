#!/usr/bin/env python3
"""
crm_menu.py - Alfred Script Filter (THE home, keyword/hotkey entry)

The CRM hotkey / "CRM / Content Pipeline…" main-menu row opens this. Since
2026-07-28 it is the UNIFIED home: CRM and Content stopped being two
workflows, and this screen and the in-browse home (browse.py ctx:crmhub)
render the SAME seven rows from ONE table, src/crm_home.py.

  📅 Calendar · 🎨 Logbooks · 👥 Customers · 🎬 Pipelines
  🎛 Manage   · 💰 Money    · 📊 Stats

Add a row to crm_home.ROWS + HOME_ORDER and it lands in both homes; edit a
renderer instead and they drift (which is exactly what happened before the
table existed). Subtitles come from crm_home.subtitles() - live counts, cache
only, every row independently guarded.

Wiring: this filter's output → a Conditional. ctx rows carry arg "tags" +
browse_ctx=<ctx> and take the BROWSE branch (browse.py reads browse_ctx;
"tags" only routes the conditional, the ET call drops it). xact rows pass
their verb straight through. Both branches pass variables, so list_id and
browse_ctx reach the target. The raw "Add" row is RETIRED (2026-07-17): an
unlinked CRM task is an orphan.
"""
import sys
import os
import json
import re

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
    import alfred
    import fuzzy as fuzz
    import areas
except Exception as e:
    print(json.dumps({"items": [{"title": "Import error", "subtitle": str(e), "valid": False}]}))
    sys.exit(0)

CRM_ID   = areas.CRM_ID          # from the Configure panel; empty = dormant
CRM_NAME = areas.crm_list_name()
# item_type=list marks this as "adding INTO the CRM list" - so the add window
# shows "Adding to 🔥CRM" (not the generic / create-a-list/note/project hint) and
# the / menu offers task attributes, not the top-level creation modes.
CRM_VARS = {"list_id": CRM_ID, "task_list_id": CRM_ID, "list_name": CRM_NAME,
            "item_type": "list"}




def _records_row(uid, title, subtitle, ctx):
    """Records rows ride the conditional's BROWSE branch (arg 'tags') with the
    real destination in browse_ctx - zero canvas. The picker's ⏎ args are
    xact:* verbs (dialog chains); see browse.py ctx:crmnew/crmdone/crmlog."""
    return alfred.item(uid=uid, title=title, subtitle=subtitle, arg="tags",
                       variables={**CRM_VARS, "browse_ctx": ctx})


def build_items():
    if not areas.crm_configured():
        # Dormant until crm_list_id is set in Configure Workflow - the one row
        # opens the setup guide (arg routes via the ^open conditional branch).
        return [alfred.item(**areas.setup_row("CRM", "47-crm.md"))]
    # The raw "Add" row is RETIRED (smoke ruling 2026-07-17): an unlinked CRM
    # task is an orphan - everything enters through a records flow now, and
    # dormant hand-adds get scheduled + linked via 📅 Schedule.
    if not areas.records_configured():
        return [alfred.item(**areas.setup_row("CRM records", "47-crm.md"))]
    # ONE source of truth with the crmhub screen: src/crm_home.py
    # (Vex simplification green 2026-07-26 - the two homes had drifted
    # four rows apart each). ctx rows ride the conditional's BROWSE
    # branch; xact rows go straight through.
    import crm_home
    rows = []
    for uid, title, subtitle, kind, val in crm_home.rows_for(
            crm_home.MENU_ORDER, crm_home.MENU_UIDS, "crm-"):
        if kind == "ctx":
            rows.append(_records_row(uid, title, subtitle, val))
        else:
            rows.append(alfred.item(uid=uid, title=title,
                                    subtitle=subtitle, arg=val,
                                    variables=CRM_VARS))
    return rows


# Back is ⌃ everywhere - stamp the ⌃ back-mod on every emitted row
# (mod-level valid=True lets it fire even from invalid prompt/hint rows).
_orig_output = alfred.output
def _output_backstamped(items, **kw):
    for _it in items:
        _it.setdefault("mods", {}).setdefault("ctrl", {"valid": True, "arg": "", "subtitle": "🔙 Main menu"})
    return _orig_output(items, **kw)
alfred.output = _output_backstamped


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    stripped = raw.strip()
    # Treat Alfred placeholder values (e.g. "…", "...") as empty, like main_menu.py.
    query = stripped if re.search(r'[a-zA-Z0-9]', stripped) else ""
    try:
        items = build_items()
        if query:
            # Narrow only when a real term actually matches - a 2-row menu should
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
