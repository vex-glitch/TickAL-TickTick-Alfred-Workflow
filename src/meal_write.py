#!/usr/bin/env python3
"""meal_write.py - every TickTick write the 🥘 Meal Prep hub makes
(HANDOFF_MEAL.md). meal.py folds the plan into weeks, meal_scale.py scales,
mela.py reads the recipe app, mela_cal.py reads the plan out of Apple
Calendar; this module writes, and it is the ONLY module that does.

ONE VERB. Vex 2026-09-21: "this python script that runs in the background
is unacceptable. We should only have a row that says sync TickTick with
Mela, that would do that manually." So sync() is the whole write side and
runs only when the 🔄 row is pressed: new Mela recipes into the library
(cap CAP_IMPORT), empty descriptions filled (cap CAP_FILL), then the COOK
WEEK mirrored: the routine's live cook Sunday picks the week, the calendar
says what is planned on it, the routine's old meal POINTERS are deleted and
one is minted per planned meal, a 🛒 CHECKLIST per meal is made in the
library list (seven portions), the weekly note's 🥘 bullet is written. No
hourly hitchhiker, nothing wakes Mela, nothing schedules: "I will be
scheduling in Mela, it is nicer".

Pointers are deleted rather than reopened or moved: HANDOFF_ROUTINES §8
says API completion leaves a repeating task's children completed while the
app reopens them - delete-then-create is the one shape that is right on
both roads, and the library entries never move, so nothing is lost.

THE READ SIDE, plan_view(), is what the screens render from: the calendar
plan folded into HORIZON_WEEKS weeks with the library entries joined in.
It never raises; a calendar it cannot read becomes `error`, the toast line
the hub's status row shows.

LIVE READS. sync reads the routine, its list and the library list live:
the routine tree is mutated by routine resets (which invalidate all_tasks)
and by the app, and a cached child list would hand us an id that is
already gone. A grocery list is re-dated from its live object, never from
the cache (full-object writes clobber whatever changed since the read).

THE LOCK (~/.ticktick_alfred/meal.lock), the okr_write shape: sync waits
LOCK_WAIT then refuses "busy".

BUDGET. TickTick enforces 100 requests a MINUTE (hit 2026-09-19). A sync is
~20 calls plus the imports and backfills, all at PACE. api.RateLimitError
ends any run at once - retrying inside the window deepens the lockout - and
the toast says how far it got.

CACHE. Writes are mirrored into all_tasks / all_notes / project_data_<pid>
(dispatch's own helpers) so the hub shows the new week before the next
sync. Never invalidate all_tasks (map trap 10).

THE IMPORT LEDGER (~/.ticktick_alfred/meal_import.json) stays: it is the
dedupe memory of what was imported, not a plan. The cooked-history ledger
of the picker era is gone; "cooked N weeks ago" reads off the calendar.

NO SYNC CLICK HERE: every road a verb runs on ends at ET End, which clicks
File > Sync already (the 2026-09-12 wedge).
"""
import fcntl
import json
import os
import time
from collections import namedtuple
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import cache as cache_store
import config as cfg
import mdtext
import meal

LOCK_FILE = os.path.join(cfg.CONFIG_DIR, "meal.lock")
IMPORT_LEDGER = os.path.join(cfg.CONFIG_DIR, "meal_import.json")
LOCK_WAIT = 60.0
POST_GAP = 0.35            # seconds between our own POSTs (periodic_engine's rule)
CAP_IMPORT = 40            # recipes imported per sync
CAP_FILL = 60              # descriptions filled per sync
PACE = 1.0                 # seconds between requests (100 a minute is the wall)
HORIZON_WEEKS = 13         # "all the next meals for a quarter, by week"


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


def _dry_env():
    return os.environ.get("TICKAL_MEAL_DRY") == "1"


# ── the import ledger (dedupe memory) ────────────────────────────────────────
def _load_import_ledger(path):
    """{"weeks": [{uuid, tid, pid, when}]} - the key is historical; missing
    or corrupt reads as empty."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("weeks"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"weeks": []}


def _save_import_ledger(path, data):
    """Atomic, 0600, like config.save - never a half-written memory."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _imported_uuids(path):
    led = _load_import_ledger(path)
    return {w.get("uuid", "").upper() for w in led.get("weeks", []) if w.get("uuid")}


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


def _by_id(recipes):
    return {(r.id or "").upper(): r for r in recipes or [] if getattr(r, "id", None)}


def _render(recipe):
    import mela
    return mela.render_markdown(recipe)


