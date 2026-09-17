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
    ("h", "⭐️ Highlight"), ("$", "💰 Money"), ("b", "📋 Backlog"),
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
                "h": "The one thing this week is remembered for",
                "$": "Money you made, any day this week",
                "b": "Fill in a day you missed"}
# k, h, $ and b own a whole screen rather than one text row. Money is in the
# legend because Vex asked for it back "under entries row" (2026-09-17) and the
# `pn $ ` keyword caller still exists; both roads enter the SAME machine, one
# step apart, so there is one money screen and not two doors onto one answer.


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
    if letter == "$":                     # 💰 straight into the machine
        return income_rows(tail.strip())
    if letter == "b":                     # 📋 Backlog IS the machine
        return backlog_rows(tail.strip())
    if len(letter) == 1 and letter not in _KINDS:
        # Everything unrecognised used to fall through to THOUGHT, so
        # `pn + $ 485` logged a thought called "$ 485" and `pn + m 200` one
        # called "m 200" - a valid row, no warning (found 2026-09-17). A
        # single stray character is a mistyped kind, never a thought worth
        # keeping; longer text still is one.
        return [alfred.item(uid="pn-kind-unknown",
                            title=f"No entry kind “{head}”",
                            subtitle="⏎ see the kinds", valid=False,
                            autocomplete="pn + ", mods=_mods())]
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


def _pe():
    """periodic_engine, loaded ON DEMAND. It pulls in requests through api,
    and this module renders on every keystroke of the pn scope - only the 💰
    screen needs the engine, so only the 💰 screen pays for it."""
    import periodic_engine
    return periodic_engine


_DAY_TOKEN_RE = re.compile(r"(?<!\S)\*(\S+)\s*$")
_PIN_RE = re.compile(r"^!(\d{4}-\d{2}-\d{2})\b\s*")


# A parser returns (shown, payload, typed). `shown` is what a row DISPLAYS,
# `typed` is what goes back into the bar when a row autocompletes - they are
# not the same string, and conflating them silently dropped the money label on
# every round trip through the confirm screen (caught by tests/test_money.py).
def _parse_money(rest):
    head, _, tail = rest.partition(" ")
    amt = pm.parse_amount(head) if head else None
    if amt is None:
        return None
    label = tail.strip()
    shown = pm.fmt_amount(amt)
    return shown, {"amount": amt, "label": label}, shown + (f" {label}" if label else "")


def _parse_text(rest):
    rest = " ".join(rest.split())
    return (rest, {"text": rest}, rest) if rest else None


_SCALE_RE = re.compile(r"^([1-5])(?!\d)(?:\s*·?\s*(.*))?$", re.S)


def _parse_scale(rest):
    # the SAME shape xact's mood branch uses. The legend hint literally teaches
    # the separator ("1 to 5, a note after ·"), so "4 · tired" must store
    # "🙂 tired" and not "🙂 · tired" - two doors onto one answer cannot write
    # two shapes of it (found by review 2026-09-17).
    m = _SCALE_RE.match(rest.strip())
    if not m:
        return None
    head, note = m.group(1), (m.group(2) or "").strip()
    return head, {"score": int(head), "note": note}, head + (f" {note}" if note else "")


def _unknown_day_row(msg):
    return [alfred.item(uid="pn-bk-noday", title=f"📋 {msg}",
                        subtitle="Pick a day from the list",
                        valid=False, mods=_mods())]


# 📋 Backlog - ONE machine for "fill a day in after the fact" (Vex 2026-09-17:
# "Make it one machinery, put it under Backlog in entries row"). Every one of
# these is a single JOURNAL ANSWER on a single day, which is why they can share
# a screen: the strip, the state read and the overwrite guard are identical and
# only the value differs.
BACKLOG_KINDS = (
    {"letter": "h", "emoji": "✨", "label": "Highlight", "key": "dhighlight",
     "slot": "evening", "needle": "highlight of the day",
     "hint": "The day's one thing", "prompt": "Type the highlight…",
     "parse": _parse_text, "bad": "Words, not a number"},
    {"letter": "$", "emoji": "💰", "label": "Money", "key": "money",
     "slot": "evening", "needle": "money did you earn", "money": True,
     "hint": "What you made", "prompt": "Type the amount…",
     "parse": _parse_money, "bad": "Numbers first"},
    {"letter": "m", "emoji": "😊", "label": "Mood", "key": "mood",
     "slot": "morning", "needle": "mood 1-5",
     "hint": "1 to 5, a note after ·", "prompt": "Type 1 to 5…",
     "parse": _parse_scale, "bad": "1 to 5"},
    {"letter": "r", "emoji": "★", "label": "Day rating", "key": "rating",
     "slot": "evening", "needle": "rate the day",
     "hint": "1 to 5 stars", "prompt": "Type 1 to 5…",
     "parse": _parse_scale, "bad": "1 to 5"},
)
_BY_LETTER = {k["letter"]: k for k in BACKLOG_KINDS}
MONEY = _BY_LETTER["$"]


