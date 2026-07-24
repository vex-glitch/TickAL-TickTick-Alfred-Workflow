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

# Anchors every writer targets, per tier - each must appear as a
# `### <anchor>…` header line in the shipped template (prefix anchors seed
# bare, the engine appends `: data` on refresh).
WRITER_ANCHORS = {
    "daily":     [SEC_COUNTDOWNS, SEC_HABITS, SEC_WEEK_GOALS, SEC_DAY_GOAL,
                  SEC_YESTERDAY, SEC_YBRIDGE, SEC_TODAY, SEC_TOMORROW,
                  SEC_MORNING, SEC_NOTES, SEC_EVENING, SEC_DAY_SUM,
                  SEC_MONEY],
    "weekly":    [SEC_GOALS, SEC_HIGHLIGHT, SEC_TOP_LIST, SEC_TOP_TASKS,
                  SEC_CREATED, SEC_COMPLETED, SEC_WBARS, SEC_FOCUS_WEEK,
                  SEC_ENTRIES, SEC_MOODS, SEC_HABIT_WEEK, SEC_WEEKLY_JNL,
                  SEC_REVIEW, SEC_LAST_WEEK, SEC_INCOME],
    "monthly":   [SEC_STATS, SEC_SPARKS, SEC_TOP_WINS, SEC_MONEY],
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


def tag(p):
    return TIER_TAGS[p.kind]


def title_key(p):
    """Index-lookup key: daily matches by ISO-date title PREFIX (tolerates
    day-abbr drift), other tiers by exact title."""
    return p.start.isoformat() if p.kind == "daily" else title(p)


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
ENTRY_GLYPHS = {"win": "🏆", "nag": "👎", "thought": "💭",
                "link": "🔗", "mood": "😊"}
ENTRY_RE = re.compile(r"^\s*- (?P<hm>\d{2}:\d{2}) (?P<glyph>🏆|👎|💭|🔗|😊) (?P<body>.*)$")
MOOD_RE = re.compile(r"^(?P<score>[1-5])(?:\s*·\s*(?P<note>.*))?$")


def make_entry(kind, text, hm):
    return f"- {hm} {ENTRY_GLYPHS[kind]} {text}"


def harvest_entries(body_lines):
    """[(hm, glyph, body)] from a 📓 Notes body."""
    out = []
    for ln in body_lines:
        m = ENTRY_RE.match(ln)
        if m:
            out.append((m.group("hm"), m.group("glyph"), m.group("body")))
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
GROUP_ORDER = ["🏆", "👎", "💭", "🔗"]     # 😊 gets its own weekly section
GROUP_LABELS = {"🏆": "Wins", "👎": "Nags", "💭": "Thoughts",
                "🔗": "Links", "😊": "Moods"}


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


def merge_checkboxes(body_lines, items, indent=""):
    """items = [(pid, tid, title)] → (new_body, added). Dedupe by tid against
    ALL existing linked lines, checked or unchecked (a phone-ticked task must
    NOT re-enter unchecked). User lines + check states are preserved verbatim;
    new links append after the last checkbox (or at top), prefixed with
    `indent` (tab nesting)."""
    known = set(checkbox_tids(body_lines))
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


# ── Journal ──────────────────────────────────────────────────────────────────
JOURNAL_Q_RE = re.compile(r"^\s*\*\*Q(?P<n>\d+) · (?P<q>.+)\*\*\s*$")
JOURNAL_A_RE = re.compile(r"^(?P<ws>\s*)A: ?(?P<a>.*)$")


# Fixed journal prompts - code-owned because they ROUTE: each key
# tells the merge step where the answer lands (mood → 💬 Mood line, money →
# 💰 entry, rating → 💬 Day line, highlight → ✨ section). ctx carries the
# live day-goal / weekly-goals text baked into the prompt.
JOURNAL_RANDOM_K = {"morning": 3, "evening": 5, "weekly": 5}


def journal_fixed(slot, ctx=None):
    """[(route_key, question)] - the fixed head of each journal, in order."""
    ctx = ctx or {}
    if slot == "morning":
        out = [
            ("mood", "Mood 1-5 (1 😢 · 3 😐 · 5 😁), optional note after ·"),
        ]
        # 🌉 yesterday's bridge echoes as a reflection prompt. Key MUST stay
        # "free": inserted prompts shift later indexes, and index-keyed
        # routing tolerates that only while every shifting slot is "free".
        yb = (ctx.get("ybridge") or "").strip()
        if yb:
            if len(yb) > 140:
                yb = yb[:140].rstrip() + "…"
            out.append(("free", f"🌉 Yesterday's bridge: {yb} - "
                                "what carries into today?"))
        out += [
            ("free", "What is on your mind?"),
            ("free", "What is the one thing you need to do today? What would, "
                     "if achieved, make this day count?"),
        ]
        return out
    if slot == "evening":
        goal = (ctx.get("goal") or "").strip()
        goal_q = (f"Did you achieve your daily goal, {goal}? "
                  "Describe success/failure factors."
                  if goal else
                  "Did you achieve your daily goal? "
                  "Describe success/failure factors.")
        return [
            ("free", "What is on your mind?"),
            ("goal", goal_q),
            ("money", "How much money did you earn today? (logs to 💰 Money)"),
            ("rating", "Rate the day, 1-5 stars"),
            ("bridge", "🌉 Daily bridge - what should tomorrow-you know? "
                       "(saves to the Bridges board + tomorrow's note)"),
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
        lines.append(f"{T1}**Q{i} · {q}**")     # nested journal layout
        lines.append(f"{T2}A: ")
    return lines


def journal_q_line(n, q, ws=T1):
    return f"{ws}**Q{n} · {q}**"


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


def merge_journal_answers(body_lines, answers):
    """answers = {n: text}. Fill ONLY still-empty A-lines (phone wins). The
    A-line's own indentation survives. Returns (new_body, filled_count)."""
    body = list(body_lines)
    filled = 0
    for n, _q, a, idx in journal_pairs(body):
        if n in answers and not a and answers[n].strip():
            ws = JOURNAL_A_RE.match(body[idx]).group("ws")
            body[idx] = f"{ws}A: {answers[n].strip()}"
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
        s = ln.strip()
        if not s or PENDING_RE.match(s):
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
