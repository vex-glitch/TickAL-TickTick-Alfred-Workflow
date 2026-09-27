#!/usr/bin/env python3
"""🚗 src/commute.py - commutes that belong to a CRM booking (Vex 2026-09-26).

The ask: "commute added automatically. Hour and a half before and an hour
after whatever duration is set ... same tags so my calendar is nicely color
scheduled." Pure window math + a fake API for the writers; nothing reaches
the network. The second half pins the review findings of the same day
(live pool, date-only reschedule, midnight moves, the hand-made guard, the
copied leg, the point booking, the zero setting, the sweep).

    python3 tests/test_commute.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import os
    import sys
    import tempfile
    from datetime import datetime, timezone

    SCRATCH = tempfile.mkdtemp(prefix="tickal_commute_")
    os.environ["HOME"] = SCRATCH              # before ANY repo import (config.json)
    os.environ["TICKAL_NO_SETTLE"] = "1"
    os.environ["crm_list_id"] = "69fed9d51fe6d10d8510bf15"
    os.environ["crm_records_list_id"] = "6a4e50e9842a1194a7c681e1"
    os.environ["crm_tags"] = "📅consultation 📅tattoo"
    os.environ["crm_prepare_tag"] = "📅prepare"

    REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(REPO, "src", "lib"))
    sys.path.insert(0, os.path.join(REPO, "src"))
    import commute as cm   # noqa: E402

    FAILS, COUNT = [], [0]


    def check(name, cond, detail=""):
        COUNT[0] += 1
        print(f"  ok  {name}" if cond else f"FAIL  {name}  {detail}")
        if not cond:
            FAILS.append(name)


    CRM = "69fed9d51fe6d10d8510bf15"
    LST = cm.COMMUTE_LIST_DEFAULT
    REC = "[🎨 Marko • Sleeve](https://ticktick.com/webapp/#p/6a4e50e9842a1194a7c681e1/tasks/6a5f18fd8f0846c75ce1d09c)"
    B1 = "6ab000000000000000000001"
    B2 = "6ab000000000000000000002"
    BOOK = {"id": B1, "projectId": CRM, "title": f"{REC} S2 - 400",
            "tags": ["📅tattoo"], "status": 0,
            "startDate": "2026-09-30T10:00:00+0000", "dueDate": "2026-09-30T13:00:00+0000"}


    class FakeAPI:
        def __init__(self, lists=None):
            self.created, self.updated, self.deleted, self.reads = [], [], [], []
            self.fail_create = False
            self.fail_read = False
            self.lists = lists if lists is not None else {}

        def get_project_data(self, pid):
            self.reads.append(pid)
            if self.fail_read:
                raise RuntimeError("read boom")
            return {"tasks": [dict(t) for t in self.lists.get(pid, [])]}

        def create_task(self, title, project_id=None, due_date=None, content=None,
                        priority=0, tags=None, column_id=None, parent_id=None,
                        kind=None, start_date=None, repeat_flag=None, reminders=None,
                        time_zone=None):
            if self.fail_create:
                raise RuntimeError("boom")
            t = {"id": f"c{len(self.created) + 1}".ljust(24, "0"), "projectId": project_id,
                 "title": title, "content": content, "tags": tags,
                 "startDate": start_date, "dueDate": due_date, "status": 0,
                 "priority": priority}
            self.created.append(t)
            return dict(t)

        def update_task(self, task_id, project_id, current=None, fresh=None,
                        derive=None, **fields):
            self.updated.append((task_id, project_id, dict(fields)))
            return {**(current or {}), **fields}

        def delete_task(self, project_id, task_id):
            self.deleted.append((project_id, task_id))
            return True


    def leg(tid, word, booking_tid, start, end, **kw):
        t = {"id": tid.ljust(24, "0"), "projectId": LST, "title": "Commute", "status": 0,
             "content": f"🚗 {word} {cm.booking_link(CRM, booking_tid, BOOK['title'])}",
             "startDate": start, "dueDate": end}
        t.update(kw)
        return t


    # ── 1. config defaults (the okr_list_id rule; minutes read 0 as 0) ──────────
    check("1.list default is 📅Calendar scheduling", cm.list_id() == "6a9d214c8f08ea0ec9b69e35")
    check("1.tags default 2️⃣personal", cm.tags() == ["2️⃣personal"], cm.tags())
    check("1.before 90 / after 60", (cm.before_min(), cm.after_min()) == (90, 60))
    check("1.title Commute", cm.title() == "Commute")
    check("1.enabled by default", cm.enabled())
    os.environ["commute_tags"] = "⬜️greytag, 2️⃣Personal"
    check("1.env tags: comma or space, lowercased", cm.tags() == ["⬜️greytag", "2️⃣personal"], cm.tags())
    del os.environ["commute_tags"]
    os.environ["commute_list_id"] = ""
    check("1.present-but-blank list id = OFF", not cm.enabled())
    del os.environ["commute_list_id"]
    os.environ["commute_before_min"] = "junk"
    check("1.unreadable minutes fall back", cm.before_min() == 90)
    os.environ["commute_before_min"] = "0"
    check("1.a zero setting is zero, not the default (review)", cm.before_min() == 0)
    check("1.one leg at zero keeps the feature on", cm.enabled())
    os.environ["commute_before_min"] = ""
    check("1.a blank setting is the default", cm.before_min() == 90)
    del os.environ["commute_before_min"]

    # ── 2. stamps ───────────────────────────────────────────────────────────────
    check("2.parse cache stamp (.000+0000)", cm.parse_iso("2026-09-23T09:00:00.000+0000") is not None)
    check("2.parse write stamp (+0000)", cm.parse_iso("2026-09-23T09:00:00+0000") is not None)
    check("2.parse MCP stamp (+0100) is the same instant",
          cm.fmt_iso(cm.parse_iso("2026-09-23T09:00:00+0100")) == "2026-09-23T08:00:00+0000")
    check("2.parse bare date", cm.parse_iso("2026-09-23") is not None)
    check("2.parse junk is None", cm.parse_iso("soon") is None and cm.parse_iso("") is None)
    check("2.fmt is the TickAL write form", cm.fmt_iso(cm.parse_iso("2026-09-23T09:00:00.000+0000")) == "2026-09-23T09:00:00+0000")

    # ── 3. windows: 90 before the start, 60 after the end ───────────────────────
    w = cm.windows("2026-09-30T10:00:00+0000", "2026-09-30T13:00:00+0000")
    check("3.two legs", [x[0] for x in w] == ["to", "from"], w)
    check("3.to = start-90 → start", w[0][1:] == ("2026-09-30T08:30:00+0000", "2026-09-30T10:00:00+0000"), w[0])
    check("3.from = end → end+60", w[1][1:] == ("2026-09-30T13:00:00+0000", "2026-09-30T14:00:00+0000"), w[1])
    w = cm.windows(None, "2026-09-30T10:00:00+0000")
    check("3.a point has no end to leave from: the to-leg only (review)",
          w == [("to", "2026-09-30T08:30:00+0000", "2026-09-30T10:00:00+0000")], w)
    w = cm.windows("2026-09-30T10:00:00+0000", "2026-09-30T10:00:00+0000")
    check("3.start == due is a point too", [x[0] for x in w] == ["to"], w)
    check("3.is_point", cm.is_point(None, "2026-09-30T10:00:00+0000")
          and not cm.is_point("2026-09-30T10:00:00+0000", "2026-09-30T13:00:00+0000")
          and not cm.is_point(None, None))
    check("3.zero before drops that leg",
          [x[0] for x in cm.windows("2026-09-30T10:00:00+0000", "2026-09-30T13:00:00+0000", before=0)] == ["from"])
    check("3.custom lengths", cm.windows("2026-09-30T10:00:00+0000", "2026-09-30T13:00:00+0000", 30, 15)[0][1]
          == "2026-09-30T09:30:00+0000")
    check("3.no stamps = no legs", cm.windows(None, None) == [])
    check("3.crosses midnight cleanly",
          cm.windows("2026-09-30T00:30:00+0000", "2026-09-30T02:00:00+0000")[0][1] == "2026-09-29T23:00:00+0000")

    # ── 4. time state ───────────────────────────────────────────────────────────
    check("4.span is timed", cm.time_state(BOOK) == "timed" and not cm.is_all_day(BOOK))
    check("4.isAllDay True wins", cm.time_state({**BOOK, "isAllDay": True}) == "all-day")
    check("4.UTC-midnight due, no start = all-day",
          cm.time_state({"dueDate": "2026-09-30T00:00:00+0000"}) == "all-day")
    check("4.a +0100 midnight stamp is normalised first (review)",
          cm.time_state({"dueDate": "2026-09-30T01:00:00+0100"}) == "all-day")
    check("4.two midnight stamps a day apart = an all-day span",
          cm.time_state({"startDate": "2026-09-30T00:00:00+0000", "dueDate": "2026-10-01T00:00:00+0000"}) == "all-day")
    check("4.no stamps = undated (review: not 'all-day')", cm.time_state({}) == "undated")
    check("4.a timed point is timed", cm.time_state({"dueDate": "2026-09-30T10:00:00+0000"}) == "timed")
    p = cm.plan({**BOOK, "startDate": None, "dueDate": "2026-09-30T00:00:00+0000"}, [])
    check("4.plan says all-day, plans nothing", p["reason"] == "all-day" and not p["make"], p)

    # ── 5. plan: make / move / keep / stale ─────────────────────────────────────
    p = cm.plan(BOOK, [])
    check("5.empty pool: make both", [m[0] for m in p["make"]] == ["to", "from"] and not p["move"], p)
    to_ok = leg("x1", "to", B1, "2026-09-30T08:30:00.000+0000", "2026-09-30T10:00:00.000+0000")
    from_old = leg("x2", "from", B1, "2026-09-30T12:00:00.000+0000", "2026-09-30T13:00:00.000+0000")
    p = cm.plan(BOOK, [to_ok, from_old])
    check("5.linked leg on the right span is kept", [k[0]["id"] for k in p["keep"]] == [to_ok["id"]], p)
    check("5.linked leg on the wrong span is moved to the new one",
          [(m[0]["id"], m[2], m[3]) for m in p["move"]]
          == [(from_old["id"], "2026-09-30T13:00:00+0000", "2026-09-30T14:00:00+0000")], p)
    check("5.nothing made when both legs exist", not p["make"], p)
    done_to = {**to_ok, "status": 2}
    p = cm.plan(BOOK, [done_to, from_old])
    check("5.a completed leg is not this booking's open leg (made again)",
          [m[0] for m in p["make"]] == ["to"], p)
    hand = {"id": "h1".ljust(24, "0"), "projectId": LST, "title": "Commute", "status": 0, "content": "",
            "startDate": "2026-09-30T08:30:00.000+0000", "dueDate": "2026-09-30T10:00:00.000+0000"}
    p = cm.plan(BOOK, [hand])
    check("5.a hand-made commute on the same start is honoured, not doubled",
          [m[0] for m in p["make"]] == ["from"] and p["keep"][0][0]["id"] == hand["id"], p)
    other = {**hand, "id": "o1".ljust(24, "0"), "projectId": "someOtherList"}
    p = cm.plan(BOOK, [other])
    check("5.a same-time task in another list is not a commute", len(p["make"]) == 2, p)
    notmine = leg("n1", "from", B2, "2026-09-30T08:30:00.000+0000", "2026-09-30T09:30:00.000+0000")
    p = cm.plan(BOOK, [notmine])
    check("5.another booking's leg on the same minute is NEVER adopted (review)",
          [m[0] for m in p["make"]] == ["to", "from"] and not p["keep"], p)
    legacy = {**to_ok, "id": "l1".ljust(24, "0"), "content": f"see {cm.booking_link(CRM, B1, BOOK['title'])}"}
    p = cm.plan(BOOK, [legacy])
    check("5.a linked leg without a to/from word takes the first window",
          p["keep"][0][0]["id"] == legacy["id"] and [m[0] for m in p["make"]] == ["from"], p)
    # the copied leg (review): two 'to' legs link B1, one far away - the one
    # nearest the PREVIOUS span is the real one
    prev = {"startDate": "2026-09-28T10:00:00+0000", "dueDate": "2026-09-28T13:00:00+0000"}
    real = leg("r1", "to", B1, "2026-09-28T08:30:00.000+0000", "2026-09-28T10:00:00.000+0000")
    copy = leg("k1", "to", B1, "2026-10-20T08:30:00.000+0000", "2026-10-20T10:00:00.000+0000")
    p = cm.plan(BOOK, [copy, real], prev=prev)
    check("5.the leg nearest the previous span is the one moved; the copy stays",
          [m[0]["id"] for m in p["move"]] == [real["id"]], p)
    # span → point: the from-leg has nothing to leave from
    pt = {**BOOK, "startDate": "2026-09-30T10:00:00+0000", "dueDate": "2026-09-30T10:00:00+0000"}
    p = cm.plan(pt, [to_ok, {**from_old, "startDate": "2026-09-30T13:00:00.000+0000",
                             "dueDate": "2026-09-30T14:00:00.000+0000"}])
    check("5.a booking that lost its end: to-leg kept, from-leg stale, point flagged",
          p["point"] and [k[0]["id"] for k in p["keep"]] == [to_ok["id"]]
          and [t["id"] for t in p["stale"]] == [from_old["id"]] and not p["make"], p)
    p = cm.plan({**BOOK, "startDate": None, "dueDate": "2026-10-02T00:00:00+0000"}, [to_ok, from_old])
    check("5.all-day now: both linked legs are stale (review)",
          p["reason"] == "all-day" and sorted(t["id"] for t in p["stale"]) == sorted([to_ok["id"], from_old["id"]]), p)

    # ── 6. the link ─────────────────────────────────────────────────────────────
    c = cm.leg_content("to", CRM, B1, BOOK["title"])
    check("6.content links the booking by task id", f"/tasks/{B1})" in c and c.startswith("🚗 to ["), c)
    check("6.the nested records link is flattened to its label",
          "[🎨 Marko • Sleeve S2 - 400](" in c and c.count("](") == 1, c)
    check("6.links_booking reads it back", cm.links_booking({"content": c}, B1)
          and not cm.links_booking({"content": c}, B2))
    check("6.booking_tid_of / leg_of", cm.booking_tid_of({"content": c}) == B1 and cm.leg_of({"content": c}) == "to"
          and cm.booking_tid_of(hand) == "" and cm.leg_of(hand) == "")
    check("6.near: within a day of the span",
          cm.near(to_ok, BOOK) and cm.near(to_ok, (BOOK["startDate"], BOOK["dueDate"]))
          and not cm.near(copy, BOOK) and cm.near(copy, {}) and not cm.near({}, BOOK))

    # ── 7. sync with a fake API ─────────────────────────────────────────────────
    api = FakeAPI()
    line, made, moved, rm = cm.sync(api, BOOK, pool=[])
    check("7.two creates", len(api.created) == 2 and len(made) == 2 and rm == 0, api.created)
    c1, c2 = api.created
    check("7.title / list / tags / no priority",
          all(t["title"] == "Commute" and t["projectId"] == LST and t["tags"] == ["2️⃣personal"]
              and not t["priority"] for t in api.created), api.created)
    check("7.to leg span", (c1["startDate"], c1["dueDate"]) == ("2026-09-30T08:30:00+0000", "2026-09-30T10:00:00+0000"))
    check("7.from leg span", (c2["startDate"], c2["dueDate"]) == ("2026-09-30T13:00:00+0000", "2026-09-30T14:00:00+0000"))
    check("7.both link the booking", all(f"/tasks/{B1})" in t["content"] for t in api.created))
    check("7.toast says ×2 added", line.startswith("🚗 Commute ×2 added"), line)
    api = FakeAPI()
    line, made, moved, rm = cm.sync(api, BOOK, pool=[to_ok, from_old])
    check("7.move: one update, no create", len(api.updated) == 1 and not api.created, (api.updated, api.created))
    tid_, pid_, f_ = api.updated[0]
    check("7.move posts the new span through update_task",
          tid_ == from_old["id"] and pid_ == LST and (f_["startDate"], f_["dueDate"])
          == ("2026-09-30T13:00:00+0000", "2026-09-30T14:00:00+0000"), api.updated)
    check("7.a move says isAllDay False - never update_task's midnight guess (review)",
          f_.get("isAllDay") is False, f_)
    check("7.toast says moved", "moved" in line and "added" not in line, line)
    api = FakeAPI()
    line, made, moved, rm = cm.sync(api, BOOK, pool=[to_ok, {**from_old, "startDate": "2026-09-30T13:00:00.000+0000",
                                                                "dueDate": "2026-09-30T14:00:00.000+0000"}])
    check("7.nothing to do: no writes, honest toast", not api.updated and not api.created
          and line == "🚗 Commute already there", (line, api.updated))
    api = FakeAPI()
    api.fail_create = True
    line, made, moved, rm = cm.sync(api, BOOK, pool=[])
    check("7.a failed create is reported, never raised", "2 commutes failed" in line and not made, line)
    api = FakeAPI()
    line, made, moved, rm = cm.sync(api, {**BOOK, "startDate": None, "dueDate": "2026-09-30T00:00:00+0000"}, pool=[])
    check("7.all-day: no writes, the toast says why", not api.created and "all-day" in line, line)
    api = FakeAPI()
    line, made, moved, rm = cm.sync(api, {**BOOK, "startDate": None, "dueDate": None}, pool=[])
    check("7.undated: the toast says undated, not all-day", line == "🚗 no commute · undated booking", line)
    api = FakeAPI()
    line, made, moved, rm = cm.sync(api, {**BOOK, "id": ""}, pool=[])
    check("7.no id: nothing", not api.created and line == "")
    # the date-only reschedule (review): legs left behind must go
    api = FakeAPI()
    line, made, moved, rm = cm.sync(api, {**BOOK, "startDate": "2026-10-02T00:00:00+0000",
                                          "dueDate": "2026-10-02T00:00:00+0000"}, pool=[to_ok, from_old])
    check("7.booking moved to a date without a time: both legs removed, toast says so",
          sorted(t for _p, t in api.deleted) == sorted([to_ok["id"], from_old["id"]]) and rm == 2
          and line == "🚗 Commute ×2 removed · all-day booking", (line, api.deleted))
    # a point booking: to-leg only, honest toast
    api = FakeAPI()
    line, made, moved, rm = cm.sync(api, {**BOOK, "startDate": None, "dueDate": "2026-09-30T10:00:00+0000"}, pool=[])
    check("7.point booking: one leg, 'to only' in the toast",
          len(api.created) == 1 and "×1 added" in line and "to only, no duration" in line, line)
    # span → point with legs: the from-leg goes
    api = FakeAPI()
    line, made, moved, rm = cm.sync(api, pt, pool=[to_ok, {**from_old, "startDate": "2026-09-30T13:00:00.000+0000",
                                                            "dueDate": "2026-09-30T14:00:00.000+0000"}])
    check("7.booking lost its end: from-leg removed, to-leg kept",
          [t for _p, t in api.deleted] == [from_old["id"]] and not api.created and "no end to leave from" in line, line)
    # the live pool (review): pool=None reads the list, once
    api = FakeAPI(lists={LST: [to_ok, from_old]})
    line, made, moved, rm = cm.sync(api, BOOK)
    check("7.pool=None reads the commute list live, once", api.reads == [LST], api.reads)
    check("7.…and works on it: the from-leg moved, nothing created", len(api.updated) == 1 and not api.created, api.updated)
    api = FakeAPI(lists={LST: [to_ok, from_old]})
    api.fail_read = True
    line, made, moved, rm = cm.sync(api, BOOK)
    check("7.a failed live read checks nothing and says so (a reschedule never doubles)",
          line == cm.NOT_CHECKED and not api.created and not api.updated, (line, api.created))
    import cache as cache_store   # noqa: E402
    cache_store.set("all_tasks", [])   # earlier cases mirrored their legs here
    api = FakeAPI()
    api.fail_read = True
    line, made, moved, rm = cm.sync(api, BOOK, fresh_booking=True)
    check("7.…but a brand-new booking still gets its legs from the cache view",
          len(api.created) == 2, api.created)

    # ── 8. drop ─────────────────────────────────────────────────────────────────
    api = FakeAPI()
    line, n = cm.drop(api, B1, pool=[to_ok, from_old, done_to, hand, notmine])
    check("8.only the OPEN linked legs are deleted",
          sorted(t for _p, t in api.deleted) == sorted([to_ok["id"], from_old["id"]]), api.deleted)
    check("8.count + toast", n == 2 and line == "🚗 Commute ×2 removed", (n, line))
    api = FakeAPI()
    line, n = cm.drop(api, B1, pool=[hand])
    check("8.nothing linked: silent", n == 0 and line == "")
    api = FakeAPI()
    line, n = cm.drop(api, B1, pool=[to_ok, copy], ref=BOOK)
    check("8.ref guard: a copied leg on another day is left alone (review)",
          [t for _p, t in api.deleted] == [to_ok["id"]], api.deleted)
    api = FakeAPI(lists={LST: [to_ok, from_old]})
    line, n = cm.drop(api, B1)
    check("8.pool=None reads live", api.reads == [LST] and n == 2)
    api = FakeAPI()
    api.fail_read = True
    line, n = cm.drop(api, B1)
    check("8.a failed live read removes nothing and says so", line == cm.NOT_CHECKED and n == 0 and not api.deleted)

    # ── 9. the booking gate ─────────────────────────────────────────────────────
    check("9.CRM + tattoo tag", cm.is_booking(BOOK))
    check("9.CRM + consultation tag", cm.is_booking({**BOOK, "tags": ["📅consultation"]}))
    check("9.a Prepare task is not a booking", not cm.is_booking({**BOOK, "tags": ["📅prepare"]}))
    check("9.another list is not a booking", not cm.is_booking({**BOOK, "projectId": LST}))
    check("9._projectId (a cache row) counts", cm.is_booking({**BOOK, "projectId": None, "_projectId": CRM}))
    check("9.tag case is blind", cm.is_booking({**BOOK, "tags": ["📅Tattoo"]}))

    # ── 10. sweep: the manual road ──────────────────────────────────────────────
    NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    B3, B4, B5 = "6ab000000000000000000003", "6ab000000000000000000004", "6ab000000000000000000005"
    ahead = {**BOOK, "id": B3}                                              # no legs yet → 2 added
    past = {**BOOK, "id": B4, "startDate": "2026-09-20T10:00:00+0000",     # happened → untouched
            "dueDate": "2026-09-20T13:00:00+0000"}
    undated = {**BOOK, "id": B5, "startDate": None, "dueDate": None}       # its leg → removed
    prep = {**BOOK, "id": "6ab000000000000000000006", "tags": ["📅prepare"]}
    undated_leg = leg("u1", "to", B5, "2026-10-03T08:30:00.000+0000", "2026-10-03T10:00:00.000+0000")
    stray_future = leg("s1", "to", "6ab00000000000000000dead", "2026-10-09T08:30:00.000+0000",
                       "2026-10-09T10:00:00.000+0000")
    stray_past = leg("s2", "to", "6ab00000000000000000dead", "2026-09-01T08:30:00.000+0000",
                     "2026-09-01T10:00:00.000+0000")
    past_leg_open = leg("p1", "from", B4, "2026-09-20T13:00:00.000+0000", "2026-09-20T14:00:00.000+0000")
    api = FakeAPI(lists={LST: [undated_leg, stray_future, stray_past, past_leg_open],
                         CRM: [ahead, past, undated, prep]})
    line = cm.sweep(api, now=NOW)
    check("10.reads each list once", sorted(api.reads) == sorted([LST, CRM]), api.reads)
    check("10.the booking ahead gets two legs", len(api.created) == 2
          and all(f"/tasks/{B3})" in t["content"] for t in api.created), api.created)
    check("10.the undated booking's leg and the future stray go; past legs stay",
          sorted(t for _p, t in api.deleted) == sorted([undated_leg["id"], stray_future["id"]]), api.deleted)
    check("10.nothing moved", not api.updated)
    check("10.the toast counts", line == "🚗 Sync · 2 added · 2 removed", line)
    api = FakeAPI(lists={LST: [], CRM: [past]})
    check("10.nothing ahead", cm.sweep(api, now=NOW) == "🚗 Sync · nothing ahead")
    api = FakeAPI(lists={LST: [to_ok, {**from_old, "startDate": "2026-09-30T13:00:00.000+0000",
                                       "dueDate": "2026-09-30T14:00:00.000+0000"}], CRM: [BOOK]})
    check("10.a booking already right counts as fine", cm.sweep(api, now=NOW) == "🚗 Sync · 1 booking fine")

    print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
