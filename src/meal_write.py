#!/usr/bin/env python3
"""meal_write.py - every TickTick write the 🥘 Meal Prep hub makes
(HANDOFF_MEAL.md). meal.py plans, meal_scale.py scales, mela.py reads the
recipe app; this module writes, and it is the ONLY module that does.

Why src/ and not Scripts/xact.py: the hourly agent (src/sync.py) imports
recipes and fills descriptions too, and it cannot import Scripts/. The xact
verbs (meal_commit, meal_import, meal_fill, meal_groceries) are thin
wrappers over the functions here; sync.py calls hourly().

THE WEEK. commit() takes the three picks (library task ids) and makes the
week real: the routine's old meal POINTERS are deleted, three new ones are
minted under it dated the cook Sunday, one 🛒 CHECKLIST per meal is made in
the library list with the ingredients scaled to seven portions, the weekly
note's 🥘 bullet is filled, and the ledger remembers the week. Pointers are
deleted rather than reopened or moved: HANDOFF_ROUTINES §8 says API
completion leaves a repeating task's children completed while the app
reopens them - delete-then-create is the one shape that is right on both
roads, and the library entries never move, so nothing is lost.

LIVE READS. Every commit reads the routine, its list and the library list
live: the routine tree is mutated by routine resets (which invalidate
all_tasks) and by the app, and a cached child list would hand us an id
that is already gone. A grocery list is re-dated from its live object, never
from the cache (full-object writes clobber whatever changed since the read).

THE LOCK (~/.ticktick_alfred/meal.lock), the okr_write shape: user verbs
wait LOCK_WAIT then refuse "busy"; hourly() takes it non-blocking and
leaves when it is held.

BUDGET. TickTick allows 300 requests per 5 minutes and the hourly sync
already spends ~100 unpaced. A commit is ~20 calls. The hourly hitchhiker
caps itself at BUDGET_HOURLY requests at 1 s pacing; the foreground backfill
paces 1.5 s. api.RateLimitError ends any run at once - retrying inside the
window deepens the lockout.

CACHE. Writes are mirrored into all_tasks / all_notes / project_data_<pid>
(dispatch's own helpers) so the hub shows the new week before the next
sync. Never invalidate all_tasks (map trap 10).

NO SYNC CLICK HERE: every road a verb runs on ends at ET End, which clicks
File > Sync already (the 2026-09-12 wedge).
"""
import fcntl
import json
import os
import time
from collections import namedtuple
from contextlib import contextmanager
from datetime import date, datetime, timezone

import cache as cache_store
import config as cfg
import mdtext
import meal

LOCK_FILE = os.path.join(cfg.CONFIG_DIR, "meal.lock")
LEDGER = os.path.join(cfg.CONFIG_DIR, "meal_ledger.json")
IMPORT_LEDGER = os.path.join(cfg.CONFIG_DIR, "meal_import.json")
LOCK_WAIT = 60.0
POST_GAP = 0.35            # seconds between our own POSTs (periodic_engine's rule)
BUDGET_HOURLY = 30         # requests the hourly hitchhiker may spend
CAP_IMPORT_HOURLY = 10     # of which, at most this many imports
PACE_BG = 1.0              # seconds between requests inside the hourly agent
PACE_FG = 1.5              # in a foreground verb
CAP_FG = 150               # entries per foreground backfill
STALE_WAKE_S = 6 * 3600    # meal_wake_mela: Mela's DB older than this → open -gj


class Refusal(Exception):
    """A write that was NOT made, worded for the toast (okr_write's)."""

    def __init__(self, msg="", reopen=None):
        super().__init__(msg)
        self.reopen = reopen


Outcome = namedtuple("Outcome", "msg reopen ids")


# ── plumbing ─────────────────────────────────────────────────────────────────
@contextmanager
def _lock(wait=None):
    wait = LOCK_WAIT if wait is None else wait
    try:
        os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
        fd = open(LOCK_FILE, "a")
    except OSError:
        yield True
        return
    got = False
    try:
        deadline = time.monotonic() + max(0.0, wait)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.2)
        yield got
    finally:
        try:
            if got:
                fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
        except Exception:
            pass


