#!/usr/bin/env python3
"""meal.py - the 🥘 Meal Prep model (PURE: stdlib only, no I/O).

Vex cooks on SUNDAY for the week ahead - a breakfast, a lunch, a snack,
seven portions each - and keeps the recipe library in Mela. Since
2026-09-21 the PLAN lives in Mela too (Vex: "I will be scheduling in Mela,
it is nicer"): Mela's "Add to Calendar" puts an event on the cook Sunday
whose url ends in the recipe UUID, and TickAL only MIRRORS that plan (the
calendar reader is src/mela_cal.py; this module turns its rows into weeks).
In TickTick the library is the 🍳Meal Prep list: one task per recipe,
title `[Name](mela://recipe/<UUID>)`, tagged 🍳breakfast / 🍛lunch /
🌮snack. The mirrored week is a POINTER task per meal under the repeating
🥘 Meal Prep routine (`🍳 [Name](mela://…)`, 🍽️ for a recipe outside the
three slots) plus a 🛒 grocery checklist per meal in the library list; the
library entries themselves never move (HANDOFF_MEAL.md). This module holds
the grammar of those titles, the slot logic, the week arithmetic and the
plan-to-weeks fold; nothing here talks to TickTick, Mela or the calendar.

The Mela UUID is the join key everywhere: Mela kept Crouton's ids on import,
the TickTick titles carry them, the calendar url carries them, and
`mela://recipe/<UUID>` opens the recipe on the Mac (verified 2026-09-19).
Titles saved by the TickTick app may be backslash-escaped, so every reader
goes through `parse_title`.

"Cooked" history is READ OFF THE CALENDAR PLAN (a past planned Sunday =
cooked): the cooked-history ledger of the picker era is gone with the
picker ("get rid of Plan the week / Schedule a meal").

Since 2026-09-21 the library also remembers Vex's verdict on a recipe (Vex:
"I would like to be able to mark meal cooked via modifier", "know which
meals I have cooked before, so I am thinking a tag", "rate a meal and give
a comment"). COOKED is the 👨‍🍳cooked tag on the library task: a tag,
because the calendar only knows what was PLANNED (a week can be skipped)
and TickTick groups by tag. The RATING is one quote line of ⭐️ right under
the link header of the description, each COMMENT one quote line below it
("a rating should be quote first liner below links in recipe, stars",
"comment should go below that also as quote", "retrospectively I also
should be able to add a comment, like add less salt next time"): quote
lines because that head block reads first in the app and survives a
re-render of the body. Mela is READ ONLY (a Core Data + CloudKit store, no
write intent, no URL verb), so TickTick is the record; Mela's own
"Rating: ⭐️⭐️⭐️" line (a plain line in the recipe's description or notes)
is only adopted into a task that has no rating yet.
"""
import json
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, time, timezone

try:
    import periodic_model as _pm
    _unescape = _pm.unescape_md
except Exception:                       # pure fallback, same effect
    _ESC = re.compile(r"\\([!-/:-@\[-`{-~])")

    def _unescape(text):
        text = text or ""
        for _ in range(4):
            out = _ESC.sub(r"\1", text)
            if out == text:
                break
            text = out
        return text

try:
    import mela as _mela
except Exception:                       # standalone: the mapping is small
    _mela = None

PORTIONS = 7
GROCERY_TAG = "🛒groceries"
GROCERY_GLYPH = "🛒"
COOKED_TAG = "👨‍🍳cooked"             # on the LIBRARY task; Vex made it under
COOKED_PARENT = "🍱mealprep"          # this parent tag (2026-09-21)
STAR = "⭐️"                 # ⭐️ as Mela writes it: U+2B50 + VS16
MAX_STARS = 5
# key, TickTick tag, glyph, label - in the order a week is planned
SLOTS = (("b", "🍳breakfast", "🍳", "Breakfast"),
         ("l", "🍛lunch", "🍛", "Lunch"),
         ("s", "🌮snack", "🌮", "Snack"))
SLOT_KEYS = tuple(s[0] for s in SLOTS)
# a planned recipe in none of the three Mela categories: shown, never
# dropped, no TickTick tag of its own
SLOT_X = ("x", "", "🍽️", "Other")
ALL_SLOTS = SLOTS + (SLOT_X,)
ALL_SLOT_KEYS = tuple(s[0] for s in ALL_SLOTS)
GLYPH = {s[0]: s[2] for s in ALL_SLOTS}
_SLOT_RANK = {k: i for i, k in enumerate(ALL_SLOT_KEYS)}
# Weekly notes minted before this day never had the 🥘 bullet: a missing
# bullet there is seeded once, a missing bullet later is Vex's deletion.
NOTE_SINCE = date(2026, 9, 20)

