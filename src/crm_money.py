"""💰 THE money source for the periodic notes: the CRM's dated entries.

Vex 2026-10-02, in the middle of a quarterly review: "we have too many
places in our system that ask the same question about money ... make the
daily intakes of money in daily notes drag from our CRM Session charges
for the given day. That I always enter." So every money figure a note
carries - the daily summary's Money line, the weekly's 💰 Income day
lines, the month's weeks, the quarter's months, the year's quarters - is
read HERE, from the same entries CRM > 💰 Money sums, and nowhere else.
The evening journal no longer asks, and the `$` entry road only points at
the CRM.

What counts: every dated amount in every logbook, open or archived -
session charges, deposits, refunds, payments - exactly what the money
screen's day would show (crm_records.all_entries, the local cache, never
the network: a note refresh runs on every open and at 04:30). A needle
session without a price (gratis, "-") is a 0 day: a session happened and
no money came. A day with no session and no priced line is absent from
the map, which is how the fillers tell "no sessions" from "made 0".

CRM records not set up here, or the cache unreadable: day_sums is None,
not {} - the callers then write NO money figure at all (never a 0 that
lies), and every money section keeps what it holds. Under launchd the
list id comes from config.json (areas._env_or_cfg); review 2026-10-02
found the 04:30 agent would otherwise have sealed every closing week and
month at 0.
"""
import os
import time
from datetime import date

MEMO_TTL = 2.0                  # one refresh parses the notes cache ONCE: six
_MEMO = {"fn": None, "at": 0.0, "rows": None}   # readers, 1.5 MB of JSON each


def available():
    try:
        import areas
        return bool(areas.records_configured())
    except Exception:
        return False


def _cache_present():
    """Is there a notes cache to read at all? None on disk = UNREADABLE, not
    an empty CRM (review 2026-10-02: records_notes reads a missing cache as
    [], which would have written 0 over every money section)."""
    try:
        import cache as cache_store
        return os.path.exists(cache_store._path("all_notes"))
    except Exception:
        return False


def _entries():
    """[(date, is_session, amount|None, sym, pre, minutes)] off the cache;
    None when the CRM is not set up here, the cache is missing, or the read
    fails. Memoised for MEMO_TTL seconds per reader function: a daily
    refresh asks six times in a row."""
    if not available() or not _cache_present():
        return None
    try:
        import crm_records as cr
        fn = cr.all_entries
        now = time.time()
        if _MEMO["fn"] is fn and _MEMO["rows"] is not None and now - _MEMO["at"] < MEMO_TTL:
            return _MEMO["rows"]
        rows = list(fn())
        _MEMO.update(fn=fn, at=now, rows=rows)
        return rows
    except Exception:
        return None


def day_sums(start=None, end=None):
    """{date: amount} for every day with a session or a priced entry, inside
    [start, end] when given (dates, inclusive). None when the CRM cannot be
    read: the caller leaves the note's money alone."""
    rows = _entries()
    if rows is None:
        return None
    out = {}
    for row in rows:
        d_s, is_s, amt = row[0], row[1], row[2]
        if amt is None:
            if not is_s:
                continue            # an unpriced deposit/payment line says nothing
            amt = 0.0               # a session with no price: a day that earned 0
        try:
            d = date.fromisoformat(d_s[:10])
        except ValueError:
            continue
        if (start and d < start) or (end and d > end):
            continue
        out[d] = out.get(d, 0.0) + amt
    return out


def day_sum(day):
    """That day's money, or None: nothing dated that day, or the CRM
    unreadable (available() tells the two apart)."""
    s = day_sums(day, day)
    return s.get(day) if s is not None else None


def period_sum(start, end):
    """Σ over [start, end]; 0.0 when nothing is logged there, None when the
    CRM cannot be read."""
    s = day_sums(start, end)
    return sum(s.values()) if s is not None else None
