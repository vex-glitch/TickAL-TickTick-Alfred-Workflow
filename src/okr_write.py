#!/usr/bin/env python3
"""okr_write.py - every TickTick write the 🥅 OKR hub makes (HANDOFF_OKR
phase 2). okr.py plans, this module writes; okr.py stays pure.

Why src/ and not Scripts/xact.py: the hourly agent (src/sync.py) heals and
auto-ticks too, and it cannot import Scripts/. So the xact verbs
(okr_sched, okr_addkr, okr_link, okr_tag, okr_heal) are thin wrappers over
the functions here, and sync.py calls heal_and_tick() directly.

THE WRITER RULE (okr.py module docstring). A span write - a schedule
action's ripple, the heal - and the auto-tick write only from a Snapshot
that is .writable: a live read with every completed KR. A cache read, or one
missing completed KRs, reads a ticked deliverable as deleted, and a plan
built on that writes a wrong plan over the right one. Title, tag and new-KR
writes need a LIVE read (settled names and codes, the O's KRs) but not the
completed feed.

THE LOCK (~/.ticktick_alfred/okr.lock). Every writer loads INSIDE it, so no
plan comes from a snapshot another writer has already made stale. User verbs
wait for it (LOCK_WAIT, then refuse "busy" rather than hang); the background
heal takes it non-blocking and leaves when it is taken. Full-object writes
clobber whatever changed since the read (a KR ticked in between would be
posted back open), so load -> write stays inside one hold. The heal's ticks
come from a SECOND hold (its done lookups run between the two), so each
candidate is re-read inside that hold and ticked only while still open: two
overlapping heals tick a KR once.

STORED ITEMS ONLY. apply_spans puts snap.items on their new dates, never an
okr.healed() copy: a healed copy's start/end moved but its raw still holds
the stored stamps, and write_fields would read "same length, shift by 0" and
leave a stale O where it was (map trap 1).

WRITES: one v2 batch per 50 items (the road the app itself writes on), and
v1 one full object each when there is no v2 token or a batch is refused.
The values are absolute dates / titles / tags on full objects, so a v1 retry
after a half-applied batch lands the same.

CACHE: patch_cache() mirrors every write into all_tasks, all_notes, the
list's project_data_<pid> (the browse screens read that) and the hub's own
okr_rows snapshot ({"list_id", "name", "done_complete", "rows": [raw
tasks]}), in one pass. okr_rows is REBUILT from the writer's own live read,
never patched: an older copy re-stamped by a patch would pass the hub's
freshness test and show a plan the app has moved on from. It never
invalidates all_tasks: the next keystroke would refetch every list live
against the 300-per-5-min budget (map trap 10).

NO SYNC CLICK HERE. Every road a verb runs on ends at ET End, which already
clicks File > Sync; a second click inside the same breath is the double
click that wedged TickTick's sync on 2026-09-12. The detached heal banners
through the same End (xact _crm_say), and the hourly sync's headless banner
does too.
"""
import fcntl
import os
import re
import subprocess
import time
from collections import namedtuple
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import cache as cache_store
import config as cfg
import okr

LOCK_FILE = os.path.join(cfg.CONFIG_DIR, "okr.lock")
HEAL_STAMP = os.path.join(cfg.CONFIG_DIR, "okr_heal.stamp")
HEAL_LOG = "/tmp/tickal_okr.log"
LOCK_WAIT = 90.0          # seconds a user verb waits out a running heal
BATCH = 50                # v2 batch/task bodies per request
ROWS_KEY = "okr_rows"     # the hub's cached snapshot (browse ctx:okr)
AREA_ROOT = "0️⃣area"
MAX_EXTEND = 3660         # days; a typo like +99999 is not a plan


class Refusal(Exception):
    """A write that was NOT made, worded for the toast. The xact wrapper
    prints it once - left to escape, main()'s catch-all would print AND
    banner it (two notices, map trap 17)."""


# ── plumbing ─────────────────────────────────────────────────────────────────
@contextmanager
def _lock(wait=None):
    """Hold the OKR write lock; yields True when held, False when another
    writer kept it past `wait` seconds (0 = one non-blocking try, the
    background heal). A lock file that cannot even be opened yields True:
    a broken lock must not block every write (app_sync.claim fails open
    the same way)."""
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


def _clients(api=None, v2=None):
    """(v1 client, v2 client or None). Built once per verb so the read, the
    writes and the done lookups share them."""
    if api is None:
        from api import TickTickAPI
        api = TickTickAPI(cfg.get_token())
    if v2 is None:
        try:
            from api_v2 import TickTickV2
            v2 = TickTickV2()
        except Exception:
            v2 = None
    return api, v2