LINK_RE = re.compile(r"mela://recipe/([0-9A-Fa-f-]{36})")
_TITLE_RE = re.compile(r"\[(?P<name>[^\]]*)\]\(mela://recipe/(?P<id>[0-9A-Fa-f-]{36})\)")
# glyph -> key, with the 🍽️ pointer read both with and without its VS16
# (TickTick's app has been seen dropping the variation selector)
_GLYPHS = {s[2]: s[0] for s in ALL_SLOTS}
_GLYPHS[SLOT_X[2].replace("\ufe0f", "")] = SLOT_X[0]


# ── title grammar ────────────────────────────────────────────────────────────
def unescape(text):
    return _unescape(text)


def parse_title(title):
    """(name, UUID) from any title carrying a Mela link - a library entry,
    a pointer or a grocery list - or None. The UUID is upper-cased (Mela's
    own form); the name is the link label, whatever glyph precedes it."""
    m = _TITLE_RE.search(unescape(title or ""))
    if not m:
        return None
    return m.group("name").strip(), m.group("id").upper()


def link_uuid(title):
    m = LINK_RE.search(unescape(title or ""))
    return m.group(1).upper() if m else None


def md_link(name, uuid):
    name = re.sub(r"[\[\]\\]", "", name or "").strip() or "Recipe"
    return f"[{name}](mela://recipe/{uuid})"


def slot(key):
    """The SLOTS tuple for a key ('b' | 'l' | 's', and 'x' for 🍽️), else
    None."""
    return next((s for s in ALL_SLOTS if s[0] == key), None)


def slot_of_tags(tags):
    """Which slot a library entry belongs to, from its tags (SLOTS order
    decides when an entry somehow carries two). None when none."""
    have = {str(t).lower() for t in (tags or [])}
    for s in SLOTS:
        if s[1].lower() in have:
            return s[0]
    return None


def pointer_title(key, name, uuid):
    s = slot(key) or SLOT_X
    return f"{s[2]} {md_link(name, uuid)}"


def is_pointer(title):
    """A pointer WE minted: a slot glyph (🍳 🍛 🌮 🍽️), a space, then the
    Mela link."""
    t = unescape(title or "").strip()
    return any(t.startswith(g + " [") for g in _GLYPHS) and bool(LINK_RE.search(t))


def pointer_slot(title):
    t = unescape(title or "").strip()
    return next((k for g, k in _GLYPHS.items() if t.startswith(g + " [")), None)


def grocery_title(name, uuid):
    return f"{GROCERY_GLYPH} {md_link(name, uuid)}"


def is_grocery(title):
    t = unescape(title or "").strip()
    return t.startswith(GROCERY_GLYPH + " [") and bool(LINK_RE.search(t))


def is_library_title(title):
    """A plain library entry: a Mela link with NO glyph prefix."""
    t = unescape(title or "").strip()
    return t.startswith("[") and bool(_TITLE_RE.match(t))


# ── rating, comments, cooked ─────────────────────────────────────────────────
# The HEAD BLOCK of a recipe description is the leading run of quote lines
# mela.render_markdown (and mela2ticktick before it) puts on top: the 🔗
# link line, the 🌐 site line. Vex's verdicts live in that block, so they
# read first and outlive a re-render of the body: the stars line right
# after the last link line, then one quote line per comment, oldest first.
_STAR_GLYPHS = "⭐★"           # ⭐ (with or without VS16) and ★
# Mela's own line, as an older render copied it into the blurb or ## Notes
_MELA_RATING_RE = re.compile(r"^\s*Rating:\s*(?:⭐️?|★)+\s*$")


def stars(n):
    """n copies of ⭐️, at most MAX_STARS; '' for None, 0 or less."""
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return ""
    return STAR * min(max(n, 0), MAX_STARS)