def _api(api=None):
    if api is None:
        from api import TickTickAPI
        api = TickTickAPI(cfg.get_token())
    return api


def _rate_limited(exc):
    return type(exc).__name__ == "RateLimitError"


def _pd_key(pid):
    return ("project_data_inbox" if str(pid).startswith("inbox")
            else f"project_data_{pid}")


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


_LAST_POST = [0.0]


def _pace():
    gap = time.time() - _LAST_POST[0]
    if gap < POST_GAP:
        time.sleep(POST_GAP - gap)
    _LAST_POST[0] = time.time()


def _dry(spec):
    return bool((spec or {}).get("dry")) or os.environ.get("TICKAL_MEAL_DRY") == "1"


# ── the caches, mirrored ─────────────────────────────────────────────────────
def _uncache(ids, pids=()):
    """Drop deleted ids from every pool a screen reads. Never raises."""
    ids = {i for i in ids if i}
    if not ids:
        return
    try:
        for key in ("all_tasks", "all_notes"):
            cached = cache_store.get(key)
            if cached is not None:
                cache_store.set(key, [t for t in cached if t.get("id") not in ids])
        for pid in {p for p in pids if p}:
            key = _pd_key(pid)
            pd = cache_store.get(key)
            if isinstance(pd, dict) and isinstance(pd.get("tasks"), list):
                pd = dict(pd)
                pd["tasks"] = [t for t in pd["tasks"] if t.get("id") not in ids]
                cache_store.set(key, pd)
    except Exception:
        pass


def _cache_add(tasks):
    try:
        from dispatch import _cache_new_tasks
        _cache_new_tasks([t for t in tasks if t])
    except Exception:
        pass


def _cache_patch(tid, **fields):
    try:
        from dispatch import _patch_task_cache
        _patch_task_cache(tid, **fields)
    except Exception:
        pass


def _pool_tasks(list_id):
    """Every cached copy of the library list's rows (project_data first,
    then the two pools - an entry can sit in both while it is NOTE kind)."""
    seen, out = set(), []
    pd = cache_store.get(_pd_key(list_id))
    rows = list((pd or {}).get("tasks") or []) if isinstance(pd, dict) else []
    for key in ("all_tasks", "all_notes"):
        rows += [t for t in (cache_store.get(key) or [])
                 if isinstance(t, dict)
                 and (t.get("projectId") or t.get("_projectId")) == list_id]
    for t in rows:
        if isinstance(t, dict) and t.get("id") and t["id"] not in seen:
            seen.add(t["id"])
            out.append(t)
    return out


# ── Mela ─────────────────────────────────────────────────────────────────────
def _mela():
    """(recipes, {UUID: recipe}, error or None) - never raises."""
    try:
        import mela
        recipes = mela.library()
        return recipes, {r.id.upper(): r for r in recipes if r.id}, None
    except Exception as e:
        return [], {}, str(e) or type(e).__name__


def _render(recipe):
    import mela
    return mela.render_markdown(recipe)


def _tag_for(recipe, tag_map=None):
    import mela
    return mela.meal_tag_for(recipe, tag_map or cfg.get_meal_tag_map())


# ── groceries ────────────────────────────────────────────────────────────────
def grocery_body(recipe):
    """(checklist lines, description) for one recipe at PORTIONS."""
    import meal_scale
    lines, info = meal_scale.scaled_ingredients(recipe, meal.PORTIONS)
    desc = info.get("note") or ""
    if info.get("detail"):
        desc += f"\n_(yield: {info['detail']})_"
    if info.get("unscaled"):
        desc += f"\n_({len(info['unscaled'])} line(s) had no quantity, left as written)_"
    return lines, desc.strip()


