#!/usr/bin/env python3
"""
sync.py — called by Alfred (Update → Sync) to refresh all caches from the TickTick API.
"""
import sys
import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "lib"))

import config as cfg
import cache as cache_store
from api import TickTickAPI


def do_sync():
    """Refresh all caches from TickTick API. Prints a one-line status."""
    api = TickTickAPI(cfg.get_token())

    # Fetch projects first — if API is unreachable/rate-limited, bail before touching cache
    projects = api.get_projects()

    # Overwrite projects — no full cache wipe so search keeps working during sync
    cache_store.set("projects", projects)

    # Inbox is a special project not returned by /project — fetch it separately
    all_tasks = []
    try:
        inbox_data = api.get_project_data("inbox")
        cache_store.set("project_data_inbox", inbox_data)
        inbox_tasks = inbox_data.get("tasks", [])
        for t in inbox_tasks:
            t["_projectName"] = "Inbox"
            t["_projectId"]   = "inbox"
            t["_columnName"]  = ""
        all_tasks.extend(inbox_tasks)
    except Exception:
        pass  # inbox unavailable, non-fatal

    errors = 0
    for p in projects:
        if p.get("kind") == "SMART_LIST":
            continue
        try:
            pdata = api.get_project_data(p["id"])
            tasks = pdata.get("tasks", [])
            col_map = {c["id"]: c.get("name", "")
                       for c in (pdata.get("columns", []) or [])}
            for t in tasks:
                t["_projectName"] = p["name"]
                t["_projectId"]   = p["id"]
                t["_columnName"]  = col_map.get(t.get("columnId") or "", "")
            all_tasks.extend(tasks)
            cache_store.set(f"project_data_{p['id']}", pdata)
        except Exception:
            errors += 1

    cache_store.set("all_tasks", all_tasks)

    # Notes — two sources:
    # 1. NOTE-kind projects (dedicated note lists)
    # 2. kind==NOTE tasks inside regular task projects (e.g. a note in Shopping list)
    all_notes = []
    seen_note_ids = set()

    # Source 1: NOTE-kind projects
    for p in projects:
        if p.get("kind") != "NOTE":
            continue
        try:
            pdata = api.get_project_data(p["id"])
            notes = pdata.get("tasks", [])
            for n in notes:
                n["_projectName"] = p["name"]
                n["_projectId"]   = p["id"]
                seen_note_ids.add(n["id"])
            all_notes.extend(notes)
        except Exception:
            pass

    # Source 2: kind==NOTE items that appeared in regular project task lists
    for t in all_tasks:
        if t.get("kind") == "NOTE" and t["id"] not in seen_note_ids:
            all_notes.append(t)
            seen_note_ids.add(t["id"])

    # Enrich notes with content — bulk project data doesn't return note bodies.
    # Fetch each note individually only when content is missing.
    enriched = []
    for n in all_notes:
        if not (n.get("content") or "").strip():
            npid = n.get("projectId") or n.get("_projectId", "")
            nid  = n.get("id", "")
            if npid and nid:
                try:
                    full = api.get_task(npid, nid)
                    n = {**n, "content": full.get("content") or ""}
                except Exception:
                    pass
        enriched.append(n)
    all_notes = enriched

    cache_store.set("all_notes", all_notes)

    # Tags — zero setup: the v2 tag tree is the source of truth
    # (TickTick's own list + order, which also drives group-by-tag sections);
    # tags discovered on tasks append after. Tokenless installs run on the
    # discovered set alone — new tags are creatable from the pickers.
    discovered = {tag for t in all_tasks for tag in (t.get("tags") or [])}

    tree, has_v2 = [], False
    try:
        import api_v2
        _v2 = api_v2.TickTickV2()
        has_v2 = bool(_v2.token)
        if has_v2:
            tree = _v2.get_tags()
            if tree is None:
                # transient fetch failure → keep last-known-good tree so
                # zero-usage tags don't vanish from the cache for an hour
                tree = cache_store.get("tags_tree") or []
            elif tree:
                cache_store.set("tags_tree", tree)
            else:
                cache_store.set("tags_tree", [])   # truly tag-less account
        else:
            # Token removed → the v2 caches must stop ghost-ruling the UI.
            cache_store.set("tags_tree", [])
            cache_store.set("folder_groups", [])
            cache_store.set("filters_v2", [])
    except Exception:
        tree = []

    if tree:
        base = [t.get("label") or t.get("name", "")
                for t in sorted(tree, key=lambda t: t.get("sortOrder") or 0)]
        base = [b for b in base if b]
    else:
        base = []
    # Case-insensitive dedup — prevents "🔥Ongoing" + "🔥ongoing" duplicates.
    seen = {t.lower() for t in base}
    extra = sorted(t for t in discovered if t.lower() not in seen)
    all_tags = base + extra
    cache_store.set("tags", all_tags)

    # Folders + native filters via ONE v2 sync-meta call — the open API
    # returns bare group ids and no filters at all. config.get_folders()
    # overlays manual names on the folder_groups cache; filtering.load_filters
    # prefers the translated filters_v2 cache. Best-effort, never fails sync.
    try:
        # get_sync_meta: dict on success (empty lists ARE the account's
        # truth — folder-less / filter-less), None on failure (keep the
        # last-known-good caches).
        meta = _v2.get_sync_meta() if has_v2 else None
        if meta is not None:
            cache_store.set("folder_groups", meta["groups"])
            import filtering
            cache_store.set("filters_v2",
                            filtering.translate_native(meta["filters"], projects))
    except Exception:
        pass

    # Completed list = server truth via the same v2 session — the Open API
    # can't list completed tasks, and the old local snapshots only knew
    # completions made THROUGH the workflow, so counts ran far too low.
    # Best-effort.
    try:
        import api_v2
        v2c = api_v2.TickTickV2()
        if v2c.token:
            pname = {p["id"]: p.get("name", "") for p in projects}

            def _enrich(ts):
                for t in ts:
                    dpid = t.get("projectId", "")
                    t["_projectName"] = pname.get(
                        dpid, "Inbox" if str(dpid).startswith("inbox") else "")
                return ts

            done = v2c.get_completed(days=60, limit=200)
            if isinstance(done, list) and done:
                cache_store.set("completed_tasks", _enrich(done))
            # Won't Do twin — None = fetch failed (keep last-known-
            # good); [] is the account's truth and DOES clear the cache
            wontdo = v2c.get_abandoned(days=60, limit=200)
            if isinstance(wontdo, list):
                cache_store.set("wontdo_tasks", _enrich(wontdo))
    except Exception:
        pass

    summary = f"Synced {len(projects)} lists, {len(all_tasks)} tasks, {len(all_notes)} notes, {len(all_tags)} tags"
    if errors:
        summary += f" ({errors} list(s) failed)"
    print(summary)
    return summary


def _notify(text, title="TickAL sync"):
    """macOS notification so the hourly background sync is visible. Routed
    through Alfred's notification chain — launchd osascript banners were
    silently eaten by Notification-Center permissions."""
    from script_base import notify
    notify(text, title=title)


def main():
    # Alfred's manual Update→Sync already surfaces stdout as a notification;
    # only headless runs (the hourly LaunchAgent) need their own.
    headless = not os.environ.get("alfred_version")
    try:
        summary = do_sync()
        if headless:
            _notify(summary or "Synced")
    except Exception as e:
        print(f"Sync error: {e}")
        if headless:
            _notify(f"Sync FAILED: {e}", title="TickAL sync ⚠️")


if __name__ == "__main__":
    main()
