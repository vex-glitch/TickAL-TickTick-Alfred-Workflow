"""focus_backlog.py - the `log` screen's time grammar (pure, unit-tested).

Retro focus records: Vex types WHEN the session ran, the picker shows it,
⏎ mints a real TickTick focus record (xact:focus_backlog → open/v1 POST
/focus, type 1 timing). This module is only the grammar + guards - no I/O.

Query shape (after the committed "log " token):

    [day] range [task fragment...]

    day    y = yesterday · yy = day before · D.M or D.M. = that date
           (this year) - omitted = today
    range  A-B  or  A+MIN   where A/B = H · H:MM · HMM · HHMM
           (9 → 09:00 · 930 → 9:30 · 1430 → 14:30)
           B before or equal to A crosses midnight (+1 day)
    rest   whatever follows = the task-search fragment

Guards (validate): 1 minute floor, 12 h ceiling (TickTick's timing-record
cap), must already be over. All datetimes here are NAIVE LOCAL - the
picker turns them into epochs with .timestamp(), the verb re-guards and
converts to the UTC wire format. Durations (validate + fmt_range) are
measured on that SAME epoch delta, not the naive one - across a DST
transition the naive delta lies about what actually gets logged
(review catch 2026-07-24). A D.M day in the future = last year's date
(validate would reject any future range anyway, so the future reading
is always dead).
"""
import re
from datetime import datetime, time as dtime, timedelta

MAX_HOURS = 12          # TickTick timing-record ceiling (type 1)

_DAY_RE = re.compile(r"^(y{1,2}|(\d{1,2})\.(\d{1,2})\.?)$")
_RANGE_RE = re.compile(
    r"^(\d{1,2}:\d{2}|\d{1,4})(?:-(\d{1,2}:\d{2}|\d{1,4})|\+(\d{1,3}))$")


def _hm(tok):
    """'14:30'/'1430'/'930'/'9' → (h, m); None when not a clock time."""
    try:
        if ":" in tok:
            h, m = (int(p) for p in tok.split(":", 1))
        elif len(tok) >= 3:
            h, m = int(tok[:-2]), int(tok[-2:])
        else:
            h, m = int(tok), 0
    except ValueError:
        return None
    return (h, m) if 0 <= h <= 23 and 0 <= m <= 59 else None


def parse_when(text, now=None):
    """Leading [day] range tokens → (start, end, rest) as naive-local
    datetimes + the leftover task fragment. (None, None, text) when the
    grammar doesn't parse - the screen shows the help row then."""
    now = now or datetime.now()
    toks = (text or "").split()
    day, i = None, 0
    m = _DAY_RE.match(toks[0]) if toks else None
    if m:
        if m.group(1) in ("y", "yy"):
            day = (now - timedelta(days=len(m.group(1)))).date()
        else:
            try:
                day = now.date().replace(month=int(m.group(3)),
                                         day=int(m.group(2)))
                if day > now.date():
                    day = day.replace(year=day.year - 1)
            except ValueError:
                return None, None, text
        i = 1
    if i >= len(toks):
        return None, None, text
    rm = _RANGE_RE.match(toks[i])
    a = _hm(rm.group(1)) if rm else None
    if not a:
        return None, None, text
    start = datetime.combine(day or now.date(), dtime(a[0], a[1]))
    if rm.group(3) is not None:
        end = start + timedelta(minutes=int(rm.group(3)))
    else:
        b = _hm(rm.group(2))
        if not b:
            return None, None, text
        end = datetime.combine(start.date(), dtime(b[0], b[1]))
        if end <= start:
            end += timedelta(days=1)
    return start, end, " ".join(toks[i + 1:])


def validate(start, end, now=None):
    """Caveman error string, or None when the range is loggable. All
    bounds run on the epoch delta - exactly what the verb re-guards and
    the record stores."""
    now = now or datetime.now()
    secs = end.timestamp() - start.timestamp()
    if secs <= 0:
        return "0 minutes"
    if secs < 60:
        return "under 1 minute"
    if secs > MAX_HOURS * 3600:
        return f"over {MAX_HOURS}h - TickTick cap"
    if end.timestamp() > now.timestamp() + 60:
        return "ends in the future"
    return None


def fmt_dur(secs):
    h, m = int(secs // 3600), int(secs % 3600 // 60)
    return f"{h}h {m}m" if h else f"{m}m"


def fmt_range(start, end, now=None):
    """'14:30 → 15:45 · 1h 15m', day-chipped when not today
    ('y · …' / '22.7 · …'), '+1' on the end time when it crossed
    midnight."""
    now = now or datetime.now()
    if start.date() == now.date():
        day = ""
    elif start.date() == (now - timedelta(days=1)).date():
        day = "y · "
    else:
        day = f"{start.day}.{start.month} · "
    cross = "+1" if end.date() != start.date() else ""
    dur = fmt_dur(end.timestamp() - start.timestamp())
    return (f"{day}{start:%H:%M} → {end:%H:%M}{cross} · {dur}")
