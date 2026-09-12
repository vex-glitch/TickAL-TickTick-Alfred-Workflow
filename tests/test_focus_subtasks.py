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
      set(s["items"][0]) == {"idx", "title", "url", "tid", "pid", "checked",
                             "depth"})
check("summary-depth-default", [i["depth"] for i in s["items"]] == [1, 1, 1, 1])

# ── descendants ──────────────────────────────────────────────────────────
TREE = [T("c1", 20, parent="root"), T("c0", 10, parent="root"),
        T("g0", 5, parent="c1"), T("g1", 6, parent="c1"),
        T("gg", 1, parent="g0"), T("other", 1, parent="elsewhere"),
        T("root", 0)]
d = fs.descendants(TREE, "root")
check("desc-dfs-order", [t["id"] for t in d] == ["c0", "c1", "g0", "gg", "g1"],
      [t["id"] for t in d])
check("desc-depths", [t["_depth"] for t in d] == [1, 1, 2, 3, 2])
check("desc-dfs-stamp", [t["_dfs"] for t in d] == [0, 1, 2, 3, 4])
check("desc-copies", "_depth" not in TREE[0])
check("desc-display-key-sorts",
      [t["id"] for t in sorted(reversed(d), key=fs.display_key)]
      == ["c0", "c1", "g0", "gg", "g1"])
check("desc-max-depth", [t["id"] for t in fs.descendants(TREE, "root", 2)]
      == ["c0", "c1", "g0", "g1"])
check("desc-none-root", fs.descendants(TREE, "") == [])
check("desc-no-kids", fs.descendants(TREE, "gg") == [])
LOOPY = [T("a", 1, parent="r"), T("b", 2, parent="a"), T("r", 0, parent="b")]
check("desc-cycle-safe", [t["id"] for t in fs.descendants(LOOPY, "r")] == ["a", "b"])
# summary keeps the tree order + depth through the DFS stamp
s = fs.children_summary(d, ["c0", "c1", "done"])
check("summary-tree-order",
      [i["tid"] for i in s["items"]] == ["c0", "c1", "g0", "gg", "g1", "done"])
check("summary-tree-depths",
      [i["depth"] for i in s["items"]] == [1, 1, 2, 3, 2, 1])
check("summary-tree-done", s["done"] == 1 and s["total"] == 6)

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

# ── drag-drop: order_at / sibling_gaps / move_block ─────────────────────────
O4 = [100, 200, 300, 400]
for pos, d in ((1, "up"), (2, "up"), (2, "down"), (0, "down"), (3, "top"), (0, "bottom")):
    tgt = {"up": pos - 1, "down": pos + 1, "top": 0, "bottom": 3}[d]
    check(f"order_at == move_order {pos} {d}", fs.order_at(O4, pos, tgt) == fs.move_order(O4, pos, d))
check("order_at no-op", fs.order_at(O4, 2, 2) is None)
check("order_at oob", fs.order_at(O4, 1, 9) is None)
check("order_at jump 0→2", fs.order_at(O4, 0, 2) == 350)       # between 300 and 400
check("order_at jump 3→1", fs.order_at(O4, 3, 1) == 150)       # between 100 and 200
check("order_at collapse", fs.order_at([100, 101, 102], 0, 1) == fs.RESPREAD)
check("order_at single", fs.order_at([100], 0, 0) is None)

# A, B(b1, b2), C, D(d1) - depth-coded DFS display list
R = lambda tid, depth=1: {"tid": tid, "depth": depth}
L = [R("A"), R("B"), R("b1", 2), R("b2", 2), R("C"), R("D"), R("d1", 2)]
check("parents inferred", fs._parents(L) == [None, None, "B", "B", None, None, "D"])
check("subtree end", fs._subtree_end(L, 1) == 4 and fs._subtree_end(L, 5) == 7)
gA = fs.sibling_gaps(L, 0)             # siblings A B C D
check("gaps top-level", gA == [(0, 0), (1, 0), (4, 1), (5, 2), (7, 3)], gA)
gb2 = fs.sibling_gaps(L, 3)            # siblings b1 b2 only
check("gaps nested stay among siblings", gb2 == [(2, 0), (3, 1), (4, 1)], gb2)
check("gaps oob", fs.sibling_gaps(L, 99) == [])
tids = lambda xs: [x["tid"] for x in xs]
check("move_block A below C", tids(fs.move_block(L, 0, 5)) == ["B", "b1", "b2", "C", "A", "D", "d1"])
check("move_block B+kids to end", tids(fs.move_block(L, 1, 7)) == ["A", "C", "D", "d1", "B", "b1", "b2"])
check("move_block D+kid to top", tids(fs.move_block(L, 5, 0)) == ["D", "d1", "A", "B", "b1", "b2", "C"])
check("move_block b2 above b1", tids(fs.move_block(L, 3, 2)) == ["A", "B", "b2", "b1", "C", "D", "d1"])
check("move_block hugging gap = no-op", tids(fs.move_block(L, 1, 4)) == tids(L))
# the drop's local result agrees with the backend's sibling slot
for i in range(len(L)):
    for g, tgt in fs.sibling_gaps(L, i):
        moved = fs.move_block(L, i, g)
        par = fs._parents(moved)
        me = [k for k, t in enumerate(moved) if t["tid"] == L[i]["tid"]][0]
        slot = [k for k in range(len(moved)) if par[k] == par[me]].index(me)
        check(f"slot agrees {L[i]['tid']}@{g}", slot == tgt, (slot, tgt))

