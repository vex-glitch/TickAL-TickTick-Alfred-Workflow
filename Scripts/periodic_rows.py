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
from display import pick_title, pick_where
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
        # ⌥ = every note of this tier, newest first (Vex 2026-09-12: "I should
        # be able to enter a list of those notes ... so I can actually open any
        # note, not just this week's"). The search SF's ⌥ edge enters the
        # Browse loop, so the ctx rides as a VARIABLE with an EMPTY arg -
        # iron rule 8, nothing lands in the bar.
        m["alt"] = {"valid": True, "arg": "", "subtitle": "📚 All of them",
                    "variables": {"browse_ctx": f"ctx:pnlist:{sticky_spec}"}}
    else:
        m["ctrl+shift"] = dict(_DEAD)
    return m


# The tiers, in Vex's order and emoji (2026-09-12). Yesterday lost its own
# row: ⌥ on Daily opens every daily note, newest first, so it is one row down
# there instead of a permanent line on the idle screen.
_OPEN_ROWS = [
    ("daily",     "☀️", "Daily"),
    ("weekly",    "♻️", "Weekly"),
    ("monthly",   "🗓️", "Monthly"),
    ("quarterly", "🌓", "Quarterly"),
    ("yearly",    "🎉", "Yearly"),
]

# extra words a tier row should answer to when the scope is filtered
_OPEN_KW = {"daily": "today note day",
            "weekly": "week", "monthly": "month",
            "quarterly": "quarter", "yearly": "year"}


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
            subtitle="⏎↗️ Open  ⌥📚 All  ⌃⇧📌 Sticky",
            arg=f"xact:pn_open:{spec}", valid=True,
            mods=_mods(spec))
        it["_kw"] = f"{spec} {_OPEN_KW.get(spec, '')}"
        items.append(it)
    # Vex's order (2026-09-12). The three families are ONE row each - goals,
    # journals and the schedule-it verbs each open their own little screen
    # instead of spending five lines on the idle one.
    # Everything you WRITE into a note lives behind ➕ Entry (Vex 2026-09-12:
    # ➕ Add was the entry list's ☑️ Task by another road, 💰 Income and
    # 😊 Mood are journal answers now, and ⭐️ Highlight belongs with the rest
    # of the writing verbs). What stays out here is navigation and the refresh.
    extras = [
        ("pn-entry",     "➕ Entry",         "Write into today's note",
         None, "pn + "),
        ("pn-goals",     "🏆 Goals",         "The day goal and the week goal",
         None, "pn goals "),
        ("pn-journals",  "📓 Journals",      "Morning, evening, weekly",
         None, "pn journals "),
        ("pn-refresh",   "♻️ Refresh Today", "Complete ticked, rebuild numbers",
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


# 😊 Mood and 💰 Income are gone from here: both are evening/morning journal
# ANSWERS, and a second door to the same answer is a second place to look
# (Vex 2026-09-12). ⭐️ Highlight moved IN, because it writes too.
_KIND_LEGEND = [
    ("w", "🟢 Win"), ("n", "🔴 Nag"), ("t", "💭 Thought"),
    ("r", "❗️ Reminder"), ("l", "🔗 Link"), ("k", "☑️ Task"),
    ("h", "⭐️ Highlight"),
]
_KINDS = {"w": "win", "n": "nag", "t": "thought", "r": "reminder",
          "l": "link"}
_GLYPH = {"win": "🟢", "nag": "🔴", "thought": "💭", "reminder": "❗️",
          "link": "🔗"}
_LEGEND_SUBS = {"w": "Something went well", "n": "Something nagged you",
                "t": "Plain text is a thought too",
                "r": "Something not to forget",
                "l": "Clipboard is the link, you name it",
                "k": "Put a task on today or tomorrow",
                "h": "The one thing this week is remembered for"}


def entry_rows(rest):
    if not rest:
        rows = []
        for letter, label in _KIND_LEGEND:
            it = alfred.item(uid=f"pn-kind-{letter}",
                             title=label, subtitle=_LEGEND_SUBS[letter],
                             arg="", valid=False, mods=_mods())
            it["autocomplete"] = f"pn + {letter} "
            rows.append(it)
        return rows
    head, _, tail = rest.strip().partition(" ")
    letter = head.lower()
    if letter == "k":                     # ☑️ Task owns the whole add screen
        return task_rows(tail.strip())
    if letter == "h":
        return highlight_rows(tail.strip())
    kind, text = "thought", rest.strip()
    if letter in _KINDS and not tail and letter != "l":
        # bare kind letter (fresh from the legend) → prompt, never a valid
        # "💭 Thought - w" row an accidental ⏎ would log
        return [alfred.item(title=f"Type the {_KINDS[letter]} text…",
                            valid=False, mods=_mods())]
    if letter in _KINDS and (tail or letter == "l"):
        kind, text = _KINDS[letter], tail.strip()
    if not text and kind != "link":
        return [alfred.item(title=f"Type the {kind} text…",
                            valid=False, mods=_mods())]
    shown = text or "the copied link"
    sub = ("⏎ Log it as [%s](clipboard)" % (text[:28] or "the link name")
           if kind == "link" else "⏎ Log to today's note")
    return [alfred.item(
        title=f"{_GLYPH[kind]} {kind.capitalize()} · {shown[:60]}",
        subtitle=sub,
        arg=f"xact:pn_entry:{_b64({'kind': kind, 'text': text})}",
        valid=True, mods=_mods())]


def highlight_rows(frag):
    frag = (frag or "").strip()
    if not frag:
        return [alfred.item(title="Type the highlight…",
                            subtitle="What this week is remembered for",
                            valid=False, mods=_mods())]
    return [alfred.item(
        uid="pn-hl",
        title=f"⭐️ {frag[:60]}",
        subtitle="⏎ Save to this week's note",
        arg=f"xact:pn_highlight:{_b64({'text': frag})}",
        valid=True, mods=_mods())]


def income_rows(rest):
    """💰 stopped being a list row (Vex 2026-09-12: "I will only answer the
    question in the journal"). The caller ET still fires `pn $ `, so this
    screen points at the one place the number lives now instead of dead-ending.
    """
    return [alfred.item(
        uid="pn-money-journal",
        title="💰 Money is an evening journal answer",
        subtitle="⏎ Open the evening journal",
        arg="xact:pn_journal:evening", valid=True, mods=_mods())]


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
            title="📋 " + pick_title(t),
            subtitle=pick_where(t) + "  |  " + sub,
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
            title="☀️ " + pick_title(t),
            subtitle=pick_where(t) + "  |  ⏎ The one thing · scheduled today",
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


def task_rows(rest):
    """☑️ Task - the ONE add screen. ➕ Add in the main list and the entry
    list's ☑️ Task were two roads to the same intent (Vex 2026-09-12), so this
    screen does both jobs: pick a task you already have, or name one you do
    not. Screen 2 ("!pid:tid [time]") picks the day, and the time if you type
    one."""
    rest = rest or ""
    if rest.startswith("!"):
        spec, _, frag = rest[1:].partition(" ")
        pid, _, tid = spec.partition(":")
        if not pid or not tid:            # hand-typed '!' junk - no valid row
            return [alfred.item(title="Type to pick a task…",
                                valid=False, mods=_mods())]
        title = next((t.get("title") for t in (cache_store.get("all_tasks") or [])
                      if t.get("id") == tid), "Task") or "Task"
        frag = frag.strip()
        m = _TIME_RE.match(frag)
        hhmm = (f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
                if frag and m and int(m.group(1)) <= 23
                and int(m.group(2) or 0) <= 59 else None)
        rows = []
        for when, emoji, label in (("today", "☀️", "today"),
                                   ("tomorrow", "🌙", "tomorrow")):
            rows.append(alfred.item(
                uid=f"pn-task-{when}",
                title=f"{emoji} {title[:44]} → {label}"
                      + (f" {hhmm}" if hhmm else ""),
                subtitle="⏎ With this time" if hhmm else "⏎ Day only, no time",
                arg=f"xact:pn_sched:{when}|{pid}|{tid}"
                    + (f"|{hhmm}" if hhmm else ""),
                valid=True, mods=_mods()))
        if not hhmm:
            rows.append(alfred.item(uid="pn-task-time", title="⏰ At a time",
                                    subtitle="Keep typing · like 14:30",
                                    valid=False, mods=_mods()))
        return rows

    def row(t):
        pid = t.get("projectId") or t.get("_projectId", "")
        it = alfred.item(
            uid=f"pn-task-{t['id']}",
            title="☑️ " + pick_title(t),
            subtitle=pick_where(t) + "  |  ⏎ Pick a day",
            arg="", valid=False, mods=_mods())
        it["autocomplete"] = f"pn + k !{pid}:{t['id']} "
        return it
    frag = rest.strip()
    pool = _task_pool(include_notes=True)
    if frag:
        pool = fuzz.filter_and_score(frag, pool, key_fn=lambda t: t.get("title") or "")
    items = [row(t) for t in pool[:40]]
    if frag:
        items.append(alfred.item(
            uid="pn-task-new",
            title=f'➕ New task: "{frag[:50]}"',
            subtitle="Makes a real task, on today",
            arg=f"xact:pn_entry:{_b64({'kind': 'task', 'text': frag})}",
            valid=True, mods=_mods()))
    elif not items:
        items = [alfred.item(title="Type to pick or name a task…",
                             valid=False, mods=_mods())]
    return items


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
            title=f"{emoji} " + pick_title(t),
            subtitle=pick_where(t) + f"  |  ⏎ Schedule {label}",
            arg="", valid=False, mods=_mods())
        it["autocomplete"] = f"pn {key}!{pid}:{t['id']} "
        return it
    return _picker_rows(frag=rest, pool=_task_pool(include_notes=True),
                        row_fn=row, empty_hint="Type to pick a task…")


# ── the three family screens (Vex 2026-09-12) ───────────────────────────────
# Each is a plain row list plus a way back; the members kept their own verbs,
# so nothing downstream changed - only where the row is reached from.
_FAMILIES = {
    "goals": ("🏆 Goals", [
        ("pn-goal-daily",     "☀️ Daily",     "The one thing for today",
         None, "pn goals daily "),
        ("pn-goal-weekly",    "♻️ Weekly",    "Goals for this week",
         None, "pn goals weekly "),
        ("pn-goal-monthly",   "🗓️ Monthly",   "Goals for this month",
         None, "pn goals monthly "),
        ("pn-goal-quarterly", "🌓 Quarterly", "Goals for this quarter",
         None, "pn goals quarterly "),
        ("pn-goal-yearly",    "🎉 Yearly",    "Goals for this year",
         None, "pn goals yearly "),
    ]),
    "journals": ("📓 Journals", [
        ("pn-jm", "🌅 Morning journal", "Answer short questions",
         "xact:pn_journal:morning", None),
        ("pn-je", "🌙 Evening journal", "Answer short questions",
         "xact:pn_journal:evening", None),
        ("pn-jw", "📔 Weekly journal",  "Review the week, set next week",
         "xact:pn_journal:weekly", None),
    ]),
}


def family_rows(key, frag):
    label, members = _FAMILIES[key]
    items = []
    for uid, title, sub, arg, autoc in members:
        it = alfred.item(uid=uid, title=title, subtitle=sub,
                         arg=arg or "", valid=bool(arg), mods=_mods())
        if autoc:
            it["autocomplete"] = autoc
        items.append(it)
    if frag:
        items = fuzz.filter_and_score(frag, items, key_fn=lambda x: x["title"])
    if not items:
        return [alfred.item(uid=f"pn-{key}-nohit",
                            title=f'Nothing in {label} matching "{frag}"',
                            valid=False, mods=_mods())]
    items.append(alfred.item(uid=f"pn-{key}-back", title="🔙 Back",
                             subtitle="Every periodic row", arg="", valid=False,
                             autocomplete="pn ", mods=_mods()))
    return items


_GOAL_TIERS = {"daily": "☀️ Daily", "weekly": "♻️ Weekly",
               "monthly": "🗓️ Monthly", "quarterly": "🌓 Quarterly",
               "yearly": "🎉 Yearly"}


def tier_goal_rows(kind, rest, jnl=None):
    """One screen, Vex's three shapes (2026-09-12):
        "<text>"              -> ➕ the text alone
        "<frag>"              -> pick a task alone
        "<text> | <frag>"     -> the text anchored to the picked task
    The pipe is the add bar's own separator, so the grammar is one you
    already type; the 🔗 row hands the line back with it appended.

    jnl = a goal_handoff state: the screen a paused journal opened (Vex
    2026-09-15 - tomorrow's goal from the evening journal, today's from the
    morning check). Same rows, aimed at that day, each pick carrying the
    handoff so it answers the question and reopens the journal; 🔙 Back
    becomes ⏭ No goal.
    """
    label = _GOAL_TIERS[kind]
    prefix = f"pn goals {kind}"
    if jnl:
        day = jnl["for_day"]
        label = ("☀️ Tomorrow" if jnl["slot"] == "evening" else "☀️ Today") \
            + f" ({day.strftime('%a %d %b')})"
        prefix = "pn goals journal"
    head, _, tail = (rest or "").partition("|")
    text, frag = head.strip(), tail.strip()
    combining = "|" in (rest or "")

    def arg(txt, t=None):
        payload = {"kind": kind, "text": txt}
        if t is not None:
            payload.update({"pid": t.get("projectId") or t.get("_projectId", ""),
                            "tid": t["id"], "title": t.get("title") or ""})
        if jnl:
            payload["jnl"] = {"slot": jnl["slot"], "mode": jnl["mode"],
                              "note_day": jnl["note_day"].isoformat(),
                              "for_day": jnl["for_day"].isoformat()}
        return "xact:pn_setgoal:" + _b64(payload)

    items = []
    if combining and text:
        items.append(alfred.item(
            uid="pn-goal-textonly", title=f'🎯 {label} · "{text[:44]}"',
            subtitle="⏎ Just the text, no task", arg=arg(text),
            valid=True, mods=_mods()))
    elif text:
        items.append(alfred.item(
            uid="pn-goal-textonly", title=f'🎯 {label} · "{text[:44]}"',
            subtitle="⏎ Set it  ·  ⇥ then a task", arg=arg(text),
            valid=True, autocomplete=f"{prefix} {text} | ",
            mods=_mods()))

    pool = _task_pool(include_notes=(kind == "daily"))
    pick = frag if combining else text
    if pick:
        pool = fuzz.filter_and_score(pool and pick, pool,
                                     key_fn=lambda t: t.get("title") or "")
    for t in pool[:30]:
        items.append(alfred.item(
            uid=f"pn-goal-{kind}-{t['id']}",
            title=("📋 " if not (combining and text) else "🔗 ") + pick_title(t),
            subtitle=pick_where(t) + (f'  |  ⏎ "{text[:24]}" on this task'
                                      if (combining and text)
                                      else f"  |  ⏎ The {label} goal"),
            arg=arg(text if combining else "", t), valid=True, mods=_mods()))
    if not items:
        items = [alfred.item(uid="pn-goal-empty",
                             title=f"Type the {label} goal…",
                             subtitle="Text, a task, or both with  |",
                             valid=False, mods=_mods())]
    if jnl:
        skip = {"slot": jnl["slot"], "mode": jnl["mode"],
                "note_day": jnl["note_day"].isoformat(),
                "for_day": jnl["for_day"].isoformat()}
        if jnl["mode"] == "changed":
            # Change… then nothing: the goal stays, and the answer says so
            skip_title = "↩️ Keep the current goal"
        else:
            skip_title = "⏭ No goal tonight" if jnl["slot"] == "evening" else "⏭ No goal today"
        items.append(alfred.item(
            uid="pn-goal-jnl-skip", title=skip_title,
            subtitle="Back to the journal", arg="xact:pn_goal_skip:" + _b64(skip),
            valid=True, mods=_mods()))
        return items
    items.append(alfred.item(uid=f"pn-goal-{kind}-back", title="🔙 Back",
                             subtitle="Every tier", arg="", valid=False,
                             autocomplete="pn goals ", mods=_mods()))
    return items


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
        row = areas.setup_row("Periodic notes", "48-periodic.md")
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
    for key in ("goals", "journals"):
        rest = _after(q, key)
        if rest is None:
            continue
        if key == "goals":
            sub = _after(rest, "journal")
            if sub is not None:                 # a paused journal's picker
                import goal_handoff
                state = goal_handoff.load()
                if not state:
                    # never the ordinary picker: that would set TODAY's goal
                    # from tomorrow's question
                    return [alfred.item(uid="pn-goal-jnl-expired",
                                        title="🎯 This goal screen expired",
                                        subtitle="Run the journal again",
                                        valid=False, mods=_mods())]
                return tier_goal_rows("daily", sub, jnl=state)
            for tier in _GOAL_TIERS:
                sub = _after(rest, tier)
                if sub is not None:
                    return tier_goal_rows(tier, sub)
        return family_rows(key, rest)
    rest = _after(q, "day")
    if rest is not None:
        return day_goal_rows(rest)
    rest = _after(q, "goal")
    if rest is not None:
        return goal_rows(rest)
    return idle_rows(q)