def _write_groceries(api, list_id, picks, sunday, today, by_id, existing):
    """One 🛒 CHECKLIST per pick in the library list. `existing` = {UUID:
    live open grocery task}. Kept when its meal is still planned (re-dated
    when the Saturday moved), deleted when its meal is not, created when
    missing. -> (made, kept, deleted_ids)."""
    day = meal.api_day(meal.grocery_day(sunday, today))
    want = {p["uuid"]: p for p in picks.values() if p.get("uuid")}
    made, kept, gone = [], [], []
    for uuid, t in list(existing.items()):
        if uuid in want:
            continue
        try:
            _pace()
            api.delete_task(t.get("projectId") or list_id, t["id"])
        except Exception as e:
            if _rate_limited(e):
                raise
        gone.append(t["id"])
    for key, _tag, _glyph, _label in meal.SLOTS:
        p = picks.get(key)
        if not p or not p.get("uuid"):
            continue
        cur = existing.get(p["uuid"])
        if cur is not None:
            if (cur.get("dueDate") or "")[:10] != day:
                try:
                    _pace()
                    api.update_task(cur["id"], cur.get("projectId") or list_id,
                                    current=cur, dueDate=day, startDate=None,
                                    isAllDay=True)
                    _cache_patch(cur["id"], dueDate=day, startDate=None, isAllDay=True)
                except Exception as e:
                    if _rate_limited(e):
                        raise
            kept.append(cur["id"])
            continue
        recipe = by_id.get(p["uuid"].upper())
        if recipe is not None:
            lines, desc = grocery_body(recipe)
        else:
            lines, desc = [], "⚠️ recipe not in Mela on this Mac · no list (open Mela to sync)"
        _pace()
        t = api.create_task(meal.grocery_title(p.get("name", ""), p["uuid"]),
                            project_id=list_id, tags=[meal.GROCERY_TAG],
                            kind="CHECKLIST", due_date=day, content=desc)
        if lines:
            items = [{"title": ln, "status": 0, "sortOrder": i} for i, ln in enumerate(lines)]
            try:
                _pace()
                t = api.update_task(t["id"], list_id, current=t, items=items) or t
            except Exception as e:
                if _rate_limited(e):
                    raise
                t["_items_error"] = f"{type(e).__name__}: {e}"
        t["projectId"] = t.get("projectId") or list_id
        made.append(t)
    return made, kept, gone


# ── the week ─────────────────────────────────────────────────────────────────
def _resolve_picks(spec, lib_tasks):
    """{key: {tid, name, uuid, task}} for the three ids in spec; Refusal on
    a miss or a slot/tag mismatch. lib_tasks = the library list's tasks."""
    entries = {e["tid"]: e for e in meal.library_entries(lib_tasks, None)}
    picks = {}
    for key, tag, _g, label in meal.SLOTS:
        tid = (spec.get(key) or "").strip()
        if not tid:
            raise Refusal(f"🥘 No {label.lower()} picked · nothing written")
        e = entries.get(tid)
        if e is None:
            raise Refusal("🥘 Not in the library · sync and pick again")
        if e.get("slot") != key:
            raise Refusal(f"🥘 {e['name'][:30]} is not tagged {tag} · pick again")
        picks[key] = {"tid": tid, "name": e["name"], "uuid": e["uuid"]}
    return picks


def preview(spec, today=None, api=None):
    """The dry run's text: what commit would do, from LIVE reads, no write."""
    return commit(dict(spec or {}, dry=True), today=today, api=api)


