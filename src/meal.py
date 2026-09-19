#!/usr/bin/env python3
"""meal.py - the 🥘 Meal Prep model (PURE: stdlib only; the ledger helpers
take a path and are the only I/O).

Vex cooks THREE meals every Sunday evening for the week ahead - one
breakfast, one lunch, one snack, seven portions each - and keeps the recipe
library in Mela. In TickTick the library is the 🍳Meal Prep list: one task
per recipe, title `[Name](mela://recipe/<UUID>)`, tagged 🍳breakfast /
🍛lunch / 🌮snack. The plan for a week is three POINTER tasks minted under
the repeating 🥘 Meal Prep routine (`🍳 [Name](mela://…)` …) and three
🛒 grocery checklists in the library list; the library entries themselves
never move (HANDOFF_MEAL.md). This module holds the grammar of those titles,
the slot logic, the week arithmetic and the cooked-history ledger; nothing
here talks to TickTick or Mela.

The Mela UUID is the join key everywhere: Mela kept Crouton's ids on import,
the TickTick titles carry them, and `mela://recipe/<UUID>` opens the recipe
on the Mac (verified 2026-09-19). Titles saved by the TickTick app may be
backslash-escaped, so every reader goes through `parse_title`.
"""
import json
import os
import random
import re
from datetime import date, datetime, timedelta, timezone

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

PORTIONS = 7
GROCERY_TAG = "🛒groceries"
GROCERY_GLYPH = "🛒"
# key, TickTick tag, glyph, label - in the order a week is planned
SLOTS = (("b", "🍳breakfast", "🍳", "Breakfast"),
         ("l", "🍛lunch", "🍛", "Lunch"),
         ("s", "🌮snack", "🌮", "Snack"))
SLOT_KEYS = tuple(s[0] for s in SLOTS)
# Weekly notes minted before this day never had the 🥘 bullet: a missing
# bullet there is seeded once, a missing bullet later is Vex's deletion.
NOTE_SINCE = date(2026, 9, 20)
SURPRISE_WEEKS = 4                      # 🎲 avoids anything cooked this recently

LINK_RE = re.compile(r"mela://recipe/([0-9A-Fa-f-]{36})")
_TITLE_RE = re.compile(r"\[(?P<name>[^\]]*)\]\(mela://recipe/(?P<id>[0-9A-Fa-f-]{36})\)")
_GLYPHS = {s[2]: s[0] for s in SLOTS}


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
    """The SLOTS tuple for a key ('b' | 'l' | 's'), else None."""
    return next((s for s in SLOTS if s[0] == key), None)


def slot_of_tags(tags):
    """Which slot a library entry belongs to, from its tags (SLOTS order
    decides when an entry somehow carries two). None when none."""
    have = {str(t).lower() for t in (tags or [])}
    for s in SLOTS:
        if s[1].lower() in have:
            return s[0]
    return None


def pointer_title(key, name, uuid):
    s = slot(key)
    return f"{s[2]} {md_link(name, uuid)}"


def is_pointer(title):
    """A pointer WE minted: a slot glyph, a space, then the Mela link."""
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
    slot ({key: task}). Archived occurrences (repeatTaskId) never count."""
    out = {}
    for t in tasks or []:
        if not isinstance(t, dict) or t.get("status", 0) != 0:
            continue
        if t.get("parentId") != routine_id or t.get("repeatTaskId"):
            continue
        if not is_pointer(t.get("title") or ""):
            continue
        k = pointer_slot(t.get("title"))
        if k and k not in out:
            out[k] = t
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


# ── the ledger (cooked history) ──────────────────────────────────────────────
def load_ledger(path):
    """{"weeks": [...]} - missing or corrupt reads as empty."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("weeks"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"weeks": []}


