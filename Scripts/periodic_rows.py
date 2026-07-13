#!/usr/bin/env python3
"""periodic_rows.py - the 💫 pn search scope.

Imported by everything_search.py AFTER its bootstrap, so src/ is already on
sys.path. Renders: the idle action rows and the submodes - `+` entry (with
the 😢-😁 mood faces), `$` income, `goal` / `day` task pickers, `today` /
`tmrw` schedule pickers (two-screen: pick → add-or-time). All state rides
the query - no handshake files; ⏎ always fires an xact: arg (the only shape
search-⏎ forwards to a script). Subtitles stay plain: no syntax in
subtitles, ever - autocomplete rows teach by doing.

Chord rule: the search SF has live mod edges (⌘ Actions chain, ⇧, ⌥,
⌥⇧ X1 router, ⌥⌘ copy, ⌃⇧ modOpen) - a row with NO mods entry fires its
DEFAULT arg down every one of them. Every row here carries a full mods dict:
dead chords everywhere, ⌃⇧ = sticky on the six open rows. ⌘ physically
routes to the Actions chain and can never reach dispatch.
"""
import base64
import json
import re
import time
from datetime import date, timedelta

import alfred
import areas
import cache as cache_store
import fuzzy as fuzz
import periodic_model as pm
from script_base import run_path


def _b64(d):
    return base64.b64encode(json.dumps(d).encode("utf-8")).decode("ascii")


_DEAD = {"valid": False, "subtitle": ""}


def _mods(sticky_spec=None):
    # alt+cmd included: the search SF has a wired ⌥⌘ (copy-link) edge - without
    # an explicit entry the row's DEFAULT xact: arg would ride it into pbcopy.
    # ⌃ is NOT dead: the wired ⌃ edge is the universal 🔙 back-to-main-menu
    # (every other search row gets it via _output_backstamped).
    m = {k: dict(_DEAD)
         for k in ("cmd", "shift", "alt", "alt+shift", "alt+cmd")}
    m["ctrl"] = {"valid": True, "arg": "", "subtitle": "🔙 Main menu"}
    if sticky_spec:
        m["ctrl+shift"] = {"valid": True,
                           "arg": f"xact:pn_sticky:{sticky_spec}",
                           "subtitle": "📌 Open as sticky"}
    else:
        m["ctrl+shift"] = dict(_DEAD)
    return m


_OPEN_ROWS = [
    ("daily",     "💫", "Today"),
    ("yesterday", "◀️", "Yesterday"),
    ("weekly",    "📆", "Week"),
    ("monthly",   "🗓", "Month"),
    ("quarterly", "🧭", "Quarter"),
    ("yearly",    "📅", "Year"),
]


def _period_of(spec, today):
    if spec == "yesterday":
        return pm.period_for("daily", today - timedelta(days=1))
    return pm.period_for("daily" if spec == "daily" else spec, today)


def _goalseq_active():
    """The weekly journal's three-things sequence (xact writes the file)."""
    try:
        with open(run_path("tickal_pn_goalseq.json")) as f:
            d = json.load(f)
        return d if (time.time() - d.get("ts", 0) < 600
                     and d.get("remaining", 0) > 0) else None
    except Exception:
        return None