def commit(spec, today=None, api=None):
    """Make the week real (module docstring). spec: {"b","l","s": library
    task ids, "sunday": iso|None, "back": ctx, "dry": bool}. Returns an
    Outcome (or, dry, the plan as text); raises Refusal when nothing was
    written."""
    today = today or date.today()
    spec = dict(spec or {})
    list_id = cfg.get_meal_list_id()
    rid = cfg.get_meal_routine_id()
    if not list_id or not rid:
        raise Refusal("🥘 Meal prep is off · ⚙️ Settings → Meal Prep List")
    with _lock() as held:
        if not held:
            raise Refusal("🥘 Busy · another meal-prep write is running")
        api = _api(api)
        try:
            rpid = _routine_pid(rid)
            routine = api.get_task(rpid, rid)
            rpid = routine.get("projectId") or rpid
            lib = api.get_project_data(list_id)
            rlist = api.get_project_data(rpid) if rpid != list_id else lib
        except Exception as e:
            if _rate_limited(e):
                raise Refusal("🥘 Not written · TickTick rate limit · try again in a minute")
            raise Refusal(f"🥘 Not written · {type(e).__name__}: {e}")
        lib_tasks = list((lib or {}).get("tasks") or [])
        r_tasks = list((rlist or {}).get("tasks") or [])
        picks = _resolve_picks(spec, lib_tasks)
        sunday = None
        if spec.get("sunday"):
            try:
                sunday = date.fromisoformat(spec["sunday"])
            except (ValueError, TypeError):
                sunday = None
        sunday = sunday or meal.cook_sunday(routine, today)
        old = meal.pointers_of(r_tasks, rid)
        old_ids = [t["id"] for t in old.values()]
        existing = meal.groceries_of(lib_tasks, list_id)
        recipes, by_id, mela_err = _mela()
        if _dry(spec):
            lines = [f"🥘 DRY RUN · {meal.week_label(sunday)} (cook {sunday:%a %d %b})",
                     f"routine {rid} in {rpid}: delete {len(old_ids)} pointer(s) {old_ids}"]
            for key, _t, glyph, label in meal.SLOTS:
                p = picks[key]
                lines.append(f"  create {glyph} {p['name']} ({p['uuid']}) due {meal.api_day(sunday)}")
            keep = [u for u in existing if u in {p['uuid'] for p in picks.values()}]
            drop = [existing[u]['id'] for u in existing if u not in keep]
            lines.append(f"groceries in {list_id}: keep {len(keep)}, delete {drop}, "
                         f"create {3 - len(keep)} due {meal.api_day(meal.grocery_day(sunday, today))}")
            if mela_err:
                lines.append(f"Mela: {mela_err}")
            else:
                for p in picks.values():
                    r = by_id.get(p['uuid'])
                    n = len(grocery_body(r)[0]) if r else 0
                    lines.append(f"  {p['name'][:30]}: {n} grocery lines" if r else f"  {p['name'][:30]}: NOT in Mela")
            lines.append(f"weekly note: {meal.note_day(sunday)} (block filled)")
            return "\n".join(lines)
        # ── write ──
        made = []
        try:
            for tid in old_ids:
                try:
                    _pace()
                    api.delete_task(rpid, tid)
                except Exception as e:
                    if _rate_limited(e):
                        raise
            for key, _t, _g, _l in meal.SLOTS:
                p = picks[key]
                _pace()
                t = api.create_task(meal.pointer_title(key, p["name"], p["uuid"]),
                                    project_id=rpid, parent_id=rid,
                                    due_date=meal.api_day(sunday), kind="TEXT")
                t["parentId"] = rid                # the response lies (map trap 12)
                t["projectId"] = t.get("projectId") or rpid
                made.append(t)
            try:
                from dispatch import _order_children
                _order_children(api, made, rpid, rid)
            except Exception:
                pass
            g_made, g_kept, g_gone = _write_groceries(api, list_id, picks, sunday,
                                                      today, by_id, existing)
        except Exception as e:
            if _rate_limited(e):
                _uncache(old_ids, [rpid])
                _cache_add(made)
                raise Refusal("🥘 Partly written · TickTick rate limit · re-run the plan in a minute")
            raise
        note_ok = _write_note(picks, sunday)
        try:
            led = meal.load_ledger(LEDGER)
            meal.ledger_add(led, sunday, picks, pointers=[t["id"] for t in made],
                            groceries=[t["id"] for t in g_made] + g_kept)
            meal.save_ledger(LEDGER, led)
        except Exception:
            pass
        _uncache(old_ids + g_gone, [rpid, list_id])
        _cache_add(made + g_made)
        ids = [t["id"] for t in made] + [t["id"] for t in g_made]
        return Outcome(meal.outcome_text(sunday, len(made), len(g_made) + len(g_kept), note_ok),
                       spec.get("back") or "ctx:meal", ids)


def _routine_pid(rid):
    """The routine's list: the cache's copy, else the registry's hint."""
    try:
        t = cache_store.find_task(rid) or {}
        pid = t.get("projectId") or t.get("_projectId")
        if pid:
            return pid
    except Exception:
        pass
    try:
        import routines as rt
        r = rt.by_tid(rid)
        if r:
            return r["pid"]
    except Exception:
        pass
    return meal.ROUTINES_LIST if hasattr(meal, "ROUTINES_LIST") else "6a268ea18f081f1de80eaeb5"


