#!/usr/bin/env python3
"""The OKR model (src/okr.py), phase 1: everything it reads and plans.

Fixtures are Vex's own 🏆Goals Planning list as it stood on 2026-09-18
(titles and raw dates copied from a read-only get_project_with_undone_tasks
and the v1 cache of the same list), plus small made-up plans where the live
list has no example yet (no 🏔️ Y exists, nothing is linked, nothing is done).

No network: load() and done_lookup() get fake clients and a patched cache.

    python3 tests/test_okr.py
"""
import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import cache  # noqa: E402
import config  # noqa: E402
import okr  # noqa: E402

FAILS = []
COUNT = [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


PID = "6aac1b808f089e43641f5e90"
BER = "Europe/Berlin"


def T(tid, title, start=None, due=None, tz=BER, parent=None, kids=None,
      status=0, **kw):
    """A raw task the way TickTick hands one over."""
    t = {"id": tid, "projectId": PID, "title": title, "startDate": start,
         "dueDate": due, "timeZone": tz, "isAllDay": True, "status": status,
         "parentId": parent, "childIds": kids, "tags": []}
    t.update(kw)
    return t


def D(tid, title, s=None, e=None, parent=None, kids=None, status=0, **kw):
    """A raw task from INCLUSIVE dates, written the way okr writes a span."""
    if s is None:
        return T(tid, title, None, None, parent=parent, kids=kids, status=status, **kw)
    st, du = okr.span_raw(s, e)
    return T(tid, title, st, du, tz="", parent=parent, kids=kids, status=status, **kw)


def d(m, day, y=2026):
    return date(y, m, day)


def by_id(plan):
    return {i: (s, e) for i, s, e in plan}


# ── 1. every title shape in the live list ────────────────────────────────────
LIVE = [
    ("🥅 O • Other things", "O", "Other things", None),
    ("🥅 O • Workflows", "O", "Workflows", None),
    ("🥅 O • Audits • Execute & Establish (Naming Conventions)", "O",
     "Audits • Execute & Establish (Naming Conventions)", None),
    ("🥅 O • KeyCue/MIAs/Shared actions", "O", "KeyCue/MIAs/Shared actions", None),
    ("🥅 O • TickAL", "O", "TickAL", None),
    ("🥅 O • Onboard TickTicks", "O", "Onboard TickTicks", None),
    ("🔑 KR • Change keyboard in ScutsWiz", "KR", "Change keyboard in ScutsWiz", None),
    ("🔑 KR • Files and folders WF", "KR", "Files and folders WF", None),
    ("🔑 KR • Backups WF", "KR", "Backups WF", None),
    ("🔑 KR • ScutsWiz WF", "KR", "ScutsWiz WF", None),
    ("🔑 KR • Linky (URL getter) WF", "KR", "Linky (URL getter) WF", None),
    ("🔑 KR • Eagle WF", "KR", "Eagle WF", None),
    ("🔑 KR • AnyBox WF", "KR", "AnyBox WF", None),
    ("🔑 KR • Typinator WF", "KR", "Typinator WF", None),
    ("🔑 KR • Publish - TA", "KR", "Publish", "TA"),
    ("🔑 KR • ReReadmeadme - TA", "KR", "ReReadmeadme", "TA"),
    ("🔑 KR • Run codebase review skill - TA", "KR", "Run codebase review skill", "TA"),
    ("🔑 KR • Figure out bridges wf - TA", "KR", "Figure out bridges wf", "TA"),
    ("🔑 KR • Review/test content pl wf - TA", "KR", "Review/test content pl wf", "TA"),
    ("🔑 KR • Goals wf - TA", "KR", "Goals wf", "TA"),
    ("🔑 KR • Review - TT", "KR", "Review", "TT"),
    ("🔑 KR • Curriculums - TT", "KR", "Curriculums", "TT"),
    ("🔑 KR • Audits - TT", "KR", "Audits", "TT"),
    ("🔑 KR • Reschedule Goals (used to be OKRs) - TT", "KR",
     "Reschedule Goals (used to be OKRs)", "TT"),
    ("🔑 KR • Finish periodic notes - TT", "KR", "Finish periodic notes", "TT"),
]
for n in ("Eagle", "YNAB", "KeyCue", "Typinator", "Keyboard Maestro", "AnyBox"):
    LIVE.append((f"🔑 KR • {n} - Audit", "KR", n, "Audit"))
for n in ("Obsidian", "Spotify", "Sleeve", "Safari", "Numbers", "Zen", "Claude",
          "Bloom", "Finder", "Typinator", "Keyboard Maestro", "Spark", "Eagle",
          "AnyBox", "YNAB", "TickTick"):
    LIVE.append((f"🔑 KR • {n} - Shortcuts", "KR", n, "Shortcuts"))
check("the live list has 47 titles", len(LIVE) == 47, str(len(LIVE)))
for title, kind, name, code in LIVE:
    got = okr.parse_title(title)
    check(f"live: {title}", got == (kind, name, None, code), str(got))

# ── 2. tolerant parsing ─────────────────────────────────────────────────────
TOL = [
    ("🏔️ Y • Productivity System", ("Y", "Productivity System", None, None)),
    ("🏔 Y • Productivity System", ("Y", "Productivity System", None, None)),
    ("🏔️Y•Productivity System", ("Y", "Productivity System", None, None)),
    ("🥅 O · TickAL", ("O", "TickAL", None, None)),
    ("🥅 O - TickAL", ("O", "TickAL", None, None)),
    ("  🥅  O  •   TickAL  ", ("O", "TickAL", None, None)),
    ("🥅️ O • TickAL", ("O", "TickAL", None, None)),
    ("🔑 kr • goals wf - TA", ("KR", "goals wf", None, "TA")),
    ("🔑 KR • Goals   wf  -  TA", ("KR", "Goals wf", None, "TA")),
    ("🔑 KR • Goals wf · TA", ("KR", "Goals wf", None, "TA")),
    ("🔑 KR • Goals wf \\- TA", ("KR", "Goals wf", None, "TA")),
    # the dashes text substitution and pasting make of a hyphen
    ("🔑 KR \u2013 Goals wf \u2013 TA", ("KR", "Goals wf", None, "TA")),
    ("🔑 KR \u2014 Goals wf \u2014 TA", ("KR", "Goals wf", None, "TA")),
    ("🔑 KR \u2212 Goals wf \u2212 TA", ("KR", "Goals wf", None, "TA")),
    ("🥅 O\u2013TickAL", ("O", "TickAL", None, None)),
]
for title, want in TOL:
    got = okr.parse_title(title)
    check(f"tolerant: {title!r}", got == want, str(got))
check("a candidate is only a candidate: parse_title reads 2027 off 'Q4 money - 2027'"
      " (settle_codes, section 15, decides in context)",
      okr.parse_title("🔑 KR • Q4 money - 2027") == ("KR", "Q4 money", None, "2027"))
check("an unspaced dash inside a name is still no separator",
      okr.parse_title("🔑 KR • Goals wf\u2013TA")[1:] == ("Goals wf\u2013TA", None, None))

check("a lower-case last word is a name, not a code",
      okr.parse_title("🔑 KR • Fix the export - again")
      == ("KR", "Fix the export - again", None, None))
check("a spaced • never splits off a code (his names use it)",
      okr.parse_title("🔑 KR • Audits • Execute")
      == ("KR", "Audits • Execute", None, None))
check("an unspaced hyphen is part of the word",
      okr.parse_title("🔑 KR • Re-read - TA") == ("KR", "Re-read", None, "TA"))
check("a code alone is a name (nothing before the separator)",
      okr.parse_title("🔑 KR • - TA")[1:] == ("- TA", None, None))
for title in ("🥅 Onboard TickTick", "O • TickAL", "KR - Something",
              "Buy milk - TA", "🔑 O • Mixed up", "🏔️ KR • Wrong emoji"):
    k, n, _l, c = okr.parse_title(title)
    check(f"not an OKR title: {title!r}", k is None and c is None, str((k, c)))
check("unprefixed keeps its words",
      okr.parse_title("Buy milk")[:2] == (None, "Buy milk"))
check("empty and None parse to nothing",
      okr.parse_title("") == (None, "", None, None)
      and okr.parse_title(None) == (None, "", None, None))

# ── 3. links in titles ───────────────────────────────────────────────────────
TL = "https://ticktick.com/webapp/#p/6a3413e02522110c0d06e678/tasks/6aac1e85b1d3e7b5eb7d7e0a"
LL = "ticktick:///webapp/#p/6a3413e02522110c0d06e678/tasks"
k, n, link, c = okr.parse_title(f"🔑 KR • [Goals wf]({TL}) - TA")
check("task link: name is the label", (k, n, c) == ("KR", "Goals wf", "TA"), str((k, n, c)))
check("task link: url kept raw", link == TL, str(link))
check("task link: target", okr.link_target(link)
      == ("task", "6a3413e02522110c0d06e678", "6aac1e85b1d3e7b5eb7d7e0a"))
k, n, link, c = okr.parse_title(f"🥅 O • [TickAL]({LL})")
check("list link (app scheme)", (k, n, link, c) == ("O", "TickAL", LL, None))
check("list link: target", okr.link_target(LL) == ("list", "6a3413e02522110c0d06e678", None))
check("list link (https form)", okr.link_target(
    "https://ticktick.com/webapp/#p/6a3413e02522110c0d06e678/tasks")
    == ("list", "6a3413e02522110c0d06e678", None))
check("task link (app scheme)", okr.link_target(
    "ticktick:///webapp/#p/abc/tasks/def") == ("task", "abc", "def"))
W = "https://en.wikipedia.org/wiki/Foo_(bar)"
k, n, link, c = okr.parse_title(f"🔑 KR • [Read up]({W}) - TA")
check("other url kept raw, parens and all", (n, link, c) == ("Read up", W, "TA"), str((n, link, c)))
check("other url target", okr.link_target(W) == ("url", None, None))
check("no link, no target", okr.link_target(None) is None and okr.link_target("") is None)
k, n, link, c = okr.parse_title("🔑 KR • Read [the doc](https://x.y/z) today")
check("a link inside words: flattened name, first url",
      (n, link) == ("Read the doc today", "https://x.y/z"), str((n, link)))
esc = "🔑 KR • \\[Goals wf\\]\\(" + TL + "\\) - TA"
check("app-escaped link reads as the link",
      okr.parse_title(esc) == ("KR", "Goals wf", TL, "TA"), str(okr.parse_title(esc)))
got = okr.parse_title(f"🔑 KR • [Sleeve [250]]({TL}) - TA")
check("a label with one level of nested brackets is still the link",
      got == ("KR", "Sleeve [250]", TL, "TA"), str(got))
got = okr.parse_title("🔑 KR • \\[Sleeve \\[250\\]\\]\\(" + TL + "\\) - TA")
check("...escaped by the app too", got == ("KR", "Sleeve [250]", TL, "TA"), str(got))
got = okr.parse_title("🔑 KR • Read [the [draft] doc](https://x.y/z) today")
check("a nested label inside words: flattened, url kept",
      got[1:3] == ("Read the [draft] doc today", "https://x.y/z"), str(got))
got = okr.parse_title(f"🔑 KR • [Goals wf]({TL})- TA")
check("an unspaced '- TA' right after a link's paren is a code",
      got == ("KR", "Goals wf", TL, "TA"), str(got))
got = okr.parse_title(f"🔑 KR • [Read up]({W})\u2013 TA")
check("...after a url that ends in its own paren, with an en dash",
      got == ("KR", "Read up", W, "TA"), str(got))
got = okr.parse_title(f"🔑 KR • [Goals wf]({TL})- again")
check("...but a lower-case word there is no code", got[3] is None and got[2] == TL, str(got))
got = okr.parse_title("🔑 KR • Reschedule Goals (used to be OKRs)- TT")
check("an unspaced dash after a plain paren (no link) is no separator",
      got[3] is None, str(got))
check("builders are areas' own",
      okr.task_link("P", "T") == "https://ticktick.com/webapp/#p/P/tasks/T"
      and okr.list_link("P") == "ticktick:///webapp/#p/P/tasks")
check("built links classify back",
      okr.link_target(okr.task_link("p1", "t1")) == ("task", "p1", "t1")
      and okr.link_target(okr.list_link("p1")) == ("list", "p1", None))

# ── 4. build / parse round trip ─────────────────────────────────────────────
check("the spec's example, exactly",
      okr.build_title("KR", "Goals wf", TL, "TA") == f"🔑 KR • [Goals wf]({TL}) - TA")
check("prefixes are Vex's",
      okr.build_title("Y", "Productivity System") == "🏔️ Y • Productivity System"
      and okr.build_title("O", "TickAL") == "🥅 O • TickAL")
for kind in okr.KINDS:
    for link in (None, TL, LL, W):
        for code in (None, "TA", "OT"):
            for name in ("Goals wf", "Reschedule Goals (used to be OKRs)",
                         "Audits • Execute & Establish"):
                built = okr.build_title(kind, name, link, code)
                check(f"round trip {kind}/{bool(link)}/{code}/{name[:12]}",
                      okr.parse_title(built) == (kind, name, link, code),
                      f"{built!r} -> {okr.parse_title(built)}")
check("a bracketed name comes back with parens",
      okr.parse_title(okr.build_title("KR", "Sleeve [250]", TL))[1] == "Sleeve (250)")
try:
    okr.build_title(None, "x")
    check("build refuses an unknown kind", False)
except ValueError:
    check("build refuses an unknown kind", True)

# ── 5. dates ─────────────────────────────────────────────────────────────────
S = okr.span
check("single day, start == due (Finish periodic notes)",
      S(T("a", "x", "2026-09-18T00:00:00+0200", "2026-09-18T00:00:00+0200"))
      == (d(9, 18), d(9, 18)))
check("single day, due == start + 1 (Change keyboard in ScutsWiz)",
      S(T("a", "x", "2026-12-25T00:00:00+0100", "2026-12-26T00:00:00+0100"))
      == (d(12, 25), d(12, 25)))
check("the UTC 22:00 form is the NEXT day in Berlin (Curriculums)",
      S(T("a", "x", "2026-09-24T22:00:00+0000", "2026-09-24T22:00:00+0000", tz=""))
      == (d(9, 25), d(9, 25)))
check("UTC form, multi-day, exclusive due (Audits - TT: 23-24 Sep)",
      S(T("a", "x", "2026-09-22T22:00:00+0000", "2026-09-24T22:00:00+0000", tz=""))
      == (d(9, 23), d(9, 24)))
check("multi-day exclusive due, local form (Backups WF: 17-20 Dec)",
      S(T("a", "x", "2026-12-17T00:00:00+0100", "2026-12-21T00:00:00+0100"))
      == (d(12, 17), d(12, 20)))
check("v1 form with millis (Files and folders WF: 21-24 Dec)",
      S(T("a", "x", "2026-12-20T23:00:00.000+0000", "2026-12-24T23:00:00.000+0000"))
      == (d(12, 21), d(12, 24)))
check("the chain hands over ON the due date (Backups due = Files start)",
      okr.to_date("2026-12-21T00:00:00+0100", BER)
      == S(T("a", "x", "2026-12-20T23:00:00.000+0000", "2026-12-24T23:00:00.000+0000"))[0])
check("across the clock change (Keyboard Maestro - Shortcuts: 25-26 Oct)",
      S(T("a", "x", "2026-10-25T00:00:00+0200", "2026-10-27T00:00:00+0100"))
      == (d(10, 25), d(10, 26)))
check("same, v1 UTC form",
      S(T("a", "x", "2026-10-24T22:00:00.000+0000", "2026-10-26T23:00:00.000+0000"))
      == (d(10, 25), d(10, 26)))
check("undated", S(T("a", "x")) == (None, None))
check("only a due = one day",
      S(T("a", "x", None, "2026-09-24T22:00:00+0000", tz="")) == (d(9, 25), d(9, 25)))
check("only a start = one day",
      S(T("a", "x", "2026-09-24T22:00:00+0000", None, tz="")) == (d(9, 25), d(9, 25)))
check("a TIMED due is on its own day",
      S(T("a", "x", "2026-09-18T08:00:00+0000", "2026-09-19T10:00:00+0000",
          isAllDay=False)) == (d(9, 18), d(9, 19)))
check("a due before the start reads as one day",
      S(T("a", "x", "2026-09-20T00:00:00+0200", "2026-09-18T00:00:00+0200"))
      == (d(9, 20), d(9, 20)))
check("[:10] would have been wrong", okr.to_date("2026-09-24T22:00:00+0000", "")
      != date(2026, 9, 24))
check("an unknown zone falls back to Berlin",
      okr.to_date("2026-09-24T22:00:00+0000", "Mars/Olympus") == d(9, 25))
check("a date-only string", okr.to_date("2026-09-18") == d(9, 18))
check("garbage is None", okr.to_date("soon") is None and okr.to_date(None) is None)

# ── 6. writers ───────────────────────────────────────────────────────────────
SR = okr.shift_raw
check("shift keeps the UTC form across the clock change",
      SR("2026-10-24T22:00:00.000+0000", "2026-10-26T23:00:00.000+0000", 7, BER)
      == ("2026-10-31T23:00:00.000+0000", "2026-11-02T23:00:00.000+0000"),
      str(SR("2026-10-24T22:00:00.000+0000", "2026-10-26T23:00:00.000+0000", 7, BER)))
check("shift keeps the local form and takes the new offset",
      SR("2026-10-25T00:00:00+0200", "2026-10-27T00:00:00+0100", 7, BER)
      == ("2026-11-01T00:00:00+0100", "2026-11-03T00:00:00+0100"))
check("shift keeps the start == due single-day shape",
      SR("2026-09-24T22:00:00+0000", "2026-09-24T22:00:00+0000", 1, "")
      == ("2026-09-25T22:00:00+0000", "2026-09-25T22:00:00+0000"))
check("negative shift",
      SR("2026-12-17T00:00:00+0100", "2026-12-21T00:00:00+0100", -3, BER)
      == ("2026-12-14T00:00:00+0100", "2026-12-18T00:00:00+0100"))
raw = T("a", "x", "2026-10-24T22:00:00.000+0000", "2026-10-26T23:00:00.000+0000")
ns, nd = SR(raw["startDate"], raw["dueDate"], 7, BER)
check("a shifted item reads 7 days later",
      S(dict(raw, startDate=ns, dueDate=nd)) == (d(11, 1), d(11, 2)))
check("an undated field stays undated", SR(None, None, 3) == (None, None))
check("a colon offset keeps its colon",
      SR("2026-09-18T00:00:00+02:00", None, 1, BER)[0] == "2026-09-19T00:00:00+02:00")
try:
    SR("next tuesday", None, 1)
    check("shift refuses an unreadable date", False)
except ValueError:
    check("shift refuses an unreadable date", True)
check("span_raw writes the exclusive form, UTC by default",
      okr.span_raw(d(9, 29), d(10, 3), BER)
      == ("2026-09-28T22:00:00+0000", "2026-10-03T22:00:00+0000"))
check("span_raw: one day = due the day after",
      okr.span_raw(d(12, 25), d(12, 25), BER)
      == ("2026-12-24T23:00:00+0000", "2026-12-25T23:00:00+0000"))
check("span_raw in a local form",
      okr.span_raw(d(10, 25), d(10, 26), BER, like="2026-10-01T00:00:00+0200")
      == ("2026-10-25T00:00:00+0200", "2026-10-27T00:00:00+0100"))
check("span_raw keeps millis when the like has them",
      okr.span_raw(d(9, 29), d(9, 29), BER, like="2026-01-01T00:00:00.000+0000")[0]
      == "2026-09-28T22:00:00.000+0000")
for s_, e_ in ((d(9, 29), d(10, 3)), (d(10, 20), d(11, 5)), (d(12, 31), d(1, 2, 2027))):
    st, du = okr.span_raw(s_, e_, BER)
    check(f"span_raw reads back {s_}..{e_}", S(T("a", "x", st, du, tz="")) == (s_, e_))
try:
    okr.span_raw(d(10, 3), d(9, 29))
    check("span_raw refuses an end before the start", False)
except ValueError:
    check("span_raw refuses an end before the start", True)
it = okr.from_task(T("a", "🔑 KR • x", "2026-09-24T22:00:00+0000", "2026-09-24T22:00:00+0000", tz=""))
f = okr.write_fields(it, d(9, 27), d(9, 27))
check("write_fields: same length = a shift, form kept",
      f == {"startDate": "2026-09-26T22:00:00+0000", "dueDate": "2026-09-26T22:00:00+0000",
            "isAllDay": True}, str(f))
f = okr.write_fields(it, d(9, 27), d(9, 29))
check("write_fields: new length = the exclusive form",
      f["dueDate"] == "2026-09-29T22:00:00+0000" and f["startDate"] == "2026-09-26T22:00:00+0000",
      str(f))
f = okr.write_fields(okr.from_task(T("a", "x")), d(9, 27), d(9, 27))
check("write_fields: an undated item gets the exclusive form",
      okr.span(dict(T("a", "x"), **f)) == (d(9, 27), d(9, 27)), str(f))
# A TIMED item (dragged into the list with a time) moved at the same length:
# a shift would keep 08:00 / 10:00 and then stamp isAllDay on it, and the
# 10:00 due would read as an exclusive end - a day short.
timed = T("tm", "🔑 KR • timed", "2026-09-18T08:00:00+0000", "2026-09-19T10:00:00+0000",
          isAllDay=False)
tit = okr.from_task(timed)
check("a timed item reads 18-19 Sep", (tit.start, tit.end) == (d(9, 18), d(9, 19)))
f = okr.write_fields(tit, d(9, 20), d(9, 21))
check("write_fields: a timed item, same length, gets the all-day exclusive form",
      f == {"startDate": "2026-09-19T22:00:00+0000", "dueDate": "2026-09-21T22:00:00+0000",
            "isAllDay": True}, str(f))
check("...and reads back as exactly the span asked for",
      okr.span(dict(timed, **f)) == (d(9, 20), d(9, 21)), str(okr.span(dict(timed, **f))))
f = okr.write_fields(okr.from_task(dict(timed, isAllDay=None)), d(9, 20), d(9, 21))
check("write_fields: no isAllDay at all is not all-day either",
      okr.span(dict(timed, **f)) == (d(9, 20), d(9, 21)), str(f))

# ── 7. the live list as a model: Onboard TickTicks + TickAL ─────────────────
LIVE_TASKS = [
    T("ott", "🥅 O • Onboard TickTicks", "2026-09-18T00:00:00+0200", "2026-09-29T00:00:00+0200",
      kids=["k_aud", "k_cur", "k_fin", "k_res", "k_rev"]),
    T("k_fin", "🔑 KR • Finish periodic notes - TT", "2026-09-18T00:00:00+0200",
      "2026-09-18T00:00:00+0200", parent="ott"),
    T("k_res", "🔑 KR • Reschedule Goals (used to be OKRs) - TT", "2026-09-21T22:00:00+0000",
      "2026-09-21T22:00:00+0000", tz="", parent="ott"),
    T("k_aud", "🔑 KR • Audits - TT", "2026-09-22T22:00:00+0000", "2026-09-24T22:00:00+0000",
      tz="", parent="ott"),
    T("k_cur", "🔑 KR • Curriculums - TT", "2026-09-24T22:00:00+0000", "2026-09-24T22:00:00+0000",
      tz="", parent="ott"),
    T("k_rev", "🔑 KR • Review - TT", "2026-09-26T00:00:00+0200", "2026-09-29T00:00:00+0200",
      parent="ott"),
    T("tal", "🥅 O • TickAL", "2026-09-29T00:00:00+0200", "2026-10-15T00:00:00+0200",
      kids=["k_goal", "k_rt", "k_pub", "6aac1f8ab1d3e7b5eb7d7f4c"]),
    T("k_goal", "🔑 KR • Goals wf - TA", "2026-09-18T22:00:00+0000", "2026-09-21T22:00:00+0000",
      tz="", parent="tal"),
    T("k_rt", "🔑 KR • Review/test content pl wf - TA", "2026-09-29T00:00:00+0200",
      "2026-10-04T00:00:00+0200", parent="tal"),
    T("k_pub", "🔑 KR • Publish - TA", "2026-10-12T00:00:00+0200", "2026-10-15T00:00:00+0200",
      parent="tal"),
]
LI = okr.items_from(LIVE_TASKS)
LBY = okr.index(LI)
check("Onboard TickTicks spans 18-28 Sep", (LBY["ott"].start, LBY["ott"].end) == (d(9, 18), d(9, 28)))
check("its KRs already fill it: no heal", "ott" not in okr.wanted_spans(LI)
      or okr.wanted_spans(LI)["ott"] == (d(9, 18), d(9, 28)))
heals = okr.heal_diff(LI)
check("TickAL heals to its Goals wf start (the live stale span)",
      heals == [("tal", d(9, 19), d(10, 14))], str(heals))
check("a deleted childId is dangling", okr.dangling(LI) == [("tal", "6aac1f8ab1d3e7b5eb7d7f4c")])
check("progress counts nowhere what was deleted", okr.progress(LBY["tal"], LI) == (0, 3))
check("code_of reads the majority suffix (TT, never corrected to OT)",
      okr.code_of(LBY["ott"], okr.krs_of(LBY["ott"], LI)) == "TT")

check("the healed copy carries the wanted span, the input keeps the stored one",
      okr.index(okr.healed(LI))["tal"].start == d(9, 19) and LBY["tal"].start == d(9, 29))

# Workflows, live 2026-09-18: stored 1-24 Dec, its Typinator WF runs 26-30 Nov
WF = [
    T("wf", "🥅 O • Workflows", "2026-12-01T00:00:00+0100", "2026-12-25T00:00:00+0100",
      kids=["typ", "any"]),
    T("typ", "🔑 KR • Typinator WF", "2026-11-26T00:00:00+0100", "2026-12-01T00:00:00+0100",
      parent="wf"),
    T("any", "🔑 KR • AnyBox WF", "2026-12-01T00:00:00+0100", "2026-12-05T00:00:00+0100",
      parent="wf"),
]
WI = okr.items_from(LIVE_TASKS + WF)
nov = okr.overlapping(WI, d(11, 1), d(11, 30), kinds=("O", "KR"))
check("November's plan (O's + KRs): the Workflows / Typinator WF pair",
      [i.id for i in nov] == ["typ", "wf"], str([i.id for i in nov]))
check("November's O's alone: Workflows, on its WANTED span",
      [i.id for i in okr.overlapping(WI, d(11, 1), d(11, 30), kinds=("O",))] == ["wf"])
check("the stored span alone would have missed it",
      okr.index(WI)["wf"].start == d(12, 1))

# ── 8. tree with orphans ─────────────────────────────────────────────────────
TREE = [
    D("y1", "🏔️ Y • Productivity System", d(10, 1), d(10, 15), kids=["oa", "kr_y"]),
    D("oa", "🥅 O • TickAL", d(10, 1), d(10, 9), parent="y1", kids=["a1", "a2"]),
    D("a1", "🔑 KR • One - TA", d(10, 1), d(10, 3), parent="oa"),
    D("a2", "🔑 KR • Two - TA", d(10, 4), d(10, 9), parent="oa"),
    D("kr_y", "🔑 KR • Straight under the Y", d(10, 10), d(10, 15), parent="y1"),
    D("oc", "🥅 O • Loose objective", d(11, 1), d(11, 3), kids=["c1", "step"]),
    D("c1", "🔑 KR • Its KR", d(11, 1), d(11, 3), parent="oc"),
    D("step", "just a step", parent="oc"),
    D("oe", "🥅 O • Parent was deleted", d(12, 1), d(12, 2), parent="gone"),
    D("k0", "🔑 KR • Nobody's KR", d(12, 5), d(12, 5)),
    D("idea", "Loose idea", kids=["under_idea"]),
    D("under_idea", "🔑 KR • Under an idea", parent="idea"),
    D("oo", "🥅 O • An O inside an O", d(11, 2), d(11, 2), parent="oc"),
]
TI = okr.items_from(TREE)
tr = okr.tree(TI)
ids = lambda nodes: [n[0].id for n in nodes]  # noqa: E731
check("years", ids(tr["years"]) == ["y1"], str(ids(tr["years"])))
check("O without a Y, and O whose parent is gone", ids(tr["orphan_os"]) == ["oc", "oe"],
      str(ids(tr["orphan_os"])))
check("KR without an O", ids(tr["orphan_krs"]) == ["k0"])
check("unprefixed roots are loose", ids(tr["loose"]) == ["idea"])
check("every unprefixed item reported", [i.id for i in tr["unprefixed"]] == ["idea", "step"],
      str([i.id for i in tr["unprefixed"]]))
check("misplaced: KR under a Y, KR under an idea, O inside an O",
      sorted(i.id for i in tr["misplaced"]) == ["kr_y", "oo", "under_idea"],
      str([i.id for i in tr["misplaced"]]))


def walk(nodes, out):
    for it_, kids in nodes:
        out.append(it_.id)
        walk(kids, out)
    return out


seen = walk(tr["years"] + tr["orphan_os"] + tr["orphan_krs"] + tr["loose"], [])
check("nothing dropped, nothing twice", sorted(seen) == sorted(t["id"] for t in TREE),
      str(sorted(seen)))
loop = okr.tree(okr.items_from([T("la", "🥅 O • Loop A", parent="lb"),
                                T("lb", "🔑 KR • Loop B", parent="la")]))
check("even a parentId loop drops nothing",
      sorted(walk(loop["orphan_os"] + loop["orphan_krs"], [])) == ["la", "lb"],
      str(loop))
y_node = tr["years"][0]
check("Y -> O -> KR nesting, dated in start order",
      [n[0].id for n in y_node[1]] == ["oa", "kr_y"]
      and [n[0].id for n in y_node[1][0][1]] == ["a1", "a2"])
check("undated children sort last", [n[0].id for n in tr["orphan_os"][0][1]][-1] == "step")

# ── 9. heal ──────────────────────────────────────────────────────────────────
HEAL = [
    D("y", "🏔️ Y • Year", d(9, 1), d(9, 2), kids=["o1", "o2"]),
    D("o1", "🥅 O • Stale wide", d(8, 1), d(12, 31), parent="y", kids=["k1", "k2", "ku"]),
    D("k1", "🔑 KR • A", d(10, 1), d(10, 3), parent="o1"),
    D("k2", "🔑 KR • B", d(10, 4), d(10, 10), parent="o1"),
    D("ku", "🔑 KR • Undated", parent="o1"),
    D("o2", "🥅 O • Undated but has dated kids", parent="y", kids=["k3"]),
    D("k3", "🔑 KR • C", d(11, 1), d(11, 5), parent="o2"),
    D("o3", "🥅 O • Only undated kids", d(9, 5), d(9, 6), kids=["k4"]),
    D("k4", "🔑 KR • D", parent="o3"),
    D("o4", "🥅 O • No kids", d(9, 7), d(9, 8)),
    D("o5", "🥅 O • Already right", d(12, 1), d(12, 3), kids=["k5"]),
    D("k5", "🔑 KR • E", d(12, 1), d(12, 3), parent="o5", status=2),
]
HI = okr.items_from(HEAL)
w = okr.wanted_spans(HI)
check("O span = first dated KR start .. last dated KR end", w["o1"] == (d(10, 1), d(10, 10)))
check("the Y reads its O's WANTED spans, not o1's stale stored one",
      w["y"] == (d(10, 1), d(11, 5)), str(w.get("y")))
check("an undated O with dated kids gets a span", w["o2"] == (d(11, 1), d(11, 5)))
check("only undated kids = left alone", "o3" not in w)
check("no kids = left alone", "o4" not in w)
check("a completed KR still shapes the span", w["o5"] == (d(12, 1), d(12, 3)))
hd = okr.heal_diff(HI)
check("heal diff lists only what differs, O's before their Y",
      [x[0] for x in hd] == ["o1", "o2", "y"], str(hd))
check("heal diff values", by_id(hd) == {"o1": (d(10, 1), d(10, 10)),
                                          "o2": (d(11, 1), d(11, 5)),
                                          "y": (d(10, 1), d(11, 5))})
ab = okr.items_from(HEAL + [D("kab", "🔑 KR • Won't do", d(1, 1), d(1, 2), parent="o5",
                              status=-1)])
check("an abandoned KR does not stretch its O", okr.wanted_spans(ab)["o5"] == (d(12, 1), d(12, 3)))
hist = okr.items_from([
    D("od", "🥅 O • Closed", d(9, 1), d(9, 2), kids=["kd1"], status=2),
    D("kd1", "🔑 KR • It ran later", d(9, 5), d(9, 9), parent="od", status=2),
    D("ow", "🥅 O • Won't do", d(9, 1), d(9, 2), kids=["kw1"], status=-1),
    D("kw1", "🔑 KR • Its KR", d(9, 5), d(9, 9), parent="ow"),
    D("oo2", "🥅 O • Open, same shape", d(9, 1), d(9, 2), kids=["ko1"]),
    D("ko1", "🔑 KR • Its KR", d(9, 5), d(9, 9), parent="oo2"),
])
check("a done or won't-do O is history: heal never targets it, the open twin heals",
      okr.heal_diff(hist) == [("oo2", d(9, 5), d(9, 9))], str(okr.heal_diff(hist)))

# ── 10. progress ─────────────────────────────────────────────────────────────
PROG = [
    D("y", "🏔️ Y • Year", kids=["o1", "o2"]),
    D("o1", "🥅 O • One", parent="y", kids=["p1", "p2", "p3", "deleted1", "pab"]),
    D("p1", "🔑 KR • Open", d(10, 1), d(10, 2), parent="o1"),
    # a completed KR comes from v2 project_completed, not the open data -
    # with its parentId, which is what ties it to its O
    D("p2", "🔑 KR • Done", d(10, 3), d(10, 4), parent="o1", status=2),
    D("p3", "🔑 KR • Open too", parent="o1"),
    D("pab", "🔑 KR • Won't do", parent="o1", status=-1),
    D("o2", "🥅 O • Two", parent="y", kids=["q1"]),
    D("q1", "🔑 KR • Done", d(10, 5), d(10, 5), parent="o2", status=2),
    D("q2", "🔑 KR • Missing from childIds", parent="o2", status=2),
]
PI = okr.items_from(PROG)
PBY = okr.index(PI)
check("progress with a completed child", okr.progress(PBY["o1"], PI) == (1, 3),
      str(okr.progress(PBY["o1"], PI)))
check("a stale childIds is backed by parentId", okr.progress(PBY["o2"], PI) == (2, 2))
check("a Y aggregates the KRs of all its O's", okr.progress(PBY["y"], PI) == (3, 5))
check("a KR is its own progress", okr.progress(PBY["p2"], PI) == (1, 1)
      and okr.progress(PBY["p1"], PI) == (0, 1))
check("an O with no KRs is 0/0", okr.progress(okr.from_task(D("x", "🥅 O • Empty")), []) == (0, 0))
# A KR moved from one O to another stays in the OLD O's childIds. Counting
# childIds put it under both.
MOVED = okr.items_from([
    D("y", "🏔️ Y • Year", kids=["old", "new"]),
    D("old", "🥅 O • Old home", parent="y", kids=["mv", "stay"]),
    D("stay", "🔑 KR • Stayed", parent="old"),
    D("new", "🥅 O • New home", parent="y", kids=["mv"]),
    D("mv", "🔑 KR • Moved", parent="new", status=2),
])
MBY = okr.index(MOVED)
check("stale childIds: the old O no longer counts a KR that moved away",
      okr.progress(MBY["old"], MOVED) == (0, 1), str(okr.progress(MBY["old"], MOVED)))
check("stale childIds: the new O counts it", okr.progress(MBY["new"], MOVED) == (1, 1))
check("stale childIds: the Y counts it once", okr.progress(MBY["y"], MOVED) == (1, 2))
check("stale childIds are no dangling ids (the KR exists)", okr.dangling(MOVED) == [])
check("a childId that is not in the list at all is not counted, only dangling",
      okr.progress(PBY["o1"], PI)[1] == 3 and ("o1", "deleted1") in okr.dangling(PI))
YAB = okr.items_from([
    D("y", "🏔️ Y • Year", kids=["ok", "gone"]),
    D("ok", "🥅 O • Kept", parent="y", kids=["k"]),
    D("k", "🔑 KR • open", parent="ok"),
    D("gone", "🥅 O • Won't do", parent="y", kids=["g"], status=-1),
    D("g", "🔑 KR • done under a won't-do O", parent="gone", status=2)])
check("a Y skips a won't-do O and every KR under it",
      okr.progress(okr.index(YAB)["y"], YAB) == (0, 1), str(okr.progress(okr.index(YAB)["y"], YAB)))
check("a Y counts the KRs hung straight under it too (TREE y1: a1, a2 + kr_y)",
      okr.progress(okr.index(TI)["y1"], TI) == (0, 3), str(okr.progress(okr.index(TI)["y1"], TI)))

# ── 11. pace (Onboard TickTicks, seen from 25 Sep, Finish periodic notes done) ─
PACE = [dict(t) for t in LIVE_TASKS[:6]]
PACE[1]["status"] = 2
PACE.append(T("k_und", "🔑 KR • Someday - TT", parent="ott"))
PACE[0]["childIds"] = PACE[0]["childIds"] + ["k_und"]
PAI = okr.items_from(PACE)
p = okr.pace(okr.index(PAI)["ott"], PAI, today=d(9, 25))
check("expected = dated KRs ended before today", p.expected == 3, str(p))
check("actual = done KRs", p.actual == 1, str(p))
check("behind = today - end of the earliest open late KR (Reschedule, 22 Sep)",
      p.behind_days == 3, str(p))
check("elapsed counts TODAY: 25 Sep is day 8 of 11", abs(p.elapsed - 8 / 11) < 1e-9, str(p))
p = okr.pace(okr.index(PAI)["ott"], PAI, today=d(9, 18))
check("the first day is day 1 of 11, not 0", abs(p.elapsed - 1 / 11) < 1e-9, str(p))
p = okr.pace(okr.index(PAI)["ott"], PAI, today=d(9, 28))
check("the last day is all of it", p.elapsed == 1.0, str(p))
p = okr.pace(okr.index(PAI)["ott"], PAI, today=d(9, 17))
check("the day before the start: 0", p.elapsed == 0.0, str(p))
p = okr.pace(okr.index(PAI)["ott"], PAI, today=d(9, 1))
check("before the span: nothing due, 0 elapsed", (p.expected, p.behind_days, p.elapsed) == (0, 0, 0.0))
PAI_U = okr.items_from(PACE + [T("k_ud", "🔑 KR • Done, never dated - TT", parent="ott", status=2)])
p = okr.pace(okr.index(PAI_U)["ott"], PAI_U, today=d(9, 25))
check("an undated DONE KR counts in actual, never in expected",
      (p.actual, p.expected) == (2, 3), str(p))
p = okr.pace(okr.index(PAI)["ott"], PAI, today=d(10, 30))
check("after the span: everything dated due, all elapsed",
      (p.expected, p.elapsed) == (5, 1.0) and p.behind_days == (d(10, 30) - d(9, 22)).days, str(p))
p = okr.pace(LBY["tal"], LI, today=d(9, 20))
check("pace reads the WANTED span, not TickAL's stale one",
      p.elapsed is not None and p.elapsed > 0, str(p))
p = okr.pace(okr.from_task(D("x", "🥅 O • Undated")), [], today=d(9, 20))
check("an undated O with no KRs: no elapsed", p == okr.Pace(0, 0, 0, None), str(p))

# ── 12. the plan for a period ────────────────────────────────────────────────
wk = okr.overlapping(PAI, d(9, 21), d(9, 27), kinds=("KR",))
check("week 21-27 Sep: the KRs touching it, in order",
      [i.id for i in wk] == ["k_res", "k_aud", "k_cur", "k_rev"], str([i.id for i in wk]))
check("a day: only what covers it",
      [i.id for i in okr.overlapping(PAI, d(9, 24), d(9, 24), kinds=("KR",))] == ["k_aud"])
check("objectives for the quarter",
      [i.id for i in okr.overlapping(LI, d(7, 1), d(9, 30), kinds=("O",))] == ["ott", "tal"])
check("inclusive at both ends",
      [i.id for i in okr.overlapping(PAI, d(9, 28), d(9, 30), kinds=("KR",))] == ["k_rev"])
check("undated never overlaps", all(i.dated for i in okr.overlapping(PAI, d(1, 1), d(12, 31), None)))
check("kinds=None takes unprefixed too",
      "under_idea" not in [i.id for i in okr.overlapping(TI, d(1, 1), d(12, 31), None)]
      and "oc" in [i.id for i in okr.overlapping(TI, d(1, 1), d(12, 31), None)])
OV = okr.items_from(TREE + [D("dstep", "a dated step", d(11, 2), d(11, 2), parent="oc")])
check("kinds=None takes a DATED unprefixed item",
      "dstep" in [i.id for i in okr.overlapping(OV, d(11, 1), d(11, 30), None)])
check("...and the default kinds leave it out",
      "dstep" not in [i.id for i in okr.overlapping(OV, d(11, 1), d(11, 30))])
check("an item starting ON the period's last day is in it",
      [i.id for i in okr.overlapping(PAI, d(9, 16), d(9, 18), kinds=("KR",))] == ["k_fin"])
check("an item ending ON the period's first day is in it",
      [i.id for i in okr.overlapping(PAI, d(9, 28), d(10, 5), kinds=("KR",))] == ["k_rev"])
check("an undated O whose KRs are dated is in the plan",
      "o2" in [i.id for i in okr.overlapping(HI, d(11, 1), d(11, 30), kinds=("O",))])

# ── 12b. the pace of one period (📈 Pace rows) ──────────────────────────────
PP = okr.items_from([
    D("o", "🥅 O • P", d(10, 1), d(10, 12), kids=["k1", "k2", "k3", "k4", "kw"]),
    D("k1", "🔑 KR • early done", d(10, 1), d(10, 3), parent="o", status=2),
    D("k2", "🔑 KR • late open", d(10, 4), d(10, 6), parent="o"),
    D("k3", "🔑 KR • running", d(10, 7), d(10, 9), parent="o"),
    D("k4", "🔑 KR • next week", d(10, 12), d(10, 12), parent="o"),
    D("kw", "🔑 KR • won't do", d(10, 5), d(10, 5), parent="o", status=-1)])
pp = okr.period_pace(PP, d(10, 1), d(10, 9), today=d(10, 8))
check("period pace: KRs overlapping the period, won't-do left out",
      (pp.total, pp.done) == (3, 1), str(pp))
check("period pace: expected = ended before today", pp.expected == 2, str(pp))
check("period pace: behind = today minus the earliest late OPEN end",
      pp.behind_days == 2, str(pp))
check("period pace: an empty period is all zeros",
      tuple(okr.period_pace(PP, d(11, 1), d(11, 30), today=d(10, 8))) == (0, 0, 0, 0))
check("span_txt: one day, a range, another year, undated",
      (okr.span_txt(d(10, 1), d(10, 1), d(1, 1)), okr.span_txt(d(10, 1), d(10, 3), d(1, 1)),
       okr.span_txt(d(1, 2, 2027), d(1, 2, 2027), d(1, 1)), okr.span_txt(None, None))
      == ("Oct 1", "Oct 1 - Oct 3", "Jan 2 2027", "undated"))

# ── 14. auto-tick ────────────────────────────────────────────────────────────
DONE = {("p", "done"), ("p", "list-done")}
AT = [
    T("k1", f"🔑 KR • [Done one]({okr.task_link('p', 'done')}) - TA"),
    T("k2", f"🔑 KR • [Still open]({okr.task_link('p', 'open')}) - TA"),
    T("k3", f"🔑 KR • [A list]({okr.list_link('p')}) - TA"),
    T("k4", f"🔑 KR • [Ticked already]({okr.task_link('p', 'done')}) - TA", status=2),
    T("k5", "🔑 KR • Text only - TA"),
    T("o1", f"🥅 O • [An O]({okr.task_link('p', 'done')})"),
    T("k6", f"🔑 KR • [Unknown]({okr.task_link('p', 'mystery')}) - TA"),
    T("k7", "🔑 KR • [Web](https://example.com) - TA"),
]


def lookup(pid, tid):
    if tid == "mystery":
        return None
    return (pid, tid) in DONE


cand = okr.autotick_candidates(okr.items_from(AT), lookup)
check("auto-tick: only the open KR linked to a done task",
      [i.id for i in cand] == ["k1"], str([i.id for i in cand]))
check("auto-tick: a list link is ticked by hand even when asked",
      okr.autotick_candidates(okr.items_from(AT[2:3]), lambda *a: True) == [])
check("auto-tick: a won't-do KR is never ticked, even when its original is done",
      okr.autotick_candidates(okr.items_from([dict(AT[0], status=-1)]), lookup) == [])

# ── 15. codes ────────────────────────────────────────────────────────────────
for name, want in (("TickAL", "TA"), ("Onboard TickTick", "OT"), ("Onboard TickTicks", "OT"),
                   ("Workflows", "W"), ("VexOS", "VO"), ("HTMLParser", "HP"),
                   ("Audits • Execute & Establish (Naming Conventions)", "AEE"),
                   ("KeyCue/MIAs/Shared actions", "KMS"), ("money 2027", "M2"),
                   (f"[TickAL]({LL})", "TA"), ("🏆", ""), ("", ""),
                   # a word written in capitals = its capitals, capped at 3
                   ("YNAB", "YNA"), ("CRM", "CRM"), ("OKRs", "OKR"), ("KRs", "KR"),
                   ("Q4", "Q4"), (f"[Sleeve [250]]({TL})", "S2")):
    check(f"propose_code({name!r}) = {want!r}", okr.propose_code(name) == want,
          repr(okr.propose_code(name)))
krs = okr.items_from([T("1", "🔑 KR • a - TA"), T("2", "🔑 KR • b - TT"),
                      T("3", "🔑 KR • c - TT"), T("4", "🔑 KR • d")])
O = lambda **kw: okr.from_task(T("o", kw.pop("title", "🥅 O • TickAL"), **kw))  # noqa: E731
check("code_of: the 🏷️ line wins", okr.code_of(O(content="Plan it\n🏷️ TA\nmore"), krs) == "TA")
check("code_of: bullet, no VS16", okr.code_of(O(content="- 🏷 OT"), krs) == "OT")
check("code_of: an escaped description", okr.code_of(O(content="\\- 🏷️ OT"), krs) == "OT")
check("code_of: the desc field counts too", okr.code_of(O(desc="🏷️ XY"), krs) == "XY")
check("code_of: 🏷️ inside a sentence is not a marker",
      okr.code_of(O(content="see the 🏷️ TA tag"), krs) == "TT")
check("code_of: the O's own title suffix next", okr.code_of(O(title="🥅 O • TickAL - TK"), krs) == "TK")
check("code_of: a marker line AND a title code - the marker wins",
      okr.code_of(O(title="🥅 O • TickAL - TK", content="🏷️ TA"), krs) == "TA")
check("code_of: else the MAJORITY KR suffix (TT: 2 of the 3 that carry one)",
      okr.code_of(O(), krs) == "TT")
check("code_of: a tie is no majority", okr.code_of(O(), krs[:2]) is None)
check("code_of: a scatter is no majority",
      okr.code_of(O(), okr.items_from([T("1", "🔑 KR • a - TA"), T("2", "🔑 KR • b - TT"),
                                        T("3", "🔑 KR • c - OT")])) is None)
check("code_of: nothing to go on", okr.code_of(O(), krs[3:]) is None)
check("code_line reads back", okr.code_of(O(content=okr.code_line("TA")), []) == "TA")

# ── 15b. codes in context (settle_codes) ────────────────────────────────────
# Vex's live codes are not all caps: 16 KRs end " - Shortcuts" and 6 end
# " - Audit", and those ARE codes. "Call Anna - Monday" is a name.
LINKED = f"🔑 KR • [Call Anna]({TL}) - Monday"


def settled(tasks):
    return okr.index(okr.items_from(tasks))


S1 = settled([T("o", "🥅 O • TickAL", content="🏷️ TA", kids=["g", "p", "c", "q", "u", "l"]),
              T("g", "🔑 KR • Goals wf - TA", parent="o"),
              T("p", "🔑 KR • Publish - TA", parent="o"),
              T("c", "🔑 KR • Call Anna - Monday", parent="o"),
              T("q", "🔑 KR • Q4 money - 2027", parent="o"),
              T("u", "🔑 KR • Ship it - USA", parent="o"),
              T("l", LINKED, parent="o")])
check("settle: a KR carrying its O's code keeps it", (S1["g"].name, S1["g"].code) == ("Goals wf", "TA"))
check("settle: 'Call Anna - Monday' keeps its name, code None",
      (S1["c"].name, S1["c"].code) == ("Call Anna - Monday", None), str((S1["c"].name, S1["c"].code)))
check("settle: 'Q4 money - 2027' keeps 2027 in the name under an O coded TA",
      (S1["q"].name, S1["q"].code) == ("Q4 money - 2027", None), str((S1["q"].name, S1["q"].code)))
check("settle: an all-caps candidate stays a code even when it is not the O's",
      (S1["u"].name, S1["u"].code) == ("Ship it", "USA"))
check("settle: a linked KR folds its suffix into the name, the link kept",
      (S1["l"].name, S1["l"].link, S1["l"].code) == ("Call Anna - Monday", TL, None),
      str((S1["l"].name, S1["l"].code)))
check("settle: the candidate is still on the item", S1["c"].suffix == "Monday")
check("settle: code_of reads candidates, so a settled list gives the same O code",
      okr.code_of(S1["o"], [S1[k] for k in "gpcqul"]) == "TA")
S1b = settled([T("o", "🥅 O • TickAL", kids=["g", "p", "r", "c"]),
               T("g", "🔑 KR • Goals wf - TA", parent="o"),
               T("p", "🔑 KR • Publish - TA", parent="o"),
               T("r", "🔑 KR • Review - TA", parent="o"),
               T("c", "🔑 KR • Call Anna - Monday", parent="o")])
check("settle: no marker - the KR majority (TA, 3 of 4) is the O's code, Monday folds",
      (S1b["c"].name, S1b["c"].code, S1b["g"].code) == ("Call Anna - Monday", None, "TA"))
S1c = settled([T("o", "🥅 O • Week", kids=["m", "t"]),
               T("m", "🔑 KR • Call Anna - Monday", parent="o"),
               T("t", "🔑 KR • Call Bob - Tuesday", parent="o")])
check("settle: a scatter of weekdays is no code at all",
      (S1c["m"].code, S1c["t"].code, S1c["t"].name) == (None, None, "Call Bob - Tuesday"))
S1d = settled([T("o", "🥅 O • Calls", kids=["c"]),
               T("c", "🔑 KR • Call Anna - Monday", parent="o")])
check("settle: ONE 'Call Anna - Monday' under a fresh O does not vote itself in as its code",
      (S1d["c"].name, S1d["c"].code) == ("Call Anna - Monday", None)
      and okr.code_of(S1d["o"], [S1d["c"]]) is None, str((S1d["c"].name, S1d["c"].code)))
S1e = settled([T("o", "🥅 O • Calls", kids=["a", "b"]),
               T("a", "🔑 KR • Call Anna - Calls", parent="o"),
               T("b", "🔑 KR • Call Bob - Calls", parent="o")])
check("settle: a word carried by two KRs IS the O's code (the live Audit/Shortcuts shape)",
      (S1e["a"].code, S1e["b"].code) == ("Calls", "Calls"))
MIXED = [T("o", "🥅 O • Mixed", kids=["k1", "k2", "k3", "k4"]),
         T("k1", "🔑 KR • One - TA", parent="o"),
         T("k2", "🔑 KR • Two - Shortcuts", parent="o"),
         T("k3", "🔑 KR • Three - Shortcuts", parent="o"),
         T("k4", "🔑 KR • Four - Monday", parent="o")]
S1f = settled(MIXED)
RAWM = okr.index([okr.from_task(t) for t in MIXED])
check("code_of reads CANDIDATES: no majority in [TA, Shortcuts x2, Monday] on the raw list",
      okr.code_of(RAWM["o"], [RAWM[k] for k in ("k1", "k2", "k3", "k4")]) is None)
check("...and the same None on the settled list (settled codes would have said TA)",
      okr.code_of(S1f["o"], [S1f[k] for k in ("k1", "k2", "k3", "k4")]) is None
      and S1f["k1"].code == "TA")
S1g = settled([T("o", "🥅 O • TickAL", content="🏷️ TA", kids=["b", "g"]),
               T("b", "🔑 KR • Plan - B", parent="o"),
               T("g", "🔑 KR • Ship - ABCDEFG", parent="o")])
check("settle: one capital is too short to be a code on its own (2-6)",
      (S1g["b"].name, S1g["b"].code) == ("Plan - B", None), str((S1g["b"].name, S1g["b"].code)))
check("settle: seven capitals is too long to be a code on its own (2-6)",
      (S1g["g"].name, S1g["g"].code) == ("Ship - ABCDEFG", None),
      str((S1g["g"].name, S1g["g"].code)))
S2 = settled([T("o", "🥅 O • Money", content="🏷️ 2027", kids=["q"]),
              T("q", "🔑 KR • Q4 money - 2027", parent="o")])
check("settle: 'Q4 money - 2027' IS coded 2027 when the O's code is 2027",
      (S2["q"].name, S2["q"].code) == ("Q4 money", "2027"), str((S2["q"].name, S2["q"].code)))
AUD = [T("oa", "🥅 O • Audits • Execute & Establish (Naming Conventions)",
         kids=["e", "y", "k"]),
       T("e", "🔑 KR • Eagle - Audit", parent="oa"),
       T("y", "🔑 KR • YNAB - Audit", parent="oa"),
       T("k", "🔑 KR • KeyCue - Audit", parent="oa"),
       T("os", "🥅 O • KeyCue/MIAs/Shared actions", kids=["s1", "s2", "odd"]),
       T("s1", "🔑 KR • Obsidian - Shortcuts", parent="os"),
       T("s2", "🔑 KR • Spotify - Shortcuts", parent="os"),
       T("odd", "🔑 KR • Zen - Audit", parent="os")]
S3 = settled(AUD)
check("settle: the live ' - Audit' KRs keep Audit (their O's majority)",
      all((S3[k].code, S3[k].name) == ("Audit", n)
          for k, n in (("e", "Eagle"), ("y", "YNAB"), ("k", "KeyCue"))),
      str([(S3[k].name, S3[k].code) for k in "eyk"]))
check("settle: the live ' - Shortcuts' KRs keep Shortcuts",
      (S3["s1"].code, S3["s2"].code) == ("Shortcuts", "Shortcuts"))
check("settle: a stray ' - Audit' under the Shortcuts O folds into its name",
      (S3["odd"].name, S3["odd"].code) == ("Zen - Audit", None), str((S3["odd"].name, S3["odd"].code)))
S4 = settled([T("k1", "🔑 KR • Nobody's - TA"), T("k2", "🔑 KR • Nobody's - Monday")])
check("settle: a KR without an O keeps an all-caps code and folds the rest",
      (S4["k1"].code, S4["k2"].code, S4["k2"].name) == ("TA", None, "Nobody's - Monday"))
check("settle: every live title keeps the code parse_title read (whole-list context)",
      all(i.code == i.suffix for i in okr.items_from(LIVE_TASKS)))
check("settle: from_task alone does not settle", okr.from_task(
      T("c", "🔑 KR • Call Anna - Monday")).code == "Monday")

# ── 16. config: the OKR list id ──────────────────────────────────────────────
_load, _env = config.load, os.environ.pop("okr_list_id", None)
try:
    config.load = lambda: {}
    check("key ABSENT from config.json = the default, 🏆Goals Planning",
          config.get_okr_list_id() == PID)
    config.load = lambda: {"okr_list_id": ""}
    check("key present but BLANK in config.json = OFF, not the default",
          config.get_okr_list_id() == "")
    config.load = lambda: {"okr_list_id": None}
    check("key present as null = OFF too", config.get_okr_list_id() == "")
    config.load = lambda: {"okr_list_id": "cfgid"}
    check("key SET in config.json = that list", config.get_okr_list_id() == "cfgid")
    os.environ["okr_list_id"] = "envid"
    check("env present wins", config.get_okr_list_id() == "envid")
    os.environ["okr_list_id"] = ""
    check("env present but blank = OFF, not the default", config.get_okr_list_id() == "")
finally:
    config.load = _load
    os.environ.pop("okr_list_id", None)
    if _env is not None:
        os.environ["okr_list_id"] = _env

# ── 17. the loader: live, fallbacks, and never "no items" on a failure ──────
class FakeV1:
    def __init__(self, data=None, boom=None, tasks=None):
        self.data, self.boom, self.tasks = data, boom, tasks or {}

    def get_project_data(self, pid):
        if self.boom:
            raise self.boom
        return self.data

    def get_task(self, pid, tid):
        if self.boom:
            raise self.boom
        return self.tasks[tid]


class FakeV2:
    def __init__(self, rows, boom=None):
        self.rows, self.boom = rows, boom

    def project_completed(self, pid, days=0, limit=0):
        self.asked = (days, limit)
        if self.boom:
            raise self.boom
        return self.rows


OPEN = [T("o1", "🥅 O • One", kids=["k1", "k2"]), T("k1", "🔑 KR • Open", parent="o1")]
DONE_ROWS = [T("k2", "🔑 KR • Done", parent="o1", status=2),
             T("k1", "🔑 KR • Open (older copy)", parent="o1", status=2),
             T("kd", "🔑 KR • Deleted", parent="o1", status=2, deleted=1)]
CACHE = {}
_get, _age_s = cache.get, cache.age_seconds
cache.get = lambda key: CACHE.get(key)
cache.age_seconds = lambda key: 120 if key in CACHE else None
try:
    v2 = FakeV2(DONE_ROWS)
    snap = okr.load(api=FakeV1({"project": {"name": "🏆Goals Planning"}, "tasks": OPEN}),
                    v2=v2, list_id=PID)
    check("live: source says live", snap.source == "live" and "v1 open 2" in snap.detail, snap.detail)
    check("live: completed asked for COMPLETED_DAYS with the COMPLETED_LIMIT row cap",
          v2.asked == (okr.COMPLETED_DAYS, okr.COMPLETED_LIMIT) and v2.asked[0] >= 365,
          str(v2.asked))
    check("live: open wins a duplicate, deleted rows dropped",
          sorted(i.id for i in snap.items) == ["k1", "k2", "o1"]
          and okr.index(snap.items)["k1"].done is False)
    check("live: the completed KR counts", okr.progress(okr.index(snap.items)["o1"], snap.items) == (1, 2))
    check("live: the list name", snap.name == "🏆Goals Planning")
    check("live + v2 answered under the limit: done_complete, writable",
          snap.done_complete is True and snap.writable is True, snap.detail)

    full = [T(f"c{n}", "🔑 KR • old", parent="o1", status=2) for n in range(okr.COMPLETED_LIMIT)]
    snap = okr.load(api=FakeV1({"tasks": OPEN}), v2=FakeV2(full), list_id=PID)
    check("v2 at the row limit: TRUNCATED said, not complete, not writable",
          snap.done_complete is False and not snap.writable and "TRUNCATED" in snap.detail
          and "reads as deleted" in snap.detail, snap.detail)
    check("...its rows are still read", len(snap.items) == len(OPEN) + okr.COMPLETED_LIMIT)
    snap = okr.load(api=FakeV1({"tasks": OPEN}), v2=FakeV2(full[:-1]), list_id=PID)
    check("one row under the limit is complete", snap.done_complete is True, snap.detail)

    CACHE.clear()
    CACHE["completed_tasks"] = [T("k2", "🔑 KR • Done", parent="o1", status=2),
                                dict(T("zz", "elsewhere", status=2), projectId="other")]
    snap = okr.load(api=FakeV1({"tasks": OPEN}), v2=FakeV2(None), list_id=PID)
    check("v2 down: open stays live, completed from the cache feed",
          snap.source == "live" and sorted(i.id for i in snap.items) == ["k1", "k2", "o1"]
          and "account-wide" in snap.detail, snap.detail)
    check("v2 answered None: 'v2 completed unavailable', not complete, not writable",
          "v2 completed unavailable" in snap.detail and snap.done_complete is False
          and not snap.writable, snap.detail)
    snap = okr.load(api=FakeV1({"tasks": OPEN}), v2=FakeV2(None, boom=ValueError("bad json")),
                    list_id=PID)
    check("v2 raised: unavailable, with why", "v2 completed unavailable (ValueError: bad json)"
          in snap.detail and snap.done_complete is False, snap.detail)
    CACHE["completed_tasks"] = []
    snap = okr.load(api=FakeV1({"tasks": OPEN}), v2=FakeV2(None), list_id=PID)
    check("an EMPTY feed says so - no 'newest 0 only'",
          "newest 0" not in snap.detail and "feed is empty" in snap.detail, snap.detail)
    del CACHE["completed_tasks"]
    snap = okr.load(api=FakeV1({"tasks": OPEN}), v2=FakeV2(None), list_id=PID)
    check("no feed at all says so", "no completed tasks readable" in snap.detail, snap.detail)

    CACHE["completed_tasks"] = [T("k2", "🔑 KR • Done", parent="o1", status=2)]
    CACHE["project_data_" + PID] = {"project": {"name": "cached"}, "tasks": OPEN}
    snap = okr.load(api=FakeV1(boom=ConnectionError("offline")), v2=FakeV2([]), list_id=PID)
    check("v1 down: the cache, and it SAYS so",
          snap.source == "cache" and "offline" in snap.detail and "project_data" in snap.detail,
          snap.detail)
    check("v1 down: the cached items, completed from the feed",
          sorted(i.id for i in snap.items) == ["k1", "k2", "o1"])
    check("v1 down: older completions flagged as reading deleted", "deleted" in snap.detail)
    check("v1 down: a cache read is never writable",
          snap.done_complete is False and not snap.writable)
    check("a network failure carries no interpreter hint, on any python",
          "3.10" not in snap.detail, snap.detail)
    check("the hint is only for an import-time ImportError/TypeError",
          ("3.10+" in okr._why(TypeError("unsupported operand type(s) for |"), at_import=True))
          == (sys.version_info < (3, 10))
          and "3.10+" not in okr._why(TypeError("x"), at_import=False)
          and "3.10+" not in okr._why(ConnectionError("x"), at_import=True))

    del CACHE["project_data_" + PID]
    CACHE["all_tasks"] = OPEN + [dict(T("x", "other list"), projectId="other")]
    snap = okr.load(api=FakeV1(boom=ConnectionError("offline")), v2=FakeV2([]), list_id=PID)
    check("no project cache: all_tasks filtered to the list",
          snap.source == "cache" and sorted(i.id for i in snap.items) == ["k1", "k2", "o1"],
          snap.detail)
    CACHE["all_tasks"] = [dict(T("x", "other list"), projectId="other")]
    try:
        okr.load(api=FakeV1(boom=ConnectionError("offline")), v2=FakeV2([]), list_id=PID)
        check("all_tasks with no row of the list, list unknown = an error", False)
    except okr.OkrLoadError as e:
        check("all_tasks with no row of the list, list unknown = an error",
              "all_tasks" in str(e), str(e))
    CACHE["projects"] = [{"id": "other", "name": "Other"}]
    try:
        okr.load(api=FakeV1(boom=ConnectionError("offline")), v2=FakeV2([]), list_id=PID)
        check("...the cached lists not holding it = still an error", False)
    except okr.OkrLoadError:
        check("...the cached lists not holding it = still an error", True)
    CACHE["projects"] = [{"id": PID, "name": "🏆Goals Planning"}]
    snap = okr.load(api=FakeV1(boom=ConnectionError("offline")), v2=FakeV2([]), list_id=PID)
    check("...the cached lists showing it exists = a real empty open list, from the cache",
          snap.source == "cache" and [i.id for i in snap.items] == ["k2"]
          and snap.name == "🏆Goals Planning", snap.detail)

    CACHE.clear()
    try:
        okr.load(api=FakeV1(boom=ConnectionError("offline")), v2=FakeV2([]), list_id=PID)
        check("down AND no cache = an error, never an empty plan", False)
    except okr.OkrLoadError as e:
        check("down AND no cache = an error, never an empty plan", "offline" in str(e), str(e))
    # A v1 ANSWER of the wrong shape is an error on the spot - even with a
    # cache that could have been shown.
    CACHE["project_data_" + PID] = {"project": {"name": "cached"}, "tasks": OPEN}
    for bad in (["not", "a", "dict"], {}, {"tasks": None}, {"tasks": {"a": 1}}, None):
        try:
            okr.load(api=FakeV1(bad), v2=FakeV2([]), list_id=PID)
            check(f"a malformed v1 answer {bad!r} is OkrLoadError, not no items", False)
        except okr.OkrLoadError:
            check(f"a malformed v1 answer {bad!r} is OkrLoadError, not no items", True)
    try:
        okr.load(api=FakeV1({}), v2=FakeV2([]), list_id="PIDX")
    except okr.OkrLoadError as e:
        check("v1 answering {} names the list as not found", "PIDX not found" in str(e)
              and "okr_list_id" in str(e), str(e))

    # 5(f) through load() itself, on a pretend 3.9: a TypeError while READING
    # is not an interpreter problem; one while IMPORTING the client is.
    class _Sys39:
        version_info = (3, 9, 6)

        def __getattr__(self, name):
            return getattr(sys, name)

    _real_sys = okr.sys
    okr.sys = _Sys39()
    _api_mod = sys.modules.get("api")
    try:
        CACHE.clear()
        CACHE["project_data_" + PID] = {"project": {"name": "cached"}, "tasks": OPEN}
        snap = okr.load(api=FakeV1(boom=TypeError("unsupported operand type(s) for |")),
                        v2=FakeV2([]), list_id=PID)
        check("3.9, a TypeError while READING: no interpreter hint", "3.10+" not in snap.detail,
              snap.detail)

        class _Boom:
            def __getattr__(self, name):
                raise TypeError("unsupported operand type(s) for |")

        sys.modules["api"] = _Boom()
        snap = okr.load(api=None, v2=FakeV2([]), list_id=PID)
        check("3.9, a TypeError while IMPORTING the client: the hint", "3.10+" in snap.detail,
              snap.detail)
    finally:
        okr.sys = _real_sys
        if _api_mod is not None:
            sys.modules["api"] = _api_mod
        else:
            sys.modules.pop("api", None)

    CACHE.clear()
    snap = okr.load(api=FakeV1({"tasks": []}), v2=FakeV2([]), list_id=PID)
    check("a truly empty list reads empty, live", snap.items == [] and snap.source == "live")

    # done_lookup: the GET decides; a failed GET is unknown; None never ticks
    look = okr.done_lookup(api=FakeV1(tasks={
        "t1": {"id": "t1", "status": 2}, "t2": {"id": "t2", "status": 0},
        "n1": {"id": "n1", "status": 2, "kind": "NOTE"},
        "tr": {"id": "tr", "status": 0, "deleted": 1}, "bad": ["?"],
        "wd": {"id": "wd", "status": -1}, "nid": {"status": 2}}))
    check("lookup: a completed task", look("p", "t1") is True)
    check("lookup: an open task", look("p", "t2") is False)
    check("lookup: a note is never done", look("p", "n1") is False)
    check("lookup: a TRASHED task comes back status 0 and never ticks", look("p", "tr") is False)
    check("lookup: an answer that is not a task is unknown", look("p", "bad") is None)
    check("lookup: a WON'T-DO original (status -1) is not done", look("p", "wd") is False)
    check("lookup: an answer without an id is unknown", look("p", "nid") is None)
    CACHE["completed_tasks"] = [{"id": "c1"}, {"id": "both"}, {"id": "n2", "kind": "NOTE"}]
    CACHE["all_tasks"] = [{"id": "c2"}, {"id": "both"}]
    look = okr.done_lookup(api=FakeV1(boom=ConnectionError("offline")))
    check("lookup: a FAILED GET is None, even with the task in the completed cache",
          look("p", "c1") is None)
    check("lookup: a failed GET is None for an open-cached task too", look("p", "c2") is None)

    class _NoClient:
        def __init__(self, token):
            raise RuntimeError("no token")

    _api_mod = sys.modules.get("api")
    sys.modules["api"] = type(sys)("api")
    sys.modules["api"].TickTickAPI = _NoClient
    try:
        look = okr.done_lookup()
        check("lookup, no client at all: the completed cache says done", look("p", "c1") is True)
        check("lookup, no client at all: the open cache says open", look("p", "c2") is False)
        check("lookup, no client at all: the OPEN cache is read first (reopened task)",
              look("p", "both") is False)
        check("lookup, no client at all: unknown stays unknown", look("p", "c3") is None)
        check("lookup, no client at all: a NOTE in the completed feed is not done",
              look("p", "n2") is False)
    finally:
        if _api_mod is not None:
            sys.modules["api"] = _api_mod
        else:
            sys.modules.pop("api", None)

    # the report renders the live-shaped snapshot
    snap = okr.Snapshot(LI, "live", "test", PID, "🏆Goals Planning")
    lines = okr.report(snap, today=d(9, 18))
    txt = "\n".join(lines)
    check("report: the tree, the heal, the dangling count",
          "🥅 O • TickAL" in txt and "Heal (would write, read-only here): 1" in txt
          and "Dangling childIds (deleted or won't-do, counted nowhere): 1" in txt, txt)
    check("report: a Snapshot without done_complete says writers would refuse",
          "writers: would REFUSE" in txt, txt)
    txt = "\n".join(okr.report(okr.Snapshot(LI, "live", "test", PID, "x", True), today=d(9, 18)))
    check("report: a live complete read allows writers", "writers: allowed" in txt)
finally:
    cache.get, cache.age_seconds = _get, _age_s


print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if __name__ == "__main__":
    sys.exit(1 if FAILS else 0)
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