def _tag_for(recipe, tag_map=None):
    import mela
    return mela.meal_tag_for(recipe, tag_map or cfg.get_meal_tag_map())


# ── the calendar (the plan) ──────────────────────────────────────────────────
def _calendar(since=None, until=None):
    """(planned rows, error line) - the Mela plan out of Apple Calendar.
    Never raises: a MelaCalError (Full Disk Access, a busy store) or a
    missing module becomes the one toast line."""
    try:
        import mela_cal
    except Exception as e:
        return [], f"Calendar reader missing · {type(e).__name__}: {e}"
    try:
        return list(mela_cal.plan(since=since, until=until)), ""
    except mela_cal.MelaCalError as e:
        return [], str(e)
    except Exception as e:
        return [], f"Calendar store unreadable ({type(e).__name__}: {e}) · try again"


# ── the read side: the screens' plan ─────────────────────────────────────────
def plan_view(today=None, n_weeks=HORIZON_WEEKS, planned=None, recipes=None,
              tasks=None, first_sunday=None):
    """The plan the 🥘 screens render: {weeks: [meal.Week] (every week
    present), first_sunday, planned_count, error, mela_error, planned,
    by_id, entries, today}. Never raises. `error` is the calendar's toast
    line ("" when it read fine) - the hub wears a "cache" chip on it;
    `mela_error` is Mela's own (its meals then read slot 🍽️ off the event
    title). first_sunday defaults to the coming Sunday (today itself on a
    Sunday), the routine's cook Sunday when it is on schedule; the browse
    side passes meal.cook_sunday(routine, today) when it has the live
    routine. planned / recipes / tasks are injectable (tests, and a caller
    that already holds them); read otherwise from the calendar snapshot, the
    Mela snapshot and the cached library pool."""
    today = today or date.today()
    n_weeks = max(1, int(n_weeks or HORIZON_WEEKS))
    first_sunday = (meal.cook_week_of(first_sunday) if first_sunday
                    else meal.next_sunday(today))
    since = first_sunday - timedelta(days=7)
    until = first_sunday + timedelta(days=7 * n_weeks)
    error = ""
    if planned is None:
        planned, error = _calendar(since=since, until=until)
    planned = list(planned or [])
    mela_error = ""
    if recipes is None:
        recipes, by_id, err = _mela()
        mela_error = err or ""
    else:
        by_id = _by_id(recipes)
    list_id = cfg.get_meal_list_id()
    if tasks is None:
        tasks = _pool_tasks(list_id) if list_id else []
    entries = meal.library_entries(tasks, list_id)
    tag_map = cfg.get_meal_tag_map()
    weeks = meal.weeks_plan(planned, by_id, tag_map, entries, first_sunday, n_weeks)
    return {"weeks": weeks, "first_sunday": first_sunday, "planned_count": len(planned),
            "error": error, "mela_error": mela_error, "planned": planned,
            "by_id": by_id, "entries": entries, "today": today}


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


def _picks_of(meals):
    """{UUID: {name, uuid, slot, tid}} in meal order - the pick shape the
    grocery writer and the note take (one list per recipe, however many
    meals the week has; slot "x" rides like any other)."""
    picks = {}
    for m in meals or []:
        u = (m.uuid or "").upper()
        if u and u not in picks:
            picks[u] = {"name": m.name, "uuid": u, "slot": m.slot, "tid": m.tid}
    return picks


def _write_groceries(api, list_id, picks, sunday, today, by_id, existing):
    """One 🛒 CHECKLIST per pick in the library list, in pick order.
    `existing` = {UUID: live open grocery task}. Kept when its meal is still
    planned (re-dated when the Saturday moved), deleted when its meal is
    not, created when missing. -> (made, kept, deleted_ids)."""
    gday = meal.grocery_day(sunday, today)
    day = meal.api_day(gday)
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
    for p in want.values():
        cur = existing.get(p["uuid"])
        if cur is not None:
            if _task_day(cur) != gday:            # local day, not the UTC string
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


# ── the routine and the note ─────────────────────────────────────────────────
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


NOTHING_PLANNED = "nothing planned in Mela"


def note_lines(meals):
    """The 🥘 bullet's body for a week: meal_notes.block_lines' three slot
    lines (a missing slot reads "_(not planned)_") plus one line per extra
    meal (a second breakfast, a 🍽️ recipe outside the three slots); an empty
    week reads "_(nothing planned in Mela)_" - the toast's words."""
    meals = list(meals or [])
    if not meals:
        return [f"- _({NOTHING_PLANNED})_"]
    import meal_notes
    picks, extra = {}, []
    for m in meals:
        if m.slot in meal.SLOT_KEYS and m.slot not in picks:
            picks[m.slot] = {"name": m.name, "uuid": m.uuid}
        else:
            extra.append(f"- {m.glyph} {meal.md_link(m.name, m.uuid)}")
    return meal_notes.block_lines(picks) + extra


