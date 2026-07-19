#!/usr/bin/env python3
"""
Shared date/time parsing and display helpers.
Single source of truth used by add_task.py, reschedule.py, and dispatch.py.
"""
import re
import time as _time
import calendar as _cal
from datetime import datetime, timezone as _tz

# ── Month tables ─────────────────────────────────────────────────────────────
MONTHS = ["january", "february", "march", "april", "may", "june",
          "july", "august", "september", "october", "november", "december"]

_MONTH_MAP = {}
for _i, _mn in enumerate(MONTHS, 1):
    _MONTH_MAP[_mn]      = _i
    _MONTH_MAP[_mn[:3]]  = _i   # jan, feb, mar …


# ── Normaliser ────────────────────────────────────────────────────────────────
def _normalise_date(date_str):
    """Normalise a raw date/time string before handing it to parsedatetime.

    Steps (in order):
      1. Weekend aliases → saturday
      2. "Xth of Month" → "X Month"
      3. Ordinal suffixes stripped: "21st" → "21"
      4. Month-name reordering / abbreviation expansion + 2-digit year
      5. DD/MM[-./][YY|YYYY] → 'D MonthName [YYYY]'
      6. Hour notation: 21h → 21:00
      7. "at N" (bare) → "at Nam" (N<12) or "at N:00" (N≥12)
      8. Bare hour at end of date phrase → am (N<12) or :00 (12-23)
    """
    s = date_str.strip()

    # 1. Weekend aliases. Mid-weekend (Sat/Sun) "this weekend" means NOW -
    # "this saturday" would resolve to the PAST on a Sunday.
    _mid_wknd = datetime.now().weekday() >= 5
    s = re.sub(r'\bnext\s+weekend\b', 'next saturday', s, flags=re.IGNORECASE)
    s = re.sub(r'\bthis\s+weekend\b',
               'today' if _mid_wknd else 'this saturday', s, flags=re.IGNORECASE)
    s = re.sub(r'\bweekend\b',
               'today' if _mid_wknd else 'saturday', s, flags=re.IGNORECASE)

    # 2. "Xth of Month [...]" → "X Month [...]"
    s = re.sub(r'\b(\d{1,2})(?:st|nd|rd|th)\s+of\s+', r'\1 ', s, flags=re.IGNORECASE)

    # 3. Strip ordinal suffixes: 21st → 21, 1st → 1
    s = re.sub(r'\b(\d{1,2})(st|nd|rd|th)\b', r'\1', s, flags=re.IGNORECASE)

    # 4. Normalise "D MonthName [YYYY]" and "MonthName D [YYYY]"
    _month_pat = r'(?:' + '|'.join(
        re.escape(k) for k in sorted(_MONTH_MAP, key=len, reverse=True)
    ) + r')'

    def _expand_year(yr):
        if not yr:
            return ""
        yi = int(yr)
        return f" {yi + 2000 if yi < 100 else yi}"

    s = re.sub(
        rf'\b(\d{{1,2}})\s+({_month_pat})(?:\s+(\d{{2,4}}))?\b',
        lambda m: f"{m.group(1)} {MONTHS[_MONTH_MAP[m.group(2).lower()]-1].capitalize()}"
                  + _expand_year(m.group(3)),
        s, flags=re.IGNORECASE,
    )
    s = re.sub(
        rf'\b({_month_pat})\s+(\d{{1,2}})(?:\s+(\d{{2,4}}))?\b',
        lambda m: f"{m.group(2)} {MONTHS[_MONTH_MAP[m.group(1).lower()]-1].capitalize()}"
                  + _expand_year(m.group(3)),
        s, flags=re.IGNORECASE,
    )

    # 5. DD/MM[-./][YY|YYYY] → 'D MonthName [YYYY]'
    m = re.match(r'^(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?(.*)$', s)
    if m:
        d, mo, yr, rest = m.groups()
        d, mo = int(d), int(mo)
        if 1 <= mo <= 12:
            month_name = MONTHS[mo - 1].capitalize()
            yr_part = _expand_year(yr)
            s = f"{d} {month_name}{yr_part}"
            if rest:
                s += rest

    # 6. Hour notation: 21h → 21:00, 9h → 9:00
    s = re.sub(r'\b(\d{1,2})h\b', lambda x: f"{x.group(1)}:00", s)

    # 7. "at N" with no am/pm/colon: N<12 → am, N≥12 → 24h
    def _at_conv(x):
        h = int(x.group(1))
        return f"at {h}am" if h < 12 else f"at {h}:00"
    s = re.sub(r'\bat\s+(\d{1,2})\b(?!\s*(?:am|pm|:|h\b))', _at_conv, s, flags=re.IGNORECASE)

    # 8. Bare hour at end of date phrase
    _DATE_PHRASE = (
        r'today|tomorrow|yesterday'
        r'|monday|tuesday|wednesday|thursday|friday|saturday|sunday'
        r'|next\s+\w+|this\s+\w+|in\s+\d+\s+\w+'
    )
    def _bare_hour(x):
        h = int(x.group(2))
        if h < 12:    return f"{x.group(1)} {h}am"
        elif h <= 23: return f"{x.group(1)} {h}:00"
        return x.group(0)
    s = re.sub(
        rf'(\b(?:{_DATE_PHRASE})\b)\s+(\d{{1,2}})\s*$',
        _bare_hour, s, flags=re.IGNORECASE,
    )

    return s


