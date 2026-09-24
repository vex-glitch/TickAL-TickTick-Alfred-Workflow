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
import mdtext


def _dayroll_today():
    """The workflow's day (src/dayroll.py: rolls at 04:00, not midnight)."""
    import dayroll
    return dayroll.today()

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

# The note NAME carries its tier's emoji since 2026-09-17 (Vex: "Add emoji
# prefixes to periodic notes for even easier visual orientation"). His own
# five, the ones the pn rows already use (periodic_rows._OPEN_ROWS).
TIER_EMOJI = {"daily": "☀️", "weekly": "♻️", "monthly": "🗓️",
              "quarterly": "🌓", "yearly": "🎉"}
# Both spellings of each: three of the five end in VARIATION SELECTOR-16, and
# a title that loses it somewhere between TickTick, a phone and a hand edit
# must still resolve to the same note.
_TIER_PREFIXES = tuple(
    f"{e}{sfx} " for e in TIER_EMOJI.values()
    for sfx in ("", "\ufe0f") if not (sfx and e.endswith("\ufe0f"))
) + tuple(f"{e.replace(chr(0xfe0f), '')} " for e in TIER_EMOJI.values())


def strip_tier_emoji(s):
    """A note title without its tier emoji, if it has one.

    Every title MATCH goes through this, because notes minted before
    2026-09-17 have no prefix and notes minted after do - and both have to
    land on the same index key, or a refresh would mint a second note for a
    period that already has one."""
    t = (s or "").lstrip()
    for pre in _TIER_PREFIXES:
        if t.startswith(pre):
            return t[len(pre):].lstrip()
    return s or ""

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
# weekly - Vex's 2026-09-17 relayout: two GROUP headers (📊 Stats · 💿 Data)
# each holding a run of bullets, the emoji dropped off the numbers he reads
# at a glance and kept on the things he reads one at a time.
SEC_GOALS      = "🏆 Goals"
# …holding one bullet per tier since 2026-09-17 (Vex: "we need under goals to
# have same kind of thing as in daily … quarter goal, month goal and week
# goal"). The two parents are MIRRORS of their own notes, the same way the
# daily mirrors this note's ♻️ Weekly; only the last one is written here.
# Emoji are Vex's own tier set (periodic_rows._OPEN_ROWS), which is why the
# week reads ♻️ here and 🗓️ in the daily note - his older choice, kept.
SEC_WK_QTR     = "🌓 Quarterly"            # mirror of the quarter's goals
SEC_WK_MONTH   = "🗓️ Monthly"             # mirror of the month's goals
SEC_WK_WEEK    = "♻️ Weekly"              # THIS week's own goals
HINT_WK_QTR    = "- _(mirrors this quarter's note - set it there)_"
HINT_WK_MONTH  = "- _(mirrors this month's note - set it there)_"
# ✨ Highlight is in BOTH the weekly (the week's, set by the row or the weekly
# journal) and the daily (the day's, asked at shutdown) - same name, different
# notes. SEC_HL_WEEK is the weekly's by-day roll-up of the daily ones, and its
# name is PLURAL so neither can ever resolve to the other.
SEC_HIGHLIGHT  = "✨ Highlight"
SEC_HL_WEEK    = "✨ Highlights"          # weekly 💿 Data, one line per day
SEC_WK_STATS   = "📊 Stats"               # group: the week's numbers
SEC_WK_DATA    = "💿 Data"                # group: the week's texture
SEC_TOP_LIST   = "Top lists:"             # plain bullet, 3 lines of body
SEC_TOP_TASKS  = "Top tasks:"             # plain bullet, 3 lines of body
SEC_CREATED    = "Created"                # prefix - header carries the data
SEC_COMPLETED  = "Completed"              # prefix
SEC_WBARS      = "Daily Completed"        # per-day bars
SEC_FOCUS_WEEK = "Focus"                  # prefix
SEC_ALIGNED    = "🥅 Aligned"             # prefix - the week's work that served an
                                          # objective (HANDOFF_OKR phase 5)
SEC_ENTRIES    = "📨 Entries"
SEC_MOODS      = "😊 Moods"               # prefix - header carries the average
SEC_LAST_WEEK  = "⏪ Last week"
SEC_HABIT_WEEK = "Habit consistency"
SEC_WEEKLY_JNL = "📔 Weekly journal"
SEC_REVIEW     = "♻️ Weekly Review"
SEC_INCOME     = "💰 Income"              # prefix
SEC_PEOPLE     = "👽 People"              # birthdays + stale cards
SEC_MEALPREP   = "🥘 Meal prep"           # the week's three meals (src/meal_notes.py)
SEC_STATS      = "📈 Stats"               # monthly
# LEGACY names (older notes) - readers fall back to these, writers don't
LEGACY_NAV     = "🧭 Nav"
LEGACY_QUOTE   = "💬 Quote & weather"
LEGACY_TODAY   = "✅ Today"
# monthly
# monthly - Vex's 2026-09-17 layout, the weekly's shape one tier up: the same
# 📊 Stats / 💿 Data groups holding the same bullet names, counted by WEEK
# instead of by day.
SEC_MTH_QTR    = "🌓 Quarterly goal"       # mirror of the quarter's goals
SEC_MTH_MONTH  = "🗓️ Monthly goal"        # THIS month's own
SEC_MBARS      = "Weekly Completed"       # per-week bars (the daily's twin)
SEC_MDATES     = "⏳ Dates"                # birthdays + countdowns this month
SEC_LAST_MONTH = "⏪ Last month"
SEC_MREVIEW    = "♻️ Monthly Review"
SEC_MONTHLY_JNL = "📔 Monthly journal"
# quarterly - the monthly's shape one tier up, counted by MONTH. Vex killed
# the old skeleton wholesale on 2026-09-17 ("kill it all, adhere to our
# existing logic"): 🎯 OKR review, 🚀 Next-Q OKRs, ⚖️ Decision log and
# 🔋 Energy audit never had a filler and he never filled one by hand.
SEC_QTR_YEAR   = "🎉 Yearly goal"          # mirror of the year's goals
SEC_QTR_QTR    = "🌓 Quarterly goal"       # THIS quarter's own
SEC_QBARS      = "Monthly Completed"      # per-month bars
SEC_LAST_QTR   = "⏪ Last quarter"
SEC_QTR_JNL    = "📔 Quarterly journal"
SEC_QREVIEW    = "♻️ Quarterly Review"
SEC_MONTH_GOAL = "🎯 Month goal"          # what monthly notes called it before
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
# every tier, at the top (HANDOFF_OKR phase 4, Vex 2026-09-19: "We should
# also then have the OKRs section in periodic notes. All of them. With all
# levels."). One line per tier, the plan and his picked goal side by side;
# filled by periodic_engine._fill_okr from src/okr_notes.py.
SEC_OKR        = "🥅 OKRs"

# Where a goal lands, per tier (Vex 2026-09-12: "There should be goal setting
# for every periodic note"). Only daily and weekly had a setter before; the
# other three sections already ship in their templates and NO filler writes
# them, so appending is safe and nothing can overwrite a goal.
GOAL_SECTION = {
    "daily":     SEC_DAY_GOAL,      # the One Thing - REPLACES the body
    "weekly":    SEC_WK_WEEK,       # the bullet, not the whole section
    "monthly":   SEC_MTH_MONTH,
    "quarterly": SEC_QTR_QTR,
    "yearly":    SEC_SCORECARD,
}


# Names a tier's goal section used to have. A mirror or a setter tries the
# current name first and these after it, so a note minted under an older
# template still answers (and is never silently written twice).
GOAL_SECTION_ALT = {"monthly": [SEC_MONTH_GOAL],
                    "quarterly": [SEC_OKR_REVIEW]}


# ⏭ in a goal screen's query = that screen aimed at the NEXT period, by hand
# (Vex 2026-09-20: "I must be able to set goal for next week. When doing
# weekly review on Sunday, that is impossible."). A glyph, not a word: a goal
# typed as "next steps" must stay a goal.
GOAL_NEXT_MARK = "⏭"


def goal_section_names(kind):
    return [GOAL_SECTION[kind]] + GOAL_SECTION_ALT.get(kind, [])


# A bullet that is nothing but an unticked box is the TEMPLATE's placeholder,
# not a goal: setting one must consume it rather than land underneath it (Vex
# 2026-09-17: "new row appeared with new checkbox while our existing checkbox
# in a row below monthly goal stayed unused").
EMPTY_BOX_RE = re.compile(r"^[-*]\s*\[[ xX]\]\s*$")


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
                  SEC_YESTERDAY, SEC_YBRIDGE, SEC_HIGHLIGHT, SEC_TODAY,
                  SEC_TOMORROW, SEC_MORNING, SEC_NOTES, SEC_EVENING,
                  SEC_DAY_SUM, SEC_OTD, SEC_OKR],
    "weekly":    [SEC_OKR, SEC_GOALS, SEC_WK_QTR, SEC_WK_MONTH, SEC_WK_WEEK,
                  SEC_HIGHLIGHT, SEC_TOP_LIST, SEC_TOP_TASKS,
                  SEC_CREATED, SEC_COMPLETED, SEC_WBARS, SEC_FOCUS_WEEK,
                  SEC_HL_WEEK, SEC_ENTRIES, SEC_MOODS, SEC_HABIT_WEEK,
                  SEC_WEEKLY_JNL, SEC_REVIEW, SEC_LAST_WEEK, SEC_INCOME,
                  SEC_PEOPLE, SEC_ALIGNED],
    "monthly":   [SEC_OKR, SEC_MTH_QTR, SEC_MTH_MONTH, SEC_HIGHLIGHT,
                  SEC_TOP_LIST, SEC_TOP_TASKS, SEC_CREATED, SEC_COMPLETED,
                  SEC_MBARS, SEC_FOCUS_WEEK, SEC_HABIT_WEEK,
                  SEC_HL_WEEK, SEC_ENTRIES, SEC_MOODS, SEC_INCOME,
                  SEC_MDATES, SEC_PEOPLE, SEC_LAST_MONTH, SEC_MONTHLY_JNL,
                  SEC_MREVIEW],
    "quarterly": [SEC_OKR, SEC_QTR_YEAR, SEC_QTR_QTR, SEC_HIGHLIGHT,
                  SEC_TOP_LIST, SEC_TOP_TASKS, SEC_CREATED, SEC_COMPLETED,
                  SEC_QBARS, SEC_FOCUS_WEEK, SEC_HABIT_WEEK,
                  SEC_HL_WEEK, SEC_ENTRIES, SEC_MOODS, SEC_INCOME,
                  SEC_MDATES, SEC_PEOPLE, SEC_LAST_QTR, SEC_QTR_JNL,
                  SEC_QREVIEW],
    "yearly":    [SEC_OKR, SEC_MONEY],
}