def parse_stars(text):
    """What Vex typed into the rating dialog, as a count: '3', '3/5' or a
    row of ⭐️ / ⭐ / ★ / * glyphs -> 1..5 (more is capped); '0', 'none',
    'clear', '-' or nothing -> 0 (clear the rating); anything else ->
    None, so the verb can refuse instead of guessing."""
    t = (text or "").strip()
    if t.casefold() in ("", "0", "none", "clear", "-"):
        return 0
    m = re.fullmatch(r"(\d+)\s*(?:/\s*5)?", t)
    if m:
        return min(int(m.group(1)), MAX_STARS)
    bare = t.replace("️", "").replace(" ", "")
    if bare and all(c in _STAR_GLYPHS + "*" for c in bare):
        return min(len(bare), MAX_STARS)
    return None


def header_block(content):
    """(head, rest): the leading run of quote lines (every line starting
    with '>', a bare '>' included) and the text after them with the ONE
    blank line separating the two removed; ([], content) when the
    description does not start with a quote. Never raises on None."""
    content = content or ""
    if not content.startswith(">"):
        return [], content
    lines = content.split("\n")
    n = 0
    while n < len(lines) and lines[n].startswith(">"):
        n += 1
    tail = lines[n:]
    if tail and not tail[0].strip():
        tail = tail[1:]
    return lines[:n], "\n".join(tail)


def _rebuild(content, head, rest):
    """header_block's inverse: head, one blank line, the body untouched.
    With no body the result ends the way `content` ended: whatever
    trailing whitespace followed the original head lines comes back as it
    was (one newline, two, none), and an empty input gains nothing beyond
    the block."""
    if not head:
        return rest
    block = "\n".join(head)
    if (rest or "").strip():
        return block + "\n\n" + rest
    content = content or ""
    lines = content.split("\n")
    n = 0
    while n < len(lines) and lines[n].startswith(">"):
        n += 1
    if n:
        return block + content[len("\n".join(lines[:n])):]
    return block + ("\n" if content.endswith("\n") else "")


def _quote_text(line):
    """A quote line's text: the leading '>' (and the space after it) gone,
    both ends trimmed."""
    return re.sub(r"^>\s?", "", line or "").strip()


_LINK_LINE_RE = re.compile(r"^>\s*(?:🔗|🌐)\s")


def is_link_line(line):
    """A head line carrying the recipe link (🔗) or its web source (🌐) in
    the header shape mela.render_markdown / mint_header write: the glyph
    is the FIRST thing after the quote mark. A note that merely mentions
    the web ("> 🌐 the web version is better" is still a note when the
    glyph is not followed by a link, but "> see 🌐 for it" surely is) must
    not push the stars line below itself or vanish from the picker."""
    return bool(_LINK_LINE_RE.match(line or ""))


def is_stars_line(line):
    """A quote line whose text is nothing but 1..5 star glyphs (⭐️, ⭐
    or ★)."""
    line = line or ""
    if not line.startswith(">"):
        return False
    txt = _quote_text(line).replace("️", "").replace(" ", "")
    return bool(txt) and len(txt) <= MAX_STARS and all(c in _STAR_GLYPHS for c in txt)


def read_rating(content):
    """The count on the first stars line of the head block, else None
    (VS16 blind: the app has been seen dropping variation selectors)."""
    for l in header_block(content)[0]:
        if is_stars_line(l):
            return len(_quote_text(l).replace("️", "").replace(" ", ""))
    return None


def read_comments(content):
    """The head block's comment lines with the '> ' stripped: every line
    that is not a link line, not the stars line and not empty, in the
    order they were added."""
    out = []
    for l in header_block(content)[0]:
        if is_link_line(l) or is_stars_line(l):
            continue
        txt = _quote_text(l)
        if txt:
            out.append(txt)
    return out


def mint_header(name, uuid, web=""):
    """The head block a hand-written (or empty) description gets before a
    rating or comment can sit in it: the 🔗 line from the task title and,
    when the recipe's web page is known, the 🌐 line, both in the exact
    form mela.render_markdown writes (host = netloc without 'www.')."""
    head = [f"> 🔗 {md_link(name, uuid)}"]
    web = (web or "").strip()
    if web:
        host = urllib.parse.urlparse(web).netloc.replace("www.", "") or web
        head.append(f"> 🌐 [{host}]({web})")
    return head


