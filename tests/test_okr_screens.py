#!/usr/bin/env python3
"""The 🥅 OKR screens: Scripts/browse.py ctx:okr*, the main-menu row and the
⌘ Actions entity rows, rendered the way Alfred runs them (main() with the
ctx riding env browse_ctx) against a FAKE cache in a temp dir.

No network and no write anywhere real: okr.load is a stub that counts its
calls, okr_write is a stub module that counts heal spawns, cache.CACHE_DIR
points at a temp dir, and okr_list_id rides env. The dates are built around
today, so "late", "behind" and the ripple preview are stable on any day.

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
    os.environ["browse_ctx"] = f"ctx:okrsched:{KR2}"
    os.environ["browse_back"] = ""
    check("parse_ctx: 'tomorrow' typed on the schedule screen stays there",
          browse.parse_ctx("tomorrow") == ("okrsched", [KR2], "tomorrow"),
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
    check("root: ⇧ and ⌘⇧ dead on a Y/O, ⌥⇧ opens the schedule screen",
          y["mods"]["shift"]["valid"] is False and y["mods"]["cmd+shift"]["valid"] is False
          and y["mods"]["alt+shift"]["arg"] == f"xact:crmbrowse:ctx:okrsched:{Y1}")
    check("root: item rows are task rows (⌘ Actions on THE item, raw title)",
          y["variables"]["task_id"] == Y1 and y["variables"]["task_list_id"] == PID
          and y["variables"]["task_title"] == "🏔️ Y • Productivity System"
          and y["variables"]["item_type"] == "task" and y["mods"]["cmd"]["valid"] is True)
    closed = rows[-1]
    check("root: a closed O never schedules (⌥⇧ dead)",
          closed["mods"]["alt+shift"]["valid"] is False)
    check("root: ⌃ goes back to the folders root",
          all(r["variables"]["browse_back"] == "ctx:folders" for r in rows))
    check("root: the live read is kept as okr_rows (the cache every other read uses)",
          (cache.get("okr_rows") or {}).get("list_id") == PID
          and len(cache.get("okr_rows")["rows"]) == len(OPEN_ROWS) + len(DONE_ROWS))

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
    check("root search: 'today' searches, it does not jump to the smart list",
          rows[0]["title"] == 'No OKR matching "today"'
          and rows[0]["variables"]["browse_back"] == "ctx:folders", rows[0])
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
    check("O screen search: the head row steps aside, ⏎ hits the match",
          [r["title"] for r in rows] == ["🔑 Publish"], [r["title"] for r in rows])
    rows = render("ctx:okr:o:nope")
    check("O screen: an id not in the plan says so",
          rows[0]["title"].startswith("Not in the plan") and rows[0]["valid"] is False)
    rows = render(f"ctx:okr:y:{Y1}")
    check("Y screen: head + its O", [r["title"] for r in rows] == ["🏔️ Productivity System", "🥅 TickAL"],
          [r["title"] for r in rows])

    # ── pace ─────────────────────────────────────────────────────────────
    rows = render("ctx:okrpace")
    check_rows("pace", rows)
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

    # ── schedule ─────────────────────────────────────────────────────────
    n_loads = len(LOADS)
    rows = render(f"ctx:okrsched:{KR2}")
    check_rows("schedule", rows)
    check("schedule: reads the cache only (a preview, never a plan to write)",
          len(LOADS) == n_loads)
    titles = [r["title"] for r in rows]
    check("schedule: head, +1 / +3 / +7, tomorrow, pick-a-date hint",
          titles == [f"📅 Review · {okr.span_txt(day(0), day(2), TODAY)}", "⏩ +1 day",
                     "⏩ +3 days", "⏩ +7 days", "🌙 Tomorrow", "📆 Pick a date · type it"], titles)
    p1 = b64(rows[1]["arg"], "xact:okr_sched:")
    check("schedule: +1 day = the extend payload, back = the screen that lists it",
          p1 == {"id": KR2, "action": "extend", "arg": 1, "back": f"ctx:okr:o:{O1}"}, p1)
    check("schedule: the preview names the new span and the ripple",
          rows[1]["subtitle"].startswith(f"{okr.span_txt(day(0), day(3), TODAY)} · moves 1"),
          rows[1]["subtitle"])
    pt = b64(rows[4]["arg"], "xact:okr_sched:")
    check("schedule: tomorrow carries no arg", pt["action"] == "tomorrow" and pt["arg"] is None, pt)
    check("schedule: ⌃ goes to the item's O screen",
          all(r["variables"]["browse_back"] == f"ctx:okr:o:{O1}" for r in rows))
    rows = render(f"ctx:okrsched:{KR2}", "+5")
    check("schedule: typed +5 = one extend row, arg 5",
          len(rows) == 1 and b64(rows[0]["arg"], "xact:okr_sched:")["arg"] == 5, rows)
    rows = render(f"ctx:okrsched:{KR2}", "-1")
    check("schedule: typed -1 pulls in",
          rows[0]["title"] == "⏪ Pull in 1 day"
          and b64(rows[0]["arg"], "xact:okr_sched:")["arg"] == -1, rows[0])
    rows = render(f"ctx:okrsched:{KR2}", "+0")
    check("schedule: +0 moves nothing", rows[0]["valid"] is False)
    rows = render(f"ctx:okrsched:{KR1}", "-1")
    check("schedule: a pull-in that would end before today is a dead row",
          rows[0]["valid"] is False and "That end is gone" in rows[0]["subtitle"], rows[0])
    rows = render(f"ctx:okrsched:{KR1}", "+1")
    check("schedule: an extend that ends TODAY is still offered",
          rows[0]["valid"] is True, rows[0])
    rows = render(f"ctx:okrsched:{KR2}", "+523w")
    check("schedule: a length the verb refuses (> 3660 days) is never a ⏎",
          rows[0]["valid"] is False and "Too long" in rows[0]["subtitle"], rows[0])
    rows = render(f"ctx:okrsched:{KR2}", "+522w")
    check("schedule: +522w is still a plan", rows[0]["valid"] is True, rows[0])
    for dash in ("\u2212", "\u2013", "\u2014"):
        rows = render(f"ctx:okrsched:{KR2}", dash + "1d")
        check(f"schedule: a leading {dash!r} is a minus, never a date",
              rows[0]["title"] == "⏪ Pull in 1 day"
              and b64(rows[0]["arg"], "xact:okr_sched:")["arg"] == -1, rows[0])
    target = day(30)
    typed = f"{target.day}.{target.month}.{target.year}"
    want_iso = dateutil.parse_date(typed)
    rows = render(f"ctx:okrsched:{KR2}", typed)
    got = b64(rows[0]["arg"], "xact:okr_sched:") if rows[0]["valid"] else rows[0]
    check("schedule: a typed date = the date action, ISO arg",
          want_iso and got.get("action") == "date" and got.get("arg") == want_iso[:10], (typed, got))
    rows = render(f"ctx:okrsched:{KR2}", "tomorrow 14:00")
    check("schedule: a time is refused (all-day only)",
          rows[0]["title"] == "Dates only · no time" and rows[0]["valid"] is False)
    rows = render(f"ctx:okrsched:{KR2}", "tomorrow")
    check("schedule: 'tomorrow' typed is a date here, not the smart list",
          rows[0]["valid"] is True and b64(rows[0]["arg"], "xact:okr_sched:")["arg"]
          == (TODAY + timedelta(days=1)).isoformat(), rows[0])
    rows = render(f"ctx:okrsched:{KR2}", "tom")
    check("schedule: a word that is no date falls back to the rows it names",
          [r["title"] for r in rows] == ["🌙 Tomorrow"], [r["title"] for r in rows])
    rows = render(f"ctx:okrsched:{KR2}", "xyzzy")
    check("schedule: nonsense says so", rows[0]["valid"] is False and "No date" in rows[0]["title"])
    rows = render(f"ctx:okrsched:{KR6}")
    ext = rows[1]
    check("schedule: an undated KR cannot extend - the refusal is the subtitle",
          ext["valid"] is False and "no dates to extend" in ext["subtitle"], ext)
    check("schedule: an undated KR can still move to tomorrow", rows[4]["valid"] is True)
    rows = render(f"ctx:okrsched:{KR4}")
    check("schedule: a done KR never moves",
          [r["title"] for r in rows][1] == "Closed · never moves" and len(rows) == 2)
    rows = render(f"ctx:okrsched:{O1}")
    check("schedule: +1 on an O goes to its last KR (the O ends a day later)",
          rows[1]["valid"] is True
          and rows[1]["subtitle"].startswith(okr.span_txt(day(-12), day(13), TODAY)),
          rows[1]["subtitle"])

    # S1: a bar led by + or - is a LENGTH, every spelling, and it never
    # reaches dateutil (a bare "-2" or "+3 months" read as a date would be
    # a silent wrong move)
    SEEN = []
    _pd, _pds = dateutil.parse_date, dateutil.parse_date_status
    dateutil.parse_date = lambda x, _f=_pd: SEEN.append(x) or _f(x)
    dateutil.parse_date_status = lambda x, _f=_pds: SEEN.append(x) or _f(x)
    try:
        bad = []
        for typed, n in (("+3", 3), ("+3d", 3), ("+3 D", 3), ("+ 3 days", 3),
                         ("+1 day", 1), ("+1DAY", 1), ("+1w", 7), ("+2W", 14),
                         ("+ 2 weeks", 14), ("+1 Week", 7), ("-2", -2), ("-2d", -2),
                         ("- 1 w", -7)):
            rows = render(f"ctx:okrsched:{KR3}", typed)
            got = b64(rows[0]["arg"], "xact:okr_sched:") if rows[0]["valid"] else {}
            if len(rows) != 1 or got.get("action") != "extend" or got.get("arg") != n:
                bad.append((typed, rows[0]["title"], rows[0]["subtitle"], got.get("arg")))
        check("schedule: +N · +Nd · +N day(s) · +Nw · +N week(s), any case, any spacing",
              not bad, bad)
        rows = render(f"ctx:okrsched:{KR3}", "+2w")
        check("schedule: weeks say weeks, the payload counts days",
              rows[0]["title"] == "⏩ Extend +2 weeks", rows[0]["title"])
        rows = render(f"ctx:okrsched:{KR3}", "-2")
        check("schedule: a minus pulls in", rows[0]["title"] == "⏪ Pull in 2 days", rows[0]["title"])
        bad = []
        for typed in ("+", "-", "+x", "+3 months", "+2 wks", "-tomorrow", "+1.5", "+ 3 days later"):
            rows = render(f"ctx:okrsched:{KR3}", typed)
            if not (len(rows) == 1 and rows[0]["title"] == "+N longer · -N shorter"
                    and rows[0]["valid"] is False):
                bad.append((typed, [r["title"] for r in rows]))
        check("schedule: a signed bar that is no length = one dead hint row", not bad, bad)
        check("schedule: no signed bar ever reached dateutil", not SEEN, SEEN)
    finally:
        dateutil.parse_date, dateutil.parse_date_status = _pd, _pds

    # S3: ANY typed time is refused, by parsedatetime's own status. Pinned
    # to UTC+2 (Vex's summer offset): there "2am" is UTC midnight, and an
    # ISO check alone read it as a plain date
    _tz = os.environ.get("TZ")
    os.environ["TZ"] = "Etc/GMT-2"                          # POSIX sign: UTC+2
    time.tzset()
    try:
        check("dateutil: parse_date unchanged - '2am' at UTC+2 is UTC midnight",
              (dateutil.parse_date("2am") or "")[11:19] == "00:00:00",
              dateutil.parse_date("2am"))
        st = {x: dateutil.parse_date_status(x) for x in ("tomorrow", "2am", "12.10 2am", "xyzzy")}
        check("dateutil: parse_date_status = 1 date · 2 time · 3 both · 0 nothing",
              st["tomorrow"][1] == 1 and st["2am"][1] == 2 and st["12.10 2am"][1] == 3
              and st["xyzzy"] == (None, 0), st)
        check("dateutil: parse_date_status's ISO is parse_date's",
              dateutil.parse_date_status("12.10")[0] == dateutil.parse_date("12.10"))
        bad = []
        for typed in ("3pm", "2am", "12.10 2am", "tomorrow 14:00", "noon", "9 at 14"):
            rows = render(f"ctx:okrsched:{KR2}", typed)
            if not (len(rows) == 1 and rows[0]["title"] == "Dates only · no time"
                    and rows[0]["valid"] is False):
                bad.append((typed, rows[0]["title"]))
        check("schedule: every typed time is refused - '2am', '12.10 2am' like '3pm'",
              not bad, bad)
    finally:
        if _tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = _tz
        time.tzset()

    # S4: the past is refused, and a pull-in past the start says so in words
    rows = render(f"ctx:okrsched:{KR2}", "yesterday")
    check("schedule: a day before today is a dead row",
          len(rows) == 1 and rows[0]["title"] == "That day is gone · today or later"
          and rows[0]["valid"] is False, rows)
    rows = render(f"ctx:okrsched:{KR2}", "today")
    check("schedule: today itself is a date",
          rows[0]["valid"] is True
          and b64(rows[0]["arg"], "xact:okr_sched:")["arg"] == TODAY.isoformat(), rows[0])
    iso_re = re.compile(r"\d{4}-\d{2}-\d{2}")
    for who, iid, typed in (("a KR", KR2, "-5"), ("an O (its last KR's start)", O1, "-12")):
        rows = render(f"ctx:okrsched:{iid}", typed)
        check(f"schedule: {who} pulled in past its start = words, never raw ISO dates",
              rows[0]["valid"] is False
              and rows[0]["subtitle"].startswith("Longer than the item · pick a date")
              and not iso_re.search(rows[0]["subtitle"]), rows[0])

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
    del stub.code_ok
    try:
        rows = render(f"ctx:okraddkr:{O1}", "Draft =xy")
        check("add KRs: no writer layer = no code check (the verb decides)",
              rows[0]["valid"] is True, rows[0])
    finally:
        stub.code_ok = _real_okr_write.code_ok
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

    # ── no screen shares a mods dict between two rows ────────────────────
    for screen, fn, ids, q in (
            ("root", browse.render_okr, [], ""), ("root search", browse.render_okr, [], "o"),
            ("O screen", browse.render_okr, ["o", O1], ""),
            ("pace", browse.render_okrpace, [], ""), ("pace plan", browse.render_okrpace, ["monthly"], ""),
            ("schedule", browse.render_okrsched, [KR2], ""), ("add KRs", browse.render_okraddkr, [O1], "a | b"),
            ("link", browse.render_okrlink, [KR2], ""), ("tag", browse.render_okrtag, [O1], "")):
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
    check("Actions KR: entity rows first, right after Open",
          titles[op + 1:op + 5] == ["📅 Schedule…", "🔗 Link…", "🏷 Tag…", "✔️ Done"], titles)
    args = {i["title"]: i["arg"] for i in items}
    check("Actions KR: the drills ride xact:crmbrowse to the hub's own screens",
          args["📅 Schedule…"] == f"xact:crmbrowse:ctx:okrsched:{KR2}"
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
finally:
    os.environ.clear()
    os.environ.update(_env)
    shutil.rmtree(tmp, ignore_errors=True)


print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if __name__ == "__main__":
    sys.exit(1 if FAILS else 0)
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
