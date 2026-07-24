"""countdowns.py - the ⏳ Countdowns model (pure, unit-tested).

Entity truth from the webapp bundle (module +SYV, extracted 2026-07-24):
kinds are a FIXED enum of four - holiday=1, birthday=2, anniversary=3,
countdown=4 (no custom kinds; the 130-icon catalog + the countup flip
carry any flavor). Calendar / smart-list visibility is the per-entity
`typeOfSmartList`: 0 = on the day, -3 = 3 days before, -7 = 7 days
before, -9999 = always, 9999 = never. `daysOption` is the day-COUNTING
method (0 standard / 1 inclusive), not visibility - easy to confuse.

This module is grammar + math + entity builders only, no I/O. Occurrence
math mirrors periodic_fetch._next_occurrence (kept separate on purpose -
that one feeds notes, this one feeds screens).

Sibling: writes ride api_v2.countdown_batch (add/update take FULL
entities, delete takes bare ids).
"""
import re
from datetime import date, timedelta

KINDS = {1: ("🎉", "Holiday"), 2: ("🎂", "Birthday"),
         3: ("💞", "Anniversary"), 4: ("⏳", "Countdown")}
KIND_ICON = {1: "countdown_new_year_day", 2: "countdown_birthday",
             3: "countdown_wedding_anniversary", 4: "countdown_countdown"}
KIND_COLOR = {1: "#F796A7", 2: "#A0EFED", 3: "#FDB368", 4: "#92D0FF"}

# typeOfSmartList - when the countdown surfaces in calendar/smart lists
APPEAR = [(0, "On the day"), (-3, "3 days before"), (-7, "7 days before"),
          (-9999, "Always"), (9999, "Never")]
APPEAR_LABEL = dict(APPEAR)

_BYDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def cd_date(n):
    """YYYYMMDD int → date, None when malformed."""
    try:
        return date(n // 10000, n // 100 % 100, n % 100)
    except Exception:
        return None


def kind_chip(cd):
    return KINDS.get(cd.get("type") or 4, KINDS[4])[0]


def is_countup(cd):
    return (cd.get("timerMode") or 0) == 1


def days_until(cd, today=None):
    """(days, mode) - mode 'ahead' (n days to the next occurrence),
    'since' (count-up / past one-shot: n days elapsed), or None when the
    entity is unreadable. Repeats resolved for WEEKLY/BYDAY, MONTHLY,
    YEARLY (+ ignoreYear); Feb-29 clamps to the 28th off-leap."""
    today = today or date.today()
    target = cd_date(cd.get("date") or 0)
    if not target:
        return None
    if is_countup(cd):
        return max(0, (today - target).days), "since"
    rule = cd.get("repeatFlag") or ""
    try:
        if "FREQ=WEEKLY" in rule:
            m = re.search(r"BYDAY=([A-Z,]+)", rule)
            days = sorted(_BYDAY[d] for d in
                          (m.group(1).split(",") if m else [])
                          if d in _BYDAY)
            if not days:
                return None
            ahead = min((d - today.weekday()) % 7 for d in days)
            im = re.search(r"INTERVAL=(\d+)", rule)
            k = int(im.group(1)) if im else 1
            if k > 1:
                # biweekly+ parity, anchored at the entity date's week
                cand = today + timedelta(days=ahead)
                a_mon = target - timedelta(days=target.weekday())
                c_mon = cand - timedelta(days=cand.weekday())
                off = ((c_mon - a_mon).days // 7) % k
                if off:
                    cand += timedelta(days=7 * (k - off))
                    ahead = (cand - today).days
            return ahead, "ahead"
        if "FREQ=MONTHLY" in rule:
            for k in range(62):
                if (today + timedelta(days=k)).day == target.day:
                    return k, "ahead"
            return None
        if "FREQ=YEARLY" in rule or cd.get("ignoreYear"):
            def _yr(y):
                try:
                    return target.replace(year=y)
                except ValueError:
                    return date(y, target.month, 28)
            cand = _yr(today.year)
            if cand < today:
                cand = _yr(today.year + 1)
            return (cand - today).days, "ahead"
    except Exception:
        return None
    delta = (target - today).days
    return (delta, "ahead") if delta >= 0 else (-delta, "since")


def age_on_next(cd, today=None):
    """Birthday with a real year → the age they turn at the next
    occurrence; None otherwise."""
    today = today or date.today()
    if cd.get("type") != 2 or cd.get("ignoreYear"):
        return None
    born = cd_date(cd.get("date") or 0)
    if not born or born.year >= today.year:
        return None
    occ = days_until(cd, today)
    if not occ or occ[1] != "ahead":
        return None
    return (today + timedelta(days=occ[0])).year - born.year


def distance_label(cd, today=None):
    """'today' / 'tomorrow' / 'in 12d' / '387d since' - the row chip."""
    occ = days_until(cd, today)
    if not occ:
        return "?"
    n, mode = occ
    if mode == "since":
        return f"{n}d since"
    return "today" if n == 0 else ("tomorrow" if n == 1 else f"in {n}d")


def sort_key(cd, today=None):
    """Soonest-first; count-ups sink below upcoming, longest run first."""
    occ = days_until(cd, today)
    if not occ:
        return (2, 0)
    n, mode = occ
    return (1, -n) if mode == "since" else (0, n)


def milestone(cd, today=None):
    """Count-up round-number chip: '💯 100d' at 100/365/500/1000/… within
    a 3-day window past the mark; None otherwise."""
    occ = days_until(cd, today)
    if not occ or occ[1] != "since":
        return None
    n = occ[0]
    for mark in (100, 365, 500, 730, 1000, 1500, 2000, 3650):
        if mark <= n <= mark + 3:
            return f"💯 {mark}d"
    return None


def parse_cd_date(text, today=None):
    """Vex date grammar → (yyyymmdd_int, had_year). Forms: YYYY/MM/DD ·
    DD.MM.YYYY · DD.MM. / DD.MM (year-less → the NEXT occurrence from
    today). Dots and slashes both tolerated, swap-forgiving on D/M when
    unambiguous. None when unparseable."""
    today = today or date.today()
    t = (text or "").strip().rstrip(".")
    m = re.fullmatch(r"(\d{4})[./](\d{1,2})[./](\d{1,2})", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", t)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})", t)
            if not m:
                return None
            d, mo, y = int(m.group(1)), int(m.group(2)), None
    if mo > 12 and d <= 12:
        d, mo = mo, d
    if y is None:
        try:
            cand = date(today.year, mo, d)
        except ValueError:
            return None
        if cand < today:
            try:
                cand = date(today.year + 1, mo, d)
            except ValueError:
                cand = date(today.year + 1, mo, 28)
        # int built from cand, NOT the raw d - the Feb-29 roll-forward
        # clamps to the 28th and a 0229 int in a non-leap year would be
        # invalid on the live account (review catch 2026-07-24)
        return cand.year * 10000 + cand.month * 100 + cand.day, False
    try:
        date(y, mo, d)
    except ValueError:
        return None
    return y * 10000 + mo * 100 + d, True


def new_entity(cid, name, date_int, kind, appear=0, sort_order=0,
               countup=False, yearless=False):
    """Full countdown entity with the kind's defaults (Vex's birthday
    grammar generalized: 9:00 day-of + 2-days-before reminders, yearly
    RRULE for birthday/anniversary/holiday, style cartoon). `appear` =
    typeOfSmartList. `yearless` marks a D.M-only date (ignoreYear)."""
    mo, d = date_int // 100 % 100, date_int % 100
    yearly = kind in (1, 2, 3) and not countup
    return {
        "id": cid, "type": kind, "iconRes": KIND_ICON[kind],
        "color": KIND_COLOR[kind], "name": name, "date": date_int,
        "ignoreYear": bool(yearless) and kind == 2,
        "showCalendarType": 1, "typeOfSmartList": appear,
        "reminders": ["TRIGGER:P0DT9H0M0S", "TRIGGER:-P2DT15H0M0S"],
        "repeatFlag": (f"RRULE:FREQ=YEARLY;INTERVAL=1;BYMONTH={mo};"
                       f"BYMONTHDAY={d}") if yearly else None,
        "remark": "", "showRemark": True, "status": 0, "deleted": 0,
        "style": "cartoon", "styleColor": ["#2B2B2B", "#E4E4E4"],
        "dateDisplayFormat": "day",
        "timerMode": 1 if countup else 0,
        "showAge": kind == 2 and not yearless, "daysOption": 0,
        "annoyingAlert": None, "sortOrder": sort_order,
    }
