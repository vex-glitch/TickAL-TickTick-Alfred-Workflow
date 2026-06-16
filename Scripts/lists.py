#!/usr/bin/env python3
"""
lists.py — Alfred Script Filter
Displays TickTick lists. If folder_id env var is set, filters by folder (groupId).
If not set, shows all lists (acts as a root-level list browser).
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
    from display import build_subtitle
except Exception as e:
    emit_error(f"Import failed: {e} | SRC_DIR={SRC_DIR}")
    sys.exit(0)

# ── Data ─────────────────────────────────────────────────────────────────────
def get_projects():
    data = cache_store.get("projects")
    if data is None:
        data = TickTickAPI(cfg.get_token()).get_projects()
        cache_store.set("projects", data)
    return sorted(
        [p for p in data if p.get("kind") != "SMART_LIST"],
        key=lambda p: p.get("sortOrder", 0)
    )

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    folder_id = os.environ.get("folder_id", "")
    query     = sys.argv[1] if len(sys.argv) > 1 else ""

    # When triggered via ET (go back from sections), env vars are gone.
    # Recover folder_id from temp file written by the go-back Run Script.
    if not folder_id:
        try:
            with open("/tmp/ticktick_reattribute.txt") as _f:
                _parts = _f.read().strip().split(":", 1)
                if len(_parts) >= 1 and _parts[0]:
                    folder_id = _parts[0]
        except Exception:
            pass

    try:
        all_projects = get_projects()

        if folder_id:
            projects = [p for p in all_projects if p.get("groupId") == folder_id]
        else:
            projects = all_projects

        items = []

        for p in projects:
            pid  = p["id"]
            name = p["name"]
            link = f"ticktick:///webapp/#p/{pid}/tasks"

            cached = cache_store.get(f"project_data_{pid}")
            section_count = len(cached.get("columns", [])) if cached else 0

            items.append(alfred.item(
                uid=f"list-{pid}",
                title=name,
                subtitle=build_subtitle(section_count, child_label="Section", actions=True),
                arg=f"open:{link}",
                mods={
                    "cmd": {
                        "arg": "",
                    },
                    "alt": {
                        "arg": "",
                    },
                    "alt+shift": {
                        "arg": "",
                    },
                    "alt+cmd": {
                        "arg": f"copy:{link}",
                    },
                },
                variables={"item_type": "list", "list_id": pid, "list_name": name, "folder_id": folder_id},
            ))

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

        if not items:
            items.append(alfred.item(
                uid="no-results",
                title=f'No lists matching "{query}"' if query else ("No lists in this folder" if folder_id else "No lists — run Sync first"),
                valid=False,
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