def set_rating(content, n, header=None):
    """`content` with its rating set to n stars (1..5): the stars line
    goes right after the LAST link line, an existing one is replaced
    wherever it sat in the head. 0/None removes it. `header` (from
    mint_header) tops a description with no head block; without one the
    stars still land, as a head block of their own. The body below stays
    byte-identical, and a description that needs no change comes back as
    it was."""
    content = content or ""
    n = min(int(n or 0), MAX_STARS)
    head, rest = header_block(content)
    had = any(is_stars_line(l) for l in head)
    if n <= 0 and not had:
        return content                       # nothing to remove
    if not head:
        head = list(header or [])
    head = [l for l in head if not is_stars_line(l)]
    if n > 0:
        at = 0
        for i, l in enumerate(head):
            if is_link_line(l):
                at = i + 1
        head.insert(at, "> " + stars(n))
    return _rebuild(content, head, rest)


def add_comment(content, text, header=None):
    """`content` with one quote line per non-empty line of `text` appended
    at the END of the head block, after the stars and the earlier comments
    (Vex adds "less salt next time" after eating; the older verdicts stay,
    never replaced). Blank text leaves the description untouched; `header`
    as in set_rating."""
    content = content or ""
    lines = [re.sub(r"^>+\s*", "", l).strip() for l in (text or "").splitlines()]
    lines = [l for l in lines if l]
    if not lines:
        return content
    head, rest = header_block(content)
    if not head:
        head = list(header or [])
    head += ["> " + l for l in lines]
    return _rebuild(content, head, rest)


def strip_mela_rating(content):
    """Mela's own "Rating: ⭐️⭐️⭐️" line removed from the BODY (an older
    render copied it into the blurb or the ## Notes section); the head
    block is never touched, our stars line is not Mela's. A blank line the
    removal left doubled goes with it, and a ## Notes header left with
    nothing under it."""
    content = content or ""
    head, rest = header_block(content)
    lines = rest.split("\n")
    if not any(_MELA_RATING_RE.match(l) for l in lines):
        return content
    out, gap = [], False
    for l in lines:
        if _MELA_RATING_RE.match(l):
            gap = True
            continue
        if gap and not l.strip() and (not out or not out[-1].strip()):
            continue                         # the blank the line left doubled
        gap = False
        out.append(l)
    j = next((i for i, l in enumerate(out) if l.strip() == "## Notes:"), None)
    if j is not None and not any(l.strip() for l in out[j + 1:]):
        ends_nl = rest.endswith("\n")
        out = out[:j]
        while out and not out[-1].strip():
            out.pop()
        if out and ends_nl:
            out.append("")
    return _rebuild(content, head, "\n".join(out))


def adopt_mela_rating(content, n, header=None):
    """Mela's rating taken over by a task that has none: Mela's line leaves
    the body, the stars land in the head."""
    return set_rating(strip_mela_rating(content), n, header)


def cooked_payload(pid, tid, back=None):
    """The b64-able spec behind xact:meal_cooked (the tag + one note)."""
    p = {"pid": pid, "tid": tid}
    if back:
        p["back"] = back
    return p


def rate_payload(pid, tid, stars, back=None):
    """The spec behind xact:meal_rate: stars is the count (0 clears)."""
    p = {"pid": pid, "tid": tid, "stars": stars}
    if back:
        p["back"] = back
    return p


def comment_payload(pid, tid, back=None):
    """The spec behind xact:meal_comment (the text is asked for at run time)."""
    p = {"pid": pid, "tid": tid}
    if back:
        p["back"] = back
    return p


# ── the library as the screens see it ────────────────────────────────────────
def library_entries(tasks, list_id):
    """[{tid, pid, title, name, uuid, slot, tags, content, kind, cooked,
    rating}] for the open library entries of list_id among `tasks` (a
    cache pool or a project_data task list). Pointers, grocery lists and
    untagged strays are left out; `slot` is None for an entry without a
    meal tag; `cooked` = the 👨‍🍳cooked tag is on it (case blind), `rating`
    = the stars in the description's head block, else None."""
    out = []
    for t in tasks or []:
        if not isinstance(t, dict) or t.get("status", 0) != 0:
            continue
        pid = t.get("projectId") or t.get("_projectId") or ""
        if list_id and pid != list_id:
            continue
        title = t.get("title") or ""
        if not is_library_title(title):
            continue
        tags = [str(x).lower() for x in (t.get("tags") or [])]
        if GROCERY_TAG in tags:
            continue
        parsed = parse_title(title)
        if not parsed:
            continue
        name, uuid = parsed
        content = t.get("content") or ""
        out.append({"tid": t.get("id"), "pid": pid, "title": title, "name": name,
                    "uuid": uuid, "slot": slot_of_tags(tags), "tags": tags,
                    "content": content, "kind": t.get("kind") or "",
                    "cooked": COOKED_TAG.lower() in tags, "rating": read_rating(content)})
    return out


