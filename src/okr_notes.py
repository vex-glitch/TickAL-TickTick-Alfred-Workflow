"""okr_notes.py - the plan in the periodic notes (HANDOFF_OKR phase 4).

Vex 2026-09-19: "We should also then have the OKRs section in periodic notes.
All of them. With all levels. Instead of goals I guess. The only thing is
that there will still exist our hand picked goals. I think those should
appear in the same line as the forecasted goal for that period, kind of like
our comparison for other data."

He then picked, from mocks: a NEW section at the top of every tier, one line
per tier from the year down to the note's own, the plan first and the goal
he picked for that tier on the SAME line. The daily note of 2026-09-19:

    #### 🥅 OKRs
    - 🎉 2026 · 6 🥅 · 0/41 KRs · 🔴 1d · 🎯 Productivity System
    - 🌓 Q3 · 🥅 Onboard TickTicks 0/5 · 🥅 TickAL 0/6 · 🎯 none
    - 🗓️ Sep · 🥅 Onboard TickTicks · 🥅 TickAL · 0/7 KRs · 🔴 1d · 🎯 TickAL • WF
    - ♻️ W38 · 🔑 Finish periodic notes 🔴 1d · 🔑 Goals wf · 🎯 Onboard TickTick
    - ☀️ Sat 19 · 🔑 Goals wf · 🎯 Onboard TickTick

(every plan name and every linked goal is a markdown link in the note; the
mock above shows the labels). The day line says "Sat 19", never "Today": a
note stops refreshing once its day is over and keeps whatever text it had.

Three things read the plan here, and all three ask plan_for():
  * okr_section_lines - the 🥅 OKRs section of every tier,
  * scorecard_lines   - the yearly note's 🎯 Goals scorecard,
  * goal_choices      - the 🔮 rows of every goal picker ("First row could
    say something like: '<mimic objective or key result for respective
    period>', enter would set that as goal", Vex 2026-09-19).
One selection, so a note and a picker can never disagree about what the
plan says for a period.

Tier -> what the plan means there (HANDOFF_OKR section 4): 🎉 year = the Y's
(their O's when there is no Y), 🌓 quarter = the O's overlapping it, 🗓️ month
= O's + KRs, ♻️ week and ☀️ day = the KRs overlapping them.

PURE: no I/O. The engine (periodic_engine._fill_okr) hands in the cached
plan (okr_write.cached_plan - never the network inside a refresh), the goal
lines it read out of each tier's own note, and today.
"""
import re

import focus_blocks as fb
import mdtext
import okr
import okr_write
import periodic_model as pm

TIERS = ("yearly", "quarterly", "monthly", "weekly", "daily")

# The plan levels each tier reads, IN ORDER - a yearly picker offers the
# Y's before the O's, a monthly note names the O's before counting the KRs.
PLAN_KINDS = {"yearly": ("Y", "O"), "quarterly": ("O",),
              "monthly": ("O", "KR"), "weekly": ("KR",), "daily": ("KR",)}

GLYPH = {"Y": "🏔️", "O": "🥅", "KR": "🔑"}

# How many names a line carries before the rest fold into "+N". A note line
# is read at a glance; the hub (ctx:okr) is where the whole list lives.
CAP = {"yearly": 3, "quarterly": 4, "monthly": 4, "weekly": 5, "daily": 5}

BAR_CELLS = 5


# ── the plan of one period ───────────────────────────────────────────────────
def plan_for(kind, start, end, items):
    """The plan of a `kind` period start..end: the items of that tier's
    levels (PLAN_KINDS) whose span touches it, level by level, each in plan
    (start) order. okr.overlapping does the test, on the WANTED span of a
    Y/O, so a stale stored span never hides an objective from its month.

    Done items stay in - they were the plan, and a note shows them as ✅.
    Won't-do items are left out: dropping one is Vex changing the plan, not
    reality drifting from it."""
    out = []
    for k in PLAN_KINDS[kind]:
        out += [it for it in okr.overlapping(items, start, end, (k,))
                if not it.abandoned]
    return out