def _write_note(meals, sunday):
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
        lines = note_lines(meals)

        def mutate(doc, live):
            return meal_notes.write_block(doc, lines, live=live)
        ok, _doc = pe._pn_rmw(pid, task["id"], mutate)
        return bool(ok) or meal_notes.read_block(_doc) == lines
    except Exception:
        return False


# ── import + backfill ────────────────────────────────────────────────────────
def _existing_uuids(list_id, tasks=None):
    out = set()
    for t in (tasks if tasks is not None else _pool_tasks(list_id)):
        u = meal.link_uuid((t or {}).get("title") or "")
        if u:
            out.add(u)
    return out


def _import_candidates(recipes, existing, done, tag_map=None):
    """[(recipe, tag)] newest first for the categorised recipes in neither
    the list nor the ledger, and the count of uncategorised ones."""
    cands, no_cat = [], 0
    for r in recipes or []:
        tag = _tag_for(r, tag_map)
        if not tag:
            no_cat += 1
            continue
        u = (r.id or "").upper()
        if not u or u in existing or u in done:
            continue
        cands.append((r, tag))
    cands.sort(key=lambda rt: (rt[0].date or datetime.min.replace(tzinfo=timezone.utc)),
               reverse=True)
    return cands, no_cat


def import_new(api, recipes=None, existing=None, list_id=None, tag_map=None,
               cap=CAP_IMPORT, pace=PACE, ledger_path=None, now=None, column_id=None):
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
    led = _load_import_ledger(ledger_path)
    done = {w.get("uuid", "").upper() for w in led.get("weeks", []) if w.get("uuid")}
    cands, out["no_category"] = _import_candidates(recipes, existing, done, tag_map)
    out["skipped"] = len(recipes) - out["no_category"] - len(cands)
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
            _save_import_ledger(ledger_path, led)
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