def _has_token(v2):
    return v2 is not None and bool(getattr(v2, "token", None))


def _load(api, v2, writable):
    """The live snapshot a writer may use, else Refusal. writable=True is
    the writer rule (spans, ticks); False needs a live read only."""
    pid = cfg.get_okr_list_id()
    if not pid:
        raise Refusal("🥅 OKRs are off · ⚙️ Settings → OKR List")
    try:
        snap = okr.load(api=api, v2=v2, list_id=pid)
    except okr.OkrLoadError as e:
        raise Refusal(f"🥅 Not written · {e}")
    if snap.source != "live" or (writable and not snap.writable):
        raise Refusal(_why_not(snap, v2))
    return snap


def _why_not(snap, v2):
    """Why a read cannot feed this writer, worded like wontdo's toast: a
    cache read never can, a live one only with every completed KR."""
    if snap.source != "live":
        return "🥅 Not written · TickTick unreachable, only the cache answered"
    if "TRUNCATED" in (snap.detail or ""):
        return "🥅 Not written · too many completed KRs to read them all"
    if not _has_token(v2):
        return ("🥅 Not written · completed KRs need the Attachment Login "
                "token (⚙️ Settings)")
    return "🥅 Not written · completed KRs unreadable right now · try again"


def _pd_key(pid):
    """dispatch._pd_key (the inbox is cached under the literal 'inbox')."""
    return ("project_data_inbox" if str(pid).startswith("inbox")
            else f"project_data_{pid}")


def _norm_tags(tags):
    """dispatch._norm_tags: deduped, lowercase (TickTick lowercases names)."""
    return list(dict.fromkeys(str(t).lower() for t in (tags or []) if t))


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


# ── the cache mirror ─────────────────────────────────────────────────────────
def patch_cache(snap, patches=None, done=(), add=(), rebuild=True):
    """Mirror OKR writes into every cache a screen reads, one pass:

      patches  {id: fields} merged into each cached copy of the task
      done     ids completed: out of the OPEN pools (all_tasks, all_notes,
               project_data_<pid>), status 2 in okr_rows (the hub reads
               completed KRs too, for progress), and onto the front of
               completed_tasks - the dispatch complete: mirror
      add      new raw tasks (the caller restates parentId: the v1 create
               response says null, map trap 12), appended everywhere

    okr_rows is REBUILT from `snap` - the live read the caller wrote from,
    loaded inside the lock - with the writes over it, in the shape
    browse._okr_snapshot keeps ({"list_id", "name", "done_complete",
    "rows"}). An older okr_rows copy is never patched: the hub kept it
    minutes ago, the app may have moved things since, and patched and
    re-stamped it would pass browse._okr_fresh as the new plan. rebuild=False
    drops okr_rows instead - for a caller whose snap may be OLDER than a
    copy another writer left (the heal's second hold). Written LAST: the
    hub trusts okr_rows only while its mtime is not older than
    project_data / all_tasks / completed_tasks.

    The written rows are folded back into snap.items (what TickTick now
    holds), so a second mirror in the same hold builds on the first
    (add_krs: the O's 🏷️ line, then its KRs; the heal: spans, then ticks).
    Never raises. A failure drops okr_rows only - never all_tasks (map
    trap 10): the hub re-reads live on its next empty bar."""
    patches = {k: v for k, v in (patches or {}).items() if k and v}
    gone = {d for d in (done or ()) if d}
    add = [a for a in (add or ()) if isinstance(a, dict) and a.get("id")]
    if not (patches or gone or add):
        return
    try:
        list_id = snap.list_id
        stamp = _stamp()
        pname = next((p.get("name") or "" for p in (cache_store.get("projects") or [])
                      if isinstance(p, dict) and p.get("id") == list_id), "")
        entries = []
        for a in add:
            e = dict(a)
            e["projectId"] = e.get("projectId") or list_id
            e["_projectId"] = list_id
            e["_projectName"] = pname
            e["_columnName"] = e.get("_columnName", "")
            entries.append(e)
        new_ids = {e["id"] for e in entries}
        opened = {}

        def fix(rows, keep_done):
            out = []
            for t in rows:
                if not isinstance(t, dict):
                    out.append(t)
                    continue
                tid = t.get("id")
                if tid in new_ids:
                    continue                  # re-added below: idempotent
                if tid in patches:
                    t = {**t, **patches[tid]}
                if tid in gone:
                    opened.setdefault(tid, t)
                    if not keep_done:
                        continue
                    t = {**t, "status": 2, "completedTime": stamp}
                out.append(t)
            return out

        # the snap first: it is what TickTick holds now, whatever the caches do
        plan_rows = fix([i.raw for i in snap.items], True) + [dict(e) for e in entries]
        snap.items = okr.items_from(plan_rows)
        for key in ("all_tasks", "all_notes"):
            rows = cache_store.get(key)
            if isinstance(rows, list):
                rows = fix(rows, False)
                if key == "all_tasks":
                    rows += [dict(e) for e in entries]
                cache_store.set(key, rows)
        pk = _pd_key(list_id)
        pd = cache_store.get(pk)
        if isinstance(pd, dict) and isinstance(pd.get("tasks"), list):
            pd = dict(pd)
            pd["tasks"] = fix(pd["tasks"], False) + [dict(e) for e in entries]
            cache_store.set(pk, pd)
        if gone and opened:
            feed = [t for t in (cache_store.get("completed_tasks") or [])
                    if isinstance(t, dict) and t.get("id") not in gone]
            fresh = [{**opened[i], "status": 2, "completedTime": stamp}
                     for i in opened]
            cache_store.set("completed_tasks", (fresh + feed)[:200])
        # okr_rows LAST: the hub trusts it only while its mtime is not older
        # than project_data / all_tasks / completed_tasks (browse
        # _okr_fresh), and a mirror must not make the rebuilt copy look stale
        if rebuild and snap.source == "live":
            cache_store.set(ROWS_KEY, {"list_id": list_id, "name": snap.name,
                                       "done_complete": snap.done_complete,
                                       "rows": plan_rows})
        else:
            cache_store.invalidate(ROWS_KEY)
    except Exception:
        try:
            cache_store.invalidate(ROWS_KEY)
        except Exception:
            pass