def goal_choices(kind, start, end, items, today=None):
    """The OPEN plan items a `kind` goal picker offers as 🔮 rows for the
    period start..end, as okr.Item objects: yearly Y's then O's, quarterly
    O's, monthly O's then KRs, weekly and daily KRs - each level in plan
    order. Done ones are gone: a goal is something still to do.

    The picker decides the rest (skipping one already set as a goal, and
    setting the LINKED ORIGINAL, never the planning copy - a daily goal from
    a task MOVES that task onto the day). `today` is accepted for the
    picker's convenience; the choice depends on the period alone, the same
    rule as the note's own lines."""
    return [it for it in plan_for(kind, start, end, items) if not it.done]


# ── pieces ───────────────────────────────────────────────────────────────────
def tier_label(kind, p):
    """🎉 2026 · 🌓 Q3 · 🗓️ Sep · ♻️ W38 · ☀️ Sat 19 - a name for the period
    that stays true after it is over (never "Today", never "This week")."""
    s = p.start
    e = pm.TIER_EMOJI[kind]
    if kind == "yearly":
        return f"{e} {s.year}"
    if kind == "quarterly":
        return f"{e} Q{(s.month - 1) // 3 + 1}"
    if kind == "monthly":
        return f"{e} {pm.MONTH_ABBR[s.month]}"
    if kind == "weekly":
        return f"{e} W{s.isocalendar()[1]:02d}"
    return f"{e} {pm.DAY_ABBR[s.weekday()]} {s.day}"


def item_link(it, list_id=None):
    """A plan item's name as a link to its PLANNING COPY - the note is about
    the plan, and the copy is where he drags it in the timeline."""
    return mdtext.md_link(it.name or "(untitled)",
                          okr.task_link(list_id or it.pid, it.id))


def _late_days(it, today):
    """Days an OPEN dated item is past its end, 0 when it is not."""
    if it.done or not it.dated or today is None or it.end >= today:
        return 0
    return (today - it.end).days


def _kr_piece(it, today, list_id):
    if it.done:
        return f"✅ {item_link(it, list_id)}"
    late = _late_days(it, today)
    return f"🔑 {item_link(it, list_id)}" + (f" 🔴 {late}d" if late else "")


def _capped(pieces, cap):
    if len(pieces) <= cap:
        return list(pieces)
    return list(pieces[:cap]) + [f"+{len(pieces) - cap}"]


def _behind(items, start, end, today):
    pp = okr.period_pace(items, start, end, today)
    return pp, ([f"🔴 {pp.behind_days}d"] if pp.behind_days > 0 else [])


def _year_pieces(items, start, end, today, list_id):
    pp, chip = _behind(items, start, end, today)
    ys = [it for it in plan_for("yearly", start, end, items) if it.kind == "Y"]
    if ys:
        pieces = _capped(
            [f"{GLYPH['Y']} {item_link(y, list_id)} "
             f"{'/'.join(map(str, okr.progress(y, items)))}" for y in ys],
            CAP["yearly"])
    else:
        # no Y yet (the live list on 2026-09-19): the year is its objectives
        # and its deliverables, counted
        os_ = [it for it in plan_for("yearly", start, end, items) if it.kind == "O"]
        pieces = []
        if os_:
            pieces.append(f"{len(os_)} {GLYPH['O']}")
        if pp.total:
            pieces.append(f"{pp.done}/{pp.total} KRs")
    return (pieces + chip) if pieces else ["no plan"]


def _quarter_pieces(items, start, end, today, list_id):
    os_ = plan_for("quarterly", start, end, items)
    pieces = [f"{GLYPH['O']} {item_link(o, list_id)} "
              f"{'/'.join(map(str, okr.progress(o, items)))}" for o in os_]
    return _capped(pieces, CAP["quarterly"]) or ["no plan"]