def _pe():
    """periodic_engine, loaded ON DEMAND. It pulls in requests through api,
    and this module renders on every keystroke of the pn scope - only the
    backlog screens need the engine, so only they pay for it."""
    import periodic_engine
    return periodic_engine


def _state(cfg, day):
    """(state, shown, raw) for one day, live off the cache. `shown` is for a
    row, `raw` is the answer as written - the money confirm screen has to test
    the real text to know whether adding would drop words from it."""
    try:
        pe = _pe()
        if cfg.get("money"):
            st, amt, txt = pe.day_money_state(day)
            return st, (pm.fmt_amount(amt) if amt is not None else txt), txt
        st, txt = pe.day_answer_state(day, cfg["slot"], cfg["needle"])
        return st, txt, txt
    except Exception:
        return "unknown", "", ""


def _week(cfg, today):
    """The week's state for this kind, newest day first. A broken cache costs
    the strip its values, never the screen."""
    try:
        rows = _pe().week_answer_states(cfg["slot"], cfg["needle"],
                                        today=today, money=bool(cfg.get("money")))
        return [(d, st, (pm.fmt_amount(v) if cfg.get("money") and v is not None
                         else (txt or "")), txt or "") for d, st, v, txt in rows]
    except Exception:
        # "unknown", NEVER "unasked": an unreadable cache used to mark every
        # day empty, which made every row a one-keystroke blind overwrite -
        # the exact thing the confirm screen exists to prevent.
        monday = today - timedelta(days=today.weekday())
        return [(monday + timedelta(days=i), "unknown", "", "")
                for i in range((today - monday).days, -1, -1)]


def _arg(cfg, payload, day, replace=False):
    return "xact:pn_backlog:" + _b64(dict(payload, kind=cfg["letter"],
                                          day=day.isoformat(),
                                          replace=bool(replace)))


def _confirm(cfg, day, shown, payload, had, prefix, typed, shown_had=None):
    """Vex's fail-safe (2026-09-17): "if money is entered already for the day
    that I am trying to enter it again, it shows entered amount first row,
    enter confirms or second row to adjust entry."

    What is already there leads. For money ⏎ ADDS to it, because two payments
    on one day are two payments; for everything else there is only ever one
    answer, so ⏎ keeps what is there and changing it is the second row. Either
    way nothing is overwritten that has not been read first.
    """
    when = pm.day_label(day)
    shown_had = had if shown_had is None else shown_had
    rows = []
    if cfg.get("money"):
        amt, prev = payload["amount"], pm.parse_money_answer(had)
        if prev is not None:
            rows.append(alfred.item(
                uid="pn-bk-add",
                title=f"{cfg['emoji']} {when} · {pm.fmt_amount(prev)} + "
                      f"{pm.fmt_amount(amt)} = {pm.fmt_amount(prev + amt)}",
                subtitle="⏎ Add it" + ("" if had.strip().startswith(
                    pm.fmt_amount(prev)) else "  ·  keeps the number, not the words"),
                arg=_arg(cfg, payload, day), valid=True, mods=_mods()))
    else:
        rows.append(alfred.item(
            uid="pn-bk-keep", title=f"{cfg['emoji']} {when} · {shown_had[:60]}",
            subtitle="⏎ Leave it", arg="", valid=False, mods=_mods()))
        # back to the strip WITH what he typed still in the bar: an invalid
        # Alfred row performs its autocomplete on Return, and a bare prefix
        # here wiped the answer he was in the middle of filing
        rows[-1]["autocomplete"] = prefix + typed
    rows.append(alfred.item(
        uid="pn-bk-replace",
        title=f"✏️ {when} · {shown_had[:30]} → {shown[:30]}",
        subtitle="⏎ Replace it",
        arg=_arg(cfg, payload, day, replace=True), valid=True, mods=_mods()))
    back = alfred.item(uid="pn-bk-back", title="🔙 Another day",
                       subtitle="Pick again", valid=False, mods=_mods())
    back["autocomplete"] = prefix + typed
    rows.append(back)
    return rows


