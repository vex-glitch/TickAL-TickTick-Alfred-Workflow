#!/usr/bin/env python3
"""Unit suite for src/focus_subtasks.py. Pure stdlib.
Run: python3 tests/test_focus_subtasks.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import focus_subtasks as fs  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


def T(tid, so, title=None, pid="p1", parent=None):
    return {"id": tid, "sortOrder": so, "title": title or tid,
            "projectId": pid, "parentId": parent}


# ── children_summary ─────────────────────────────────────────────────────
s = fs.children_summary([T("b", 20), T("a", 10)], ["a", "b", "x", "y"],
                        done_titles={"x": "Done one"})
check("summary-counts", s["done"] == 2 and s["total"] == 4, s)
check("summary-sort-ascending", [i["tid"] for i in s["items"][:2]] == ["a", "b"],
      [i["tid"] for i in s["items"]])
check("summary-open-first-done-last",
      [i["checked"] for i in s["items"]] == [False, False, True, True])
check("summary-done-title-known",
      next(i for i in s["items"] if i["tid"] == "x")["title"] == "Done one")
check("summary-done-title-unknown",
      next(i for i in s["items"] if i["tid"] == "y")["title"] == "")
check("summary-url-shape",
      s["items"][0]["url"] == "https://ticktick.com/webapp/#p/p1/tasks/a")
check("summary-idx-1based", [i["idx"] for i in s["items"]] == [1, 2, 3, 4])
check("summary-shape-keys", set(s) == {"done", "total", "items", "date"})
check("summary-item-keys",
      set(s["items"][0]) == {"idx", "title", "url", "tid", "pid", "checked"})

s = fs.children_summary([], [], None)
check("summary-empty", s["done"] == 0 and s["total"] == 0 and s["items"] == [])

# a child open in project data but NOT in childIds (fresh, stale parent GET)
# still renders as open - childIds only decides the DONE side
s = fs.children_summary([T("new", 5)], [])
check("summary-open-not-in-childids", s["total"] == 1 and s["done"] == 0)

# ── would_cycle ──────────────────────────────────────────────────────────
CHAIN = {"f": {"parentId": "m"}, "m": {"parentId": "g"}, "g": {}}
lk = CHAIN.get
check("cycle-self", fs.would_cycle("f", "f", lk))
check("cycle-parent", fs.would_cycle("f", "m", lk))
check("cycle-grandparent", fs.would_cycle("f", "g", lk))
check("cycle-unrelated", not fs.would_cycle("f", "z", lk))
check("cycle-none-candidate", not fs.would_cycle("f", None, lk))
LOOP = {"a": {"parentId": "b"}, "b": {"parentId": "a"}}
check("cycle-corrupt-bounded", not fs.would_cycle("a", "z", LOOP.get))

# ── stage_orders ─────────────────────────────────────────────────────────
check("stage-empty", fs.stage_orders([], 2) == [fs.SORT_STEP, 2 * fs.SORT_STEP])
o = fs.stage_orders([-100, 50], 3)
check("stage-appends-below", o[0] == 50 + fs.SORT_STEP and o == sorted(o)
      and len(o) == 3)
check("stage-monotonic-gap", o[1] - o[0] == fs.SORT_STEP)

# ── move_order ───────────────────────────────────────────────────────────
O = [100, 200, 300, 400]
check("move-up-edge", fs.move_order(O, 0, "up") is None)
check("move-up-to-top", fs.move_order(O, 1, "up") == 100 - fs.SORT_STEP)
check("move-up-mid", fs.move_order(O, 2, "up") == 150)
check("move-down-edge", fs.move_order(O, 3, "down") is None)
check("move-down-to-bottom", fs.move_order(O, 2, "down") == 400 + fs.SORT_STEP)
check("move-down-mid", fs.move_order(O, 0, "down") == 250)
check("move-top", fs.move_order(O, 3, "top") == 100 - fs.SORT_STEP)
check("move-top-noop", fs.move_order(O, 0, "top") is None)
check("move-bottom", fs.move_order(O, 0, "bottom") == 400 + fs.SORT_STEP)
check("move-bottom-noop", fs.move_order(O, 3, "bottom") is None)
check("move-unknown", fs.move_order(O, 1, "sideways") is None)
check("move-collapse", fs.move_order([100, 101, 102], 2, "up") == fs.RESPREAD)
check("move-oob", fs.move_order(O, 9, "up") is None)

r = fs.respread(3)
check("respread-ascending", r == sorted(r) and len(r) == 3 and r[0] > 0)

# ── record_note ──────────────────────────────────────────────────────────
n = fs.record_note("2026-07-21", [("Task A", True), ("Task  B\nx", False)])
check("note-shape", n == "### 2026-07-21\n- [x] Task A\n- [ ] Task B x", n)
check("note-empty", fs.record_note("2026-07-21", []) == "")
check("note-untitled",
      fs.record_note("d", [("", True)]) == "### d\n- [x] (untitled)")

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES: {FAILS}")
    sys.exit(1)
print("all green")