# ── review fixes: open_rows / drop_anchor / anchor_slot ─────────────────────
C = lambda tid, depth=1, checked=False: {"tid": tid, "depth": depth, "checked": checked}
M = [C("B", 1, True), C("b1", 2), C("b2", 2), C("C"), C("D"), C("x", 1, True)]
check("open_rows drops a ticked parent's subtree", tids(fs.open_rows(M)) == ["C", "D"], tids(fs.open_rows(M)))
M2 = [C("A"), C("a1", 2, True), C("a1x", 3), C("a2", 2), C("B")]
check("open_rows keeps the ticked row's siblings", tids(fs.open_rows(M2)) == ["A", "a2", "B"], tids(fs.open_rows(M2)))
check("open_rows plain list", tids(fs.open_rows(L)) == tids(L))
rest = ["A", "C", "D"]                      # siblings without the mover
check("drop_anchor top", fs.drop_anchor(rest, 0) == ("before", "A"))
check("drop_anchor middle", fs.drop_anchor(rest, 2) == ("after", "C"))
check("drop_anchor end", fs.drop_anchor(rest, 3) == ("after", "D"))
check("drop_anchor alone", fs.drop_anchor([], 0) == ("at", "0"))
for tgt in range(len(rest) + 1):           # same list both sides → same slot
    kind, anc = fs.drop_anchor(rest, tgt)
    check(f"anchor round trip {tgt}", fs.anchor_slot(rest, kind, anc) == min(tgt, len(rest)))
check("anchor gone → None", fs.anchor_slot(["A", "D"], "after", "C") is None)
# the stale-list case the review reproduced: a sibling added server-side
# above the anchor still lands the row right after its anchor
srv = ["NEW", "A", "C", "D"]
k = fs.anchor_slot(srv, *fs.drop_anchor(rest, 2))
check("stale server list still lands after the anchor", srv[k - 1] == "C", k)

# ── row links + folding (bar right-hand icons, 2026-09-12) ─────────────────
check("markdown link target",
      fs.title_link("[Startup • Start](kmtrigger://macro=Startup%20%E2%80%A2%20Start)")
      == "kmtrigger://macro=Startup%20%E2%80%A2%20Start")
check("alfred link target",
      fs.title_link("[Journal](alfred://runtrigger/com.vex.tickal/Link/?argument=journal%3Aweekly)")
      == "alfred://runtrigger/com.vex.tickal/Link/?argument=journal%3Aweekly")
check("first link wins",
      fs.title_link("[a](ticktick://habit) then [b](https://x.test/)") == "ticktick://habit")
check("no link", fs.title_link("Check todays schedule") is None)
check("empty title", fs.title_link("") is None and fs.title_link(None) is None)
check("bare url", fs.title_link("pay https://ynab.test/budget today")
      == "https://ynab.test/budget")
check("bare url loses trailing punctuation",
      fs.title_link("open https://x.test/a.") == "https://x.test/a")
check("relative target is not openable", fs.title_link("[x](/Users/vex/thing)") is None)
check("javascript refused", fs.title_link("[x](javascript:alert(1))") is None)
check("data refused", fs.title_link("[x](DATA:text/html,hi)") is None)
check("url with parens in the text survives",
      fs.title_link("[Money (YNAB)](kmtrigger://macro=YNAB)") == "kmtrigger://macro=YNAB")

R = [{"tid": "a", "depth": 1}, {"tid": "b", "depth": 2},
     {"tid": "c", "depth": 3}, {"tid": "d", "depth": 1}]
check("kid_tids = rows with a subtree", fs.kid_tids(R) == {"a", "b"})
check("kid_tids on a flat list", fs.kid_tids([{"tid": "a", "depth": 1}]) == set())
check("kid_tids ignores an idless row", fs.kid_tids([{"depth": 1}, {"depth": 2}]) == set())
check("fold hides the whole subtree",
      [r["tid"] for r in fs.fold_rows(R, {"a"})] == ["a", "d"])
check("fold a middle row keeps its parent open",
      [r["tid"] for r in fs.fold_rows(R, {"b"})] == ["a", "b", "d"])
check("no folds = every row", [r["tid"] for r in fs.fold_rows(R, set())]
      == ["a", "b", "c", "d"])
check("folding a leaf changes nothing",
      [r["tid"] for r in fs.fold_rows(R, {"d"})] == ["a", "b", "c", "d"])
check("a folded tid that is gone is ignored",
      [r["tid"] for r in fs.fold_rows(R, {"zz"})] == ["a", "b", "c", "d"])
check("fold survives an empty list", fs.fold_rows([], {"a"}) == [])
check("a folded row still owns its chevron (kids read off the unfolded list)",
      "a" in fs.kid_tids(R) and "a" in {r["tid"] for r in fs.fold_rows(R, {"a"})})
deep = [{"tid": "p", "depth": 1}, {"tid": "q", "depth": 2}, {"tid": "r", "depth": 3},
        {"tid": "s", "depth": 2}, {"tid": "t", "depth": 1}]
check("fold stops at the subtree edge, siblings stay",
      [x["tid"] for x in fs.fold_rows(deep, {"q"})] == ["p", "q", "s", "t"])
check("two folds at once",
      [x["tid"] for x in fs.fold_rows(deep, {"q", "p"})] == ["p", "t"])

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES: {FAILS}")
    sys.exit(1)
print("all green")
