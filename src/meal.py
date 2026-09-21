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
"""
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

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


# ── the library as the screens see it ────────────────────────────────────────
def library_entries(tasks, list_id):
    """[{tid, pid, title, name, uuid, slot, tags, content, kind}] for the
    open library entries of list_id among `tasks` (a cache pool or a
    project_data task list). Pointers, grocery lists and untagged strays
    are left out; `slot` is None for an entry without a meal tag."""
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
        out.append({"tid": t.get("id"), "pid": pid, "title": title, "name": name,
                    "uuid": uuid, "slot": slot_of_tags(tags), "tags": tags,
                    "content": t.get("content") or "", "kind": t.get("kind") or ""})
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


def api_day(d):
    """A bare ISO date - api.create_task reads it as all-day."""
    return d.isoformat()


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


def cooked_chip(weeks):
    if weeks is None:
        return "never cooked"
    if weeks == 0:
        return "cooked this week"
    if weeks == 1:
        return "cooked last week"
    return f"cooked {weeks} weeks ago"


def lib_chip(planned, uuid, today):
    """The library row's chip: 'never cooked' / 'cooked 2 weeks ago', with
    ' · next Sun 4 Oct' when the calendar has it coming."""
    chip = cooked_chip(last_cooked(planned, uuid, today))
    nxt = next_planned(planned, uuid, today)
    return chip + (f" · next {nxt:%a %-d %b}" if nxt else "")


def sort_for_lib(entries, planned, today):
    """Library order: never cooked first, then least recently cooked, then
    by name."""
    def key(e):
        w = last_cooked(planned, e.get("uuid"), today)
        return (0 if w is None else 1, -(w or 0), (e.get("name") or "").lower())
    return sorted(entries, key=key)


# ── the sync verb ────────────────────────────────────────────────────────────
def sync_payload(back="ctx:meal"):
    """The b64-able spec behind xact:meal_sync."""
    return {"back": back}


def sync_text(sunday, n_meals, n_groceries, imported, filled, note_ok=True,
              dated=0, dates_left=0):
    """The toast: '🔄 Mela · +2 recipes · 3 filled · Week of 28 Sep: 🍳 Hot
    Pockets · 2 grocery lists'. `n_meals` is a count OR the week's meals
    (Meal objects, (slot, name) pairs or plain names) - names read better
    than a number when the writer has them."""
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
    parts.append(f"{week_label(sunday)}: {what}")
    parts.append(f"{n_groceries} grocery list{'s' if n_groceries != 1 else ''}")
    if dated:                      # library tasks re-dated off the calendar
        parts.append(f"{dated} recipe{'s' if dated != 1 else ''} dated")
    if dates_left:                 # the 100-a-minute limit stopped the pass
        parts.append(f"{dates_left} date{'s' if dates_left != 1 else ''} left · run again")
    txt = " · ".join(parts)
    return txt if note_ok else txt + " · note not written"