def _write_note(picks, sunday):
    """The weekly note's 🥘 bullet for the week being cooked for. Never
    raises; False when the note could not be written (kill switch, no
    periodic list, network)."""
    try:
        import areas
        import periodic_engine as pe
        import periodic_model as pm
        import meal_notes
        if not areas.periodic_configured():
            return False
        p = pm.period_for("weekly", meal.note_day(sunday))
        task, _ = pe.ensure_note(p)
        pid = task.get("projectId") or areas.PERIODIC_LIST_ID
        lines = meal_notes.block_lines(picks)

        def mutate(doc, live):
            return meal_notes.write_block(doc, lines, live=live)
        ok, _doc = pe._pn_rmw(pid, task["id"], mutate)
        return bool(ok) or meal_notes.read_block(_doc) == lines
    except Exception:
        return False


# ── import + backfill (the verb AND the hourly sync) ─────────────────────────
def _existing_uuids(list_id, tasks=None):
    out = set()
    for t in (tasks if tasks is not None else _pool_tasks(list_id)):
        u = meal.link_uuid((t or {}).get("title") or "")
        if u:
            out.add(u)
    return out


def import_new(api, recipes=None, existing=None, list_id=None, tag_map=None,
               cap=CAP_IMPORT_HOURLY, pace=PACE_BG, ledger_path=None,
               now=None, column_id=None):
    """Create a library task for every Mela recipe that carries a meal
    category and is in neither the list nor the import ledger. Newest
    first, `cap` per run, ledger saved after EACH ack (a crash between the
    create and the ledger is the only way to mint a duplicate, and the
    title check catches that on the next sync). Returns a summary dict."""
    list_id = list_id or cfg.get_meal_list_id()
    ledger_path = ledger_path or IMPORT_LEDGER      # resolved at CALL time (tests re-point it)
    out = {"created": 0, "skipped": 0, "no_category": 0, "failed": 0,
           "remaining": 0, "rate_limited": False, "ids": [], "chip": ""}
    if not list_id:
        return out
    if recipes is None:
        recipes, _by, err = _mela()
        if err:
            out["error"] = err
            return out
    existing = set(existing) if existing is not None else _existing_uuids(list_id)
    led = meal.load_ledger(ledger_path)
    done = {w.get("uuid", "").upper() for w in led.get("weeks", []) if w.get("uuid")}
    cands = []
    for r in recipes:
        tag = _tag_for(r, tag_map)
        if not tag:
            out["no_category"] += 1
            continue
        u = (r.id or "").upper()
        if not u or u in existing or u in done:
            out["skipped"] += 1
            continue
        cands.append((r, tag))
    cands.sort(key=lambda rt: (rt[0].date or datetime.min.replace(tzinfo=timezone.utc)),
               reverse=True)
    made = []
    for r, tag in cands[:max(0, int(cap))]:
        title = mdtext.md_link(r.title, r.url)
        try:
            t = api.create_task(title, project_id=list_id, tags=[tag.lower()],
                                content=_render(r), column_id=column_id)
        except Exception as e:
            if _rate_limited(e):
                out["rate_limited"] = True
                break
            out["failed"] += 1
            continue
        t["projectId"] = t.get("projectId") or list_id
        made.append(t)
        out["ids"].append(t.get("id"))
        led.setdefault("weeks", []).append({"uuid": r.id.upper(), "tid": t.get("id"),
                                            "pid": list_id, "when": _stamp()})
        try:
            meal.save_ledger(ledger_path, led)
        except Exception:
            pass
        if pace:
            time.sleep(pace)
    out["created"] = len(made)
    out["remaining"] = max(0, len(cands) - len(made))
    _cache_add(made)
    if made:
        out["chip"] = f"🥘 +{len(made)} recipe" + ("s" if len(made) > 1 else "")
    return out