# Which GROUP header an anchor lives under, per tier. A weekly note now
# repeats names on purpose - "- Completed: 78" is this week's and
# "- Completed: 387" is last week's - so every writer that could collide
# names its container and ps.find/find_prefix look nowhere else. An anchor
# missing from here is searched document-wide, as it always was.
SECTION_SCOPE = {
    "weekly": {
        SEC_WK_QTR: SEC_GOALS, SEC_WK_MONTH: SEC_GOALS, SEC_WK_WEEK: SEC_GOALS,
        SEC_TOP_LIST: SEC_WK_STATS, SEC_TOP_TASKS: SEC_WK_STATS,
        SEC_CREATED: SEC_WK_STATS, SEC_COMPLETED: SEC_WK_STATS,
        SEC_WBARS: SEC_WK_STATS, SEC_FOCUS_WEEK: SEC_WK_STATS,
        SEC_HABIT_WEEK: SEC_WK_STATS, SEC_ALIGNED: SEC_WK_STATS,
        SEC_HL_WEEK: SEC_WK_DATA,
        SEC_ENTRIES: SEC_WK_DATA, SEC_MOODS: SEC_WK_DATA,
        SEC_INCOME: SEC_WK_DATA, SEC_PEOPLE: SEC_WK_DATA,
        SEC_MEALPREP: SEC_WK_DATA,
    },
    # same two group headers, same bullet names, one tier up
    "monthly": {
        SEC_MTH_QTR: SEC_GOALS, SEC_MTH_MONTH: SEC_GOALS,
        SEC_TOP_LIST: SEC_WK_STATS, SEC_TOP_TASKS: SEC_WK_STATS,
        SEC_CREATED: SEC_WK_STATS, SEC_COMPLETED: SEC_WK_STATS,
        SEC_MBARS: SEC_WK_STATS, SEC_FOCUS_WEEK: SEC_WK_STATS,
        SEC_HABIT_WEEK: SEC_WK_STATS,
        SEC_HL_WEEK: SEC_WK_DATA,
        SEC_ENTRIES: SEC_WK_DATA, SEC_MOODS: SEC_WK_DATA,
        SEC_INCOME: SEC_WK_DATA, SEC_PEOPLE: SEC_WK_DATA,
        SEC_MDATES: SEC_WK_DATA,
    },
    # the same two group headers again - a quarter is a month with a longer
    # ruler, and every writer keeps its name
    "quarterly": {
        SEC_QTR_YEAR: SEC_GOALS, SEC_QTR_QTR: SEC_GOALS,
        SEC_TOP_LIST: SEC_WK_STATS, SEC_TOP_TASKS: SEC_WK_STATS,
        SEC_CREATED: SEC_WK_STATS, SEC_COMPLETED: SEC_WK_STATS,
        SEC_QBARS: SEC_WK_STATS, SEC_FOCUS_WEEK: SEC_WK_STATS,
        SEC_HABIT_WEEK: SEC_WK_STATS,
        SEC_HL_WEEK: SEC_WK_DATA,
        SEC_ENTRIES: SEC_WK_DATA, SEC_MOODS: SEC_WK_DATA,
        SEC_INCOME: SEC_WK_DATA, SEC_PEOPLE: SEC_WK_DATA,
        SEC_MDATES: SEC_WK_DATA,
    },
}


def scope_of(kind, anchor):
    """The container `anchor` must be looked up inside, or None."""
    return SECTION_SCOPE.get(kind, {}).get(anchor)

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
    """The note's own NAME: the tier emoji, then the stable id, then (weekly
    only) its date range - "2026-W37" alone says nothing about which days it
    covers (Vex 2026-09-12).

    The emoji is HERE and not in title(), which stays the bare stable id: it
    is the note's name on the board, not its identity. title() goes on
    building the index keys and the crumb link labels inside other notes,
    where the arrows already say which way you are travelling."""
    base = f"{title(p)} • {date_range(p)}" if p.kind == "weekly" else title(p)
    return f"{TIER_EMOJI[p.kind]} {base}"


def tag(p):
    return TIER_TAGS[p.kind]


def title_key(p):
    """Index-lookup key: daily matches by ISO-date title PREFIX (tolerates
    day-abbr drift), other tiers by the STABLE id - the part before " • ", so
    a weekly note keeps its identity whether or not its name carries the date
    range (see long_title)."""
    return p.start.isoformat() if p.kind == "daily" else title(p)


def stable_key(note_title):
    """The index key for a non-daily note TITLE: everything before " • ",
    without the tier emoji."""
    return strip_tier_emoji(note_title).split(" • ")[0].strip()


def note_day(p):
    """The day a periodic note sits on in TickTick (at pm.note_time): its
    period's LAST day
    (Vex 2026-09-19: "Daily note should get scheduled. Full day item for
    corresponding day. Weekly for Sunday end of week, monthly for 30th of
    the month" - the 30th read as the month's last day, so February, 31-day
    months, quarters and the year all land where their period ends)."""
    return p.end


def note_time(p):
    """The local time a periodic note sits at on its day (Vex 2026-09-24:
    "Daily notes should get scheduled on the day at 4:30am and weekly or
    monthly or quarterly on 5 am"). 04:30 is also when the agent mints the
    day; the yearly note sits at 05:00 with the other long tiers."""
    import datetime as _dt
    return _dt.time(4, 30) if p.kind == "daily" else _dt.time(5, 0)


def period_from_title(kind, note_title):
    """The Period a note's TITLE names, or None - the index key read back
    (daily "2026-09-23 · Wed", weekly "2026-W39 • 21st-27th Sep", monthly
    "2026-09 September", quarterly "2026-Q3", yearly "2026"; the tier emoji
    and the weekly date range are tolerated)."""
    try:
        if kind == "daily":
            d = parse_daily_title(note_title)
            return period_for("daily", d) if d else None
        key = stable_key(note_title or "")
        if kind == "weekly":
            m = re.match(r"^(\d{4})-W(\d{2})$", key)
            d = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1) if m else None
        elif kind == "monthly":
            m = re.match(r"^(\d{4})-(\d{2})(?:\s|$)", key)
            d = date(int(m.group(1)), int(m.group(2)), 1) if m else None
        elif kind == "quarterly":
            m = re.match(r"^(\d{4})-Q([1-4])$", key)
            d = date(int(m.group(1)), 3 * (int(m.group(2)) - 1) + 1, 1) if m else None
        elif kind == "yearly":
            m = re.match(r"^(\d{4})$", key)
            d = date(int(m.group(1)), 1, 1) if m else None
        else:
            return None
    except (ValueError, AttributeError):
        return None
    return period_for(kind, d) if d else None


def parse_daily_title(s):
    """The date a daily note's TITLE stands for, or None. Tolerates the tier
    emoji, so a note minted before 2026-09-17 and one minted after land on
    the same index key."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", strip_tier_emoji(s))
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


# ── Week-day links (lead, under the crumb) ───────────────────────────────────
# Vex 2026-09-17: "below breadcrumbs, links to days of that week". He typed
# the first two into the live note himself, so the label shape is his:
# "Mon, 14th Sep". Matches a bullet whether we wrote it or he did (the app
# escapes brackets on a hand edit: `- \[Mon, 14th Sep\]\(url\)`).
# The WHOLE label has to be there - day, ordinal AND month. "- Mon, 3 people
# coming" is a line Vex could write in the lead, and a looser match would eat it.
DAY_LINK_RE = re.compile(
    r"^\s*[-*]\s+\\?\[?(?:" + "|".join(DAY_ABBR) + r"), "
    r"\d{1,2}(?:st|nd|rd|th) (?:" + "|".join(MONTH_ABBR[1:]) + r")\b")


def day_link_label(d):
    return f"{DAY_ABBR[d.weekday()]}, {_ord(d.day)} {MONTH_ABBR[d.month]}"


def day_link_lines(p, url_for):
    """Weekly only: one bullet per day of the week, linked when that day's
    note exists. A day with no note yet is plain text and self-heals into a
    link on a later refresh - the breadcrumb rule (see render_breadcrumb).
    Other tiers get [] - a yearly period would otherwise render 365 lines."""
    if p.kind != "weekly":
        return []
    out, d = [], p.start
    while d <= p.end:
        label = day_link_label(d)
        u = url_for(period_for("daily", d))
        out.append(f"- [{label}]({u})" if u else f"- {label}")
        d += timedelta(days=1)
    return out


def set_day_links(doc, lines):
    """Splice the day bullets into the lead under the breadcrumb: replaces the
    existing run in place, else inserts it (with its own `---`) after the
    crumb's divider. For notes _compose_lead will never rebuild again - a week
    sealed before this shipped. Returns changed?"""
    if not lines:
        return False
    lead = doc.lead
    hits = [i for i, l in enumerate(lead) if DAY_LINK_RE.match(l)]
    if hits:
        # EVERY day bullet goes, not just the first unbroken run: a hand-typed
        # list with a line in the middle of it would otherwise keep the tail
        # and end up with the week in the note twice.
        kept = [l for i, l in enumerate(lead) if i not in set(hits)]
        out = kept[:hits[0]] + list(lines) + kept[hits[0]:]
    else:
        at = next((i + 1 for i, l in enumerate(lead)
                   if l.strip().startswith("---")), 1 if lead else 0)
        out = lead[:at] + list(lines) + ["---"] + lead[at:]
    if out == lead:
        return False
    doc.lead = out
    return True



# ── A month's weeks (Vex 2026-09-17: "Everywhere you write W1 add date range")
def count_task_lines(counts, n=3, gi=T1):
    """top_task_lines' rows from already-summed {title: times} - the monthly
    reads its weeks' rankings rather than the completion records."""
    return [f"{gi}- {nm[:64]}" + (f" · {c}×" if c > 1 else "")
            for nm, c in top_n(counts, n)]


def count_list_lines(pairs, n=3, gi=T1):
    """top_list_lines' rows from already-summed {name: (done, added)}."""
    traffic = {nm: d + a for nm, (d, a) in (pairs or {}).items()}
    return [f"{gi}- {nm} · {pairs[nm][0]} done · {pairs[nm][1]} added"
            for nm, _c in top_n(traffic, n)]


CHILD_KIND = {"weekly": "daily", "monthly": "weekly",
              "quarterly": "monthly", "yearly": "quarterly"}


def child_spans(p):
    """[(n, child period, start, end)] - the periods one tier down that a note
    covers, numbered from 1 within it and CLIPPED to it.

    Only weeks straddle: a month always sits inside one quarter and a quarter
    inside one year, so for those tiers the clip is the child itself. Numbered
    by the PARENT (Vex's "Week1 1st-7th Sep"), because that is how he reads a
    note; the child's own id is one click away in its title."""
    kind = CHILD_KIND.get(p.kind)
    if not kind:
        return []
    out, d, n = [], p.start, 0
    while d <= p.end:
        cp = period_for(kind, d)
        n += 1
        out.append((n, cp, max(cp.start, p.start), min(cp.end, p.end)))
        d = cp.end + timedelta(days=1)
    return out


