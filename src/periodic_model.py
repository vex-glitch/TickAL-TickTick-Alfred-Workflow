"""periodic_model.py - pure model for periodic notes.

Everything deterministic lives here: period math, the frozen title/tag lookup
contracts, section-header constants (the SINGLE source - templates render from
them and every writer looks anchors up here, never hand-typed twice), line
grammars, money parsing/roll-ups, journal prompt selection + Q/A merge,
sparklines, harvest, summary composition.

Locale rule: English day/month names come from the explicit tables below -
NEVER strftime %a/%B (locale-dependent).

Pure module: no I/O, no workflow imports except focus_blocks' regex constants
(CHECKBOX_RE / LINK_TAIL_RE / make_line - shared line grammar, not the block
model).
"""
import re
import random
from datetime import date, timedelta

import focus_blocks as fb

# ── English name tables (weekday() / month index) ────────────────────────────
DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_NAME = [None, "January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]
MONTH_ABBR = [None, "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ── Tags (lookup contract) ───────────────────────────────────────────────────
TAG_PARENT = "💫Periodic"
TIER_TAGS = {"daily": "💫Daily", "weekly": "💫Weekly", "monthly": "💫Monthly",
             "quarterly": "💫Quarterly", "yearly": "💫Yearly"}
KINDS = ("daily", "weekly", "monthly", "quarterly", "yearly")

# ── Section header constants (one source of truth) ──────────────────────────
# The shipped default layout: nav/quote/weather/mood live in the LEAD
# (engine-composed), `#` group headers + `---` dividers are decor
# (periodic_sections pre), and the weekly 📌 This Week block is data-in-HEADER
# subsections (PREFIX anchors, found via ps.find_prefix, headers rewritten on
# refresh).
SEC_COUNTDOWNS = "⏳ Countdowns"
SEC_HABITS     = "🔄 Habits"
SEC_WEEK_GOALS = "🗓️ Weekly"              # daily mirror of the weekly Goals
SEC_DAY_GOAL   = "☀️ Daily"               # the One Thing
SEC_YESTERDAY  = "⏪ Yesterday"
SEC_YBRIDGE    = "🌉 Yesterday's bridge"   # fed by the bridge write, day-1
SEC_TODAY      = "✅ Tasks"               # under the # ☀️ Today group
SEC_TOMORROW   = "⏩ Tomorrow"
SEC_MORNING    = "🌅 Morning journal"
SEC_NOTES      = "📓 Notes"
SEC_EVENING    = "🌙 Evening journal"
SEC_DAY_SUM    = "📊 Today"               # under the # 🔎 Summaries group
SEC_OTD        = "🕰️ On this day"         # past years' same date, last in the note
SEC_MONEY      = "💰 Money"
# weekly
SEC_GOALS      = "🏆 Goals"
SEC_HIGHLIGHT  = "✨ Highlight"
SEC_TOP_LIST   = "🔥 Top list"            # prefix - header carries the data
SEC_TOP_TASKS  = "🚀 Top tasks"           # prefix
SEC_CREATED    = "➕ Created"             # prefix
SEC_COMPLETED  = "✅ Completed"           # prefix
SEC_WBARS      = "📈 Stats"               # per-day bars
SEC_FOCUS_WEEK = "🎯 Focus"               # prefix
SEC_ENTRIES    = "📨 Entries"
SEC_MOODS      = "😊 Moods"
SEC_LAST_WEEK  = "⏪ Last week"
SEC_HABIT_WEEK = "🔄 Habit consistency"
SEC_WEEKLY_JNL = "📔 Weekly journal"
SEC_REVIEW     = "♻️ Weekly Review"
SEC_INCOME     = "💰 Income"              # prefix
SEC_PEOPLE     = "👽 People"              # birthdays + stale cards
SEC_STATS      = "📈 Stats"               # monthly
# LEGACY names (older notes) - readers fall back to these, writers don't
LEGACY_NAV     = "🧭 Nav"
LEGACY_QUOTE   = "💬 Quote & weather"
LEGACY_TODAY   = "✅ Today"
# monthly
SEC_MONTH_GOAL = "🎯 Month goal"
SEC_SPARKS     = "📊 Sparklines"
SEC_TOP_WINS   = "🏆 Top wins"
# quarterly
SEC_OKR_REVIEW = "🎯 OKR review"
SEC_NEXT_OKRS  = "🚀 Next-Q OKRs"
SEC_DECISION   = "⚖️ Decision log"
SEC_ENERGY     = "🔋 Energy audit"
# yearly
SEC_DASHBOARD  = "📊 Dashboard"
SEC_TOP10      = "🏆 Top 10 wins"
SEC_SCORECARD  = "🎯 Goals scorecard"
SEC_YEAR_PARA  = "📝 Year in one paragraph"
SEC_BEST_OF    = "⭐ Best of"
SEC_THEME      = "🧭 Theme of the year"
SEC_ANTI       = "🚫 Anti-goals"
SEC_DECEMBER   = "🧪 December test"

# Where a goal lands, per tier (Vex 2026-09-12: "There should be goal setting
# for every periodic note"). Only daily and weekly had a setter before; the
# other three sections already ship in their templates and NO filler writes
# them, so appending is safe and nothing can overwrite a goal.
GOAL_SECTION = {
    "daily":     SEC_DAY_GOAL,      # the One Thing - REPLACES the body
    "weekly":    SEC_GOALS,
    "monthly":   SEC_MONTH_GOAL,
    "quarterly": SEC_OKR_REVIEW,
    "yearly":    SEC_SCORECARD,
}


def goal_line(text="", pid=None, tid=None, title=None):
    """The three shapes a goal can take (Vex's own list):
        text only  -> "- [ ] Ship the thing"
        task only  -> "- [ ] [Task](url)"
        both       -> "- [ ] Ship the thing · [Task](url)"
    The link stays LAST so the line still ends in a task URL, which is what
    the checkbox parser reads the tid from - tick the goal in the note and
    the real task completes, in all three shapes that have one.
    """
    import focus_blocks as fb
    text = " ".join((text or "").split())
    if tid:
        linked = fb.make_line(pid, tid, title or "Task").raw.rstrip()
        if not text:
            return linked
        return linked.replace("- [ ] ", f"- [ ] {text} · ", 1)
    if not text:
        return ""
    return f"- [ ] {text}"


# Anchors every writer targets, per tier - each must appear as a
# `### <anchor>…` header line in the shipped template (prefix anchors seed
# bare, the engine appends `: data` on refresh).
WRITER_ANCHORS = {
    # no SEC_MONEY: the day's money is the EVENING JOURNAL's answer, and the
    # summary reflects it (Vex 2026-09-12 - "it is an answer in the evening
    # journal, that is all that should be there"). Older notes that still
    # carry a 💰 section are still read, they just are not seeded any more.
    "daily":     [SEC_COUNTDOWNS, SEC_HABITS, SEC_WEEK_GOALS, SEC_DAY_GOAL,
                  SEC_YESTERDAY, SEC_YBRIDGE, SEC_TODAY, SEC_TOMORROW,
                  SEC_MORNING, SEC_NOTES, SEC_EVENING, SEC_DAY_SUM, SEC_OTD],
    "weekly":    [SEC_GOALS, SEC_HIGHLIGHT, SEC_TOP_LIST, SEC_TOP_TASKS,
                  SEC_CREATED, SEC_COMPLETED, SEC_WBARS, SEC_FOCUS_WEEK,
                  SEC_ENTRIES, SEC_MOODS, SEC_HABIT_WEEK, SEC_WEEKLY_JNL,
                  SEC_REVIEW, SEC_LAST_WEEK, SEC_INCOME, SEC_PEOPLE],
    "monthly":   [SEC_STATS, SEC_SPARKS, SEC_TOP_WINS, SEC_MONEY,
                  SEC_PEOPLE],
    "quarterly": [SEC_MONEY],            # v3.0: template + money only
    "yearly":    [SEC_MONEY],
}

# Tab indents - the default layout nests section bodies. Parsers are
# whitespace-tolerant; WRITERS use these so generated lines match the
# shipped look.
T1, T2, T3 = "\t", "\t\t", "\t\t\t"


def ind(lines, n=2):
    return [("\t" * n) + ln for ln in lines]


# ── Periods ──────────────────────────────────────────────────────────────────
class Period:
    __slots__ = ("kind", "start", "end")

    def __init__(self, kind, start, end):
        self.kind = kind        # one of KINDS
        self.start = start      # date, inclusive
        self.end = end          # date, inclusive

    def __eq__(self, other):
        return (isinstance(other, Period) and self.kind == other.kind
                and self.start == other.start)

    def __hash__(self):
        return hash((self.kind, self.start))

    def __repr__(self):
        return f"Period({self.kind}, {self.start}→{self.end})"


def _last_dom(y, m):
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day


def period_for(kind, d):
    """The period of `kind` containing date d. Weekly = ISO Mon-Sun."""
    if kind == "daily":
        return Period(kind, d, d)
    if kind == "weekly":
        monday = d - timedelta(days=d.weekday())
        return Period(kind, monday, monday + timedelta(days=6))
    if kind == "monthly":
        return Period(kind, date(d.year, d.month, 1),
                      date(d.year, d.month, _last_dom(d.year, d.month)))
    if kind == "quarterly":
        qm = 3 * ((d.month - 1) // 3) + 1
        endm = qm + 2
        return Period(kind, date(d.year, qm, 1),
                      date(d.year, endm, _last_dom(d.year, endm)))
    if kind == "yearly":
        return Period(kind, date(d.year, 1, 1), date(d.year, 12, 31))
    raise ValueError(f"unknown period kind {kind!r}")


def prev_period(p):
    return period_for(p.kind, p.start - timedelta(days=1))


def next_period(p):
    return period_for(p.kind, p.end + timedelta(days=1))


def parents(p):
    """Coarser periods a note breadcrumbs UP to. A week's month/quarter parent
    is its MONDAY's month/quarter (documented convention)."""
    if p.kind == "daily":
        return [period_for("weekly", p.start)]
    if p.kind == "weekly":
        return [period_for("monthly", p.start), period_for("quarterly", p.start)]
    if p.kind == "monthly":
        return [period_for("quarterly", p.start)]
    if p.kind == "quarterly":
        return [period_for("yearly", p.start)]
    return []


def periods_started_by(d):
    """Every period that BEGINS on date d (the mint-ahead rule: minting these
    for tomorrow means weekly mints on Sunday, monthly on month's last day…)."""
    out = [period_for("daily", d)]
    if d.weekday() == 0:
        out.append(period_for("weekly", d))
    if d.day == 1:
        out.append(period_for("monthly", d))
        if d.month in (1, 4, 7, 10):
            out.append(period_for("quarterly", d))
        if d.month == 1:
            out.append(period_for("yearly", d))
    return out


# ── Titles (frozen lookup contract) ──────────────────────────────────────────
def title(p):
    s = p.start
    if p.kind == "daily":
        return f"{s.isoformat()} · {DAY_ABBR[s.weekday()]}"
    if p.kind == "weekly":
        iso = s.isocalendar()            # ISO year - week-53 safe
        return f"{iso[0]}-W{iso[1]:02d}"
    if p.kind == "monthly":
        return f"{s.year}-{s.month:02d} {MONTH_NAME[s.month]}"
    if p.kind == "quarterly":
        return f"{s.year}-Q{(s.month - 1) // 3 + 1}"
    return f"{s.year}"


def _ord(n):
    """1st · 2nd · 3rd · 4th … 11th-13th are th, 21st/22nd/23rd are not."""
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }".replace(" ", "")


def date_range(p):
    """'7th-13th Sep', or '28th Sep-4th Oct' when the span crosses a month."""
    a, b = p.start, p.end
    am, bm = MONTH_ABBR[a.month], MONTH_ABBR[b.month]
    if a.month == b.month:
        return f"{_ord(a.day)}-{_ord(b.day)} {bm}"
    return f"{_ord(a.day)} {am}-{_ord(b.day)} {bm}"


def long_title(p):
    """The note's own NAME. Weekly carries its date range, because "2026-W37"
    alone says nothing about which days it covers (Vex 2026-09-12). The
    STABLE id stays in front and title_key still matches on it, so renaming a
    note can never orphan it from the index."""
    if p.kind == "weekly":
        return f"{title(p)} • {date_range(p)}"
    return title(p)


def tag(p):
    return TIER_TAGS[p.kind]


def title_key(p):
    """Index-lookup key: daily matches by ISO-date title PREFIX (tolerates
    day-abbr drift), other tiers by the STABLE id - the part before " • ", so
    a weekly note keeps its identity whether or not its name carries the date
    range (see long_title)."""
    return p.start.isoformat() if p.kind == "daily" else title(p)


def stable_key(note_title):
    """The index key for a non-daily note TITLE: everything before " • "."""
    return (note_title or "").split(" • ")[0].strip()


def parse_daily_title(s):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ── Breadcrumbs (lead line 1) ────────────────────────────────────────────────
BREADCRUMB_RE = re.compile(r"(◀|▲|▶)")


def render_breadcrumb(segments):
    """segments = [(text, url_or_None)] → '[◀ …](url) · ▲ … · [… ▶](url)'.
    Missing neighbor → plain text (self-heals to a link on a later refresh)."""
    parts = [f"[{t}]({u})" if u else t for t, u in segments]
    return " · ".join(parts)


def breadcrumb_segments(p, url_for):
    """Standard crumb for a period. url_for(period) → deep link or None."""
    segs = []
    pv, nx = prev_period(p), next_period(p)
    segs.append((f"◀ {title(pv)}", url_for(pv)))
    for par in parents(p):
        segs.append((f"▲ {title(par)}", url_for(par)))
    segs.append((f"{title(nx)} ▶", url_for(nx)))
    return segs


def set_breadcrumb(doc, line):
    """Replace lead line 1 iff it's a breadcrumb, else insert as line 1.
    Returns True when the lead changed."""
    lead = doc.lead
    if lead and BREADCRUMB_RE.search(lead[0]):
        if lead[0] == line:
            return False
        lead[0] = line
        return True
    doc.lead = [line, ""] + lead if lead != [""] and lead else [line, ""]
    return True


# ── Money ────────────────────────────────────────────────────────────────────
# Whitespace-tolerant + total-as-bullet (the layout indents body lines with
# tabs and bullets the Total - the old anchored regexes silently zeroed
# indented sums).
MONEY_TOTAL_RE = re.compile(r"^\s*(?:[-*]\s+)?\*\*Total = (?P<amt>.+)\*\*\s*$")
WEEK_DAY_RE = re.compile(
    r"^\s*- (?P<dow>Mon|Tue|Wed|Thu|Fri|Sat|Sun) (?P<d>\d{1,2}) "
    r"(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"(?P<y>\d{4}) • (?P<amt>.+)$")


def parse_amount(s):
    """Currency-symbol/letter tolerant number parse. Rightmost [.,] followed
    by 1-2 trailing digits = decimal sep; every other [.,] dropped.
    Unparseable → None (line ignored in sums - never crashes a roll-up)."""
    s = (s or "").strip()
    if not s:
        return None
    neg = s.lstrip().startswith(("-", "−"))
    cleaned = re.sub(r"[^\d.,]", "", s)
    if not any(ch.isdigit() for ch in cleaned):
        return None
    m = re.search(r"[.,](\d{1,2})$", cleaned)
    try:
        if m:
            intpart = re.sub(r"[.,]", "", cleaned[:m.start()]) or "0"
            val = float(f"{intpart}.{m.group(1)}")
        else:
            val = float(re.sub(r"[.,]", "", cleaned))
    except ValueError:
        return None
    return -val if neg else val


def fmt_amount(x):
    return str(int(x)) if float(x) == int(x) else f"{x:.2f}"


# A journal money ANSWER is hand-typed prose, so only the FIRST number counts.
# parse_amount scrapes every digit in the string, which reads "500 for the
# sleeve, 2 sessions" as 5002 - fine for the canonical "- 485 · label" entry
# lines it was built for, wrong for a sentence.
MONEY_ANSWER_RE = re.compile(r"(?<![\w.,])(\d[\d.,]*)")


def parse_money_answer(text):
    """Evening-journal money answer → amount | None (first number wins)."""
    m = MONEY_ANSWER_RE.search(text or "")
    return parse_amount(m.group(1)) if m else None


def money_answer_line(total, labels):
    """The canonical shape the 💰 verb writes back into that answer:
    the running total, then what it was for."""
    tail = ", ".join([l for l in labels if l])
    return fmt_amount(total) + (f" · {tail}" if tail else "")


def split_money_answer(text):
    """An answer written by money_answer_line → (amount|None, [labels])."""
    amt = parse_money_answer(text)
    tail = ""
    for sep in (" · ", " - "):
        if sep in (text or ""):
            tail = (text or "").split(sep, 1)[1]
            break
    labels = [x.strip() for x in tail.split(",") if x.strip()]
    return amt, labels


def parse_money_entry(line):
    """Daily-money entry → (amount, label) | None. Canonical '- 485 · label';
    lenient: '- 485' and '- 485 - label' also parse; any indentation
    tolerated. Checkbox / day-line / total lines fall out via the
    parse_amount guard or explicit checks."""
    s = line.strip()
    if not s.startswith("- ") or MONEY_TOTAL_RE.match(s):
        return None
    if fb.CHECKBOX_RE.match(s) or WEEK_DAY_RE.match(s):
        return None
    body = s[2:]
    if "**" in body:
        return None                      # bolded non-total decor, not money
    for sep in (" · ", " - "):
        if sep in body:
            amt_s, label = body.split(sep, 1)
            amt = parse_amount(amt_s)
            if amt is not None:
                return amt, label.strip()
    amt = parse_amount(body)
    return (amt, "") if amt is not None else None


def money_entry_line(amount, label):
    return f"- {fmt_amount(amount)} · {label}" if label else f"- {fmt_amount(amount)}"


def money_day_line(d, total):
    # EXACT weekly line format: "- Sat 11 Jul 2026 • 485" - no zero-pad day
    return (f"- {DAY_ABBR[d.weekday()]} {d.day} {MONTH_ABBR[d.month]} "
            f"{d.year} • {fmt_amount(total)}")


def section_money_sum(body_lines):
    total = 0.0
    for ln in body_lines:
        hit = parse_money_entry(ln)
        if hit:
            total += hit[0]
    return total


def money_total_line(total, n=2):
    """Canonical total line - indented bullet."""
    return ("\t" * n) + f"- **Total = {fmt_amount(total)}**"


def recompute_money_body(body_lines):
    """MANAGED daily 💰: keep every non-total line verbatim, recompute the
    Total line and keep it LAST."""
    kept = [ln for ln in body_lines if not MONEY_TOTAL_RE.match(ln)]
    while kept and not kept[-1].strip():
        kept.pop()
    return kept + [money_total_line(section_money_sum(kept))]


def rollup_money_lines(day_lines, total):
    """FILLER money body for monthly/quarterly/yearly."""
    return list(day_lines) + [money_total_line(total)]


def sum_in_period(day_sums, p):
    """Σ over {date → amount} entries whose date falls inside p (inclusive).
    THE straddle-week rule: coarser totals always sum DAILY amounts by date,
    never week lines - a week straddling two months can't double-count."""
    return sum(v for d, v in day_sums.items() if p.start <= d <= p.end)


# ── Capture entries (📓 Notes, APPEND) ───────────────────────────────────────
# Vex 2026-09-12 recoloured the two verdict entries (🏆/👎 -> 🟢/🔴) and added
# ❗️ Reminder. The old glyphs stay READABLE forever - every note already
# written carries them - and canonicalize into the new ones on the way out, so
# a week that straddles the change still groups as one list.
ENTRY_GLYPHS = {"win": "🟢", "nag": "🔴", "thought": "💭",
                "reminder": "❗️", "link": "🔗", "mood": "😊"}
ENTRY_LEGACY = {"🏆": "🟢", "👎": "🔴"}
ENTRY_RE = re.compile(
    r"^\s*- (?P<hm>\d{2}:\d{2}) (?P<glyph>🟢|🔴|❗️|💭|🔗|😊|🏆|👎) (?P<body>.*)$")
MOOD_RE = re.compile(r"^(?P<score>[1-5])(?:\s*·\s*(?P<note>.*))?$")


def make_entry(kind, text, hm):
    return f"- {hm} {ENTRY_GLYPHS[kind]} {text}"


def harvest_entries(body_lines):
    """[(hm, glyph, body)] from a 📓 Notes body, legacy glyphs canonicalized."""
    out = []
    for ln in body_lines:
        m = ENTRY_RE.match(ln)
        if m:
            g = m.group("glyph")
            out.append((m.group("hm"), ENTRY_LEGACY.get(g, g), m.group("body")))
    return out


def day_mood(body_lines):
    """Last 😊 entry of the day → (score:int, note) | None. LEGACY reader -
    mood has since moved to the 💬 Mood: line (quote_mood below); this
    survives for older notes only."""
    best = None
    for _, glyph, body in harvest_entries(body_lines):
        if glyph == "😊":
            m = MOOD_RE.match(body.strip())
            if m:
                best = (int(m.group("score")), m.group("note") or "")
    return best


# ── Mood faces + day rating (💬 section lines) ──────────────────────────────
MOOD_FACES = {1: "😢", 2: "😞", 3: "😐", 4: "🙂", 5: "😁"}
FACE_SCORE = {v: k for k, v in MOOD_FACES.items()}
MOOD_LINE_RE = re.compile(r"^Mood: (?P<face>😢|😞|😐|🙂|😁)(?: · (?P<note>.*))?$")
RATING_LINE_RE = re.compile(r"^Day: (?P<stars>★{1,5})$")


def mood_line(score, note=""):
    return f"Mood: {MOOD_FACES[int(score)]}" + (f" · {note}" if note else "")


def rating_line(score):
    return f"Day: {'★' * max(1, min(5, int(score)))}"


def answer_mood(text):
    """(score, note) from a journal MOOD answer: the bare face the picker
    echoes, with anything written after it on the SAME line as the note -
    "😐", "🙂 slept badly", or the older "🙂 · slept badly". None otherwise."""
    t = (text or "").strip()
    if not t:
        return None
    face = t[:1]
    if face in FACE_SCORE:
        return FACE_SCORE[face], t[1:].lstrip(" ·\t")
    m = MOOD_LINE_RE.match(t)                      # tolerate a full Mood: line
    return (FACE_SCORE[m.group("face")], m.group("note") or "") if m else None


def mood_text(score, note=""):
    """'🙂 slept badly' - a plain space, no separator (Vex 2026-09-12)."""
    return MOOD_FACES[int(score)] + (f" {note}" if note else "")


def answer_stars(text):
    """'★★★' or '3' from a journal RATING answer → the star string, or ''."""
    t = (text or "").strip()
    if t and set(t) == {"★"}:
        return t[:5]
    try:
        n = int(float(t.split()[0]))
    except (ValueError, IndexError):
        return ""
    return "★" * max(1, min(5, n)) if 1 <= n <= 5 else ""


def quote_mood(body_lines):
    """💬 body → (score, note) | None."""
    for ln in body_lines:
        m = MOOD_LINE_RE.match(ln.strip())
        if m:
            return FACE_SCORE[m.group("face")], m.group("note") or ""
    return None


def quote_rating(body_lines):
    """💬 body → stars:int | None."""
    for ln in body_lines:
        m = RATING_LINE_RE.match(ln.strip())
        if m:
            return len(m.group("stars"))
    return None


def merge_quote_body(body_lines, quote, weather):
    """Rebuild the 💬 body: fresh quote/weather (None = keep the old line of
    that shape if any), Mood:/Day: lines preserved verbatim, order fixed
    quote → weather → Mood → Day."""
    old_quote = next((l for l in body_lines if l.strip().startswith(">")), None)
    old_weather = next((l for l in body_lines
                        if l.strip() and not l.strip().startswith(">")
                        and not MOOD_LINE_RE.match(l.strip())
                        and not RATING_LINE_RE.match(l.strip())
                        and not PENDING_RE.match(l.strip())), None)
    mood = next((l for l in body_lines if MOOD_LINE_RE.match(l.strip())), None)
    day = next((l for l in body_lines if RATING_LINE_RE.match(l.strip())), None)
    out = [x for x in (quote or old_quote, weather or old_weather, mood, day) if x]
    return out


def set_line_in_body(body_lines, line_re, new_line):
    """Replace the first line matching line_re, else append. → new body."""
    body = [l for l in body_lines if not PENDING_RE.match(l.strip())]
    for i, ln in enumerate(body):
        if line_re.match(ln.strip()):
            body[i] = new_line
            return body
    while body and not body[-1].strip():
        body.pop()
    return body + [new_line]


PENDING_RE = re.compile(r"^_\(.*\)_$")


# ── 📨 Entries (weekly harvest) ──────────────────────────────────────────────
GROUP_ORDER = ["🟢", "🔴", "❗️", "💭", "🔗"]   # 😊 gets its own weekly section
GROUP_LABELS = {"🟢": "Wins", "🔴": "Nags", "❗️": "Reminders",
                "💭": "Thoughts", "🔗": "Links", "😊": "Moods"}


def entries_grouped(items, glyphs=None, gi=T2, ei=T3):
    """items = [(date, hm, glyph, body)] → 📨 Entries body: grouped by type,
    newest first inside each group, timestamp AFTER the text
    ('- body · Thu 14:32'), tab-nested (gi = group indent, ei = entry
    indent)."""
    lines = []
    for glyph in (glyphs or GROUP_ORDER):
        grp = sorted([it for it in items if it[2] == glyph],
                     key=lambda it: (it[0], it[1]), reverse=True)
        if not grp:
            continue
        lines.append(f"{gi}**{glyph} {GROUP_LABELS[glyph]}**")
        for d, hm, _g, body in grp:
            lines.append(f"{ei}- {body} · {DAY_ABBR[d.weekday()]} {hm}")
    return lines


# ── 📌 This Week composite helpers ───────────────────────────────────────────
def indent(lines):
    return ["    " + ln for ln in lines]


def chip(cur, prev, kind="count", unit="tasks"):
    """vs-last-week chip: '🟢 12 ahead of last week (+9%)' / '🔴 7 behind
    last week (−4%)' / '⚪ level with last week'. None prev → None."""
    if prev is None or cur is None:
        return None
    diff = cur - prev
    if kind == "duration":
        mag = fmt_hm(abs(diff))
    elif kind == "money":
        mag = fmt_amount(abs(diff))
    else:
        mag = f"{int(abs(diff))} {unit}".strip()
    pct = f" ({'+' if diff > 0 else '−'}{abs(diff) / abs(prev) * 100:.0f}%)" if prev else ""
    if diff > 0:
        return f"🟢 {mag} ahead of last week{pct}"
    if diff < 0:
        return f"🔴 {mag} behind last week{pct}"
    return "⚪ level with last week"


def same_day_back(day, years):
    """`day` moved back `years` years, or None when that date does not exist
    that year (29 Feb in a common year has no "on this day")."""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return None


def otd_lines(memories):
    """🕰️ On this day body. memories = [(date, url|None, stars, mood, wins,
    highlight)], newest year first.

    Each year's line LINKS to that day's note, so the section is a door into
    the whole day rather than a copy of it. A past note with none of the four
    readers filled still gets its line - opening it is the point. With no
    past-year note at all the section holds one quiet line instead of an
    empty header: a header that appeared and vanished could not honour the
    delete-it-to-kill-it rule every other section follows.
    """
    if not memories:
        return ["- _(nothing from past years yet)_"]
    out = []
    for d, url, stars, mood, wins, hl in memories:
        # the label IS that day's daily note title ("2025-09-13 · Sat"), the
        # same name the breadcrumb links by - so the line reads as the note
        # it opens (Vex 2026-09-13: "make sure to include a link to that
        # days daily note")
        label = title(period_for("daily", d))
        out.append(f"- [{label}]({url})" if url else f"- {label}")
        if stars:
            out.append(f"\t- Day: {stars}")
        if mood:
            out.append(f"\t- Mood: {mood}")
        out += [f"\t- 🟢 {w}" for w in (wins or [])[:3]]
        if hl:
            out.append(f"\t- ⭐️ {hl}")
    return out


def delta_chip(cur, prev, kind="count"):
    """Compact day-over-day indicator for the daily summaries: '▲ 2' / '▼ 1'
    / '▬'. None when there is nothing to compare against.

    Arrows rather than the weekly chip's 🟢/🔴: those two are the Win and Nag
    entry glyphs now (Vex 2026-09-12), and one note must not spend the same
    colour on two meanings.
    """
    if cur is None or prev is None:
        return None
    diff = cur - prev
    if not diff:
        return "▬"
    if kind == "duration":
        mag = fmt_hm(int(abs(diff)))
    elif kind == "money":
        mag = fmt_amount(abs(diff))
    else:
        mag = f"{abs(diff):g}"
    return f"{'▲' if diff > 0 else '▼'} {mag}"


# ── Checkbox merge (✅ Today, MANAGED) ───────────────────────────────────────
def checkbox_tids(body_lines):
    """tid → checked for every LINKED checkbox line (checked or not)."""
    out = {}
    for ln in body_lines:
        cb = fb.CHECKBOX_RE.match(ln)
        if not cb:
            continue
        tail = fb.LINK_TAIL_RE.search(ln)
        if tail:
            out[tail.group("tid")] = cb.group("mark") in "xX"
    return out


def checked_linked(body_lines):
    """[(pid, tid)] for checked+linked lines - the sweep targets."""
    out = []
    for ln in body_lines:
        cb = fb.CHECKBOX_RE.match(ln)
        if cb and cb.group("mark") in "xX":
            tail = fb.LINK_TAIL_RE.search(ln)
            if tail:
                out.append((tail.group("pid"), tail.group("tid")))
    return out


def sweep_verdict(live, line_day, to_local_date):
    """Should the sweep complete a ticked line's task? -> "complete" | "done".

    A ticked line in a note points at a task ID, and a REPEATING task keeps
    that id when an occurrence is completed: the series just rolls its date
    forward. So a line ticked for an occurrence that was ALREADY completed
    elsewhere (the routine's end, the focus bar, the app) points at an open
    task that is now TOMORROW's occurrence, and completing it again eats
    tomorrow. On 2026-09-13 the refresh at 09:34 did exactly that to Rise and
    shine, Startup and Self Care, an hour after they were finished for real.

    "done" = leave it alone and record it: the task is no longer open, or it
    repeats and its current occurrence is already past the day the line was
    ticked for. line_day is that day (the note's day for ✅ Tasks, the next
    day for ⏩ Tomorrow). to_local_date maps a TickTick UTC stamp to
    'YYYY-MM-DD' local. A task we could not read never reaches here - the
    caller skips it rather than completing blind.
    """
    if (live or {}).get("status", 0) != 0:
        return "done"
    if live.get("repeatFlag"):
        when = live.get("startDate") or live.get("dueDate") or ""
        occ = to_local_date(when) if when else ""
        if occ and occ > line_day.isoformat():
            return "done"
    return "complete"


def done_tids_for(records, line_day, to_local_date):
    """The task ids a note line should show TICKED for line_day, from the
    completed feed (Vex 2026-09-13: "if I tick off a task in TickTick that
    shows in tasks in daily note, that checkbox is not ticked in daily note.
    Even when I refresh").

    A plain task keeps its id when completed, so its own record counts. A
    REPEATING task's line links the SERIES id, and its completion lives on a
    copy with a new id and repeatTaskId = the series - that copy counts only
    for the occurrence's own day, or finishing today's Startup would tick a
    Startup line meant for tomorrow."""
    d = line_day.isoformat()
    out = set()
    for t in records or []:
        series = t.get("repeatTaskId")
        if series:
            occ = to_local_date(t.get("startDate") or t.get("dueDate") or "")
            if occ == d:
                out.add(series)
        elif t.get("id"):
            out.add(t["id"])
    return out


def tick_lines(body_lines, tids):
    """body with every UNticked linked checkbox whose task id is in tids
    ticked -> (new_body, [ticked tids]). Only [ ] -> [x]: a line never gets
    unticked here, so a tick Vex made in the note is never taken back."""
    out, ticked = [], []
    for ln in body_lines:
        cb = fb.CHECKBOX_RE.match(ln)
        tail = fb.LINK_TAIL_RE.search(ln) if cb else None
        if cb and tail and cb.group("mark") not in "xX" and tail.group("tid") in tids:
            ln = ln.replace("[ ]", "[x]", 1)
            ticked.append(tail.group("tid"))
        out.append(ln)
    return out, ticked


def merge_checkboxes(body_lines, items, indent=""):
    """items = [(pid, tid, title)] → (new_body, added). Dedupe by tid against
    ALL existing linked lines, checked or unchecked (a phone-ticked task must
    NOT re-enter unchecked). User lines + check states are preserved verbatim;
    new links append after the last checkbox (or at top), prefixed with
    `indent` (tab nesting)."""
    known = set(checkbox_tids(body_lines))
    # land BESIDE the checkboxes already there: a list whose first line came
    # in one tab deep (the evening goal pick) got every 04:30 task a tab
    # deeper than it, and the list read ragged (review 2026-09-15)
    depths = [len(ln) - len(ln.lstrip("\t")) for ln in body_lines if fb.CHECKBOX_RE.match(ln)]
    if depths:
        indent = "\t" * min(depths)
    fresh = [indent + fb.make_line(pid, tid, ttl).raw
             for pid, tid, ttl in items if tid not in known]
    if not fresh:
        return list(body_lines), 0
    body = list(body_lines)
    last_cb = -1
    for i, ln in enumerate(body):
        if fb.CHECKBOX_RE.match(ln):
            last_cb = i
    body[last_cb + 1:last_cb + 1] = fresh
    return body, len(fresh)


def mark_swept(body_lines, tids):
    """Strike nothing, remove nothing - swept lines stay as the day's record.
    (Placeholder for symmetry; sweep completes the REAL tasks via API.)"""
    return list(body_lines)


# ── Scheduled-task lines ────────────────────────────────────────────────────
TIME_TAIL_RE = re.compile(r" · (?P<hm>[012]?\d:[0-5]\d)\]\(")


def clock(iso, all_day=False):
    """'09:00' for a timed task, '' for an all-day one. LOCAL, like every
    other time these notes show - the API stores UTC."""
    if all_day or not iso:
        return ""
    try:
        from datetime import datetime, timezone
        c = str(iso)[:19]
        dt = datetime(int(c[0:4]), int(c[5:7]), int(c[8:10]),
                      int(c[11:13]), int(c[14:16]), int(c[17:19]),
                      tzinfo=timezone.utc)
        return dt.astimezone().strftime("%H:%M")
    except Exception:
        return ""


def timed_title(title, hm):
    """'Task · 09:00' - the time goes INSIDE the link label, never after it:
    the checkbox parser reads the task id off the END of the line, so a
    trailing time would cost the line its identity (Vex 2026-09-12)."""
    return f"{title} · {hm}" if hm else title


def sort_checkboxes(body_lines):
    """Checkbox lines ordered by the time in their label, untimed last, every
    other line left exactly where it is. Stable, so same-time tasks keep the
    order they arrived in."""
    idxs = [i for i, ln in enumerate(body_lines) if fb.CHECKBOX_RE.match(ln)]
    if len(idxs) < 2:
        return list(body_lines)

    def key(i):
        m = TIME_TAIL_RE.search(body_lines[i])
        return (m.group("hm") if m else "99:99", idxs.index(i))

    out = list(body_lines)
    for slot, src in zip(idxs, sorted(idxs, key=key)):
        out[slot] = body_lines[src]
    return out


# ── Habits ──────────────────────────────────────────────────────────────────
_HABIT_DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def unpack_stamp(n):
    """20260913 → date, or None."""
    try:
        n = int(n)
        return date(n // 10000, (n // 100) % 100, n % 100)
    except (TypeError, ValueError):
        return None


def habit_due(rule, anchor, day):
    """Is a habit due on `day`? (Vex 2026-09-12: the daily note listed ALL
    habits, including the ones that only come round on a Sunday or every 30
    days.)  `anchor` is targetStartDate, packed YYYYMMDD.

    WEEKLY honours BYDAY. DAILY with an INTERVAL counts whole periods from
    the anchor. Anything else - and anything unparseable - answers True: a
    habit wrongly SHOWN is a smaller sin than one wrongly hidden.
    """
    bits = {}
    for part in (rule or "").replace("RRULE:", "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            bits[k.strip().upper()] = v.strip().upper()
    freq, every = bits.get("FREQ"), int(bits.get("INTERVAL") or 1)
    start = unpack_stamp(anchor)
    if freq == "WEEKLY":
        days = [_HABIT_DAYS[d] for d in (bits.get("BYDAY") or "").split(",")
                if d in _HABIT_DAYS]
        if days:
            return day.weekday() in days
        return True
    if freq == "DAILY":
        if every <= 1:
            return True
        if start is None:
            return True
        return (day - start).days % every == 0
    return True


# ── Journal ──────────────────────────────────────────────────────────────────
# Both shapes parse: the old bold form (**Q1 · …** / A: …) that older notes
# carry, and Vex's 2026-09-12 bullet form (- Q1 · … / - *A: …*). Writers emit
# the new one; merge_journal_answers rebuilds each A-line in the shape it
# found, so a note is never half-converted.
JOURNAL_Q_RE = re.compile(r"^\s*(?:- )?\*{0,2}Q(?P<n>\d+)\s*· (?P<q>.+?)\*{0,2}\s*$")
JOURNAL_A_RE = re.compile(r"^(?P<ws>\s*)(?P<dash>- )?(?P<ital>\*?)A: ?(?P<a>.*?)\*?\s*$")


# Fixed journal prompts - code-owned because they ROUTE: each key
# tells the merge step where the answer lands (mood → 💬 Mood line, money →
# 💰 entry, rating → 💬 Day line, highlight → ✨ section). ctx carries the
# live day-goal / weekly-goals text baked into the prompt.
JOURNAL_RANDOM_K = {"morning": 3, "evening": 5, "weekly": 5}


def _clip(s, n=140):
    s = (s or "").strip()
    return s[:n].rstrip() + "…" if len(s) > n else s


def journal_fixed(slot, ctx=None):
    """[(route_key, question)] - the fixed head of each journal, in order.

    Every key except "free" is RECOGNISED BY ITS WORDING (JOURNAL_KEY_RULES),
    never by its position: a note keeps the question set it was seeded with,
    so the day a question is added, older notes still route their own
    answers right (Vex 2026-09-15 added the goal prompts to both journals)."""
    ctx = ctx or {}
    if slot == "morning":
        out = [
            ("mood", "Mood 1-5 (1 😢 · 3 😐 · 5 😁), optional note after ·"),
        ]
        # 🌉 yesterday's bridge echoes as a reflection prompt
        yb = _clip(ctx.get("ybridge"))
        if yb:
            out.append(("ybridge", f"🌉 Yesterday's bridge: {yb} - "
                                   "what carries into today?"))
        # ☀️ the goal check (Vex 2026-09-15): last night's goal, kept or
        # changed through the goal picker. It replaces "What is the one thing
        # you need to do today?" and the picker that used to follow the dialogs.
        goal = _clip(ctx.get("goal"), 100)
        out.append(("gcheck", f"☀️ Does your goal for today still align with: {goal}?"
                              if goal else "☀️ What is today's goal?"))
        out.append(("free", "What is on your mind?"))
        return out
    if slot == "evening":
        goal = (ctx.get("goal") or "").strip()
        goal_q = (f"Did you achieve your daily goal, {goal}? "
                  "Describe success/failure factors."
                  if goal else
                  "Did you achieve your daily goal? "
                  "Describe success/failure factors.")
        # The bridge asks FIRST (Vex 2026-09-12 moved it there): it is the one
        # answer that leaves the note - it writes tomorrow's head and the
        # Bridges board - so it should not be the question you reach tired.
        # Tomorrow's goal right after it (Vex 2026-09-15): picked through the
        # goal picker, it creates tomorrow's note and fills its ☀️ Daily.
        return [
            ("bridge", "🌉 Daily bridge - what should tomorrow-you know? "
                       "(saves to the Bridges board + tomorrow's note)"),
            ("tgoal", "🎯 What is the goal for tomorrow? The one thing that, "
                      "if done, makes the day a success?"),
            ("free", "What is on your mind?"),
            ("goal", goal_q),
            ("money", "How much money did you earn today?"),
            ("rating", "Rate the day, 1-5 stars"),
        ]
    # weekly - the three-things picker is NOT a seeded question: it runs as
    # the Alfred goal-picker handoff after the dialogs (phones edit next
    # week's 🎯 Goals directly instead)
    goals = (ctx.get("goals") or "").strip()
    goals_q = (f"Did you achieve your weekly goals, {goals}? "
               "Describe success/fail factors on each."
               if goals else
               "Did you achieve your weekly goals? "
               "Describe success/fail factors on each.")
    return [
        ("highlight", "What was the highlight of the week? "
                      "Think of one thing that stands out."),
        ("wgoals", goals_q),
    ]


# Which fixed question a seeded Q line IS, by its wording. Every question
# journal_fixed has ever seeded must match its rule (older wordings too), and
# no rule may match another key's question or a pool prompt.
JOURNAL_KEY_RULES = (
    ("mood", re.compile(r"^Mood 1-5\b")),
    ("ybridge", re.compile(r"^🌉 Yesterday's bridge\b")),
    ("gcheck", re.compile(r"^☀️ (?:Does your goal for today still align|What is today's goal\?)")),
    ("bridge", re.compile(r"^🌉 Daily bridge\b")),
    ("tgoal", re.compile(r"^🎯 What is the goal for tomorrow\?")),
    ("goal", re.compile(r"^Did you achieve your daily goal\b")),
    ("money", re.compile(r"^How much money did you earn today\?")),
    ("rating", re.compile(r"^Rate the day\b")),
    ("highlight", re.compile(r"^What was the highlight of the week\?")),
    ("wgoals", re.compile(r"^Did you achieve your weekly goals\b")),
)


_MD_ESCAPE_RE = re.compile(r"\\([!-/:-@\[-`{-~])")        # \ + any ASCII punctuation


def unescape_md(text):
    """Drop the backslash escapes the TickTick app adds to markdown it saves
    ("Mood 1-5 \\(1 ...\\)", "\\_\\(pending\\)\\_")."""
    text = text or ""
    for _ in range(4):                  # the app can escape an escape again
        out = _MD_ESCAPE_RE.sub(r"\1", text)
        if out == text:
            break
        text = out
    return text


def journal_key(question):
    """The route key of one question's text, "free" when it is not a fixed
    question (a pool prompt, "What is on your mind?", a retired wording)."""
    q = unescape_md((question or "").strip())
    for key, rx in JOURNAL_KEY_RULES:
        if rx.search(q):
            return key
    return "free"


def journal_keys(pairs):
    """{n: route_key} for journal_pairs output."""
    return {n: journal_key(q) for n, q, _a, _i in pairs}


def insert_fixed_questions(body_lines, fixed):
    """Give a journal seeded BEFORE a fixed question existed that question,
    unanswered, right after the fixed question it follows in `fixed` (after
    the last Q/A pair before it, else at the top). Every Q is renumbered in
    order and each answer stays under its own question. Only keys a rule can
    recognise are inserted ("free" never is). Returns (new_body, inserted)."""
    body = list(body_lines)
    have = {journal_key(q) for _n, q, _a, _i in journal_pairs(body)}
    inserted = []
    for pos, (key, text) in enumerate(fixed):
        if key == "free" or key in have or journal_key(text) != key:
            continue
        pairs = journal_pairs(body)
        if not pairs:
            return body_lines, []          # an unseeded journal seeds whole
        # the nearest EARLIER fixed key this journal already has
        after = None
        for prev_key, _t in reversed(fixed[:pos]):
            hit = [p for p in pairs if journal_key(p[1]) == prev_key]
            if hit:
                after = hit[-1]
                break
        at = (after[3] + 1) if after else (pairs[0][3] - 1)
        if after:
            # past the answer's own continuation lines (a phone answer can run
            # onto more bullets under it) - never split an answer
            q_indent = len(body[after[3] - 1]) - len(body[after[3] - 1].lstrip())
            j = at
            while j < len(body) and not JOURNAL_Q_RE.match(body[j]):
                ln = body[j]
                if ln.strip() and len(ln) - len(ln.lstrip()) <= q_indent:
                    break
                j += 1
            while j > at and not body[j - 1].strip():      # trailing blanks stay after
                j -= 1
            at = j
        q_ws = body[pairs[0][3] - 1][:len(body[pairs[0][3] - 1]) - len(body[pairs[0][3] - 1].lstrip())] or T1
        a_ws = body[pairs[0][3]][:len(body[pairs[0][3]]) - len(body[pairs[0][3]].lstrip())] or T2
        body[at:at] = [journal_q_line(0, text, q_ws), f"{a_ws}- A: "]
        have.add(key)
        inserted.append(key)
    if not inserted:
        return body_lines, []
    return renumber_journal(body), inserted


def renumber_journal(body_lines):
    """Q lines numbered 1..n in document order; everything else verbatim."""
    out, n = [], 0
    for ln in body_lines:
        m = JOURNAL_Q_RE.match(ln)
        if m:
            n += 1
            ws = ln[:len(ln) - len(ln.lstrip())]
            out.append(journal_q_line(n, m.group("q"), ws))
        else:
            out.append(ln)
    return out


def select_prompts(pool, d, which, k=None):
    """k seeded-random picks from the pool's random section. Deterministic
    across processes: random.Random(f'{date}:{slot}') - NEVER hash(), which
    is salted per process. Fixed prompts live in journal_fixed, not the
    pool."""
    rnd_pool = list(pool.get("random", []))
    k = JOURNAL_RANDOM_K.get(which, 3) if k is None else k
    k = min(k, len(rnd_pool))
    picks = random.Random(f"{d.isoformat()}:{which}").sample(rnd_pool, k) if k else []
    return picks


def seed_journal_lines(prompts):
    lines = []
    for i, q in enumerate(prompts, 1):
        lines.append(journal_q_line(i, q))
        lines.append(f"{T2}- A: ")
    return lines


def journal_q_line(n, q, ws=T1):
    # the QUESTION is italic, the answer plain (Vex 2026-09-12 - he had them
    # the wrong way round in his mock-up and corrected it)
    return f"{ws}- *Q{n} · {q}*"


def journal_pairs(body_lines):
    """[(n, question, answer, a_line_index)] - answer '' == unanswered."""
    out = []
    i = 0
    while i < len(body_lines):
        q = JOURNAL_Q_RE.match(body_lines[i])
        if q and i + 1 < len(body_lines):
            a = JOURNAL_A_RE.match(body_lines[i + 1])
            if a:
                out.append((int(q.group("n")), q.group("q"),
                            a.group("a").strip(), i + 1))
                i += 2
                continue
        i += 1
    return out


def same_question(a, b):
    """Two question texts are the same question: equal once TickTick's escapes
    are dropped, or the same FIXED key (a dynamic question's text follows the
    goal, so its words can move while it is still the same question)."""
    ua, ub = unescape_md(a or "").strip(), unescape_md(b or "").strip()
    if ua == ub:
        return True
    ka = journal_key(ua)
    return ka != "free" and ka == journal_key(ub)


def merge_journal_answers(body_lines, answers, questions=None):
    """answers = {n: text}. Fill ONLY still-empty A-lines (phone wins). The
    A-line's own indentation survives. Returns (new_body, filled_count).

    questions = {n: the question text answer n was given for}: the answer
    lands under question n only if it still IS that question, else under the
    one question that is (a copy of the note saved mid-run by the app or the
    phone can carry other numbering), else nowhere - a skipped answer beats
    one filed under the wrong question."""
    body = list(body_lines)
    pairs = journal_pairs(body)
    by_n = {n: (q, a, idx) for n, q, a, idx in pairs}
    filled, used = 0, set()
    for n, text in answers.items():
        if not (text or "").strip():
            continue
        target = None
        if questions and n in questions:
            asked = questions[n]
            if n in by_n and same_question(by_n[n][0], asked):
                target = by_n[n]
            else:
                hits = [(q, a, idx) for _n, q, a, idx in pairs if same_question(q, asked)]
                target = hits[0] if len(hits) == 1 else None
        else:
            target = by_n.get(n)
        if target is None or target[1] or target[2] in used:
            continue
        idx = target[2]
        m = JOURNAL_A_RE.match(body[idx])
        ws, dash, ital = m.group("ws"), m.group("dash") or "", m.group("ital")
        body[idx] = f"{ws}{dash}{ital}A: {text.strip()}{ital}"
        used.add(idx)
        filled += 1
    return body, filled


# ── Stats / sparklines / harvest rendering ───────────────────────────────────
STAT_RE = re.compile(r"^- (?P<name>[^:]+): (?P<val>[^(]+?)(?: \(Δ (?P<delta>[+−-][^)]+)\))?$")
_BARS = "▁▂▃▄▅▆▇█"


def stat_line(name, val, delta=None):
    return f"- {name}: {val}" + (f" (Δ {delta})" if delta else "")


def fmt_hm(minutes):
    minutes = int(round(minutes))
    h, m = divmod(abs(minutes), 60)
    body = f"{h}h {m:02d}m" if h else f"{m}m"
    return f"-{body}" if minutes < 0 else body


def fmt_delta(cur, prev, kind="count"):
    """Δ string, or None when prev is unavailable."""
    if prev is None or cur is None:
        return None
    diff = cur - prev
    if kind == "duration":
        return f"+{fmt_hm(diff)}" if diff >= 0 else fmt_hm(diff)
    if kind == "float":
        return f"{diff:+.1f}"
    if kind == "money":
        return f"+{fmt_amount(diff)}" if diff >= 0 else f"-{fmt_amount(abs(diff))}"
    return f"{int(diff):+d}"


def spark(values):
    """min-max normalized ▁…█; None → '·'; all-equal/all-zero → ▁; single → ▄."""
    if not values:
        return ""
    real = [v for v in values if v is not None]
    if not real:
        return "·" * len(values)
    if len(values) == 1:
        return "▄"
    lo, hi = min(real), max(real)
    out = []
    for v in values:
        if v is None:
            out.append("·")
        elif hi == lo:
            out.append("▁")
        else:
            out.append(_BARS[round((v - lo) / (hi - lo) * 7)])
    return "".join(out)


def spark_line(name, values, rng=None):
    return f"- {name} {spark(values)}" + (f" ({rng})" if rng else "")


def harvest_line(glyph, src, text):
    return f"- {glyph} {src} · {text}"


def done_week_lines(per_day):
    """per_day = [(date, count)] Mon..Sun → '- Mon ▇▇▇ 12' rows + week total."""
    mx = max((c for _, c in per_day), default=0)
    lines = []
    for d, c in per_day:
        bar = "▇" * max(1, round(c / mx * 7)) if mx and c else ""
        lines.append(f"- {DAY_ABBR[d.weekday()]} " + (f"{bar} {c}" if bar else f"{c}"))
    lines.append(f"**Week: {sum(c for _, c in per_day)}**")
    return lines


# ── ☀️ Day Goal ──────────────────────────────────────────────────────────────
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def strip_md_links(s):
    """Repeated md-link strip + leftover URL-paren cleanup - titles that
    themselves contain ']' or '](' must not leak raw URLs into prompts."""
    prev = None
    while prev != s:
        prev = s
        s = _MD_LINK_RE.sub(r"\1", s)
    return re.sub(r"\(https?://[^)\s]*\)?", "", s).strip()


def goal_titles(body_lines):
    """Every real line of a goals-ish section → display text (checkbox +
    md-link stripped)."""
    out = []
    for ln in body_lines:
        # the TickTick app backslash-escapes markdown when the note is edited
        # there ("\_\(pick one...\)\_"), and an escaped placeholder was read
        # as the goal: "Did you achieve your daily goal, _(pick one...)?"
        s = unescape_md(ln.strip())
        if not s or PENDING_RE.match(s) or PENDING_RE.match(s[2:] if s.startswith("- ") else s):
            continue
        s = re.sub(r"^- \[[ xX]\] ", "", s)
        s = s[2:] if s.startswith("- ") else s
        s = strip_md_links(s)
        if s:
            out.append(s)
    return out


def day_goal_title(body_lines):
    """First real line of the ☀️ section → display text | ''. Feeds the
    evening 'did you achieve…' prompt."""
    titles = goal_titles(body_lines)
    return titles[0] if titles else ""


# ── Templates ────────────────────────────────────────────────────────────────
PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def render_template(text, mapping):
    """Replace {{key}}; unknown keys render as empty string."""
    return PLACEHOLDER_RE.sub(lambda m: str(mapping.get(m.group(1), "")), text)
