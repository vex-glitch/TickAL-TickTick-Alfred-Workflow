"""🕰 Backfill a month of money the CRM never saw (pure: no network, no
dialogs). Vex 2026-10-02: a guest-spot month without the Mac left August
at one session; the fix by hand was a logbook with one entry per day from
the 💰 money-tracking note ("2026 August • MT - 3490"), hours set so the
month reads the hourly rate he knows he made. This module is that write
as a plan; Scripts/xact.py moneybackfill asks the two questions (total,
rate) and performs it through crm_records.

The plan (plan_entries):
  * the month's money note found and its days add up to the total typed →
    ONE ENTRY PER DAY with money, S1..Sn by date, hours = amount / rate
    rounded to the quarter hour (never under a quarter)
  * no note, or the note disagrees with the typed total → ONE entry on
    the month's last day (today for the current month) carrying the whole
    total, hours = total / rate to the quarter hour
Every entry is "### <day> · S<n> · <h>h<mm> · <amount>", the shape
crm_records.ENTRY_RE already reads; the logbook is born under the
"Guest spot" customer, titled "Guest spot • <Month YYYY>", archived on its
last day. One logbook per month: a second backfill of the same month is
refused by the verb (money would double).
"""
import calendar
import re
from datetime import date

CUSTOMER_NAME = "Guest spot"
DEFAULT_RATE = 75
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

# "\t* 3rd Mon - 275", "- 22nd Sat - 490", "* 1st - 20": a day ordinal,
# an optional weekday, a dash, the amount. Week sums ("::145::") and the
# title total never match (no ordinal).
_DAY_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(\d{1,2})\s*(?:st|nd|rd|th)\b[^-\d\n]*-\s*(-?\d[\d.,]*)\s*$",
    re.M)
_TOTAL_RE = re.compile(r"MT\s*-\s*(\d[\d.,]*)", re.I)


def _num(s):
    s = (s or "").strip().replace(" ", "")
    if not s:
        return None
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_amount(text):
    """The number in a typed answer: '3490', '3 490', '3490€', '3.490,00'
    (one separator = decimal, both = thousands + decimal) → float, None
    when there is none."""
    m = re.search(r"-?\d[\d.,\s]*", text or "")
    if not m:
        return None
    raw = m.group(0).strip()
    if "." in raw and "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    return _num(raw)


def parse_day_amounts(content, year, month):
    """{day: amount} for every day line of a money-tracking note with money
    on it (zero days skipped, days the month does not have ignored)."""
    out = {}
    last = calendar.monthrange(year, month)[1]
    for m in _DAY_RE.finditer(content or ""):
        d, amt = int(m.group(1)), _num(m.group(2))
        if 1 <= d <= last and amt:
            out[d] = out.get(d, 0.0) + amt
    return out


def note_total(title, content=""):
    """The note's own total: the ' MT - 3490' title tail, else the first
    '# ::3490::' line, else None."""
    m = _TOTAL_RE.search(title or "")
    if m:
        return _num(m.group(1))
    m = re.search(r"^#\s*::\s*(\d[\d.,]*)\s*::", content or "", re.M)
    return _num(m.group(1)) if m else None


def quarter_hours(amount, rate):
    """amount / rate rounded to the quarter hour, at least one quarter."""
    if not rate or rate <= 0:
        return 0.0
    return max(1, round(amount / rate * 4)) / 4.0


def duration_str(hours):
    """2.25 → '2h15' (the entry segment crm_records.dur_minutes reads)."""
    mins = int(round(hours * 60))
    return f"{mins // 60}h{mins % 60:02d}"


def fmt_amount(v):
    return f"{v:g}"


def month_label(year, month):
    return f"{MONTHS[month - 1][:3]} {year}"


def logbook_title(year, month):
    return f"{CUSTOMER_NAME} • {MONTHS[month - 1]} {year}"


def plan_entries(year, month, total, rate, days=None, today=None):
    """[(iso_day, marker, duration, amount)], hours, mode. mode = 'days'
    when the note's days carried the whole total, 'lump' otherwise."""
    today = today or date.today()
    last = calendar.monthrange(year, month)[1]
    end = date(year, month, last)
    if (year, month) == (today.year, today.month):
        end = today
    if days and abs(sum(days.values()) - total) < 0.005:
        entries, hours = [], 0.0
        for n, d in enumerate(sorted(days), 1):
            h = quarter_hours(days[d], rate)
            hours += h
            entries.append((date(year, month, d).isoformat(), f"S{n}",
                            duration_str(h), fmt_amount(days[d])))
        return entries, hours, "days"
    h = quarter_hours(total, rate)
    return [(end.isoformat(), "S1", duration_str(h), fmt_amount(total))], h, "lump"


def month_choices(today=None, back=24):
    """[(year, month)] newest first, this month and `back` before it."""
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(back + 1):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out
