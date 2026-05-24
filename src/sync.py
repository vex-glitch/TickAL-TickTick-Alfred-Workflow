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

    # Extract all unique tags from tasks, merged with tags_config.py (or tags_var env var)
    discovered = {tag for t in all_tasks for tag in (t.get("tags") or [])}
    try:
        import sys as _sys
        _workflow_dir = os.path.dirname(SCRIPT_DIR)
        if _workflow_dir not in _sys.path:
            _sys.path.insert(0, _workflow_dir)
        from tags_config import TAGS as _config_tags
    except Exception:
        # Fall back to tags_var from Alfred Configure panel
        _tags_var = os.environ.get("tags_var", "").strip()
        _config_tags = [t.strip() for t in _tags_var.splitlines() if t.strip()] if _tags_var else []
    # Preserve config order, append discovered tags not already in config.
    # Case-insensitive match — prevents "🔥Ongoing" + "🔥ongoing" duplicates.
    config_lower = {t.lower() for t in _config_tags}
    extra = sorted(t for t in discovered if t.lower() not in config_lower)
    all_tags = list(_config_tags) + extra
    cache_store.set("tags", all_tags)

    summary = f"Synced {len(projects)} lists, {len(all_tasks)} tasks, {len(all_notes)} notes, {len(all_tags)} tags"
    if errors:
        summary += f" ({errors} list(s) failed)"
    print(summary)


def main():
    try:
        do_sync()
    except Exception as e:
        print(f"Sync error: {e}")


if __name__ == "__main__":
    main()