def _day_row(cfg, day, state, holds, shown, payload, today, prefix, typed=""):
    when = pm.day_label(day)
    if day == today:
        title = f"☀️ Today · {when}"
    elif day == today - timedelta(days=1):
        title = f"◀️ Yesterday · {when}"
    else:
        title = f"📅 {when}"
    sub = ("Cannot read that day" if state == "unknown"
           else f"Has {holds[:40]}" if (state == "answered" and holds)
           else "Has an answer" if state == "answered" else "Nothing yet")
    it = alfred.item(uid=f"pn-bk-{cfg['letter']}-{day.isoformat()}",
                     title=title, subtitle=sub, valid=False, mods=_mods())
    if shown is None:
        return it
    if state in ("answered", "unknown"):
        it["subtitle"] = f"{sub}  ·  ⏎ " + ("Add or fix" if cfg.get("money")
                                            else "Keep or replace")
        it["autocomplete"] = f"{prefix}!{day.isoformat()} {typed}"
        return it
    it["subtitle"] = f"{sub}  ·  ⏎ Log {shown[:30]}"
    it["arg"] = _arg(cfg, payload, day)
    it["valid"] = True
    return it


def day_strip_rows(cfg, rest, prefix):
    """THE machine: type the value, pick the day it belongs to.

    Every row names a day, today included, so filling in a day you missed is
    the same move as today and there is no separate mode to remember. Each day
    shows what it already holds, read from the CACHE - this renders on every
    keystroke.

    `!<ISO>` at the front pins a day (the rows autocomplete it in, he never
    types it); a trailing `*tue` / `*-2` / `*9` targets one day by hand through
    pm.past_day, which reads BACKWARD unlike dateutil.parse_date.
    """
    rest = (rest or "").strip()
    pin = _PIN_RE.match(rest)
    if pin:
        rest = rest[pin.end():]
    want = None
    m = _DAY_TOKEN_RE.search(rest)
    if m and not pin:
        # ONLY strip it when it really is a day. The token was being cut off
        # whatever it said, so "Shipped the thing *finally" silently lost its
        # last word on a free-text answer (found by review 2026-09-17).
        want = pm.past_day(m.group(1))
        if want is not None:
            rest = rest[:m.start()].rstrip()
    parsed = cfg["parse"](rest) if rest else None
    today = date.today()
    strip = _week(cfg, today)

    if parsed is None:
        first = alfred.item(
            uid="pn-bk-prompt", title=f"{cfg['emoji']} {cfg['prompt']}",
            subtitle=cfg["bad"] if rest else "Then pick a day",
            valid=False, mods=_mods())
        return [first] + [_day_row(cfg, d, st, holds, None, None, today, prefix)
                          for d, st, holds, _raw in strip]
    shown, payload, typed = parsed
    if pin:
        try:
            day = date.fromisoformat(pin.group(1))
        except ValueError:
            return _unknown_day_row("Not a date")
        if day > today:
            # pm.past_day refuses the future on the *token road; the pin road
            # has to refuse it too, or a typo back-mints and seeds a note for
            # a day that has not happened
            return _unknown_day_row("Not a day you have had yet")
        st, shown_had, raw = _state(cfg, day)
        if st == "answered":
            return _confirm(cfg, day, shown, payload, raw, prefix, typed, shown_had)
        return [_day_row(cfg, day, st, shown_had, shown, payload, today, prefix, typed)]
    days = strip
    if want is not None:
        days = [r for r in strip if r[0] == want] or [(want, ) + _state(cfg, want)]
        days = [d for d in days if d[0] <= today]
    if not days:
        return [alfred.item(uid="pn-bk-noday",
                            title=f"{cfg['emoji']} Not this week",
                            subtitle="Pick a day from Monday on",
                            valid=False, mods=_mods())]
    return [_day_row(cfg, d, st, holds, shown, payload, today, prefix, typed)
            for d, st, holds, _raw in days]


def backlog_rows(rest):
    """`pn + b …` - the 📋 Backlog screen: what are you filling in, and when.
    The 💰 money road (`pn $`, the `tmo` keyword) enters the same machine one
    step further in, so there is one screen and not two."""
    rest = (rest or "").strip()
    head, _, tail = rest.partition(" ")
    cfg = _BY_LETTER.get(head.lower()) if head else None
    if cfg is not None:
        return day_strip_rows(cfg, tail.strip(), f"pn + b {cfg['letter']} ")
    if head:
        return [alfred.item(uid="pn-bk-unknown",
                            title=f"Nothing to fill in called “{head}”",
                            subtitle="⏎ see the list", valid=False,
                            autocomplete="pn + b ", mods=_mods())]
    rows = []
    for k in BACKLOG_KINDS:
        it = alfred.item(uid=f"pn-bk-kind-{k['letter']}",
                         title=f"{k['emoji']} {k['label']}",
                         subtitle=k["hint"], arg="", valid=False, mods=_mods())
        it["autocomplete"] = f"pn + b {k['letter']} "
        rows.append(it)
    return rows


def income_rows(rest):
    """`pn $ …` and the `tmo` keyword: straight into the machine on money."""
    return day_strip_rows(MONEY, rest, "pn $ ")


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