# ── the one writer of full objects ───────────────────────────────────────────
def _write(snap, todo, api, v2):
    """[(Item, fields)] -> (written ids, failed ids). Bodies are the item's
    STORED raw with the fields over it. v2 batch first, 50 a request; a
    chunk v2 refuses (or no token at all) goes v1, one object each -
    update_task is TASK id first, list id second (map trap 2), and the
    fields carry isAllDay whenever they carry dates, so v1 never guesses it
    (trap 3)."""
    written, failed = [], []
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        ok = False
        if _has_token(v2):
            try:
                ok = bool(v2.update_tasks([{**(it.raw or {}), **f} for it, f in chunk]))
            except Exception:
                ok = False
        if ok:
            written += [it.id for it, _f in chunk]
            continue
        for it, f in chunk:
            try:
                api.update_task(it.id, it.pid or snap.list_id, current=it.raw, **f)
                written.append(it.id)
            except Exception:
                failed.append(it.id)
    return written, failed


SpanResult = namedtuple("SpanResult", "written failed")


def apply_spans(snap, pairs, api=None, v2=None):
    """Put items on new all-day spans: pairs = [(id, start, end_inclusive)],
    a plan's MOVES then its HEALS - the later entry for an id wins, which is
    how okr.ripple_plan means them. Planned from snap.items as STORED (the
    module docstring: never a healed() copy). History never moves; an item
    already all-day on that exact span is not written (a TIMED one on it is:
    OKR items are all-day by rule). The cache follows only what TickTick
    took. THE WRITER RULE is checked here, whoever calls: a snap that is not
    .writable is a Refusal before anything is planned.
    -> SpanResult(written ids, failed ids)."""
    if not snap.writable:
        raise Refusal(_why_not(snap, v2))
    by = okr.index(snap.items)
    final = {}
    for iid, s, e in pairs or ():
        final[iid] = (s, e)
    todo = []
    for iid, (s, e) in final.items():
        it = by.get(iid)
        if it is None or it.history:
            continue
        if (it.start, it.end) == (s, e) and (it.raw or {}).get("isAllDay") is True:
            continue
        todo.append((it, okr.write_fields(it, s, e)))
    if not todo:
        return SpanResult([], [])
    api, v2 = _clients(api, v2) if api is None else (api, v2)
    written, failed = _write(snap, todo, api, v2)
    ok = set(written)
    patch_cache(snap, patches={it.id: f for it, f in todo if it.id in ok})
    return SpanResult(written, failed)