def entries_by_slot(entries):
    by = {k: [] for k in SLOT_KEYS}
    for e in entries:
        if e.get("slot") in by:
            by[e["slot"]].append(e)
    return by


def pointers_of(tasks, routine_id):
    """The open pointer children of the routine among `tasks`, keyed by
    slot ({key: task}); a SECOND pointer of an already-taken slot (the
    calendar can plan two breakfasts in a week) rides under "<key>:<tid>",
    so `.values()` is EVERY pointer and a delete-all never leaves a stale
    twin. Archived occurrences (repeatTaskId) never count."""
    out = {}
    for t in tasks or []:
        if not isinstance(t, dict) or t.get("status", 0) != 0:
            continue
        if t.get("parentId") != routine_id or t.get("repeatTaskId"):
            continue
        if not is_pointer(t.get("title") or ""):
            continue
        k = pointer_slot(t.get("title"))
        if not k:
            continue
        if k not in out:
            out[k] = t
        else:
            out[f"{k}:{t.get('id') or len(out)}"] = t
    return out


def groceries_of(tasks, list_id):
    """{UUID: task} for the open 🛒 grocery lists in the library list."""
    out = {}
    for t in tasks or []:
        if not isinstance(t, dict) or t.get("status", 0) != 0:
            continue
        pid = t.get("projectId") or t.get("_projectId") or ""
        if list_id and pid != list_id:
            continue
        if not is_grocery(t.get("title") or ""):
            continue
        u = link_uuid(t.get("title"))
        if u and u not in out:
            out[u] = t
    return out


# ── week arithmetic ──────────────────────────────────────────────────────────
def _local_date(iso):
    if not iso:
        return None
    try:
        txt = iso.replace("Z", "+00:00")
        if re.search(r"[+-]\d{4}$", txt):
            txt = txt[:-2] + ":" + txt[-2:]
        return datetime.fromisoformat(txt).astimezone().date()
    except (ValueError, TypeError, AttributeError):
        return None


def next_sunday(today):
    """Today when it is a Sunday, else the coming one."""
    return today + timedelta(days=(6 - today.weekday()) % 7)


def cook_week_of(d):
    """The Sunday on or before d: the cook day of the week d is eaten in
    (Vex puts a meal on the Sunday it is cooked; a meal dropped on a
    Wednesday still belongs to the Sunday before it)."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def cook_sunday(routine_task, today):
    """The Sunday the plan is FOR: the routine's live occurrence date when
    it is a Sunday on or after today (a repeating task rolls forward on
    completion, so a stale date means that week is done), else the next
    Sunday from today."""
    day = _local_date((routine_task or {}).get("startDate")
                      or (routine_task or {}).get("dueDate"))
    if day and day >= today and day.weekday() == 6:
        return day
    return next_sunday(today)


def grocery_day(sunday, today):
    """The Saturday before the cook Sunday - or today when that has passed
    (a plan made on the Sunday itself shops the same day)."""
    return max(sunday - timedelta(days=1), today)


def note_day(sunday):
    """A day inside the week the cooking FEEDS: the Monday after."""
    return sunday + timedelta(days=1)


def week_label(sunday):
    """'Week of 22 Sep' - named by the Monday the meals are eaten from."""
    return f"Week of {note_day(sunday):%-d %b}"


PREP_TITLE = "🥘 Meal Prep"          # the routine, and any copy Vex moves
GROCERIES_TITLE = "🛒 Groceries"     # the Saturday routine, moved the same way


def local_zone():
    """The Mac's zone (via /etc/localtime), DST-aware."""
    try:
        from zoneinfo import ZoneInfo
        name = os.path.realpath("/etc/localtime").split("zoneinfo/")[-1]
        return ZoneInfo(name)
    except Exception:
        return datetime.now().astimezone().tzinfo


def zone_of(task):
    """The zone a task's dates are READ in: its own timeZone field, else
    the Mac's. TickTick shows an all-day task on the date its stamp has in
    THAT zone - Vex's account writes Europe/London on API-made tasks while
    the Mac sits on Europe/Berlin, so a Berlin-midnight stamp on a London
    task showed the day before (2026-09-21)."""
    name = ((task or {}).get("timeZone") or "").strip()
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:
            pass
    return local_zone()


