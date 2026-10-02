#!/usr/bin/env python3
"""The money roll-up belongs to the month, the quarter and the year.

On 2026-09-24 the early OKR fill split refresh_period's dispatch in two, and
a daily and a weekly fell into the yearly's branch: every refresh of one
wrote the year's four quarter lines over any SECTION of the note named
💰 Money. In a daily of the layout before 2026-09-12 that section holds the
day's own money entries, which every sum above it is read from. Found by
the review of the relayout tools, 2026-09-27.

Pure: HOME is a temp dir, today is pinned, nothing reaches the network, and
the read-modify-write of a note is an in-memory stand-in.

    python3.13 tests/test_money_rollup_scope.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import os
    import socket
    import sys
    import tempfile
    from datetime import date

    _TMP = tempfile.mkdtemp(prefix="tickal_mr_")
    os.environ["HOME"] = _TMP
    os.environ["TICKAL_CACHE_DIR"] = os.path.join(_TMP, "cache")
    os.environ["TT_V2_TOKEN"] = ""
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

    import periodic_sections as ps      # noqa: E402
    import periodic_model as pm         # noqa: E402
    import periodic_engine as pe        # noqa: E402

    TODAY = date(2026, 9, 17)
    pe.LOG_FILE = os.path.join(_TMP, "periodic.log")
    pe._today = lambda: TODAY
    pe._tier2 = lambda: None
    pe._completed_batch = lambda: []

    def _no_api():
        raise RuntimeError("no API in tests")

    pe._api = _no_api
    pe._sweep_due = lambda pairs, line_day: ([], [])        # the sweep completes tasks: never here

    P = F = 0

    def check(n, c, d=""):
        global P, F
        if c:
            P += 1
        else:
            F += 1
            print("  FAIL", n, d)

    MINE = ["- 🟢 Ana, deposit · 120", "- 🟢 Flash sheet · 50"]
    # the roll-up's source is the CRM (2026-10-02): the day holds 170 there
    import crm_money                    # noqa: E402
    crm_money.day_sums = lambda start=None, end=None: {date(2026, 9, 15): 170.0}

    def note(kind, day, body):
        p = pm.period_for(kind, day)
        return p, {"id": "a" * 24, "projectId": "b" * 24, "title": pm.title(p), "content": "\n".join(body)}

    def index_of(*pairs):
        return {(p.kind, pm.title_key(p)): t for p, t in pairs}

    def money(doc):
        sec = next((s for s in doc.sections if s.name == pm.SEC_MONEY), None)
        return [l.strip() for l in (sec.body if sec else []) if l.strip()]

    # a daily of the layout before 2026-09-12: the day's money in a section
    day = note("daily", date(2026, 9, 15), ["C", "---", "### 💰 Money"] + MINE + ["\t\t- **Total = 170**", ""])
    idx = index_of(day)
    sums = pe._day_sums(idx)
    check("the CRM holds the day's money", sums == {date(2026, 9, 15): 170.0}, sums)
    for kind, d in (("daily", date(2026, 9, 15)), ("weekly", date(2026, 9, 15))):
        p = pm.period_for(kind, d)
        doc = ps.parse_sections("\n".join(["C", "---", "### 💰 Money"] + MINE + [""]))
        before = ps.serialize_sections(doc)
        pe._fill_rollup_money(doc, p, idx)
        check(f"the roll-up leaves a {kind} note alone", ps.serialize_sections(doc) == before, money(doc))
    for kind in ("monthly", "quarterly", "yearly"):
        p = pm.period_for(kind, date(2026, 9, 15))
        doc = ps.parse_sections("\n".join(["C", "---", "### 💰 Money", "**Total = 0**", ""]))
        pe._fill_rollup_money(doc, p, idx)
        check(f"and still writes the {kind} one", any("• 170" in l for l in money(doc)) and any("Total = 170" in l for l in money(doc)), money(doc))

    # the whole refresh, the note held in memory
    for kind, d in (("daily", date(2026, 9, 15)), ("weekly", date(2026, 9, 15))):
        p, task = note(kind, d, ["C", "---", "### 💰 Money"] + MINE + [""])
        held = {}

        def rmw(pid, tid, mutate, task=task, held=held):
            doc = ps.parse_sections(task["content"])
            res = mutate(doc, dict(task))
            held["doc"] = doc
            return res, doc

        real = pe._pn_rmw
        pe._pn_rmw = rmw
        try:
            pe.refresh_period(p, index=index_of(day, (p, task)))
        finally:
            pe._pn_rmw = real
        check(f"the refresh of the {kind} note ran", "doc" in held)
        got = money(held.get("doc") or ps.parse_sections(""))
        # the daily's own filler totals the day's entries: that line is its
        check(f"a refresh of a {kind} note keeps a 💰 Money section of his", [l for l in got if "Total" not in l] == [l.strip() for l in MINE], got)
        check(f"and writes no quarter into it ({kind})", not any("2026-Q" in l for l in got), got)

    check("nothing reached the network", NET == [], NET[:3])
    print(f"money roll-up scope: {P} passed, {F} failed")
    sys.exit(1 if F else 0)
