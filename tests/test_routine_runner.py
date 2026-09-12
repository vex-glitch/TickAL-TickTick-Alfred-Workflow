#!/usr/bin/env python3
"""Unit suite for src/routine_runner.py (the KM-free routine step model).
Run: python3 tests/test_routine_runner.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import routine_runner as rr  # noqa: E402
import routines as rt        # noqa: E402

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


APP = "com.TickTick.task.mac"
GOOD = [
    {"do": "quit", "app": APP, "secs": 15},
    {"do": "activate", "app": APP, "wait": True},
    {"do": "hide_others"},
    {"do": "place", "app": APP, "frame": [10, -20, 800, 600]},
    {"do": "link", "arg": "focus:{tid}:{pid}", "sticky": [1, 2, 3, 4], "bar": [5, 6]},
    {"do": "url", "url": "ticktick:///webapp/#p/inbox/tasks"},
    {"do": "pause", "secs": 3},
    {"do": "key", "key": "escape", "mods": ["shift"]},
]

check("a full list validates", rr.validate(GOOD) == [], rr.validate(GOOD))
check("defaults validate", rr.validate(rr.default_steps()) == [])
check("every period's default validates",
      all(rr.validate(rr.default_steps(s)) == [] for s in
          ("daily", "weekly", "monthly", "quarterly", "yearly")))
check("empty is refused", rr.validate([]) == ["no steps"])
check("not a list is refused", rr.validate({"do": "pause"}) == ["no steps"])
check("unknown step named", "unknown do='dance'" in " ".join(rr.validate([{"do": "dance"}])))
check("place needs a frame", rr.validate([{"do": "place", "app": APP}]))
check("place needs FOUR numbers",
      rr.validate([{"do": "place", "app": APP, "frame": [1, 2, 3]}]))
check("frame rejects text",
      rr.validate([{"do": "place", "app": APP, "frame": [1, 2, 3, "x"]}]))
check("activate needs an app", rr.validate([{"do": "activate"}]))
check("link needs an arg", rr.validate([{"do": "link"}]))
check("sticky must be 4 numbers",
      rr.validate([{"do": "link", "arg": "x", "sticky": [1, 2]}]))
check("bar must be 2 numbers",
      rr.validate([{"do": "link", "arg": "x", "bar": [1, 2, 3]}]))
check("url needs a url", rr.validate([{"do": "url"}]))
check("pause is capped", rr.validate([{"do": "pause", "secs": 999}]))
check("negative pause refused", rr.validate([{"do": "pause", "secs": -1}]))
check("key must be known", rr.validate([{"do": "key", "key": "hyperspace"}]))
check("mods must be real", rr.validate([{"do": "key", "key": "escape", "mods": ["hyper"]}]))
check("a long list is refused", rr.validate([{"do": "hide_others"}] * 61))
check("problems are listed per step", len(rr.validate([{"do": "nope"}, {"do": "url"}])) == 2)

check("expand fills both ids",
      rr.expand({"do": "link", "arg": "focus:{tid}:{pid}"}, "T", "P")["arg"] == "focus:T:P")
check("expand fills a url",
      rr.expand({"do": "url", "url": "x/{pid}/y/{tid}"}, "T", "P")["url"] == "x/P/y/T")
check("expand copies, never mutates",
      (lambda s: (rr.expand(s, "T", "P"), s["arg"])[1] == "focus:{tid}:{pid}")(
          {"do": "link", "arg": "focus:{tid}:{pid}"}))
check("expand leaves other steps alone",
      rr.expand({"do": "place", "app": APP, "frame": [1, 2, 3, 4]}, "T", "P")["frame"]
      == [1, 2, 3, 4])

check("describe covers every step type",
      all(rr.describe(s) and "None" not in rr.describe(s) for s in GOOD))
check("describe names the app", "com.TickTick" in rr.describe(GOOD[0]))
check("describe shows the frame", "800x600" in rr.describe(GOOD[3]))
check("describe shows sticky + bar",
      "sticky" in rr.describe(GOOD[4]) and "bar" in rr.describe(GOOD[4]))

# the shipped registry must be runnable with no config file at all
for r in rt.ROUTINES:
    steps = [rr.expand(s, r["tid"], r["pid"]) for s in rr.default_steps()]
    check(f"{r['key']}: default list runs with its own ids",
          rr.validate(steps) == [] and steps[1]["arg"] == f"focus:{r['tid']}:{r['pid']}")

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if __name__ == "__main__":
    sys.exit(1 if FAILS else 0)
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