# ── 📅 schedule: extend / tomorrow / pick a date, with the ripple ────────────
def _sched_arg(action, arg):
    if action == "extend":
        try:
            if isinstance(arg, bool):
                raise ValueError
            n = int(str(arg).strip())
        except (TypeError, ValueError):
            raise Refusal(f"📅 Extend by how many days? Got {arg!r}")
        if abs(n) > MAX_EXTEND:
            raise Refusal(f"📅 {n:+d} days is not a plan")
        return n
    if action == "date":
        try:
            return date.fromisoformat(str(arg or "").strip())
        except ValueError:
            raise Refusal(f"📅 Not a date: {arg!r}")
    return None


def schedule(spec, api=None, v2=None, today=None):
    """xact:okr_sched {"id", "action": extend|tomorrow|date, "arg"}. The
    plan is okr.schedule_plan's (the ONLY way dates are computed - it reads
    them off healed items), written moves-then-heals from the STORED items.
    Its ValueErrors are refusals, toasted as they are (closed item, undated
    extend, a parent that cannot land on the asked end) - "bad span" (a
    pull-in longer than the item) in words. The past is refused: a picked
    start before today, and an extend whose new end is before today (the
    plan is a forecast; yesterday is not one). -> toast text."""
    iid = str(spec.get("id") or "")
    action = spec.get("action")
    if not iid or action not in okr.SCHEDULE_ACTIONS:
        raise Refusal("📅 Nothing to schedule")
    arg = _sched_arg(action, spec.get("arg"))
    today = today or date.today()
    if action == "date" and arg < today:
        raise Refusal("📅 That day is gone · today or later")
    api, v2 = _clients(api, v2)
    with _lock() as got:
        if not got:
            raise Refusal("🥅 Busy · another OKR write is running · try again")
        snap = _load(api, v2, writable=True)
        by = okr.index(snap.items)
        it = by.get(iid)
        if it is None:
            raise Refusal("🥅 Not in the OKR list any more")
        try:
            moves, heals = okr.schedule_plan(snap.items, iid, action, arg, today)
        except ValueError as e:
            if str(e).startswith("bad span"):
                raise Refusal("📅 Longer than the item · pick a date")
            raise Refusal(f"📅 {e}")
        # the span every screen shows for it: the HEALED one (a stale-stored
        # O reads Sep 29 while all its screens say Sep 19). Taken BEFORE
        # apply_spans folds the writes into snap.items.
        h = okr.index(okr.healed(snap.items))[iid]
        if action == "extend":
            # the end schedule_plan asked for: the HEALED end + N
            if h.end + timedelta(days=arg) < today:
                raise Refusal("📅 That end is gone · today or later")
        res = apply_spans(snap, list(moves) + list(heals), api, v2)
    final = {}
    for i, s, e in list(moves) + list(heals):
        final[i] = (s, e)
    s, e = final.get(iid, (it.start, it.end))
    span = okr.span_txt(s, e, today)
    done = set(res.written)
    if not done and not res.failed:
        return f"📅 {it.name} already on {span}"
    first = moves[0][0] if moves else None
    stays = f"📅 Not written · {it.name} stays on {okr.span_txt(h.start, h.end, today)}"
    if not done:
        return stays
    moved = {m[0] for m in moves}
    along = sum(1 for m in moves if m[0] in done and m[0] not in (iid, first))
    healed = sum(1 for h in heals if h[0] in done and h[0] != iid and h[0] not in moved)
    if (first or iid) in res.failed:
        # the item that carries the change did not take it: saying
        # "→ <new span>" would be a lie, whatever else went through
        return stays + f" · ⚠️ {len(res.failed)} not written, {len(done)} were"
    msg = f"📅 {it.name} → {span}"
    if first and first != iid and first in by:
        msg += f" · via {by[first].name}"
    if along:
        msg += f" · {along} moved along"
    if healed:
        msg += f" · {healed} healed"
    if res.failed:
        msg += f" · ⚠️ {len(res.failed)} not written"
    return msg


# ── 🔑 KRs under an O from one piped line ────────────────────────────────────
def code_ok(code):
    """A code a KR title reads back: one word, capital or digit first.
    "xy" is not one - the title would end " - xy" and read as part of the
    name - so the verb refuses it; a screen can mark such a row dead with
    this same test."""
    return okr.parse_title(okr.build_title("KR", "x", code=code))[3] == code


def _kr_title(name, code):
    """The KR title, or None when it would not read back (map trap 13):
    with no code, a name ending " - USA" reads USA as its code, and nothing
    in a title can escape an all-caps word. A lower-case or mixed word
    ("Call Anna - Monday") is fine - okr.settle_codes folds it back into the
    name."""
    title = okr.build_title("KR", name, code=code)
    cand = okr.parse_title(title)[3]
    if cand == code or (code is None and not okr._caps(cand or "")):
        return title
    return None