# ── Parser ────────────────────────────────────────────────────────────────────
def parse_date(date_str):
    """Convert natural language date string → UTC ISO 8601 string or None.

    All-day dates (parsedatetime status 1) are stored as UTC midnight of the
    LOCAL calendar date - e.g. "today" on 21 May → "2026-05-21T00:00:00+0000"
    regardless of timezone.  TickTick reads the date portion directly.

    Timed dates (status 2/3) use DST-correct local→UTC conversion via
    time.mktime(), which applies the correct seasonal offset for the TARGET
    date (not today's offset).
    """
    if not date_str:
        return None
    try:
        import parsedatetime
        cal   = parsedatetime.Calendar()
        t, status = cal.parse(_normalise_date(date_str))
        if status == 0:
            return None
        dt_local = datetime(*t[:6])
        if status == 1:
            # All-day: encode the LOCAL calendar date as UTC midnight so
            # TickTick shows the correct day regardless of the user's timezone.
            return dt_local.strftime("%Y-%m-%dT00:00:00+0000")
        ts     = _time.mktime(dt_local.timetuple())
        dt_utc = datetime.utcfromtimestamp(ts).replace(tzinfo=_tz.utc)
        return dt_utc.strftime("%Y-%m-%dT%H:%M:%S+0000")
    except Exception:
        return None


# ── Display helpers ───────────────────────────────────────────────────────────
def utc_to_local_display(iso_str):
    """'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' in local time.

    All-day detection: UTC hour/min/sec == 0 (TickTick stores all-day dates as
    UTC midnight of the calendar date, regardless of timezone).
    """
    if not iso_str:
        return ""
    try:
        dt_utc = datetime(
            int(iso_str[0:4]), int(iso_str[5:7]), int(iso_str[8:10]),
            int(iso_str[11:13]), int(iso_str[14:16]), int(iso_str[17:19]),
            tzinfo=_tz.utc,
        )
        if dt_utc.hour == 0 and dt_utc.minute == 0 and dt_utc.second == 0:
            return iso_str[:10]          # "YYYY-MM-DD" - the TickTick calendar date
        local = dt_utc.astimezone()
        return local.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_str[:10]


def utc_to_picker_display(iso_str):
    """'Fri, 22 May' or 'Fri, 22 May  14:30' in local time.

    All-day detection: UTC hour/min/sec == 0 (TickTick stores all-day dates as
    UTC midnight of the calendar date, regardless of timezone).
    """
    if not iso_str:
        return ""
    try:
        dt_utc = datetime(
            int(iso_str[0:4]), int(iso_str[5:7]), int(iso_str[8:10]),
            int(iso_str[11:13]), int(iso_str[14:16]), int(iso_str[17:19]),
            tzinfo=_tz.utc,
        )
        if dt_utc.hour == 0 and dt_utc.minute == 0 and dt_utc.second == 0:
            return dt_utc.strftime("%a, %-d %b")   # UTC date = TickTick calendar date
        local = dt_utc.astimezone()
        return local.strftime("%a, %-d %b  %H:%M")
    except Exception:
        return iso_str[:10]


def utc_to_long_display(iso_str):
    """'Thu, 21 May 2026' or 'Thu, 21 May 2026  14:30' - includes year for notifications."""
    if not iso_str:
        return ""
    try:
        dt_utc = datetime(
            int(iso_str[0:4]), int(iso_str[5:7]), int(iso_str[8:10]),
            int(iso_str[11:13]), int(iso_str[14:16]), int(iso_str[17:19]),
            tzinfo=_tz.utc,
        )
        if dt_utc.hour == 0 and dt_utc.minute == 0 and dt_utc.second == 0:
            return dt_utc.strftime("%a, %-d %b %Y")
        local = dt_utc.astimezone()
        return local.strftime("%a, %-d %b %Y  %H:%M")
    except Exception:
        return iso_str[:10]


# ── Shortcut list ─────────────────────────────────────────────────────────────
def build_date_shortcuts():
    """Build the dynamic date shortcut list.

    Returns a list of tuples: (parse_str, display_label [, extra_search_tags])
    Today's weekday → 'In a Week' instead of 'Next <Weekday>'.
    All remaining months of the current year are included.
    """
    today = datetime.now().strftime("%A").lower()   # e.g. "thursday"

    shortcuts = [
        ("today",             "Today"),
        ("tomorrow",          "Tomorrow"),
        ("in 2 days",         "In 2 Days"),          # discoverability hint for "in..." syntax
        (f"next {today}",     "In a Week"),           # dynamic: same weekday next week
        ("this weekend",      "This Weekend"),
    ]
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        if day == today:
            continue                                  # already covered as "In a Week"
        shortcuts.append((f"next {day}", f"Next {day.capitalize()}"))
    shortcuts += [
        ("next weekend", "Next Weekend"),
        ("in 2 weeks",   "In 2 Weeks"),
    ]

    # Month boundaries: end of current month, then start+end for every remaining month
    now  = datetime.now()
    y, m = now.year, now.month

    last_day = _cal.monthrange(y, m)[1]
    end_date = datetime(y, m, last_day)
    shortcuts.append((end_date.strftime("%-d %B %Y"), f"End of {end_date.strftime('%B')}", "month"))

    for mo in range(m + 1, 13):
        start_date = datetime(y, mo, 1)
        shortcuts.append((start_date.strftime("%-d %B %Y"), f"Start of {start_date.strftime('%B')}", "month"))
        last_day   = _cal.monthrange(y, mo)[1]
        end_date   = datetime(y, mo, last_day)
        shortcuts.append((end_date.strftime("%-d %B %Y"), f"End of {end_date.strftime('%B')}", "month"))

    return shortcuts