def idle_rows(frag):
    today = date.today()
    items = []
    for spec, emoji, label in _OPEN_ROWS:
        p = _period_of(spec, today)
        it = alfred.item(
            uid=f"pn-open-{spec}",
            title=f"{emoji} {label} · {pm.title(p)}",
            subtitle="⏎↗️ Open  ⌃⇧📌 Sticky",
            arg=f"xact:pn_open:{spec}", valid=True,
            mods=_mods(spec))
        it["_kw"] = spec if spec != "daily" else "daily note"   # 'pn daily' hits
        items.append(it)
    extras = [
        ("pn-entry",     "➕ Entry",            "Log a win, nag, thought, link",
         None, "pn + "),
        ("pn-income",    "💰 Income",           "Log money you made",
         None, "pn $ "),
        ("pn-daygoal",   "☀️ Day goal",         "Pick the one thing for today",
         None, "pn day "),
        ("pn-today",     "☀️ Add to today",     "Pick any task, schedule it today",
         None, "pn today "),
        ("pn-tmrw",      "🌙 Add to tomorrow",  "Pick any task, schedule it tomorrow",
         None, "pn tmrw "),
        ("pn-jm",        "🌅 Morning journal",  "Answer short questions",
         "xact:pn_journal:morning", None),
        ("pn-je",        "🌙 Evening journal",  "Answer short questions",
         "xact:pn_journal:evening", None),
        ("pn-jw",        "📔 Weekly journal",   "Review the week, set next week",
         "xact:pn_journal:weekly", None),
        ("pn-goal",      "🎯 Weekly goal",      "Pick a task",
         None, "pn goal "),
        ("pn-highlight", "🗓️ Week highlight",   "One thing that stands out",
         "xact:pn_highlight", None),
        ("pn-refresh",   "🔄 Refresh today",    "Complete ticked, rebuild numbers",
         "xact:pn_refresh", None),
    ]
    for uid, title, sub, arg, autoc in extras:
        it = alfred.item(uid=uid, title=title, subtitle=sub,
                         arg=arg or "", valid=bool(arg), mods=_mods())
        if autoc:
            it["autocomplete"] = autoc
        items.append(it)
    if frag:
        items = fuzz.filter_and_score(
            frag, items,
            key_fn=lambda x: x["title"] + " " + x.get("_kw", ""))
        if not items:
            items = [alfred.item(title=f'Nothing matching "{frag}"',
                                 valid=False, mods=_mods())]
    for it in items:
        it.pop("_kw", None)               # hidden match keywords, not payload
    return items


_KIND_LEGEND = [
    ("w", "🏆 Win"), ("n", "👎 Nag"), ("t", "💭 Thought"),
    ("k", "☑️ Task"), ("l", "🔗 Link"), ("m", "😊 Mood"),
]
_KINDS = {"w": "win", "n": "nag", "t": "thought", "k": "task",
          "l": "link", "m": "mood"}
_GLYPH = {"win": "🏆", "nag": "👎", "thought": "💭", "task": "☑️",
          "link": "🔗", "mood": "😊"}
_LEGEND_SUBS = {"w": "Something went well", "n": "Something nagged you",
                "t": "Plain text is a thought too", "k": "Makes a real task",
                "l": "Empty = clipboard", "m": "How you feel, 5 faces"}
_MOOD_FACES = [(5, "😁", "Great"), (4, "🙂", "Good"), (3, "😐", "OK"),
               (2, "😞", "Meh"), (1, "😢", "Rough")]


def _mood_rows():
    rows = []
    for score, face, label in _MOOD_FACES:
        rows.append(alfred.item(
            uid=f"pn-mood-{score}",
            title=f"{face} {label}",
            subtitle="⏎ then an optional note",
            arg=f"xact:pn_mood:{score}", valid=True, mods=_mods()))
    return rows


