#!/usr/bin/env python3
"""
change_tag_picker.py — Alfred Script Filter
Tag picker for adding a tag to a task.
Reads task_id, task_list_id from env vars.
Outputs arg: attr_tag:{list_id}:{task_id}:{tag_name}
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
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    list_id    = os.environ.get("task_list_id", os.environ.get("list_id", ""))
    tid        = os.environ.get("task_id", "")
    task_title = os.environ.get("task_title", "task")
    old_tag    = os.environ.get("old_tag", "")   # set by tag_manager.py when changing
    query      = sys.argv[1] if len(sys.argv) > 1 else ""

    if not list_id or not tid:
        try:
            with open("/tmp/ticktick_reattribute.txt") as _f:
                _parts = _f.read().strip().split(":", 1)
                if len(_parts) == 2:
                    list_id, tid = _parts[0], _parts[1]
        except Exception:
            pass

    try:
        # ⌘⇧ back must work even on invalid rows — a mod-level valid=True
        # overrides the row's valid=False (Alfred ignores action chords on
        # invalid rows). This picker's back leads to the tag manager.
        back_mod = {"ctrl": {"valid": True, "arg": "",
                                  "subtitle": "🔙 Back to tags",
                                  "variables": {"task_list_id": list_id,
                                                "task_id": tid}}}

        tags = cache_store.get("tags") or cfg.get_tags()
        # 🔥CRM: the change picker offers only the booking tags — same scoping
        # as the CRM add window's # picker (Vex ruling 2026-07-06). Truthiness
        # guard: with CRM unconfigured (CRM_ID "") an empty list_id must fall
        # through to the parent-drill branch, not CRM-scope the picker.
        if areas.crm_configured() and list_id == areas.CRM_ID:
            crm_lc = {c.lower() for c in areas.CRM_TAGS}
            tags = [t for t in tags if t.lower() in crm_lc]
        else:
            # Parent drill (Run 3.5): exact parent query → children only;
            # parents also listed as drill rows (never assignable themselves)
            import tagtree
            kids = tagtree.children_of(query) if query else []
            if kids:
                tags, query = kids, ""
            else:
                known = {t.lower() for t in tags}
                tags = list(tags) + [p for p in tagtree.parent_labels()
                                     if p.lower() not in known]
        if not tags and not query:
            # a typed query still reaches the ➕ new-tag row below — the empty
            # cache must not dead-end coining the very first tag
            print(alfred.output([alfred.item(
                title="No tags cached — run sync first",
                valid=False,
                mods=back_mod,
            )], skipknowledge=True))
            return

        replacing = f"Replace #{old_tag} with" if old_tag else "Add tag"

        import tagtree
        items = []
        for tag in tags:
            if tag.lower() == old_tag.lower():
                continue  # skip replacing with the same tag (cache labels are cased)
            if list_id != areas.CRM_ID and tagtree.is_parent(tag):
                # drill row: never assignable — bar becomes the parent name,
                # the next render lists its children
                it = alfred.item(title=f"#{tag}", subtitle="⏎ show child tags  ⌃ 🔙",
                                 arg="", valid=False, mods=back_mod,
                                 variables={"task_list_id": list_id, "task_id": tid,
                                            "old_tag": old_tag})
                it["autocomplete"] = tag.lower()
                items.append(it)
                continue
            items.append(alfred.item(
                title=f"#{tag}",
                subtitle=f"{replacing} #{tag}  ⌃ 🔙",
                arg=tag,
                mods=back_mod,
                variables={"task_list_id": list_id, "task_id": tid, "old_tag": old_tag},
            ))

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])
            # ➕ new tag (R4.2): unmatched query → assignable anyway; the REAL
            # tag is created at exec time (v2). Not on CRM tasks.
            from display import tag_match_key
            frag_tag = query.strip().lstrip("#").replace(",", "").replace(":", "")
            if (frag_tag and list_id != areas.CRM_ID
                    and tag_match_key(frag_tag) not in {tag_match_key(t) for t in tags}):
                items.append(alfred.item(
                    title=f"➕ #{frag_tag}",
                    subtitle=f"{replacing} NEW #{frag_tag}  ⌃ 🔙",
                    arg=frag_tag,
                    mods=back_mod,
                    variables={"task_list_id": list_id, "task_id": tid,
                               "old_tag": old_tag},
                ))

        if not items:
            items.append(alfred.item(
                title=f'No tags matching "{query}"' if query else "No tags — run Sync first",
                subtitle="⌃ 🔙",
                arg="",
                valid=True,
                mods=back_mod,
                variables={"task_list_id": list_id, "task_id": tid},
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
