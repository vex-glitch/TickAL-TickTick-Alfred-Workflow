"""Reminder token ↔ RFC5545 TRIGGER helpers, shared across add / edit / dispatch.

A "token" is the short form the user types or picks (at, 0, 15, 15m, 1h, 2d…).
A "trigger" is what TickTick stores: an RFC5545 string like 'TRIGGER:-PT15M'
(negative = before the due/start time; 'TRIGGER:PT0S' = at the due time).
"""
import re

# token, label, hint — the preset rows shown in the pickers
PRESETS = [
    ("at", "At time",       "when it's due"),
    ("5",  "5 min before",  "5 minutes ahead"),
    ("15", "15 min before", "15 minutes ahead"),
    ("30", "30 min before", "30 minutes ahead"),
    ("1h", "1 hour before",  "1 hour ahead"),
    ("1d", "1 day before",   "1 day ahead"),
]
PRESET_TOKENS = {tok for tok, _, _ in PRESETS}

_TOKEN_RE = re.compile(r'^(\d+)(m|min|mins|h|hr|hrs|hour|hours|d|day|days)?$')


def trigger(token):
    """token (at/0, 15, 15m, 1h, 2d…) → 'TRIGGER:…' string, or None if unparseable."""
    t = (token or "").strip().lower()
    if t in ("at", "0", "ontime", "now"):
        return "TRIGGER:PT0S"
    m = _TOKEN_RE.match(t)
    if not m:
        return None
    n = int(m.group(1))
    if n == 0:
        return "TRIGGER:PT0S"
    unit = (m.group(2) or "m")[0]
    if unit == 'm':
        return f"TRIGGER:-PT{n}M"
    if unit == 'h':
        return f"TRIGGER:-PT{n}H"
    if unit == 'd':
        return f"TRIGGER:-P{n}D"
    return None


def human(token):
    """token → friendly label, e.g. '45 mins before', 'At time'."""
    t = (token or "").strip().lower()
    if t in ("at", "0", "ontime", "now"):
        return "At time"
    m = _TOKEN_RE.match(t)
    if not m:
        return token
    n = int(m.group(1))
    unit = (m.group(2) or "m")[0]
    word = {"m": "min", "h": "hour", "d": "day"}[unit]
    return f"{n} {word}{'s' if n != 1 else ''} before"


def human_from_trigger(trig):
    """'TRIGGER:-PT15M' → '15m before'; 'TRIGGER:PT0S' → 'At time'. For display."""
    if not trig:
        return ""
    t = str(trig).replace("TRIGGER:", "").strip()
    neg = t.startswith("-")
    m = re.match(r'^-?P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$', t)
    if not m:
        return str(trig)
    days, hrs, mins, _secs = (int(x) if x else 0 for x in m.groups())
    if days == hrs == mins == 0:
        return "At time"
    parts = []
    if days:
        parts.append(f"{days}d")
    if hrs:
        parts.append(f"{hrs}h")
    if mins:
        parts.append(f"{mins}m")
    label = " ".join(parts)
    return f"{label} before" if neg else f"{label} after"
