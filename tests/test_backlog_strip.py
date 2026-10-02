#!/usr/bin/env python3
"""📋 The Backlog day strip for ✨ highlight, 😊 mood and ★ the day rating
(Scripts/periodic_rows.py), plus the ➕ Entry legend's guards and the ✨
mirror's clearing.

These checks lived in tests/test_money.py until the money road left the
notes (2026-10-02); the review found that deleting that suite dropped them
although the code they pin is still live (and that twelve of them sat after
the old file's only raise, so they could never fail a run). No network: the
engine is a stub for the strip, the real engine only for the ✨ mirror.
Run: python3 tests/test_backlog_strip.py
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

    _TMP = tempfile.mkdtemp(prefix="tickal_bs_")
    os.environ["HOME"] = _TMP
    os.environ["TICKAL_CACHE_DIR"] = os.path.join(_TMP, "cache")
    os.environ["TT_V2_TOKEN"] = ""
    os.environ["TICKAL_NO_SETTLE"] = "1"
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "Scripts")):
        sys.path.insert(0, _p)

    def _no_net(self, *a, **k):
        raise OSError("no network in tests")

    socket.socket.connect = _no_net
    socket.socket.connect_ex = _no_net

    import script_base                  # noqa: E402
    script_base.run_path = lambda name: os.path.join(_TMP, name)

    import periodic_sections as ps      # noqa: E402
    import periodic_model as pm         # noqa: E402
    import periodic_engine as pe        # noqa: E402
    import periodic_rows as prows       # noqa: E402

    FAILS, COUNT = [], [0]

    def check(name, cond, detail=""):
        COUNT[0] += 1
        if cond:
            print(f"  ok  {name}")
        else:
            print(f"FAIL  {name}  {detail}")
            FAILS.append(name)

    TODAY = date(2026, 9, 17)                                  # a Thursday
    WEEK = {date(2026, 9, 17): ("blank", ""),
            date(2026, 9, 16): ("blank", ""),
            date(2026, 9, 15): ("answered", "A highlight"),
            date(2026, 9, 14): ("blank", "")}

    class _FakeEngine:
        """The strip and the confirm screen both read the engine, and the
        confirm screen re-reads the day LIVE rather than trusting the strip
        it came from, so the stub covers both roads."""
        @staticmethod
        def week_answer_states(slot, needle, monday=None, today=None):
            return [(d, ) + WEEK[d] + (WEEK[d][1], ) for d in sorted(WEEK, reverse=True)]

        @staticmethod
        def day_answer_state(day, slot, needle, notes=None):
            return WEEK.get(day, ("unasked", ""))

    prows._pe = lambda: _FakeEngine

    class _FakeDate(date):
        @classmethod
        def today(cls):
            return TODAY

    _real_date = prows.date
    prows.date = _FakeDate
    # pm.past_day (the *mon road) reads ITS OWN clock, the 04:00 day roll
    pm.date = _FakeDate
    pm._dayroll_today = lambda: TODAY

    HL = prows._BY_LETTER["h"]

    # ── the strip ──────────────────────────────────────────────────────
    r = prows.day_strip_rows(HL, "", "pn + b h ")
    check("idle strip prompts then lists the week",
          r[0]["title"].startswith("✨ Type the highlight") and len(r) == 5
          and not any(x.get("valid") for x in r), [x["title"] for x in r])
    r = prows.day_strip_rows(HL, "Shipped the thing", "pn + b h ")
    check("today is the first row, so plain ⏎ is today",
          r[0]["title"].startswith("☀️ Today") and r[0]["valid"] is True, r[0]["title"])
    check("a day with nothing writes straight away",
          r[0]["arg"].startswith("xact:pn_backlog:") and "autocomplete" not in r[0], r[0].get("arg", "")[:30])
    day_with = next(x for x in r if "15 Sep" in x["title"])
    check("a day that ALREADY has an answer cannot be written by accident",
          day_with.get("valid") is False
          and day_with["autocomplete"] == "pn + b h !2026-09-15 Shipped the thing", day_with)
    check("and it says what it holds", "Has A highlight" in day_with["subtitle"], day_with["subtitle"])
    r = prows.day_strip_rows(HL, "Shipped the thing *finally", "pn + b h ")
    check("a trailing *word that is not a day stays in the text",
          all("Shipped the thing *finally" in x.get("subtitle", "") for x in r if x.get("valid")),
          [x.get("subtitle") for x in r])
    r = prows.day_strip_rows(HL, "Shipped it *mon", "pn + b h ")
    check("a trailing *day still targets a day", len(r) == 1 and "14 Sep" in r[0]["title"], [x["title"] for x in r])

    r = prows.day_strip_rows(HL, "!2026-09-15 A new highlight", "pn + b h ")
    check("the confirm screen leads with what is there",
          r[0]["title"] == "✨ Tue 15 Sep · A highlight" and r[0]["valid"] is False, r[0])
    check("the Leave it row keeps what you typed in the bar",
          r[0]["autocomplete"] == "pn + b h A new highlight", r[0].get("autocomplete"))
    check("and replacing is the second row", "Replace" in r[1]["subtitle"] and r[1]["valid"] is True, r[1])
    check("and there is a way back", r[2]["autocomplete"] == "pn + b h A new highlight", r[2])
    import base64
    import json
    pay = json.loads(base64.b64decode(r[1]["arg"].split(":", 2)[2]))
    check("the replace row really means replace",
          pay == {"text": "A new highlight", "kind": "h", "day": "2026-09-15", "replace": True}, pay)
    check("a day you have not had yet is refused",
          "Not a day you have had yet" in prows.day_strip_rows(HL, "!2099-01-01 x", "pn + b h ")[0]["title"])

    class _Broken:
        @staticmethod
        def week_answer_states(*a, **k):
            raise RuntimeError("cache is gone")

        @staticmethod
        def day_answer_state(*a, **k):
            raise RuntimeError("cache is gone")

    prows._pe = lambda: _Broken
    r = prows.day_strip_rows(HL, "A highlight", "pn + b h ")
    check("an unreadable cache never becomes a one-keystroke overwrite",
          not any(x.get("valid") for x in r) and all("Cannot read" in x["subtitle"] for x in r),
          [(x["subtitle"], x.get("valid")) for x in r])
    prows._pe = lambda: _FakeEngine

    # ── the scale kinds ────────────────────────────────────────────────
    check("the mood separator the hint teaches is shaved",
          prows._parse_scale("4 · slept badly")[1] == {"score": 4, "note": "slept badly"},
          prows._parse_scale("4 · slept badly"))
    check("and a note with no separator still works",
          prows._parse_scale("4 slept badly")[1]["note"] == "slept badly")
    check("a scale value must be 1 to 5",
          prows._parse_scale("7") is None and prows._parse_scale("x") is None and prows._parse_scale("42") is None)
    check("the day rating does not wear the week highlight's glyph",
          prows._BY_LETTER["r"]["emoji"] != "⭐️" and dict(prows._KIND_LEGEND)["h"] == "⭐️ Highlight")
    check("the backlog kinds are highlight, mood, rating", [k["letter"] for k in prows.BACKLOG_KINDS] == ["h", "m", "r"])

    # ── the legend's guards ────────────────────────────────────────────
    bad = prows.entry_rows("m 485")
    check("an unknown kind letter never logs a thought",
          bad[0]["valid"] is False and "No entry kind" in bad[0]["title"], bad[0])
    check("plain text is still a thought",
          prows.entry_rows("shipped the thing")[0]["title"].startswith("💭 Thought"))
    legend = prows.entry_rows("")
    check("the legend lists win, nag, thought, reminder, link, task, highlight, backlog",
          [x["uid"] for x in legend] == [f"pn-kind-{l}" for l in "wntrlkhb"], [x["uid"] for x in legend])

    # ── the clock ──────────────────────────────────────────────────────
    check("a date in another year says so",
          pm.day_label(date(2025, 9, 15), date(2026, 9, 17)) == "Mon 15 Sep 2025"
          and pm.day_label(date(2026, 9, 15), date(2026, 9, 17)) == "Tue 15 Sep")

    # ── the ✨ mirror ──────────────────────────────────────────────────
    _doc = ps.parse_sections(
        "- 🌙 Evening journal\n\t- *Q1 · ✨ What was the highlight of the day?*\n"
        "\t\t- A: \n#### ✨ Highlight\n- ✨ yesterday's leftover\n")
    pe._fill_day_highlight(_doc)
    check("emptying the answer clears the ✨ mirror",
          [l for l in (ps.find(_doc, pm.SEC_HIGHLIGHT) or ps.Section("", "")).body if l.strip()] == [],
          (ps.find(_doc, pm.SEC_HIGHLIGHT) or ps.Section("", "")).body)

    prows.date = _real_date
    print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} ok")
    if FAILS:
        print("FAILED:", FAILS)
        sys.exit(1)
