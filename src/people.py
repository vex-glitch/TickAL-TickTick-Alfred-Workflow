"""
👽 People - pure model (no I/O, no API): title grammar, circles, card
sections, log lines, birthday parsing.

The card is a TASK (not a note - CTAs nest under it as real, schedulable
subtasks; notes can't have children). One home list (areas.PEOPLE_ID),
kanban board grouped by CIRCLE tag - five fixed circles, ONE per person
(a second tag doubles the card on a tag-grouped board - bridges lesson).

Title grammar mirrors projects' "💼P • {name}":  👽H • {Name}
Archive copies (the old log, split off by person_archive) are NOTEs:
  👽H • {Name} · 🗄️ {YYYY.MM.DD}   - tagged "archive", no circle.

Impure sides (dialogs, API, cache) live in Scripts/xact.py and browse.
"""
import re
from datetime import date, datetime

PERSON_PREFIX = "👽H • "
PARENT_TAG = "👽people"          # existing live parent tag - circles nest under
ARCHIVE_TAG = "archive"
ARCHIVE_MARK = "🗄️"

# (tag, chip, label) - tag is the TickTick-stored form (lowercase family)
CIRCLES = (
    ("👽family",  "👪", "Family"),
    ("👽work",    "💼", "Work"),
    ("👽friends", "🍻", "Friends"),
    ("👽orbit",   "🛰️", "Orbit"),       # acquaintances
    ("👽admin",   "🧾", "Admin"),       # landlord, bank, doctor…
)
CIRCLE_TAGS = tuple(c[0] for c in CIRCLES)

SEC_CARD = "## 📇 Card"
SEC_IDEAS = "## 🎁 Ideas"
SEC_LOG = "## 🧾 Log"

CARD_SKEL = (
    "## 📇 Card\n"
    "Birthday: \n"
    "Phone: \n"
    "Mail: \n"
    "\n"
    "## 🎁 Ideas\n"
    "\n"
    "\n"
    "## 🧾 Log\n"
)

STALE_DAYS = 30


def person_title(name):
    return f"{PERSON_PREFIX}{name.strip()}"


def person_name(title):
    """'👽H • Goga' → 'Goga' (archive titles lose the 🗄️ tail too)."""
    t = (title or "").strip()
    if t.startswith(PERSON_PREFIX):
        t = t[len(PERSON_PREFIX):]
    t = re.sub(r"\s*·\s*🗄️?\s*[\d./-]+\s*$", "", t)
    return t.strip()


def is_person(title):
    """Live card - prefixed, NOT an archive copy."""
    t = (title or "").strip()
    return t.startswith(PERSON_PREFIX) and ARCHIVE_MARK not in t


def is_archive(title):
    t = (title or "").strip()
    return t.startswith(PERSON_PREFIX) and ARCHIVE_MARK in t


def archive_title(name, d):
    return f"{PERSON_PREFIX}{name} · {ARCHIVE_MARK} {d.strftime('%Y.%m.%d')}"


def circle_of(tags):
    """First circle tag on the card ('' when uncircled)."""
    low = {str(t).lower() for t in (tags or [])}
    for tag, _, _ in CIRCLES:
        if tag in low:
            return tag
    return ""


def circle_chip(tags):
    low = {str(t).lower() for t in (tags or [])}
    for tag, chip, _ in CIRCLES:
        if tag in low:
            return chip
    return ""


# ── card fields ──────────────────────────────────────────────────────────────

def card_field(content, field):
    """'Birthday:' / 'Phone:' / 'Mail:' value from the 📇 Card section."""
    m = re.search(rf"^{re.escape(field)}:\s*(.*?)\s*$",
                  content or "", re.M | re.I)
    return m.group(1).strip() if m else ""


def parse_birthday(value):
    """(year|None, month, day) or None. Grammars (seeded by the skeleton
    hint): 1993/06/27 · 1993-06-27 · 1993.06.27 (year first), 27.06.1993 /
    27.06. (European dots = day first), 06/27 (slashes = month first)."""
    v = (value or "").strip()
    if not v:
        return None
    m = re.fullmatch(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", v)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", v)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.?", v)
            if m:
                d, mo, y = int(m.group(1)), int(m.group(2)), None
            else:
                m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", v)
                if not m:
                    return None
                mo, d, y = int(m.group(1)), int(m.group(2)), None
    if mo > 12 and d <= 12:          # forgive a swapped 27/06
        mo, d = d, mo
    try:
        date(y or 2000, mo, d)
    except ValueError:
        return None
    return (y, mo, d)


# ── log ──────────────────────────────────────────────────────────────────────

_LOG_DATE_RE = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2})\b", re.M)


def log_line(text, now=None):
    ts = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    return f"- {ts} - {text.strip()}"


def _log_span(content):
    """(start, end) char span of the 🧾 Log section body, or None."""
    c = content or ""
    m = re.search(rf"^{re.escape(SEC_LOG)}\s*$", c, re.M)
    if not m:
        return None
    start = m.end()
    nxt = re.search(r"^## ", c[start:], re.M)
    return (start, start + nxt.start() if nxt else len(c))


def log_insert(content, line):
    """Prepend a log line under ## 🧾 Log (newest on top). Missing
    heading → appended at the end with a fresh heading."""
    c = content or ""
    span = _log_span(c)
    if span is None:
        sep = "" if (not c or c.endswith("\n\n")) else \
            ("\n" if c.endswith("\n") else "\n\n")
        return f"{c}{sep}{SEC_LOG}\n{line}\n"
    start, _ = span
    return c[:start] + "\n" + line + c[start:]


def log_body(content):
    """The 🧾 Log section body text ('' when absent)."""
    span = _log_span(content)
    if span is None:
        return ""
    return (content or "")[span[0]:span[1]].strip("\n")


def log_reset(content):
    """Empty the 🧾 Log body (heading stays) - the archive split's second
    half. No Log section → content unchanged."""
    span = _log_span(content)
    if span is None:
        return content or ""
    start, end = span
    return (content or "")[:start] + "\n" + (content or "")[end:]


def last_log_date(content):
    """Newest dated log line in the card → date, else None. Max over all
    lines - hand-edited cards may not keep newest-on-top."""
    body = log_body(content)
    days = _LOG_DATE_RE.findall(body)
    if not days:
        return None
    try:
        return max(date.fromisoformat(d) for d in days)
    except ValueError:
        return None


def days_silent(content, today=None):
    """Days since the last log entry, None when the log is empty."""
    last = last_log_date(content)
    if last is None:
        return None
    return ((today or date.today()) - last).days


def is_stale(content, today=None, limit=STALE_DAYS):
    """No log at all, or last entry ≥ limit days old."""
    d = days_silent(content, today)
    return d is None or d >= limit


def age_chip(content, today=None):
    d = days_silent(content, today)
    return "🗨️ never" if d is None else f"🗨️ {d}d"