def span_label(kind, n, a, b):
    """The label a parent gives one of its children, with its dates on it
    (Vex 2026-09-17: "Everywhere you write W1 add date range").

        weekly    → "Mon, 14th Sep"        (a day names itself)
        monthly   → "W1 · 1st-6th Sep"
        quarterly → "M1 · July"
        yearly    → "Q1 · Jan-Mar"
    """
    if kind == "weekly":
        return day_link_label(a)
    if kind == "monthly":
        return week_span_label(n, a, b)
    if kind == "quarterly":
        return f"M{n} · {MONTH_NAME[a.month]}"
    return f"Q{n} · {MONTH_ABBR[a.month]}-{MONTH_ABBR[b.month]}"


def child_link_lines(p, url_for):
    """One bullet per child period, linked where its note exists. A child with
    no note yet is plain text and heals into a link on a later refresh - the
    breadcrumb rule (see render_breadcrumb)."""
    out = []
    for n, cp, a, b in child_spans(p):
        label = span_label(p.kind, n, a, b)
        u = url_for(cp)
        out.append(f"- [{label}]({u})" if u else f"- {label}")
    return out


def month_week_spans(p):
    """[(n, week_period, start, end)] - the ISO weeks a month touches,
    numbered 1..5 within the month and CLIPPED to it.

    Numbered by MONTH, not by ISO year, because that is how Vex wrote the
    layout ("Week1 1st-7th Sep"); the ISO number is one click away in the
    week note's own title. Clipped, because every number in a monthly note is
    about the month's own days - a week straddling two months contributes only
    the part that is in this one, the rule the money roll-up has always used.
    """
    out, d, n = [], p.start, 0
    while d <= p.end:
        wp = period_for("weekly", d)
        n += 1
        out.append((n, wp, max(wp.start, p.start), min(wp.end, p.end)))
        d = wp.end + timedelta(days=1)
    return out


def week_span_label(n, a, b):
    """'W1 · 1st-6th Sep' · a one-day tail is just '30th Sep'."""
    if a == b:
        return f"W{n} · {_ord(a.day)} {MONTH_ABBR[a.month]}"
    if a.month == b.month:
        return f"W{n} · {_ord(a.day)}-{_ord(b.day)} {MONTH_ABBR[b.month]}"
    return (f"W{n} · {_ord(a.day)} {MONTH_ABBR[a.month]}-"
            f"{_ord(b.day)} {MONTH_ABBR[b.month]}")


def done_span_lines(rows):
    """'- W1 · 1st-6th Sep ▇▇▇ 12' per row, then the month total.

    rows = [(label, count | None[, why])]. None is NOT zero: it means there is
    no number to read, and a 0 there would read as a span he got nothing done
    in. `why` names which kind of nothing. The bar scales to the biggest
    known span."""
    nums = [r[1] for r in rows if r[1] is not None]
    mx = max(nums, default=0)
    out = []
    for row in rows:
        label, c = row[0], row[1]
        if c is None:
            # a row may say WHY: a note that does not exist and one that
            # exists with no numbers in it are different facts, and the head
            # two lines above links the second one
            out.append(f"- {label} · {row[2] if len(row) > 2 else 'no note'}")
            continue
        bar = "▇" * max(1, round(c / mx * 7)) if mx and c else ""
        out.append(f"- {label} " + (f"{bar} {c}" if bar else f"{c}"))
    out.append(f"**Month: {sum(nums)}**")
    return out


def mood_span_lines(rows, gi=T1):
    """😊 Moods body for a MONTH: one line per week (Vex 2026-09-17 - "in
    moods instead of day, week 1, week 2… Average for month"). A week with no
    mood logged is left out; the month average rides the section header, the
    way the week's does."""
    out = []
    for label, avg in rows:
        if avg is None:
            continue
        # round ONCE, then read the face off the rounded number: 3.45 printed
        # "3.5" beside the face for 3
        shown = round(avg, 1)
        face = MOOD_FACES[max(1, min(5, int(shown + 0.5)))]
        out.append(f"{gi}- {label} · {face} {shown:.1f}")
    return out


def top_entries(items, week_of, n=5):
    """The n entries of each kind worth resurfacing at month's end.

    Nothing an entry carries says how big it was, so "top 5" has to be a RULE
    (Vex 2026-09-17: "it should resurface top 5 of the month for each … not
    sure how you do those calculations"). The rule: one per week, newest
    first, then fill what is left by recency. Five wins then come from across
    the month instead of all from its last few days, which is the only
    reading of "of the month" that survives being read once a month.

    items = [(date, hm, glyph, body)]; week_of(date) → the week it belongs to.

    With more weeks than slots (a month can touch six ISO weeks) the oldest
    weeks lose theirs: the walk is newest-first and stops at n.
    """
    out = []
    for glyph in GROUP_ORDER:
        grp = sorted([it for it in items if it[2] == glyph],
                     key=lambda it: (it[0], it[1]), reverse=True)
        picked, seen = [], set()
        for it in grp:                       # one per week, newest first
            if len(picked) >= n:
                break
            w = week_of(it[0])
            if w not in seen:
                seen.add(w)
                picked.append(it)
        for it in grp:                       # then the newest of what is left
            if len(picked) >= n:
                break
            if it not in picked:
                picked.append(it)
        out.extend(picked)
    return out


# ── Reading a sealed week back (the money pyramid, one tier up) ─────────────
# A month cannot recount its own completions: get_completed(days=15, limit=500)
# reaches back about nine days at Vex's rate. The weekly notes ARE the record
# for everything completed, so the monthly reads them - the same rule money has
# always used, and the reason a weekly note's numbers are never refilled once
# its week has closed. These are the inverses of the renderers above; anything
# that does not parse is dropped, never guessed.
_BAR_RE = re.compile(
    r"^\s*[-*]\s+(?P<dow>" + "|".join(DAY_ABBR) + r")\s+[▇\s]*(?P<n>\d+)\s*$")
_PROJ_RE = re.compile(r"^\s*[-*]\s+🗂\s+(?P<name>.+?)\s+·\s+(?P<n>\d+)\s*$")
_TOPLIST_RE = re.compile(
    r"^\s*[-*]\s+(?P<name>.+?)\s+·\s+(?P<done>\d+) done\s+·\s+(?P<add>\d+) added\s*$")
_TOPTASK_RE = re.compile(r"^\s*[-*]\s+(?P<name>.+?)(?:\s+·\s+(?P<n>\d+)×)?\s*$")


def parse_day_bars(lines, monday=None):
    """'- Mon ▇▇▇ 12' rows → {weekday_index: count}, or {date: count} when a
    monday is given. The bar itself is decoration; the number is the record."""
    out = {}
    for ln in lines or []:
        m = _BAR_RE.match(unescape_md(ln))
        if not m:
            continue
        i = DAY_ABBR.index(m.group("dow"))
        out[monday + timedelta(days=i) if monday else i] = int(m.group("n"))
    return out


def parse_proj_lines(lines):
    """'- 🗂 📌CTA · 13' rows → {list name: count}."""
    out = {}
    for ln in lines or []:
        m = _PROJ_RE.match(unescape_md(ln))
        if m:
            out[m.group("name").strip()] = int(m.group("n"))
    return out


def parse_top_list_lines(lines):
    """'- 📌CTA · 13 done · 14 added' rows → {name: (done, added)}."""
    out = {}
    for ln in lines or []:
        m = _TOPLIST_RE.match(unescape_md(ln))
        if m:
            out[m.group("name").strip()] = (int(m.group("done")),
                                            int(m.group("add")))
    return out


def parse_top_task_lines(lines):
    """'- Commute · 4×' / '- Did a thing' rows → {title: times}. A line with
    no ×N was done once - that is what top_task_lines renders."""
    out = {}
    for ln in lines or []:
        raw = unescape_md(ln)
        if _TOPLIST_RE.match(raw) or _PROJ_RE.match(raw) or _BAR_RE.match(raw):
            continue                       # a neighbour's shape, not ours
        m = _TOPTASK_RE.match(raw)
        if not m:
            continue
        name = strip_md_links(m.group("name").strip())
        if not name or PENDING_RE.match(name):
            continue
        out[name] = int(m.group("n") or 1)
    return out


def merge_counts(*maps):
    """Sum {name: count} maps - the month's ranking from its weeks'."""
    out = {}
    for mp in maps:
        for k, v in (mp or {}).items():
            out[k] = out.get(k, 0) + v
    return out


def merge_pairs(maps):
    """Sum {name: (done, added)} maps - Top lists, a month's worth."""
    out = {}
    for mp in maps or []:
        for k, (d, a) in (mp or {}).items():
            pd, pa = out.get(k, (0, 0))
            out[k] = (pd + d, pa + a)
    return out


def top_n(counts, n=3):
    """[(name, count)] busiest first, ties alphabetical (a refresh that
    changes nothing must rewrite nothing)."""
    return sorted((counts or {}).items(), key=lambda kv: (-kv[1], kv[0]))[:n]

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
# The sign is INSIDE the group: parse_amount reads a leading "-" off the raw
# string, so leaving it outside made a refund read back as income (found
# 2026-09-17: "-50" parsed as 50, and a bump then ADDED it).
MONEY_ANSWER_RE = re.compile(r"(?<![\w.,])([-−]?\d[\d.,]*)")
MONEY_SEPS = (" · ", " - ", " • ")
MONEY_LABEL_CAP = 6


def parse_money_answer(text):
    """Evening-journal money answer → amount | None (first number wins).

    Unescaped first: the TickTick app saves "1250\\.50", and reading that
    without unescaping dropped the decimals."""
    m = MONEY_ANSWER_RE.search(unescape_md(text or ""))
    return parse_amount(m.group(1)) if m else None


def money_answer_line(total, labels):
    """The canonical shape the 💰 verb writes back into that answer: the
    running total, then what it was for. Labels are de-duplicated (case
    blind) and capped - a bump appended unconditionally, so five entries for
    the same client listed it five times."""
    seen, out = set(), []
    for l in labels or []:
        l = " ".join((l or "").split())
        if l and l.casefold() not in seen:
            seen.add(l.casefold())
            out.append(l)
    tail = ", ".join(out[:MONEY_LABEL_CAP])
    return fmt_amount(total) + (f" · {tail}" if tail else "")


def split_money_answer(text):
    """An answer → (amount|None, [labels]).

    The canonical "485 · tattoo, deposit" splits on its separator. ANYTHING
    ELSE is a sentence a human typed, and it is kept WHOLE as a single label
    rather than thrown away: bumping "500 for the sleeve, 2 sessions" used to
    rewrite it as "600 · deposit" and the sentence was simply gone
    (2026-09-17). Keeping the original whole is mildly redundant - its number
    appears twice - and that is the right trade against losing what he wrote.
    """
    raw = unescape_md(text or "")
    amt = parse_money_answer(raw)
    if amt is None:
        rest = " ".join(raw.split())
        return None, ([rest] if rest else [])
    m = MONEY_ANSWER_RE.search(raw)
    tail = raw[m.end():]
    for sep in MONEY_SEPS:
        if tail.startswith(sep):
            return amt, [x.strip() for x in tail[len(sep):].split(",") if x.strip()]
    rest = " ".join(raw.split())
    # an answer that is ONLY the number carries no words to keep, and listing
    # "0" or "-50" as its own label is noise
    return amt, ([rest] if rest and rest != m.group(1).strip() else [])


