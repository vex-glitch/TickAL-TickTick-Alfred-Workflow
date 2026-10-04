"""okr_notes.py - the 🔑OKRs board in the periodic notes (HANDOFF_OKR
section 8, 2026-10-03).

Vex: "our notes and journals should somehow mimic these OKRs now." Every
tier carries a `🥅 OKRs` section at the top (pm.SEC_OKR, the kill switch:
delete it and nothing OKR is written to that note again) and this module
writes its body the way the board reads, one bullet per column, the
column's areas as bullets under it, the objectives under their area, the
key results under their objective:

    - 🔟 October • 1/22 KRs
    \t- 🏔️ VexOS 4️⃣ • 1/22 KRs
    \t\t- 🥅 [Onboard TickTicks](link) 1/3
    \t\t\t- ✅ [Reschedule Goals](link)
    \t\t\t- 🔑 [Audits](link)

What each tier shows (the 2026-10-03 proposal, "All good"):
    ☀️ day, ♻️ week   this month, whole (a week's month is its Thursday's)
    🗓️ month          its month whole, then the other months of its
                      quarter, objectives only (the monthly journal asks
                      about the quarter's objectives)
    🌓 quarter        the year's Goals column, then its three months,
                      objectives only
    🎉 year           the year's Goals column, then its planned months,
                      objectives only

The names link to the cards on the board. Won't-do key results are left
out (dropping one is Vex changing the plan) and out of every count. The
yearly note's 🎯 Goals scorecard gets one flat line per year goal, a bar
and the roll-up of the same-named monthly objectives; merge_scorecard
keeps every line that is not ours (the yearly goals live there too).

Three things read the board here and all three ask the same model:
okr_section_lines (the section), scorecard_lines (the scorecard) and
goal_choices (the 🔮 rows of every goal picker). PURE: no I/O. The engine
(periodic_engine._fill_okr) hands in the cached board (okr_board.cached).
"""
import mdtext
import okr_board as ob
import periodic_model as pm

TIERS = ("yearly", "quarterly", "monthly", "weekly", "daily")

# The separator on a column's own bullet. U+2022, never the middle dot:
# "you are using some weird version of • Which I cannot use arrow keys to
# move characters" (Vex 2026-09-19, about U+00B7 in these lines).
SEP = " • "

# key-result lines per objective before the rest fold into "+N more" (the
# hub holds them all; a note is read at a glance - October's Shortcuts
# objective alone has 16)
KR_CAP = 8
BAR_CELLS = 5
NO_OBJECTIVES = "no objectives yet"       # pm.PLAN_LINE_RE knows this chip


# ── pieces ───────────────────────────────────────────────────────────────────
def card_link(card, list_id=None):
    """A card's name as a link to the card on the board."""
    return mdtext.md_link(card.name or "(untitled)",
                          ob.card_url(list_id or card.pid, card.id))


def _dn(d, n):
    return f"{d}/{n}"


def _kr_line(k, list_id):
    g = ob.GLYPH_DONE if k.done else ob.GLYPH_KR
    return f"{g} {card_link(k, list_id)}"


def _objective_line(o, list_id, with_count=True):
    """🥅 <name> d/n - the count only while the objective has key results
    (a bare "0/0" says nothing). A closed objective reads ✅."""
    g = ob.GLYPH_DONE if o.done else (ob.GLYPH_GOAL if o.kind == "goal" else ob.GLYPH_O)
    d, n = o.progress
    line = f"{g} {card_link(o.card, list_id)}"
    if with_count and n:
        line += f" {_dn(d, n)}"
    return line


def _area_line(a):
    d, n = a.progress
    return a.label + (f"{SEP}{_dn(d, n)} KRs" if n else "")


def _capped(lines, cap):
    if len(lines) <= cap:
        return list(lines)
    return list(lines[:cap]) + [f"+{len(lines) - cap} more"]


def _month_head(col, year, month):
    """"🔟 October • 1/22 KRs", or what is wrong with the column."""
    label = ob.month_bullet(year, month)
    if col is None:
        return label + SEP + "no column on the board"
    if col.empty:
        return label + SEP + "nothing planned"
    d, n = col.progress
    return label + (f"{SEP}{_dn(d, n)} KRs" if n else SEP + "no KRs yet")


def month_lines(board, year, month, list_id, krs=True):
    """One month's bullet with its areas, objectives and (krs=True) key
    results indented under it. A missing or empty column is one line."""
    col = board.month(year, month) if board is not None else None
    out = ["- " + _month_head(col, year, month)]
    if col is None or col.empty:
        return out
    for a in col.areas:
        out.append(f"\t- {_area_line(a)}")
        for o in a.objectives:
            if o.abandoned:
                continue
            out.append(f"\t\t- {_objective_line(o, list_id)}")
            if krs:
                lines = [_kr_line(k, list_id) for k in o.krs if not k.abandoned]
                out += [f"\t\t\t- {x}" for x in _capped(lines, KR_CAP)]
        if krs:
            out += [f"\t\t- {_kr_line(k, list_id)}" for k in a.loose_krs if not k.abandoned]
    for s in col.strays:
        if s.abandoned:
            continue
        g = ob.GLYPH_DONE if s.done else s.glyph
        out.append(f"\t- {g} {card_link(s, list_id)}")
    return out