def _month_pieces(items, start, end, today, list_id):
    pp, chip = _behind(items, start, end, today)
    os_ = [it for it in plan_for("monthly", start, end, items) if it.kind == "O"]
    pieces = _capped([f"{GLYPH['O']} {item_link(o, list_id)}" for o in os_],
                     CAP["monthly"])
    if pp.total:
        pieces.append(f"{pp.done}/{pp.total} KRs")
    return (pieces + chip) if pieces else ["no plan"]


def _kr_pieces(kind):
    def build(items, start, end, today, list_id):
        krs = plan_for(kind, start, end, items)
        return _capped([_kr_piece(k, today, list_id) for k in krs],
                       CAP[kind]) or ["no plan"]
    return build


_PIECES = {"yearly": _year_pieces, "quarterly": _quarter_pieces,
           "monthly": _month_pieces, "weekly": _kr_pieces("weekly"),
           "daily": _kr_pieces("daily")}


# ── the goal Vex picked, on the same line ────────────────────────────────────
_BOX_RE = re.compile(r"^- \[[ xX]\]\s*")


def goal_label(line):
    """One goal LINE out of a tier's goal section -> its label on an OKR
    line, '' when the line is not a goal (a pointer, a placeholder, a bare
    box - pm.goal_titles decides, the same reader every goal screen uses).

    The name is cleaned the way a planning copy's is (okr_write._clean_name:
    link labels, no "💼 P • " lead, no trailing 🔗) and linked to its task
    when the goal line links one, so "[💼 P • TickAL • WF 🔗](…/tasks/T)"
    reads "[TickAL • WF](…/tasks/T)". The app's backslash escapes go first:
    an escaped link would otherwise keep its task out of reach."""
    if not pm.goal_titles([line]):
        return ""
    raw = pm.unescape_md((line or "").strip())
    raw = _BOX_RE.sub("", raw)
    raw = raw[2:] if raw.startswith("- ") else raw
    name = okr_write._clean_name(raw)
    if not name:
        return ""
    tail = fb.LINK_TAIL_RE.search(raw)
    if tail:
        return mdtext.md_link(name, okr.task_link(tail.group("pid"),
                                                  tail.group("tid")))
    return name


def goals_part(lines):
    """"🎯 A · B" for a tier's goal lines, "🎯 none" when it has none - the
    comparison is the point, so an empty side still says so."""
    labels = list(dict.fromkeys(x for x in map(goal_label, lines or []) if x))
    return "🎯 " + (" · ".join(labels) if labels else "none")


# ── the section ──────────────────────────────────────────────────────────────
def tiers_down_to(kind):
    """The tiers a `kind` note shows, the year first: a daily note all five,
    a yearly one only itself."""
    return TIERS[:TIERS.index(kind) + 1]


def okr_section_lines(kind, p, items, goals_by_tier, today, list_id):
    """The 🥅 OKRs body of a `kind` note for period p: one "- " line per tier
    from the year down to the note's own, "<label> · <the plan> · 🎯 <the
    goal>". The tiers above the note are the periods holding its FIRST day
    (a week's month is its Monday's - the breadcrumb's own convention).

    goals_by_tier = {tier kind: [goal lines from THAT tier's own note]};
    a tier missing from it reads "🎯 none"."""
    goals_by_tier = goals_by_tier or {}
    out = []
    for t in tiers_down_to(kind):
        tp = p if t == kind else pm.period_for(t, p.start)
        pieces = _PIECES[t](items, tp.start, tp.end, today, list_id)
        out.append("- " + " · ".join([tier_label(t, tp)] + pieces
                                      + [goals_part(goals_by_tier.get(t))]))
    return out


# ── the yearly 🎯 Goals scorecard ────────────────────────────────────────────
def bar(done, total, cells=BAR_CELLS):
    """▰▰▱▱▱ - done over total in five cells, rounded; nothing done is
    all empty however many there are, everything done is all full."""
    if total <= 0 or done <= 0:
        return "▱" * cells
    # half UP, not Python's half-to-even: 1 of 2 is three cells, never two
    n = max(1, min(cells, int(cells * done / total + 0.5)))
    if done < total:
        n = min(n, cells - 1)          # one KR short is never a full bar
    return "▰" * n + "▱" * (cells - n)