def _live(api, snap, it):
    """The item's live v1 object (the u_append pattern), else its raw."""
    try:
        t = api.get_task(it.pid or snap.list_id, it.id)
        if isinstance(t, dict) and t.get("id"):
            return t
    except Exception:
        pass
    return it.raw


def _stamp_code(api, snap, o, code):
    """Write "🏷️ XY" at the bottom of the O's description, where
    okr.code_of reads it first (HANDOFF section 2: the code lives in the
    O's DESCRIPTION). LIVE GET first - appending to a stale description
    would drop whatever was typed since. -> "" or a toast suffix."""
    try:
        live = _live(api, snap, o)
        old = live.get("content") or ""
        line = okr.code_line(code)
        new = (old.rstrip() + "\n" + line) if old.strip() else line
        api.update_task(o.id, o.pid or snap.list_id, current=live, content=new)
        patch_cache(snap, patches={o.id: {"content": new}})
        return ""
    except Exception:
        return " · 🏷️ not saved"


def _settle_kids(api, v2, made, pid, parent_id, tz):
    """The one full-object body each new KR gets after its create, posted
    once for all of them:

      order     dispatch._order_children's fix: v1 creates subtasks with
                DESCENDING sortOrder (Milk, Bread shows Bread first), so the
                server's own values are dealt back out ascending in TYPED
                order (two or more KRs)
      timeZone  the O's (the caller's `tz`): v1 create takes no zone, and a
                KR read in another zone than the one its all-day dates were
                written in lands a day off once it is dated
      parentId  restated on every body (the create response says null, and
                posting it back as null would detach the lot)

    One v2 batch; a KR whose body changes nothing (one KR already in the
    zone) is no reason to post. v2 refused or no token: v1, one object
    each, only for the KRs that need it - the zone is not cosmetic, the
    order is. Updates `made` in place with what landed."""
    orders = sorted((k.get("sortOrder") or 0) for k in made)
    todo = []                     # (made KR, the fields its body changes)
    for i, k in enumerate(made):
        f = {"parentId": parent_id, "timeZone": tz}
        if len(made) >= 2:
            f["sortOrder"] = orders[i]
        todo.append((k, f, f.get("sortOrder", k.get("sortOrder")) != k.get("sortOrder")
                     or (k.get("timeZone") or "") != tz))
    if not any(n for _k, _f, n in todo):
        return
    bodies = [{**{kk: vv for kk, vv in k.items() if not kk.startswith("_")},
               "projectId": k.get("projectId") or pid, **f} for k, f, _n in todo]
    ok = False
    if _has_token(v2):
        try:
            ok = bool(v2.update_tasks(bodies))
        except Exception:
            ok = False
    for k, f, n in todo:
        if not ok and n:
            try:
                api.update_task(k["id"], pid, current=k, **f)
            except Exception:
                continue
        k.update(f)


def add_krs(spec, api=None, v2=None):
    """xact:okr_addkr {"oid", "names": [...], "code": str|null}. Every name
    becomes a sibling KR under the O, titled "🔑 KR • <name> - <CODE>",
    tagged like its O ("KRs inherit their O's tag"), UNDATED (a fresh copy
    stays undated until Vex drags it - and v1 create with both dates forces
    isAllDay false, map trap 3). No heal: undated KRs shape no span.

    The code: null = the O's own (okr.code_of: its 🏷️ line, its title, its
    KRs' majority), and when it has none, okr.propose_code from its name,
    written into the O's description as its 🏷️ line. A given code (the
    bar's " =XY") wins for these KRs and is written there too when the O
    has no code yet - an existing code is never rewritten ("never rewrite
    his"). Refused under anything but an open 🥅 O. Every KR takes the O's
    timeZone (else Europe/Berlin) in the body _settle_kids posts anyway."""
    oid = str(spec.get("oid") or "")
    names = [" ".join(str(n).split()) for n in (spec.get("names") or [])
             if isinstance(n, str) and n.strip()]
    if not oid or not names:
        raise Refusal("🔑 No KR names")
    given = spec.get("code")
    given = str(given).strip() if given not in (None, "") else None
    if given is not None and not code_ok(given):
        raise Refusal(f"🔑 Code {given!r} would not read back · one word, capital first")
    api, v2 = _clients(api, v2)
    with _lock() as got:
        if not got:
            raise Refusal("🥅 Busy · another OKR write is running · try again")
        snap = _load(api, v2, writable=False)
        o = okr.index(snap.items).get(oid)
        if o is None:
            raise Refusal("🔑 That objective is gone from the list")
        if o.kind != "O":
            raise Refusal(f"🔑 KRs go under a 🥅 O · {o.name} is not one")
        if o.history:
            raise Refusal(f"🔑 {o.name} is closed · reopen it first")
        have = okr.code_of(o, okr.krs_of(o, snap.items))
        code = given or have or okr.propose_code(o.name) or None
        note = _stamp_code(api, snap, o, code) if (code and have is None) else ""
        tags = list((o.raw or {}).get("tags") or [])
        made, skipped, failed = [], [], []
        for name in names:
            title = _kr_title(name, code)
            if title is None:
                skipped.append(name)
                continue
            try:
                t = api.create_task(title=title, project_id=snap.list_id,
                                    parent_id=o.id, tags=tags or None)
            except Exception:
                failed.append(name)
                continue
            if isinstance(t, dict) and t.get("id"):
                t = dict(t)
                t["parentId"] = o.id            # the response says null, it lies
                t["projectId"] = t.get("projectId") or snap.list_id
                made.append(t)
            else:
                failed.append(name)
        _settle_kids(api, v2, made, snap.list_id, o.id, o.tz or okr.DEFAULT_TZ)
        patch_cache(snap, add=made)
    n = len(made)
    msg = (f"🔑 {n} KR{'' if n == 1 else 's'} under {o.name}" if n
           else f"🔑 No KR added under {o.name}")
    msg += f" · code {code}" if code else " · no code"
    msg += note
    if skipped:
        msg += " · skipped " + ", ".join(repr(s) for s in skipped[:3]) + " (reads as a code)"
    if failed:
        msg += f" · ⚠️ {len(failed)} not created"
    return msg


