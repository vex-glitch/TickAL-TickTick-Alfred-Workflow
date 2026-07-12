"""Reminder token ↔ RFC5545 TRIGGER helpers, shared across add / edit / dispatch.

A "token" is the short form the user types or picks (at, 0, 15, 15m, 1h, 2d…).
A "trigger" is what TickTick stores: an RFC5545 string like 'TRIGGER:-PT15M'
(negative = before the due/start time; 'TRIGGER:PT0S' = at the due time).
"""
import re

# token, label, hint — the preset rows shown in the pickers. Custom offsets
# (15m, 1h, 2d…) and "at" still work when typed; "7am" = on-the-day at 07:00,
# which TickTick stores as a positive trigger and only makes sense on all-day
# tasks (e.g. the 🔥prepare follow-ups).
PRESETS = [
    ("at",  "At time",           "when it's due"),
    ("5",   "5 min before",      "5 minutes ahead"),
    ("15",  "15 min before",     "15 minutes ahead"),
    ("30",  "30 min before",     "30 minutes ahead"),
    ("1h",  "1 hour before",     "1 hour ahead"),
    ("1d",  "1 day before",      "1 day ahead"),
    ("2d",  "Two days before",   "2 days ahead"),
    ("3d",  "Three days before", "3 days ahead"),
    ("7d",  "Week before",       "7 days ahead"),
    ("7am", "Day of · 7am",      "07:00 on the day (all-day tasks)"),
]
PRESET_TOKENS = {tok for tok, _, _ in PRESETS}

_TOKEN_RE = re.compile(r'^(\d+)(m|min|mins|h|hr|hrs|hour|hours|d|day|days)?$')


def trigger(token):
    """token (at/0, 15, 15m, 1h, 2d…, 7am) → 'TRIGGER:…' string, or None.
    Before-offsets use the minute form TickTick itself stores (e.g. -PT4320M for
    3 days); '7am' is the on-the-day 07:00 trigger TickTick uses for all-day tasks."""
    t = (token or "").strip().lower()
    if t in ("at", "0", "ontime", "now"):
        return "TRIGGER:PT0S"
    if t == "7am":
        return "TRIGGER:P0DT7H0M0S"
    m = _TOKEN_RE.match(t)
    if not m:
        return None
    n = int(m.group(1))
    if n == 0:
        return "TRIGGER:PT0S"
    unit = (m.group(2) or "m")[0]
    mins = n if unit == 'm' else (n * 60 if unit == 'h' else n * 1440)
    return f"TRIGGER:-PT{mins}M"


def human(token):
    """token → friendly label, e.g. '45 mins before', 'At time', 'Day of · 7am'."""
    t = (token or "").strip().lower()
    if t in ("at", "0", "ontime", "now"):
        return "At time"
    if t == "7am":
        return "Day of · 7am"
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
    total = days * 1440 + hrs * 60 + mins
    if total == 0:
        return "At time"
    if not neg:
        # Positive offset from an all-day midnight start → "on the day at HH:MM".
        h, mn = divmod(total, 60)
        ampm = "am" if h < 12 else "pm"
        h12 = h % 12 or 12
        return f"Day of · {h12}{':%02d' % mn if mn else ''}{ampm}"
    # Negative = before due. Normalise minutes (TickTick's form) back to d/h/m.
    d, rem = divmod(total, 1440)
    h, mn = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if mn:
        parts.append(f"{mn}m")
    return f"{' '.join(parts)} before"
