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

PERSON_PREFIX = "👽 "            # the card marker (Vex re-rule 2026-07-24:
LEGACY_PREFIX = "👽H • "         # no 'H •' - search scopes do the narrowing;
                                 # legacy accepted on read, never minted)
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
SEC_FACTS = "## 💬 Facts"        # conversation starters ("cat named Garfield")
SEC_IDEAS = "## 🎁 Ideas"
SEC_LOG = "## 🧾 Log"

CARD_FIELDS = ("Birthday", "Phone", "Mail", "Instagram")

CARD_SKEL = (
    "## 📇 Card\n"
    "Birthday: \n"
    "Phone: \n"
    "Mail: \n"
    "Instagram: \n"
    "\n"
    "## 💬 Facts\n"
    "\n"
    "\n"
    "## 🎁 Ideas\n"
    "\n"
    "\n"
    "## 🧾 Log\n"
)

STALE_DAYS = 30
NUDGE_DAYS = 14                  # silence before the hourly sync mints a CTA
NUDGE_TITLE = "🫂 Reach out"


def person_title(name):
    return f"{PERSON_PREFIX}{name.strip()}"


def person_name(title):
    """'👽 Goga' → 'Goga' (legacy '👽H • ' and archive 🗄️ tails too)."""
    t = (title or "").strip()
    for pre in (LEGACY_PREFIX, PERSON_PREFIX):
        if t.startswith(pre):
            t = t[len(pre):]
            break
    t = re.sub(r"\s*·\s*🗄️?\s*[\d./-]+\s*$", "", t)
    return t.strip()


def _prefixed(t):
    return t.startswith(PERSON_PREFIX) or t.startswith(LEGACY_PREFIX)


def is_person(title):
    """Live card - marked, NOT an archive copy."""
    t = (title or "").strip()
    return _prefixed(t) and ARCHIVE_MARK not in t


def is_archive(title):
    t = (title or "").strip()
    return _prefixed(t) and ARCHIVE_MARK in t


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
    """'Birthday:' / 'Phone:' / … value from the 📇 Card section.
    [ \\t]* only - a \\s* after the colon crosses the newline on an EMPTY
    field and steals the next line as the value (review-era bug class)."""
    m = re.search(rf"^{re.escape(field)}:[ \t]*(.*?)[ \t]*$",
                  content or "", re.M | re.I)
    return m.group(1).strip() if m else ""


def card_field_set(content, field, value):
    """Set 'Field: value' in the 📇 Card section - replaces the existing
    line, inserts one when missing, mints the section when absent."""
    c = content or ""
    line = f"{field}: {value.strip()}"
    m = re.search(rf"^{re.escape(field)}:.*$", c, re.M | re.I)
    if m:
        return c[:m.start()] + line + c[m.end():]
    span = _sec_span(c, SEC_CARD)
    if span is None:
        sep = "" if not c else ("\n" if c.endswith("\n") else "\n\n")
        return f"{SEC_CARD}\n{line}\n\n{c}" if not c else \
            f"{SEC_CARD}\n{line}\n\n" + c
    start, end = span
    body = c[start:end]
    last = None
    for fm in re.finditer(r"^[A-Za-z]+:.*$", body, re.M):
        last = fm
    at = start + (last.end() if last else 0)
    return c[:at] + ("\n" if last else "\n") + line + c[at:] if last else \
        c[:start] + "\n" + line + c[start:]


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

# dates live on the indented *stamp* line now; legacy top-level
# '- YYYY-MM-DD…' entries (CRM style) still parse
_LOG_DATE_RE = re.compile(r"^[ \t]*-\s+\*?(\d{4}-\d{2}-\d{2})", re.M)


def log_line(text, now=None):
    """Two lines: the entry, then the tab-indented italic datestamp
    (Vex re-rule 2026-07-24 - the text leads, the clock whispers)."""
    ts = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    return f"- {text.strip()}\n\t- *{ts}*"