def _top_line(it, items, want, today, ref, list_id):
    """"- 🏔️ <name> ▰▰▱▱▱ d/n · <span> · 🔴 Nd" - a scorecard's top line."""
    d, n = okr.progress(it, items)
    bits = [f"{GLYPH[it.kind]} {item_link(it, list_id)} {bar(d, n)} {d}/{n}",
            okr.span_txt(*okr._effective(it, want), ref)]
    behind = okr.pace(it, items, today).behind_days if today else 0
    if behind > 0:
        bits.append(f"🔴 {behind}d")
    return "- " + " · ".join(bits)


def scorecard_lines(p, items, today, list_id):
    """The plan half of the yearly note's 🎯 Goals scorecard:

        - 🏔️ Productivity System ▰▰▱▱▱ 4/10 · Jan 5 - Dec 20 · 🔴 3d
        \t- 🥅 TickAL 2/6 · Sep 19 - Oct 14

    one line per 🏔️ Y overlapping the year, its O's tab-indented under it.
    With no Y (the live list on 2026-09-19) the O's overlapping the year
    ARE the top level, and take the Y line's shape - bar and 🔴 - since they
    are what the year is scored on. Spans are the WANTED spans (a stale
    stored one is exactly what the next heal fixes), written with the year
    only when it is not the note's. [] when the year has no plan.

    Only the plan: the goals he picked for the year live in the same
    section (pm.GOAL_SECTION["yearly"]) and merge_scorecard keeps them."""
    want = okr.wanted_spans(items)
    ref = p.start                       # the year a span is written without
    plan = plan_for("yearly", p.start, p.end, items)
    ys = [it for it in plan if it.kind == "Y"]
    kids = okr._kids(items)
    out = []
    for top in ys or [it for it in plan if it.kind == "O"]:
        out.append(_top_line(top, items, want, today, ref, list_id))
        if top.kind != "Y":
            continue
        for o in kids.get(top.id, []):
            if o.kind != "O" or o.abandoned:
                continue
            d, n = okr.progress(o, items)
            out.append(f"\t- {GLYPH['O']} {item_link(o, list_id)} {d}/{n} · "
                       + okr.span_txt(*okr._effective(o, want), ref))
    return out


def _rebase(lines, tabs):
    real = [ln for ln in lines if ln.strip()]
    if not real:
        return list(lines)
    base = min(len(ln) - len(ln.lstrip("\t")) for ln in real)
    return ["" if not ln.strip() else
            "\t" * (tabs + len(ln) - len(ln.lstrip("\t")) - base) + ln.lstrip("\t")
            for ln in lines]


def _pending(line):
    s = pm.unescape_md(line.strip())
    return bool(pm.PENDING_RE.match(s)
                or (s.startswith("- ") and pm.PENDING_RE.match(s[2:])))


def merge_scorecard(body, plan_lines):
    """The scorecard body with the plan half replaced and EVERYTHING else
    kept - above all the yearly goals: the 🎯 Goals scorecard is where the
    yearly goal setter appends them (pm.GOAL_SECTION["yearly"]), and the
    🎉 year line of every OKR section reads them back from here.

    Ours are the lines pm.is_plan_line recognizes; they are regenerated.
    The rest keep their order and come after the plan, re-based to its
    depth (relative nesting kept), so a goal never reads as the child of the
    last objective. The template's "_(pending)_" goes once there is
    anything to show, and comes back when nothing is left."""
    kept = [ln for ln in body or []
            if ln.strip() and not pm.is_plan_line(ln) and not _pending(ln)]
    if not plan_lines:
        return kept or ["_(pending)_"]
    return list(plan_lines) + _rebase(kept, 0)
