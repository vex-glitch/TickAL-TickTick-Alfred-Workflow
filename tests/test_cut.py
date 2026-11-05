#!/usr/bin/env python3
"""🫵 The percentage per session (Vex 2026-11-05: "not every shop I work in
has the same percentage ... one of the pop up prompts after how much was
charged should be 'What is your percentage' and then the rest should be
calculated accordingly"). An entry carries its own share as a fifth
segment ("· 🫵 60%"); an entry without one inherits the latest stated
above it in its logbook, before any the global crm_cut; every money figure
sums the entries' OWN shares (sum_share, _share_raw, lifetime_share,
period_kpis["share"], crm_money.day_shares) and every 🫵 chip on the money
screens reads that sum. Pure: fixture notes, a fake api for the writer,
no network.

    python3 tests/test_cut.py
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
    os.environ["crm_records_tags"] = "🗂️Customer, 🗂️Logbook, 🗂️Lead, 🗂️Archive"
    os.environ.pop("crm_cut", None)                 # the global default: 50

    import areas                        # noqa: E402
    import browse                       # noqa: E402
    import crm_money                    # noqa: E402
    import crm_records as cr            # noqa: E402

    FAILS, COUNT = [], [0]

    def check(name, cond, detail=""):
        COUNT[0] += 1
        if cond:
            print(f"  ok  {name}")
        else:
            print(f"FAIL  {name}  {detail}")
            FAILS.append(name)

    REC = "6a4e50e9842a1194a7c681e1"
    LB_A = ("👤 [👤 Ana](https://ticktick.com/webapp/#p/%s/tasks/c1) · Started 2026-10-01 · Finished -\n"
            "Paid: 900€ · 3 sessions\n\n## Sessions\n\n### 2026-10-01 · S1 · 2h · 400\n\n"
            "### 2026-10-08 · S2 · 1h · 200 · 🫵 60%%\nShading.\n\n### 2026-10-15 · S3 · 3h · 300\n\n## Notes\n" % REC)
    LB_B = ("👤 [👤 Bo](https://ticktick.com/webapp/#p/%s/tasks/c2) · Started 2026-10-02 · Finished -\n"
            "Paid: 100€ · 2 sessions\n\n## Sessions\n\n### 2026-10-02 · S1 · 2h · gift · 🫵 70%%\n\n"
            "### 2026-10-09 · S2 · 2h · 100 · 🫵 70%%\n\n## Notes\n" % REC)
    NOTES = [{"id": "a1", "projectId": REC, "_projectId": REC, "title": "🎨 Ana • Fox", "tags": [areas.LOGBOOK_TAG], "content": LB_A, "status": 0},
             {"id": "b1", "projectId": REC, "_projectId": REC, "title": "🎨 Bo • Moth", "tags": [areas.LOGBOOK_TAG], "content": LB_B, "status": 0}]
    cr.records_notes = lambda tag=None: [n for n in NOTES if not tag or tag in (n.get("tags") or [])]
    cr.customer_logbooks = lambda tid: [n for n in NOTES if f"/tasks/{tid})" in n["content"]]

    # ── the segment ────────────────────────────────────────────────────
    check("parse_cut: 60 / 60% / 62,5 / 🫵 60% read, blank and junk and out-of-range do not",
          [cr.parse_cut(x) for x in ("60", "60%", "62,5", "🫵 60%", " 45 % ")] == [60, 60, 62.5, 60, 45]
          and all(cr.parse_cut(x) is None for x in ("", "abc", "0", "150", None)))
    check("cut_seg", cr.cut_seg(60) == "🫵 60%" and cr.cut_seg(62.5) == "🫵 62.5%")
    check("entry_cut reads the fifth segment, a four-segment entry has none",
          cr.entry_cut(["2026-10-08", "S2", "1h", "200", "🫵 60%"]) == 60 and cr.entry_cut(["d", "S1", "2h", "400"]) is None)
    rows = cr.entries_cut(LB_A)
    check("entries_cut: the global 50 before any, the entry's own, then inherited by the next",
          [p for _s, p in rows] == [50, 60, 60] and [s[1] for s, _p in rows] == ["S1", "S2", "S3"], rows)
    check("entries_cut with the cut off: no share before the first stated one", [p for _s, p in cr.entries_cut(LB_A, default=None)] == [None, 60, 60])
    check("last_cut = the percentage in force after the last entry; an empty logbook = the global", cr.last_cut(LB_A) == 60 and cr.last_cut(LB_B) == 70 and cr.last_cut("") == 50)
    check("the four-segment readers are untouched by the fifth", cr._totals_raw(LB_A)[:2] == (900.0, 3) and cr.chair_minutes(LB_A) == 360
          and cr.last_duration(LB_A) == "3h" and cr.paid_summary(LB_A) == "900€ · 3 sessions", (cr._totals_raw(LB_A), cr.chair_minutes(LB_A), cr.last_duration(LB_A)))
    check("share_of", cr.share_of(400, 50) == 200 and cr.share_of(None, 50) is None and cr.share_of(400, None) is None)
    check("_share_raw sums each entry at ITS percentage (200 + 120 + 180), a gift has no share",
          cr._share_raw(LB_A) == 500 and cr._share_raw(LB_B) == 70 and cr._share_raw("") is None)

    # ── the ledger ─────────────────────────────────────────────────────
    e = cr.all_entries()
    check("all_entries rows carry the share as a 7th field", all(len(r) == 7 for r in e) and len(e) == 5, e)
    check("sum_entries still answers the four it always did (the total is the total)", cr.sum_entries(e)[:2] == ("1000€", 5) and cr.sum_entries(e)[3] == 1000.0, cr.sum_entries(e))
    check("sum_share = Σ the entries' own shares, bounded like sum_entries",
          cr.sum_share(e) == 570 and cr.sum_share(e, "2026-10-08", "2026-10-09") == 190 and cr.sum_share(e, "2026-11-01", None) is None, cr.sum_share(e))
    check("an old six-field ledger has no share", cr.sum_share([("2026-10-01", True, 400.0, "€", False, 120)]) is None
          and cr.sum_entries([("2026-10-01", True, 400.0, "€", False, 120)])[0] == "400€")
    check("lifetime_share", cr.lifetime_share("c1") == 500 and cr.lifetime_share("c2") == 70 and cr.lifetime_share("nobody") is None)
    det = cr.entries_detailed()
    s2 = next(x for x in det if x["lb"]["id"] == "a1" and x["marker"] == "S2")
    s3 = next(x for x in det if x["lb"]["id"] == "a1" and x["marker"] == "S3")
    check("entries_detailed carries cut + share per entry", s2["cut"] == 60 and s2["share"] == 120 and s3["cut"] == 60 and s3["share"] == 180, (s2, s3))
    k = cr.period_kpis("2026-10-01", "2026-10-31")
    check("period_kpis: the share beside the money", k["money"] == 1000 and k["share"] == 570, k)

    # ── the chips ──────────────────────────────────────────────────────
    check("cut_chip with a share renders the share, never the total × global", cr.cut_chip(900, "900€", share=500) == " · 🫵 500€")
    check("cut_chip without one: the global cut (the old road)", cr.cut_chip(900, "900€") == " · 🫵 450€")
    check("cut_chip at a logbook's percentage", cr.cut_chip(100, "100€", percent=70) == " · 🫵 70€")
    check("cut_chip: nothing to say", cr.cut_chip(0, "-") == "" and cr.cut_chip(100, "100€", share=0) == "")
    check("cut_rate_chip with a share rate", cr.cut_rate_chip(150, "€", share_rate=83.3) == " · 🫵 ~83€/h" and cr.cut_rate_chip(150, "€") == " · 🫵 ~75€/h")
    check("browse._rate_chip: the 🫵 rate is share / hours", browse._rate_chip(cr, 6.0, 900, "900€", share=500) == " · 6h · ~150€/h · 🫵 ~83€/h"
          and browse._rate_chip(cr, 6.0, 900, "900€") == " · 6h · ~150€/h · 🫵 ~75€/h", browse._rate_chip(cr, 6.0, 900, "900€", share=500))

    # ── the money screens read the sum of shares ───────────────────────
    browse._records_gate = lambda: None
    home = browse.render_crmmoney("", "")
    total = next(r for r in home if r.get("uid") == "mo-total")
    check("💰 All time: the total, then 🫵 the sum of the entries' own shares", "1000€ · 🫵 570€" in total["title"], total["title"])
    lb = browse.render_crmmoney("lb:a1", "")
    head = next(r for r in lb if r.get("uid") == "lb-head")
    check("one tattoo's head: 900€ · 3 sessions · 🫵 500€ · 6h · ~150€/h · 🫵 ~83€/h",
          head["title"] == "💰 900€ · 3 sessions · 🫵 500€ · 6h · ~150€/h · 🫵 ~83€/h", head["title"])
    r2 = next(r for r in lb if r.get("uid") == "lbe-2026-10-08-S2")
    r1 = next(r for r in lb if r.get("uid") == "lbe-2026-10-01-S1")
    check("each entry row at its own percentage (S1 at the global 50, S2 at its 60)",
          r1["title"] == "S1 · 400€ · 🫵 200€" and r2["title"] == "S2 · 200€ · 🫵 120€" and "🫵 ~120€/h" in r2["subtitle"], (r1["title"], r2["title"], r2["subtitle"]))
    lbs = browse.render_crmmoney("lbs", "")
    ana = next(r for r in lbs if r.get("uid") == "mo-l-a1")
    check("the tattoos list: 🫵 after the paid summary, the rate at the share", "900€ · 3 sessions · 🫵 500€" in ana["subtitle"] and "🫵 ~83€/h" in ana["subtitle"], ana["subtitle"])

    # ── the notes' source ──────────────────────────────────────────────
    areas.records_configured = lambda: True
    crm_money._cache_present = lambda: True
    crm_money._MEMO.update(fn=None, rows=None)
    sh = crm_money.day_shares()
    check("day_shares: the day's shares beside day_sums", sh[date(2026, 10, 8)] == 120 and crm_money.day_sums()[date(2026, 10, 8)] == 200
          and sh[date(2026, 10, 2)] == 0 and set(sh) == set(crm_money.day_sums()), sh)
    check("day_share / period_share", crm_money.day_share(date(2026, 10, 15)) == 180 and crm_money.day_share(date(2026, 10, 20)) is None
          and crm_money.period_share(date(2026, 10, 1), date(2026, 10, 31)) == 570)
    check("a gift-only day knows a 0 share while the cut is on", crm_money.day_share(date(2026, 10, 2)) == 0)
    cr.all_entries = lambda: [("2026-10-01", True, 400.0, "€", False, 120), ("2026-10-02", True, None, "", False, 60)]
    crm_money._MEMO.update(fn=None, rows=None)
    check("an old six-field ledger: no shares known (the notes keep the bare totals)", crm_money.day_shares() is None and crm_money.day_sums()[date(2026, 10, 1)] == 400)

    # ── the writer ─────────────────────────────────────────────────────
    LIVE = {"id": "a1", "projectId": REC, "title": "🎨 Ana • Fox", "content": LB_A, "tags": [areas.LOGBOOK_TAG]}
    class _API:
        def __init__(self):
            self.writes = []
        def get_task(self, pid, tid):
            return dict(LIVE)
        def update_task(self, tid, pid, current=None, **f):
            self.writes.append(f.get("content"))
            return dict(LIVE, **f)
    api = _API()
    cr._api = lambda: api
    cr._fresher_content = lambda tid, live: live
    cr._patch_cache = lambda tid, **f: None
    cr.sync_customer_bullet = lambda lb: None
    content, money, n, _t = cr.append_session(REC, "a1", "S4", "2h", "250", "Lines.", when="2026-10-22", cut=55)
    check("append_session writes the fifth segment", "### 2026-10-22 · S4 · 2h · 250 · 🫵 55%\nLines." in content and money == "1150€" and n == 4, content)
    check("…and the next default is that percentage", cr.last_cut(content) == 55 and cr._share_raw(content) == 637.5)
    content2, _m, _n, _t = cr.append_session(REC, "a1", "S5", "1h", "100", when="2026-10-29")
    check("no percentage given: a plain four-segment entry (inherits on read)", "### 2026-10-29 · S5 · 1h · 100\n" in content2 and " · 🫵 " not in content2.split("### 2026-10-29")[1].split("\n")[0], content2)

    print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} ok")
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