def log_entries(content):
    """[(text, stamp)] pairs from the Log, newest-first as stored. Both
    grammars parse: entry + indented *stamp*, and legacy '- ts - text'."""
    out = []
    lines = log_body(content).splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^-\s+(.*)$", lines[i])
        if not m:
            i += 1
            continue
        txt = m.group(1).strip()
        lm = re.match(
            r"^(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?)\s*-\s*(.*)$", txt)
        if lm:
            out.append((lm.group(2).strip(), lm.group(1)))
            i += 1
            continue
        stamp = ""
        if i + 1 < len(lines):
            sm = re.match(r"^[ \t]+-\s+\*(.+?)\*\s*$", lines[i + 1])
            if sm:
                stamp = sm.group(1)
                i += 1
        out.append((txt, stamp))
        i += 1
    return out


def _sec_span(content, heading):
    """(start, end) char span of a ## section's body (starts at the
    heading line's own newline - [ \\t]* keeps \\s* from eating blank
    lines), or None."""
    c = content or ""
    m = re.search(rf"^{re.escape(heading)}[ \t]*$", c, re.M)
    if not m:
        return None
    start = m.end()
    nxt = re.search(r"^## ", c[start:], re.M)
    return (start, start + nxt.start() if nxt else len(c))


def _log_span(content):
    return _sec_span(content, SEC_LOG)


def ideas_insert(content, line):
    """Append a bullet at the END of 🎁 Ideas (chronological stash).
    Missing heading → minted right before the Log (or at the end)."""
    c = content or ""
    span = _sec_span(c, SEC_IDEAS)
    if span is None:
        log = _sec_span(c, SEC_LOG)
        if log is None:
            sep = "" if (not c or c.endswith("\n\n")) else \
                ("\n" if c.endswith("\n") else "\n\n")
            return f"{c}{sep}{SEC_IDEAS}\n{line}\n"
        at = c.rfind(SEC_LOG)
        return c[:at] + f"{SEC_IDEAS}\n{line}\n\n" + c[at:]
    start, end = span
    body = (c[start:end]).strip("\n")
    newbody = "\n" + (body + "\n" if body else "") + line + "\n"
    if end < len(c):
        newbody += "\n"          # keep one blank before the next section
    return c[:start] + newbody + c[end:]


def facts_insert(content, line):
    """Append a bare bullet to 💬 Facts. Missing heading → minted before
    🎁 Ideas (else before the Log, else appended)."""
    c = content or ""
    span = _sec_span(c, SEC_FACTS)
    if span is None:
        for anchor in (SEC_IDEAS, SEC_LOG):
            if _sec_span(c, anchor) is not None:
                at = c.rfind(anchor)
                return c[:at] + f"{SEC_FACTS}\n{line}\n\n" + c[at:]
        sep = "" if (not c or c.endswith("\n\n")) else \
            ("\n" if c.endswith("\n") else "\n\n")
        return f"{c}{sep}{SEC_FACTS}\n{line}\n"
    start, end = span
    body = (c[start:end]).strip("\n")
    newbody = "\n" + (body + "\n" if body else "") + line + "\n"
    if end < len(c):
        newbody += "\n"
    return c[:start] + newbody + c[end:]


def facts_body(content):
    span = _sec_span(content, SEC_FACTS)
    return (content or "")[span[0]:span[1]].strip("\n") if span else ""


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


def ideas_body(content):
    span = _sec_span(content, SEC_IDEAS)
    return (content or "")[span[0]:span[1]].strip("\n") if span else ""


def created_date(task):
    """The card's createdTime → date (None when unparsable)."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", task.get("createdTime") or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def is_stale_task(task, today=None, limit=STALE_DAYS):
    """Staleness with the same basis as the nudge: last log line, else
    card age. A card minted yesterday is NOT stale (its log is just
    young). No basis at all → stale."""
    d = nudge_silent_days(task, today)
    return d is None or d >= limit


def nudge_silent_days(task, today=None):
    """Silence for the reach-out nudge: days since the last log entry,
    falling back to card AGE when never logged (a card minted yesterday
    must not nudge today). None = no usable basis."""
    today = today or date.today()
    last = last_log_date(task.get("content") or "")
    if last is None:
        last = created_date(task)
    if last is None:
        return None
    return (today - last).days
