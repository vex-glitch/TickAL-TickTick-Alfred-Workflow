#!/usr/bin/env python3
"""🚗 A session marked done ticks its commutes off (Vex 2026-10-09: "when I
mark session as done, commute that was added for that session is ticked
off as well"). The roads, over a fake API with the dialogs answered by
hand: ✅ Session done - Happened and No-show tick the two legs AFTER the
session's own complete, Cancelled still trashes them, and the near guard
holds either way (a copied leg weeks away stays; find_task after the
cache drop had voided that guard on the cancel road); a dead commute
list leaves the session done and logged with the toast saying not
checked; the 📕 backlog's "complete it too"; and a plain ⇧ complete on a
booking row through dispatch, where a plain task costs no commute-list
read. Nothing reaches the network; HOME is a scratch dir before any repo
import, so the cache never touches ~/.ticktick_alfred.

    python3 tests/test_commute_done.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import contextlib
    import io
    import os
    import sys
    import tempfile

    SCRATCH = tempfile.mkdtemp(prefix="tickal_cmdone_")
    os.environ["HOME"] = SCRATCH              # before ANY repo import
    os.environ["TICKAL_NO_SETTLE"] = "1"
    os.environ.setdefault("TICKAL_RUN_DIR", os.path.join(SCRATCH, "run"))
    os.environ["TICKAL_NO_PERSIST"] = "1"
    os.environ["token"] = "fake-token"        # cfg.get_token(): no Keychain
    CRM = "69fed9d51fe6d10d8510bf15"
    REC_PID = "6a4e50e9842a1194a7c681e1"
    os.environ["crm_list_id"] = CRM
    os.environ["crm_records_list_id"] = REC_PID
    os.environ["crm_tags"] = "📅consultation 📅tattoo"
    os.environ["crm_prepare_tag"] = "📅prepare"
    os.environ["crm_records_tags"] = "🗂️Customer, 🗂️Logbook, 🗂️Lead, 🗂️Archive"

    REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _p in ("src/lib", "src", "Scripts"):
        sys.path.insert(0, os.path.join(REPO, _p))
    import cache as cache_store      # noqa: E402
    import commute as cm             # noqa: E402
    import crm_records as cr         # noqa: E402
    import dispatch                  # noqa: E402
    import xact                      # noqa: E402

    assert cache_store.CACHE_DIR.startswith(SCRATCH), cache_store.CACHE_DIR

    FAILS, COUNT = [], [0]


    def check(name, cond, detail=""):
        COUNT[0] += 1
        print(f"  ok  {name}" if cond else f"FAIL  {name}  {detail}")
        if not cond:
            FAILS.append(name)


    LST = cm.list_id()
    LB_TID = "6a5f18fd8f0846c75ce1d09c"
    REC = f"[🎨 Marko • Sleeve](https://ticktick.com/webapp/#p/{REC_PID}/tasks/{LB_TID})"
    B1 = "6ab000000000000000000001"
    BOOK = {"id": B1, "projectId": CRM, "_projectId": CRM, "kind": "TEXT",
            "title": f"{REC} S2 - 400", "tags": ["📅tattoo"], "status": 0,
            "startDate": "2026-10-09T10:00:00.000+0000",
            "dueDate": "2026-10-09T13:00:00.000+0000"}
    PLAIN = {"id": "6ab000000000000000000009", "projectId": "someList",
             "_projectId": "someList", "title": "Buy milk", "tags": [], "status": 0}


    def leg(tid, word, start, end):
        return {"id": tid.ljust(24, "0"), "projectId": LST, "_projectId": LST,
                "title": "Commute", "status": 0,
                "content": f"🚗 {word} {cm.booking_link(CRM, B1, BOOK['title'])}",
                "startDate": start, "dueDate": end}


    TO = leg("to1", "to", "2026-10-09T08:30:00.000+0000", "2026-10-09T10:00:00.000+0000")
    FROM = leg("fr1", "from", "2026-10-09T13:00:00.000+0000", "2026-10-09T14:00:00.000+0000")
    # a leg the app (or 📑 Duplicate) copied weeks away: still links B1
    COPY = leg("cp1", "to", "2026-10-30T08:30:00.000+0000", "2026-10-30T10:00:00.000+0000")


    class FakeAPI:
        """One pool of rows is the server: the commute list is read live off
        it (open rows only, like GET project data), completes and deletes
        change it."""
        def __init__(self, rows):
            self.rows = rows
            self.completed, self.deleted, self.reads = [], [], []
            self.fail_read = False

        def get_project_data(self, pid):
            self.reads.append(pid)
            if self.fail_read:
                raise RuntimeError("read boom")
            return {"tasks": [dict(t) for t in self.rows
                              if t.get("projectId") == pid and not t.get("status")]}

        def get_task(self, pid, tid):
            for t in self.rows:
                if t["id"] == tid:
                    return dict(t)
            raise RuntimeError("404")

        def complete_task(self, pid, tid, task_data=None):
            self.completed.append(tid)
            for t in self.rows:
                if t["id"] == tid:
                    t["status"] = 2
            return True

        def delete_task(self, pid, tid):
            self.deleted.append(tid)
            self.rows = [t for t in self.rows if t["id"] != tid]
            return True


    # ── the dialogs, answered by hand ───────────────────────────────────────────
    SAID, LOGGED = [], []
    CHOOSE = {"outcome": "✅ Happened"}
    DLG = {"Final session": "More to come", "schedule S": "Later",
           "rebook": "Later", "Log as?": "S1", "complete it too": "Complete"}
    xact._crm_say = SAID.append
    xact._say_now = SAID.append
    xact._records_ready = lambda: True
    xact._photo_source = lambda: ""
    xact._record_by_id = lambda tid: {"id": tid, "title": "🎨 Marko • Sleeve",
                                      "content": "", "tags": ["🗂️logbook"],
                                      "projectId": REC_PID}
    xact._crm_session_prefill = lambda *a, **k: None
    xact._run_trigger = lambda *a, **k: None
    xact.reopen_actions = lambda *a, **k: None
    xact.person_autolog = lambda *a, **k: ""
    xact.routine_checkin = lambda *a, **k: ""
    xact._choose = lambda prompt, options, title="TickAL", default=None: CHOOSE["outcome"]
    xact._ask = lambda prompt, *a, **k: ""          # OK skips every ask
    xact._ask_date = lambda prompt: "2026-10-09"
    xact._dialog = lambda prompt, buttons, default, giveup=None: next(
        (v for k, v in DLG.items() if k in prompt), default)


    def _append(log_pid, log_tid, marker, *a, **k):
        LOGGED.append(marker)
        return ("content", "400€", 2, "🎨 Marko • Sleeve")


    cr.append_session = _append


    def fresh(rows):
        """The hourly view and the server, from one set of rows."""
        cache_store.set("all_tasks", [dict(t) for t in rows])
        cache_store.set("all_notes", [])
        cache_store.set("completed_tasks", [])
        api = FakeAPI([dict(t) for t in rows])
        xact._api = lambda: api
        dispatch.TickTickAPI = lambda tok: api
        SAID.clear()
        LOGGED.clear()
        return api


    def run_dispatch(arg):
        sys.argv = ["dispatch.py", arg]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            dispatch.main()
        return buf.getvalue()


    # ── R1 ✅ Happened ──────────────────────────────────────────────────────────
    api = fresh([BOOK, PLAIN, TO, FROM, COPY])
    CHOOSE["outcome"] = "✅ Happened"
    xact.sessiondone(CRM, B1)
    check("R1 the session completes first, then its two legs",
          api.completed == [B1, TO["id"], FROM["id"]], api.completed)
    check("R1 the copied leg weeks away stays open (the near guard off the cache row)",
          COPY["id"] not in api.completed and not api.deleted, (api.completed, api.deleted))
    check("R1 the commute list was read live, once", api.reads == [LST], api.reads)
    check("R1 the entry was logged", LOGGED == ["S2"], LOGGED)
    check("R1 the toast carries the chip",
          SAID and SAID[-1].startswith("✅ S2 done") and SAID[-1].endswith(" · 🚗 Commute ×2 ticked"), SAID)
    check("R1 the legs leave the open cache with the session",
          sorted(t["id"] for t in cache_store.get("all_tasks")) == sorted([PLAIN["id"], COPY["id"]]),
          [t["id"] for t in cache_store.get("all_tasks")])
    check("R1 …and join the local completed log beside it",
          {t["id"] for t in cache_store.get("completed_tasks")} == {B1, TO["id"], FROM["id"]},
          cache_store.get("completed_tasks"))

    # ── R2 👻 No-show: he travelled, the legs happened ──────────────────────────
    api = fresh([BOOK, TO, FROM, COPY])
    CHOOSE["outcome"] = "👻 No-show"
    xact.sessiondone(CRM, B1)
    check("R2 no-show: the session completes, then its legs are ticked",
          api.completed == [B1, TO["id"], FROM["id"]], api.completed)
    check("R2 nothing trashed", not api.deleted, api.deleted)
    check("R2 logged as a no-show, the toast carries the chip",
          LOGGED == ["no-show"] and SAID[-1].startswith("👻 S2 no-show logged")
          and SAID[-1].endswith(" · 🚗 Commute ×2 ticked"), (LOGGED, SAID))

    # ── R3 🚫 Cancelled: the legs go, the guard holds ───────────────────────────
    api = fresh([BOOK, TO, FROM, COPY])
    CHOOSE["outcome"] = "🚫 Cancelled"
    xact.sessiondone(CRM, B1)
    check("R3 cancelled: the session completes, no leg is ticked", api.completed == [B1], api.completed)
    check("R3 the two legs go to Trash, the copied leg weeks away stays "
          "(the guard rides the row the cache held before the drop)",
          sorted(api.deleted) == sorted([TO["id"], FROM["id"]]), api.deleted)
    check("R3 the toast says removed", SAID[-1].endswith(" · 🚗 Commute ×2 removed"), SAID)

    # ── R4 a dead commute list ──────────────────────────────────────────────────
    api = fresh([BOOK, TO, FROM])
    api.fail_read = True
    CHOOSE["outcome"] = "✅ Happened"
    xact.sessiondone(CRM, B1)
    check("R4 the session is done and logged all the same",
          api.completed == [B1] and LOGGED == ["S2"], (api.completed, LOGGED))
    check("R4 the toast says not checked", SAID[-1].endswith(" · " + cm.NOT_CHECKED), SAID)

    # ── R5 📕 backlog: the open task for the logged session is completed too ────
    api = fresh([dict(BOOK, title=f"{REC} S1 - 400"), TO, FROM])
    xact.crmpast(LB_TID)
    check("R5 the open S1 task is completed, then its legs",
          api.completed == [B1, TO["id"], FROM["id"]], api.completed)
    check("R5 the toast carries the chip",
          any(s == "✅ S1 task completed · 🚗 Commute ×2 ticked" for s in SAID), SAID)

    # ── R6 a plain ⇧ complete on the booking row (dispatch complete:) ───────────
    api = fresh([BOOK, PLAIN, TO, FROM, COPY])
    out = run_dispatch(f"complete:{CRM}:{B1}:{BOOK['title']}")
    check("R6 ⇧ complete on a booking: the session, then its legs",
          api.completed == [B1, TO["id"], FROM["id"]], api.completed)
    check("R6 the toast ends with the chip",
          "completed" in out and out.rstrip().endswith("\n🚗 Commute ×2 ticked"), out)
    check("R6 the copied leg stays, nothing trashed",
          COPY["id"] not in api.completed and not api.deleted, (api.completed, api.deleted))

    # ── R7 a plain task costs nothing ───────────────────────────────────────────
    api = fresh([BOOK, PLAIN, TO, FROM])
    out = run_dispatch(f"complete:someList:{PLAIN['id']}:Buy milk")
    check("R7 a plain task: completed, no commute-list read, no chip",
          api.completed == [PLAIN["id"]] and api.reads == [] and "🚗" not in out, (api.completed, api.reads, out))

    print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