# ── 🔗 link a task, note or list ─────────────────────────────────────────────
def _target_name(to, pid, tid):
    try:
        if to == "list":
            p = next((p for p in (cache_store.get("projects") or [])
                      if isinstance(p, dict) and p.get("id") == pid), None)
            return f"📂 {p.get('name')}" if p and p.get("name") else "the list"
        t = cache_store.find_task(tid) or {}
        import mdtext
        return mdtext.link_text(t.get("title") or "", 40) or "the task"
    except Exception:
        return "the task" if to == "task" else "the list"


def link(spec, api=None, v2=None):
    """xact:okr_link {"id", "to": task|list, "pid", "tid"}. Rewrites ONLY
    the planning copy's title: prefix and code outside the link, the name
    as its label ("🔑 KR • [Goals wf](<task link>) - TA"). The target is
    never touched - "moving a copy NEVER moves the real task". Built from
    the SETTLED Item (items_from), never raw parse_title candidates, so
    "Call Anna - Monday" does not gain the code Monday (map trap 14); a
    title with a link inside other words comes back as one whole-body link
    (build_title writes no other shape). NOTHING inside the OKR list is a
    target: not another planning copy (by its list, or by its id when the
    payload's list is stale), not the plan list itself."""
    iid = str(spec.get("id") or "")
    to = spec.get("to")
    pid = str(spec.get("pid") or "")
    tid = str(spec.get("tid") or "")
    if not iid or to not in ("task", "list") or not pid or (to == "task" and not tid):
        raise Refusal("🔗 Nothing to link")
    copy = "🔗 That is a planning copy · link the original"
    plan = "🔗 That is the plan list · link the real one"
    if pid == cfg.get_okr_list_id():
        raise Refusal(copy if to == "task" else plan)
    api, v2 = _clients(api, v2)
    with _lock() as got:
        if not got:
            raise Refusal("🥅 Busy · another OKR write is running · try again")
        snap = _load(api, v2, writable=False)
        by = okr.index(snap.items)
        it = by.get(iid)
        if it is None:
            raise Refusal("🔗 Not in the OKR list any more")
        if it.kind not in okr.KINDS:
            raise Refusal("🔗 Not an OKR item · give it a 🏔️ / 🥅 / 🔑 prefix first")
        if pid == snap.list_id or (to == "task" and tid in by):
            raise Refusal(copy if to == "task" else plan)
        url = okr.task_link(pid, tid) if to == "task" else okr.list_link(pid)
        new = okr.build_title(it.kind, it.name, link=url, code=it.code)
        if new == it.title:
            return f"🔗 Already linked · {it.name}"
        current = _live(api, snap, it)
        api.update_task(it.id, it.pid or snap.list_id, current=current, title=new)
        patch_cache(snap, patches={it.id: {"title": new}})
    return f"🔗 {it.name} → {_target_name(to, pid, tid)}"


# ── 🏷 tag from the OKR pool ─────────────────────────────────────────────────
def _area_tags():
    import tagtree
    return {str(t).lower() for t in tagtree.children_of(AREA_ROOT) if t}


