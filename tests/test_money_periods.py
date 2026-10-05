#!/usr/bin/env python3
"""The 💰 money period tiers: year → months → weeks → sessions, and the
quarter with its All-quarters row (Scripts/browse.py render_crmmoney).

Vex 2026-10-02: "how much money per hour I am making ... impossible to do
that by month or by week. It is all over the place." So: a Year row (⏎ =
the months of the year, Jan first, each ⏎ = its weeks), a Quarter row (⏎ =
All quarters first, then the quarter's months), both on the money home
under All time, and Last quarter on the All-time ledger.

No network: crm_records.all_entries is a fake flat ledger and the records
gate is open. Dates are fixed around a frozen "today" (Fri 2 Oct 2026) so
the quarter and month cut-offs are stable on any day.
Run: python3 tests/test_money_periods.py
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

    import browse                       # noqa: E402
    import crm_records as cr            # noqa: E402

    FAILS, COUNT = [], [0]

    def check(name, cond, detail=""):
        COUNT[0] += 1
        if cond:
            print(f"  ok  {name}")
        else:
            print(f"FAIL  {name}  {detail}")
            FAILS.append(name)

    TODAY = date(2026, 10, 2)

    class _FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(TODAY.year, TODAY.month, TODAY.day)

    # (date, is_session, amount, sym, pre, minutes)
    LEDGER = [
        ("2025-11-03", True, 500.0, "€", False, 120),   # last year
        ("2026-02-10", True, 300.0, "€", False, 60),    # Q1
        ("2026-05-05", True, 400.0, "€", False, 120),   # Q2
        ("2026-07-14", True, 1000.0, "€", False, 240),  # Q3 Jul
        ("2026-09-22", True, 200.0, "€", False, 60),    # Q3 Sep (last week)
        ("2026-10-01", True, 150.0, "€", False, 30),    # Q4 Oct (this week)
    ]

    browse._records_gate = lambda: None
    browse._date = _FrozenDate
    cr.all_entries = lambda: list(LEDGER)
    cr.cut_percent = lambda: 0
    import datetime as _dt
    _real_date = _dt.date

    def render(sub, q=""):
        # render_crmmoney imports date inside; swap the module attribute
        _dt.date = _FrozenDate
        try:
            return browse.render_crmmoney(sub, q)
        finally:
            _dt.date = _real_date

    def titles(rows):
        return [r["title"] for r in rows if r.get("uid") != "back"]

    def by_uid(rows, uid):
        return next((r for r in rows if r.get("uid") == uid), None)

    # ── money home: order and drills ───────────────────────────────────
    home = render("")
    uids = [r.get("uid") for r in home]
    check("home order: All time, year, quarter, month, week, then the rest",
          uids[:5] == ["mo-total", "mo-year", "mo-quarter", "mo-month", "mo-week"],
          uids)
    yr = by_uid(home, "mo-year")
    check("year row sums the year", "2050€" in yr["title"] and "5 sessions" in yr["title"], yr["title"])
    check("year row carries hours and rate", "8.5h" in yr["title"] and "~241€/h" in yr["title"], yr["title"])
    check("year row drills yr:2026 via the clean-bar trampoline",
          yr["arg"] == "xact:crmbrowse:ctx:crmmoney:yr:2026", yr["arg"])
    qt = by_uid(home, "mo-quarter")
    check("quarter row names the quarter", "This quarter · Q4" in qt["title"], qt["title"])
    check("quarter row sums the quarter", "150€" in qt["title"] and "1 session" in qt["title"], qt["title"])
    check("quarter row drills qt:2026-Q4",
          qt["arg"] == "xact:crmbrowse:ctx:crmmoney:qt:2026-Q4", qt["arg"])
    check("every home row still pins the dead chords",
          all(r.get("mods", {}).get("shift", {}).get("valid") is False
              for r in home if r.get("uid") in ("mo-year", "mo-quarter")))

    # ── All time ledger: last quarter, drillable quarter and year rows ─
    per = render("periods")
    puids = [r.get("uid") for r in per]
    check("ledger order: week, last week, month, last month, quarter, last quarter, year, last year",
          puids[:8] == ["mo-w", "mo-lw", "mo-m", "mo-lm", "mo-q", "mo-lq", "mo-y", "mo-ly"], puids)
    lq = by_uid(per, "mo-lq")
    check("last quarter sums Jul-Sep", "1200€" in lq["title"] and "2 sessions" in lq["title"], lq["title"])
    check("last quarter span", lq["subtitle"].startswith("2026-07-01 → 2026-09-30"), lq["subtitle"])
    check("last quarter drills qt:2026-Q3", lq["arg"] == "xact:crmbrowse:ctx:crmmoney:qt:2026-Q3", lq["arg"])
    check("this quarter drills now", by_uid(per, "mo-q")["arg"] == "xact:crmbrowse:ctx:crmmoney:qt:2026-Q4")
    check("this year drills now", by_uid(per, "mo-y")["arg"] == "xact:crmbrowse:ctx:crmmoney:yr:2026")
    ly = by_uid(per, "mo-ly")
    check("last year drills yr:2025 and sums it", ly["arg"] == "xact:crmbrowse:ctx:crmmoney:yr:2025"
          and "500€" in ly["title"], ly)

    # ── yr: months of the year, Jan first, up to the current month ─────
    y26 = render("yr:2026")
    t = titles(y26)
    check("year screen: Jan..Oct, chronological", [x[:10] for x in t] == [
        "📅 Jan 2026", "📅 Feb 2026", "📅 Mar 2026", "📅 Apr 2026", "📅 May 2026",
        "📅 Jun 2026", "📅 Jul 2026", "📅 Aug 2026", "📅 Sep 2026", "📅 Oct 2026"], t)
    check("no future months", not any("Nov 2026" in x or "Dec 2026" in x for x in t))
    jul = by_uid(y26, "ym-2026-07")
    check("July sums its month with rate", "1000€" in jul["title"] and "4h" in jul["title"]
          and "~250€/h" in jul["title"], jul["title"])
    check("a month row drills its weeks (mw:)", jul["arg"] == "xact:crmbrowse:ctx:crmmoney:mw:2026-07", jul["arg"])
    check("empty month still listed as a row", "- · 0 sessions" in by_uid(y26, "ym-2026-01")["title"])
    y25 = render("yr:2025")
    check("a past year lists all twelve months", len(titles(y25)) == 12, len(titles(y25)))
    check("a future year is empty", titles(render("yr:2027")) == ["Nothing that year"], titles(render("yr:2027")))
    check("a bad year is refused", titles(render("yr:abc")) == ["Bad year"])

    # ── qt: All quarters first, then the quarter's months ──────────────
    q4 = render("qt:2026-Q4")
    t = titles(q4)
    check("quarter screen: All quarters row first", t[0].startswith("📅 All quarters 2026"), t)
    check("All quarters row sums the whole year", "2050€" in t[0], t[0])
    check("All quarters drills qts:2026", q4[0]["arg"] == "xact:crmbrowse:ctx:crmmoney:qts:2026", q4[0]["arg"])
    check("Q4 lists only October so far", [x[:10] for x in t[1:]] == ["📅 Oct 2026"], t)
    q3 = render("qt:2026-Q3")
    t3 = titles(q3)
    check("Q3 lists Jul, Aug, Sep", [x[:10] for x in t3[1:]] == ["📅 Jul 2026", "📅 Aug 2026", "📅 Sep 2026"], t3)
    check("a quarter month drills its weeks", q3[1]["arg"] == "xact:crmbrowse:ctx:crmmoney:mw:2026-07", q3[1]["arg"])
    check("a bad quarter is refused", titles(render("qt:2026-Q5")) == ["Bad quarter"])

    # ── qts: every quarter of the year so far ──────────────────────────
    qs = render("qts:2026")
    t = titles(qs)
    check("all quarters: Q1..Q4 of 2026, chronological",
          [x[:15] for x in t] == ["📅 Q1 2026 · Jan", "📅 Q2 2026 · Apr", "📅 Q3 2026 · Jul", "📅 Q4 2026 · Oct"], t)
    q3r = by_uid(qs, "yq-2026-Q3")
    check("Q3 sums Jul-Sep", "1200€" in q3r["title"] and "2 sessions" in q3r["title"] and "5h" in q3r["title"], q3r["title"])
    check("a quarter row drills qt:", q3r["arg"] == "xact:crmbrowse:ctx:crmmoney:qt:2026-Q3", q3r["arg"])
    check("a future year has no quarters", titles(render("qts:2027")) == ["Nothing that year"])

    # ── every money row carries the rate (Vex 2026-10-05: the month's
    # week-by-week screen had hours and no ~€/h; so did the week totals,
    # the tattoo list, the customers and the backfill picker) ──────────
    mw = render("mw:2026-10")
    w40 = by_uid(mw, "mw-2026-09-28")
    check("week-by-week: a week row carries hours AND rate",
          w40 and "0.5h" in w40["title"] and "~300€/h" in w40["title"], w40 and w40["title"])
    check("week-by-week: an empty week shows no rate chip",
          not any("/h" in r["title"] for r in mw if r.get("uid", "").startswith("mw-") and "0 sessions" in r["title"]))
    DET = [
        {"date": "2026-10-01", "marker": "S1", "is_s": True, "amount": 150.0,
         "sym": "€", "pre": False, "minutes": 30, "gratis": False,
         "lb": {"id": "lbx", "title": "🎨 Test • Tattoo"}, "cust_tid": "", "cust_title": ""},
        {"date": "2026-10-02", "marker": "S2", "is_s": True, "amount": None,
         "sym": "", "pre": False, "minutes": 60, "gratis": True,
         "lb": {"id": "lbx", "title": "🎨 Test • Tattoo"}, "cust_tid": "", "cust_title": ""},
    ]
    cr.entries_detailed = lambda: list(DET)
    wk = render("wk:2026-09-28")
    tot = by_uid(wk, "wk-sum")
    check("week screen: the totals row carries hours and rate",
          "0.5h" in tot["title"] and "~300€/h" in tot["title"], tot["title"])
    s1 = by_uid(wk, "wke-lbx-2026-10-01-S1")
    check("week screen: a charged session shows its own rate",
          s1 and s1["subtitle"].startswith("Thu 01 Oct · 0.5h · ~300€/h"), s1 and s1["subtitle"])
    s2 = by_uid(wk, "wke-lbx-2026-10-02-S2")
    check("week screen: a gratis session shows hours, never a rate",
          s2 and s2["subtitle"].startswith("Fri 02 Oct · 1h  |"), s2 and s2["subtitle"])
    LBX = {"id": "lbx", "title": "🎨 Test • Tattoo", "tags": [],
           "content": "👤 x · Started 2026-10-01 · Finished -\nPaid: - · 0 sessions\n\n"
                      "## Sessions\n### 2026-10-01 · S1 · 30m · 150€\n"
                      "### 2026-10-02 · S2 · 1h · gift\n\n## Notes\n"}
    cr.records_notes = lambda tag=None: [LBX]
    lb = render("lb:lbx")
    head = by_uid(lb, "lb-head")
    check("logbook screen: the head reads the symbol off the bare total",
          "150€ · 2 sessions · 🖤 1 · 0.5h · ~300€/h" in head["title"], head["title"])
    check("logbook screen: gratis minutes stay out of the rate (0.5h, not 1.5h)",
          "1.5h" not in head["title"], head["title"])
    check("logbook screen: entry rows carry their own rate",
          by_uid(lb, "lbe-2026-10-01-S1")["subtitle"] == "2026-10-01 · 0.5h · ~300€/h"
          and by_uid(lb, "lbe-2026-10-02-S2")["subtitle"] == "2026-10-02 · 1h",
          [r["subtitle"] for r in lb])
    lbs = render("lbs")
    row = by_uid(lbs, "mo-l-lbx")
    check("tattoo list: money · sessions · hours · rate, symbol clean",
          row and row["subtitle"].startswith("150€ · 2 sessions · 🖤 1 · 0.5h · ~300€/h"), row and row["subtitle"])
    check("chair_minutes: gratis sessions out", cr.chair_minutes(LBX["content"]) == 30)

    # ── typing filters, never jumps away ───────────────────────────────
    f = render("yr:2026", "jul")
    check("typing on the year screen filters its months", [x[:10] for x in titles(f)] == ["📅 Jul 2026"], titles(f))

    # ── every drill lands with a clean bar (iron rule 8) ───────────────
    all_rows = home + per + y26 + q4 + qs
    check("every period drill is an xact:crmbrowse trampoline, never a bare ctx arg",
          all(r["arg"].startswith("xact:crmbrowse:ctx:crmmoney:") for r in all_rows
              if r.get("valid", True) and r.get("arg", "").startswith("xact:crmbrowse")))
    check("⌥ and ⌃ never carry an xact arg on a period row",
          all(not (r.get("mods", {}).get(k, {}).get("arg") or "").startswith("xact:")
              for r in all_rows for k in ("alt", "ctrl")))

    print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} ok")
    if FAILS:
        print("FAILED:", FAILS)
        sys.exit(1)
