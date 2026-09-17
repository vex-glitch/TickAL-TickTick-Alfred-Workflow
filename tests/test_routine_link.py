#!/usr/bin/env python3
"""Unit suite for src/routine_link.py (the clickable-link grammar). Pure
stdlib. Run: python3 tests/test_routine_link.py
"""
import sys
import os
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
import routine_link as rl  # noqa: E402

FAILS = []
COUNT = [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


def refused(arg):
    try:
        rl.parse(arg)
    except ValueError as e:
        return str(e)
    return None


TID = "6a9faa51635ed1022425af34"      # 🌅 Startup (repeating series id)
PID = "6a268ea18f081f1de80eaeb5"

# ── parse: the allowlist ────────────────────────────────────────────────────
check("focus tid+pid", rl.parse(f"focus:{TID}:{PID}") == ("focus", TID, PID))
check("focus tid only", rl.parse(f"focus:{TID}") == ("focus", TID, ""))
check("sticky", rl.parse(f"sticky:{TID}:{PID}")[0] == "sticky")
check("timer", rl.parse(f"timer:{TID}")[0] == "timer")
check("inbox pid", rl.parse(f"focus:{TID}:inbox123456789")[2] == "inbox123456789")
for v in ("ping", "pause", "resume"):
    check(f"bare {v}", rl.parse(v) == (v, "", ""))
check("still-encoded arg decoded once",
      rl.parse(f"focus%3A{TID}%3A{PID}") == ("focus", TID, PID))
check("surrounding whitespace stripped", rl.parse(f"  ping \n") == ("ping", "", ""))

check("done with pid", rl.parse(f"done:{TID}:{PID}") == ("done", TID, PID))
check("done without pid", rl.parse(f"done:{TID}") == ("done", TID, ""))
check("done url round trip",
      rl.url("done", TID, PID).endswith(f"?argument=done%3A{TID}%3A{PID}"))
check("done needs a task", refused("done") is not None)
check("done refuses a slot word", refused("done:weekly") is not None)

check("journal morning", rl.parse("journal:morning") == ("journal", "morning", ""))
check("journal evening", rl.parse("journal:evening") == ("journal", "evening", ""))
check("journal weekly", rl.parse("journal:weekly") == ("journal", "weekly", ""))
check("journal url round trip",
      rl.url("journal", "evening").endswith("?argument=journal%3Aevening"))
check("journal weekly url round trip",
      rl.url("journal", "weekly").endswith("?argument=journal%3Aweekly"))

# ── parse: everything else is refused ───────────────────────────────────────
# monthly and quarterly journals exist since 2026-09-17, and their review
# tasks link to them; yearly still has none
check("journal monthly opens", rl.parse("journal:monthly") == ("journal", "monthly", ""))
check("journal quarterly opens",
      rl.parse("journal:quarterly") == ("journal", "quarterly", ""))
check("journal yearly refused", refused("journal:yearly") is not None)
check("journal without slot", refused("journal") is not None)
check("journal extra field", refused("journal:morning:x") is not None)
check("empty", refused("") == "empty link")
check("xact passthrough", refused(f"xact:focus_sticky:{PID}:{TID}") == "unknown verb")
check("destructive verb", refused("inboxempty") == "unknown verb")
check("bare verb with id", refused(f"ping:{TID}") is not None)
check("task verb without id", refused("focus") is not None)
check("too many fields", refused(f"focus:{TID}:{PID}:x") is not None)
check("uppercase hex tid", refused(f"focus:{TID.upper()}") == "bad task id")
check("short tid", refused("focus:abc123") == "bad task id")
check("bad pid", refused(f"focus:{TID}:../etc") == "bad list id")
check("space inside", refused(f"focus:{TID} :{PID}") == "malformed link")
check("non-ascii", refused(f"focus:{TID}:🌅") == "malformed link")
check("over-long", refused("ping" + ":" * 300) == "malformed link")
check("double-encoded stays invalid", refused(f"focus%253A{TID}") is not None)
check("reason never echoes link text",
      "EVIL" not in (refused("EVILverb:x") or ""))

# ── url: round trip ─────────────────────────────────────────────────────────
u = rl.url("focus", TID, PID)
parts = urlsplit(u)
check("scheme/host", parts.scheme == "alfred" and parts.netloc == "runtrigger")
check("path = bundle/trigger/", parts.path == "/com.vex.tickal/Link/")
check("colons encoded", "%3A" in u and u.count(":") == 1, u)
got = parse_qs(parts.query)["argument"][0]
check("argument decodes back", rl.parse(got) == ("focus", TID, PID), got)
check("bare url", rl.url("ping").endswith("?argument=ping"))
try:
    rl.url("inboxempty")
    check("url refuses what parse refuses", False)
except ValueError:
    check("url refuses what parse refuses", True)

# ── markdown ────────────────────────────────────────────────────────────────
md = rl.markdown("🌅 Startup", "focus", TID, PID)
check("markdown shape", md == f"[🖥 Focus + sticky 🌅 Startup]({u})", md)
md2 = rl.markdown("Read [the doc](https://x.y/z) now", "focus", TID)
check("md link in title flattened", md2.startswith("[🖥 Focus + sticky Read the doc now]("), md2)
md3 = rl.markdown("a ] b [ c", "sticky", TID)
check("brackets dropped", md3.startswith("[🖥 Sticky a  b  c]("), md3)
md4 = rl.markdown("x" * 80, "timer", TID)
check("title capped at 40", md4.startswith("[🖥 Focus " + "x" * 40 + "]("), md4)
check("empty title", rl.markdown("", "focus", TID).startswith("[🖥 Focus + sticky]("))
md5 = rl.markdown("Path C:\\", "focus", TID)
check("trailing backslash dropped", md5.startswith("[🖥 Focus + sticky Path C:]("), md5)
md6 = rl.markdown("y" * 39 + "\\z", "focus", TID)
check("backslash at the cut dropped", "\\" not in md6.split("](")[0], md6)

# ── series_id: completed instance → series ──────────────────────────────────
INST = "6aa257c94524d103dca1815b"
done = [{"id": INST, "repeatTaskId": TID}, {"id": "b" * 24}]
check("instance heals to series", rl.series_id(INST, done) == TID)
check("found in second pool", rl.series_id(INST, None, done) == TID)
check("non-repeating completed → ''", rl.series_id("b" * 24, done) == "")
check("unknown → ''", rl.series_id("c" * 24, done) == "")
check("self-reference → ''", rl.series_id(TID, [{"id": TID, "repeatTaskId": TID}]) == "")
check("junk repeatTaskId → ''", rl.series_id(INST, [{"id": INST, "repeatTaskId": "x:y"}]) == "")

# ── view verb + internal_links ──────────────────────────────────────────────
check("view calendar", rl.parse("view:calendar") == ("view", "calendar", ""))
check("view countdowns", rl.parse("view:countdowns") == ("view", "countdowns", ""))
check("view habits refused (it has an app link)", refused("view:habits") is not None)

il = rl.internal_links("🌅 Startup", TID, PID)
keys = [r[0] for r in il]
check("full list order", keys == ["focus", "sticky", "window", "focuswindow",
                                  "timer", "calendar", "habits",
                                  "focusview", "matrix", "countdowns", "tasks",
                                  "inbox", "crmcal",
                                  "daily", "daily_sticky", "daily_window",
                                  "weekly", "weekly_sticky", "weekly_window",
                                  "monthly", "monthly_sticky", "monthly_window",
                                  "quarterly", "quarterly_sticky", "quarterly_window",
                                  "yearly", "yearly_sticky", "yearly_window",
                                  "morning", "evening", "weekly_journal",
                                  "monthly_journal", "quarterly_journal"], keys)
check("no item → destinations + journals only",
      [r[0] for r in rl.internal_links()] == keys[5:])
check("periodic off drops daily + journals",
      not {"daily", "morning", "evening", "weekly_journal"}
      & {r[0] for r in rl.internal_links(periodic=False)})
check("note daily", rl.parse("note:daily") == ("note", "daily", ""))
check("note weekly", rl.parse("note:weekly") == ("note", "weekly", ""))
check("note yesterday refused", refused("note:yesterday") is not None)
check("notesticky yearly", rl.parse("notesticky:yearly") == ("notesticky", "yearly", ""))
check("notesticky bad spec refused", refused("notesticky:hourly") is not None)
check("weekly sticky link is dynamic",
      dict((r[0], r[3]) for r in il)["weekly_sticky"].endswith("?argument=notesticky%3Aweekly)"))
check("sticky row labels", dict((r[0], r[1]) for r in il)["quarterly_sticky"]
      == "🗒️ Quarterly note sticky")
check("note without slot refused", refused("note") is not None)
check("daily link is dynamic (no note id inside)",
      dict((r[0], r[3]) for r in il)["daily"].endswith("?argument=note%3Adaily)"))
check("bad tid → no item rows", rl.internal_links("x", "nothex", PID)[0][0] == "calendar")
check("bad pid hint dropped, item rows kept",
      rl.internal_links("x", TID, "../x")[0][3].endswith(f"focus%3A{TID})"))
check("app links are plain ticktick://",
      all("(ticktick://" in r[3] for r in il if r[0] in ("habits", "focusview", "matrix", "tasks")))
for k, _t, _s, md in il:
    target = md[md.rindex("(") + 1:-1]
    if target.startswith("alfred://"):
        arg = parse_qs(urlsplit(target).query)["argument"][0]
        check(f"{k} link parses back",
              rl.parse(arg)[0] in ("focus", "focuswindow", "sticky", "window",
                                   "timer", "view", "journal", "note",
                                   "notesticky", "notewindow", "money",
                                   "moneysticky", "moneywindow"), arg)
check("every row is markdown", all(r[3].startswith("[") and r[3].endswith(")") for r in il))

# ── money + crmcal + inbox ──────────────────────────────────────────────────
check("money bare", rl.parse("money") == ("money", "", ""))
check("money takes no id", refused("money:6a955950b4839102c549b053") is not None)
check("view crmcal", rl.parse("view:crmcal") == ("view", "crmcal", ""))
check("inbox app link", rl.APP_LINKS["inbox"] == "ticktick:///webapp/#p/inbox/tasks")
N = lambda i, t, k="NOTE": {"id": i, "title": t, "kind": k}
SEP, AUG, JUL = (N("s" * 24, "2026 September • MT - 2,150"),
                 N("a" * 24, "2026 August • MT - 3490"), N("j" * 24, "2026 July • MT - 5390"))
pool = [JUL, SEP, AUG, N("p" * 24, "Money Priorities"), N("t" * 24, "2026 October • MT", "TEXT")]
check("current month found", rl.money_note(pool, 2026, 9) == (SEP, SEP))
check("older month found", rl.money_note(pool, 2026, 8)[0] is AUG)
check("month not made yet → None + newest",
      rl.money_note(pool, 2026, 10) == (None, SEP))        # the TEXT October is ignored
check("nothing dated", rl.money_note([N("x" * 24, "Money Priorities")], 2026, 9) == (None, None))
check("year boundary newest", rl.money_note(
    [N("d" * 24, "2025 December • MT"), N("n" * 24, "2026 January • MT")], 2026, 2)[1]["id"] == "n" * 24)
check("case-insensitive month", rl.money_note([N("c" * 24, "2026 september • MT")], 2026, 9)[0] is not None)
check("empty pool", rl.money_note(None, 2026, 9) == (None, None))
check("money row gated off by default", "money" not in [r[0] for r in il])
ilm = rl.internal_links("x", TID, PID, money=True)
check("money row after crmcal when on",
      [r[0] for r in ilm].index("money") == [r[0] for r in ilm].index("crmcal") + 1)
check("money link", dict((r[0], r[3]) for r in ilm)["money"].endswith("?argument=money)"))
check("moneysticky bare", rl.parse("moneysticky") == ("moneysticky", "", ""))
check("moneysticky takes no id", refused("moneysticky:x") is not None)
check("money sticky row right after money",
      [r[0] for r in ilm].index("money_sticky") == [r[0] for r in ilm].index("money") + 1)
check("money sticky link",
      dict((r[0], r[3]) for r in ilm)["money_sticky"].endswith("?argument=moneysticky)"))

# sticky_step / sticky_target: (x, y, w, h, sticky 1|pop-up 0, focused 1|0)
ST, SS = rl.sticky_target, rl.sticky_step
S1, S2 = (10, 10, 400, 900, 1, 0), (500, 10, 400, 900, 1, 0)
POP = (1600, -800, 480, 580, 0, 0)          # a task pop-up (AX title "Untitled")
F = lambda r: r[:5] + (1,)                   # the same window, focused
check("sticky_step: one new sticky", SS([S1], [S1, (900, 10, 300, 300, 1, 1)]) == ("new", (900, 10, 300, 300)))
check("sticky_step: a new pop-up is not a sticky", SS([S1], [S1, POP]) == (None, None))
check("sticky_step: new sticky beside a new pop-up", SS([], [POP, S2]) == ("new", (500, 10, 400, 900)))
check("sticky_step: two new stickies = ambiguous", SS([], [S1, S2]) == (None, None))
check("sticky_step: already open, focus moved onto it", SS([F(S1), S2], [S1, F(S2)]) == ("open", (500, 10, 400, 900)))
check("sticky_step: nothing changed", SS([F(S1), S2], [F(S1), S2]) == (None, None))
check("sticky_step: focus moved to a pop-up", SS([F(S1), POP], [S1, F(POP)]) == (None, None))
check("sticky_step: empty snapshots", SS([], []) == (None, None) and SS(None, None) == (None, None))
check("sticky_target = sticky_step's frame", ST([], [S1]) == (10, 10, 400, 900) and ST([S1], [S1]) is None)

# ── the routine registry (src/routines.py) ─────────────────────────────────
import routines as rt  # noqa: E402

check("five routines", len(rt.ROUTINES) == 5, len(rt.ROUTINES))
check("keys unique", len({r["key"] for r in rt.ROUTINES}) == 5)
check("task ids unique", len({r["tid"] for r in rt.ROUTINES}) == 5)
check("every routine is complete",
      all(r.get("tid") and r.get("pid") and r.get("macro") and r.get("habit")
          for r in rt.ROUTINES),
      [r["key"] for r in rt.ROUTINES if not r.get("habit")])
check("task ids parse as link ids",
      all(rl.parse(f"done:{r['tid']}")[1] == r["tid"] for r in rt.ROUTINES))
check("habit ids are 24-hex",
      all(len(r["habit"]) == 24 and all(c in "0123456789abcdef" for c in r["habit"])
          for r in rt.ROUTINES))
check("macro uids all valid", all(rt.valid_macro(r["macro"]) for r in rt.ROUTINES))
check("macro uids unique", len({r["macro"] for r in rt.ROUTINES}) == 5)
check("habits unique per routine", len({r["habit"] for r in rt.ROUTINES}) == 5)
check("by_tid finds each", all(rt.by_tid(r["tid"])["key"] == r["key"] for r in rt.ROUTINES))
check("by_tid misses a stranger (the done: gate refuses any other task)",
      rt.by_tid("0123456789abcdef01234567") is None)
check("by_key round trip", all(rt.by_key(r["key"])["tid"] == r["tid"] for r in rt.ROUTINES))
check("macro_url shape",
      rt.macro_url(rt.ROUTINES[0]["macro"]).startswith("kmtrigger://macro="))
check("every routine has a mintable Finish link",
      all(rl.url("done", r["tid"], r["pid"]).startswith("alfred://runtrigger/")
          for r in rt.ROUTINES))

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if __name__ == "__main__":            # make test / python3 tests/...: exit code
    sys.exit(1 if FAILS else 0)
if FAILS:                             # imported by unittest discover: still red on failure
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
