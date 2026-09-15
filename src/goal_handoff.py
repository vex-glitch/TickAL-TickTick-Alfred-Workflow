"""goal_handoff.py - a journal paused at its goal question, waiting on the picker.

Vex 2026-09-15: the evening journal asks for TOMORROW's goal and the morning
journal checks TODAY's, both through the ☀️ goal picker - text, a task, or
both. The journal is a chain of dialogs and a dialog cannot host Alfred's
picker, so the journal stops at that question, writes this file, and opens
the picker. The pick (or "⏭ No goal") reads it back: which journal, which
note day, and which day the goal is FOR; then it answers the question and
reopens the journal, which skips everything already answered.

Expires after TTL: an Esc in the picker never comes back. The journal goal
screen never falls back to the ordinary picker when it has expired - that
would set TODAY's goal from tomorrow's question (review 2026-09-15).

Skips: an empty OK skips a question for the rest of the run, and the run now
spans the picker, so the skipped questions ride along (remember_skips /
take_skips) instead of being asked again on the resume.
"""
import json
import os
import time
from datetime import date, timedelta

from script_base import run_path

TTL = 3 * 3600
_PATH = None
_SKIPS = None


def _path():
    global _PATH
    if _PATH is None:
        _PATH = run_path("tickal_pn_goaljnl.json")
    return _PATH


def for_day(slot, note_day):
    """The day a journal's goal question is about: the evening asks for the
    day after its note, the morning for its own."""
    return note_day + timedelta(days=1) if slot == "evening" else note_day


def save(slot, note_day, mode="set", now=None):
    """mode: "set" (no goal yet) | "changed" (the morning's Change… button)."""
    state = {"slot": slot, "note_day": note_day.isoformat(),
             "for_day": for_day(slot, note_day).isoformat(), "mode": mode,
             "ts": now if now is not None else time.time()}
    try:
        with open(_path(), "w") as f:
            json.dump(state, f)
    except OSError:
        return None
    return state


def load(now=None):
    """The live handoff | None (missing, unreadable, or older than TTL)."""
    try:
        with open(_path()) as f:
            d = json.load(f)
        if (now if now is not None else time.time()) - float(d.get("ts", 0)) > TTL:
            return None
        if d.get("slot") not in ("morning", "evening"):
            return None
        d["note_day"] = date.fromisoformat(d["note_day"])
        d["for_day"] = date.fromisoformat(d["for_day"])
        d["mode"] = "changed" if d.get("mode") == "changed" else "set"
        return d
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _skips_path():
    global _SKIPS
    if _SKIPS is None:
        _SKIPS = run_path("tickal_pn_goaljnl_skips.json")
    return _SKIPS


def remember_skips(slot, note_day, questions, now=None):
    """Add question texts skipped in this run of (slot, note_day)."""
    key = f"{slot}@{note_day.isoformat()}"
    data = _read_skips(now)
    have = data.get(key, {}).get("q", [])
    data[key] = {"q": have + [q for q in questions if q not in have],
                 "ts": now if now is not None else time.time()}
    try:
        with open(_skips_path(), "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def take_skips(slot, note_day, now=None):
    """The skipped question texts of (slot, note_day), removed as read."""
    key = f"{slot}@{note_day.isoformat()}"
    data = _read_skips(now)
    out = data.pop(key, {}).get("q", [])
    try:
        with open(_skips_path(), "w") as f:
            json.dump(data, f)
    except OSError:
        pass
    return out


def _read_skips(now=None):
    now = now if now is not None else time.time()
    try:
        with open(_skips_path()) as f:
            data = json.load(f)
        return {k: v for k, v in data.items()
                if isinstance(v, dict) and now - float(v.get("ts", 0)) <= TTL}
    except (OSError, ValueError, TypeError):
        return {}


def clear():
    try:
        os.remove(_path())
    except OSError:
        pass


def answer_text(slot, outcome, goal=""):
    """The journal answer a pick leaves. outcome: set | kept | changed | skip."""
    goal = (goal or "").strip()
    if outcome == "skip":
        return "⏭ No goal set"
    if outcome == "kept":
        return f"✅ Kept: {goal}"
    if outcome == "changed":
        return f"🔄 Changed to: {goal}"
    return f"🎯 {goal}"