def backfill_descriptions(api, entries=None, by_id=None, cap=CAP_FILL, pace=PACE,
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


# ── THE sync ─────────────────────────────────────────────────────────────────
def _refuse_partial(what, imported, filled):
    bits = ["🥘 Partly synced"]
    if imported:
        bits.append(f"+{imported} recipe{'s' if imported != 1 else ''}")
    if filled:
        bits.append(f"{filled} filled")
    bits.append(f"{what} · TickTick rate limit · press 🔄 again in a minute")
    raise Refusal(" · ".join(bits), reopen="ctx:meal")


def sync(today=None, api=None, dry=False, planned=None, recipes=None):
    """🔄 Sync with Mela, the one meal verb (module docstring). Under the
    lock: Mela library → import_new (CAP_IMPORT) → backfill_descriptions
    (CAP_FILL) → the calendar plan → the LIVE routine → cook Sunday =
    meal.cook_sunday(routine, today) → meal.week_meals → that week mirrored:
    old pointers deleted, one pointer per meal created (🍽️ for slot "x"),
    groceries made / kept / dropped, the note bullet written, caches
    mirrored. A week with nothing planned clears the pointers and the OPEN
    stale groceries; bullet and toast say "nothing planned in Mela".

    dry=True or TICKAL_MEAL_DRY=1: live READS only, returns the plan as
    text, nothing written. planned / recipes are injectable (tests). Raises
    Refusal when the list or routine id is blank, Mela's DB is missing, the
    calendar store is unreadable, another sync holds the lock, or TickTick
    rate-limits mid-way (the toast says how far it got)."""
    today = today or date.today()
    dry = bool(dry) or _dry_env()
    list_id = cfg.get_meal_list_id()
    rid = cfg.get_meal_routine_id()
    if not list_id or not rid:
        raise Refusal("🥘 Meal prep is off · ⚙️ Settings → Meal Prep List")
    with _lock() as held:
        if not held:
            raise Refusal("🥘 Busy · another meal-prep sync is running")
        # the recipe library
        if recipes is None:
            try:
                import mela
                if not mela.db_present():
                    raise Refusal("🥘 Not synced · Mela's database is not on this Mac "
                                  "· open Mela once")
            except ImportError:
                raise Refusal("🥘 Not synced · the Mela reader is missing")
            recipes, by_id, err = _mela()
            if err:
                raise Refusal(f"🥘 Not synced · Mela: {err}")
        else:
            by_id = _by_id(recipes)
        # the plan - read before a single write, so a store we cannot read
        # costs nothing (the Full Disk Access caveat, HANDOFF_MEAL §6)
        if planned is None:
            planned, cal_err = _calendar()
            if cal_err:
                raise Refusal(f"🥘 Not synced · {cal_err}")
        planned = list(planned or [])
        tag_map = cfg.get_meal_tag_map()
        api = _api(api)
        # ── recipes in, descriptions filled ──
        imported = filled = 0
        if dry:
            cands, _nc = _import_candidates(recipes, _existing_uuids(list_id),
                                            _imported_uuids(IMPORT_LEDGER), tag_map)
            n_import = min(len(cands), CAP_IMPORT)
            n_fill = min(len(missing_descriptions(list_id)), CAP_FILL)
        else:
            imp = import_new(api, recipes=recipes, list_id=list_id, tag_map=tag_map,
                             cap=CAP_IMPORT, pace=PACE)
            imported = imp["created"]
            if imp.get("rate_limited"):
                _refuse_partial("week not mirrored", imported, 0)
            bf = backfill_descriptions(api, by_id=by_id, cap=CAP_FILL, pace=PACE)
            filled = bf["filled"]
            if bf.get("rate_limited"):
                _refuse_partial("week not mirrored", imported, filled)
        # ── live reads ──
        try:
            rpid = _routine_pid(rid)
            routine = api.get_task(rpid, rid)
            rpid = routine.get("projectId") or rpid
            lib = api.get_project_data(list_id)
            rlist = api.get_project_data(rpid) if rpid != list_id else lib
        except Exception as e:
            if _rate_limited(e):
                _refuse_partial("week not mirrored", imported, filled)
            raise Refusal(f"🥘 Not synced · {type(e).__name__}: {e}")
        lib_tasks = list((lib or {}).get("tasks") or [])
        r_tasks = list((rlist or {}).get("tasks") or [])
        sunday = meal.cook_sunday(routine, today)
        entries = meal.library_entries(lib_tasks, list_id)
        week = meal.week_meals(planned, by_id, tag_map, entries, sunday)
        picks = _picks_of(week.meals)
        old = meal.pointers_of(r_tasks, rid)
        old_ids = [t["id"] for t in old.values()]
        existing = meal.groceries_of(lib_tasks, list_id)
        if dry:
            lines = [f"🥘 DRY RUN · {meal.week_label(sunday)} (cook {sunday:%a %d %b})",
                     f"Mela: {len(recipes)} recipes · import +{n_import} (cap {CAP_IMPORT})"
                     f" · fill {n_fill} (cap {CAP_FILL})",
                     f"calendar: {len(planned)} planned row(s) · on {sunday:%a %d %b}: "
                     f"{len(week.meals)} meal(s)",
                     f"routine {rid} in {rpid}: delete {len(old_ids)} pointer(s) {old_ids}"]
            for m in week.meals:
                src = "in the library" if m.tid else "NOT in the library"
                lines.append(f"  create {m.glyph} {m.name} ({m.uuid}) due {sunday} · {src}")
            if not week.meals:
                lines.append(f"  ({NOTHING_PLANNED})")
            keep = [u for u in existing if u in picks]
            drop = [existing[u]["id"] for u in existing if u not in picks]
            lines.append(f"groceries in {list_id}: keep {len(keep)}, delete {drop}, "
                         f"create {len(picks) - len(keep)} due "
                         f"{meal.grocery_day(sunday, today)}")
            for p in picks.values():
                r = by_id.get(p["uuid"])
                lines.append(f"  {p['name'][:30]}: {len(grocery_body(r)[0])} grocery lines"
                             if r else f"  {p['name'][:30]}: NOT in Mela")
            lines.append(f"weekly note: {meal.note_day(sunday)} (block: "
                         f"{len(note_lines(week.meals))} line(s))")
            d_set, d_clear = date_plan(lib_tasks, planned, today)
            lines.append(f"library dates: set {len(d_set)}, clear {len(d_clear)}")
            for t, d in d_set[:8]:
                lines.append(f"  {_name_of(t)[:30]} → {d}")
            for t in d_clear[:8]:
                lines.append(f"  {_name_of(t)[:30]} → undated")
            return "\n".join(lines)
        # ── write the week ──
        made = []
        try:
            for tid in old_ids:
                try:
                    _pace()
                    api.delete_task(rpid, tid)
                except Exception as e:
                    if _rate_limited(e):
                        raise
            for m in week.meals:
                _pace()
                t = api.create_task(meal.pointer_title(m.slot, m.name, m.uuid),
                                    project_id=rpid, parent_id=rid,
                                    due_date=meal.api_day(sunday), kind="TEXT")
                t["parentId"] = rid                # the response lies (map trap 12)
                t["projectId"] = t.get("projectId") or rpid
                made.append(t)
            if made:
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
                _refuse_partial("week partly mirrored", imported, filled)
            raise
        note_ok = _write_note(week.meals, sunday)
        _uncache(old_ids + g_gone, [rpid, list_id])
        _cache_add(made + g_made)
        # last, so a rate limit here leaves the week already mirrored
        dated, dates_left = _date_library(api, lib_tasks, planned, today)
        ids = [t["id"] for t in made] + [t["id"] for t in g_made]
        return Outcome(meal.sync_text(sunday, week.meals, len(g_made) + len(g_kept),
                                      imported, filled, note_ok,
                                      dated=dated, dates_left=dates_left),
                       "ctx:meal", ids)



# ── the library's dates (Vex 2026-09-21: "as long as the correct recipe in
# TickTick reflects the date it is scheduled for in Mela, I am happy") ──────
def _name_of(t):
    parsed = meal.parse_title(t.get("title", ""))
    return parsed[0] if parsed else (t.get("title") or "")


def _task_day(t):
    """The local day a task's date sits on, or None."""
    raw = t.get("startDate") or t.get("dueDate")
    if not raw:
        return None
    try:
        return meal._local_date(raw)
    except Exception:
        return None


def date_plan(lib_tasks, planned, today):
    """Pure: what every library entry's date should become -> (set, clear).
    A recipe takes its NEAREST planned day on or after today (all-day, the
    day Mela has it on, not the cook Sunday); a recipe with no upcoming plan
    loses its date. Entries already right are left out. `set` =
    [(task, day)], `clear` = [task]. Only library entries (meal.library_entries):
    groceries, pointers and hand-made rows are never touched."""
    upcoming = {}
    for p in planned or []:
        d = getattr(p, "date", None)
        u = (getattr(p, "uuid", "") or "").upper()
        if d and u and d >= today and (u not in upcoming or d < upcoming[u]):
            upcoming[u] = d
    by_id = {t.get("id"): t for t in lib_tasks or []}
    to_set, to_clear = [], []
    for e in meal.library_entries(lib_tasks, ""):
        t = by_id.get(e.get("tid"))
        if not t:
            continue
        want = upcoming.get((e.get("uuid") or "").upper())
        have = _task_day(t)
        if want and have != want:
            to_set.append((t, want))
        elif not want and have:
            to_clear.append(t)
    return to_set, to_clear


def _date_library(api, lib_tasks, planned, today):
    """Write date_plan: (dated, left). One paced full-object update per
    entry; the 100-a-minute limit stops the pass and `left` says how many
    wait for the next press (the toast: "N dates left · run again")."""
    to_set, to_clear = date_plan(lib_tasks, planned, today)
    todo = [(t, d) for t, d in to_set] + [(t, None) for t in to_clear]
    dated = 0
    for t, d in todo:
        try:
            _pace()
            if d is None:
                resp = api.update_task(t["id"], t.get("projectId"), current=t,
                                       startDate=None, dueDate=None, isAllDay=False)
            else:
                day = meal.api_day(d)
                resp = api.update_task(t["id"], t.get("projectId"), current=t,
                                       startDate=day, dueDate=day, isAllDay=True)
        except Exception as e:
            if _rate_limited(e):
                return dated, len(todo) - dated
            raise
        dated += 1
        fields = (dict(startDate=None, dueDate=None, isAllDay=False) if d is None
                  else dict(startDate=(resp or {}).get("startDate") or meal.api_day(d),
                            dueDate=(resp or {}).get("dueDate") or meal.api_day(d),
                            isAllDay=True))
        _cache_patch(t["id"], **fields)
    return dated, 0


# ── the hub's numbers (cache only, no network) ───────────────────────────────
def hub_counts():
    """{new, missing, uncategorised, mela_ok, mela_age_s, mela_error,
    list_id} for the hub's status and 🔄 rows, from the caches and the Mela
    snapshot only."""
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
    cands, out["uncategorised"] = _import_candidates(
        recipes, _existing_uuids(list_id, tasks), _imported_uuids(IMPORT_LEDGER))
    out["new"] = len(cands)
    return out
