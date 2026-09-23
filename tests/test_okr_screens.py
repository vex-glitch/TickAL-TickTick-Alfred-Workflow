#!/usr/bin/env python3
"""The 🥅 OKR screens: Scripts/browse.py ctx:okr*, the main-menu row and the
⌘ Actions entity rows, rendered the way Alfred runs them (main() with the
ctx riding env browse_ctx) against a FAKE cache in a temp dir.

No network and no write anywhere real: okr.load is a stub that counts its
calls, okr_write is a stub module that counts heal spawns, cache.CACHE_DIR
points at a temp dir, and okr_list_id rides env. The dates are built around
today, so "late" and "behind" are stable on any day.

What it pins down (map_rows.md, the traps that burned the other hubs):
  * every row spells out all six chords, fresh dicts, ⌃ and ⌥ args empty,
    no xact: on ⌘ or ⌥, ⌘ dead on anything that is not a task, task rows
    carry the full variable set (so ⌘ opens Actions on THE item)
  * the network is read only on an empty bar, and a fresh read is reused
    until a cache a write patches moves past it
  * typing "today" / "tomorrow" on an OKR screen never jumps away
  * the verbs' payloads (b64 JSON) say what the writer contract says

    python3 tests/test_okr_screens.py
"""
import base64
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import types
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