def money_answer_update(prev, amount, label="", replace=False):
    """(new answer text, the amount it had before).

    ONE rule for both doors into a day's money - the 💰 row and the evening
    journal write the same line, so they cannot drift. `replace` swaps the
    number for the new one; the default sums into it and keeps the labels.
    """
    had, labels = split_money_answer(prev)
    if replace:
        return money_answer_line(amount, [label]), had
    return money_answer_line((had or 0) + amount, list(labels) + [label]), had


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


def day_label(d, today=None):
    """"Mon 14 Sep", and "Mon 14 Sep 2025" when it is not this year.

    A retrospective entry must ALWAYS say which day it hit, and a screen that
    can reach any past date must not make last year look like this one - the
    bare stamp rendered 2025-09-15 and 2026-09-15 identically."""
    today = today or _dayroll_today()
    base = f"{DAY_ABBR[d.weekday()]} {d.day} {MONTH_ABBR[d.month]}"
    return base if d.year == today.year else f"{base} {d.year}"


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


def entries_grouped(items, glyphs=None, gi=T1, ei=T2, dated=False):
    """items = [(date, hm, glyph, body)] → 📨 Entries body: grouped by type,
    newest first inside each group, timestamp AFTER the text
    ('- body · Thu 14:32'), tab-nested (gi = group indent, ei = entry
    indent).

    Each group heading is a BULLET with a blank line above it (Vex's
    2026-09-17 layout): a week's worth of thoughts under one unbulleted bold
    line ran together into a wall of text in the app."""
    lines = []
    for glyph in (glyphs or GROUP_ORDER):
        grp = sorted([it for it in items if it[2] == glyph],
                     key=lambda it: (it[0], it[1]), reverse=True)
        if not grp:
            continue
        if lines:
            lines.append("")
        lines.append(f"{gi}- **{glyph} {GROUP_LABELS[glyph]}**")
        for d, hm, _g, body in grp:
            when = (f"{DAY_ABBR[d.weekday()]} {d.day} {MONTH_ABBR[d.month]}"
                    if dated else DAY_ABBR[d.weekday()])
            lines.append(f"{ei}- {body} · {when} {hm}")
    return lines


def mood_week_lines(moods, gi=T1, ei=T2):
    """😊 Moods body from [(date, (score, note))]: one line per day, and the
    day's note as a CHILD bullet rather than a `·` tail (Vex 2026-09-17 - a
    paragraph about a bad night does not belong on the same line as a face).
    The average is NOT here: it rides the section header."""
    out = []
    for d, m in moods or []:
        score, note = (m + ("",))[:2] if isinstance(m, tuple) else (m, "")
        out.append(f"{gi}- {DAY_ABBR[d.weekday()]} {MOOD_FACES[int(score)]}")
        if note:
            out.append(f"{ei}- {note}")
    return out


DAY_FULL = ["monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday"]
_DAY_AGO_RE = re.compile(r"^-?(\d{1,3})\s*(?:d|days?)?(?:\s+ago)?$")


def past_day(token, today=None):
    """A day token for a RETROSPECTIVE entry → date | None.

    Looks BACKWARD, which is the whole point: you are filling in a day you
    have already lived. A weekday name means the MOST RECENT one, today
    included - never next week's. (dateutil.parse_date is parsedatetime and
    resolves "tuesday" forward, so it is the wrong tool for this one job.)

    Understood: "" or "today" · "yesterday" · a weekday name or any prefix of
    one from three letters up · "-2" / "2d" / "2 days ago" · a day of the
    month 1-31 (this month, or last month when that day has not come round
    yet) · an ISO date. Anything else, or any day in the FUTURE, is None -
    there is no money in a day you have not had.
    """
    today = today or _dayroll_today()
    t = " ".join((token or "").split()).casefold().lstrip("*@").strip()
    if not t or t == "today":
        return today
    if t == "yesterday":
        return today - timedelta(days=1)
    for i, name in enumerate(DAY_FULL):
        if len(t) >= 3 and name.startswith(t):
            back = (today.weekday() - i) % 7
            return today - timedelta(days=back)
    m = _DAY_AGO_RE.match(t)
    if m:
        n = int(m.group(1))
        # a bare 1-31 with no unit is a day OF THE MONTH ("the 9th"), which is
        # how the add bar already reads a bare number; "2d" or "-2" is an
        # offset. The regex keeps them apart by whether a unit or sign is there
        if t[0] in "-" or t.rstrip().endswith(("d", "day", "days", "ago")):
            d = today - timedelta(days=n)
            return d if d <= today else None
        if 1 <= n <= 31:
            for month_back in (0, 1):
                y, mo = today.year, today.month - month_back
                if mo < 1:
                    y, mo = y - 1, mo + 12
                try:
                    d = date(y, mo, n)
                except ValueError:
                    continue
                if d <= today:
                    return d
            return None
    try:
        d = date.fromisoformat(t)
    except ValueError:
        return None
    return d if d <= today else None


def drop_lists(tasks, skip):
    """`tasks` minus the rows belonging to any project id in `skip`.

    None passes straight through: an unreadable completed feed must stay
    unreadable, never quietly read as empty. `projectId` first and the
    workflow's own `_projectId` after it, the same order _by_proj uses - a
    row off the completed feed carries only the former, a cached row both.
    """
    if tasks is None:
        return None
    skip = {s for s in (skip or ()) if s}
    if not skip:
        return list(tasks)
    return [t for t in tasks
            if (t.get("projectId") or t.get("_projectId") or "") not in skip]


def task_ignored(name, names):
    """True when a task NAME is one the summaries are told to drop.

    Matched on the flattened, casefolded title: exactly, or as its first
    WORDS. "Commute" therefore also covers "Commute Copied Copied", which is
    what a duplicated repeat leaves behind in a sealed ranking, and never
    covers "Commuter belt"."""
    n = mdtext.flatten_links(name or "").strip().casefold()
    if not n:
        return False
    for want in names or ():
        w = (want or "").strip().casefold()
        if w and (n == w or n.startswith(w + " ")):
            return True
    return False


def drop_task_names(tasks, names):
    """`tasks` minus the rows whose title is ignored. None passes straight
    through, the way drop_lists treats an unreadable feed."""
    if tasks is None:
        return None
    names = [n for n in (names or ()) if n]
    if not names:
        return list(tasks)
    return [t for t in tasks if not task_ignored(t.get("title") or "", names)]


def drop_task_counts(counts, names):
    """{name: count} minus the ignored names. A SEALED note hands its
    rankings back as text, so the rule has to reach them there too - the
    same reason _ignored_names exists for lists."""
    names = [n for n in (names or ()) if n]
    if not names:
        return dict(counts or {})
    return {k: v for k, v in (counts or {}).items() if not task_ignored(k, names)}