def entry_rows(rest):
    if not rest:
        rows = []
        for letter, label in _KIND_LEGEND:
            it = alfred.item(title=label, subtitle=_LEGEND_SUBS[letter],
                             arg="", valid=False, mods=_mods())
            it["autocomplete"] = f"pn + {letter} "
            rows.append(it)
        return rows
    kind, text = "thought", rest.strip()
    head, _, tail = text.partition(" ")
    if head.lower() == "m" and not tail:
        # mood is a picker: faces first, note dialog after
        return _mood_rows()
    if head.lower() in _KINDS and not tail and head.lower() != "l":
        # bare kind letter (fresh from the legend) → prompt, never a valid
        # "💭 Thought - w" row an accidental ⏎ would log
        return [alfred.item(title=f"Type the {_KINDS[head.lower()]} text…",
                            valid=False, mods=_mods())]
    if head.lower() in _KINDS and (tail or head.lower() == "l"):
        kind, text = _KINDS[head.lower()], tail.strip()
    if kind == "mood":
        m = re.match(r"^([1-5])(?!\d)\s*·?\s*(.*)$", text)
        if not m:
            return _mood_rows()           # junk after m → back to the faces
        note = m.group(2).strip()         # normalize to the verb's grammar
        text = m.group(1) + (f" · {note}" if note else "")
    if not text and kind != "link":
        return [alfred.item(title=f"Type the {kind} text…",
                            valid=False, mods=_mods())]
    shown = text or "clipboard contents"
    return [alfred.item(
        title=f"{_GLYPH[kind]} {kind.capitalize()} · {shown[:60]}",
        subtitle="⏎ Log to today's note",
        arg=f"xact:pn_entry:{_b64({'kind': kind, 'text': text})}",
        valid=True, mods=_mods())]


def income_rows(rest):
    if not rest:
        return [alfred.item(title="💰 Log income",
                            subtitle="Amount first, then what for",
                            valid=False, mods=_mods())]
    head, _, tail = rest.strip().partition(" ")
    amt = pm.parse_amount(head)
    if amt is None:
        return [alfred.item(title="💰 Amount first",
                            subtitle="Then what it was for",
                            valid=False, mods=_mods())]
    label = tail.strip()
    shown = pm.fmt_amount(amt) + (f" · {label}" if label else "")
    return [alfred.item(
        title=f"💰 {shown}",
        subtitle="⏎ Log to today's 💰 Money",
        arg=f"xact:pn_income:{_b64({'amount': amt, 'label': label})}",
        valid=True, mods=_mods())]


def _task_pool(include_notes=False):
    pool = [t for t in (cache_store.get("all_tasks") or [])
            if t.get("status", 0) == 0
            and (include_notes or t.get("kind") != "NOTE")
            and (t.get("projectId") or t.get("_projectId")) != areas.PERIODIC_LIST_ID]
    return pool


def _picker_rows(frag, pool, row_fn, empty_hint):
    if frag:
        pool = fuzz.filter_and_score(frag, pool,
                                     key_fn=lambda t: t.get("title") or "")
    items = [row_fn(t) for t in pool[:40]]
    if not items:
        items = [alfred.item(title=empty_hint, valid=False, mods=_mods())]
    return items


def goal_rows(frag):
    seq = _goalseq_active()
    sub = ("⏎ Goal for NEXT week" if seq else "⏎ Set as this week's goal")

    def row(t):
        pid = t.get("projectId") or t.get("_projectId", "")
        return alfred.item(
            uid=f"pn-goal-{t['id']}",
            title=f"📋 {(t.get('title') or 'Untitled')[:60]}",
            subtitle=sub,
            arg=f"xact:pn_goal:{pid}:{t['id']}",
            valid=True, mods=_mods())
    items = _picker_rows(frag, _task_pool(), row,
                         "Type to pick a goal task…")
    if frag.strip():
        items.append(alfred.item(
            title=f'➕ Goal: "{frag.strip()[:50]}"',
            subtitle="Plain-text goal",
            arg=f"xact:pn_goal_text:{_b64({'text': frag.strip()})}",
            valid=True, mods=_mods()))
    return items


def day_goal_rows(frag):
    def row(t):
        pid = t.get("projectId") or t.get("_projectId", "")
        return alfred.item(
            uid=f"pn-dg-{t['id']}",
            title=f"☀️ {(t.get('title') or 'Untitled')[:60]}",
            subtitle="⏎ The one thing · pinned + scheduled today",
            arg=f"xact:pn_day_goal:{pid}:{t['id']}",
            valid=True, mods=_mods())
    items = _picker_rows(frag, _task_pool(include_notes=True), row,
                         "Type to pick today's one thing…")
    if frag.strip():
        items.append(alfred.item(
            title=f'➕ New goal task: "{frag.strip()[:50]}"',
            subtitle="Makes a real task due today, pins it",
            arg=f"xact:pn_day_goal_text:{_b64({'text': frag.strip()})}",
            valid=True, mods=_mods()))
    return items


_TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?$")


def sched_rows(rest, when):
    """Two-screen ☀️/🌙 Add-to picker. Screen 1: pick a task (⏎ advances).
    Screen 2 (query '…!pid:tid [time]'): Add now, or type a time."""
    label = "today" if when == "today" else "tomorrow"
    emoji = "☀️" if when == "today" else "🌙"
    key = "today" if when == "today" else "tmrw"
    if rest.startswith("!"):
        spec, _, frag = rest[1:].partition(" ")
        pid, _, tid = spec.partition(":")
        if not pid or not tid:            # hand-typed '!' junk - no valid row
            return [alfred.item(title="Type to pick a task…",
                                valid=False, mods=_mods())]
        title = next((t.get("title") for t in (cache_store.get("all_tasks") or [])
                      if t.get("id") == tid), "Task") or "Task"
        rows = [alfred.item(
            uid="pn-sched-add",
            title=f"{emoji} {title[:50]} → {label}",
            subtitle="⏎ Day only, no time",
            arg=f"xact:pn_sched:{when}|{pid}|{tid}",
            valid=True, mods=_mods())]
        frag = frag.strip()
        m = _TIME_RE.match(frag)
        if frag and m and int(m.group(1)) <= 23 and int(m.group(2) or 0) <= 59:
            hhmm = f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
            rows.append(alfred.item(
                uid="pn-sched-time",
                title=f"⏰ {title[:46]} → {label} {hhmm}",
                subtitle="⏎ With this time",
                arg=f"xact:pn_sched:{when}|{pid}|{tid}|{hhmm}",
                valid=True, mods=_mods()))
        else:
            rows.append(alfred.item(
                title="⏰ At a time",
                subtitle="Keep typing · like 14:30",
                valid=False, mods=_mods()))
        return rows

    def row(t):
        pid = t.get("projectId") or t.get("_projectId", "")
        it = alfred.item(
            uid=f"pn-sched-{t['id']}",
            title=f"{emoji} {(t.get('title') or 'Untitled')[:60]}",
            subtitle=f"⏎ Schedule {label}",
            arg="", valid=False, mods=_mods())
        it["autocomplete"] = f"pn {key}!{pid}:{t['id']} "
        return it
    return _picker_rows(frag=rest, pool=_task_pool(include_notes=True),
                        row_fn=row, empty_hint="Type to pick a task…")


def _after(q, prefix):
    """rest after a WORD prefix ('day', 'day frag', 'today!pid:tid …') |
    None. The boundary check keeps 'daily' out of the 'day' submode."""
    ql = q.lower()
    if ql == prefix:
        return ""
    if ql.startswith(prefix + " "):
        return q[len(prefix) + 1:].lstrip()
    if ql.startswith(prefix + "!"):
        return q[len(prefix):]            # screen 2 keeps its '!' marker
    return None


def rows(query):
    """Entry point for the pn scope. query = bar text after 'pn '."""
    if not areas.periodic_configured():
        row = areas.setup_row("Periodic notes", "47-periodic.md")
        row["mods"] = _mods()
        return [row]
    q = (query or "").strip()
    if q.startswith("+"):
        return entry_rows(q[1:].lstrip())
    if q.startswith("$"):
        return income_rows(q[1:].lstrip())
    for prefix, when in (("today", "today"), ("tmrw", "tomorrow"),
                         ("tomorrow", "tomorrow")):
        rest = _after(q, prefix)
        if rest is not None:
            return sched_rows(rest, when)
    rest = _after(q, "day")
    if rest is not None:
        return day_goal_rows(rest)
    rest = _after(q, "goal")
    if rest is not None:
        return goal_rows(rest)
    return idle_rows(q)
