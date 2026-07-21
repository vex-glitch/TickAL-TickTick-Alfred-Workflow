#!/usr/bin/env python3
"""
bridges.py - 🌉 Bridge notes: pure model (titles, tags, dates, skeletons).

Two kinds (ruled 2026-07-21):
  DAILY   - ONE home list (🌉 Bridges, config bridges_list_id) viewed as a
            kanban board grouped by month tag, sorted by edit date.
            Title "D • Bridge 🌉 YYYY/MM/DD". Carries ONLY the YYMM month
            tag - a second tag would double every card on a tag-grouped
            board, so 🌉bridge stays OFF dailies by design.
  PROJECT - a NOTE living in the project's OWN list (scattered on purpose),
            tagged 🌉bridge, title "P • {Project} • Bridge 🌉 YYYY/MM/DD".

The impure sides live elsewhere: verbs in Scripts/xact.py (bridge_daily /
bridge_proj / bridge_copy), surface in Scripts/browse.py (ctx:bridges),
daily-note fan-out via periodic_engine (### 🌉 Yesterday's bridge).
"""
import re
from datetime import date

BRIDGE_TAG = "🌉bridge"          # lower form - how TickTick stores tag names

# "… Bridge 🌉 2026/07/21" - date tail shared by both title grammars
_DATE_TAIL_RE = re.compile(r"🌉\s*(\d{4})/(\d{2})/(\d{2})\s*$")


def month_tag(d):
    """YYMM ('2607') - alphabetical tag grouping = chronological columns."""
    return d.strftime("%y%m")


def daily_title(d):
    return f"D • Bridge 🌉 {d.strftime('%Y/%m/%d')}"


def project_title(list_name, d):
    """'💼P • Website 4️⃣' → 'P • Website • Bridge 🌉 YYYY/MM/DD'."""
    import areas
    name = (list_name or "").strip()
    if areas.is_project(name):
        name = areas.clean_project_name(name)
    else:
        # plain lists: drop a leading emoji/pictograph cluster, keep the words
        name = re.sub(r"^[^\w]*", "", name).strip() or name
    return f"P • {name} • Bridge 🌉 {d.strftime('%Y/%m/%d')}"


def title_date(title):
    """date from a bridge title's 🌉 YYYY/MM/DD tail, else None."""
    m = _DATE_TAIL_RE.search(title or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def days_ago(d, today=None):
    if d is None:
        return None
    return ((today or date.today()) - d).days


def age_chip(d, today=None):
    """'0d' / '4d' / '' when the title carries no date."""
    n = days_ago(d, today)
    return f"{n}d" if n is not None and n >= 0 else ""


def is_daily(title):
    return (title or "").startswith("D • Bridge 🌉")


def is_bridge_note(note):
    """Tagged project bridge? (dailies are found by LIST, not tag)."""
    tags = {str(t).lower() for t in (note.get("tags") or [])}
    return BRIDGE_TAG in tags


# Skeletons seed a bridge that starts empty (no typed text, empty clipboard) -
# writing against structure beats a blank note.
DAILY_SKEL = ("## Today\n\n\n## Open loops\n\n\n## Tomorrow\n")
PROJ_SKEL  = ("## State\n\n\n## Next\n\n\n## Traps\n")
