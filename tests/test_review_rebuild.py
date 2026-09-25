"""The 2026-09-25 review rebuild: the spec's doors parse, the trees hold the
rulings, and the planner keeps ids, retitles by alias, creates the new,
deletes the dropped bottom-up and orders siblings. Pure; no network."""
import os
import re
import sys

WF = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(WF, "src"), os.path.join(WF, "Scripts"),
          os.path.join(WF, "tools", "review_rebuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

import review_spec as spec          # noqa: E402
import rebuild as rb                # noqa: E402
import routine_link as rl           # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def flat(nodes, depth=0):
    for title, kids in nodes:
        yield depth, title
        yield from flat(kids, depth + 1)


_MD = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")

# ── 1. the spec ───────────────────────────────────────────────────────────────
trees = {t: spec.TREES[t]() for t in ("weekly", "monthly", "quarterly")}
titles = {t: [x for _, x in flat(n)] for t, n in trees.items()}
daily = {t: spec.TREES[t]() for t in ("startup", "shutdown")}
dtitles = {t: [x for _, x in flat(n)] for t, n in daily.items()}

check("1.no-dashes", all("–" not in x and "—" not in x for xs in titles.values() for x in xs))
links = [(t, m.group(2)) for t, xs in titles.items() for x in xs for m in _MD.finditer(x)]
bad = []
for t, url in links:
    if url.startswith("alfred://"):
        from urllib.parse import unquote
        arg = unquote(url.split("argument=", 1)[1])
        try:
            rl.parse(arg)
        except Exception as e:
            bad.append((arg, str(e)))
check("1.alfred-links-parse", not bad, str(bad))
check("1.km-by-uid", all(re.fullmatch(r"kmtrigger://macro=[0-9A-F-]{36}", u)
                         for _, u in links if u.startswith("kmtrigger")))
# the two daily routines (Vex 2026-09-25 late, 🟢): links by UID, MIT gone, journal last, doors
dlinks = [(t, m.group(2)) for t, xs in dtitles.items() for x in xs for m in _MD.finditer(x)]
check("5.daily-km-by-uid", all(re.fullmatch(r"kmtrigger://macro=[0-9A-F-]{36}", u)
                               for _, u in dlinks if u.startswith("kmtrigger")) and len([u for _, u in dlinks if u.startswith("kmtrigger")]) == 2)
check("5.daily-alfred-links-parse", all(rl.parse(__import__("urllib.parse").parse.unquote(u.split("argument=", 1)[1])) or True
                                        for _, u in dlinks if u.startswith("alfred://")))
check("5.no-set-mit", not any("mit" in rb.norm(x).split() for x in dtitles["shutdown"]))
_tt = next(n for n in daily["shutdown"] if n[0] == "TickTick")
check("5.journal-last-of-ticktick", "journal%3Aevening" in _tt[1][-1][0]
      and not any("journal" in rb.norm(k[0]) for k in next(n for n in _tt[1] if rb.norm(n[0]) == "wrap the day")[1]))
check("5.doors", any("#f/" + spec.FILTER["overdue"] in x and "overdue" in rb.norm(x) for x in dtitles["shutdown"])
      and any("#f/" + spec.FILTER["status"] in x and "status filter" in rb.norm(x) for x in dtitles["shutdown"]))
check("5.aligns", any(rb.norm(x) == "make sure your daily plan aligns with your goals" for x in dtitles["startup"])
      and "make sure your daily plan aligns with your goals" in spec.ALIASES)
check("5.counts", (len(dtitles["startup"]), len(dtitles["shutdown"])) == (12, 28), str((len(dtitles["startup"]), len(dtitles["shutdown"]))))
check("5.parents-known", all(k in spec.PARENT and k in spec.COLUMN for k in ("startup", "shutdown")))
check("1.tag-urls", spec.tag_url("🚦waiting").endswith("#t/8J-apndhaXRpbmc/tasks")
      and spec.tag_url("🔮someday").endswith("#t/8J-UrnNvbWVkYXk/tasks"))
check("1.counts", (len(titles["weekly"]), len(titles["monthly"]), len(titles["quarterly"])) == (37, 64, 24),
      str((len(titles["weekly"]), len(titles["monthly"]), len(titles["quarterly"]))))
check("1.weekly-has-no-numbers", not any(rb.norm(x) == "numbers" for x in titles["weekly"]))
check("1.weekly-ynab-back", any(rb.norm(x) == "ynab" for x in titles["weekly"]))
check("1.monthly-no-categories", not any("review categories" in rb.norm(x) for x in titles["monthly"]))
check("1.quarterly-categories", any(rb.norm(x) == "ynab: review categories" for x in titles["quarterly"])
      and not any(rb.norm(x) == "review categories" for x in titles["quarterly"]))
check("1.quarterly-single-lines", any(rb.norm(x) == "numbers: compare with the same quarter last year" for x in titles["quarterly"])
      and not any(rb.norm(x) in ("ynab", "numbers") for x in titles["quarterly"]))
check("1.quarterly-no-copied-blocks", not any(rb.norm(x) in ("process my digital inboxes", "mindsweep", "update crm")
                                             for x in titles["quarterly"]))
# the monthly runs first as its OWN routine (its Start quits TickTick and takes the timer)
check("1.quarterly-monthly-first", "argument=routine%3Amonthly" in titles["quarterly"][0]
      and "argument=routine%3Aquarterly" in titles["quarterly"][1])
check("1.portfolio-no-door", any(x == "Portfolio refresh: swap in the best recent pieces" for x in titles["quarterly"]))
_m = [rb.norm(x) for x in titles["monthly"]]
_i = lambda s: next(i for i, x in enumerate(_m) if x.startswith(s))
check("1.monthly-long-overdue-after-overdue", _i("overdue:") < _i("long overdue") < _i("no date:"))
check("1.struck-lines-absent", not any(("receivable" in rb.norm(x)) or ("crm archive" in rb.norm(x))
                                       or ("revenue by offer" in rb.norm(x)) or ("vat" in rb.norm(x).split())
                                       for xs in titles.values() for x in xs))
check("1.journal-once-late", all(sum(1 for x in xs if "journal" in rb.norm(x)) == 1 for xs in titles.values())
      and all([x for x in trees[t] if "journal" in rb.norm(x[0])][0] is trees[t][-2] for t in trees))
check("1.start-first", all(rb.norm(trees[t][0][0]).endswith("review • start") for t in ("weekly", "monthly"))
      and rb.norm(trees["quarterly"][1][0]).endswith("review • start"))
check("1.no-set-goal", not any("set weekly goal" in rb.norm(x) or "set monthly goal" in rb.norm(x)
                               or "set quarterly goal" in rb.norm(x) for xs in titles.values() for x in xs))
check("1.audits-parked", not any("typinator" in rb.norm(x) or "keyboard maestro" in rb.norm(x)
                                 for xs in titles.values() for x in xs))
check("1.repeat-rules", spec.REPEAT["monthly"].endswith("INTERVAL=1;BYMONTHDAY=-1")
      and spec.REPEAT["quarterly"].endswith("INTERVAL=3;BYMONTHDAY=-1"))

# ── 2. norm ───────────────────────────────────────────────────────────────────
check("2.norm-flattens-cut-link",
      rb.norm("[Check how much money you made this ](alfred://x)month") == "check how much money you made this month")
check("2.norm-trailing-space", rb.norm("Work ") == "work")

# ── 3. the planner on a fixture ───────────────────────────────────────────────
ROOT = "root"


def task(tid, title, parent, order, status=0, kids=()):
    return {"id": tid, "title": title, "parentId": parent, "sortOrder": order,
            "status": status, "childIds": list(kids)}


bag = [
    task(ROOT, "♻️ Weekly Review", None, 0, kids=("j", "s", "m", "t")),
    task("j", "[📔 Weekly journal](alfred://j)", ROOT, 1),
    task("s", "[Weekly Review • Start](alfred://s)", ROOT, 2),
    task("m", "[Money](kmtrigger://macro=M)", ROOT, 3, kids=("m1", "m2")),
    task("m1", "[Check how much money you made this ](alfred://m)week", "m", 1),
    task("m2", "[Numbers](kmtrigger://macro=N)", "m", 2, kids=("m21",)),
    task("m21", "Add Income", "m2", 1),
    task("t", "TickTick", ROOT, 4, kids=("t1", "t2", "t3")),
    task("t1", "Review status filter", "t", 1),
    task("t2", "Check stale status", "t", 2, status=2),
    task("t3", "Set Weekly goal", "t", 3, status=2),
    task("ghost", "old copy", ROOT, 9),          # archived occurrence
]
bag[-1]["repeatTaskId"] = "x"
desired = [
    spec.N("[Weekly Review • Start](alfred://s)"),
    spec.N("[Money](kmtrigger://macro=M)",
           spec.N("[Check how much money you made this week](alfred://m)"),
           spec.N("[YNAB](kmtrigger://macro=Y)", spec.N("Reconcile all accounts"))),
    spec.N("TickTick",
           spec.N("[Review status filter, clear stale statuses](ticktick:///f)"),
           spec.N("Waiting for")),
    spec.N("[📔 Weekly journal](alfred://j)"),
]
p = rb.plan_tier("weekly", bag, desired=desired, root=ROOT)
kept = {tid: new for tid, _o, new in p.keep}
check("3.keeps-ids", set(kept) == {"s", "m", "m1", "t", "t1", "j"}, str(sorted(kept)))
check("3.retitle-cut-link", kept["m1"] == "[Check how much money you made this week](alfred://m)")
check("3.retitle-alias", kept["t1"] == "[Review status filter, clear stale statuses](ticktick:///f)")
check("3.no-retitle-same", kept["s"] is None and kept["j"] is None)
check("3.creates", [t for _, t in p.create] == ["[YNAB](kmtrigger://macro=Y)", "Reconcile all accounts", "Waiting for"])
check("3.create-parent-refs", p.create[1][0] == ("new", 0) and p.create[0][0] == "m")
check("3.deletes-bottom-up", p.delete == ["m21", "m2", "t2", "t3"], str(p.delete))
check("3.ghost-untouched", "ghost" not in p.delete and "ghost" not in kept)
order = dict(p.order)
check("3.order-root", order[ROOT] == ["s", "m", "t", "j"])
check("3.order-money", order["m"] == ["m1", ("new", 0)])
check("3.reopen-none-kept-completed", p.reopen == [])
c = p.counts()
check("3.counts", c == {"keep": 6, "retitle": 2, "create": 3, "delete": 4, "reopen": 0}, str(c))

# a kept step that is completed gets reopened, and a second plan is clean
bag2 = [task(ROOT, "r", None, 0, kids=("a",)), task("a", "Reconcile all accounts", ROOT, 1, status=2)]
p2 = rb.plan_tier("weekly", bag2, desired=[spec.N("Reconcile all accounts")], root=ROOT)
check("3.reopen-kept-completed", p2.reopen == ["a"] and p2.counts()["create"] == 0)
bag3 = [task(ROOT, "r", None, 0, kids=("a",)), task("a", "Reconcile all accounts", ROOT, 1)]
p3 = rb.plan_tier("weekly", bag3, desired=[spec.N("Reconcile all accounts")], root=ROOT)
check("3.idempotent", p3.counts() == {"keep": 1, "retitle": 0, "create": 0, "delete": 0, "reopen": 0})

# children read from parentId when childIds lags, and the other way round
bag4 = [task(ROOT, "r", None, 0), task("b", "Lagging", ROOT, 1)]
check("3.children-by-parentid", [t["id"] for t in rb.children_of(ROOT, bag4)] == ["b"])
bag5 = [task(ROOT, "r", None, 0, kids=("c",)), {"id": "c", "title": "Lagging", "sortOrder": 1, "status": 0}]
check("3.children-by-childids", [t["id"] for t in rb.children_of(ROOT, bag5)] == ["c"])
# a trashed task reads back as status 0 with `deleted`; an id this run deleted is gone for good
bag6 = [task(ROOT, "r", None, 0, kids=("d", "e")), task("d", "Trashed", ROOT, 1), task("e", "Gone", ROOT, 2)]
bag6[1]["deleted"] = 1
rb.GONE.add("e")
check("3.trashed-and-gone-skipped", rb.children_of(ROOT, bag6) == [])
rb.GONE.discard("e")
# fetched by id: only a completed task is real (a trashed one reads status 0, no flag)
check("3.fetched-ok", rb.fetched_ok({"id": "x", "status": 2}) and not rb.fetched_ok({"id": "x", "status": 0})
      and not rb.fetched_ok({"id": "x", "status": 2, "deleted": 1}) and not rb.fetched_ok(None)
      and not rb.fetched_ok({"id": "x", "status": 2, "repeatTaskId": "s"}))

# ── 4. the last-day repeat rule in the routine helpers ────────────────────────
import datetime as _dt                  # noqa: E402
import routines as rt                   # noqa: E402
M, Q = spec.REPEAT["monthly"], spec.REPEAT["quarterly"]
check("4.rule-text", rt.rule_text(M) == "the last day of every month" and rt.rule_text(Q) == "the last day, every 3 months",
      f"{rt.rule_text(M)!r} {rt.rule_text(Q)!r}")
check("4.rule-text-30th-unchanged", rt.rule_text("RRULE:FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=30") == "the 30th of every month")
check("4.prev-last-day", rt.prev_occurrence(_dt.date(2026, 11, 30), M) == _dt.date(2026, 10, 31)
      and rt.prev_occurrence(_dt.date(2027, 2, 28), M) == _dt.date(2027, 1, 31)
      and rt.prev_occurrence(_dt.date(2026, 6, 30), Q) == _dt.date(2026, 3, 31)
      and rt.prev_occurrence(_dt.date(2026, 12, 31), Q) == _dt.date(2026, 9, 30))
check("4.prev-30th-unchanged", rt.prev_occurrence(_dt.date(2026, 10, 30), "RRULE:FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=30")
      == _dt.date(2026, 9, 30))

print(f"\n{len(FAILS)} failures" if FAILS else "\nall green")
sys.exit(1 if FAILS else 0)