def tag_pool(items):
    """The OKR tags (HANDOFF_OKR section 4, the picker's pool; Vex's ruling
    2026-09-18): the 0️⃣Area subtags plus every tag a 🏔️ Y or 🥅 O of the
    list carries (the LANE tags - done ones too, a closed O still names its
    lane), lowercase. A tag only KRs or loose items carry is theirs, never
    the pool's: a retag keeps it."""
    pool = _area_tags()
    for it in items:
        if it.kind in okr.PARENT_KINDS:
            pool.update(_norm_tags(it.tags))
    return pool


def _tag_label(name):
    for t in cache_store.get("tags_tree") or []:
        if isinstance(t, dict) and (t.get("name") or "").lower() == name:
            return t.get("label") or name
    return name


def retag(spec, api=None, v2=None):
    """xact:okr_tag {"id", "tag"}. REPLACES the item's OKR-pool tags
    (tag_pool: 0️⃣Area + the Y/O lane tags) with the picked one and keeps
    every other tag. On an 🥅 O it cascades to its OPEN KRs whose pool tags
    share one with the O's old ones, or that carry no pool tag at all ("KRs
    inherit their O's tag") - a KR tagged into another lane on purpose
    keeps it. Tags compare as SETS: the same tags in another order is
    "already", no write. The picked tag must be in the pool: no area tag is
    ever created here (HANDOFF trap 11)."""
    iid = str(spec.get("id") or "")
    tag = str(spec.get("tag") or "").strip().lstrip("#").lower()
    if not iid or not tag:
        raise Refusal("🏷 No tag picked")
    api, v2 = _clients(api, v2)
    with _lock() as got:
        if not got:
            raise Refusal("🥅 Busy · another OKR write is running · try again")
        snap = _load(api, v2, writable=False)
        it = okr.index(snap.items).get(iid)
        if it is None:
            raise Refusal("🏷 Not in the OKR list any more")
        pool = tag_pool(snap.items)
        if tag not in pool:
            raise Refusal(f"🏷 {_tag_label(tag)} is not an OKR tag · 0️⃣Area or a Y / O tag")

        def pool_tags(x):
            return {t for t in _norm_tags(x.tags) if t in pool}

        old = pool_tags(it)
        targets = [it]
        if it.kind == "O":
            for kr in okr.krs_of(it, snap.items):
                if kr.history or kr.id == it.id:
                    continue
                mine = pool_tags(kr)
                if not mine or mine & old:
                    targets.append(kr)
        todo = []
        for x in targets:
            now = _norm_tags(x.tags)
            drop = pool_tags(x)
            new = _norm_tags([tag] + [t for t in now if t not in drop])
            if set(new) != set(now):
                todo.append((x, {"tags": new}))
        if not todo:
            return f"🏷 {it.name} already {_tag_label(tag)}"
        written, failed = _write(snap, todo, api, v2)
        ok = set(written)
        patch_cache(snap, patches={x.id: f for x, f in todo if x.id in ok})
    krs = sum(1 for x, _f in todo if x.id != it.id and x.id in ok)
    mine_ok = it.id in ok or all(x.id != it.id for x, _f in todo)
    msg = f"🏷 {_tag_label(tag)} · {it.name}" if mine_ok else f"🏷 {it.name} not retagged"
    if krs:
        msg += f" · {krs} KR{'' if krs == 1 else 's'} too"
    if failed:
        msg += f" · ⚠️ {len(failed)} not written"
    return msg


# ── heal + auto-tick (hub open, hourly sync) ─────────────────────────────────
HealResult = namedtuple("HealResult", "healed ticked chip note")