def top_list_lines(done_bp, created_bp, n=3, gi=T1):
    """Top lists body: the n busiest lists (done + added), busiest first.
    Ties break alphabetically so a refresh that changes nothing rewrites
    nothing."""
    traffic = {}
    for src in (done_bp, created_bp):
        for nm, c in (src or {}).items():
            traffic[nm] = traffic.get(nm, 0) + c
    top = sorted(traffic.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return [f"{gi}- {nm} · {(done_bp or {}).get(nm, 0)} done · "
            f"{(created_bp or {}).get(nm, 0)} added" for nm, _c in top]


def task_counts(tasks):
    """{display title: times completed} - the ranking behind top_task_lines,
    exposed so a MONTH can sum its weeks' without re-deriving the rules
    (top-level only, a repeating task counts once per occurrence)."""
    counts = {}
    for t in (tasks or []):
        if t.get("parentId"):
            continue
        name = mdtext.flatten_links(t.get("title") or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1
    return counts


def top_task_lines(tasks, n=3, gi=T1):
    """Top tasks body: the n titles completed MOST OFTEN this week, ties
    broken by the most recent completion.

    Frequency, not recency (Vex 2026-09-17 reads it that way: "start up and
    shutdown are always gonna appear as top tasks of the week since they are
    done 7 days a week"), which also makes it the twin of Top lists.
    Subtasks are their parent's detail and never a task of their own; a
    repeating task leaves one completion record per occurrence, which is the
    count.
    """
    counts, last, order = {}, {}, []
    for t in (tasks or []):
        if t.get("parentId"):
            continue
        name = mdtext.flatten_links(t.get("title") or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key not in counts:
            counts[key], order = 0, order + [(key, name)]
        counts[key] += 1
        ct = t.get("completedTime") or ""
        if ct > last.get(key, ""):
            last[key] = ct
    ranked = sorted(order, key=lambda kn: last.get(kn[0], ""), reverse=True)
    ranked.sort(key=lambda kn: -counts[kn[0]])          # stable: count, then recency
    return [f"{gi}- {name[:64]}" + (f" · {counts[key]}×" if counts[key] > 1 else "")
            for key, name in ranked[:n]]


# ── 📌 This Week composite helpers ───────────────────────────────────────────
def indent(lines):
    return ["    " + ln for ln in lines]


def chip(cur, prev, kind="count"):
    """vs-last-week chip: '🟢 ▲ 12 (+9%)' / '🔴 ▼ 714 (−78%)' / '⚪ ▬'.
    None prev → None.

    Arrows since 2026-09-17 (Vex: "changed comparisons to use the arrows like
    we did in daily note"). The traffic light stays, because this line has to
    read at a glance from across the room and the daily note's bare ▲/▼ does
    not: colour says good/bad, the arrow says which way, and the sentence the
    chip used to spell out ("7 tasks behind last week") was three words of
    padding around one number.
    """
    if prev is None or cur is None:
        return None
    diff = cur - prev
    if kind == "avg":
        # a mood average is one decimal - 2.74 vs 2.71 is the same mood, and
        # rounding BEFORE the zero test keeps "⚪ ▬" honest rather than
        # drawing an arrow over "0.0"
        diff = round(diff, 1)
    if not diff:
        return "⚪ ▬"
    if kind == "duration":
        mag = fmt_hm(int(abs(diff)))
    elif kind == "money":
        mag = fmt_amount(abs(diff))
    elif kind == "avg":
        mag = f"{abs(diff):.1f}"
    else:
        mag = f"{int(abs(diff))}"
    pct = f" ({'+' if diff > 0 else '−'}{abs(diff) / abs(prev) * 100:.0f}%)" if prev else ""
    return f"{'🟢 ▲' if diff > 0 else '🔴 ▼'} {mag}{pct}"


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


def drop_checkbox_lines(body_lines, names=(), pids=()):
    """Checkbox lines minus the ignored task names and the ignored lists.

    Only LINKED lines are touched - a line Vex typed himself survives
    whatever it says, because the engine did not put it there and has no
    business taking it away. And only UNTICKED ones: a ticked line is a
    record of something he did, and the sweep still has to read it."""
    names = [n for n in (names or ()) if n]
    pids = {p for p in (pids or ()) if p}
    if not names and not pids:
        return list(body_lines)
    out = []
    for ln in body_lines:
        cb = fb.CHECKBOX_RE.match(ln)
        tail = fb.LINK_TAIL_RE.search(ln) if cb else None
        if tail and cb.group("mark") not in "xX" and (
                tail.group("pid") in pids
                or task_ignored(mdtext.flatten_links(cb.group("body")), names)):
            continue
        out.append(ln)
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
JOURNAL_RANDOM_K = {"morning": 3, "evening": 5, "weekly": 5,
                    "monthly": 5, "quarterly": 5}   # the legacy draw: a plain {'random'} dict, or a date before a tier's epoch

# The daily random block (Vex 2026-09-24): SIX prompts, two per category.
# The morning draws its three categories every day; the evening draws three
# of its six, the window sliding one step a day, so each category lands on
# three evenings in six. Friday evening is chain night: the block is ONE
# chain asked in order (Sunday is the weekly review, so not Sunday). Pools
# cycle per category without repeats; POOL_EPOCH is day 0 of the rotation.
MORNING_CATEGORIES = ("prepare", "people", "perspective")
EVENING_CATEGORIES = ("review", "control", "virtue", "desire", "connection", "open")
JOURNAL_PER_CATEGORY = 2
EVENING_CATEGORIES_PER_DAY = 3
CHAIN_WEEKDAY = 4                      # Friday
POOL_EPOCH = date(2026, 9, 25)
# The weekly random block (Vex 2026-09-24, late): TEN prompts, two from EVERY
# category, cycling per category by week; no chains. WEEK_EPOCH is the first
# Monday whose note is seeded the new way (W39 was seeded the old way).
WEEKLY_CATEGORIES = ("retrospect", "priorities", "energy", "people", "open")
WEEK_EPOCH = date(2026, 9, 28)
# The monthly random block (Vex 2026-09-24, late: "the bigger the scope, the
# more retrospective"): TEN prompts, two from every category, cycling per
# category by month; MONTH_EPOCH is the first month seeded the new way.
MONTHLY_CATEGORIES = ("patterns", "direction", "cost", "people", "open")
MONTH_EPOCH = date(2026, 10, 1)
# The quarterly random block (Vex 2026-09-24, late night: "10"): TEN prompts,
# two from every category, cycling per category by quarter, from a pool of
# thirty (six a category: each prompt is asked once in every three quarters
# and never two quarters running; repeats land two to four quarters apart).
# QUARTER_EPOCH is the first quarter seeded the new way: Q3 2026, whose
# journal was reseeded clean (it was all unanswered).
QUARTERLY_CATEGORIES = ("lookback", "lessons", "decisions", "direction", "system")
QUARTER_EPOCH = date(2026, 7, 1)


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
        # 🔮 the forecast (Vex 2026-09-24): the evening quotes this answer
        # back in its own check. Ahead of "What is on your mind?", which is
        # the LAST set prompt on both journals: the border before the random
        # block.
        out.append(("forecast", "🔮 What is the intention for today? How will this "
                                "day go, what will you achieve? Forecast the best "
                                "scenario."))
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
        out = [
            ("bridge", "🌉 Daily bridge - what should tomorrow-you know? "
                       "(saves to the Bridges board + tomorrow's note)"),
            # ✨ right after the bridge (Vex 2026-09-17: "logged on shutdown …
            # somewhere at the beggining, after bridge or whatever"). BEFORE
            # the goal question on purpose: tgoal hands off to the Alfred goal
            # picker, which stops the dialog run, so anything behind it is
            # answered in a second sitting.
            ("dhighlight", "✨ What was the highlight of the day? "
                           "Think of one thing that stands out."),
            ("tgoal", "🎯 What is the goal for tomorrow? The one thing that, "
                      "if done, makes the day a success?"),
            ("goal", goal_q),
        ]
        # 🔑 today's key result and 🥅 the month's objectives (Vex 2026-09-24:
        # "Currently we only ask about goal"), each only when the note's
        # 🥅 OKRs section plans one (ruling: skip, never ask about nothing).
        # Then 🔮 the morning forecast quoted back, always. ctx text comes
        # off the note at run time (_refresh_fixed_q), never the 04:30 mint.
        kr = (ctx.get("kr") or "").strip()
        if kr:
            word = "key results" if " · " in kr else "key result"
            out.append(("kr", f"🔑 Did you achieve or make progress on today's {word}, {kr}?"))
        objs = (ctx.get("objectives") or "").strip()
        if objs:
            word = "objectives" if " · " in objs else "objective"
            out.append(("objectives", f"🥅 How are you progressing on this month's {word}, {objs}?"))
        fc = _clip(ctx.get("forecast"), 140)
        out.append(("fcheck", f"🔮 How did the day go compared to your morning forecast: {fc}?"
                              if fc else
                              "🔮 How did the day go compared to what you expected this morning?"))
        out += [
            ("money", "How much money did you earn today?"),
            ("rating", "Rate the day, 1-5 stars"),
            # the border: last set prompt, the random block follows
            ("free", "What is on your mind?"),
        ]
        return out
    if slot == "quarterly":
        return _quarterly_fixed(ctx)
    if slot == "monthly":
        word = "month"
        # the weekly's two, one tier up. No picker handoff: next month's goal
        # is set from the 🎯 row like every other tier's, and a month is not
        # a three-things horizon.
        adj = "monthly"
        goals = (ctx.get("goals") or "").strip()
        weeks = (ctx.get("weeks") or "").strip()
        out = [
            (f"{word[0]}highlight",
             f"What was the highlight of the {word}? "
             "Think of one thing that stands out."
             + (f" Your weeks: {weeks}" if weeks else "")),
            (f"{word[0]}goals",
             (f"Did you achieve your {adj} goals, {goals}? "
              "Describe success/fail factors on each."
              if goals else
              f"Did you achieve your {adj} goals? "
              "Describe success/fail factors on each.")),
        ]
        # the monthly is the OKR checkpoint (Vex 2026-09-24, late): the
        # month's objectives one by one, the quarter's guiding-star check,
        # the month's habit line, the money line with its chip, each only
        # when the note carries it; "What is on your mind?" is the border
        # before the ten drawn prompts, the open-ended goal editor follows.
        objs = (ctx.get("objectives") or "").strip()
        if objs:
            out.append(("mobjectives", f"🥅 Objective by objective, {objs}: what moved, "
                                       "what stalled, and why?"))
        quarter = (ctx.get("quarter") or "").strip()
        if quarter:
            left = ctx.get("months_left")
            if left is not None and left <= 0:
                q = (f"🌓 The quarter's objectives, {quarter}: this was its last month. "
                     "Which carry into next quarter, and which stop here?")
            else:
                when = (f"with {left} month{'s' if left != 1 else ''} left" if left
                        else "with the quarter still running")
                q = (f"🌓 The quarter's objectives, {quarter}, {when}: still the right "
                     "ones? What to cut, add or move in the timeline?")
            out.append(("qcheck", q))
        habits = (ctx.get("habits") or "").strip()
        if habits:
            out.append(("habits", f"🔄 Habit consistency this month: {habits}. "
                                  "Which held all month, which only held for a week?"))
        money = (ctx.get("money") or "").strip()
        if money:
            out.append(("mmoney", f"💰 Income this month: {money}. Does this align with "
                                  "your forecast? What could you do to improve it?"))
        # Vex's six (2026-09-24, late: "month should be more set"), after the
        # OKR block, before the border; fixed wording, recognised by rule so
        # an older note gains them on its next run
        out += [
            ("mgrateful", "🙏 What three things, moments or people are you most grateful "
                          "for over the past month?"),
            ("mlearned", "📚 What have you learned this month? Think of the challenges."),
            ("mkeep", "♻️ What would you like to keep doing next month exactly as you "
                      "did this month?"),
            ("mchange", "🔧 What must change next month? What can you improve?"),
            ("mdrained", "🪫 What drained your energy this month?"),
            ("mtime", "⏳ How do you want to spend your time next month?"),
            ("free", "What is on your mind?"),
        ]
        return out
    # weekly - the three-things picker is NOT a seeded question: it runs as
    # the Alfred goal-picker handoff after the dialogs (phones edit next
    # week's 🎯 Goals directly instead)
    goals = (ctx.get("goals") or "").strip()
    goals_q = (f"Did you achieve your weekly goals, {goals}? "
               "Describe success/fail factors on each."
               if goals else
               "Did you achieve your weekly goals? "
               "Describe success/fail factors on each.")
    # the days' own ✨ highlights ride the question (Vex 2026-09-24), after
    # the fixed stem the key rule matches on
    days = (ctx.get("days") or "").strip()
    out = [
        ("highlight", "What was the highlight of the week? "
                      "Think of one thing that stands out."
                      + (f" Your days: {days}" if days else "")),
        ("wgoals", goals_q),
    ]
    # 🥅 the month's objectives BEFORE 🔑 the week's key results (ruling),
    # then 🔄 the habit line off 📊 Stats; each only when the note has it.
    # "What is on your mind?" is the border before the ten drawn prompts; the
    # three-things picker still follows the whole run.
    objs = (ctx.get("objectives") or "").strip()
    if objs:
        word = "objectives" if " · " in objs else "objective"
        out.append(("objectives", f"🥅 How are you progressing on this month's {word}, {objs}?"))
    kr = (ctx.get("kr") or "").strip()
    if kr:
        word = "key results" if " · " in kr else "key result"
        out.append(("kr", f"🔑 Did you achieve or make progress on this week's {word}, {kr}?"))
    habits = (ctx.get("habits") or "").strip()
    if habits:
        out.append(("habits", f"🔄 Habit consistency this week: {habits}. "
                              "Which habit earned its keep, which did not, and why?"))
    # 🔮 last Sunday's intention quoted back (the weekly refresh copies it
    # into ⏪ Last week), the week's stars (the answer is the record), then
    # the intention for the week ahead (Vex 2026-09-24: "The intention for
    # the week goes. Rate the week goes.")
    fc = _clip(ctx.get("wforecast"), 140)
    out.append(("wfcheck", f"🔮 How did the week go compared to last week's forecast: {fc}?"
                           if fc else
                           "🔮 How did the week go compared to what you expected?"))
    out.append(("wrating", "Rate the week, 1-5 stars"))
    out.append(("wforecast", "🔮 What is the intention for next week? How will it go, "
                             "what will you achieve? Forecast the best scenario."))
    out.append(("free", "What is on your mind?"))
    return out


def _quarterly_fixed(ctx):
    """The quarterly set block (Vex 2026-09-24, late night): his findings as
    fixed questions around the OKR checkpoint one tier up, every line quoting
    what the note already knows. He REMOVED the prose-planning questions
    (differently this / next quarter, the plan, how achieve, one rule): the
    goal editor after the run is the plan. Order: look back (three highlights
    with the months' ✨ and the 🟢 wins, three lowlights with the 🔴 nags and
    the moods), score (his goals stem, objective by objective + the bar, the
    year's goal with the quarters it has left, this quarter against last with
    last quarter's own wish echoed), the lines (habits, income + an expense
    to cut, effort with the focus hours), his three (passionate/bored, top
    three priorities, pace + where in 3 months), "What is on your mind?" the
    border before the ten drawn prompts. Conditional lines skip when the note
    has nothing to quote (CONDITIONAL_KEYS)."""
    def _s(k):
        return (ctx.get(k) or "").strip()

    def _q(label, text):
        """" Your nags: <text>." - a quote that already ends a sentence
        (a nag logged with its full stop) is not given a second one."""
        return f" {label}: {text}" + ("" if text[-1] in ".!?" else ".")
    goals, months, wins = _s("goals"), _s("months"), _s("wins")
    nags, moods = _s("nags"), _s("moods")
    out = [
        ("qhighlight", "✨ What are the three biggest highlights of the quarter?"
                       + (_q("Your months", months) if months else "")
                       + (_q("Your wins", wins) if wins else "")),
        ("qlowlights", "🔴 What are the three biggest lowlights?"
                       + (_q("Your nags", nags) if nags else "")
                       + (_q("Moods", moods) if moods else "")),
        ("qgoals", (f"Did you achieve your quarterly goals, {goals}? "
                    "Describe success/fail factors on each."
                    if goals else
                    "Did you achieve your quarterly goals? "
                    "Describe success/fail factors on each.")),
    ]
    objs = _s("objectives")
    if objs:
        out.append(("qobjectives", f"🥅 Objective by objective, {objs}: hit, partial or miss, "
                                   "and the factor that decided it? Was the bar set too high "
                                   "or too low?"))
    year = _s("year")
    if year:
        left = ctx.get("quarters_left")
        if left is not None and left <= 0:
            q = (f"🎉 The year's goal, {year}: this was its last quarter. "
                 "Which carry into next year, and which stop here?")
        else:
            when = (f"with {left} quarter{'s' if left != 1 else ''} left" if left
                    else "with the year still running")
            q = (f"🎉 The year's goal, {year}, {when}: ahead, on track or behind, and "
                 "what must next quarter deliver? Has this review given you "
                 "information that alters your yearly goals?")
        out.append(("ycheck", q))
    compare, wanted = _s("compare"), _s("wanted")
    if compare or wanted:
        out.append(("qcompare", "⏪ How does this quarter compare to last quarter?"
                                + (f" {compare}." if compare else "")
                                + (_q("Last quarter you wanted", wanted) + " Did you get there?"
                                   if wanted else "")))
    habits = _s("habits")
    if habits:
        out.append(("habits", f"🔄 Habit consistency this quarter: {habits}. Which held, "
                              "which broke, and which habits do you want to build next "
                              "quarter?"))
    money = _s("money")
    if money:
        out.append(("qmoney", f"💰 Income this quarter: {money}. Does this align with your "
                              "forecast? What could you do to improve it? Can you cut down "
                              "on any expense category?"))
    focus = _s("focus")
    out += [
        ("qeffort", "⏱ What effort is not worth your time, what are you spending your time "
                    "on that is not leading towards the desired outcome?"
                    + (_q("Your focus", focus) if focus else "")),
        ("qenergy", "🔥 When did you feel most passionate this quarter, and why then? "
                    "When did you feel bored or resentful, and why?"),
        ("qpriorities", "🧭 What are your top three priorities, and why do they matter?"),
        ("qforecast", "🔮 If you continue at this pace, where will you be in three months? "
                      "Where do you want to be in 3 months? What do you want to achieve?"),
        ("free", "What is on your mind?"),
    ]
    return out


# Which fixed question a seeded Q line IS, by its wording. Every question
# journal_fixed has ever seeded must match its rule (older wordings too), and
# no rule may match another key's question or a pool prompt.
JOURNAL_KEY_RULES = (
    # 1-5 with ANY dash: the app (and Vex) rewrite the hyphen as an en or em
    # dash when a question gets edited in TickTick, and two live morning
    # journals carry that shape - a mood answer that does not route is a mood
    # that never reaches the note's summary
    ("mood", re.compile(r"^Mood 1[-\u2010-\u2015]5\b")),
    ("ybridge", re.compile(r"^🌉 Yesterday's bridge\b")),
    # the sun with or without VARIATION SELECTOR-16 (a phone edit drops it)
    ("gcheck", re.compile(r"^☀️? (?:Does your goal for today still align|What is today's goal\?)")),
    ("bridge", re.compile(r"^🌉 Daily bridge\b")),
    ("tgoal", re.compile(r"^🎯 What is the goal for tomorrow\?")),
    ("goal", re.compile(r"^Did you achieve your daily goal\b")),
    ("money", re.compile(r"^How much money did you earn today\?")),
    ("rating", re.compile(r"^Rate the day\b")),
    # the 2026-09-24 set: the morning forecast and its evening check share
    # the 🔮 glyph but never a stem; the OKR pair is keyed on its own verbs
    ("forecast", re.compile(r"^🔮 What is the intention for today\?")),
    ("fcheck", re.compile(r"^🔮 How did the day go\b")),
    ("kr", re.compile(r"^🔑 Did you achieve or make progress on\b")),
    ("objectives", re.compile(r"^🥅 How are you progressing on\b")),
    ("habits", re.compile(r"^🔄 Habit consistency\b")),
    # the weekly's 🔮 pair and stars: "next week" / "the week" keep them apart
    # from the daily's "today" / "the day"
    ("wforecast", re.compile(r"^🔮 What is the intention for next week\?")),
    ("wfcheck", re.compile(r"^🔮 How did the week go\b")),
    ("wrating", re.compile(r"^Rate the week\b")),
    # the quarterly's set block (2026-09-24, late night). qobjectives shares
    # the monthly's stem and is told apart by its verdict words, so it MUST
    # sit before mobjectives; ⏱ with or without VS16
    ("qobjectives", re.compile(r"^🥅 Objective by objective\b.*: hit, partial or miss, and the factor "
                               r"that decided it\? Was the bar set too high or too low\?$")),
    ("qlowlights", re.compile(r"^🔴 What are the three biggest lowlights\?")),
    ("ycheck", re.compile(r"^🎉 The year's goal\b")),
    ("qcompare", re.compile(r"^⏪ How does this quarter compare\b")),
    ("qmoney", re.compile(r"^💰 Income this quarter\b")),
    ("qeffort", re.compile(r"^⏱\ufe0f? What effort is not worth your time\b")),
    ("qenergy", re.compile(r"^🔥 When did you feel most passionate\b")),
    ("qpriorities", re.compile(r"^🧭 What are your top three priorities\b")),
    ("qforecast", re.compile(r"^🔮 If you continue at this pace\b")),
    # the monthly's OKR checkpoint and money line (2026-09-24, late)
    ("mobjectives", re.compile(r"^🥅 Objective by objective\b")),
    ("qcheck", re.compile(r"^🌓 The quarter's objectives\b")),
    ("mmoney", re.compile(r"^💰 Income this month\b")),
    # Vex's six monthly set questions (emoji-prefixed so no pool prompt can
    # match; VS16 optional where the glyph carries one)
    ("mgrateful", re.compile(r"^🙏 What three things, moments or people\b")),
    ("mlearned", re.compile(r"^📚 What have you learned this month\?")),
    ("mkeep", re.compile(r"^♻️? What would you like to keep doing\b")),
    ("mchange", re.compile(r"^🔧 What must change next month\?")),
    ("mdrained", re.compile(r"^🪫 What drained your energy\b")),
    ("mtime", re.compile(r"^⏳ How do you want to spend your time\b")),
    # the day's and the week's highlights are DIFFERENT answers in different
    # notes, so their rules must not be able to match each other's question
    ("dhighlight", re.compile(r"^✨ What was the highlight of the day\?")),
    ("highlight", re.compile(r"^What was the highlight of the week\?")),
    ("wgoals", re.compile(r"^Did you achieve your weekly goals\b")),
    # …and the month's are a third pair again: every rule here has to be
    # unable to match any other key's question, or an answer routes into the
    # wrong tier's note
    ("mhighlight", re.compile(r"^What was the highlight of the month\?")),
    ("mgoals", re.compile(r"^Did you achieve your monthly goals\b")),
    # the quarter's: the old single-highlight stem and the three-highlights one
    ("qhighlight", re.compile(r"^(?:✨ )?What (?:was the highlight|are the three biggest highlights) of the quarter\?")),
    ("qgoals", re.compile(r"^Did you achieve your quarterly goals\b")),
)


_MD_ESCAPE_RE = re.compile(r"\\([!-/:-@\[-`{-~])")        # \ + any ASCII punctuation


def unescape_md_lines(lines):
    """unescape_md over a block. Every MIRROR passes its lines through this:
    the app backslash-escapes a line Vex edits in TickTick, and a raw copy
    carried that "\\[Goal\\]\\(url\\)" down the quarter → month → week →
    day chain, where it renders as literal brackets and never heals
    (review 2026-09-17, live in his notes)."""
    return [unescape_md(l) for l in (lines or [])]


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


def is_chain_night(which, d):
    """Friday evening: the random block is one chain, asked in order."""
    return which == "evening" and d.weekday() == CHAIN_WEEKDAY


def _chain_nights_before(d):
    """Chain nights in [POOL_EPOCH, d)."""
    if d <= POOL_EPOCH:
        return 0
    days = (d - POOL_EPOCH).days
    return sum(1 for i in range(days)
               if (POOL_EPOCH + timedelta(days=i)).weekday() == CHAIN_WEEKDAY)


def _evening_index(d):
    """Number of drawing (non-chain) evenings in [POOL_EPOCH, d): the
    category window's position. 0 for any day before the epoch, so an old
    day seeded later gets the first window."""
    if d <= POOL_EPOCH:
        return 0
    return (d - POOL_EPOCH).days - _chain_nights_before(d)


def journal_categories(which, d):
    """The categories a date's random block draws from, in order. Morning:
    all three, every day. Evening: three of the six, the window sliding one
    step per drawing evening; a chain night draws none (and does not move the
    window)."""
    if which == "morning":
        return list(MORNING_CATEGORIES)
    if which != "evening" or is_chain_night(which, d):
        return []
    n, k = _evening_index(d), len(EVENING_CATEGORIES)
    return [EVENING_CATEGORIES[(n + i) % k] for i in range(EVENING_CATEGORIES_PER_DAY)]


def _appearances(which, cat, d):
    """How many draws `cat` had before day d: its position in its own cycle."""
    if which == "morning":
        return max(0, (d - POOL_EPOCH).days)
    n, k = _evening_index(d), len(EVENING_CATEGORIES)
    j = EVENING_CATEGORIES.index(cat)
    hits = {(j - i) % k for i in range(EVENING_CATEGORIES_PER_DAY)}
    full, rem = divmod(n, k)
    return full * EVENING_CATEGORIES_PER_DAY + sum(1 for r in range(rem) if r in hits)


def _cycle_order(prompts, key, cyc):
    """The shuffled order of cycle `cyc` of a category's list. From the
    second cycle on, the previous cycle's last JOURNAL_PER_CATEGORY prompts
    are kept out of the first JOURNAL_PER_CATEGORY slots (moved to the end,
    in order), so a draw that straddles a cycle boundary never asks one
    prompt twice and the next draw never repeats the previous one (review
    2026-09-24: an odd-sized category hit both). That promise holds for
    lists of at least 2*per+2 prompts (six at two a draw, the shipped
    minimum); a shorter list (a user override of four or five) only keeps
    _draw's own guarantee, never twice in one draw. Lists shorter than two
    draws are left alone. random.Random(key:cycle) - NEVER hash(), which is
    salted per process."""
    n, per = len(prompts), JOURNAL_PER_CATEGORY
    # the draw before the boundary, the straddling one and the one after it
    # together reach 2*per-1 slots either side, so the old cycle's last
    # 2*per-1 prompts stay out of the new cycle's first 2*per-1 slots (as
    # far as n allows), the newest of them moved furthest back
    span = 2 * per - 1
    guard = min(span, n - span)
    order, tail = [], ()
    for c in range(cyc + 1):
        order = random.Random(f"{key}:{c}").sample(list(prompts), n)
        if tail and guard > 0:
            for _ in range(span):
                bad = [p for p in order[:guard] if p in tail]
                if not bad:
                    break
                bad.sort(key=tail.index)
                order = [p for p in order if p not in bad] + bad
        tail = tuple(order[-span:])
    return order


def _draw(prompts, key, position, k):
    """k prompts from `position` of a per-category cycle (_cycle_order):
    nothing repeats until the whole list has been asked. A list too short
    for the cycle guard (a user override of three) still never asks one
    prompt twice in the same draw."""
    n = len(prompts)
    out = []
    for i in range(k if n else 0):
        cyc, off = divmod(position + i, n)
        order = _cycle_order(prompts, key, cyc)
        pick = order[off]
        if pick in out and n > len(out):
            pick = next(p for p in order[off:] + order[:off] if p not in out)
        out.append(pick)
    return out


def select_prompts(pool, d, which, k=None):
    """The date's random block, deterministic across processes.

    A daily pool with categories: two prompts per drawn category
    (journal_categories), each category cycling through its own list; a
    chain night returns one chain's steps in order (chains rotate by chain
    night, the file's order). The weekly pool: two from EVERY
    WEEKLY_CATEGORIES category, cycling by week index from WEEK_EPOCH; the
    monthly and the quarterly the same by month / quarter index from their
    epochs. Everything else - a plain {'random': [...]} dict and any date
    before the epochs - keeps the old k seeded-random picks from 'random'.
    Fixed prompts live in journal_fixed, not the pool."""
    if k == 0:
        return []
    cats = pool.get("categories") or {}
    want = MORNING_CATEGORIES if which == "morning" else EVENING_CATEGORIES
    # a day before the epoch (a skipped day re-seeded later) keeps the OLD
    # draw, the date's own picks from the whole list: the cycles only start
    # at POOL_EPOCH, and every earlier day would otherwise share day 0's block
    if which in ("morning", "evening") and any(c in cats for c in want) and d >= POOL_EPOCH:
        if is_chain_night(which, d):
            chains = [c for c in (pool.get("chains") or []) if c.get("category") in want and c.get("prompts")]
            if chains:
                return list(chains[_chain_nights_before(d) % len(chains)]["prompts"])
            # no chain to ask: an old-style draw of the block's size, which
            # cannot collide with Saturday's window (Fridays do not move it)
            rnd_pool = list(pool.get("random", []))
            kk = min(JOURNAL_PER_CATEGORY * EVENING_CATEGORIES_PER_DAY, len(rnd_pool))
            return random.Random(f"{d.isoformat()}:{which}").sample(rnd_pool, kk) if kk else []
        # k= is the single-pool tiers' count; a category pool always draws
        # JOURNAL_PER_CATEGORY per category (the cycle stride)
        out = []
        for c in journal_categories(which, d):
            lst = list(cats.get(c) or [])
            out += _draw(lst, f"{which}:{c}", _appearances(which, c, d) * JOURNAL_PER_CATEGORY,
                         min(JOURNAL_PER_CATEGORY, len(lst)))
        return out
    # the weekly: every category, two each, cycling by week (any day of the
    # week gives the week's picks: the note is pinned to its Monday)
    if which == "weekly" and any(c in cats for c in WEEKLY_CATEGORIES) and d >= WEEK_EPOCH:
        wk = (d - WEEK_EPOCH).days // 7
        out = []
        for c in WEEKLY_CATEGORIES:
            lst = list(cats.get(c) or [])
            out += _draw(lst, f"weekly:{c}", wk * JOURNAL_PER_CATEGORY, min(JOURNAL_PER_CATEGORY, len(lst)))
        return out
    # the monthly: every category, two each, cycling by month (any day of the
    # month gives the month's picks: the note is pinned to its first day)
    if which == "monthly" and any(c in cats for c in MONTHLY_CATEGORIES) and d >= MONTH_EPOCH:
        mi = (d.year - MONTH_EPOCH.year) * 12 + (d.month - MONTH_EPOCH.month)
        out = []
        for c in MONTHLY_CATEGORIES:
            lst = list(cats.get(c) or [])
            out += _draw(lst, f"monthly:{c}", mi * JOURNAL_PER_CATEGORY, min(JOURNAL_PER_CATEGORY, len(lst)))
        return out
    # the quarterly: every category, two each, cycling by quarter (any day
    # of the quarter gives its picks: the note is pinned to its first day)
    if which == "quarterly" and any(c in cats for c in QUARTERLY_CATEGORIES) and d >= QUARTER_EPOCH:
        qi = quarter_index(d)
        out = []
        for c in QUARTERLY_CATEGORIES:
            lst = list(cats.get(c) or [])
            out += _draw(lst, f"quarterly:{c}", qi * JOURNAL_PER_CATEGORY, min(JOURNAL_PER_CATEGORY, len(lst)))
        return out
    rnd_pool = list(pool.get("random", []))
    k = JOURNAL_RANDOM_K.get(which, 3) if k is None else k
    k = min(k, len(rnd_pool))
    return random.Random(f"{d.isoformat()}:{which}").sample(rnd_pool, k) if k else []


_PERSON_RE = re.compile(r"\[person(?:'s)?\]")


def pick_person(candidates, d):
    """A name for the day's [person] prompt from [(name, weight)] - weight
    is how often (family 3, friends 2, work and orbit 1) - seeded by the
    date, and never the name the day before got. Walked day by day from
    POOL_EPOCH so every day agrees on every other day's pick."""
    # sorted and merged by name: the pick must not depend on the cache's row
    # order (review 2026-09-24). A change of MEMBERSHIP still re-walks the
    # sequence; that looser rule is accepted.
    merged = {}
    for n, w in (candidates or []):
        if n and w > 0:
            merged[n] = max(w, merged.get(n, 0))
    cands = sorted(merged.items())
    if not cands:
        return ""
    if len(cands) == 1:
        return cands[0][0]

    def one(day, avoid=None):
        pool = [(n, w) for n, w in cands if n != avoid] or cands
        return random.Random(f"{day.isoformat()}:person").choices(
            [n for n, _w in pool], [w for _n, w in pool])[0]

    if d <= POOL_EPOCH:
        return one(d)
    prev, day = one(POOL_EPOCH), POOL_EPOCH
    while day < d:
        day += timedelta(days=1)
        prev = one(day, avoid=prev)
    return prev


def fill_person(text, name):
    """[person] → the name, [person's] → its possessive; no name = "someone
    close to you" / "their". "this [person's] character" reads "Ana's
    character"."""
    if "[person" not in (text or ""):
        return text
    who = name or "someone close to me"          # first person, like the prompt
    whos = f"{name}'s" if name else "their"
    out = _PERSON_RE.sub(lambda m: whos if m.group(0) == "[person's]" else who, text)
    return out.replace(f"this {whos}", whos)


_MDLINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_LATE_CHIP_RE = re.compile(r"\s*🔴\s*\d+d\b")
_PLAN_GLYPHS = {"🔑", "✅", "🥅", "🏔"}          # okr_notes' item glyphs, VS16 dropped
# fixed questions that only exist while the note plans something: dropped
# again while unanswered when the plan goes (periodic_engine._refresh_fixed_q)
CONDITIONAL_KEYS = ("kr", "objectives", "habits", "mobjectives", "qcheck", "mmoney",
                    "qobjectives", "ycheck", "qcompare", "qmoney")
# fixed questions that QUOTE free text (a forecast, a KR title): the needle
# readers and writers skip them, or "rate the day" inside a forecast would
# catch the stars (review 2026-09-24)
QUOTING_KEYS = ("fcheck", "kr", "objectives", "habits", "wfcheck", "mobjectives", "qcheck", "mmoney",
                "qobjectives", "ycheck", "qcompare", "qmoney", "qeffort", "qlowlights", "qhighlight")


def months_left_in_quarter(d):
    """Months of d's quarter AFTER d's month: 2, 1 or 0 (the last month)."""
    q_end = ((d.month - 1) // 3 + 1) * 3
    return q_end - d.month


def quarters_left_in_year(d):
    """Quarters of d's year AFTER d's quarter: 3, 2, 1 or 0 (the last)."""
    return 4 - ((d.month - 1) // 3 + 1)


def quarter_index(d):
    """Quarters from QUARTER_EPOCH's quarter to d's (0 in the epoch's)."""
    return ((d.year - QUARTER_EPOCH.year) * 4
            + (d.month - 1) // 3 - (QUARTER_EPOCH.month - 1) // 3)


def entry_children(body_lines, label, sub):
    """The bullets under the `sub` bullet under the top-level `label` bullet:
    💿 Data holds "- 📨 Entries" with "**🟢 Wins**" one level in and the wins
    one level under that. Depth is the indent width, so tabs and a phone's
    spaces both read; emoji, bold stars, case and escapes are ignored in the
    two labels. [] when either is missing."""
    want, want_sub = _label_key(label), _label_key(sub)
    out, on, sub_w = [], False, None
    for ln in body_lines or []:
        s = unescape_md(ln.strip())
        if not s:
            continue
        w = len(ln) - len(ln.lstrip("\t "))
        if w == 0:
            on = s.startswith("- ") and _label_key(s[2:]).startswith(want)
            sub_w = None
            continue
        if not on or not s.startswith("- "):
            continue
        if sub_w is None or w <= sub_w:
            sub_w = w if _label_key(s[2:]).startswith(want_sub) else None
            continue
        out.append(s[2:].strip())
    return out


_ENTRY_STAMP_RE = re.compile(r"\s·\s[A-Z][a-z]{2} \d{1,2} [A-Z][a-z]{2}(?: \d{2}:\d{2})?$")


def entries_summary(children, cap=8):
    """📨 Entries lines ("Did weekly review · Sun 20 Sep 09:58") without their
    stamps and their own full stops (a nag logged as a sentence would read
    "prompt.; next"), "; "-joined, the first `cap` with "(+N more)" after
    them."""
    texts = [mdtext.flatten_links(_ENTRY_STAMP_RE.sub("", c)).replace("**", "").strip().rstrip(".").strip()
             for c in children if c]
    texts = [t for t in texts if t]
    more = len(texts) - cap
    return "; ".join(texts[:cap]) + (f" (+{more} more)" if more > 0 else "")


_COMPARE_KEYS = ("Completed", "Focus", "Mood", "Income")
_PARTIAL_RE = re.compile(r"\b\d+ of \d+ (?:days|weeks|months|quarters)\b")


def quarter_compare(this, last):
    """"Completed 665 vs 500 · Focus 97h 11m vs 49h 00m · ..." from two
    {label: header text} dicts (📊 Stats / 💿 Data heads for this quarter,
    the ⏪ Last quarter lines for last); each head's first " · " token, "avg"
    and "Average" dropped; only labels both sides carry; a side summed out
    of SOME of its months ("665 · 1 of 3 months") drops its label, the
    roll-up's own rule (half a quarter against a whole one is a number
    nobody can act on); '' when none."""
    def first(v):
        v = v or ""
        if _PARTIAL_RE.search(v):
            return ""
        v = v.split(" · ")[0].strip()
        v = re.sub(r"^Average\s+", "", v)
        return re.sub(r"\s+avg$", "", v).strip()
    parts = []
    for k in _COMPARE_KEYS:
        a, b = first((this or {}).get(k)), first((last or {}).get(k))
        if a and b:
            parts.append(f"{k} {a} vs {b}")
    return " · ".join(parts)


def bullet_head(body_lines, label):
    """The TOP-LEVEL bullet's own text after its `label` ("- 💰 Income: 1845
    · 🔴 ▼ 200 (−26%)" with label "💰 Income" → "1845 · 🔴 ▼ 200 (−26%)"),
    '' when the bullet is missing or bare. Emoji, case and the app's escapes
    are ignored in the match."""
    want = _label_key(label)
    if not want:
        return ""
    for ln in body_lines or []:
        if ln[:1] in ("\t", " "):
            continue
        s = unescape_md(ln.strip())
        if not s.startswith("- ") or not _label_key(s[2:]).startswith(want):
            continue
        text = s[2:]
        for i in range(1, len(text) + 1):
            if _label_key(text[:i]) == want:
                return text[i:].strip().lstrip(":·").strip()
        return ""
    return ""


def _label_key(s):
    """A bullet label with its emoji, punctuation, spacing and case gone:
    "🔄 Habit consistency" and "Habit consistency" are the same bullet (the
    de-emoji / re-emoji edits ps._norm exists for)."""
    return re.sub(r"[\W_]+", "", unescape_md(s or "")).casefold()


def bullet_children(body_lines, label):
    """The child bullets (text after "- ") of the TOP-LEVEL bullet whose
    label is `label` (emoji, case and the app's escapes ignored), off a
    group section's body (📊 Stats holds "- Habit consistency" with its
    habits indented under it). [] when the bullet is missing."""
    want = _label_key(label)
    out, on = [], False
    for ln in body_lines or []:
        s = unescape_md(ln.strip())
        if not s:
            continue
        indented = ln[:1] in ("\t", " ")
        if not indented:
            on = s.startswith("- ") and _label_key(s[2:]).startswith(want)
            continue
        if on and s.startswith("- "):
            out.append(s[2:].strip())
    return out


def stars_answer(text):
    """"4" (or "4 something") → "★★★★"; None when the answer is not a
    1-5 rating. The day and the week rating store their stars this way."""
    m = re.match(r"^([1-5])(?!\d)", (text or "").strip())
    return "★" * int(m.group(1)) if m else None


def habit_summary(children):
    """"Weekly Review · 0/1 · 0%" lines → "Weekly Review 0/1 · ..." (the
    percent dropped: the fraction says it)."""
    parts = []
    for c in children:
        bits = [b.strip() for b in c.split(" · ")]
        parts.append(f"{bits[0]} {bits[1]}" if len(bits) > 1 else bits[0])
    return " · ".join(p for p in parts if p)


def days_summary(children):
    """The weekly 💿 Data ✨ Highlights lines ("Wed · Meal I prepped
    yesterday"), joined for the highlight question."""
    return "; ".join(c for c in children if c)


def okr_journal_ctx(body_lines, kr_tier="daily", keep_state=False):
    """(the `kr_tier` bullet's KR titles, this month's objectives with their
    d/n), each " · "-joined: okr_tier_items twice."""
    return (" · ".join(okr_tier_items(body_lines, kr_tier, keep_state)),
            " · ".join(okr_tier_items(body_lines, "monthly")))


def okr_tier_items(body_lines, tier, keep_state=False):
    """The `tier` bullet's plan items (names with their d/n) off a 🥅 OKRs
    section body (okr_notes.okr_section_lines shape: a tier bullet, its plan
    indented under it), [] when the tier has no plan. Done items keep their
    name (the question is about progress); keep_state=True keeps their
    ✅/🔑 glyph too (the weekly asks about the week's whole list). Lines are
    unescaped first: the app backslashes the link brackets."""
    def kids(emoji):
        base = emoji.replace("️", "")
        out, on = [], False
        for ln in body_lines or []:
            s = unescape_md(ln.strip())
            if not s.startswith("- "):
                continue
            indented = ln[:1] in ("\t", " ")
            if not indented:
                on = s[2:].replace("️", "").startswith(base)
                continue
            if on and not s[2:].startswith("+"):
                out.append(s[2:])
        return out

    def name(item, state=False):
        s = re.sub(r"\s+", " ", _LATE_CHIP_RE.sub("", _MDLINK_RE.sub(r"\1", item))).strip()
        head, _, rest = s.partition(" ")
        if head.replace("️", "") in _PLAN_GLYPHS:     # only a glyph is stripped
            return f"{head} {rest.strip()}" if state else rest.strip()
        return s

    items = [name(x, keep_state) for x in kids(TIER_EMOJI.get(tier, TIER_EMOJI["daily"]))]
    return [x for x in items if x]


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


def journal_answer_text(body_lines, a_idx):
    """The WHOLE answer whose A line is body_lines[a_idx]: the A-line text
    plus the continuation bullets under it (the dialog's multiline box lands
    every further paragraph as a sibling bullet under the A line), joined
    with a space, bullets and italics stripped. Stops at the next Q line, a
    divider, or a line no deeper than the Q line. '' when unanswered."""
    if not (0 < a_idx < len(body_lines)):
        return ""
    m = JOURNAL_A_RE.match(body_lines[a_idx])
    if not m:
        return ""
    parts = [m.group("a").strip()]
    q_line = body_lines[a_idx - 1]
    q_indent = len(q_line) - len(q_line.lstrip())
    for ln in body_lines[a_idx + 1:]:
        if not ln.strip():
            continue
        if JOURNAL_Q_RE.match(ln) or ln.strip() == "---":
            break
        if len(ln) - len(ln.lstrip()) <= q_indent:
            break
        t = ln.strip()
        if t.startswith("- "):
            t = t[2:]
        t = t.strip().strip("*").strip()
        if t:
            parts.append(t)
    return " ".join(x for x in parts if x)


def highlight_body(text):
    """The ✨ Highlight section body for a highlight answer: one line as it
    is (the weekly's shape since 2026-09-12); several lines (the quarterly's
    three biggest highlights, typed one per line) as bullets, links
    flattened, blanks dropped, a line already bulleted left alone."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) <= 1:
        return [text]
    return [ln if ln.startswith("- ") else f"- {mdtext.flatten_links(ln)}" for ln in lines]


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
    writes = []                  # (idx, lines) applied LAST, bottom-up, so a
    for n, text in answers.items():          # multi-line answer cannot shift
                                             # the indices still to be written
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
        # Paragraphs become sibling bullets: the shape a phone answer already
        # takes, and the one insert_fixed_questions already walks past. A
        # blank line between them would end the list in TickTick's renderer,
        # so the bullet IS the paragraph break.
        parts = [p.strip() for p in str(text).split("\n")]
        parts = [p for p in parts if p]
        lines = [f"{ws}{dash}{ital}A: {parts[0]}{ital}"]
        lines += [f"{ws}{dash}{ital}{p}{ital}" for p in parts[1:]]
        writes.append((idx, lines))
        used.add(idx)
        filled += 1
    for idx, lines in sorted(writes, key=lambda w: w[0], reverse=True):
        body[idx:idx + 1] = lines
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
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:[^()\n]|\([^()\n]*\))+\)")


def strip_md_links(s):
    """Repeated md-link strip + leftover URL-paren cleanup - titles that
    themselves contain ']' or '](' must not leak raw URLs into prompts."""
    prev = None
    while prev != s:
        prev = s
        s = _MD_LINK_RE.sub(r"\1", s)
    return re.sub(r"\(https?://[^)\s]*\)?", "", s).strip()


# A line the ENGINE writes into the yearly 🎯 Goals scorecard (okr_notes.
# scorecard_lines): "- 🏔️ <name> ▰▰▱▱▱ 4/10 · …" and "\t- 🥅 <name> 2/6 · …".
# That section is ALSO where the yearly goal setter appends Vex's picked
# goals (GOAL_SECTION["yearly"]), so every goal reader has to tell the two
# apart - or the plan's own rows come back as "goals": in the 🎉 year line
# beside the plan, in the quarterly note's 🎉 Yearly goal mirror, and as
# removable rows in the yearly goal editor. The shape is narrow on purpose:
# a bullet with NO checkbox, a 🏔️ or 🥅 straight after the dash, a d/n
# count - a picked goal is always "- [ ] …" (goal_line).
PLAN_LINE_RE = re.compile(
    r"^\s*- (?:\U0001F3D4\ufe0f?|\U0001F945\ufe0f?) .*\b\d+/\d+\b")


def is_plan_line(line):
    """True for a scorecard line the OKR filler owns (PLAN_LINE_RE)."""
    return bool(PLAN_LINE_RE.match(unescape_md(line or "")))


def goal_titles(body_lines):
    """Every real line of a goals-ish section → display text (checkbox +
    md-link stripped). The OKR plan's scorecard lines are not goals
    (PLAN_LINE_RE)."""
    out = []
    for ln in body_lines:
        # the TickTick app backslash-escapes markdown when the note is edited
        # there ("\_\(pick one...\)\_"), and an escaped placeholder was read
        # as the goal: "Did you achieve your daily goal, _(pick one...)?"
        s = unescape_md(ln.strip())
        if not s or PENDING_RE.match(s) or PENDING_RE.match(s[2:] if s.startswith("- ") else s):
            continue
        if PLAN_LINE_RE.match(s):
            continue
        # \s* not " ": the monthly template ships a BARE "- [ ]" and the
        # anchored form left it as "[ ]", which then read as a goal - the
        # weekly journal asked "did you achieve your goals, [ ]?" and the
        # 🗓️ Monthly mirror copied an empty box in as if it were one.
        s = re.sub(r"^- \[[ xX]\]\s*", "", s)
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
