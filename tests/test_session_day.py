#!/usr/bin/env python3
"""📅 A session entry is dated on the SESSION's day, not the day it is
ticked (Vex 2026-11-05: "the other day I forgot to check off some session
from previous month and did it in this month, couple of days difference
... in money it is showing as I made that in this month"). The roads over
a fake API with the dialogs answered by hand: ✅ Happened, 👻 No-show, 🚫
Cancelled and 🔁 Rescheduled hand append_session the task's OWN day when
it is before today; a task dated today, ahead of today or undated lands
today (None, append_session's default); an explicit `when` (the adopt
chain's date dialog) wins; the Finished stamp of a final session follows
the day; the toast carries ' · 📅 28 Sep' only when the day is not today.
Plus dateutil.task_day over zones (the ONE reading, shared with the meal
plan). Nothing reaches the network; HOME is a scratch dir before any repo
import, so the cache never touches ~/.ticktick_alfred.

    python3 tests/test_session_day.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import io
    import os
    import sys
    import tempfile
    from datetime import date

    SCRATCH = tempfile.mkdtemp(prefix="tickal_sday_")
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
    import crm_records as cr         # noqa: E402
    import dateutil as du            # noqa: E402
    import xact                      # noqa: E402

    assert cache_store.CACHE_DIR.startswith(SCRATCH), cache_store.CACHE_DIR

    FAILS, COUNT = [], [0]


    def check(name, cond, detail=""):
        COUNT[0] += 1
        print(f"  ok  {name}" if cond else f"FAIL  {name}  {detail}")
        if not cond:
            FAILS.append(name)


    LB_TID = "6a5f18fd8f0846c75ce1d09c"
    REC = f"[🎨 Marko • Sleeve](https://ticktick.com/webapp/#p/{REC_PID}/tasks/{LB_TID})"
    B1 = "6ab000000000000000000001"
    TODAY = date.today()


    def booking(start=None, due=None, tz="Europe/Berlin", **extra):
        row = {"id": B1, "projectId": CRM, "_projectId": CRM, "kind": "TEXT",
               "title": f"{REC} S2 - 400", "tags": ["📅tattoo"], "status": 0,
               "timeZone": tz}
        if start:
            row["startDate"] = start
            row["dueDate"] = due or start
        row.update(extra)
        return row


    class FakeAPI:
        def __init__(self, rows):
            self.rows = rows
            self.completed, self.deleted = [], []

        def get_project_data(self, pid):
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
    SAID, LOGGED, FINISHED = [], [], []
    CHOOSE = {"outcome": "✅ Happened"}
    DLG = {"Final session": "More to come", "schedule S": "Later",
           "rebook": "Later"}
    xact._crm_say = SAID.append
    xact._say_now = SAID.append
    xact._records_ready = lambda: True
    xact._photo_source = lambda: ""
    xact._record_by_id = lambda tid: {"id": tid, "title": "🎨 Marko • Sleeve",
                                      "content": "", "tags": ["🗂️logbook"],
                                      "projectId": REC_PID}
    xact._crm_session_prefill = lambda *a, **k: None
    xact._run_trigger = lambda *a, **k: None
    xact._eagle_archive_folder = lambda *a, **k: None
    xact.reopen_actions = lambda *a, **k: None
    xact.person_autolog = lambda *a, **k: ""
    xact.routine_checkin = lambda *a, **k: ""
    xact._choose = lambda prompt, options, title="TickAL", default=None: CHOOSE["outcome"]
    xact._ask = lambda prompt, *a, **k: ""          # OK skips every ask
    xact._dialog = lambda prompt, buttons, default, giveup=None: next(
        (v for k, v in DLG.items() if k in prompt), default)
    xact.open = lambda *a, **k: io.StringIO()       # the act-again context file stays in /tmp's peace


    CUTS = []

    def _append(log_pid, log_tid, marker, duration="", charged="", text="", when=None, cut=None):
        LOGGED.append((marker, when))
        CUTS.append(cut)
        return ("content", "400€", 2, "🎨 Marko • Sleeve")
    cr.append_session = _append
    cr.finish_logbook = lambda pid, tid, when=None: FINISHED.append(when)


    def fresh(rows):
        cache_store.set("all_tasks", [dict(t) for t in rows])
        cache_store.set("all_notes", [])
        cache_store.set("completed_tasks", [])
        api = FakeAPI([dict(t) for t in rows])
        xact._api = lambda: api
        cr._api = lambda: api            # the cache-miss live read goes here too
        SAID.clear(); LOGGED.clear(); FINISHED.clear()
        return api


    def run(row, outcome="✅ Happened", **kw):
        api = fresh([row])
        CHOOSE["outcome"] = outcome
        xact.sessiondone(CRM, B1, **kw)
        return api


    SEP = booking("2026-09-28T12:00:00.000+0000", "2026-09-28T15:00:00.000+0000")

    # ── the four roads carry the task's day ─────────────────────────────────────
    api = run(SEP)
    check("✅ Happened: the entry is dated on the session's day, not today",
          LOGGED == [("S2", "2026-09-28")] and api.completed == [B1], (LOGGED, api.completed))
    check("…and the toast says where the money went",
          SAID[-1].startswith("✅ S2 done") and " · 📅 28 Sep" in SAID[-1], SAID)
    run(SEP, "👻 No-show")
    check("👻 No-show: dated on the session's day, chip on the toast",
          LOGGED == [("no-show", "2026-09-28")] and " · 📅 28 Sep" in SAID[-1], (LOGGED, SAID))
    run(SEP, "🚫 Cancelled")
    check("🚫 Cancelled: dated on the session's day",
          LOGGED == [("cancelled", "2026-09-28")] and " · 📅 28 Sep" in SAID[-1], (LOGGED, SAID))
    api = run(SEP, "🔁 Rescheduled")
    check("🔁 Rescheduled: the trace is dated on the session's day, the task stays open",
          LOGGED == [("rescheduled", "2026-09-28")] and api.completed == [] and "📅 28 Sep" in SAID[-1], (LOGGED, api.completed, SAID))

    # ── the final session's Finished stamp follows ───────────────────────────
    DLG["Final session"] = "Archive"
    run(SEP)
    check("a final session: Finished is stamped on the session's day",
          FINISHED == ["2026-09-28"], FINISHED)
    DLG["Final session"] = "More to come"

    # ── today, ahead of today, undated: today ────────────────────────────────
    run(booking(f"{TODAY.isoformat()}T12:00:00.000+0000"))
    check("a session dated today lands today (no chip)",
          LOGGED == [("S2", None)] and "📅" not in SAID[-1], (LOGGED, SAID))
    run(booking("2099-01-05T12:00:00.000+0000"))
    check("a session dated ahead of today lands today - money never lands on a day that has not happened",
          LOGGED == [("S2", None)] and "📅" not in SAID[-1], (LOGGED, SAID))
    run(booking())
    check("an undated task lands today", LOGGED == [("S2", None)], LOGGED)

    # ── an explicit day (the adopt chain's dialog) wins ──────────────────────
    run(SEP, when="2026-09-01")
    check("an explicit `when` wins over the task's day",
          LOGGED == [("S2", "2026-09-01")] and " · 📅 1 Sep" in SAID[-1], (LOGGED, SAID))

    # ── the day is read in the task's zone ───────────────────────────────────
    run(booking("2026-09-27T22:00:00.000+0000", tz="Europe/Berlin", isAllDay=True))
    check("an all-day Berlin task (midnight Berlin, stored in UTC) is its Berlin day",
          LOGGED == [("S2", "2026-09-28")], LOGGED)
    run(booking("2026-09-27T23:00:00.000+0000", tz="Europe/London", isAllDay=True))
    check("…and a London one its London day", LOGGED == [("S2", "2026-09-28")], LOGGED)

    # ── a cache miss: the live row carries the day ───────────────────────────
    api = fresh([])
    api.rows = [dict(SEP)]
    CHOOSE["outcome"] = "✅ Happened"
    xact.sessiondone(CRM, B1)
    check("a task the cache does not hold: the live read gives title AND day",
          LOGGED == [("S2", "2026-09-28")], LOGGED)

    # ── the helpers, pure ────────────────────────────────────────────────────
    check("_session_day: before today → the day; today / ahead / undated → None",
          xact._session_day(SEP, today=date(2026, 10, 2)) == "2026-09-28"
          and xact._session_day(SEP, today=date(2026, 9, 28)) is None
          and xact._session_day(SEP, today=date(2026, 9, 1)) is None
          and xact._session_day({}, today=date(2026, 10, 2)) is None)
    check("_dated_chip: another day → ' · 📅 28 Sep', today / None → ''",
          xact._dated_chip("2026-09-28") == " · 📅 28 Sep" and xact._dated_chip(None) == ""
          and xact._dated_chip(TODAY.isoformat()) == "" and xact._dated_chip("2024") == " · 📅 2024")
    check("dateutil.task_day: startDate first, dueDate when there is none, None when neither / unreadable",
          du.task_day({"startDate": "2026-09-28T12:00:00.000+0000", "dueDate": "2026-09-29T12:00:00.000+0000"}) == date(2026, 9, 28)
          and du.task_day({"dueDate": "2026-09-29T12:00:00.000+0000"}) == date(2026, 9, 29)
          and du.task_day({}) is None and du.task_day({"dueDate": "soon"}) is None)
    check("dateutil.task_day: 21T22Z is Mon 21 in London, Tue 22 in Berlin",
          du.task_day({"timeZone": "Europe/London", "startDate": "2026-09-21T22:00:00.000+0000"}) == date(2026, 9, 21)
          and du.task_day({"timeZone": "Europe/Berlin", "startDate": "2026-09-21T22:00:00.000+0000"}) == date(2026, 9, 22))
    check("dateutil.local_zone is a named zone (DST-aware for any date)",
          hasattr(du.local_zone(), "key") or du.local_zone() is not None)

    # ── 🫵 the percentage question (Vex 2026-11-05: "one of the pop up
    # prompts after how much was charged should be 'What is your
    # percentage'") ─────────────────────────────────────────────────────────
    ASKED = []

    def _ask_by(prompt, *a, **k):
        ASKED.append((prompt, k.get("default")))
        if "Charged?" in prompt:
            return "400"
        if "percentage" in prompt:
            return "60"
        return ""
    xact._ask = _ask_by
    ASKED.clear(); run(SEP)
    pct = [i for i, (p_, _d) in enumerate(ASKED) if "percentage" in p_]
    check("a priced session asks the percentage RIGHT AFTER the price, prefilled with the logbook's (the global 50 here)",
          pct == [2] and "Charged?" in ASKED[1][0] and ASKED[2][1] == "50" and "(OK = 50%" in ASKED[2][0], ASKED)
    check("…and the entry carries the answer", CUTS[-1] == 60.0 and LOGGED == [("S2", "2026-09-28")], (CUTS, LOGGED))
    xact._ask = lambda prompt, *a, **k: ASKED.append((prompt, None)) or ("gift" if "Charged?" in prompt else "")
    ASKED.clear(); run(SEP)
    check("a gift asks no percentage, the entry inherits the logbook's",
          not any("percentage" in p_ for p_, _d in ASKED) and CUTS[-1] is None and LOGGED == [("S2", "2026-09-28")], (ASKED, CUTS))
    xact._ask = lambda prompt, *a, **k: ASKED.append((prompt, None)) or ""
    ASKED.clear(); run(SEP)
    check("a skipped price asks no percentage either", not any("percentage" in p_ for p_, _d in ASKED) and CUTS[-1] is None, (ASKED, CUTS))
    xact._ask = lambda prompt, *a, **k: ""
    check("the prompt helpers", xact._cut_prompt(50.0) == "What is your percentage? (OK = 50% · Esc cancels)"
          and xact._cut_prompt(None) == "What is your percentage? (OK skips · Esc cancels)"
          and xact._cut_default(62.5) == "62.5" and xact._cut_default(None) == ""
          and xact._cut_wanted(["2h", "400"]) is True and xact._cut_wanted(["2h", "gift"]) is False
          and xact._cut_wanted(["2h", ""]) is False and xact._cut_wanted([]) is False)

    print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