def heal_and_tick(api=None, v2=None, is_done=None, today=None):
    """The background pass (HANDOFF_OKR section 4): every open Y/O onto its
    wanted span (okr.heal_diff, deepest first), then every open KR whose
    linked single task is COMPLETED gets ticked ("Auto-tick: YES", only a
    live status 2 ticks). Silent unless it wrote: -> HealResult(healed,
    ticked, chip, note); chip is "" when nothing changed, note always says
    what happened (the detached run's log line).

    Never blocks: the lock is taken non-blocking and a busy lock skips the
    pass - a user verb holds it, and heals as part of its own write. The
    done lookups (one GET per task-linked open KR) run OUTSIDE the lock so
    a hub open never makes a schedule action wait on them; the ticks take
    the lock again, because a full-object span write that raced a tick
    would post the KR back open. Inside that second hold every candidate is
    RE-READ and ticked only while still open (status 0): another heal (the
    hourly one and a hub open overlap) or Vex may have ticked it since the
    first read, and only the ticks that happened are counted. okr_rows is
    rebuilt from the first hold's read only while no other writer has left
    a copy since; otherwise it is dropped (patch_cache rebuild=False). Never
    raises (the hourly sync must not die on a nicety)."""
    try:
        pid = cfg.get_okr_list_id()
        if not pid:
            return HealResult(0, 0, "", "okr list off")
        api, v2 = _clients(api, v2)
        with _lock(wait=0) as got:
            if not got:
                return HealResult(0, 0, "", "busy: another OKR write holds the lock")
            try:
                snap = okr.load(api=api, v2=v2, list_id=pid)
            except okr.OkrLoadError as e:
                return HealResult(0, 0, "", f"unreadable: {e}")
            if not snap.writable:
                return HealResult(0, 0, "", f"refused (not a complete live read): {snap.detail}")
            res = apply_spans(snap, okr.heal_diff(snap.items), api, v2)
            linked = [k for k in snap.items if k.kind == "KR" and not k.history
                      and (k.target or ("",))[0] == "task"]
            left = cache_store.get(ROWS_KEY) if linked else None
        healed = len(res.written)
        ticked, tick_fail, moved_on = [], 0, 0
        if linked:
            look = is_done or okr.done_lookup(api)
            cands = okr.autotick_candidates(linked, look)
            if cands:
                with _lock(wait=30) as got:
                    if got:
                        for kr in cands:
                            p = kr.pid or snap.list_id
                            try:
                                now = api.get_task(p, kr.id)
                            except Exception:
                                now = None
                            if not (isinstance(now, dict) and now.get("status") == 0
                                    and not now.get("deleted")):
                                moved_on += 1     # ticked, gone or unreadable since
                                continue
                            try:
                                api.complete_task(p, kr.id)
                                ticked.append(kr.id)
                            except Exception:
                                tick_fail += 1
                        if ticked:
                            patch_cache(snap, done=ticked,
                                        rebuild=cache_store.get(ROWS_KEY) == left)
                    else:
                        tick_fail = len(cands)
        parts = []
        if healed:
            parts.append(f"🥅 {healed} span{'' if healed == 1 else 's'} healed")
        if ticked:
            parts.append(f"🔑 {len(ticked)} KR{'' if len(ticked) == 1 else 's'} ticked · "
                         f"original{'' if len(ticked) == 1 else 's'} done")
        note = (f"healed {healed} (failed {len(res.failed)}), ticked {len(ticked)} "
                f"(failed {tick_fail}, no longer open {moved_on}), "
                f"{len(linked)} linked open KRs · {snap.detail}")
        return HealResult(healed, len(ticked), " · ".join(parts), note)
    except Exception as e:
        return HealResult(0, 0, "", f"failed: {type(e).__name__}: {e}")


def spawn_heal(debounce_s=300):
    """Fire-and-forget "xact:okr_heal", detached (xact._pn_bg's shape): safe
    from a script filter render, returns at once. Debounced through
    app_sync.claim on its own stamp - the hub re-renders on every
    keystroke, and one pass per `debounce_s` is plenty. The child never
    inherits the render's stdout (it would corrupt the Alfred JSON, map
    trap 9): stdout/stderr go to HEAL_LOG, stdin is /dev/null, and it runs
    in its own session with TICKAL_DETACHED=1 (so it banners, not prints).
    -> True when a child was started."""
    try:
        if not cfg.get_okr_list_id():
            return False
        import app_sync
        if not app_sync.claim(min_gap=debounce_s, stamp=HEAL_STAMP):
            return False
        wf = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(HEAL_LOG, "a") as logf:
            subprocess.Popen(
                ["/bin/bash", os.path.join(wf, "Scripts", "py.sh"),
                 os.path.join(wf, "Scripts", "xact.py"), "xact:okr_heal"],
                stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                start_new_session=True, env=dict(os.environ, TICKAL_DETACHED="1"))
        return True
    except Exception:
        return False


# ── ⚙️ Settings → OKR List ───────────────────────────────────────────────────
_LIST_ID_RE = re.compile(r"[0-9a-fA-F]{24}")


def parse_list_answer(answer):
    """The Settings dialog's answer -> the value to save: "" = OFF (a blank
    okr_list_id means off, HANDOFF_OKR section 5), a 24-hex list id as
    typed, None = not a list id (nothing saved)."""
    a = (answer or "").strip()
    if not a:
        return ""
    return a if _LIST_ID_RE.fullmatch(a) else None
