#!/usr/bin/env python3
"""
tag_manager.py - Alfred Script Filter
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
    import config as cfg
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
    import areas
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

def back_mod(pid, tid):
    """⌃⇧ back must work even on invalid rows - a mod-level valid=True
    overrides the row's valid=False (Alfred ignores action chords on invalid
    rows). Mod variables REPLACE item-level ones, so carry the full context."""
    return {"ctrl": {"valid": True, "arg": "",
                           "subtitle": "🔙 Back to ⌘ Actions",
                           "variables": {"task_list_id": pid,
                                         "task_id": tid}}}

# ── Scope detection ──────────────────────────────────────────────────────────
def detect_mode(raw_query):
    """
    Returns ('add', fragment) for a # prefix, ('current', query) otherwise.
    Bare '#' and '#frag' land straight in the add dropdown - the old
    space-gate hint row ("Space after # to search") made every entry a
    two-step.
    """
    q = raw_query
    if q.startswith("# "):
        return "add", q[2:]  # preserve trailing space - parse_add_fragment needs it
    if q.startswith("#"):
        return "add", q[1:]
    return "current", q

# ── Views ─────────────────────────────────────────────────────────────────────
def current_tags_view(query, pid, tid, task_title):
    current = get_current_tags(pid, tid)
    back    = back_mod(pid, tid)

    if not current:
        return [alfred.item(
            title="No tags assigned",
            subtitle="Type # to add a tag  ⌃ 🔙",
            valid=False,
            mods=back,
        )]

    mods_hint = "# Add tag  ⏎ Remove  ⌘⏎ Change  ⌥⏎ Clear all"
    items = []
    for tag in current:
        items.append(alfred.item(
            uid=f"curtag-{tag}",
            title=tag,
            subtitle=f"{mods_hint}  ⌃ 🔙",
            arg=f"attr_tag_remove:{pid}:{tid}:{tag}",
            valid=True,
            mods={
                "cmd":  {"arg": "changetag"},
                "alt": {"arg": f"attr_tag_clear:{pid}:{tid}", "subtitle": "Clear ALL tags"},
                **back,
            },
            variables={"task_list_id": pid, "task_id": tid, "old_tag": tag},
        ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items:
        items = [alfred.item(title=f'No tags matching "{query}"', valid=False,
                             mods=back)]

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
    # 🔥CRM: only the booking tags, same as the CRM add window's # picker.
    # Truthiness guard: CRM unconfigured (CRM_ID "") + empty pid must NOT
    # collapse the picker to the CRM tag group.
    if areas.crm_configured() and pid == areas.CRM_ID:
        crm_lc   = {c.lower() for c in areas.CRM_TAGS}
        all_tags = [t for t in all_tags if t.lower() in crm_lc]
    else:
        # Parent drill: exact parent fragment → its children; parents
        # appear as drill rows (autocomplete keeps them as the live fragment).
        import tagtree
        kids = tagtree.children_of(current_fragment) if current_fragment else []
        if kids:
            all_tags, current_fragment = kids, ""
        else:
            known = {t.lower() for t in all_tags}
            all_tags = all_tags + [p for p in tagtree.parent_labels()
                                   if p.lower() not in known]
    current_tags = get_current_tags(pid, tid)
    current_set  = set(current_tags)
    back         = back_mod(pid, tid)

    items = []

    # ── Confirm item ─────────────────────────────────────────────────────────
    if confirmed:
        tags_display = "  ".join(f"#{t}" for t in confirmed)
        arg_tags     = ",".join(confirmed)
        items.append(alfred.item(
            title=f"Add {len(confirmed)} tag{'s' if len(confirmed) > 1 else ''}: {tags_display}",
            subtitle="⏎ Confirm and close  ⌃ 🔙",
            arg=f"attr_tags_multi:{pid}:{tid}:{arg_tags}",
            valid=True,
            mods=back,
            variables={"task_list_id": pid, "task_id": tid},
        ))

    # ── Available tags ────────────────────────────────────────────────────────
    current_lower = {c.lower() for c in current_set}
    for tag in all_tags:
        if tag in confirmed_set:
            continue  # already queued - hide it
        # ci - task tags are stored lowercase, the cache holds cased v2 labels
        already = tag.lower() in current_lower
        import tagtree
        # Parent drill stays active when CRM is unconfigured (CRM_ID "").
        parent = (not areas.CRM_ID or pid != areas.CRM_ID) and tagtree.is_parent(tag)
        # Build new autocomplete query with this tag appended. Parents are
        # drill rows: NO trailing space, so the tag stays the live fragment
        # and the next render lists its children instead of queueing it.
        if parent:
            new_query = "# " + " ".join(confirmed + [tag.lower()])
            sub = "⏎ show child tags  ⌃ 🔙"
        else:
            new_query = "# " + " ".join(confirmed + [tag]) + " "
            sub = "Already tagged  ⌃ 🔙" if already else "⏎ Queue  ⌃ 🔙"
        item = alfred.item(
            uid=f"addtag-{tag}",
            title=f"#{tag}",
            subtitle=sub,
            arg="",
            valid=False,
            mods=back,
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

    # ➕ new tag: unmatched fragment → queue it anyway; the REAL tag is
    # created at apply time (dispatch._ensure_tags_exist, v2). Not on CRM
    # tasks - their tag family is fixed.
    from display import tag_match_key
    frag_tag = (current_fragment or "").strip().lstrip("#").replace(",", "").replace(":", "")
    if (frag_tag and not (areas.CRM_ID and pid == areas.CRM_ID)
            and tag_match_key(frag_tag) not in {tag_match_key(t) for t in all_tags}
            and frag_tag.lower() not in {c.lower() for c in confirmed}):
        it = alfred.item(
            title=f"➕ #{frag_tag}",
            subtitle="New tag on apply  ⌃ 🔙",
            arg="", valid=False, mods=back,
            variables={"task_list_id": pid, "task_id": tid})
        it["autocomplete"] = "# " + " ".join(confirmed + [frag_tag]) + " "
        items.append(it)

    if not items:
        msg = (f'No tags matching "{current_fragment}"' if current_fragment
               else "No tags cached · run Sync first")
        items = [alfred.item(title=msg, valid=False, mods=back)]

    return items


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

        if mode == "add":
            items = add_tag_view(fragment, pid, tid, task_title)
        else:
            items = current_tags_view(fragment, pid, tid, task_title)

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