def zone_name(zone):
    return getattr(zone, "key", None) or str(zone)


def task_date(task):
    """The calendar day a task sits on, in its own zone (see zone_of)."""
    raw = (task or {}).get("startDate") or (task or {}).get("dueDate")
    if not raw:
        return None
    try:
        txt = str(raw).replace("Z", "+00:00")
        if re.search(r"[+-]\d{4}$", txt):
            txt = txt[:-2] + ":" + txt[-2:]
        return datetime.fromisoformat(txt).astimezone(zone_of(task)).date()
    except (ValueError, TypeError, AttributeError):
        return None


def api_day(d, zone=None):
    """The all-day form TickTick STORES: midnight of `d` in `zone` (the
    task's own, else the Mac's) written in UTC - "2026-09-26T22:00:00+0000"
    for a CEST 27 Sep, "…T23:00:00+0000" for a BST one. A bare "2026-09-27"
    is accepted by v1 and silently dropped: the first 🔄 press (2026-09-21
    20:00) came back undated."""
    zone = zone or local_zone()
    return (datetime.combine(d, time(0, 0), tzinfo=zone).astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S+0000"))


def routine_key(title):
    return " ".join((title or "").split()).casefold()


def open_matching(tasks, title, ids=()):
    """Every OPEN task that is this routine: the series (its id), an
    occurrence TickTick split off (repeatTaskId), or a copy with the same
    title (what "move this one to Tuesday" leaves behind, 2026-09-21)."""
    want, ids = routine_key(title), set(i for i in (ids or ()) if i)
    out = []
    for t in tasks or []:
        if not isinstance(t, dict) or t.get("status", 0) != 0 or t.get("deleted"):
            continue
        if (routine_key(t.get("title")) == want or t.get("id") in ids
                or (t.get("repeatTaskId") or "") in ids):
            out.append(t)
    return out


def upcoming(tasks, title, today, ids=()):
    """The NEXT occurrence of a routine: the earliest open matching task on
    or after today (its own zone); a same-day tie goes to the moved copy
    over the series. None when nothing is ahead."""
    best, best_key = None, None
    for t in open_matching(tasks, title, ids):
        d = task_date(t)
        if not d or d < today:
            continue
        key = (d, 1 if t.get("repeatFlag") else 0, str(t.get("startDate") or t.get("dueDate") or ""))
        if best is None or key < best_key:
            best, best_key = t, key
    return best


# ── the plan, folded into weeks ──────────────────────────────────────────────
@dataclass
class Meal:
    slot: str                   # "b" | "l" | "s" | "x"
    name: str
    uuid: str                   # UPPERCASE recipe id
    date: date                  # the planned (calendar) day
    web: str = ""               # the recipe's own web page (Mela ZLINK), or ""
    tid: str = ""               # the library task carrying this uuid, else ""
    pid: str = ""

    @property
    def glyph(self):
        return GLYPH.get(self.slot, SLOT_X[2])

    @property
    def url(self):
        return f"mela://recipe/{self.uuid}"


@dataclass
class Week:
    sunday: date                # the cook Sunday
    meals: list = field(default_factory=list)

    @property
    def label(self):
        return week_label(self.sunday)


def _fallback_tag_for(recipe, tag_map):
    """mela.meal_tag_for's rule when mela is not importable: exact key, or
    both stripped of a leading 'NN • ' and casefolded."""
    def plain(c):
        return re.sub(r"^\d+\s*[•·-]\s*", "", (c or "").strip()).casefold()
    tag_map = tag_map or {"02 • Breakfast": "🍳breakfast", "01 • Meal": "🍛lunch",
                          "03 • Snack": "🌮snack"}
    cats = list(getattr(recipe, "categories", None) or [])
    for key, tag in tag_map.items():
        if any(c == key or plain(c) == plain(key) for c in cats):
            return tag
    return None


def slot_for_recipe(recipe, tag_map=None):
    """"b" | "l" | "s" from the recipe's Mela category through the tag map
    (mela.meal_tag_for), "x" when it sits in none of the three - the slot
    comes from the RECIPE, never from the event's time of day."""
    if recipe is None:
        return SLOT_X[0]
    if _mela is not None:
        tag = _mela.meal_tag_for(recipe, tag_map)
    else:
        tag = _fallback_tag_for(recipe, tag_map)
    want = (tag or "").lower()
    return next((s[0] for s in SLOTS if s[1].lower() == want), SLOT_X[0])


def _uuid_of(p):
    return (getattr(p, "uuid", None) or "").strip().upper()


def _meal_sort_key(m):
    return (_SLOT_RANK.get(m.slot, len(_SLOT_RANK)), m.date, (m.name or "").casefold())


def _meal_from(p, by_id, tag_map, by_uuid):
    u = _uuid_of(p)
    r = (by_id or {}).get(u)
    e = (by_uuid or {}).get(u) or {}
    if r is not None:
        name = (getattr(r, "title", "") or getattr(p, "title", "") or "").strip()
        return Meal(slot=slot_for_recipe(r, tag_map), name=name or "Recipe", uuid=u,
                    date=p.date, web=(getattr(r, "link", "") or "").strip(),
                    tid=e.get("tid") or "", pid=e.get("pid") or "")
    # a planned uuid Mela no longer knows: still a meal, named after the
    # event, in the 🍽️ slot - never dropped
    return Meal(slot=SLOT_X[0], name=(getattr(p, "title", "") or "").strip() or "Recipe",
                uuid=u, date=p.date, web="", tid=e.get("tid") or "", pid=e.get("pid") or "")


def weeks_plan(planned, by_id, tag_map, entries, first_sunday, n_weeks):
    """[Week] for n_weeks cook Sundays from first_sunday, EVERY week present
    even when empty. `planned` = mela_cal.Planned-like rows (date, uuid,
    title); `by_id` = {UUID: mela.Recipe}; `entries` = library_entries()
    output, so tid/pid resolve to the library task. A meal belongs to the
    week of cook_week_of(its date); one row per recipe per week (Mela's
    Add to Calendar fired twice is still one meal, the earliest date
    kept); meals ordered b, l, s, x, then date, then name."""
    first_sunday = cook_week_of(first_sunday)
    n_weeks = max(0, int(n_weeks or 0))
    by_uuid = {}
    for e in entries or []:
        u = (e.get("uuid") or "").upper()
        if u and u not in by_uuid:
            by_uuid[u] = e
    buckets = {}
    for p in sorted(planned or [], key=lambda p: (p.date, getattr(p, "title", "") or "")):
        u = _uuid_of(p)
        if not u:
            continue
        sun = cook_week_of(p.date)
        seen = buckets.setdefault(sun, {})
        if u not in seen:
            seen[u] = _meal_from(p, by_id, tag_map, by_uuid)
    out = []
    for i in range(n_weeks):
        sun = first_sunday + timedelta(days=7 * i)
        meals = sorted(buckets.get(sun, {}).values(), key=_meal_sort_key)
        out.append(Week(sunday=sun, meals=meals))
    return out


def week_meals(planned, by_id, tag_map, entries, sunday):
    """The one Week cooked on `sunday` (see weeks_plan)."""
    return weeks_plan(planned, by_id, tag_map, entries, sunday, 1)[0]


def meals_on(planned, by_id, tag_map, entries, day):
    """The meals Mela has ON one calendar day - the batch a cook day makes
    (Vex 2026-09-21: the prep task moves, the meals sit on its day in Mela).
    One per recipe, slot order."""
    by_uuid = {}
    for e in entries or []:
        u = (e.get("uuid") or "").upper()
        if u and u not in by_uuid:
            by_uuid[u] = e
    seen = {}
    for p in sorted(planned or [], key=lambda p: (p.date, getattr(p, "title", "") or "")):
        if p.date != day:
            continue
        u = _uuid_of(p)
        if u and u not in seen:
            seen[u] = _meal_from(p, by_id, tag_map, by_uuid)
    return sorted(seen.values(), key=_meal_sort_key)


def last_cooked(planned, uuid, today):
    """Whole cook-weeks since this recipe was last planned on or before
    today (0 = this week's cooking, i.e. the same cook Sunday as today),
    None = never. A planned Sunday in the past IS the cooked history."""
    u = (uuid or "").strip().upper()
    if not u:
        return None
    best = None
    for p in planned or []:
        if _uuid_of(p) != u or p.date > today:
            continue
        if best is None or p.date > best:
            best = p.date
    if best is None:
        return None
    return (cook_week_of(today) - cook_week_of(best)).days // 7


def next_planned(planned, uuid, today):
    """The first day this recipe is planned AFTER today, else None (the
    day itself counts as last_cooked's "this week")."""
    u = (uuid or "").strip().upper()
    if not u:
        return None
    days = [p.date for p in planned or [] if _uuid_of(p) == u and p.date > today]
    return min(days) if days else None


def cooked_chip(weeks, tagged=False):
    """'never cooked' / 'cooked this week' / 'cooked 2 weeks ago' off the
    calendar; 'cooked before' when only the 👨‍🍳cooked tag says so (a
    recipe cooked before the calendar era, or one tagged by hand)."""
    if weeks is None:
        return "cooked before" if tagged else "never cooked"
    if weeks == 0:
        return "cooked this week"
    if weeks == 1:
        return "cooked last week"
    return f"cooked {weeks} weeks ago"


def lib_chip(planned, uuid, today, tagged=False, rating=None):
    """The library row's chip: 'never cooked' / 'cooked 2 weeks ago' (or
    'cooked before' on the tag alone), ' · next Sun 4 Oct' when the
    calendar has it coming, ' · ⭐️⭐️⭐️' when Vex rated it."""
    chip = cooked_chip(last_cooked(planned, uuid, today), tagged)
    nxt = next_planned(planned, uuid, today)
    chip += f" · next {nxt:%a %-d %b}" if nxt else ""
    return chip + (" · " + stars(rating) if stars(rating) else "")


def sort_for_lib(entries, planned, today):
    """Library order: never cooked first (no calendar past, no tag), then
    the tag-only ones, then least recently cooked, then by name."""
    def key(e):
        w = last_cooked(planned, e.get("uuid"), today)
        rank = (0 if not e.get("cooked") else 1) if w is None else 2
        return (rank, -(w or 0), (e.get("name") or "").lower())
    return sorted(entries, key=key)


# ── the sync verb ────────────────────────────────────────────────────────────
def sync_payload(back="ctx:meal"):
    """The b64-able spec behind xact:meal_sync."""
    return {"back": back}


def sync_text(day, n_meals, n_groceries, imported, filled, note_ok=True,
              dated=0, dates_left=0, rated=0, ratings_left=0):
    """The toast: '🔄 Mela · +2 recipes · 3 filled · cook Tue 22 Sep: 🍳 Hot
    Pockets · 2 grocery lists'. `day` is the cook day (the prep task's);
    `n_meals` is a count OR that day's meals (Meal objects, (slot, name)
    pairs or plain names) - names read better than a number. `rated` /
    `ratings_left` count Mela's own stars copied into unrated tasks (the
    sync's rating pass, 2026-09-21), worded like dated / dates_left."""
    parts = ["🔄 Mela"]
    if imported:
        parts.append(f"+{imported} recipe{'s' if imported != 1 else ''}")
    if filled:
        parts.append(f"{filled} filled")
    if not imported and not filled:
        parts.append("nothing new")
    if isinstance(n_meals, int):
        what = (f"{n_meals} meal{'s' if n_meals != 1 else ''}" if n_meals
                else "nothing planned in Mela")
    else:
        names = []
        for m in n_meals or []:
            if isinstance(m, Meal):
                names.append(f"{m.glyph} {m.name}")
            elif isinstance(m, (tuple, list)) and len(m) >= 2:
                names.append(f"{GLYPH.get(m[0], SLOT_X[2])} {m[1]}")
            else:
                names.append(str(m))
        what = " · ".join(names) if names else "nothing planned in Mela"
    parts.append(f"cook {day:%a %-d %b}: {what}")
    parts.append(f"{n_groceries} grocery list{'s' if n_groceries != 1 else ''}")
    if dated:                      # library tasks re-dated off the calendar
        parts.append(f"{dated} recipe{'s' if dated != 1 else ''} dated")
    if dates_left:                 # the 100-a-minute limit stopped the pass
        parts.append(f"{dates_left} date{'s' if dates_left != 1 else ''} left · run again")
    if rated:                      # Mela's stars adopted by tasks that had none
        parts.append(f"{rated} rating{'s' if rated != 1 else ''} from Mela")
    if ratings_left:               # the same limit stopped that pass
        parts.append(f"{ratings_left} rating{'s' if ratings_left != 1 else ''} left · run again")
    txt = " · ".join(parts)
    return txt if note_ok else txt + " · note not written"