def save_ledger(path, data):
    """Atomic, 0600, like config.save - never a half-written history."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def ledger_add(data, sunday, picks, pointers=(), groceries=(), when=None):
    """Record a committed week (replacing an earlier entry for the same
    Sunday: a re-plan is the plan). picks = {key: {tid, uuid, name}}."""
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    entry = {"sunday": sunday.isoformat(), "at": stamp,
             "pointers": list(pointers), "groceries": list(groceries)}
    for k in SLOT_KEYS:
        p = picks.get(k) or {}
        entry[k] = {"tid": p.get("tid", ""), "uuid": p.get("uuid", ""),
                    "name": p.get("name", "")}
    weeks = [w for w in data.get("weeks", []) if w.get("sunday") != entry["sunday"]]
    weeks.append(entry)
    weeks.sort(key=lambda w: w.get("sunday", ""))
    data["weeks"] = weeks
    return entry


def ledger_week(data, sunday):
    iso = sunday.isoformat()
    return next((w for w in data.get("weeks", []) if w.get("sunday") == iso), None)


def last_cooked(data, uuid, today):
    """Whole weeks since this recipe was last planned for a Sunday on or
    before today (0 = this week's), None = never."""
    if not uuid:
        return None
    u = uuid.upper()
    best = None
    for w in data.get("weeks", []):
        try:
            sun = date.fromisoformat(w.get("sunday", ""))
        except (ValueError, TypeError):
            continue
        if sun > today:
            continue
        if any((w.get(k) or {}).get("uuid", "").upper() == u for k in SLOT_KEYS):
            if best is None or sun > best:
                best = sun
    return None if best is None else (today - best).days // 7


def cooked_chip(weeks):
    if weeks is None:
        return "never cooked"
    if weeks == 0:
        return "cooked this week"
    if weeks == 1:
        return "cooked last week"
    return f"cooked {weeks} weeks ago"


def sort_for_pick(entries, data, today):
    """Least recently cooked first (never first), then by name."""
    def key(e):
        w = last_cooked(data, e.get("uuid"), today)
        return (0 if w is None else 1, -(w or 0), e.get("name", "").lower())
    return sorted(entries, key=key)


def surprise_pool(entries, data, today, weeks=SURPRISE_WEEKS):
    pool = [e for e in entries
            if (lambda w: w is None or w >= weeks)(last_cooked(data, e.get("uuid"), today))]
    return pool or list(entries)


def surprise(entries, data, today, weeks=SURPRISE_WEEKS, rng=None):
    pool = surprise_pool(entries, data, today, weeks)
    if not pool:
        return None
    return (rng or random).choice(pool)


# ── the picker chain's ctx ───────────────────────────────────────────────────
def slots_from_ids(ids):
    """['b tid' | '', 'l tid' | '', 's tid' | ''] from a ctx's ids; '-' and
    missing both mean 'not picked yet'."""
    ids = list(ids or [])[:3]
    ids += [""] * (3 - len(ids))
    return [("" if i in ("", "-") else i) for i in ids]


def ctx_for(slots):
    """The mealplan ctx that carries these picks: trailing empties are
    dropped, interior ones ride as '-' so positions hold."""
    parts = [s or "-" for s in list(slots)[:3]]
    while parts and parts[-1] == "-":
        parts.pop()
    return "ctx:mealplan" + ("".join(":" + p for p in parts) if parts else "")


def next_slot(slots):
    """Index of the first unpicked slot, None when all three are picked."""
    return next((i for i, s in enumerate(slots) if not s), None)


def commit_payload(slots, sunday=None, back="ctx:meal"):
    b, l, s = (list(slots) + ["", "", ""])[:3]
    return {"b": b, "l": l, "s": s, "sunday": sunday.isoformat() if sunday else None,
            "back": back}


def outcome_text(sunday, n_meals, n_groceries, note_ok=True):
    txt = f"🥘 {week_label(sunday)} planned · {n_meals} meals · {n_groceries} grocery lists"
    return txt if note_ok else txt + " · note not written"