def missing_descriptions(list_id=None, tasks=None):
    """[{tid, pid, uuid, title}] - library entries whose cached content is
    empty (the hub's count and the backfill's worklist)."""
    list_id = list_id or cfg.get_meal_list_id()
    out = []
    for t in (tasks if tasks is not None else _pool_tasks(list_id)):
        if not isinstance(t, dict) or t.get("status", 0) != 0:
            continue
        title = t.get("title") or ""
        if not meal.is_library_title(title):
            continue
        if (t.get("content") or "").strip():
            continue
        u = meal.link_uuid(title)
        if u:
            out.append({"tid": t.get("id"), "pid": t.get("projectId") or list_id,
                        "uuid": u, "title": title})
    out.sort(key=lambda e: e["title"].lower())
    return out


def backfill_descriptions(api, entries=None, by_id=None, cap=10, pace=PACE_BG,
                          progress=None):
    """Fill empty descriptions from Mela: a LIVE get_task per entry (project
    data omits NOTE bodies; a stale full-object POST would wipe a hand
    edit), skip when content appeared meanwhile. Returns a summary dict."""
    out = {"filled": 0, "skipped": 0, "not_in_mela": 0, "failed": 0,
           "remaining": 0, "rate_limited": False}
    entries = list(entries if entries is not None else missing_descriptions())
    if by_id is None:
        _r, by_id, err = _mela()
        if err:
            out["error"] = err
            return out
    todo = entries[:max(0, int(cap))]
    out["remaining"] = max(0, len(entries) - len(todo))
    for i, e in enumerate(todo, 1):
        r = by_id.get((e.get("uuid") or "").upper())
        touched = False
        if r is None:
            out["not_in_mela"] += 1
        else:
            try:
                touched = True
                live = api.get_task(e["pid"], e["tid"])
                if (live.get("content") or "").strip():
                    out["skipped"] += 1
                else:
                    body = _render(r)
                    api.update_task(e["tid"], live.get("projectId") or e["pid"],
                                    current=live, content=body)
                    _cache_patch(e["tid"], content=body)
                    out["filled"] += 1
            except Exception as ex:
                if _rate_limited(ex):
                    out["rate_limited"] = True
                    out["remaining"] += len(todo) - i + 1
                    break
                out["failed"] += 1
        if progress:
            try:
                progress(i, len(todo))
            except Exception:
                pass
        if pace and touched:
            time.sleep(pace)
    return out


def _wake_mela():
    """meal_wake_mela: launch Mela hidden in the background when its
    database is stale, so iCloud brings the phone's recipes over for the
    NEXT run. Never raises."""
    try:
        if not cfg.get_meal_wake_mela():
            return False
        import mela
        import subprocess
        fr = mela.freshness()
        if not fr.get("present") or (fr.get("age_s") or 0) < STALE_WAKE_S:
            return False
        ps = subprocess.run(["/bin/ps", "-xco", "comm"], capture_output=True, text=True)
        if "Mela" in (ps.stdout or "").split():
            return False
        subprocess.run(["open", "-gj", "-a", "Mela"], check=False)
        return True
    except Exception:
        return False


