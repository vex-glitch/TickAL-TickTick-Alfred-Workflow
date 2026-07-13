#!/usr/bin/env python3
"""
open_links.py - Alfred Script Filter

Lists the web links found in a task's description (and title) so you can open
one. Reached from the ⌘ Actions menu:
    actions.py emits arg "links" ▸ conditional "LINKS" ▸ ET "attributeLinks"
    ▸ ensure_task_context.py ▸ this filter.

Each row emits  open:<url>  - which rides the existing OPEN routing
(conditional ▸ modOpen ▸ `open "$URL"`), so no executor script is needed.
Wire this Script Filter's output to a Call External Trigger "modOpen"
(passinputasargument ON).

Task descriptions aren't kept in the offline cache (only notes are), so we read
content from the cache when present and otherwise do a single api.get_task()
fetch. Links of any scheme - web, app (obsidian://…), file://, ticktick:// - are
surfaced, since macOS `open` handles them all.
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
    import alfred
    import fuzzy as fuzz
    import cache as cache_store
    import config as cfg
    import links as links_util
    from api import TickTickAPI
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)


def main():
    list_id    = os.environ.get("task_list_id") or os.environ.get("list_id", "")
    tid        = os.environ.get("task_id", "")
    task_title = os.environ.get("task_title", "task")
    query      = sys.argv[1] if len(sys.argv) > 1 else ""

    # Go-back loop fallback (mirrors change_reminder.py)
    if not list_id or not tid:
        try:
            with open("/tmp/ticktick_reattribute.txt") as _f:
                _parts = _f.read().strip().split(":", 1)
                if len(_parts) == 2:
                    list_id, tid = _parts[0], _parts[1]
        except Exception:
            pass

    # No back chip: this Script Filter has NO ctrl (or any back) edge on the
    # canvas - the old "⌘⇧ 🔙" advertised a chord that never existed.
    # Wire a real ⌃ back before re-adding a chip.
    back = ""

    try:
        # Content: cache first (notes carry it), then one network fetch for tasks.
        task    = cache_store.find_task(tid) if tid else None
        content = ((task or {}).get("content") or "").strip()
        scan_title = (task or {}).get("title") or task_title
        if not content and list_id and tid:
            try:
                full       = TickTickAPI(cfg.get_token()).get_task(list_id, tid)
                content    = (full.get("content") or "").strip()
                scan_title = full.get("title") or scan_title
            except Exception:
                pass  # offline / rate-limited → fall through to whatever we have

        links = links_util.extract_links(f"{scan_title}\n{content}")

        if not links:
            emit([alfred.item(
                title="No links in this item",
                subtitle=f"Add via URL hotkey or =note{back}",
                valid=False,
            )])
            return

        items = [
            alfred.item(
                title=label,
                subtitle=f"{url}{back}",
                arg=f"open:{url}",
                variables={"task_list_id": list_id, "task_id": tid,
                           "task_title": task_title},
                # ⌘⏎ copies the URL instead of opening it. Wire the picker's ⌘
                # output to a Call External Trigger "modURL" - the same chain
                # "Copy link" uses (→ copy_url_action.py → End → notification).
                mods={"cmd": {"arg": f"copy:{url}",
                              "subtitle": f"⌘ Copy  {url}"}},
            )
            for label, url in links
        ]

        if query:
            items = fuzz.filter_and_score(
                query, items, key_fn=lambda x: f'{x["title"]} {x["subtitle"]}')
        if not items:
            items = [alfred.item(title=f'No link matching "{query}"', valid=False)]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
