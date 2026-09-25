#!/usr/bin/env python3
"""Rebuild the three ♻️ review trees in TickTick to review_spec (2026-09-25).

    python3.13 tools/review_rebuild/rebuild.py                 # dry run, all tiers
    python3.13 tools/review_rebuild/rebuild.py --tier weekly   # one tier
    python3.13 tools/review_rebuild/rebuild.py --apply         # write
    python3.13 tools/review_rebuild/rebuild.py --apply --repeat   # + the last-day repeat rules

The plan is computed against the LIVE tree (open tasks + the list's completed
feed + any child id neither explains, fetched by id, the reset step's walk),
so a step Vex ticked last Sunday is seen and handled, not resurrected by the
next reset. Matching is by flattened title under the same parent (norm), with
review_spec.ALIASES for reworded lines. Surviving subtasks KEEP their ids
(completion history intact); dropped ones are deleted bottom-up; new ones are
created depth-first under their parent (v1, parentId + the parent's column);
then ONE fresh read of the list feeds a v2 batch that sets every sibling's
sortOrder in spec order, retitles what changed and reopens a kept step that
was completed (the app's own write road, as the reset step does). Idempotent:
a second run plans nothing. Every write follows iron rule 12: the v1 roads
read live, the v2 batch posts only this run's own read.

Rate limit: the v1 API allows 300 calls per 5 minutes; creates and deletes
are paced and counted, and a RateLimitError stops the run (re-run later, the
plan picks up where it stopped).
"""
import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.abspath(os.path.join(HERE, "..", ".."))
for p in (os.path.join(WF, "src"), os.path.join(WF, "Scripts"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import review_spec as spec                      # noqa: E402

_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
PACE = 0.7                                      # s between v1 writes: the live limit is 100
                                                # requests a minute (hit 2026-09-25 at 0.25)
STEP = 1 << 16                                  # sortOrder gap between siblings
GONE = set()                                    # ids this process deleted: a v1 read of a
                                                # trashed task answers status 0 (HANDOFF_OKR)


def norm(title):
    """A title as the planner compares it: links flattened to their text,
    whitespace collapsed, casefolded. "[Check how much money you made this
    ](url)month" and "Check how much money you made this month" are one."""
    t = _MD_LINK.sub(r"\1", title or "")
    return re.sub(r"\s+", " ", t).strip().casefold()


# ── the live tree ────────────────────────────────────────────────────────────
def children_of(parent_id, bag):
    """Open or completed children of `parent_id` in the bag, archived
    occurrences (repeatTaskId) skipped, in the bag's order."""
    by_id = {t["id"]: t for t in bag if t.get("id")}
    seen, out = set(), []
    parent = by_id.get(parent_id) or {}
    ids = list(parent.get("childIds") or [])
    ids += [t["id"] for t in bag if t.get("parentId") == parent_id and t.get("id")]
    for cid in ids:
        if cid in seen or cid in GONE:
            continue
        seen.add(cid)
        t = by_id.get(cid)
        if t is None or t.get("repeatTaskId") or t.get("deleted"):
            continue
        out.append(t)
    out.sort(key=lambda t: t.get("sortOrder") or 0)
    return out


def fetched_ok(t):
    """A task fetched BY ID that the open list and the completed feed did not
    explain: only a COMPLETED one is real. A trashed task reads back as
    status 0 through v1 without any `deleted` flag (the 2026-09-25 apply:
    eight subtasks deleted seconds earlier came back as live children), and
    a live open task would have been in the project data."""
    return bool(t and t.get("id") and t.get("status") == 2 and not t.get("deleted")
                and not t.get("repeatTaskId"))


def descendants(tid, bag):
    """Every task under tid, deepest first (safe delete order)."""
    out = []
    for k in children_of(tid, bag):
        out.extend(descendants(k["id"], bag))
        out.append(k)
    return out


# ── the plan ─────────────────────────────────────────────────────────────────
class Plan:
    def __init__(self, tier):
        self.tier = tier
        self.keep = []        # (tid, live_title, new_title or None)
        self.create = []      # (parent_ref, title)  parent_ref: tid or ("new", index)
        self.delete = []      # tids, deepest first
        self.order = []       # (parent_ref, [child refs in order])
        self.reopen = []      # tids of kept steps that are completed
        self.lines = []       # the rendered plan

    def counts(self):
        retitle = sum(1 for _, _, n in self.keep if n)
        return {"keep": len(self.keep), "retitle": retitle, "create": len(self.create),
                "delete": len(self.delete), "reopen": len(self.reopen)}


def plan_tier(tier, bag, desired=None, root=None):
    """Diff the desired tree against the live one under the tier's parent."""
    plan = Plan(tier)
    root = root or spec.PARENT[tier]
    desired = spec.TREES[tier]() if desired is None else desired

    def walk(parent_ref, parent_id, nodes, depth):
        live = children_of(parent_id, bag) if parent_id else []
        taken = set()
        refs = []
        for title, kids in nodes:
            want = norm(title)
            aliases = (want,) + tuple(spec.ALIASES.get(want, ()))
            hit = next((t for t in live if t["id"] not in taken and norm(t.get("title")) in aliases), None)
            if hit is not None:
                taken.add(hit["id"])
                new = title if (hit.get("title") or "") != title else None
                plan.keep.append((hit["id"], hit.get("title") or "", new))
                if hit.get("status") == 2:
                    plan.reopen.append(hit["id"])
                mark = "R" if new else ("O" if hit.get("status") == 2 else " ")
                plan.lines.append(f"{mark} {'  ' * depth}- {title}")
                refs.append(hit["id"])
                walk(hit["id"], hit["id"], kids, depth + 1)
            else:
                ref = ("new", len(plan.create))
                plan.create.append((parent_ref, title))
                plan.lines.append(f"C {'  ' * depth}- {title}")
                refs.append(ref)
                walk(ref, None, kids, depth + 1)
        for t in live:
            if t["id"] in taken:
                continue
            plan.lines.append(f"D {'  ' * depth}- {t.get('title')}"
                              + ("  (completed)" if t.get("status") == 2 else ""))
            for d in descendants(t["id"], bag):
                plan.lines.append(f"D {'  ' * (depth + 1)}- {d.get('title')}")
                plan.delete.append(d["id"])
            plan.delete.append(t["id"])
        plan.order.append((parent_ref, refs))

    walk(root, root, desired, 0)
    return plan


# ── live reads ───────────────────────────────────────────────────────────────
def load_bag(api, v2, roots, days=120):
    """Open tasks + the completed feed + fetch-by-id for every child id that
    neither explains (the reset step's walk), five rounds deep."""
    import routine_runner as rr
    from api import RateLimitError
    import requests
    bag = list((api.get_project_data(spec.LIST) or {}).get("tasks") or [])
    done = v2.project_completed(spec.LIST, days=days)
    if done is None:
        raise SystemExit("completed feed unreadable; not planning against a half tree")
    bag += done
    asked = set(GONE)
    for root in roots:
        for _ in range(5):
            _todo, unknown = rr.completed_descendants(root, bag, cap=10_000)
            fresh = [u for u in unknown if u not in asked]
            if not fresh:
                break
            asked.update(fresh)
            for miss in fresh:
                try:
                    t = api.get_task(spec.LIST, miss)
                except RateLimitError:
                    raise
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 404:
                        continue             # deleted: a dangling childId
                    raise                    # anything else is not "gone"
                if fetched_ok(t):
                    bag.append(t)            # a trashed task reads status 0: skipped
    return bag


# ── apply ────────────────────────────────────────────────────────────────────
def apply_plan(api, v2, plan, log, cnt):
    """Deletes, creates, then one fresh read feeding a single v2 batch."""
    from api import RateLimitError
    tier = plan.tier
    pid, column = spec.LIST, spec.COLUMN[tier]
    ids = {}                                  # ("new", i) -> tid

    def v1(what):
        cnt["v1"] += 1
        if cnt["v1"] % 40 == 0:
            log(f"   ({cnt['v1']} v1 calls so far)")
        time.sleep(PACE)
        return what()

    for tid in plan.delete:
        try:
            v1(lambda: api.delete_task(pid, tid))
            GONE.add(tid)
            log(f"   deleted {tid}")
        except RateLimitError:
            raise
        except Exception as e:
            log(f"   delete {tid} failed: {type(e).__name__}: {e}")
            raise
    for i, (parent_ref, title) in enumerate(plan.create):
        parent = ids[parent_ref] if isinstance(parent_ref, tuple) else parent_ref
        t = v1(lambda: api.create_task(title, project_id=pid, parent_id=parent, column_id=column))
        if not t or not t.get("id"):
            raise SystemExit(f"create failed for {title!r}: {t}")
        ids[("new", i)] = t["id"]
        log(f"   created {t['id']}  {title}")

    # one fresh read, then the batch: order, retitle, reopen
    live = {t["id"]: t for t in (api.get_project_data(pid) or {}).get("tasks") or [] if t.get("id")}
    cnt["v1"] += 1
    done = v2.project_completed(pid, days=120) or []
    for t in done:
        live.setdefault(t["id"], t)
    new_title = {tid: n for tid, _o, n in plan.keep if n}
    reopen = set(plan.reopen)
    known = set(live) | set(ids.values())     # what a childIds list may still name
    bodies, missing = {}, []

    def prune(b):
        """Drop dangling child ids (TickTick keeps a deleted subtask's id in
        its parent's childIds; every reset would fetch each one by id)."""
        kids = b.get("childIds")
        if kids:
            keep = [k for k in kids if k in known and k not in GONE]
            if keep != kids:
                b["childIds"] = keep
                return True
        return False

    for parent_ref, refs in plan.order:
        for i, ref in enumerate(refs):
            tid = ids[ref] if isinstance(ref, tuple) else ref
            t = live.get(tid)
            if t is None:                     # a kept step completed before the feed window
                try:
                    t = api.get_task(pid, tid)
                    cnt["v1"] += 1
                except Exception:
                    t = None
                if not fetched_ok(t):
                    t = None
            if not t:
                missing.append(tid)
                continue
            b = dict(t)
            b["sortOrder"] = (i + 1) * STEP
            if tid in new_title:
                b["title"] = new_title[tid]
            if tid in reopen:
                b["status"] = 0
                b["completedTime"] = None
            prune(b)
            bodies[tid] = b
    if missing:
        raise SystemExit(f"{len(missing)} planned tasks are not in the fresh read: {missing[:5]}")
    # The parent itself is NOT in the batch: a v2 update of the repeating
    # parent's body answers HTTP 500 unknown_exception (probed 2026-09-25,
    # the body alone; the 37 subtask bodies posted clean), so its dangling
    # child ids stay and the reset step keeps fetching them by id.
    posted, errors = 0, {}
    items = list(bodies.values())
    for i in range(0, len(items), 50):
        chunk = items[i:i + 50]
        ok, err = _post_batch(v2, chunk)
        if not ok:
            raise SystemExit(f"v2 batch refused ({len(chunk)} bodies): {err}; tree is ordered up to here")
        errors.update(err)
        posted += len(chunk) - len(err)
    for tid, e in errors.items():
        log(f"   batch error {tid}: {e}")
    if errors:
        raise SystemExit("v2 batch: errors on subtasks (see log); re-run to finish the tree")
    log(f"   batch: {posted} bodies (order {len(items)}, retitle {len(new_title)}, reopen {len(reopen)})")


def _post_batch(v2, bodies):
    """POST /api/v2/batch/task update, like api_v2.update_tasks (same
    freshness rule) but returning (http_ok, id2error) so a refusal names
    the body: the 2026-09-25 apply died on a bare False."""
    from api import is_fresh
    if not v2.token:
        return False, {"_": "no v2 token"}
    if not all(is_fresh(t) for t in bodies):
        return False, {"_": "a body is not this run's own read"}
    import api_v2 as _v2mod
    requests = _v2mod.requests
    clean = [{k: v for k, v in t.items() if not k.startswith("_")} for t in bodies]
    r = requests.post("https://api.ticktick.com/api/v2/batch/task",
                      headers={**_v2mod._base_headers(), "cookie": f"t={v2.token}",
                               "content-type": "application/json"},
                      json={"add": [], "update": clean, "delete": []}, timeout=25)
    if not r.ok:
        return False, {"_": f"HTTP {r.status_code} {r.text[:200]}"}
    try:
        return True, dict((r.json() or {}).get("id2error") or {})
    except Exception:
        return True, {}


def verify(api, v2, tier, log):
    """Re-plan against a fresh bag: a clean tree plans nothing."""
    bag = load_bag(api, v2, [spec.PARENT[tier]])
    p = plan_tier(tier, bag)
    c = p.counts()
    clean = c["create"] == 0 and c["delete"] == 0 and c["retitle"] == 0 and c["reopen"] == 0
    log(f"   verify {tier}: {'CLEAN' if clean else c}")
    if not clean:
        for ln in p.lines:
            if ln[0] != " ":
                log("     " + ln)
    return clean


def set_repeat(api, tier, log):
    tid, pid, rule = spec.PARENT[tier], spec.LIST, spec.REPEAT[tier]

    def derive(base):
        return None if base.get("repeatFlag") == rule else {"repeatFlag": rule}

    out = api.update_task(tid, pid, derive=derive)
    log(f"   repeat {tier}: {'already ' + rule if out is None else out.get('repeatFlag')}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tier", choices=list(spec.TREES) + ["all"], default="all")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--repeat", action="store_true", help="also set the last-day repeat rules")
    ap.add_argument("--log", default=None)
    a = ap.parse_args(argv)
    tiers = list(spec.TREES) if a.tier == "all" else [a.tier]

    import config as cfg
    import api_v2
    from api import TickTickAPI
    api, v2 = TickTickAPI(cfg.get_token()), api_v2.TickTickV2()
    logf = open(a.log, "a") if a.log else None

    def log(s):
        print(s)
        if logf:
            logf.write(s + "\n")
            logf.flush()

    log(f"== review rebuild {time.strftime('%Y-%m-%d %H:%M:%S')} tiers={tiers} apply={a.apply}")
    bag = load_bag(api, v2, [spec.PARENT[t] for t in tiers])
    plans = {t: plan_tier(t, bag) for t in tiers}
    for t, p in plans.items():
        log(f"\n#### {t}: {p.counts()}")
        for ln in p.lines:
            log(ln)
    if not a.apply:
        log("\n(dry run; --apply to write)")
        return 0
    cnt = {"v1": 0}
    for t, p in plans.items():
        log(f"\n>> applying {t}")
        apply_plan(api, v2, p, log, cnt)
        if a.repeat and t in spec.REPEAT:
            set_repeat(api, t, log)
    ok = all([verify(api, v2, t, log) for t in tiers])     # a list: every tier is verified
    try:
        import cache as cache_store
        cache_store.invalidate("all_tasks")
        log("   cache all_tasks invalidated")
    except Exception as e:
        log(f"   cache invalidate skipped: {type(e).__name__}")
    log("== done, clean" if ok else "== done, NOT clean (see verify)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