def hourly(api=None):
    """The sync's hitchhiker: imports first, then descriptions, within one
    request budget, paced. Returns the summary chip ('' = nothing done).
    Never raises."""
    try:
        list_id = cfg.get_meal_list_id()
        if not list_id:
            return ""
        import mela
        if not mela.db_present():
            return ""
        with _lock(wait=0) as held:
            if not held:
                return ""
            api = _api(api)
            recipes, by_id, err = _mela()
            if err:
                return ""
            budget = BUDGET_HOURLY
            imp = import_new(api, recipes=recipes, list_id=list_id,
                             cap=min(CAP_IMPORT_HOURLY, budget), pace=PACE_BG)
            budget -= imp["created"] + imp["failed"]
            chips = [imp["chip"]] if imp.get("chip") else []
            if not imp.get("rate_limited") and budget >= 2:
                bf = backfill_descriptions(api, by_id=by_id, cap=budget // 2, pace=PACE_BG)
                if bf["filled"]:
                    chips.append(f"{bf['filled']} filled")
            _wake_mela()
            return "🥘 " + " · ".join(c.replace("🥘 ", "") for c in chips) if chips else ""
    except Exception:
        return ""


# ── the hub's numbers (cache only, no network) ───────────────────────────────
def hub_counts():
    """{new, missing, uncategorised, mela_ok, mela_age_s, mela_error,
    entries} for the hub's status and action rows, from the caches and the
    Mela snapshot only."""
    list_id = cfg.get_meal_list_id()
    out = {"new": 0, "missing": 0, "uncategorised": 0, "mela_ok": False,
           "mela_age_s": None, "mela_error": None, "list_id": list_id}
    tasks = _pool_tasks(list_id) if list_id else []
    out["missing"] = len(missing_descriptions(list_id, tasks))
    recipes, by_id, err = _mela()
    if err:
        out["mela_error"] = err
        return out
    out["mela_ok"] = True
    try:
        import mela
        out["mela_age_s"] = mela.freshness().get("age_s")
    except Exception:
        pass
    existing = _existing_uuids(list_id, tasks)
    led = meal.load_ledger(IMPORT_LEDGER)
    done = {w.get("uuid", "").upper() for w in led.get("weeks", []) if w.get("uuid")}
    for r in recipes:
        if not _tag_for(r):
            out["uncategorised"] += 1
        elif (r.id or "").upper() not in existing and (r.id or "").upper() not in done:
            out["new"] += 1
    return out


# ── groceries, rebuilt on demand ─────────────────────────────────────────────
def rebuild_groceries(spec=None, today=None, api=None):
    """Remake this week's three 🛒 lists from the routine's live pointers
    (the ⌥⇧ road on the hub's Groceries row): open lists for the planned
    meals are deleted and created again, so a recipe fixed in Mela lands
    in the shopping list. Ticked (completed) lists are never touched."""
    today = today or date.today()
    spec = dict(spec or {})
    list_id = cfg.get_meal_list_id()
    rid = cfg.get_meal_routine_id()
    if not list_id or not rid:
        raise Refusal("🥘 Meal prep is off · ⚙️ Settings → Meal Prep List")
    with _lock() as held:
        if not held:
            raise Refusal("🥘 Busy · another meal-prep write is running")
        api = _api(api)
        try:
            rpid = _routine_pid(rid)
            routine = api.get_task(rpid, rid)
            rpid = routine.get("projectId") or rpid
            r_tasks = list((api.get_project_data(rpid) or {}).get("tasks") or [])
            lib_tasks = list((api.get_project_data(list_id) or {}).get("tasks") or [])
        except Exception as e:
            if _rate_limited(e):
                raise Refusal("🥘 Not written · TickTick rate limit · try again in a minute")
            raise Refusal(f"🥘 Not written · {type(e).__name__}: {e}")
        pointers = meal.pointers_of(r_tasks, rid)
        if not pointers:
            raise Refusal("🥘 No meals planned yet · 🎲 Plan next week first")
        picks = {}
        for key, t in pointers.items():
            parsed = meal.parse_title(t.get("title") or "")
            if parsed:
                picks[key] = {"tid": t["id"], "name": parsed[0], "uuid": parsed[1]}
        sunday = meal.cook_sunday(routine, today)
        existing = meal.groceries_of(lib_tasks, list_id)
        recipes, by_id, mela_err = _mela()
        if mela_err:
            raise Refusal(f"🥘 Not rebuilt · {mela_err}")
        planned = {p["uuid"] for p in picks.values()}
        gone = []
        for uuid, t in list(existing.items()):
            if uuid in planned:
                try:
                    _pace()
                    api.delete_task(t.get("projectId") or list_id, t["id"])
                    gone.append(t["id"])
                    existing.pop(uuid, None)
                except Exception as e:
                    if _rate_limited(e):
                        raise Refusal("🥘 Partly rebuilt · TickTick rate limit · try again in a minute")
        try:
            made, kept, gone2 = _write_groceries(api, list_id, picks, sunday, today,
                                                 by_id, existing)
        except Exception as e:
            if _rate_limited(e):
                raise Refusal("🥘 Partly rebuilt · TickTick rate limit · try again in a minute")
            raise
        _uncache(gone + gone2, [list_id])
        _cache_add(made)
        return Outcome(f"🥘 {len(made)} grocery list" + ("s" if len(made) != 1 else "")
                       + f" rebuilt · {meal.week_label(sunday)}",
                       spec.get("back") or "ctx:meal", [t["id"] for t in made])
