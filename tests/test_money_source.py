#!/usr/bin/env python3
"""💰 Money comes from the CRM (Vex 2026-10-02, mid quarterly review: "too
many places in our system ask the same question about money ... make the
daily intakes of money in daily notes drag from our CRM Session charges for
the given day. That I always enter. ... You can diss the 'how much money you
made today' from journals completely.")

The contract this pins:
  * src/crm_money.py reads the CRM's dated entries off the cache - day
    sums, a day, a period; nothing when the CRM is not set up
  * the engine's day sums, the summaries' Money line and every 💰 Income
    span come from there; a span the CRM holds nothing for says "no
    sessions", never 0
  * the evening journal no longer asks; the old question still keys
    ("money"), an UNANSWERED one is dropped from a note on its next seed,
    an answered one stays as history
  * the `$` entry road, the `tmo` keyword and the backlog's money kind are
    one pointer at CRM > 💰 Money; nothing is typed into a note

Pure: HOME is a temp dir, nothing reaches the network, every door is a stub.
Run: python3 tests/test_money_source.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import contextlib
    import io
    import os
    import socket
    import sys
    import tempfile
    from datetime import date

    _TMP = tempfile.mkdtemp(prefix="tickal_ms_")
    os.environ["HOME"] = _TMP
    os.environ["TICKAL_CACHE_DIR"] = os.path.join(_TMP, "cache")
    os.environ["TT_V2_TOKEN"] = ""
    os.environ["TICKAL_NO_SETTLE"] = "1"
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "Scripts")):
        sys.path.insert(0, _p)

    NET = []

    def _no_net(self, *a, **k):
        NET.append(a)
        raise OSError("no network in tests")

    socket.socket.connect = _no_net
    socket.socket.connect_ex = _no_net

    import script_base                  # noqa: E402
    script_base.run_path = lambda name: os.path.join(_TMP, name)

    import crm_money                    # noqa: E402
    import periodic_sections as ps      # noqa: E402
    import periodic_model as pm         # noqa: E402
    import periodic_engine as pe        # noqa: E402

    FAILS, COUNT = [], [0]

    def check(name, cond, detail=""):
        COUNT[0] += 1
        if cond:
            print(f"  ok  {name}")
        else:
            print(f"FAIL  {name}  {detail}")
            FAILS.append(name)

    # ── 1. the source ──────────────────────────────────────────────────
    # (date, is_session, amount, sym, pre, minutes): a deposit and a session
    # on the 15th, a session on the 16th, an unpriced consult on the 17th
    LEDGER = [
        ("2026-09-15", False, 100.0, "€", False, None),
        ("2026-09-15", True, 300.0, "€", False, 120),
        ("2026-09-16", True, 250.0, "€", False, 90),
        ("2026-09-17", False, None, "", False, 30),
        ("2026-09-01", True, 0.0, "€", False, 60),           # a gratis session, priced 0
        ("2026-09-02", True, None, "", False, 60),           # a session with no price at all ("-", gift)
        ("garbage", True, 5.0, "€", False, None),
    ]
    import areas                        # noqa: E402
    import crm_records as cr            # noqa: E402
    areas.records_configured = lambda: True
    cr.all_entries = lambda: list(LEDGER)
    crm_money._cache_present = lambda: True

    sums = crm_money.day_sums()
    check("1.a day sums every priced entry dated on it", sums[date(2026, 9, 15)] == 400.0, sums)
    check("1.an unpriced deposit/payment line is not a money day", date(2026, 9, 17) not in sums, sums)
    check("1.a session priced 0 IS a money day (made 0, not unknown)", sums.get(date(2026, 9, 1)) == 0.0, sums)
    check("1.a session with no price at all is a 0 day too (a session happened)", sums.get(date(2026, 9, 2)) == 0.0, sums)
    check("1.an undated line is skipped", len(sums) == 4, sums)
    check("1.day_sum", crm_money.day_sum(date(2026, 9, 16)) == 250.0 and crm_money.day_sum(date(2026, 9, 17)) is None)
    check("1.a bounded read", crm_money.day_sums(date(2026, 9, 16), date(2026, 9, 30)) == {date(2026, 9, 16): 250.0})
    check("1.period_sum", crm_money.period_sum(date(2026, 9, 1), date(2026, 9, 30)) == 650.0
          and crm_money.period_sum(date(2026, 10, 1), date(2026, 10, 31)) == 0.0)
    areas.records_configured = lambda: False
    check("1.CRM not set up → None (unreadable), never {} and never a 0",
          crm_money.day_sums() is None and crm_money.day_sum(date(2026, 9, 15)) is None
          and crm_money.period_sum(date(2026, 9, 1), date(2026, 9, 30)) is None)
    areas.records_configured = lambda: True

    def _boom():
        raise RuntimeError("cache unreadable")
    cr.all_entries = _boom
    check("1.a reader that fails → None too", crm_money.day_sums() is None)
    cr.all_entries = lambda: []
    check("1.a CRM that holds nothing → {} (readable, empty)", crm_money.day_sums() == {})
    crm_money._cache_present = lambda: False
    cr.all_entries = lambda: list(LEDGER)
    check("1.no notes cache on disk → None (unreadable), never an empty CRM", crm_money.day_sums() is None)
    crm_money._cache_present = lambda: True
    CALLS = [0]
    def _counted():
        CALLS[0] += 1
        return list(LEDGER)
    cr.all_entries = _counted
    crm_money.day_sums(); crm_money.day_sum(date(2026, 9, 15)); crm_money.period_sum(date(2026, 9, 1), date(2026, 9, 30))
    check("1.one refresh parses the cache once (three reads, one parse)", CALLS[0] == 1, CALLS[0])
    cr.all_entries = lambda: list(LEDGER)

    # ── 2. the engine reads it, and only it ────────────────────────────
    pe._today = lambda: date(2026, 9, 17)
    # an index full of daily notes with money answers and 💰 sections: ignored
    idx = {("daily", "2026-09-15"): {"title": "2026-09-15 · Tue", "content":
           "#### 📓 Journals\n- 🌙 Evening journal\n\t- *Q1 · How much money did you earn today?*\n\t\t- A: 9999\n"},
           ("daily", "2026-09-14"): {"title": "2026-09-14 · Mon", "content": "### 💰 Money\n- 777 · x\n**Total = 777**\n"}}
    ds = pe._day_sums(idx)
    check("2.the engine's day sums are the CRM's, a note's answer or section counts for nothing",
          ds == {date(2026, 9, 15): 400.0, date(2026, 9, 16): 250.0, date(2026, 9, 1): 0.0, date(2026, 9, 2): 0.0}, ds)
    check("2.the engine knows when the CRM can be read", pe._money_known() is True)
    check("2.a day's money for the summary", pe._day_money(date(2026, 9, 15)) == 400.0 and pe._day_money(date(2026, 9, 17)) is None)
    check("2.no day, no money", pe._day_money(None) is None)
    wk = pm.period_for("weekly", date(2026, 9, 15))
    spans = [(1, None, date(2026, 9, 1), date(2026, 9, 6)), (2, None, date(2026, 9, 7), date(2026, 9, 13)),
             (3, None, date(2026, 9, 14), date(2026, 9, 20)), (4, None, date(2026, 9, 21), date(2026, 9, 27))]
    lines = pe._span_money_lines(ds, spans, "monthly", date(2026, 9, 17))
    check("2.a span the CRM holds nothing for says 'no sessions', never 0",
          any(l.endswith("• no sessions") for l in lines) and not any(l.endswith("• 0") for l in lines if "W2" in l), lines)
    check("2.a span with sessions carries its sum", any("• 650" in l for l in lines), lines)
    check("2.a span whose only sessions were free reads 0, not 'no sessions'", any("1st-6th" in l and l.endswith("• 0") for l in lines), lines)
    check("2.a span not yet started is not listed", len(lines) == 3, lines)
    yspans = [(1, None, date(2026, 1, 1), date(2026, 3, 31)), (2, None, date(2026, 4, 1), date(2026, 6, 30)),
              (3, None, date(2026, 7, 1), date(2026, 9, 30)), (4, None, date(2026, 10, 1), date(2026, 12, 31))]
    ylines = pe._span_money_lines({date(2026, 5, 18): 300.0, date(2026, 8, 2): 100.0}, yspans, "yearly", date(2026, 10, 2))
    check("2.a span that ended before the CRM's first entry reads 'before the CRM', not 'no sessions'",
          ylines[0].endswith("• before the CRM"), ylines)
    check("2.the span the CRM starts inside says from which day it counts", ylines[1].endswith("• 300 · from 18 May"), ylines)
    check("2.a later span is a plain sum", ylines[2].endswith("• 100") and len(ylines) == 4 and ylines[3].endswith("• no sessions"), ylines)

    # the summary: Money is ALWAYS a line, 0 without a session, the arrow only
    # when both days hold one
    pe._answer_in = lambda doc, sec, needle: ""
    pe._mood_of_doc = lambda doc: None
    pe._completed_tops = lambda d: []
    pe._people_logged = lambda d: []
    pe._wontdo_between = lambda a, b: None
    doc = ps.parse_sections("")
    rec = pe._recap_lines(date(2026, 9, 16), None, doc, pm.T2, pday=date(2026, 9, 15), pdoc=doc)
    money_line = next((l for l in rec if "Money" in l), "")
    check("3.the summary's Money line is the CRM's day with its arrow against the day before",
          money_line.startswith(pm.T2 + "- Money: 250") and "▼ 150" in money_line, rec)
    rec = pe._recap_lines(date(2026, 9, 17), None, doc, pm.T2, pday=date(2026, 9, 16), pdoc=doc)
    money_line = next((l for l in rec if "Money" in l), "")
    check("3.a day without a session reads 0 and draws no arrow", money_line == pm.T2 + "- Money: 0", rec)
    rec = pe._recap_lines(date(2026, 9, 16), None, doc, pm.T2, pday=date(2026, 9, 17), pdoc=doc)
    money_line = next((l for l in rec if "Money" in l), "")
    check("3.no arrow when the day before holds no session", money_line == pm.T2 + "- Money: 250", rec)
    rec = pe._recap_lines(date(2026, 9, 16), None, None, pm.T2, pday=date(2026, 9, 15), pdoc=None)
    check("3.a day without a note still shows its money", any(l.startswith(pm.T2 + "- Money: 250") for l in rec), rec)
    areas.records_configured = lambda: False
    rec = pe._recap_lines(date(2026, 9, 16), None, doc, pm.T2, pday=date(2026, 9, 15), pdoc=doc)
    check("3.a CRM that cannot be read writes NO Money line (never a 0 that lies)", not any("Money" in l for l in rec), rec)
    rec = pe._recap_lines(date(2026, 9, 16), None, doc, pm.T2, pday=date(2026, 9, 15), pdoc=doc,
                          money_keep=pm.T2 + "- Money: 300  🟢 ▲ 50")
    check("3.and carries the Money line the note already holds, verbatim", pm.T2 + "- Money: 300  🟢 ▲ 50" in rec, rec)
    sdoc = ps.parse_sections("#### 🔎 Summaries\n- Today\n\t\t- Mood: 🙂\n\t\t- Money: 300\n\t\t- Completed: 4\n")
    check("3._old_line finds the line as it stands", pe._old_line(sdoc, pm.SEC_DAY_SUM, "- Money:") == "\t\t- Money: 300"
          and pe._old_line(sdoc, pm.SEC_DAY_SUM, "- Focus:") is None, pe._old_line(sdoc, pm.SEC_DAY_SUM, "- Money:"))
    areas.records_configured = lambda: True

    # the legacy 💰 Money roll-up (old-layout monthly) reads the CRM too
    mdoc = ps.parse_sections("C\n---\n### 💰 Money\n**Total = 0**\n")
    pe._fill_rollup_money(mdoc, pm.period_for("monthly", date(2026, 9, 15)), {})
    body = [l.strip() for l in ps.find(mdoc, pm.SEC_MONEY).body if l.strip()]
    check("4.the old-layout roll-up sums the CRM, week by week", any("Total = 650" in l for l in body)
          and any(l.startswith("- W38") and l.endswith("• 650") for l in body), body)
    odoc = ps.parse_sections("C\n---\n### 💰 Money\n- 2026-W01 (29-04 Jan) • 1200\n**Total = 1200**\n")
    before = ps.serialize_sections(odoc)
    pe._fill_rollup_money(odoc, pm.period_for("monthly", date(2026, 1, 15)), {})
    check("4.a month before the CRM keeps its lines (never rots to 0)", ps.serialize_sections(odoc) == before)
    # the CRM's first entry is 15 Sep here: W36 and W37 ended before it
    _ds0 = pe._day_sums
    pe._day_sums = lambda index: {date(2026, 9, 15): 400.0, date(2026, 9, 16): 250.0}
    pdoc = ps.parse_sections("C\n---\n### 💰 Money\n- W36 (31-06 Sep) • 120\n**Total = 120**\n")
    pe._fill_rollup_money(pdoc, pm.period_for("monthly", date(2026, 9, 15)), {})
    pe._day_sums = _ds0
    pbody = [l.strip() for l in ps.find(pdoc, pm.SEC_MONEY).body if l.strip()]
    check("4.inside a month the CRM starts in, a week before its first entry keeps its old line",
          "- W36 (31-06 Sep) • 120" in pbody, pbody)
    check("4.…a pre-CRM week with no old line says so, a later empty week reads 0",
          any(l.startswith("- W37") and l.endswith("• before the CRM") for l in pbody)
          and any(l.startswith("- W39") and l.endswith("• 0") for l in pbody)
          and any(l.startswith("- W38") and l.endswith("• 650") for l in pbody), pbody)
    check("4.and the kept amount counts into the Total", any("Total = 770" in l for l in pbody), pbody)

    # ── 4b. the 04:30 agent: no Alfred environment. With the CRM unreadable
    # every money writer leaves its section alone; with the config.json copy
    # (areas._env_or_cfg + _persist_id) it reads the CRM like Alfred does
    from datetime import timedelta
    _REAL = {name: getattr(pe, name) for name in ("_mirror_goal", "_fill_people", "_seed_slot", "_fill_review")}
    for name in _REAL:
        setattr(pe, name, lambda *a, **k: None)
    pe._tier2 = lambda: None
    pe._completed_between = lambda a, b: []
    pe._created_between = lambda a, b: []
    pe._highlights_between = lambda *a, **k: []
    pe._entries_between = lambda *a, **k: []
    pe._mood_by_day = lambda *a, **k: []
    pe._mood_avg = lambda *a, **k: None
    pe.journal_ctx = lambda *a, **k: {}
    pe._today = lambda: date(2026, 9, 28)          # Monday 04:30: last week's closing pass
    wk = pm.period_for("weekly", date(2026, 9, 21))
    tpl = open(os.path.join(ROOT, "src", "periodic_templates", "weekly.md"), encoding="utf-8").read()

    def weekly_doc():
        d = ps.parse_sections(pm.render_template(tpl, {"breadcrumbs": "C", "daylinks": "- d"}))
        ps.set_body(d, pm.SEC_INCOME, ["\t- Tue 22 Sep 2026 • 400", "\t\t\t- **Total = 400**"], pm.scope_of("weekly", pm.SEC_INCOME))
        ps.set_body(d, pm.SEC_LAST_WEEK, ["- Completed: 10", "- Income: 100"])
        return d
    cr.all_entries = lambda: [("2026-09-15", True, 300.0, "€", False, 60),
                              ("2026-09-22", True, 400.0, "€", False, 180), ("2026-09-24", True, 250.0, "€", False, 120)]
    areas.records_configured = lambda: False       # the agent, before the copy existed
    d = weekly_doc()
    before = ps.serialize_sections(d)
    pe._fill_weekly(d, wk, {})
    inc = ps.find_prefix(d, pm.SEC_INCOME, pm.scope_of("weekly", pm.SEC_INCOME))
    check("4b.CRM unreadable: the closing pass leaves 💰 Income exactly as it was, no 0 sealed",
          [l for l in inc.body if l.strip()] == ["\t- Tue 22 Sep 2026 • 400", "\t\t\t- **Total = 400**"], inc.body)
    lw = ps.find(d, pm.SEC_LAST_WEEK)
    check("4b.and ⏪ Last week keeps the Income line it had", lw is not None and any(l.strip() == "- Income: 100" for l in lw.body), lw.body if lw else None)
    areas.records_configured = lambda: True        # the copy in config.json
    d = weekly_doc()
    pe._fill_weekly(d, wk, {})
    inc = ps.find_prefix(d, pm.SEC_INCOME, pm.scope_of("weekly", pm.SEC_INCOME))
    check("4b.CRM readable: the week reads 650 off the CRM, day by day, with its chip against last week",
          inc.name.startswith("💰 Income: 650 · 🟢 ▲ 350") and any(l.strip() == "- Thu 24 Sep 2026 • 250" for l in inc.body) and any("Total = 650" in l for l in inc.body), (inc.name, inc.body))
    lw = ps.find(d, pm.SEC_LAST_WEEK)
    check("4b.and ⏪ Last week's Income is the CRM's previous week", lw is not None and any(l.strip() == "- Income: 300" for l in lw.body), lw.body if lw else None)
    # the copy itself: areas reads config.json when the env var is absent, and
    # _persist_id writes the three CRM fields there under Alfred
    import config as cfg_mod
    cfg_mod.CONFIG_FILE = os.path.join(_TMP, "config.json")
    cfg_mod.CONFIG_DIR = _TMP
    for k in ("crm_records_list_id", "crm_records_tags", "crm_archive_list_id"):
        os.environ.pop(k, None)
    areas._CFG_COPY = None
    check("4b.no env, no config: the field is blank", areas._env_or_cfg("crm_records_list_id") == "")
    os.environ.update({"crm_records_list_id": "REC", "crm_records_tags": "🗂️Customer, 🗂️Logbook, 🗂️Lead, 🗂️Archive",
                       "crm_archive_list_id": "ARC", "periodic_list_id": "PER"})
    _np = os.environ.pop("TICKAL_NO_PERSIST", None)   # this suite's config.json IS a temp file: the gate's guard may lift here
    pe._persist_id()
    if _np is not None:
        os.environ["TICKAL_NO_PERSIST"] = _np
    saved = cfg_mod.load()
    check("4b.under Alfred the CRM fields are mirrored into config.json",
          saved.get("crm_records_list_id") == "REC" and saved.get("crm_archive_list_id") == "ARC"
          and saved.get("crm_records_tags", "").startswith("🗂️Customer"), saved)
    for k in ("crm_records_list_id", "crm_records_tags", "crm_archive_list_id"):
        os.environ.pop(k, None)
    areas._CFG_COPY = None
    check("4b.headless, the copy is read", areas._env_or_cfg("crm_records_list_id") == "REC"
          and areas._env_or_cfg("crm_archive_list_id") == "ARC")
    os.environ["crm_records_list_id"] = ""
    check("4b.a field present but blank under Alfred is OFF and beats the copy", areas._env_or_cfg("crm_records_list_id") == "")
    _np = os.environ.pop("TICKAL_NO_PERSIST", None)   # this suite's config.json IS a temp file: the gate's guard may lift here
    pe._persist_id()
    if _np is not None:
        os.environ["TICKAL_NO_PERSIST"] = _np
    check("4b.and the blank field clears the copy", "crm_records_list_id" not in cfg_mod.load())
    os.environ.pop("crm_records_list_id", None)
    areas._CFG_COPY = None
    for name, fn in _REAL.items():              # the seed road below is the real one
        setattr(pe, name, fn)

    # ── 5. the journal ─────────────────────────────────────────────────
    ev = pm.journal_fixed("evening", {"goal": "Ship it"})
    check("5.the evening set has no money question", "money" not in [k for k, _ in ev]
          and [k for k, _ in ev] == ["bridge", "dhighlight", "tgoal", "goal", "fcheck", "rating", "free"], [k for k, _ in ev])
    check("5.the old question still keys", pm.journal_key("How much money did you earn today?") == "money"
          and "money" in pm.RETIRED_KEYS)
    OLD = ["\t- *Q1 · 🌉 Daily bridge - what should tomorrow-you know? (saves to the Bridges board + tomorrow's note)*", "\t\t- A: b",
           "\t- *Q2 · How much money did you earn today?*", "\t\t- A: ",
           "\t- *Q3 · Rate the day, 1-5 stars*", "\t\t- A: ",
           "\t- *Q4 · What is on your mind?*", "\t\t- A: "]

    class _Sec:
        def __init__(self, body):
            self.body = list(body)
    sec = _Sec(OLD)
    pe._refresh_fixed_q(sec, ev)
    qs = [pm.journal_key(q) for _n, q, _a, _i in pm.journal_pairs(sec.body)]
    check("5.an UNANSWERED money question is dropped from the note on its next seed, the rest renumbered",
          qs == ["bridge", "rating", "free"] and [n for n, *_ in pm.journal_pairs(sec.body)] == [1, 2, 3], sec.body)
    sec = _Sec(OLD)
    sec.body[3] = "\t\t- A: 120"
    pe._refresh_fixed_q(sec, ev)
    pairs = pm.journal_pairs(sec.body)
    check("5.an ANSWERED one is history and stays", any(pm.journal_key(q) == "money" and a == "120" for _n, q, a, _i in pairs)
          and [pm.journal_key(q) for _n, q, _a, _i in pairs] == ["bridge", "money", "rating", "free"], sec.body)
    sec = _Sec(OLD[:4] + ["\t- *Q3 · How much money did you earn today?*", "\t\t- A: 90"] + OLD[4:])
    pe._refresh_fixed_q(sec, ev)
    pairs = pm.journal_pairs(sec.body)
    check("5.both an answered and a blank money question: the blank one goes, the answered one stays, the rest renumber",
          [(pm.journal_key(q), a) for _n, q, a, _i in pairs] == [("bridge", "b"), ("money", "90"), ("rating", ""), ("free", "")]
          and [n for n, *_ in pairs] == [1, 2, 3, 4], sec.body)
    # the phone's shape: an empty A line with the answer typed as a bullet under it
    sec = _Sec(OLD[:4] + ["\t\t\t- 485 guest spot"] + OLD[4:])
    pe._refresh_fixed_q(sec, ev)
    check("5.an answer typed under an empty A line counts as answered: kept, nothing moves",
          any(pm.journal_key(q) == "money" for _n, q, _a, _i in pm.journal_pairs(sec.body))
          and "\t\t\t- 485 guest spot" in sec.body and sec.body.index("\t\t\t- 485 guest spot") == 4, sec.body)
    # the whole seed road: the evening section of a note carrying the question
    doc = ps.parse_sections("#### 📓 Journals\n- 🌅 Morning journal\n\n- 🌙 Evening journal\n" + "\n".join(OLD) + "\n")
    pe._seed_slot(doc, pm.SEC_EVENING, "evening", date(2026, 9, 17), {"goal": ""}, insert=True)
    qs = [pm.journal_key(q) for _n, q, _a, _i in pm.journal_pairs(ps.find(doc, pm.SEC_EVENING).body)]
    check("5.the seed never plants it and drops the blank one", "money" not in qs and "rating" in qs, qs)
    doc = ps.parse_sections("#### 📓 Journals\n- 🌅 Morning journal\n\n- 🌙 Evening journal\n" + "\n".join(OLD) + "\n")
    pe._seed_slot(doc, pm.SEC_EVENING, "evening", date(2026, 9, 17), {"goal": ""})      # a refresh, not a run
    qs = [pm.journal_key(q) for _n, q, _a, _i in pm.journal_pairs(ps.find(doc, pm.SEC_EVENING).body)]
    check("5.a plain refresh (no insert) drops it too", "money" not in qs and qs == ["bridge", "rating", "free"], qs)

    # ── 6. the `$` road and the backlog ────────────────────────────────
    import periodic_rows as prows       # noqa: E402
    check("6.the entry legend has no money kind", "$" not in [l for l, _ in prows._KIND_LEGEND]
          and "$" not in prows._LEGEND_SUBS)
    check("6.the backlog has no money kind", [k["letter"] for k in prows.BACKLOG_KINDS] == ["h", "m", "r"])
    r = prows.entry_rows("$ 485 tattoo")
    check("6.`+ $` is one row that opens CRM > 💰 Money with a clean bar",
          len(r) == 1 and r[0]["arg"] == "xact:crmbrowse:ctx:crmmoney" and r[0]["valid"] is True
          and "CRM" in r[0]["title"] + r[0]["subtitle"], r)
    check("6.its chords are dead except ⌃ back", r[0]["mods"]["shift"]["valid"] is False and r[0]["mods"]["alt"]["valid"] is False
          and r[0]["mods"]["ctrl"]["valid"] is True)
    areas.periodic_configured = lambda: True
    r2 = prows.rows("$ ")
    check("6.the scope road the tmo keyword lands on (`pn $ `) is the same row", len(r2) == 1 and r2[0]["uid"] == "pn-money"
          and r2[0]["arg"] == "xact:crmbrowse:ctx:crmmoney", r2)
    r2 = prows.rows("$485 tattoo")
    check("6.`$485 tattoo` on the scope road too", len(r2) == 1 and r2[0]["uid"] == "pn-money", r2)
    b = prows.backlog_rows("$ 100")
    check("6.`+ b $` is the same pointer", b[0]["uid"] == "pn-money" and b[0]["arg"] == "xact:crmbrowse:ctx:crmmoney", b)
    r3 = prows.entry_rows("$485 tattoo")
    check("6.`+ $485` without the space is the pointer too, never a thought called '$485'", len(r3) == 1 and r3[0]["uid"] == "pn-money", r3)
    check("6.the row's ⌘⇧ and ⌃⌘ chords are dead as well", r[0]["mods"]["cmd+shift"]["valid"] is False and r[0]["mods"]["ctrl+cmd"]["valid"] is False)
    legend = prows.backlog_rows("")
    check("6.the backlog legend lists highlight, mood, rating only", [x["uid"] for x in legend] == ["pn-bk-kind-h", "pn-bk-kind-m", "pn-bk-kind-r"], [x["uid"] for x in legend])

    import xact                         # noqa: E402
    GONE = []
    xact.crmbrowse = lambda ctx: GONE.append(ctx)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        xact.pn_income("485 tattoo *mon")
    check("7.the pn_income verb writes nothing, says so and opens the money home",
          GONE == ["ctx:crmmoney"] and "CRM" in out.getvalue(), (GONE, out.getvalue()))
    xact._pn_gate = lambda: True
    xact._notify_banner = lambda *a, **k: None
    import base64
    import json
    spec = base64.b64encode(json.dumps({"kind": "$", "amount": 100, "day": "2026-09-15"}).encode()).decode()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        xact.pn_backlog(spec)
    check("7.a stale money backlog payload lands nowhere", "Nothing to fill in" in out.getvalue(), out.getvalue())
    check("7.a Unicode minus is a refund in the CRM's own number parser", cr._num("−100") == -100.0 and cr._num("-50") == -50.0)
    check("7.the retired readers are gone", not any(hasattr(pe, n) for n in ("append_income", "day_money_state", "week_money_states", "_daily_has_money", "MONEY_NEEDLE"))
          and not any(hasattr(pm, n) for n in ("parse_money_answer", "money_answer_update", "split_money_answer", "money_answer_line")))
    check("nothing reached the network", NET == [], NET[:3])

    print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} ok")
    if FAILS:
        print("FAILED:", FAILS)
        sys.exit(1)
