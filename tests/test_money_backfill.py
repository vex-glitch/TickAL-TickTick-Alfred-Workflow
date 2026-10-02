#!/usr/bin/env python3
"""🕰 Backfill a month: src/money_backfill.py (the note parser and the entry
plan), the xact.moneybackfill verb (dialogs and every writer stubbed, no
network) and the browse month picker (ctx:crmmoney:backfill).

Vex 2026-10-02: a guest-spot month without the Mac left August at one
session; the hand fix was a logbook with one entry per day from the 💰
money note at ~75€/h. This pins that as the verb: pick the month, type
the total (prefilled from the note), type the rate, one archived logbook.
Run: python3 tests/test_money_backfill.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import os
    import sys
    from datetime import date

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(ROOT, "src"))
    sys.path.insert(0, os.path.join(ROOT, "Scripts"))
    os.environ["crm_records_list_id"] = "6a4e50e9842a1194a7c681e1"
    os.environ["crm_list_id"] = "69fed9d51fe6d10d8510bf15"

    import money_backfill as mb         # noqa: E402

    FAILS, COUNT = [], [0]

    def check(name, cond, detail=""):
        COUNT[0] += 1
        if cond:
            print(f"  ok  {name}")
        else:
            print(f"FAIL  {name}  {detail}")
            FAILS.append(name)

    # the real August note, verbatim
    AUG = ("---\n# ::3490::\n---\n# Week1 (01-02)\n\t* 1st Sat - 20\n\t* 2nd Sun - 125\n\t* ::145::\n---\n"
           "## Week 2 (03-10)\n\t* 3rd Mon - 275\n\t* 4th Tue - 160\n\t* 5th Wed - 60\n\t* 6th Thu - 0\n"
           "\t* 7th Fri - 0\n\t* 8th Sat - 0\n\t* 9th Sun - 0\n\t* ::495::\n---\n## Week 3 (10-17)\n"
           "\t* 10th Mon - 0\n\t* 11th Tue - 0\n\t* 12th Wed - 195\n\t* 13th Thu - 80\n\t* 14th Fri - 0\n"
           "\t* 15th Sat - 110\n\t* 16th Sun - 150\n\t* ::535::\n---\n## Week 4 (17-23)\n\t* 17th Mon - 250\n"
           "\t* 18th Tue - 210\n\t* 19th Wed - 0\n\t* 20th Thu - 180\n\t* 21st Fri - 210\n\t* 22nd Sat - 490\n"
           "\t* 23rd Sun - 380\n\t* ::1720::\n---\n## Week 5 (24-30)\n\t* 24th Mon - 0\n\t* 25th Tue - 120\n"
           "\t* 26th Wed - 0\n\t* 27th Thu - 0\n\t* 28th Fri - 0\n\t* 29th Sat - 125\n\t* 30th Sun - 350\n"
           "\t* 31st Mon - 0\n\t* ::595::\n---\n# Total = ~::3490::~")
    TODAY = date(2026, 10, 2)

    # ── the parser ─────────────────────────────────────────────────────
    days = mb.parse_day_amounts(AUG, 2026, 8)
    check("18 money days, zero days skipped", len(days) == 18, sorted(days))
    check("the days add up to the note's total", sum(days.values()) == 3490, sum(days.values()))
    check("1st/2nd/3rd/22nd ordinals all read", days[1] == 20 and days[2] == 125 and days[3] == 275 and days[22] == 490)
    check("week sums and the title total never read as days", 145 not in days.values() or days.get(1) == 20)
    check("note total from the title tail", mb.note_total("2026 August • MT - 3490", "") == 3490)
    check("note total from the # ::N:: line when the title has none", mb.note_total("2026 August", AUG) == 3490)
    check("no total at all → None", mb.note_total("2026 August", "nothing") is None)
    check("a day the month does not have is ignored", mb.parse_day_amounts("* 31st - 50", 2026, 9) == {})
    check("dash bullets and no weekday read too", mb.parse_day_amounts("- 4th - 90\n* 5th Tue - 10", 2026, 8) == {4: 90, 5: 10})

    # ── typed amounts ──────────────────────────────────────────────────
    check("3490 / 3490€ / 3 490 / 3.490,50", [mb.parse_amount(x) for x in ("3490", "3490€", "3 490", "3.490,50")] == [3490, 3490, 3490, 3490.5])
    check("'75,5' is 75.5 and garbage is None", mb.parse_amount("75,5") == 75.5 and mb.parse_amount("abc") is None)

    # ── the plan ───────────────────────────────────────────────────────
    entries, hours, mode = mb.plan_entries(2026, 8, 3490, 75, days=days, today=TODAY)
    check("days mode when the note carries the total", mode == "days" and len(entries) == 18)
    check("S1..S18 by date", [e[1] for e in entries] == [f"S{i}" for i in range(1, 19)] and entries[0][0] == "2026-08-01" and entries[-1][0] == "2026-08-30")
    check("quarter-hour durations in the entry shape", entries[0][2] == "0h15" and entries[13][2] == "6h30", [e[2] for e in entries])
    check("amounts as typed, no symbol", entries[13][3] == "490")
    check("46.5h over the month, so ~75€/h", hours == 46.5, hours)
    e2, h2, m2 = mb.plan_entries(2026, 8, 3000, 75, days=days, today=TODAY)
    check("note disagrees with the typed total → one lump entry on the last day", m2 == "lump" and e2 == [("2026-08-31", "S1", "40h00", "3000")], e2)
    e3, h3, m3 = mb.plan_entries(2026, 8, 3490, 75, days={}, today=TODAY)
    check("no note → one lump entry", m3 == "lump" and e3[0][3] == "3490" and h3 == 46.5, (e3, h3))
    e4, _h4, _m4 = mb.plan_entries(2026, 10, 600, 100, days={}, today=TODAY)
    check("the current month lands on today, not its last day", e4[0][0] == "2026-10-02", e4)
    check("a tiny amount is still a quarter hour", mb.quarter_hours(1, 75) == 0.25 and mb.duration_str(0.25) == "0h15")
    check("2.25h → 2h15, 5h → 5h00", mb.duration_str(2.25) == "2h15" and mb.duration_str(5) == "5h00")
    check("month choices: this month first, 25 rows, year rolls", mb.month_choices(TODAY)[:3] == [(2026, 10), (2026, 9), (2026, 8)] and len(mb.month_choices(TODAY)) == 25 and (2025, 12) in mb.month_choices(TODAY))
    check("titles", mb.logbook_title(2026, 8) == "Guest spot • August 2026" and mb.month_label(2026, 8) == "Aug 2026")

    # ── the verb, every door stubbed ───────────────────────────────────
    import xact                          # noqa: E402
    import crm_records as cr             # noqa: E402
    import areas                         # noqa: E402

    LOG = []
    NOTES = []            # records notes the fake CRM holds
    ANSWERS = []          # queued dialog answers
    MONEY_NOTES = [{"id": "mn1", "kind": "NOTE", "projectId": "6a4bd07e4e3c910368319b6d",
                    "title": "2026 August • MT - 3490", "content": AUG}]

    class _CS:
        def get(self, k):
            return list(MONEY_NOTES) if k == "all_notes" else []
    xact.cache_store = _CS()
    xact._records_ready = lambda: True
    xact._crm_say = lambda msg: LOG.append(("say", msg))
    xact._ask = lambda prompt, **kw: (LOG.append(("ask", prompt, kw.get("default"))) or ANSWERS.pop(0))

    cr.records_notes = lambda tag=None: [n for n in NOTES if not tag or tag in (n.get("tags") or [])]
    cr.create_customer = lambda name, **kw: (LOG.append(("cust", name)) or {"id": "c1", "title": f"👤 {name}", "tags": [areas.CUSTOMER_TAG]})
    def _create_logbook(cust, tattoo, started=None, **kw):
        LOG.append(("logbook", cust["id"], tattoo, started))
        return {"id": "lb1", "title": f"🎨 {cust['title'][2:]} • {tattoo}", "content": "👤 x · Started %s · Finished -\nPaid: - · 0 sessions\n\n## Sessions\n\n## Notes\n" % started}
    cr.create_logbook = _create_logbook
    cr._patch_cache = lambda tid, **f: LOG.append(("cache", tid))
    cr.append_session = lambda pid, tid, marker, duration="", charged="", text="", when=None: (LOG.append(("entry", when, marker, duration, charged, bool(text))) or ("", "", 0, ""))
    cr.finish_logbook = lambda pid, tid, when=None: LOG.append(("finish", tid, when))
    class _API:
        def update_task(self, tid, pid, current=None, **f):
            LOG.append(("update", tid, "🎬 ➖" in f.get("content", "")))
        def get_project_data(self, pid):
            LOG.append(("live", pid)); return {"tasks": []}
    cr._api = lambda: _API()

    def run(ym, answers):
        LOG.clear(); ANSWERS[:] = answers
        xact.moneybackfill(ym)
        return list(LOG)

    log = run("2026-08", ["", ""])          # OK through both questions
    asks = [x for x in log if x[0] == "ask"]
    check("the total question is prefilled from the money note", asks[0][2] == "3490" and "3490" in asks[0][1], asks)
    check("the rate question defaults to 75", asks[1][2] == "75", asks)
    check("the Guest spot customer is created when missing", ("cust", "Guest spot") in log)
    check("the logbook is born 'August 2026' started on the first money day", ("logbook", "c1", "August 2026", "2026-08-01") in log, log)
    check("the 🎬 ➖ header is written", ("update", "lb1", True) in log)
    ents = [x for x in log if x[0] == "entry"]
    check("18 entries, one per money day, S1..S18", len(ents) == 18 and [e[2] for e in ents] == [f"S{i}" for i in range(1, 19)], ents[:3])
    check("only the first entry carries the explanation", [e[5] for e in ents] == [True] + [False] * 17)
    check("the 22nd reads 6h30 · 490", ("entry", "2026-08-22", "S14", "6h30", "490", False) in log)
    check("finished on the last money day", ("finish", "lb1", "2026-08-30") in log)
    say = [x for x in log if x[0] == "say"][-1][1]
    check("the toast says what landed", "Aug 2026 backfilled" in say and "3490€" in say and "18 days" in say and "46.5h" in say and "75€/h" in say, say)
    check("no live read when the cache holds the note", not any(x[0] == "live" for x in log))

    log = run("2026-08", ["2000", "100"])   # typed total disagrees with the note
    ents = [x for x in log if x[0] == "entry"]
    check("a total the note does not carry → one lump entry at the typed rate", ents == [("entry", "2026-08-31", "S1", "20h00", "2000", True)], ents)

    MONEY_NOTES.clear()
    log = run("2026-07", ["1500", ""])     # no note anywhere
    check("no note: the cache miss is followed by ONE live read of the money list", [x for x in log if x[0] == "live"] == [("live", "6a4bd07e4e3c910368319b6d")])
    asks = [x for x in log if x[0] == "ask"]
    check("no note: the total question has no prefill", asks[0][2] == "", asks)
    ents = [x for x in log if x[0] == "entry"]
    check("no note: one entry on the month's last day, 20h at 75", ents == [("entry", "2026-07-31", "S1", "20h00", "1500", True)], ents)

    log = run("2026-07", [None])
    check("Esc on the total cancels, nothing written", ("say", "Cancelled") in log and not any(x[0] in ("cust", "logbook", "entry") for x in log))
    log = run("2026-07", ["", ""])
    check("empty total with no note cancels", any(x[0] == "say" and "no total" in x[1] for x in log) and not any(x[0] == "entry" for x in log))
    log = run("2099-01", [])
    check("a future month is refused", any("not happened" in x[1] for x in log if x[0] == "say"))
    log = run("2026-13", [])
    check("a bad month is refused", any("Bad month" in x[1] for x in log if x[0] == "say"))
    NOTES.append({"id": "old", "title": "🏛️ Guest spot • July 2026", "tags": [areas.ARCHIVE_TAG]})
    log = run("2026-07", ["1500", ""])
    check("a month already backfilled is refused before any question", any("already backfilled" in x[1] for x in log if x[0] == "say") and not any(x[0] == "ask" for x in log))

    # ── the picker screen ──────────────────────────────────────────────
    import browse                        # noqa: E402
    import datetime as _dt
    browse._records_gate = lambda: None
    cr.all_entries = lambda: [("2026-08-15", True, 3490.0, "€", False, 2790)]
    cr.cut_percent = lambda: 0

    class _Frozen(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 2)
    _real = _dt.date
    _dt.date = _Frozen
    try:
        rows = browse.render_crmmoney("backfill", "")
        home = browse.render_crmmoney("", "")
    finally:
        _dt.date = _real
    rows = [r for r in rows if r.get("uid") != "back"]
    check("picker: this month first, 25 months", rows[0]["uid"] == "bf-2026-10" and len(rows) == 25, [r["uid"] for r in rows[:3]])
    aug = next(r for r in rows if r["uid"] == "bf-2026-08")
    check("picker: a month shows what the CRM holds", "3490€" in aug["title"] and "1 session" in aug["title"] and "46.5h" in aug["title"], aug["title"])
    check("picker: ⏎ fires the verb for that month", aug["arg"] == "xact:moneybackfill:2026-08")
    jul = next(r for r in rows if r["uid"] == "bf-2026-07")
    check("picker: a month already backfilled is marked and dead", "✅ backfilled" in jul["title"] and jul["valid"] is False, jul)
    check("picker: dead chords pinned", all(r["mods"]["shift"]["valid"] is False and r["mods"]["alt"]["valid"] is False for r in rows))
    bf = next(r for r in home if r.get("uid") == "mo-backfill")
    last = [r for r in home if r.get("uid") != "back"][-1]
    check("home: 🕰 Backfill a month is the last row and drills the picker", last["uid"] == "mo-backfill" and bf["arg"] == "xact:crmbrowse:ctx:crmmoney:backfill", [r.get("uid") for r in home])

    print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} ok")
    if FAILS:
        print("FAILED:", FAILS)
        sys.exit(1)