FAILS = []
COUNT = [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


PID = "5eed00000000000000000a01"          # the fake OKR list
REALP, REALT, REALC = "5eed00000000000000000b01", "5eed00000000000000000b02", "5eed00000000000000000b03"
LISTP, OTHERP, OTHERT = "5eed00000000000000000c01", "5eed00000000000000000d01", "5eed00000000000000000d02"
NOTEP, NOTET = "5eed00000000000000000e01", "5eed00000000000000000e02"
# the 📌CTA list, a 💼 project list and its CTA task (the import's list swap)
CTAP, PROJP, CTAT = "5eed00000000000000000f01", "5eed00000000000000000f02", "5eed00000000000000000f03"
NAME = "🏆Goals Planning"
TODAY = date.today()


def day(n):
    return TODAY + timedelta(days=n)


def span_raw(s, e):
    """All-day, the exclusive form okr writes (due = the day after e)."""
    return (f"{s.isoformat()}T00:00:00+0000", f"{(e + timedelta(days=1)).isoformat()}T00:00:00+0000")


def T(tid, title, s=None, e=None, parent=None, status=0, tags=(), pid=PID, **kw):
    st, du = span_raw(s, e) if s else (None, None)
    t = {"id": tid, "projectId": pid, "title": title, "startDate": st, "dueDate": du,
         "timeZone": "", "isAllDay": True, "status": status, "parentId": parent,
         "childIds": [], "tags": list(tags), "_projectId": pid, "_projectName": NAME}
    t.update(kw)
    return t


# The plan. One Y with one O (its stored span STALE: the heal would move it
# onto its KRs), a loose O with a list-linked KR and an undated one, a
# closed O, a KR with no O, an unprefixed item, one completed KR that only
# a live read (v2 project_completed) knows about, and a won't-do KR (undated,
# so no period's plan and no span counts it).
Y1, O1, O2, O3, O4 = "y1", "o1", "o2", "o3", "o4"
KR1, KR2, KR3, KR4, KR5, KR6, KR7, LOOSE = "kr1", "kr2", "kr3", "kr4", "kr5", "kr6", "kr7", "loose"
KR8 = "kr8"
OPEN_ROWS = [
    T(Y1, "🏔️ Y • Productivity System", day(-10), day(30)),
    T(O1, "🥅 O • TickAL", day(5), day(20), parent=Y1, tags=["💼tickal"]),
    T(KR1, f"🔑 KR • [Goals wf](https://ticktick.com/webapp/#p/{REALP}/tasks/{REALT}) - TA",
      day(-3), day(-1), parent=O1, tags=["💼tickal"]),
    T(KR2, "🔑 KR • Review - TA", day(0), day(2), parent=O1, tags=["💼tickal"]),
    T(KR3, "🔑 KR • Publish - TA", day(3), day(12), parent=O1, tags=["💼tickal"]),
    T(O2, "🥅 O • Onboard TickTicks", day(1), day(6), tags=["💼onboardtt"]),
    T(KR5, f"🔑 KR • [Plan](ticktick:///webapp/#p/{LISTP}/tasks) - OT", day(1), day(6),
      parent=O2, tags=["💼onboardtt"]),
    T(KR6, "🔑 KR • Someday - OT", parent=O2, tags=["💼onboardtt", "⭐solo"]),
    T(O4, "🥅 O • Brand new thing"),
    T(KR7, "🔑 KR • Orphan deliverable", day(40), day(41)),
    T(LOOSE, "Loose idea", day(2), day(2)),
]
DONE_ROWS = [
    T(KR4, "🔑 KR • Kickoff - TA", day(-12), day(-10), parent=O1, status=2, tags=["💼tickal"]),
    T(O3, "🥅 O • Closed thing", day(-40), day(-30), status=2),
    T(KR8, "🔑 KR • Dropped - OT", parent=O2, status=-1, tags=["💼onboardtt"]),
]


def setup_cache(cache, periodic_pid):
    others = [
        T(REALT, "Goals workflow (the real one)", pid=REALP, _projectName="Real list",
          modifiedTime="2026-09-18T10:00:00.000+0000"),
        T(REALC, "A step of it", pid=REALP, parent=REALT, _projectName="Real list"),
        T(OTHERT, "Buy stamps", pid=OTHERP, _projectName="Errands",
          modifiedTime="2026-09-17T10:00:00.000+0000"),
    ]
    if periodic_pid:
        others.append(T("pn1", "☀️ 2026-09-18 · Fri", pid=periodic_pid, _projectName="💫Periodic"))
    others.append(T(CTAT, f"💼 P • [Website](ticktick:///webapp/#p/{PROJP}/tasks) 🔗",
                    pid=CTAP, _projectName="📌CTA"))
    note = T(NOTET, "Reading notes", pid=NOTEP, kind="NOTE", _projectName="Notes")
    cache.set("all_tasks", OPEN_ROWS + others)
    cache.set("all_notes", [note])
    cache.set(f"project_data_{PID}", {"project": {"id": PID, "name": NAME}, "tasks": OPEN_ROWS})
    cache.set("completed_tasks", [])
    cache.set("projects", [
        {"id": PID, "name": NAME, "sortOrder": 1},
        {"id": REALP, "name": "Real list", "sortOrder": 2},
        {"id": LISTP, "name": "Plan list", "sortOrder": 3},
        {"id": OTHERP, "name": "Errands", "sortOrder": 4},
        {"id": NOTEP, "name": "Notes", "sortOrder": 5, "kind": "NOTE"},
        {"id": CTAP, "name": "📌CTA", "sortOrder": 6},
        {"id": PROJP, "name": "💼P • Website", "sortOrder": 7},
        {"id": "smart1", "name": "Smart", "kind": "SMART_LIST"},
    ])
    cache.set("tags_tree", [
        {"name": "0️⃣area", "label": "0️⃣Area", "parent": None, "sortOrder": 1},
        {"name": "1️⃣work", "label": "1️⃣Work", "parent": "0️⃣area", "sortOrder": 2},
        {"name": "2️⃣personal", "label": "2️⃣Personal", "parent": "0️⃣area", "sortOrder": 3},
        {"name": "💼tickal", "label": "💼TickAL", "parent": None, "sortOrder": 4},
        {"name": "💼onboardtt", "label": "💼OnboardTT", "parent": None, "sortOrder": 5},
    ])
    cache.set("tags", ["0️⃣Area", "1️⃣Work", "2️⃣Personal", "💼TickAL", "💼OnboardTT"])


CH = ("cmd", "shift", "alt", "alt+shift", "alt+cmd", "cmd+shift")
TASK_VARS = ("task_id", "task_list_id", "list_id", "section_id", "task_title", "item_type")


def check_rows(screen, rows):
    """The row invariants, one check each per screen (offenders named)."""
    missing = [r["title"] for r in rows
               if any(k not in (r.get("mods") or {}) for k in CH + ("ctrl",))]
    check(f"{screen}: every row spells out all six chords + ⌃", not missing, missing)
    bad = [r["title"] for r in rows if (r["mods"].get("ctrl") or {}).get("arg") != ""]
    check(f"{screen}: ⌃ arg empty on every row", not bad, bad)
    bad = [r["title"] for r in rows if (r["mods"].get("alt") or {}).get("arg", "") != ""]
    check(f"{screen}: ⌥ arg empty on every row (it would land in the bar)", not bad, bad)
    bad = [r["title"] for r in rows for k in ("cmd", "alt")
           if str((r["mods"].get(k) or {}).get("arg", "")).startswith("xact:")]
    check(f"{screen}: no xact: on ⌘ or ⌥", not bad, bad)
    bad = [r["title"] for r in rows if not (r.get("variables") or {}).get("task_id")
           and (r["mods"].get("cmd") or {}).get("valid") is not False]
    check(f"{screen}: ⌘ dead on every row that is not a task", not bad, bad)
    bad = [r["title"] for r in rows if (r.get("variables") or {}).get("task_id")
           and not all(k in r["variables"] for k in TASK_VARS)]
    check(f"{screen}: task rows carry the full task variables", not bad, bad)


def check_shared(screen, rows):
    """On the renderer's OWN list (JSON would hide it): add_back rewrites
    mods in place, so one dict shared by two rows shares their ⌃ too."""
    ids = [id(m) for r in rows for m in r["mods"].values()] + [id(r["mods"]) for r in rows]
    check(f"{screen}: no mods dict shared between rows", len(ids) == len(set(ids)))


def b64(arg, prefix):
    assert arg.startswith(prefix), arg
    return json.loads(base64.b64decode(arg[len(prefix):]).decode("utf-8"))


def by_title(rows, start):
    return next((r for r in rows if r["title"].startswith(start)), None)


tmp = tempfile.mkdtemp(prefix="okr_screens_")
_env = dict(os.environ)
try:
    os.environ["okr_list_id"] = PID
    os.environ["cta_list_id"] = CTAP          # areas reads it at import
    for k in ("browse_ctx", "browse_back"):
        os.environ.pop(k, None)
    import cache                                           # noqa: E402
    cache.CACHE_DIR = os.path.join(tmp, "cache")
    import okr                                             # noqa: E402

    LOADS, SPAWNS = [], []

    def fake_load(api=None, v2=None, list_id=None):
        LOADS.append(list_id)
        return okr.Snapshot(okr.items_from(OPEN_ROWS + DONE_ROWS), "live",
                            "v1 open (fake); v2 completed (fake)", PID, NAME, True)

    okr.load = fake_load
    import okr_write as _real_okr_write                    # noqa: E402
    stub = types.ModuleType("okr_write")
    stub.spawn_heal = lambda debounce_s=300: SPAWNS.append(debounce_s) or True
    stub.code_ok = _real_okr_write.code_ok                 # pure: the title test
    stub.tag_pool = _real_okr_write.tag_pool               # pure: what retag accepts
    stub.Refusal = _real_okr_write.Refusal
    stub.import_source = _real_okr_write.import_source     # pure over the caches
    stub.planned = _real_okr_write.planned                 # pure: the dedupe rule
    stub.screen_of = _real_okr_write.screen_of             # pure: where an item shows
    stub._title_for = _real_okr_write._title_for           # pure: does a name read back
    stub.import_plan = _real_okr_write.import_plan         # pure: can it be added, and why not
    stub.remember_complete = _real_okr_write.remember_complete   # a cache write (temp dir)
    sys.modules["okr_write"] = stub

    import alfred                                          # noqa: E402
    _plain_output = alfred.output
    import browse                                          # noqa: E402
    import dateutil                                        # noqa: E402
    setup_cache(cache, browse._areas.PERIODIC_LIST_ID)

    def render(ctx, query="", back=""):
        """browse.main() as Alfred runs it: the ctx in env, the bar in $1."""
        os.environ["browse_ctx"] = ctx
        os.environ["browse_back"] = back
        sys.argv = ["browse.py", query]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            browse.main()
        out = json.loads(buf.getvalue())
        return out["items"]

    def raw(fn, ids, query=""):
        """The renderer's own list, dict identity intact."""
        os.environ["browse_ctx"], os.environ["browse_back"] = "", ""
        return fn(ids, query)

    # ── main menu ────────────────────────────────────────────────────────
    import main_menu                                       # noqa: E402
    row = next((r for r in main_menu.build_items() if r.get("uid") == "okr"), None)
    check("main menu: 🥅 OKRs row, arg ctx:okr (the leg's matchstring)",
          row is not None and row["title"] == "🥅 OKRs" and row["arg"] == "ctx:okr", row)
    check("main menu: no bare ALIASES word for the hub",
          "okr" not in browse.__dict__.get("ALIASES", {}) and
          browse.parse_ctx("okr")[0] == "folders")

    # ── parse_ctx: an OKR screen's bar is text ───────────────────────────
    os.environ["browse_ctx"] = f"ctx:okrlink:{KR2}"
    os.environ["browse_back"] = ""
    check("parse_ctx: 'tomorrow' typed on the link screen stays there",
          browse.parse_ctx("tomorrow") == ("okrlink", [KR2], "tomorrow"),
          browse.parse_ctx("tomorrow"))
    os.environ["browse_ctx"] = "ctx:okr"
    check("parse_ctx: 'today | review' typed on the hub stays a search",
          browse.parse_ctx("today | review") == ("okr", [], "today | review"))
    os.environ["browse_ctx"], os.environ["browse_back"] = "", "ctx:okr:o:o1"
    check("parse_ctx: after ⌃ back (browse_back only) the guard still holds",
          browse.parse_ctx("today")[0] == "okr")
    os.environ["browse_ctx"], os.environ["browse_back"] = "ctx:countdowns", ""
    check("parse_ctx: other screens keep their aliases",
          browse.parse_ctx("tomorrow")[0] == "smart")

    # ── the hub root ─────────────────────────────────────────────────────
    rows = render("ctx:okr")
    check_rows("root", rows)
    # ↪️ Carry-over shows only while the closing quarter leaves something
    # open - on the fixture that depends on the calendar, so the positional
    # checks read the rows without it (its own checks are under "carry")
    carry_row = next((r for r in rows if r.get("uid") == "okr-carry"), None)
    rows = [r for r in rows if r.get("uid") != "okr-carry"]
    titles = [r["title"] for r in rows]
    check("root: one live read, one heal spawn", len(LOADS) == 1 and len(SPAWNS) == 1,
          (LOADS, SPAWNS))
    check("root: head row first - list name, open count, no cache chip on a live read",
          titles[0] == f"{NAME} · 10 open" and "cache" not in rows[0]["subtitle"]
          and rows[0]["arg"] == f"open:ticktick:///webapp/#p/{PID}/tasks", rows[0])
    check("root: 📈 Pace second, ⏎ and ⌥ both open the pace screen",
          titles[1] == "📈 Pace" and rows[1]["arg"] == "xact:crmbrowse:ctx:okrpace"
          and rows[1]["mods"]["alt"]["variables"] == {"browse_ctx": "ctx:okrpace"})
    check("root: Y, loose O's, loose KR, unprefixed - open first, the closed O last",
          titles[2:] == ["🏔️ Productivity System", "🥅 Onboard TickTicks",
                         "🥅 Brand new thing", "🔑 Orphan deliverable", "▫️ Loose idea",
                         "✅ 🥅 Closed thing"], titles)
    y = rows[2]
    check("root: a Y row drills on ⏎ (xact:crmbrowse) and on ⌥ (variable hop)",
          y["arg"] == f"xact:crmbrowse:ctx:okr:y:{Y1}"
          and y["mods"]["alt"] == {"arg": "", "valid": True, "subtitle": "⤵️ Inside",
                                   "variables": {"browse_ctx": f"ctx:okr:y:{Y1}"}}, y)
    check("root: a Y aggregates its O's KRs - the completed one counts (live read)",
          "1/4 KRs" in y["subtitle"] and "behind 1d" in y["subtitle"], y["subtitle"])
    check("root: ⇧, ⌘⇧ and ⌥⇧ dead on a Y/O (scheduling is TickTick's, 2026-09-23)",
          y["mods"]["shift"]["valid"] is False and y["mods"]["cmd+shift"]["valid"] is False
          and y["mods"]["alt+shift"] == {"arg": "", "valid": False}, y["mods"])
    check("root: item rows are task rows (⌘ Actions on THE item, raw title)",
          y["variables"]["task_id"] == Y1 and y["variables"]["task_list_id"] == PID
          and y["variables"]["task_title"] == "🏔️ Y • Productivity System"
          and y["variables"]["item_type"] == "task" and y["mods"]["cmd"]["valid"] is True)
    closed = rows[-1]
    check("root: no row schedules - ⌥⇧ dead on every item",
          all(r["mods"]["alt+shift"]["valid"] is False for r in rows), closed["mods"])
    check("root: ⌃ goes back to the folders root",
          all(r["variables"]["browse_back"] == "ctx:folders" for r in rows))
    check("root: the live read is kept as okr_rows (the cache every other read uses)",
          (cache.get("okr_rows") or {}).get("list_id") == PID
          and len(cache.get("okr_rows")["rows"]) == len(OPEN_ROWS) + len(DONE_ROWS))
    oc = cache.get("okr_complete") or {}
    check("root: a COMPLETE live read is kept as okr_complete too (remember_complete)",
          oc.get("list_id") == PID
          and len(oc.get("rows") or []) == len(OPEN_ROWS) + len(DONE_ROWS), oc)

    # the fresh read is reused until a cache a write patches moves past it
    render("ctx:okr")
    check("root again: the fresh read is reused, no second network read",
          len(LOADS) == 1, LOADS)
    past = time.time() - 5
    os.utime(os.path.join(cache.CACHE_DIR, "okr_rows.json"), (past, past))
    cache.set("all_tasks", cache.get("all_tasks"))           # a write patched it
    render("ctx:okr")
    check("root again: a newer all_tasks (a ⇧ tick, a verb) forces a live read",
          len(LOADS) == 2, LOADS)
    old = time.time() - browse._OKR_FRESH_S - 5
    for key in ("okr_rows", "all_tasks", f"project_data_{PID}", "completed_tasks"):
        os.utime(os.path.join(cache.CACHE_DIR, f"{key}.json"), (old - 1, old - 1))
    os.utime(os.path.join(cache.CACHE_DIR, "okr_rows.json"), (old, old))
    render("ctx:okr")
    check("root again: an old read is not reused", len(LOADS) == 3, LOADS)

    # typed = cache only, flat search, no jump - with the last read too OLD
    # to reuse, so a typed bar that went live would show up as a load
    old = time.time() - browse._OKR_FRESH_S - 5
    for key in ("all_tasks", f"project_data_{PID}", "completed_tasks"):
        os.utime(os.path.join(cache.CACHE_DIR, f"{key}.json"), (old - 1, old - 1))
    os.utime(os.path.join(cache.CACHE_DIR, "okr_rows.json"), (old, old))
    n_loads, n_spawns = len(LOADS), len(SPAWNS)
    rows = render("ctx:okr", "publish")
    check_rows("root search", rows)
    check("root search: never reads the network, never spawns a heal",
          len(LOADS) == n_loads and len(SPAWNS) == n_spawns)
    check("root search: flat over every item, the KR names its O",
          rows and rows[0]["title"] == "🔑 Publish" and rows[0]["subtitle"].startswith("🥅 TickAL · "),
          [r["title"] for r in rows])
    rows = render("ctx:okr", "today")
    check("root search: 'today' searches (nothing) and offers to add it - never the smart list",
          [r["title"] for r in rows] == ["➕ New 🥅 objective · today",
                                         "➕ New 🏔️ year objective · today"]
          and all(r["variables"]["browse_back"] == "ctx:folders" for r in rows),
          [r["title"] for r in rows])
    rows = render("ctx:okr", "kickoff")
    check("root search: a completed KR is still found (okr_rows keeps it)",
          rows and rows[0]["title"] == "✅ 🔑 Kickoff", [r["title"] for r in rows])

    # ── one O ────────────────────────────────────────────────────────────
    rows = render(f"ctx:okr:o:{O1}")
    check_rows("O screen", rows)
    titles = [r["title"] for r in rows]
    check("O screen: head row (the O) then its KRs, open first, done last",
          titles == ["🥅 TickAL", "🔑 Goals wf 🔗", "🔑 Review", "🔑 Publish",
                     "✅ 🔑 Kickoff"], titles)
    head = rows[0]
    check("O screen: the head row opens the copy, it does not drill again",
          head["arg"] == f"open:ticktick:///webapp/#p/{PID}/tasks/{O1}"
          and head["mods"]["alt"]["valid"] is False, head)
    check("O screen: the O shows its WANTED span (its KRs), not the stale stored one",
          head["subtitle"].startswith(okr.span_txt(day(-12), day(12), TODAY)), head["subtitle"])
    kr1, kr2, kr4 = rows[1], rows[2], rows[4]
    check("O screen: ⏎ on a KR opens the copy in TickTick",
          kr2["arg"] == f"open:ticktick:///webapp/#p/{PID}/tasks/{KR2}")
    check("O screen: ⇧ ticks a KR (complete:pid:id:name)",
          kr2["mods"]["shift"]["arg"] == f"complete:{PID}:{KR2}:Review")
    check("O screen: ⇧ on a done KR reopens it",
          kr4["mods"]["shift"]["arg"] == f"uncomplete:{PID}:{KR4}:Kickoff")
    check("O screen: a KR past its end says late",
          "late 1d" in kr1["subtitle"], kr1["subtitle"])
    check("O screen: ⌥ on a KR linked to a task with subtasks = that task's subtasks",
          kr1["mods"]["alt"].get("variables") == {"browse_ctx": f"ctx:subtasks:{REALP}:{REALT}"}
          and kr1["mods"]["alt"]["valid"] is True, kr1["mods"]["alt"])
    check("O screen: ⌥ on an unlinked KR is dead", kr2["mods"]["alt"]["valid"] is False)
    check("O screen: ⌥⌘ copies the copy's link",
          kr2["mods"]["alt+cmd"]["arg"] == f"copy:ticktick:///webapp/#p/{PID}/tasks/{KR2}")
    check("O screen: ⌃ goes back to the O's Y",
          all(r["variables"]["browse_back"] == f"ctx:okr:y:{Y1}" for r in rows))
    rows = render(f"ctx:okr:o:{O2}")
    kr5 = by_title(rows, "🔑 Plan")
    check("O screen: ⌥ on a KR linked to a list = that list's tasks",
          kr5 and kr5["mods"]["alt"].get("variables") == {"browse_ctx": f"ctx:tasks:{LISTP}"})
    kr8 = by_title(rows, "🚫 🔑 Dropped")
    check("O screen: ⇧ on a won't-do KR reopens it through xact:wontdo_undo (drops the log row)",
          kr8 is not None and kr8["mods"]["shift"] == {
              "arg": f"xact:wontdo_undo:{PID}:{KR8}", "valid": True, "subtitle": "↩️ Reopen"}
          and kr8["arg"].startswith("open:")
          and "⇧↩️" in kr8["subtitle"] and "⇧✅" not in kr8["subtitle"], kr8)
    rows = render(f"ctx:okr:o:{O1}", "pub")
    check("O screen search: the head row steps aside, ⏎ hits the match, ➕ appended",
          [r["title"] for r in rows] == ["🔑 Publish", "➕ New 🔑 KR · pub · code TA"],
          [r["title"] for r in rows])
    rows = render("ctx:okr:o:nope")
    check("O screen: an id not in the plan says so",
          rows[0]["title"].startswith("Not in the plan") and rows[0]["valid"] is False)
    rows = render(f"ctx:okr:y:{Y1}")
    check("Y screen: head + its O", [r["title"] for r in rows] == ["🏔️ Productivity System", "🥅 TickAL"],
          [r["title"] for r in rows])

    # ── pace ─────────────────────────────────────────────────────────────
    rows = render("ctx:okrpace")
    check_rows("pace", rows)
    cap = next((r for r in rows if r.get("uid") == "okrp-capacity"), None)
    c = okr.capacity(okr.items_from(OPEN_ROWS + DONE_ROWS), TODAY)
    check("pace: ⚖️ capacity row last - KRs due next 4 wks vs ticked last 4, per week",
          cap is rows[-1] and cap["valid"] is False
          and cap["title"].startswith(f"⚖️ Capacity · plan {okr.rate_txt(c.planned, 4)} · "
                                      f"done {okr.rate_txt(c.done, 4)}")
          and f"{c.planned} KRs due" in cap["subtitle"], cap)
    rows = [r for r in rows if r.get("uid") != "okrp-capacity"]
    check("pace: four periods, quarter to day",
          [r["title"].split(" · ")[0] for r in rows]
          == ["🌓 Quarter", "🗓️ Month", "♻️ Week", "☀️ Day"], [r["title"] for r in rows])
    check("pace: ⏎ and ⌥ both open the period's plan, ⌃ back to the hub",
          all(r["arg"] == f"xact:crmbrowse:ctx:okrpace:{k}"
              and r["mods"]["alt"]["variables"] == {"browse_ctx": f"ctx:okrpace:{k}"}
              and r["variables"]["browse_back"] == "ctx:okr"
              for r, k in zip(rows, ("quarterly", "monthly", "weekly", "daily"))))
    day_row = rows[3]
    check("pace: the day counts the KRs overlapping today",
          "0/1 KRs" in day_row["subtitle"], day_row["subtitle"])
    rows = render("ctx:okrpace:daily")
    check_rows("pace: day plan", rows)
    check("pace: day plan = head + today's KR (named with its O)",
          [r["title"] for r in rows] == ["☀️ Day · " + __import__("periodic_model").title(
              __import__("periodic_model").period_for("daily", TODAY)), "🔑 Review"]
          and rows[1]["subtitle"].startswith("🥅 TickAL · "), [r["title"] for r in rows])
    check("pace: a plan's ⌃ goes back to the four periods",
          all(r["variables"]["browse_back"] == "ctx:okrpace" for r in rows))
    rows = render("ctx:okrpace:yearly")
    check("pace: an unknown period says so", rows[0]["title"].startswith("Unknown period"))

    # ── ↪️ carry-over (phase 5) ──────────────────────────────────────────
    import periodic_model as _pm                            # noqa: E402
    ALL = okr.items_from(OPEN_ROWS + DONE_ROWS)
    cq = okr.closing_quarter(TODAY)
    left = okr.carry_candidates(ALL, cq.end)
    check("carry: the hub row shows exactly while the closing quarter leaves something open",
          (carry_row is not None) == bool(left)
          and (carry_row is None or (
              carry_row["title"] == f"↪️ Carry-over · {browse._okr_q(cq)} · {len(left)} open"
              and carry_row["arg"] == "xact:crmbrowse:ctx:okrcarry"
              and carry_row["mods"]["alt"]["variables"] == {"browse_ctx": "ctx:okrcarry"})),
          (carry_row, [x.name for x in left]))
    # the hub row, whatever the calendar says: the closing quarter pinned far
    # ahead, so every dated open leaf is a leftover (review 2026-09-19)
    _cq = okr.closing_quarter
    okr.closing_quarter = lambda today=None, pinned=None: _cq(today, pinned or day(400))
    try:
        hub = render("ctx:okr")
    finally:
        okr.closing_quarter = _cq
    far0 = _pm.period_for("quarterly", day(400))
    crow = [r for r in hub if r.get("uid") == "okr-carry"]
    check_rows("hub carry row", crow)
    check("carry: the hub row, pinned - title, the clean-bar hop on ⏎ and ⌥, third on the hub",
          len(crow) == 1 and hub.index(crow[0]) == 2
          and crow[0]["title"] == f"↪️ Carry-over · {browse._okr_q(far0)} · 5 open"
          and crow[0]["arg"] == "xact:crmbrowse:ctx:okrcarry"
          and crow[0]["mods"]["alt"]["variables"] == {"browse_ctx": "ctx:okrcarry"}
          and crow[0]["variables"]["browse_back"] == "ctx:folders", crow)
    os.environ["browse_ctx"], os.environ["browse_back"] = "ctx:okrcarry", ""
    check("parse_ctx: 'today' typed on the carry-over stays a search (ctx:okr* guard)",
          browse.parse_ctx("today") == ("okrcarry", [], "today"), browse.parse_ctx("today"))
    far = _pm.period_for("quarterly", day(400))
    fk = far.start.isoformat()
    rows = render(f"ctx:okrcarry:{fk}")
    check_rows("carry", rows)
    titles = [r["title"] for r in rows]
    check("carry: a pinned quarter lists every open dated leaf ending by its end, end order",
          titles == [f"↪️ Carry-over · {browse._okr_q(far)} · 5 open", "🔑 Goals wf 🔗",
                     "🔑 Review", "🔑 Plan 🔗", "🔑 Publish", "🔑 Orphan deliverable"], titles)
    kr = rows[2]
    check("carry: ⏎ on a leftover opens its choices, the other chords as on the hub",
          kr["arg"] == f"xact:crmbrowse:ctx:okrcarry:{fk}:{KR2}" and "⏎↪️" in kr["subtitle"]
          and kr["mods"]["shift"]["arg"] == f"complete:{PID}:{KR2}:Review"
          and kr["mods"]["alt+shift"]["valid"] is False
          and kr["variables"]["task_id"] == KR2, kr)
    check("carry: ⌃ back to the hub", all(r["variables"]["browse_back"] == "ctx:okr" for r in rows))
    rows = render(f"ctx:okrcarry:{fk}", "orphan")
    check("carry search: filters the leftovers, the head steps aside",
          [r["title"] for r in rows] == ["🔑 Orphan deliverable"], [r["title"] for r in rows])
    rows = render(f"ctx:okrcarry:{fk}:{KR2}")
    check_rows("carry decision", rows)
    nq = _pm.next_period(far)
    check("carry decision: head, then open in TickTick · won't do · someday",
          rows[0]["title"].startswith("🔑 Review · ") and rows[0]["valid"] is False
          and "🥅 TickAL" in rows[0]["subtitle"]
          and [r["title"] for r in rows[1:]] == ["📆 Move it in TickTick",
                                                 "🚫 Won't do", "💤 Someday"],
          [r["title"] for r in rows])
    check("carry decision: carrying forward is a DRAG - the row opens the copy, moves nothing",
          rows[1]["arg"] == f"open:ticktick:///webapp/#p/{PID}/tasks/{KR2}"
          and browse._okr_q(nq) in rows[1]["subtitle"], rows[1])
    pays = {r["uid"]: b64(r["arg"], "xact:okr_carry:") for r in rows[2:]}
    back = f"ctx:okrcarry:{fk}"
    check("carry decision: one okr_carry payload each, landing back on the pinned list",
          pays == {"okrc-wontdo": {"id": KR2, "action": "wontdo", "back": back},
                   "okrc-someday": {"id": KR2, "action": "someday", "back": back}}, pays)
    check("carry decision: ⌃ back to the list it came from",
          all(r["variables"]["browse_back"] == back for r in rows))
    rows = render(f"ctx:okrcarry:{fk}:{KR4}")
    check("carry decision: a closed item says so, nothing to press",
          [r["title"] for r in rows][1:] == ["Closed already · nothing to decide"]
          and all(r["valid"] is False for r in rows), [r["title"] for r in rows])
    past = _pm.period_for("quarterly", day(-800))
    rows = render(f"ctx:okrcarry:{past.start.isoformat()}")
    check("carry: a quarter that left nothing open says it is clean",
          [r["title"] for r in rows][1:] == [f"Nothing left open · {browse._okr_q(past)} is clean"],
          [r["title"] for r in rows])
    rows = render("ctx:okrcarry:nonsense")
    check("carry: an unreadable pin falls back to the closing quarter",
          rows[0]["title"].startswith(f"↪️ Carry-over · {browse._okr_q(cq)} · "), rows[0]["title"])

    # ── add KRs ──────────────────────────────────────────────────────────
    rows = render(f"ctx:okraddkr:{O1}")
    check_rows("add KRs", rows)
    check("add KRs: empty bar = the prompt, the code the verb will use",
          rows[0]["title"] == "🔑 KRs under 🥅 TickAL · code TA" and rows[0]["valid"] is False,
          rows[0]["title"])
    rows = render(f"ctx:okraddkr:{O1}", "Draft | Review | today")
    p = b64(rows[0]["arg"], "xact:okr_addkr:")
    check("add KRs: ✅ first - three names, no override, back to the O",
          rows[0]["title"] == "✅ Add 3 KRs under 🥅 TickAL · code TA"
          and p == {"oid": O1, "names": ["Draft", "Review", "today"], "code": None,
                    "back": f"ctx:okr:o:{O1}"}, (rows[0]["title"], p))
    check("add KRs: ➕ Another KR puts one more pipe in the bar",
          rows[1]["title"] == "➕ Another KR" and rows[1]["valid"] is False
          and rows[1]["autocomplete"] == "Draft | Review | today | ", rows[1])
    rows = render(f"ctx:okraddkr:{O1}", "Draft | Review =XY")
    p = b64(rows[0]["arg"], "xact:okr_addkr:")
    check("add KRs: =XY overrides the code", p["code"] == "XY" and p["names"] == ["Draft", "Review"]
          and rows[0]["title"].endswith("· code XY"), (rows[0]["title"], p))
    check("add KRs: ➕ moves =XY to the front (the cursor sits at the end)",
          rows[1]["autocomplete"] == "=XY Draft | Review | ", rows[1]["autocomplete"])
    rows = render(f"ctx:okraddkr:{O1}", "=XY Draft | Review | Ship")
    p = b64(rows[0]["arg"], "xact:okr_addkr:")
    check("add KRs: ... and still reads it there",
          p["code"] == "XY" and p["names"] == ["Draft", "Review", "Ship"], p)
    # S2: an =XY the KR title would not read back is refused on the row
    rows = render(f"ctx:okraddkr:{O1}", "Draft | Review =xy")
    check("add KRs: =xy (lower-case first) = the ✅ row dead, the rule as subtitle",
          rows[0]["title"].startswith("✅ Add 2 KRs") and rows[0]["valid"] is False
          and rows[0]["arg"] == ""
          and rows[0]["subtitle"].startswith("Code: one word, capital first"), rows[0])
    check("add KRs: ... ➕ keeps the code in the bar to fix",
          rows[1]["autocomplete"] == "=xy Draft | Review | ", rows[1]["autocomplete"])
    rows = render(f"ctx:okraddkr:{O1}", "Draft =Xy")
    check("add KRs: a capital first is a code (=Xy)",
          rows[0]["valid"] is True and b64(rows[0]["arg"], "xact:okr_addkr:")["code"] == "Xy",
          rows[0])
    del stub.code_ok, stub._title_for
    try:
        rows = render(f"ctx:okraddkr:{O1}", "Draft =xy")
        check("add KRs: no writer layer = no code check (the verb decides)",
              rows[0]["valid"] is True, rows[0])
    finally:
        stub.code_ok, stub._title_for = _real_okr_write.code_ok, _real_okr_write._title_for
    del stub.code_ok
    try:
        rows = render(f"ctx:okraddkr:{O1}", "Draft =xy")
        check("add KRs: a code no title reads back is the CODE's fault, not the name's",
              rows[0]["valid"] is False
              and rows[0]["subtitle"].startswith("Code: one word, capital first"), rows[0])
    finally:
        stub.code_ok = _real_okr_write.code_ok
    rows = render(f"ctx:okraddkr:{O1}", "Draft | Trip - USA")
    check("add KRs A2: under a coded O every name reads back (live)",
          rows[0]["valid"] is True, rows[0])
    rows = render(f"ctx:okraddkr:{O4}", "First")
    check("add KRs: an O with no code gets the proposal, flagged as new",
          rows[0]["title"] == "✅ Add 1 KR under 🥅 Brand new thing · code BNT · new 🏷️",
          rows[0]["title"])
    rows = render(f"ctx:okraddkr:{O2}")
    check("add KRs: the O's existing KR code is kept (OT)", "code OT" in rows[0]["title"],
          rows[0]["title"])
    rows = render(f"ctx:okraddkr:{O3}", "More")
    check("add KRs: refused under a closed O",
          rows[0]["title"] == "🥅 Closed thing is closed" and rows[0]["valid"] is False)
    rows = render(f"ctx:okraddkr:{KR2}", "x")
    check("add KRs: refused under anything but an O",
          rows[0]["title"] == "KRs go under an objective" and rows[0]["valid"] is False)

    # ── link ─────────────────────────────────────────────────────────────
    rows = render(f"ctx:okrlink:{KR2}")
    check_rows("link", rows)
    titles = [r["title"] for r in rows]
    check("link: head names the item and what it links now",
          titles[0] == "🔗 🔑 Review" and "text only" in rows[0]["subtitle"], rows[0])
    joined = " | ".join(titles)
    check("link: open tasks, subtasks and notes from other lists are offered",
          "Goals workflow (the real one)" in joined and "A step of it" in joined
          and "Reading notes" in joined and "Buy stamps" in joined, titles)
    check("link: never the OKR list itself or the periodic list",
          not any(m in t for t in titles[1:] for m in ("Y •", "O •", "KR •", "☀️ 2026-09-18"))
          and f"📂 {NAME}" not in titles, titles)
    check("link: lists offered (never a smart list)",
          "📂 Plan list" in titles and "📂 Smart" not in titles, titles)
    check("link: a KR's picker leads with tasks",
          titles.index("📂 Real list") > titles.index(next(t for t in titles if "Goals workflow" in t)))
    real = by_title(rows, "Goals workflow")
    p = b64(real["arg"], "xact:okr_link:")
    check("link: a task row = to task, its REAL list id, back to the O",
          p == {"id": KR2, "to": "task", "pid": REALP, "tid": REALT, "back": f"ctx:okr:o:{O1}"}, p)
    check("link: a candidate row is a task row (⌘ Actions on it), ⌘⇧ and ⌥⇧ dead",
          real["mods"]["cmd"]["valid"] is True and real["variables"]["task_id"] == REALT
          and real["mods"]["cmd+shift"]["valid"] is False
          and real["mods"]["alt+shift"]["valid"] is False)
    lrow = by_title(rows, "📂 Plan list")
    check("link: a list row = to list, no tid",
          b64(lrow["arg"], "xact:okr_link:") == {"id": KR2, "to": "list", "pid": LISTP,
                                                 "tid": None, "back": f"ctx:okr:o:{O1}"})
    rows = render(f"ctx:okrlink:{O1}")
    check("link: an O's picker leads with lists",
          rows[1]["title"].startswith("📂 "), [r["title"] for r in rows][:3])
    rows = render(f"ctx:okrlink:{KR2}", "stamps")
    check("link: typed = fuzzy over tasks and lists",
          rows[0]["title"].startswith("Buy stamps"), [r["title"] for r in rows])

    # ── tag ──────────────────────────────────────────────────────────────
    rows = render(f"ctx:okrtag:{O1}")
    check_rows("tag", rows)
    titles = [r["title"] for r in rows]
    check("tag: the closed pool - area children, then the tags the list uses",
          titles[1:] == ["🏷️ 1️⃣Work", "🏷️ 2️⃣Personal", "🏷️ 💼TickAL  ✓", "🏷️ 💼OnboardTT"],
          titles)
    check("tag: no ➕ create row", not any("➕" in t for t in titles))
    check("tag: a tag only a KR carries is not offered (retag would refuse it)",
          not any("solo" in t for t in titles), titles)
    p = b64(rows[1]["arg"], "xact:okr_tag:")
    check("tag: payload = the tag NAME, back to the Y", p == {"id": O1, "tag": "1️⃣work",
                                                            "back": f"ctx:okr:y:{Y1}"}, p)
    check("tag: an O says its KRs follow", "KRs follow" in rows[1]["subtitle"])
    rows = render(f"ctx:okrtag:{O1}", "pers")
    check("tag: typed = filtered", [r["title"] for r in rows] == ["🏷️ 2️⃣Personal"])


    # ── phase 3: 🥅 import (ctx:okrimport) ───────────────────────────────
    n_loads, n_spawns = len(LOADS), len(SPAWNS)
    rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}")
    check_rows("import task", rows)
    check("import: reads the cache only, never spawns a heal",
          len(LOADS) == n_loads and len(SPAWNS) == n_spawns, (LOADS, SPAWNS))
    titles = [r["title"] for r in rows]
    check("import task: head, then KR rows first (a task plans a KR), running O first",
          titles == ["↗️ Buy stamps",
                     "🔑 KR under 🥅 TickAL · code TA",
                     "🔑 KR under 🥅 Onboard TickTicks · code OT",
                     "🔑 KR under 🥅 Brand new thing · code BNT",
                     "🥅 New objective · code BS",
                     "🥅 New objective under 🏔️ Productivity System",
                     "🏔️ New year objective"], titles)
    check("import task: head = where it lives, ⏎ opens the ORIGINAL",
          rows[0]["subtitle"].startswith("📂 Errands")
          and rows[0]["arg"] == f"open:ticktick:///webapp/#p/{OTHERP}/tasks/{OTHERT}", rows[0])
    check("import: ⌃ backs to the hub", all(r["variables"]["browse_back"] == "ctx:okr" for r in rows))
    LINK_T = {"to": "task", "pid": OTHERP, "tid": OTHERT}
    p = b64(rows[1]["arg"], "xact:okr_add:")
    check("import task: KR row = kind KR under the O, the O's code (none sent), back to the O",
          p == {"kind": "KR", "parent": O1, "names": ["Buy stamps"], "code": None,
                "link": LINK_T, "then": None, "back": f"ctx:okr:o:{O1}"}, p)
    check("import task: a KR row names the O's Y and its span",
          rows[1]["subtitle"].startswith("🏔️ Productivity System · "), rows[1]["subtitle"])
    check("import task: an O with no code yet says its proposal is new",
          "new 🏷️" in rows[3]["subtitle"] and "new 🏷️" not in rows[1]["subtitle"])
    p = b64(rows[4]["arg"], "xact:okr_add:")
    check("import task: New objective = kind O, no parent, tag picker next, back to the hub",
          p == {"kind": "O", "parent": None, "names": ["Buy stamps"], "code": None,
                "link": LINK_T, "then": "tag", "back": "ctx:okr"}, p)
    p = b64(rows[5]["arg"], "xact:okr_add:")
    check("import task: New objective under a Y = parent the Y, back to the Y",
          p["kind"] == "O" and p["parent"] == Y1 and p["then"] == "tag"
          and p["back"] == f"ctx:okr:y:{Y1}" and rows[5]["subtitle"].startswith("code BS"), p)
    p = b64(rows[6]["arg"], "xact:okr_add:")
    check("import task: New year objective = kind Y, no code, tag picker next",
          p == {"kind": "Y", "parent": None, "names": ["Buy stamps"], "code": None,
                "link": LINK_T, "then": "tag", "back": "ctx:okr"}, p)
    check("import: the closed O is never offered", not any("Closed thing" in t for t in titles))

    rows = render(f"ctx:okrimport:list:{PROJP}:-")
    check_rows("import list", rows)
    titles = [r["title"] for r in rows]
    check("import list: named without its 💼P prefix, objective rows first",
          titles[:4] == ["↗️ Website", "🥅 New objective · code W",
                         "🥅 New objective under 🏔️ Productivity System", "🏔️ New year objective"]
          and titles[4].startswith("🔑 KR under 🥅 TickAL"), titles)
    check("import list: the head says it links the project's 📌 CTA",
          rows[0]["subtitle"].startswith("📂 List · links its 📌 CTA")
          and rows[0]["arg"] == f"open:ticktick:///webapp/#p/{PROJP}/tasks", rows[0])
    p = b64(rows[1]["arg"], "xact:okr_add:")
    check("import list: the payload links the CTA TASK, not the list",
          p["link"] == {"to": "task", "pid": CTAP, "tid": CTAT} and p["names"] == ["Website"], p)
    rows = render(f"ctx:okrimport:list:{OTHERP}:-")
    p = b64(rows[1]["arg"], "xact:okr_add:")
    check("import list: no CTA = the list itself",
          p["link"] == {"to": "list", "pid": OTHERP, "tid": None} and p["names"] == ["Errands"], p)
    rows = render(f"ctx:okrimport:task:{CTAP}:{CTAT}")
    check("import CTA task: named by its label, objective rows first",
          rows[0]["title"] == "↗️ Website" and rows[1]["title"].startswith("🥅 New objective")
          and b64(rows[1]["arg"], "xact:okr_add:")["link"] == {"to": "task", "pid": CTAP, "tid": CTAT},
          [r["title"] for r in rows])
    rows = render(f"ctx:okrimport:note:{NOTEP}:{NOTET}")
    check("import note: a note is a KR like a task",
          rows[1]["title"].startswith("🔑 KR under")
          and b64(rows[1]["arg"], "xact:okr_add:")["link"] == {"to": "task", "pid": NOTEP, "tid": NOTET},
          [r["title"] for r in rows])

    # already planned: one dead row, one that opens it - never a ⏎ that adds
    rows = render(f"ctx:okrimport:task:{REALP}:{REALT}")
    check_rows("import planned", rows)
    check("import planned task: head, dead 'In the plan', a row that opens its O",
          [r["title"] for r in rows] == ["↗️ Goals workflow (the real one)",
                                         "In the plan · 🔑 Goals wf", "⤵️ Open it · 🥅 TickAL"]
          and rows[1]["valid"] is False and not any(r["arg"].startswith("xact:okr_add") for r in rows),
          [r["title"] for r in rows])
    check("import planned: ⏎ and ⌥ both open the screen that lists it",
          rows[2]["arg"] == f"xact:crmbrowse:ctx:okr:o:{O1}"
          and rows[2]["mods"]["alt"]["variables"] == {"browse_ctx": f"ctx:okr:o:{O1}"}, rows[2])
    rows = render(f"ctx:okrimport:list:{LISTP}:-")
    check("import planned list: a KR already links the list",
          rows[1]["title"] == "In the plan · 🔑 Plan"
          and rows[2]["arg"] == f"xact:crmbrowse:ctx:okr:o:{O2}", [r["title"] for r in rows])

    # refusals: one dead row each
    for why, ctx, want in (
            ("a planning copy (the writer's words)", f"ctx:okrimport:task:{PID}:{KR2}",
             "🥅 That is a planning copy · add the original"),
            ("an unprefixed item of the plan list", f"ctx:okrimport:task:{PID}:{LOOSE}",
             "🥅 Already in the plan list · give it a 🏔️ / 🥅 / 🔑 prefix"),
            ("the plan list itself", f"ctx:okrimport:list:{PID}:-",
             "🥅 That is the plan list · add the real one"),
            ("no task id", f"ctx:okrimport:task:{OTHERP}", "Nothing to import"),
            ("an unknown kind", f"ctx:okrimport:habit:{OTHERP}:x", "Nothing to import"),
            ("a task not cached", f"ctx:okrimport:task:{OTHERP}:ffffffffffffffffffffffff",
             "🥅 Not cached yet · sync or reopen")):
        rows = render(ctx)
        check(f"import refused: {why} = one dead row",
              len(rows) == 1 and rows[0]["title"] == want and rows[0]["valid"] is False
              and rows[0]["variables"]["browse_back"] == "ctx:okr", rows)
    if browse._areas.PERIODIC_LIST_ID:
        rows = render(f"ctx:okrimport:task:{browse._areas.PERIODIC_LIST_ID}:pn1")
        check("import refused: a periodic note, in the writer's own words (import_source)",
              rows[0]["title"] == "🥅 Periodic notes stay out · add the task it names"
              and rows[0]["valid"] is False, rows[0])

    # typed: a filter over the targets, "=XY" for a NEW objective's code
    rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}", "onboard")
    check("import typed: filters by the target's name, the head steps aside",
          rows[0]["title"] == "🔑 KR under 🥅 Onboard TickTicks · code OT", [r["title"] for r in rows])
    rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}", "year")
    check("import typed: 'year' finds the year objective row",
          rows[0]["title"] == "🏔️ New year objective", [r["title"] for r in rows])
    rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}", "=XY")
    no = by_title(rows, "🥅 New objective ·")
    uy = by_title(rows, "🥅 New objective under")
    kr = by_title(rows, "🔑 KR under 🥅 TickAL")
    check("import =XY: the new objectives take it, the head steps aside",
          rows[0]["title"] != "↗️ Buy stamps" and no["title"] == "🥅 New objective · code XY"
          and b64(no["arg"], "xact:okr_add:")["code"] == "XY"
          and uy["subtitle"].startswith("code XY") and b64(uy["arg"], "xact:okr_add:")["code"] == "XY",
          (no, uy))
    check("import =XY: a KR keeps its O's code (none sent)",
          b64(kr["arg"], "xact:okr_add:")["code"] is None and kr["title"].endswith("code TA"))
    rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}", "=xy")
    no = by_title(rows, "🥅 New objective ·")
    check("import =xy: the new-objective rows are dead, the rule says why",
          no["valid"] is False and no["arg"] == ""
          and no["subtitle"].startswith("Code: one word, capital first")
          and by_title(rows, "🥅 New objective under")["valid"] is False
          and by_title(rows, "🏔️ New year")["valid"] is True
          and by_title(rows, "🔑 KR under")["valid"] is True, no)
    rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}", "zzzz")
    check("import typed: nothing matching says so",
          len(rows) == 1 and rows[0]["valid"] is False and "No objective matching" in rows[0]["title"])

    # the writer layer without import_plan / import_source / planned: the
    # screen still works (its fallback asks the payload link ONCE)
    _ip, _imp, _pl = stub.import_plan, stub.import_source, stub.planned
    del stub.import_plan, stub.import_source, stub.planned
    try:
        rows = render(f"ctx:okrimport:list:{PROJP}:-")
        p = b64(rows[1]["arg"], "xact:okr_add:")
        check("import fallback: the plain name, the list itself (no CTA swap)",
              rows[0]["title"] == "↗️ Website" and p["link"] == {"to": "list", "pid": PROJP, "tid": None},
              (rows[0]["title"], p))
        rows = render(f"ctx:okrimport:task:{CTAP}:{CTAT}")
        check("import fallback: the CTA lead and 🔗 are dropped, a CTA task plans an O",
              rows[0]["title"] == "↗️ Website" and rows[1]["title"].startswith("🥅 New objective"),
              [r["title"] for r in rows])
        rows = render(f"ctx:okrimport:task:{REALP}:{REALT}")
        check("import fallback: the dedupe still holds (exact task)",
              rows[1]["title"] == "In the plan · 🔑 Goals wf", [r["title"] for r in rows])
        rows = render(f"ctx:okrimport:task:{PID}:{KR2}")
        check("import fallback: a planning copy is still refused, in the writer's words",
              len(rows) == 1 and rows[0]["valid"] is False
              and rows[0]["title"] == "🥅 That is a planning copy · add the original",
              [r["title"] for r in rows])
        rows = render(f"ctx:okrimport:list:{PID}:-")
        check("import fallback: ... and the plan list itself",
              len(rows) == 1 and rows[0]["title"] == "🥅 That is the plan list · add the real one",
              [r["title"] for r in rows])
    finally:
        stub.import_plan, stub.import_source, stub.planned = _ip, _imp, _pl

    # ── phase 3: typed ➕ rows on the hub (text only) ─────────────────────
    rows = render("ctx:okr", "Launch podcast")
    check_rows("root ➕", rows)
    titles = [r["title"] for r in rows]
    check("root ➕: both rows APPENDED after the search results",
          titles[-2:] == ["➕ New 🥅 objective · Launch podcast",
                          "➕ New 🏔️ year objective · Launch podcast"], titles)
    o_row, y_row = rows[-2], rows[-1]
    check("root ➕: New objective = kind O, text only, tag picker next, back to the hub",
          b64(o_row["arg"], "xact:okr_add:") == {
              "kind": "O", "parent": None, "names": ["Launch podcast"], "code": None,
              "link": None, "then": "tag", "back": "ctx:okr"}
          and o_row["subtitle"].startswith("code LP · then 🏷"), o_row)
    check("root ➕: New year objective = kind Y",
          b64(y_row["arg"], "xact:okr_add:") == {
              "kind": "Y", "parent": None, "names": ["Launch podcast"], "code": None,
              "link": None, "then": "tag", "back": "ctx:okr"}, y_row)
    check("root ➕: Tab puts one more pipe in the bar (rapid fire)",
          o_row["autocomplete"] == "Launch podcast | " and y_row["autocomplete"] == "Launch podcast | ")
    rows = render("ctx:okr", "publish")
    check("root ➕: a search still hits its match first",
          rows[0]["title"] == "🔑 Publish" and rows[-1]["title"].startswith("➕ New 🏔️"),
          [r["title"] for r in rows])
    rows = render("ctx:okr", "Alpha | Beta")
    o_row = by_title(rows, "➕ New 🥅")
    p = b64(o_row["arg"], "xact:okr_add:")
    check("root ➕: a pipe = siblings, no tag picker, each its own proposal",
          o_row["title"] == "➕ New 🥅 objectives · Alpha · Beta"
          and p["names"] == ["Alpha", "Beta"] and p["code"] is None and p["then"] is None
          and o_row["subtitle"].startswith("codes A · B · 2 siblings")
          and o_row["autocomplete"] == "Alpha | Beta | ", (o_row, p))
    # A1: "=XY" names ONE objective (add_items refuses it on several)
    rows = render("ctx:okr", "Alpha | Beta =XY")
    o_row, y_row = by_title(rows, "➕ New 🥅"), by_title(rows, "➕ New 🏔️")
    check("root ➕ A1: =XY on two objectives = the O row dead, the rule as subtitle",
          o_row["valid"] is False and o_row["arg"] == ""
          and o_row["subtitle"].startswith("=XY codes ONE objective  |"), o_row)
    p = b64(y_row["arg"], "xact:okr_add:")
    check("root ➕ A1: ... the Y row ignores the code and stays live",
          y_row["valid"] is True and p["names"] == ["Alpha", "Beta"] and p["code"] is None
          and y_row["autocomplete"] == "=XY Alpha | Beta | ", (y_row, p))
    rows = render("ctx:okr", "Alpha =XY")
    o_row = by_title(rows, "➕ New 🥅")
    p = b64(o_row["arg"], "xact:okr_add:")
    check("root ➕ A1: =XY on ONE objective is its code, tag picker next",
          o_row["valid"] is True and p["code"] == "XY" and p["then"] == "tag"
          and o_row["subtitle"].startswith("code XY · then 🏷"), (o_row, p))
    rows = render(f"ctx:okr:y:{Y1}", "Alpha | Beta =XY")
    r = by_title(rows, "➕ New 🥅")
    check("Y ➕ A1: =XY on two objectives under a Y = dead, the rule as subtitle",
          r["valid"] is False and r["subtitle"].startswith("=XY codes ONE objective"), r)
    rows = render(f"ctx:okr:o:{O1}", "Draft | Ship =XY")
    r = by_title(rows, "➕ New 🔑")
    check("O ➕ A1: KRs share one code, =XY on several stays live",
          r["valid"] is True and b64(r["arg"], "xact:okr_add:")["code"] == "XY", r)
    rows = render("ctx:okr", "=xy Gamma")
    check("root ➕: =xy kills the objective row, not the year one",
          by_title(rows, "➕ New 🥅")["valid"] is False
          and by_title(rows, "➕ New 🏔️")["valid"] is True)
    rows = render("ctx:okr", "=xy Gamma | Delta")
    check("root ➕: a bad code outranks the one-objective rule (the verb's order)",
          by_title(rows, "➕ New 🥅")["subtitle"].startswith("Code: one word, capital first"))

    # A2: a name whose title would read as a code is never a live ⏎ (the
    # verb skips it): okr_write._title_for, the verb's own test
    for q, who in (("Trip - USA", "an all-caps tail"), ("Plan - Monday", "any tail on a Y/O"),
                   ("Fish | Trip - USA", "one bad name of several")):
        rows = render("ctx:okr", q)
        o_row, y_row = by_title(rows, "➕ New 🥅"), by_title(rows, "➕ New 🏔️")
        bad = "Plan - Monday" if "Monday" in q else "Trip - USA"
        check(f"root ➕ A2: {who} = both rows dead, the name said",
              o_row["valid"] is False and y_row["valid"] is False
              and o_row["arg"] == "" and y_row["arg"] == ""
              and o_row["subtitle"].startswith(f"'{bad}' reads as a code · reword")
              and y_row["subtitle"].startswith(f"'{bad}' reads as a code · reword"), (o_row, y_row))
    rows = render(f"ctx:okr:y:{Y1}", "Trip - USA")
    check("Y ➕ A2: an objective that reads as a code = dead",
          by_title(rows, "➕ New 🥅")["valid"] is False)
    rows = render(f"ctx:okr:o:{O1}", "Trip - USA")
    r = by_title(rows, "➕ New 🔑")
    check("O ➕ A2: under a coded O the name reads back (' - TA' follows it)",
          r["valid"] is True and b64(r["arg"], "xact:okr_add:")["names"] == ["Trip - USA"], r)
    del stub._title_for
    try:
        rows = render("ctx:okr", "Trip - USA")
        check("root ➕ A2: no writer layer = no name check (the verb decides)",
              by_title(rows, "➕ New 🥅")["valid"] is True)
    finally:
        stub._title_for = _real_okr_write._title_for

    # A3: one more pipe goes at the END, never cut at a "token"
    for q, want in (("Fish & Chips", "Fish & Chips | "),
                    ("Read 20 books / year", "Read 20 books / year | "),
                    ("Draft |", "Draft | "), ("=XY Fish & Chips", "=XY Fish & Chips | ")):
        rows = render("ctx:okr", q)
        r = by_title(rows, "➕ New 🏔️")
        check(f"root ➕ A3: Tab on {q!r} = {want!r}", r["autocomplete"] == want, r["autocomplete"])
    rows = render("ctx:okr", "Fish & Chips | Read 20 books / year")
    p = b64(by_title(rows, "➕ New 🏔️")["arg"], "xact:okr_add:")
    check("root ➕ A3: & and / stay inside their names",
          p["names"] == ["Fish & Chips", "Read 20 books / year"], p)
    rows = render(f"ctx:okraddkr:{O1}", "Fish & Chips =XY")
    check("add KRs A3: ➕ Another KR keeps & inside the name",
          rows[1]["autocomplete"] == "=XY Fish & Chips | ", rows[1]["autocomplete"])
    check("A3: empty segments and trailing pipes fold away",
          browse._okr_more("a |  | ", None) == "a | " and browse._okr_more("", "XY") == "=XY ")

    # A4: a proposal no title reads back is no code at all (add_items drops it)
    check("A4: _okr_propose = propose_code gated by code_ok",
          browse._okr_propose("Launch podcast") == "LP" and browse._okr_propose("学习 计划") is None
          and browse._okr_propose("!!!") is None)
    _ok = stub.code_ok
    del stub.code_ok
    try:
        check("A4: no writer layer = the plain proposal",
              browse._okr_propose("学习 计划") == "学计")
    finally:
        stub.code_ok = _ok
    rows = render("ctx:okr", "学习 计划")
    o_row = by_title(rows, "➕ New 🥅")
    check("root ➕ A4: a caseless name = 'no code', never a code the verb drops",
          o_row["valid"] is True and o_row["subtitle"].startswith("no code · then 🏷")
          and b64(o_row["arg"], "xact:okr_add:")["code"] is None, o_row)
    cj = okr.items_from([T("o9", "🥅 O • 学习 计划")])
    rs = browse._okr_plus_rows(cj[0], "Draft", cj)
    check("O ➕ A4: an O whose proposal would not read back = 'no code', no new 🏷️",
          rs[0]["title"] == "➕ New 🔑 KR · Draft · no code" and "new 🏷️" not in rs[0]["subtitle"]
          and rs[0]["valid"] is True, rs[0])
    rs = browse._okr_plus_rows(cj[0], "Trip - USA", cj)
    check("O ➕ A2: a code-less KR whose name ends ' - USA' = dead",
          rs[0]["valid"] is False and rs[0]["subtitle"].startswith("'Trip - USA' reads as a code"),
          rs[0])
    rs = browse._okr_plus_rows(cj[0], "Call Anna - Monday", cj)
    check("O ➕ A2: ... 'Call Anna - Monday' reads back (settle folds Monday in)",
          rs[0]["valid"] is True, rs[0])
    rows = render(f"ctx:okr:y:{Y1}", "Health")
    check_rows("Y ➕", rows)
    r = by_title(rows, "➕ New 🥅")
    check("Y ➕: New objective under the Y, tag picker next, back to the Y",
          r is not None and r["title"] == "➕ New 🥅 objective under Productivity System · Health"
          and b64(r["arg"], "xact:okr_add:") == {
              "kind": "O", "parent": Y1, "names": ["Health"], "code": None, "link": None,
              "then": "tag", "back": f"ctx:okr:y:{Y1}"}, r)
    rows = render(f"ctx:okr:o:{O1}", "Draft | Ship")
    check_rows("O ➕", rows)
    r = by_title(rows, "➕ New 🔑")
    check("O ➕: KRs under the O, its code shown, none sent, back to the O",
          r is not None and r["title"] == "➕ New 🔑 KRs · Draft · Ship · code TA"
          and b64(r["arg"], "xact:okr_add:") == {
              "kind": "KR", "parent": O1, "names": ["Draft", "Ship"], "code": None, "link": None,
              "then": None, "back": f"ctx:okr:o:{O1}"}
          and r["autocomplete"] == "Draft | Ship | ", r)
    rows = render(f"ctx:okr:o:{O1}", "Draft =XY")
    r = by_title(rows, "➕ New 🔑")
    check("O ➕: =XY overrides the code", r["title"].endswith("code XY")
          and b64(r["arg"], "xact:okr_add:")["code"] == "XY", r)
    rows = render(f"ctx:okr:o:{O1}", "Draft =xy")
    check("O ➕: =xy = dead row", by_title(rows, "➕ New 🔑")["valid"] is False)
    rows = render(f"ctx:okr:o:{O4}", "First")
    r = by_title(rows, "➕ New 🔑")
    check("O ➕: an O with no code gets the proposal, flagged new",
          r["title"] == "➕ New 🔑 KR · First · code BNT" and "new 🏷️" in r["subtitle"], r)
    # A6: a typed name on a CLOSED screen says why, never 'Nothing matching'
    rows = render(f"ctx:okr:o:{O3}", "More")
    check_rows("closed O ➕", rows)
    check("O ➕ A6: a closed O takes nothing new, and says so",
          [x["title"] for x in rows] == ["Closed · reopen it first"] and rows[0]["valid"] is False
          and rows[0]["subtitle"].startswith("🥅 Closed thing takes nothing new")
          and rows[0]["variables"]["browse_back"] == "ctx:okr", rows)
    rows = render(f"ctx:okr:o:{O3}", "=XY")
    check("O ➕ A6: a bar that is only a code names nothing (no closed row)",
          [x["title"] for x in rows] == ['Nothing matching "=XY"'], [x["title"] for x in rows])
    rows = render(f"ctx:okr:o:{O4}")
    check("O screen: an empty O says to type", rows[1]["subtitle"].startswith("Type a name to add"),
          rows[1])

    # ── no screen shares a mods dict between two rows ────────────────────
    for screen, fn, ids, q in (
            ("root", browse.render_okr, [], ""), ("root search", browse.render_okr, [], "o"),
            ("O screen", browse.render_okr, ["o", O1], ""),
            ("pace", browse.render_okrpace, [], ""), ("pace plan", browse.render_okrpace, ["monthly"], ""),
            ("add KRs", browse.render_okraddkr, [O1], "a | b"),
            ("link", browse.render_okrlink, [KR2], ""), ("tag", browse.render_okrtag, [O1], ""),
            ("import", browse.render_okrimport, ["task", OTHERP, OTHERT], ""),
            ("import planned", browse.render_okrimport, ["task", REALP, REALT], ""),
            ("root ➕", browse.render_okr, [], "a | b"),
            ("O ➕", browse.render_okr, ["o", O1], "a | b")):
        check_shared(screen, raw(fn, ids, q))

    # ── switched off ─────────────────────────────────────────────────────
    os.environ["okr_list_id"] = ""
    n_spawns = len(SPAWNS)
    rows = render("ctx:okr")
    check_rows("off", rows)
    check("off: a blank okr_list_id = the setup row, no heal",
          rows[0]["title"] == "🥅 OKRs need a list" and len(SPAWNS) == n_spawns)
    os.environ["okr_list_id"] = PID

    # ── ⌘ Actions ────────────────────────────────────────────────────────
    import actions                                         # noqa: E402
    _stamped = alfred.output
    alfred.output = _plain_output          # browse above must not be back-stamped
    actions.fx_session = lambda: None      # no running focus leaks into the menu

    def menu(tid, pid, title, itype="task"):
        env = {"task_id": tid, "task_list_id": pid, "list_id": pid, "section_id": "",
               "task_title": title, "item_type": itype}
        os.environ.update(env)
        sys.argv = ["actions.py", ""]
        alfred.output = _stamped
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                actions.main()
        finally:
            alfred.output = _plain_output
        return json.loads(buf.getvalue())["items"]

    PRUNED = ("☀️ Add to today", "🌙 Add to tomorrow", "☀️ Make day goal", "📑 Duplicate…",
              "🔔 Reminder", "🎯 Focus", "🅿️ Add to buffer", "🔃 Convert", "☑️ TickTick Internals",
              "➕ Add task", "🎯 Merge/Stage for Focus", "✔️ Complete")

    def subtitles(items):
        return {i["subtitle"] for i in items}

    items = menu(KR2, PID, "🔑 KR • Review - TA")
    titles = [i["title"] for i in items]
    op = titles.index("↗️ Open")
    check("Actions KR: entity rows first, right after Open (no 📅 Schedule - TickTick's)",
          titles[op + 1:op + 4] == ["🔗 Link…", "🏷 Tag…", "✔️ Done"], titles)
    args = {i["title"]: i["arg"] for i in items}
    check("Actions KR: the drills ride xact:crmbrowse to the hub's own screens",
          "📅 Schedule…" not in args
          and args["🔗 Link…"] == f"xact:crmbrowse:ctx:okrlink:{KR2}"
          and args["🏷 Tag…"] == f"xact:crmbrowse:ctx:okrtag:{KR2}"
          and args["✔️ Done"].startswith(f"complete:{PID}:{KR2}:"), args)
    check("Actions KR: the date-moving and pinning verbs are pruned",
          not [t for t in titles if t.startswith(PRUNED)], [t for t in titles if t.startswith(PRUNED)])
    check("Actions KR: no generic Tags… / Schedule… / Priority… rows",
          not ({"Tags…", "Schedule…", "Priority…"} & subtitles(items)), subtitles(items))
    check("Actions KR: no 📌 CTA row on a planning copy",
          not any(i["arg"].startswith("cta:") for i in items))
    check("Actions KR: 📝 Note and 🚫 Won't do stay",
          "📝 Note" in titles and "🚫 Won't do" in titles, titles)
    check("Actions KR: no Add KRs (that is an O's)", "🔑 Add KRs" not in titles)

    items = menu(O1, PID, "🥅 O • TickAL")
    titles = [i["title"] for i in items]
    check("Actions O: 🔑 Add KRs, no ✔️ Done",
          "🔑 Add KRs" in titles and "✔️ Done" not in titles, titles)
    ak = next(i for i in items if i["title"] == "🔑 Add KRs")
    check("Actions O: Add KRs opens the pipe screen",
          ak["arg"] == f"xact:crmbrowse:ctx:okraddkr:{O1}")
    br = next((i for i in items if i["title"] == "⤵️ Browse subtasks"), None)
    check("Actions O: ⤵️ Browse subtasks lands on the hub's O screen",
          br is not None and br["arg"] == "browse"
          and br["variables"]["browse_ctx"] == f"ctx:okr:o:{O1}", br)
    tg = next(i for i in items if i["title"] == "🏷 Tag…")
    check("Actions O: the tag row shows the tag and says the KRs follow",
          tg["subtitle"] == "#💼TickAL · KRs follow", tg["subtitle"])

    items = menu(KR4, PID, "🔑 KR • Kickoff - TA")
    titles = [i["title"] for i in items]
    check("Actions done KR (not in the open cache): no Schedule, no Done, no Won't do",
          "📅 Schedule…" not in titles and "✔️ Done" not in titles
          and "🚫 Won't do" not in titles and "🔗 Link…" in titles, titles)

    items = menu(LOOSE, PID, "Loose idea")
    titles = [i["title"] for i in items]
    check("Actions: an unprefixed item in the OKR list keeps the generic menu",
          "📅 Schedule…" not in titles and "Tags…" in subtitles(items), titles)

    items = menu(OTHERT, OTHERP, "Buy stamps")
    titles = [i["title"] for i in items]
    check("Actions: a task elsewhere is untouched (generic rows, no OKR rows)",
          "➕ Add task" in titles and "Tags…" in subtitles(items)
          and not {"📅 Schedule…", "🔗 Link…", "🏷 Tag…", "✔️ Done"} & set(titles), titles)

    # ── ⌘ Actions: 🥅 Add to OKRs (phase 3) ──────────────────────────────
    def okr_rows_of(items):
        return [i for i in items if "OKRs" in i["title"]]

    items = menu(OTHERT, OTHERP, "Buy stamps")
    rs = okr_rows_of(items)
    check("Actions task: ONE 🥅 Add to OKRs row, a drill to the import screen",
          len(rs) == 1 and rs[0]["title"] == "🥅 Add to OKRs"
          and rs[0]["arg"] == f"xact:crmbrowse:ctx:okrimport:task:{OTHERP}:{OTHERT}"
          and rs[0]["subtitle"] == "As 🏔️ Y · 🥅 O · 🔑 KR", rs)
    items = menu(NOTET, NOTEP, "Reading notes", "note")
    rs = okr_rows_of(items)
    check("Actions note: the row says note",
          len(rs) == 1 and rs[0]["arg"] == f"xact:crmbrowse:ctx:okrimport:note:{NOTEP}:{NOTET}", rs)
    items = menu("", OTHERP, "Errands", "list")
    rs = okr_rows_of(items)
    check("Actions list: the row, no task id",
          len(rs) == 1 and rs[0]["arg"] == f"xact:crmbrowse:ctx:okrimport:list:{OTHERP}:-", rs)
    items = menu(REALT, REALP, "Goals workflow (the real one)")
    rs = okr_rows_of(items)
    check("Actions planned task: 'In the OKRs' opens the O that lists it",
          len(rs) == 1 and rs[0]["title"] == "🥅 In the OKRs · Goals wf"
          and rs[0]["arg"] == f"xact:crmbrowse:ctx:okr:o:{O1}"
          and rs[0]["subtitle"] == "🔑 KR · open it", rs)
    items = menu("", LISTP, "Plan list", "list")
    rs = okr_rows_of(items)
    check("Actions planned list: a KR links the list",
          len(rs) == 1 and rs[0]["title"] == "🥅 In the OKRs · Plan"
          and rs[0]["arg"] == f"xact:crmbrowse:ctx:okr:o:{O2}", rs)
    for who, (tid, pid, title) in (("a KR", (KR2, PID, "🔑 KR • Review - TA")),
                                   ("an unprefixed item in the plan list", (LOOSE, PID, "Loose idea")),
                                   ("the plan list itself", ("", PID, NAME))):
        items = menu(tid, pid, title, "list" if not tid else "task")
        check(f"Actions: no import row on {who}", not okr_rows_of(items),
              [i["title"] for i in okr_rows_of(items)])
    if browse._areas.PERIODIC_LIST_ID:
        items = menu("pn1", browse._areas.PERIODIC_LIST_ID, "☀️ 2026-09-18 · Fri")
        check("Actions: no import row on a periodic note", not okr_rows_of(items))
    items = menu(Y1, PID, "🏔️ Y • Productivity System")
    ay = next((i for i in items if i["title"] == "🥅 Add objectives"), None)
    check("Actions Y: 🥅 Add objectives opens the Y's own screen (its ➕ row adds)",
          ay is not None and ay["arg"] == f"xact:crmbrowse:ctx:okr:y:{Y1}", ay)
    items = menu(O1, PID, "🥅 O • TickAL")
    check("Actions O: no 🥅 Add objectives", not any(i["title"] == "🥅 Add objectives" for i in items))

    # both faces of a project: an O linking the 📌CTA task, or the list
    _pd, _rows = cache.get(f"project_data_{PID}"), cache.get("okr_rows")

    def with_plan(extra):
        cache.set(f"project_data_{PID}", {"project": {"id": PID, "name": NAME},
                                          "tasks": OPEN_ROWS + [extra]})
        cache.set("okr_rows", {"list_id": PID, "name": NAME, "done_complete": True,
                               "rows": OPEN_ROWS + DONE_ROWS + [extra]})

    try:
        with_plan(T("o5", f"🥅 O • [Website](https://ticktick.com/webapp/#p/{CTAP}/tasks/{CTAT})"))
        rs = okr_rows_of(menu("", PROJP, "💼P • Website", "list"))
        check("Actions list: planned through its 📌CTA task",
              len(rs) == 1 and rs[0]["title"] == "🥅 In the OKRs · Website"
              and rs[0]["arg"] == "xact:crmbrowse:ctx:okr:o:o5", rs)
        rs = okr_rows_of(menu(CTAT, CTAP, f"💼 P • [Website](ticktick:///webapp/#p/{PROJP}/tasks) 🔗"))
        check("Actions CTA task: planned (the copy links it)",
              len(rs) == 1 and rs[0]["title"] == "🥅 In the OKRs · Website", rs)
        os.environ["browse_ctx"] = ""
        rows = render(f"ctx:okrimport:list:{PROJP}:-")
        check("import list: planned through its 📌CTA task = no add row",
              rows[1]["title"] == "In the plan · 🥅 Website"
              and rows[2]["arg"] == "xact:crmbrowse:ctx:okr:o:o5", [r["title"] for r in rows])
        with_plan(T("o5", f"🥅 O • [Website](ticktick:///webapp/#p/{PROJP}/tasks)"))
        rs = okr_rows_of(menu(CTAT, CTAP, f"💼 P • [Website](ticktick:///webapp/#p/{PROJP}/tasks) 🔗"))
        check("Actions CTA task: planned through the list an older O links",
              len(rs) == 1 and rs[0]["title"] == "🥅 In the OKRs · Website", rs)
    finally:
        cache.set(f"project_data_{PID}", _pd)
        cache.set("okr_rows", _rows)

    # ── review fixes A2 / A4 / A6 on a plan with a caseless O and a closed Y
    _all, _oc = cache.get("all_tasks"), cache.get("okr_complete")

    def plan_with(*extra, rows_older=False):
        cache.set("okr_rows", {"list_id": PID, "name": NAME, "done_complete": True,
                               "rows": OPEN_ROWS + DONE_ROWS + list(extra)})
        cache.set(f"project_data_{PID}", {"project": {"id": PID, "name": NAME},
                                          "tasks": OPEN_ROWS + ([] if rows_older else list(extra))})
        if rows_older:          # a live read older than the sync that came after it
            t = time.time()
            os.utime(os.path.join(cache.CACHE_DIR, "okr_rows.json"), (t - 10, t - 10))
        else:
            os.utime(os.path.join(cache.CACHE_DIR, f"project_data_{PID}.json"),
                     (time.time() - 10, time.time() - 10))

    try:
        os.environ["browse_ctx"] = ""
        plan_with(T("o9", "🥅 O • 学习 计划"), T("y9", "🏔️ Y • Old year", status=2))
        rows = render("ctx:okraddkr:o9", "Draft")
        p = b64(rows[0]["arg"], "xact:okr_addkr:")
        check("add KRs A4: an O whose proposal no title reads back = 'no code', none sent",
              rows[0]["title"] == "✅ Add 1 KR under 🥅 学习 计划 · no code" and p["code"] is None,
              (rows[0]["title"], p))
        rows = render("ctx:okraddkr:o9", "Draft | Trip - USA")
        check("add KRs A2: a code-less KR ending ' - USA' = the ✅ row dead, the name said",
              rows[0]["valid"] is False and rows[0]["arg"] == ""
              and rows[0]["subtitle"].startswith("'Trip - USA' reads as a code · reword"), rows[0])
        rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}")
        r = by_title(rows, "🔑 KR under 🥅 学习")
        check("import A4: a KR row under that O says 'no code', no new 🏷️",
              r is not None and r["title"] == "🔑 KR under 🥅 学习 计划 · no code"
              and "new 🏷️" not in r["subtitle"], r)
        rows = render("ctx:okr:y:y9", "Health")
        check_rows("closed Y ➕", rows)
        check("Y ➕ A6: a closed Y takes nothing new, and says so",
              [x["title"] for x in rows] == ["Closed · reopen it first"]
              and rows[0]["subtitle"].startswith("🏔️ Old year takes nothing new"), rows)

        cache.set("all_tasks", _all + [T("zz1", "学习 计划", pid=OTHERP, _projectName="Errands")])
        rows = render(f"ctx:okrimport:task:{OTHERP}:zz1")
        r = by_title(rows, "🥅 New objective ·")
        check("import A4: a caseless name as a NEW objective = 'no code', none sent",
              r is not None and r["title"] == "🥅 New objective · no code"
              and b64(r["arg"], "xact:okr_add:")["code"] is None, r)
        cache.set("all_tasks", _all)

        # C4: a KR row whose O's code no title carries is dead (the verb
        # would skip the name), the others stay live
        plan_with(T("o7", "🥅 O • Lower code", content="🏷️ xy"))
        rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}")
        check_rows("import C4", rows)
        r = by_title(rows, "🔑 KR under 🥅 Lower code")
        check("import C4: an O whose 🏷️ line no title reads back = its KR row dead, saying so",
              r is not None and r["title"] == "🔑 KR under 🥅 Lower code · code xy"
              and r["valid"] is False and r["arg"] == ""
              and r["subtitle"].startswith("Lower code's code 'xy' does not read back · fix its 🏷️ line"),
              r)
        check("import C4: ... the other O's KR rows stay live",
              by_title(rows, "🔑 KR under 🥅 TickAL")["valid"] is True
              and by_title(rows, "🥅 New objective ·")["valid"] is True)

        # A5 / C2: the ⌘ Actions row and the import screen both ask
        # okr_write.import_plan and nothing else - so they can never disagree
        o6 = T("o6", f"🔑 KR • [Buy stamps](https://ticktick.com/webapp/#p/{OTHERP}/tasks/{OTHERT}) - OT",
               parent=O2)
        plan_with(o6, rows_older=True)
        rs = okr_rows_of(menu(OTHERT, OTHERP, "Buy stamps"))
        rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}")
        check("Actions A5: a live read older than the sync is not believed (the screen's rule)",
              len(rs) == 1 and rs[0]["title"] == "🥅 Add to OKRs"
              and rows[1]["title"].startswith("🔑 KR under"), (rs, [r["title"] for r in rows]))
        plan_with(o6)
        rs = okr_rows_of(menu(OTHERT, OTHERP, "Buy stamps"))
        rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}")
        check("Actions A5: ... and the fresh one is, on both",
              len(rs) == 1 and rs[0]["title"] == "🥅 In the OKRs · Buy stamps"
              and rs[0]["arg"] == f"xact:crmbrowse:ctx:okr:o:{O2}"
              and rows[1]["title"] == "In the plan · 🔑 Buy stamps", (rs, [r["title"] for r in rows]))

        CALLS, PCALLS = [], []
        _ip, _pl = stub.import_plan, stub.planned

        def spy(kind, pid, tid=None, items=None, list_id=None):
            CALLS.append((kind, pid, tid))
            return _ip(kind, pid, tid, items=items, list_id=list_id)

        def pspy(*a, **k):
            PCALLS.append(a)
            return _pl(*a, **k)

        stub.import_plan, stub.planned = spy, pspy
        plan_with()
        okr_rows_of(menu(OTHERT, OTHERP, "Buy stamps"))
        check("C2: the Actions row asks import_plan about the task",
              CALLS == [("task", OTHERP, OTHERT)], CALLS)
        render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}")
        check("C2: ... and the import screen asks it the SAME question, once",
              CALLS == [("task", OTHERP, OTHERT)] * 2, CALLS)
        okr_rows_of(menu("", LISTP, "Plan list", "list"))
        render(f"ctx:okrimport:list:{LISTP}:-")
        check("C2: ... a list as a list, on both",
              CALLS[-2:] == [("list", LISTP, None)] * 2, CALLS)
        check("C2: neither asks planned() a question of its own", not PCALLS, PCALLS)
        stub.planned = _pl

        def says(**ans):
            full = dict.fromkeys(("name", "link", "kind_hint", "hit", "screen", "blocked"))
            full.update(ans)
            return lambda kind, pid, tid=None, items=None, list_id=None: dict(full)

        LINK_T = {"to": "task", "pid": OTHERP, "tid": OTHERT}
        o2 = next(i for i in okr.items_from(OPEN_ROWS) if i.id == O2)
        stub.import_plan = says(name="Buy stamps", link=LINK_T, kind_hint="KR", hit=o2,
                                screen=f"ctx:okr:o:{O2}")
        rs = okr_rows_of(menu(OTHERT, OTHERP, "Buy stamps"))
        rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}")
        check("C2: import_plan's hit is the row's, no rule of its own",
              len(rs) == 1 and rs[0]["title"] == "🥅 In the OKRs · Onboard TickTicks"
              and rs[0]["arg"] == f"xact:crmbrowse:ctx:okr:o:{O2}"
              and rs[0]["subtitle"] == "🥅 O · open it", rs)
        check("C2: ... the import screen says the same, and opens that screen",
              [r["title"] for r in rows] == ["↗️ Buy stamps", "In the plan · 🥅 Onboard TickTicks",
                                             "⤵️ Open it · 🥅 Onboard TickTicks"]
              and rows[2]["arg"] == f"xact:crmbrowse:ctx:okr:o:{O2}", [r["title"] for r in rows])

        WHY = "🥅 Not written · completed KRs unreadable right now · try again"
        stub.import_plan = says(name="Buy stamps", link=LINK_T, kind_hint="KR", blocked=WHY)
        rs = okr_rows_of(menu(OTHERT, OTHERP, "Buy stamps"))
        rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}")
        check_rows("import blocked", rows)
        check("C2: a refusal = the Add row, its words as the subtitle, still opening the screen",
              len(rs) == 1 and rs[0]["title"] == "🥅 Add to OKRs" and rs[0]["subtitle"] == WHY
              and rs[0]["arg"] == f"xact:crmbrowse:ctx:okrimport:task:{OTHERP}:{OTHERT}", rs)
        check("C2: ... the screen: the thing, then the SAME words, nothing to add - the row "
              "opens the hub, whose fresh read is the cure",
              [r["title"] for r in rows] == ["↗️ Buy stamps", WHY]
              and rows[1]["arg"] == "xact:crmbrowse:ctx:okr"
              and "re-read" in rows[1]["subtitle"]
              and not any(r["arg"].startswith("xact:okr_add") for r in rows),
              [r["title"] for r in rows])
        rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}", "onboard")
        check("C2: ... typing offers nothing either",
              not any(r["arg"].startswith("xact:okr_add") for r in rows), [r["title"] for r in rows])
        stub.import_plan = says(blocked="🥅 Not cached yet · sync or reopen")
        rs = okr_rows_of(menu(OTHERT, OTHERP, "Buy stamps"))
        rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}")
        check("C2: a refusal with nothing to name = one dead row, the row's subtitle the same",
              [r["title"] for r in rows] == ["🥅 Not cached yet · sync or reopen"]
              and rows[0]["valid"] is False
              and rs[0]["subtitle"] == "🥅 Not cached yet · sync or reopen", (rs, rows))
        stub.import_plan = lambda *a, **k: "junk"
        rs = okr_rows_of(menu(OTHERT, OTHERP, "Buy stamps"))
        rows = render(f"ctx:okrimport:task:{OTHERP}:{OTHERT}")
        check("C2: an answer nobody can read = the plain Add row, the screen's fallback",
              rs[0]["subtitle"] == "As 🏔️ Y · 🥅 O · 🔑 KR"
              and rows[1]["title"].startswith("🔑 KR under"), (rs, [r["title"] for r in rows]))
        del stub.import_plan
        rs = okr_rows_of(menu(REALT, REALP, "Goals workflow (the real one)"))
        check("Actions A5: no import_plan in the writer layer = the plain Add row (the screen decides)",
              len(rs) == 1 and rs[0]["title"] == "🥅 Add to OKRs"
              and rs[0]["subtitle"] == "As 🏔️ Y · 🥅 O · 🔑 KR", rs)
        stub.import_plan = _ip

        # C3 through the REAL import_plan. The wording of a blocked answer
        # names the Attachment Login token when there is none: a fake api_v2
        # without one keeps that hermetic (no Keychain read in a test).
        _v2mod = sys.modules.get("api_v2")
        fake_v2 = types.ModuleType("api_v2")
        fake_v2.TickTickV2 = type("TickTickV2", (), {"token": ""})
        sys.modules["api_v2"] = fake_v2
        NO_TOKEN = ("🥅 Not written · completed KRs need the Attachment Login token "
                    "(⚙️ Settings)")

        def partial(extra_complete):
            """The last live read (okr_rows) missed completed KRs; the last
            COMPLETE read (okr_complete) is `extra_complete` (None = none)."""
            plan_with()
            c = cache.get("okr_rows")
            c["done_complete"] = False
            c["rows"] = list(OPEN_ROWS)
            cache.set("okr_rows", c)
            if extra_complete is None:
                cache.invalidate("okr_complete")
            else:
                cache.set("okr_complete", {"list_id": PID, "ts": 0,
                                           "rows": OPEN_ROWS + DONE_ROWS + extra_complete})

        def both(tid, pid, title):
            rs = okr_rows_of(menu(tid, pid, title))
            rows = render(f"ctx:okrimport:task:{pid}:{tid}")
            return rs, rows, _real_okr_write.import_plan("task", pid, tid)

        try:
            partial(None)
            rs, rows, want = both(OTHERT, OTHERP, "Buy stamps")
            check("C3: no complete read anywhere = refused in the verb's words",
                  want["blocked"] == NO_TOKEN and want["hit"] is None, want)
            check("C3: ... the Actions row and the screen say exactly that",
                  len(rs) == 1 and rs[0]["subtitle"] == NO_TOKEN
                  and [r["title"] for r in rows] == ["↗️ Buy stamps", NO_TOKEN]
                  and not any(r["arg"].startswith("xact:okr_add") for r in rows),
                  (rs, [r["title"] for r in rows]))

            o6_open = T("o6", f"🔑 KR • [Buy stamps](https://ticktick.com/webapp/#p/{OTHERP}"
                              f"/tasks/{OTHERT}) - OT", parent=O2)
            partial([o6_open])
            rs, rows, want = both(OTHERT, OTHERP, "Buy stamps")
            check("C3: a hit only on a row gone since (open then) = refused: done or deleted?",
                  want["blocked"] == NO_TOKEN and want["hit"] is None
                  and rs[0]["subtitle"] == NO_TOKEN and rows[1]["title"] == NO_TOKEN,
                  (want, rs, [r["title"] for r in rows]))
            rs, rows, want = both(NOTET, NOTEP, "Reading notes")
            check("C3: ... with a complete read stored, what nothing links is free to add",
                  want["blocked"] is None and want["hit"] is None
                  and rs[0]["subtitle"] == "As 🏔️ Y · 🥅 O · 🔑 KR"
                  and rows[1]["title"].startswith("🔑 KR under") and rows[1]["valid"] is True,
                  (want, rs, [r["title"] for r in rows]))
            rs, rows, want = both(REALT, REALP, "Goals workflow (the real one)")
            check("C3: ... and what the read in hand links is planned",
                  want["hit"] is not None and want["hit"].id == KR1
                  and rs[0]["title"] == "🥅 In the OKRs · Goals wf"
                  and rows[1]["title"] == "In the plan · 🔑 Goals wf",
                  (want, rs, [r["title"] for r in rows]))

            partial([dict(o6_open, status=2)])
            rs, rows, want = both(OTHERT, OTHERP, "Buy stamps")
            check("C3: a hit on a row KNOWN closed = planned, done, on all three",
                  want["hit"] is not None and want["hit"].id == "o6" and want["blocked"] is None
                  and rs[0]["title"] == "🥅 In the OKRs · Buy stamps"
                  and rs[0]["subtitle"] == "🔑 KR · done · open it"
                  and rs[0]["arg"] == f"xact:crmbrowse:ctx:okr:o:{O2}"
                  and [r["title"] for r in rows] == ["↗️ Buy stamps", "In the plan · 🔑 Buy stamps",
                                                     "⤵️ Open it · 🥅 Onboard TickTicks"]
                  and rows[1]["subtitle"].startswith("No second copy · done"),
                  (want, rs, [r["title"] for r in rows]))
        finally:
            if _v2mod is None:
                sys.modules.pop("api_v2", None)
            else:
                sys.modules["api_v2"] = _v2mod

        # remember_complete: only a live read with every completed KR
        RC = []
        stub.remember_complete = lambda snap: RC.append((snap.source, snap.done_complete))

        def stale():
            old = time.time() - browse._OKR_FRESH_S - 5
            os.utime(os.path.join(cache.CACHE_DIR, "okr_rows.json"), (old, old))

        okr.load = lambda api=None, v2=None, list_id=None: okr.Snapshot(
            okr.items_from(OPEN_ROWS), "live", "v1 open (fake); v2 completed unavailable",
            PID, NAME, False)
        stale()
        snap, _why, live = browse._okr_snapshot("")
        check("remember_complete: a live read missing completed KRs is never kept as complete",
              live and snap.done_complete is False and RC == [], RC)
        okr.load = fake_load
        stale()
        browse._okr_snapshot("")
        check("remember_complete: ... a complete one is, once", RC == [("live", True)], RC)
        browse._okr_snapshot("")
        check("remember_complete: ... a reused fresh read is not handed over again",
              RC == [("live", True)], RC)
    finally:
        okr.load = fake_load
        stub.remember_complete = _real_okr_write.remember_complete
        stub.planned = _real_okr_write.planned
        stub.import_plan = _real_okr_write.import_plan
        cache.set("all_tasks", _all)
        cache.set(f"project_data_{PID}", _pd)
        cache.set("okr_rows", _rows)
        if _oc is None:
            cache.invalidate("okr_complete")
        else:
            cache.set("okr_complete", _oc)
finally:
    os.environ.clear()
    os.environ.update(_env)
    shutil.rmtree(tmp, ignore_errors=True)


print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if __name__ == "__main__":
    sys.exit(1 if FAILS else 0)
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
