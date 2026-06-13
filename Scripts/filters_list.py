#!/usr/bin/env python3
"""
filters_list.py — Alfred Script Filter
Displays user-defined filters from filters_config.py.
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
    sys.path.insert(0, WORKFLOW_DIR)
except Exception as e:
    emit_error(f"Path setup failed: {e}")
    sys.exit(0)

# ── Imports ──────────────────────────────────────────────────────────────────
try:
    import alfred
    import fuzzy as fuzz
    from filters_config import FILTERS
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""

    try:
        if not FILTERS:
            print(alfred.output([alfred.item(
                title="No filters defined",
                subtitle="Run 'Edit filters' to add your filters",
                valid=False,
            )], skipknowledge=True))
            return

        items = []
        for i, f in enumerate(FILTERS):
            name = f.get("name", f"Filter {i+1}")
            criteria_parts = []
            if f.get("tags"):
                t = f["tags"]
                if isinstance(t, list):
                    criteria_parts.append("tags (all): " + ", ".join(t))
                else:
                    criteria_parts.append(f"tags: {t}")
            if f.get("any_tags"):
                criteria_parts.append("tags (any): " + ", ".join(f["any_tags"]))
            if f.get("priority"):
                labels = {0: "none", 1: "low", 3: "medium", 5: "high"}
                criteria_parts.append("priority: " + ", ".join(labels.get(p, str(p)) for p in f["priority"]))
            if f.get("projects"):
                criteria_parts.append("lists: " + ", ".join(f["projects"]))
            if f.get("due_before"):
                criteria_parts.append(f"due before {f['due_before']}")
            if f.get("due_after"):
                criteria_parts.append(f"due after {f['due_after']}")
            if f.get("no_date"):
                criteria_parts.append("no date")

            subtitle = "  ".join(criteria_parts) + "  |  ⏎ ⤵️  ⌘ 🗑️  ⌘⇧ 🔙" if criteria_parts else "⏎ ⤵️  ⌘ 🗑️  ⌘⇧ 🔙"

            items.append(alfred.item(
                uid=f"filter-{i}",
                title=name,
                subtitle=subtitle,
                arg="",
                mods={
                    "cmd": {"arg": f"delete:{str(i)}", "subtitle": f"Delete {name}"},
                },
                variables={"filter_index": str(i)},
            ))

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

        if not items:
            items.append(alfred.item(
                title=f'No filters matching "{query}"',
                valid=False,
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
