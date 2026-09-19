#!/usr/bin/env python3
"""meal_notes.py - the weekly note's 🥘 Meal prep bullet (PURE over a
periodic_sections doc; the engine's _pn_rmw does the I/O).

The bullet lives under `##### 💿 Data` of the weekly note (Vex 2026-09-19:
the plan lands on the Sunday routine AND in the weekly note). Its body is
three plain bullets, one per meal, the Mela link LAST on the line and no
checkbox: focus_blocks' LINK_TAIL_RE reads only ticktick task URLs, so
these lines are display, never swept or ticked (HANDOFF_ROUTINES §9).

Kill switch, the periodic-note contract: a note without the bullet is
skipped - EXCEPT a note minted before the feature shipped (meal.NOTE_SINCE),
which never had one: there the bullet is seeded once at the end of 💿 Data,
because "he deleted it" cannot be what a bullet that never existed means.
"""
from datetime import date, datetime

import meal
import periodic_model as pm
import periodic_sections as ps

BULLET = "- " + pm.SEC_MEALPREP


def block_lines(picks):
    """['- 🍳 [Name](mela://recipe/ID)', '- 🍛 …', '- 🌮 …'] from
    {key: {name, uuid}}; a missing slot reads '- 🍳 _(not planned)_'."""
    out = []
    for key, _tag, glyph, _label in meal.SLOTS:
        p = picks.get(key) or {}
        if p.get("uuid"):
            out.append(f"- {glyph} {meal.md_link(p.get('name', ''), p['uuid'])}")
        else:
            out.append(f"- {glyph} _(not planned)_")
    return out


def _created_day(live):
    """The note's creation day from a live task dict, else None."""
    raw = (live or {}).get("createdTime") or ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")
                                      .replace("+0000", "+00:00")).date()
    except (ValueError, TypeError, AttributeError):
        return None


def write_block(doc, lines, live=None, since=meal.NOTE_SINCE):
    """Put `lines` under the 🥘 bullet of the 💿 Data group. True when the
    doc changed. False when the bullet is absent (kill switch), unless the
    note predates `since` - then the bullet is seeded first. A note without
    a 💿 Data group at all (an older layout) is never touched."""
    sec = ps.find(doc, pm.SEC_MEALPREP, within=pm.SEC_WK_DATA)
    if sec is not None and sec.name != pm.SEC_MEALPREP:
        return False
    if sec is None:
        made = _created_day(live)
        if made is None or made >= since:
            return False
        group = ps.find(doc, pm.SEC_WK_DATA)
        if group is None or isinstance(group, ps.Block):
            return False
        if not ps.append_body(doc, pm.SEC_WK_DATA, ["", BULLET]):
            return False
        sec = ps.find(doc, pm.SEC_MEALPREP, within=pm.SEC_WK_DATA)
        if sec is None:
            return False
    # a Block's body is stored re-based (tab-indented): compare the words,
    # or an identical write reads as a change on every commit
    want = [l.strip() for l in lines if l.strip()]
    have = [l.strip() for l in sec.body if l.strip()]
    if want == have:
        return False
    return ps.set_sec_body(doc, sec, list(lines))


def read_block(doc):
    """The bullet's current lines (unescaped), [] when absent."""
    sec = ps.find(doc, pm.SEC_MEALPREP, within=pm.SEC_WK_DATA)
    if sec is None:
        return []
    return [pm.unescape_md(l).strip() for l in sec.body if l.strip()]