def goals_lines(board, year, list_id):
    """The year's Goals column: "- 🏔️ 2027 Goals • 7 goals", its areas, each
    goal with the roll-up of the same-named monthly objectives when there
    is one ("0/11 • 12 months")."""
    col = board.goals(year) if board is not None else None
    head = f"{ob.GLYPH_GOAL} {year} Goals"
    if col is None or col.empty:
        return ["- " + head + SEP + ("no goals yet" if col is not None else "no column on the board")]
    goals = [o for a in col.areas for o in a.objectives if not o.abandoned]
    out = ["- " + head + SEP + f"{len(goals)} goal" + ("s" if len(goals) != 1 else "")]
    for a in col.areas:
        if not a.objectives:
            continue
        out.append(f"\t- {a.label}")
        for o in a.objectives:
            if o.abandoned:
                continue
            d, n, m = board.rollup(o)
            line = f"{ob.GLYPH_DONE if o.done else ob.GLYPH_GOAL} {card_link(o.card, list_id)}"
            if m:
                line += f" {_dn(d, n)}{SEP}{m} month" + ("s" if m != 1 else "")
            out.append(f"\t\t- {line}")
    return out


# ── the section ──────────────────────────────────────────────────────────────
def okr_section_lines(kind, p, board, list_id=None):
    """The 🥅 OKRs body of a `kind` note for period p (module docstring).
    [] when there is no board to read - the caller leaves the section as
    it is then."""
    if board is None:
        return []
    lid = list_id or board.list_id
    if kind in ("daily", "weekly"):
        y, m = ob.month_for(kind, p)
        return month_lines(board, y, m, lid, krs=True)
    if kind == "monthly":
        y, m = ob.month_for(kind, p)
        out = month_lines(board, y, m, lid, krs=True)
        for yy, mm in ob.quarter_months(p):
            if (yy, mm) != (y, m):
                out += month_lines(board, yy, mm, lid, krs=False)
        return out
    if kind == "quarterly":
        out = goals_lines(board, p.start.year, lid)
        for yy, mm in ob.quarter_months(p):
            out += month_lines(board, yy, mm, lid, krs=False)
        return out
    if kind == "yearly":
        out = goals_lines(board, p.start.year, lid)
        for yy, mm in ob.year_months(p):
            col = board.month(yy, mm)
            if col is not None and not col.empty:
                out += month_lines(board, yy, mm, lid, krs=False)
        return out
    return []


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


def scorecard_lines(p, board, list_id=None):
    """The plan half of the yearly note's 🎯 Goals scorecard, one FLAT line
    per year goal (flat, because merge_scorecard keeps every line that is
    not ours and an area line without a count would be kept as his):

        - 🏔️ [Draw](link) ▱▱▱▱▱ 0/11 • 12 months • Work 1️⃣
        - 🏔️ [Post](link) • no objectives yet • Work 1️⃣

    [] when the year has no Goals column or it is empty."""
    if board is None:
        return []
    lid = list_id or board.list_id
    col = board.goals(p.start.year)
    if col is None or col.empty:
        return []
    out = []
    for a in col.areas:
        for o in a.objectives:
            if o.abandoned:
                continue
            d, n, m = board.rollup(o)
            g = ob.GLYPH_DONE if o.done else ob.GLYPH_GOAL
            if m:
                bits = [f"{g} {card_link(o.card, lid)} {bar(d, n)} {_dn(d, n)}",
                        f"{m} month" + ("s" if m != 1 else "")]
            else:
                bits = [f"{g} {card_link(o.card, lid)}", NO_OBJECTIVES]
            bits.append(a.label[len(ob.GLYPH_AREA):].strip())
            out.append("- " + SEP.join(bits))
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
    yearly goal setter appends them (pm.GOAL_SECTION["yearly"]) and the
    quarterly note's 🎉 Yearly goal mirror reads them back from here.

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


# ── the goal pickers' 🔮 rows ────────────────────────────────────────────────
def goal_choices(kind, p, board):
    """The OPEN board items a `kind` goal picker offers as 🔮 rows for
    period p -> [(Column, Objective | Card)]: a day's and a week's picker
    the month's open key results then its open objectives, a month's its
    objectives then its key results, a quarter's the YEAR GOALS then the
    objectives of its three months (one per name), a year's the year goals.
    The year goals close every other tier's list too, so typing 🏔️ finds
    them anywhere. Done ones are gone: a goal is something still to do."""
    if board is None:
        return []
    gcol = board.goals(p.start.year)
    goals = [(gcol, o) for o in gcol.objectives if not o.closed] if gcol is not None else []
    out = []
    if kind in ("daily", "weekly", "monthly"):
        y, m = ob.month_for(kind, p)
        col = board.month(y, m)
        if col is not None:
            objs = [(col, o) for o in col.objectives if not o.closed]
            krs = [(col, k) for k in col.open_krs]
            out = objs + krs if kind == "monthly" else krs + objs
        # the year's goals last: a week or a month rarely takes one whole,
        # but typing 🏔️ must find them (Vex 2026-10-04)
        out += goals
    elif kind == "quarterly":
        # a quarter's goal is most often one of the year's: those first
        out = list(goals)
        seen = set()
        for y, m in ob.quarter_months(p):
            col = board.month(y, m)
            for o in (col.objectives if col else []):
                if not o.closed and o.key not in seen:
                    seen.add(o.key)
                    out.append((col, o))
    elif kind == "yearly":
        out = goals
    return out
