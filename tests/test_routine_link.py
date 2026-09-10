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

check("journal morning", rl.parse("journal:morning") == ("journal", "morning", ""))
check("journal evening", rl.parse("journal:evening") == ("journal", "evening", ""))
check("journal url round trip",
      rl.url("journal", "evening").endswith("?argument=journal%3Aevening"))

# ── parse: everything else is refused ───────────────────────────────────────
check("journal weekly refused", refused("journal:weekly") is not None)
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
check("full list order", keys == ["focus", "sticky", "timer", "calendar", "habits",
                                  "focusview", "matrix", "countdowns", "tasks",
                                  "daily", "daily_sticky", "weekly", "weekly_sticky",
                                  "monthly", "monthly_sticky", "quarterly",
                                  "quarterly_sticky", "yearly", "yearly_sticky",
                                  "morning", "evening"], keys)
check("no item → destinations + journals only",
      [r[0] for r in rl.internal_links()] == keys[3:])
check("periodic off drops daily + journals",
      not {"daily", "morning", "evening"} & {r[0] for r in rl.internal_links(periodic=False)})
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
        check(f"{k} link parses back", rl.parse(arg)[0] in ("focus", "sticky", "timer",
                                                            "view", "journal", "note",
                                                            "notesticky"), arg)
check("every row is markdown", all(r[3].startswith("[") and r[3].endswith(")") for r in il))

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
sys.exit(1 if FAILS else 0)
