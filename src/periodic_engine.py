"""periodic_engine.py - impure periodic-notes engine.

Owns: the note index (one v1 get_project_data call), lazy-mint + the 04:30
mint-ahead run, the refresh pipelines, money/stat roll-ups, and the journal
seed/merge RMWs. All note writes go through _pn_rmw - ONE live GET, one
conditional POST, cache mirror, app-sync nudge - under a cross-process flock
(agent vs. interactive verbs on the same note: last-POST-wins races are real).

Contracts live in periodic_model (pure); structure ops in periodic_sections.
Verbs in Scripts/xact.py are thin delegators to the public functions at the
bottom. Every public function assumes the caller already checked
areas.periodic_configured() - xact gates, the agent gates, sims gate.
"""
import fcntl
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import areas
import cache as cache_store
import config as cfg
import focus_blocks as fb
import periodic_journal as pj
import periodic_model as pm
import periodic_sections as ps
from api import TickTickAPI
import mdtext
# NOTE: display.md_links_display is DISPLAY-ONLY ("[name]🔗", never applied to
# data - its own docstring says so) and four writers here were putting it into
# note CONTENT: the ⏪ Yesterday recap and three roll-up summaries. Plain text
# is what a note wants, so they flatten to the LABEL instead (2026-09-12,
# after Vex asked why a line in his daily note showed raw markdown).
from filtering import utc_str_to_local_date
from script_base import run_path

LOCK_FILE = os.path.join(cfg.CONFIG_DIR, "periodic.lock")
STAMP_FILE = os.path.join(cfg.CONFIG_DIR, "pn_last_mint")
LOG_FILE = "/tmp/tickal_periodic.log"
TPL_REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "periodic_templates")
TPL_USER = os.path.join(cfg.CONFIG_DIR, "periodic_templates")
REFRESH_TTL = 600          # pn_open skips a re-refresh younger than this
POST_GAP = 0.25            # rate-limit insurance between consecutive POSTs

SPECS = ("daily", "yesterday", "weekly", "monthly", "quarterly", "yearly")


def _log(msg):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


# ── plumbing ─────────────────────────────────────────────────────────────────
_API = None


def _api():
    global _API
    if _API is None:
        _API = TickTickAPI(cfg.get_token())
    return _API


_LOCK_FD = None
_LOCK_DEPTH = 0


@contextmanager
def _flock():
    """Cross-process serialization (agent vs verbs), reentrant in-process."""
    global _LOCK_FD, _LOCK_DEPTH
    if _LOCK_DEPTH:
        _LOCK_DEPTH += 1
        try:
            yield
        finally:
            _LOCK_DEPTH -= 1
        return
    os.makedirs(cfg.CONFIG_DIR, exist_ok=True)
    _LOCK_FD = open(LOCK_FILE, "w")
    fcntl.flock(_LOCK_FD, fcntl.LOCK_EX)
    _LOCK_DEPTH = 1
    try:
        yield
    finally:
        _LOCK_DEPTH = 0
        try:
            fcntl.flock(_LOCK_FD, fcntl.LOCK_UN)
            _LOCK_FD.close()
        except Exception:
            pass
        _LOCK_FD = None


def _app_sync_nudge():
    """Open windows redraw our content writes in seconds (xact clone - this
    module can't import Scripts/).

    THROTTLED through the same claim as xact's clone (src/app_sync.py): the
    two of them together fired three File ▸ Sync clicks inside 300 ms and
    wedged the app's sync on 2026-09-12."""
    try:
        import app_sync
        if not app_sync.claim():
            return
        if os.environ.get("alfred_version"):
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to tell process "TickTick" '
                 'to click menu item "Sync" of menu "File" of menu bar 1'],
                capture_output=True, check=False, timeout=6)
        else:
            subprocess.run(
                ["osascript", "-e",
                 ('on run argv\n'
                  'tell application id "com.runningwithcrayons.Alfred" to '
                  'run trigger "XAct" in workflow "com.vex.tickal" '
                  'with argument (item 1 of argv)\nend run'),
                 "xact:app_sync"], check=False, timeout=10)
    except Exception:
        pass


_LAST_POST = [0.0]


def _pn_rmw(pid, tid, mutate):
    """LIVE read-modify-write of one periodic note. mutate(secdoc, live_task)
    → result; may itself call the API (the sweep does). ONE GET, POST only on
    diff, cache mirror, sync nudge. Returns (result, doc)."""
    with _flock():
        api = _api()
        live = api.get_task(pid, tid)
        old = live.get("content") or ""
        doc = ps.parse_sections(old)
        result = mutate(doc, live)
        new = ps.serialize_sections(doc)
        if new != old:
            gap = time.time() - _LAST_POST[0]
            if gap < POST_GAP:
                time.sleep(POST_GAP - gap)
            api.update_task(tid, pid, current=live, content=new)
            _LAST_POST[0] = time.time()
            try:
                from dispatch import _patch_task_cache
                _patch_task_cache(tid, content=new)
            except Exception:
                pass
            _app_sync_nudge()
    return result, doc


# ── index ────────────────────────────────────────────────────────────────────
_INDEX = None          # {(kind, title_key): task-dict-with-content}


def _persist_id():
    """Write-through: the Alfred config fields only exist as env vars under
    Alfred - mirror them into config.json so the headless launchd agent (no
    Alfred env) stays configured after the FIRST interactive use."""
    try:
        data = cfg.load()
        dirty = False
        for key in ("periodic_list_id", "weekly_review_id"):
            if key not in os.environ:
                continue                      # headless: config.json rules
            env = os.environ[key]
            if env and data.get(key) != env:
                data[key] = env
                dirty = True
            elif not env and key in data:
                data.pop(key)                 # blanked field = OFF, everywhere
                dirty = True
        if dirty:
            cfg.save(data)
    except Exception:
        pass


def build_index(force=False):
    global _INDEX
    if _INDEX is not None and not force:
        return _INDEX
    _persist_id()
    data = _api().get_project_data(areas.PERIODIC_LIST_ID)
    idx = {}
    for t in (data.get("tasks") or []):
        tags_lc = {str(x).lower() for x in (t.get("tags") or [])}
        title = t.get("title") or ""
        for kind, tg in pm.TIER_TAGS.items():
            if tg.lower() not in tags_lc:
                continue
            if kind == "daily":
                d = pm.parse_daily_title(title)
                if d:
                    idx[(kind, d.isoformat())] = t
            else:
                idx[(kind, pm.stable_key(title))] = t
            break
    _INDEX = idx
    return idx


def lookup(index, p):
    return index.get((p.kind, pm.title_key(p)))


def _note_url(task):
    """In-note link form (the [[ ]]/checkbox contract - https, not ticktick://)."""
    if not task:
        return None
    pid = task.get("projectId") or task.get("_projectId") or areas.PERIODIC_LIST_ID
    return f"https://ticktick.com/webapp/#p/{pid}/tasks/{task.get('id')}"


def open_link(task):
    pid = task.get("projectId") or task.get("_projectId") or areas.PERIODIC_LIST_ID
    return f"ticktick:///webapp/#p/{pid}/tasks/{task.get('id')}"


# ── templates / nav ──────────────────────────────────────────────────────────
def _load_template(kind):
    for base in (TPL_USER, TPL_REPO):
        path = os.path.join(base, f"{kind}.md")
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if text.strip():
                return text
        except Exception:
            continue
    return "{{breadcrumbs}}\n\n### 💰 Money\n**Total = 0**\n"   # last-resort skeleton


# Vex 2026-09-12: the note head is the BREADCRUMB only - "I do not need all
# those links. Leave only previous, up, next." The two smart-view rows that
# used to sit under it (⏪ Yesterday · 📅 Today · 🌄 Tomorrow, then 7️⃣ Next 7 ·
# ✔️ Completed · 🔄 Habits, plus 👥 CRM / ♻️ Review) are gone; those deep links
# still live, verified, in everything_search's VIEWS table.
def _review_target(rid=None):
    """A review id → (https_url, kind, obj) | None. kind: 'list' when the
    id names a project, 'task' when it names a cached task (its subtasks are
    the checklist), else None (unknown id = feature off, honest silence).
    Defaults to the weekly's."""
    rid = ((rid if rid is not None else cfg.get_weekly_review_id()) or "").strip()
    if not rid:
        return None
    for pr in (cache_store.get("projects") or []):
        if pr.get("id") == rid:
            return (f"https://ticktick.com/webapp/#p/{rid}/tasks", "list", pr)
    for t in (cache_store.get("all_tasks") or []):
        if t.get("id") == rid:
            pid = t.get("projectId") or t.get("_projectId") or ""
            return (f"https://ticktick.com/webapp/#p/{pid}/tasks/{rid}", "task", t)
    return None


def _crumb(p, index):
    return pm.render_breadcrumb(
        pm.breadcrumb_segments(p, lambda q: _note_url(lookup(index, q))))


def _day_links(p, index):
    """The week's seven day bullets, linked to the daily notes that exist."""
    return pm.day_link_lines(p, lambda q: _note_url(lookup(index, q)))


def _week_links(p, index):
    """The month's weeks as bullets, linked to their weekly notes: the day
    links one tier up (Vex 2026-09-17). Labels are month-local and clipped -
    "W1 · 1st-6th Sep" - see pm.month_week_spans."""
    if p.kind != "monthly":
        return []
    out = []
    for n, wp, a, b in pm.month_week_spans(p):
        label = pm.week_span_label(n, a, b)
        u = _note_url(lookup(index, wp))
        out.append(f"- [{label}]({u})" if u else f"- {label}")
    return out


def _week_goals_of(wdoc):
    """(this week's OWN goal lines, the section that holds them).

    Since 2026-09-17 a weekly note's 🏆 Goals holds one bullet per tier -
    🌓 Quarterly and 🗓️ Monthly are mirrors of their own notes and ♻️ Weekly
    is the week's own. Only the last one may travel into the daily note or
    into "did you achieve your weekly goals?".

    Which shape a note is in is decided by the two MIRROR bullets, never by
    whether ♻️ Weekly resolves: deleting a bullet is the documented kill
    switch, and falling back to the whole section there would push the
    quarter's and the month's goals into the daily.
    """
    tiered = any(ps.find(wdoc, a, pm.SEC_GOALS) is not None
                 for a in (pm.SEC_WK_QTR, pm.SEC_WK_MONTH))
    sec = (ps.find(wdoc, pm.SEC_WK_WEEK, pm.SEC_GOALS) if tiered
           else ps.find(wdoc, pm.SEC_GOALS))
    return [ln for ln in (sec.body if sec else []) if ln.strip()], sec


def _goal_append(doc, sec_name, line):
    """Append a goal, EATING the template's bare "- [ ]" placeholder if the
    section still carries one. Vex 2026-09-17, on setting the month goal:
    "new row appeared with new checkbox while our existing checkbox in a row
    below monthly goal stayed unused"."""
    sec = ps.find(doc, sec_name)
    if sec is None:
        return False
    keep = [l for l in sec.body if not pm.EMPTY_BOX_RE.match(l.strip())]
    if keep != list(sec.body):
        sec.body = keep
    return ps.append_body(doc, sec_name, [line])


def _week_goal_home(doc):
    """Where a NEW weekly goal is appended: the ♻️ Weekly bullet, or the whole
    🏆 Goals section in a note minted before the tiered layout."""
    return (pm.SEC_WK_WEEK
            if ps.find(doc, pm.SEC_WK_WEEK, pm.SEC_GOALS) is not None
            else pm.SEC_GOALS)


def _mirror_goal(doc, anchor, kind, index, day, hint):
    """Copy a parent period's goals into `anchor`, or reset it to its pointer
    line when that parent has none - the 🗓️ Weekly mirror's rule: never keep
    a stale copy. The source is pm.GOAL_SECTION[kind], so it follows the tier
    wherever its goal setter writes. Silent when the anchor or the parent
    note is missing (kill switch / bootstrap window)."""
    if ps.find(doc, anchor, pm.SEC_GOALS) is None:
        return
    par = lookup(index, pm.period_for(kind, day))
    if not par:
        return
    pdoc = ps.parse_sections(par.get("content") or "")
    sec = next((x for x in (ps.find(pdoc, nm)
                            for nm in pm.goal_section_names(kind))
                if x is not None), None)
    lines = [ln for ln in (sec.body if sec else []) if pm.goal_titles([ln])]
    if not lines:                  # a bare "- [ ]" or an _(hint)_ is not a goal
        lines = []
    ps.set_body(doc, anchor, lines or [pm.T1 + hint], within=pm.SEC_GOALS)


def _compose_lead(doc, p, index, refetch):
    """The lead is ENGINE-OWNED (hand-tuned layout): crumb / nav / ---,
    on weeklies the week's seven day links + a closing ---, and on dailies
    weather + quote + Mood/Day lines + a closing ---.
    Existing weather/quote/mood/day lines carry over; refetch=True swaps in
    fresh weather+quote (today's note only). Returns changed?"""
    old = doc.lead
    q_lines = [l for l in old if l.strip().startswith(">")]
    w_line = next((l for l in old if "°C" in l
                   and not l.strip().startswith(">")), None)
    if refetch and p.kind == "daily":
        t2 = _tier2()
        q = getattr(t2, "get_quote", lambda: None)() if t2 else None
        w = getattr(t2, "get_weather", lambda: None)() if t2 else None
        if q:
            q_lines = [q]
        if w:
            w_line = w
    out = [_crumb(p, index)] + ["---"]
    if p.kind == "weekly":
        # the week's own days, under the crumb (Vex 2026-09-17). Engine-owned
        # like the crumb above them: a day minted later heals into a link on
        # the next refresh.
        out += _day_links(p, index) + ["---"]
    if p.kind == "monthly":
        out += _week_links(p, index) + ["---"]
    if p.kind == "daily":
        # Mood and the day rating are NOT in the lead any more - Vex moved
        # them into the journals, where the questions that produce them live
        # ("I have removed mood from top of the note, left it in journal
        # part", 2026-09-12). An old note's Mood:/Day: lines are dropped here,
        # and the readers fall back to them while they still exist.
        tail = [x for x in [w_line] + q_lines if x]
        if tail:
            out += tail + ["---"]
    if doc.lead != out:
        doc.lead = out
        return True
    return False


# ── mint ─────────────────────────────────────────────────────────────────────
def _ensure_tags():
    """Real tag entities before any note write (v1 writes don't create
    tags). Lazy-mint path needs this too."""
    try:
        from dispatch import _ensure_tags_exist
        _ensure_tags_exist(list(pm.TIER_TAGS.values()) + [pm.TAG_PARENT],
                           parents={t.lower(): pm.TAG_PARENT
                                    for t in pm.TIER_TAGS.values()})
    except Exception as e:
        _log(f"ensure_tags: {e}")


def create_note(p, index):
    """Idempotent create: caller looked up first. Renders the tier template,
    tags with the family, feeds the fresh task back into the index so same-run
    siblings can link to it."""
    _ensure_tags()
    tpl = _load_template(p.kind)
    content = pm.render_template(tpl, {
        "breadcrumbs": _crumb(p, index),
        "daylinks": "\n".join(_day_links(p, index)),
        "weeklinks": "\n".join(_week_links(p, index)),
    })
    # Child tag ONLY - TickTick's group-by-tag prefers the PARENT when both
    # are attached, which would collapse the kanban into one 💫Periodic
    # column. The parent exists as the tree node, never on tasks.
    task = _api().create_task(
        title=pm.long_title(p), project_id=areas.PERIODIC_LIST_ID,
        content=content, kind="NOTE",
        tags=[pm.tag(p)])
    index[(p.kind, pm.title_key(p))] = task
    _log(f"minted {p.kind} {pm.title(p)} ({task.get('id')})")
    return task


def ensure_note(p, index=None):
    """(task, minted_bool) - lazy-mint net: every open/append path lands here."""
    with _flock():
        index = index if index is not None else build_index()
        hit = lookup(index, p)
        if hit:
            return hit, False
        return create_note(p, index), True


# ── data sources ─────────────────────────────────────────────────────────────
def _today():
    return date.today()


def _scheduled_today(day):
    """Open tasks scheduled on `day` from the all_tasks cache (hourly-synced;
    fresh installs pre-sync just render an empty Today). Excludes NOTE-kind
    and the periodic list itself."""
    iso = day.isoformat()
    out = []
    for t in (cache_store.get("all_tasks") or []):
        pid = t.get("projectId") or t.get("_projectId") or ""
        if pid == areas.PERIODIC_LIST_ID or t.get("kind") == "NOTE":
            continue
        when = t.get("startDate") or t.get("dueDate") or ""
        if when and utc_str_to_local_date(when) == iso:
            # the clock rides INSIDE the label; a time after the link would
            # cost the line the task id the parser reads off its end
            hm = pm.clock(when, t.get("isAllDay"))
            out.append((pid, t.get("id"),
                        pm.timed_title(t.get("title") or "Task", hm), hm))
    out.sort(key=lambda r: r[3] or "99:99")      # by the hour, untimed last
    return [(pid, tid, title) for pid, tid, title, _hm in out]


_COMPLETED = None      # [(local_date_str, task)] - one v2 call per process


def _completed_batch():
    """One get_completed(days=15) client-filtered later into windows (the
    method has no from/to params). None = no v2 token / call failed -
    consumers drop their lines (never fake zeros)."""
    global _COMPLETED
    if _COMPLETED is not None:
        return _COMPLETED
    try:
        from api_v2 import TickTickV2
        rows = TickTickV2().get_completed(days=15, limit=500)
        _COMPLETED = [(utc_str_to_local_date(t.get("completedTime") or ""), t)
                      for t in (rows or [])]
    except Exception as e:
        _log(f"completed_batch: {e}")
        _COMPLETED = None
    return _COMPLETED


def _completed_between(d0, d1):
    batch = _completed_batch()
    if batch is None:
        return None
    a, b = d0.isoformat(), d1.isoformat()
    return [t for ds, t in batch if a <= ds <= b]


def _wontdo_between(d0, d1):
    rows = cache_store.get("wontdo_tasks")
    if rows is None:
        return None
    a, b = d0.isoformat(), d1.isoformat()
    return [t for t in rows
            if a <= utc_str_to_local_date(t.get("completedTime") or "") <= b]


def _day_sums(index):
    """{date: money-sum} from every daily note's 💰 section in the index."""
    sums = {}
    for (kind, key), t in index.items():
        if kind != "daily":
            continue
        d = pm.parse_daily_title(t.get("title") or "") or pm.parse_daily_title(key)
        if not d:
            continue
        doc = ps.parse_sections(t.get("content") or "")
        ans = _answer_in(doc, pm.SEC_EVENING, "money did you earn")
        amt = pm.parse_money_answer(ans) if ans else None
        if amt is not None:
            sums[d] = amt
            continue
        sec = ps.find(doc, pm.SEC_MONEY)      # notes from before the move
        if sec:
            sums[d] = pm.section_money_sum(sec.body)
    return sums


def _dailies_between(index, d0, d1):
    out = []
    for (kind, key), t in index.items():
        if kind != "daily":
            continue
        d = pm.parse_daily_title(key)
        if d and d0 <= d <= d1:
            out.append((d, t))
    return sorted(out)


def _day_mood_of(task):
    """A daily task → (score, note) | None. Lead Mood: line first,
    legacy 💬 section then 📓 Notes 😊 entry for older notes."""
    doc = ps.parse_sections(task.get("content") or "")
    msec = ps.find(doc, pm.SEC_MORNING)          # its own question owns it now
    if msec is not None:
        for _n, q, a, _i in pm.journal_pairs(msec.body):
            if a and "mood" in (q or "").casefold():
                hit = pm.answer_mood(a)
                if hit:
                    return hit
    mood = pm.quote_mood(doc.lead)
    if mood:
        return mood
    qsec = ps.find(doc, pm.LEGACY_QUOTE)
    mood = pm.quote_mood(qsec.body) if qsec else None
    if mood:
        return mood
    nsec = ps.find(doc, pm.SEC_NOTES)
    return pm.day_mood(nsec.body) if nsec else None


def _mood_by_day(index, d0, d1):
    """[(date, (score, note))] for dailies in the window that have a mood."""
    out = []
    for d, t in _dailies_between(index, d0, d1):
        mood = _day_mood_of(t)
        if mood:
            out.append((d, mood))
    return out


def _mood_avg(index, d0, d1):
    scores = [m[0] for _d, m in _mood_by_day(index, d0, d1)]
    return (sum(scores) / len(scores)) if scores else None


def _entries_between(index, d0, d1):
    """[(date, hm, glyph, body)] harvested from the dailies' 📓 Notes."""
    out = []
    for d, t in _dailies_between(index, d0, d1):
        doc = ps.parse_sections(t.get("content") or "")
        nsec = ps.find(doc, pm.SEC_NOTES)
        for hm, glyph, body in (pm.harvest_entries(nsec.body) if nsec else []):
            out.append((d, hm, glyph, body))
    return out


def _fill_day_highlight(doc):
    """✨ Highlight - a MIRROR of the evening journal's answer, the same way
    Mood, Day and Money are (Vex 2026-09-12: the answer is the record). It
    sits at the top because that is where he reads it (2026-09-17), not
    because anything is stored there; clearing the answer clears the line.

    Shared with the retro writer, which runs it in the SAME write as the
    answer: nothing can refresh an arbitrary past daily note, so a mirror
    left for "the next refresh" would never happen on the days this matters.
    """
    hl = _answer_in(doc, pm.SEC_EVENING, "highlight of the day")
    # an EMPTIED answer clears the line, which is what the contract above says
    # and what the code did not do: skipping set_body left yesterday's ✨
    # standing over a blank answer, permanently on a past note nothing can
    # refresh (found by review 2026-09-17)
    return ps.set_body(doc, pm.SEC_HIGHLIGHT,
                       [f"- ✨ {mdtext.flatten_links(hl)}"] if hl else [])


def _highlights_between(index, d0, d1):
    """[(date, text)] - each day's ✨ highlight, from its evening journal
    answer, oldest day last. Vex 2026-09-17 wanted the week to carry them
    "by day" above the entries."""
    out = []
    for d, t in _dailies_between(index, d0, d1):
        doc = ps.parse_sections(t.get("content") or "")
        hl = _answer_in(doc, pm.SEC_EVENING, "highlight of the day")
        if hl and hl.strip():
            out.append((d, mdtext.flatten_links(hl).strip()))
    return out


def _created_between(d0, d1):
    """Created-in-window tasks (approximation: open cache + completed batch,
    deduped by id)."""
    a, b = d0.isoformat(), d1.isoformat()
    seen = set()
    pool = list(cache_store.get("all_tasks") or [])
    pool += [t for _ds, t in (_completed_batch() or [])]
    out = []
    for t in pool:
        tid = t.get("id")
        if tid in seen:
            continue
        seen.add(tid)
        if a <= utc_str_to_local_date(t.get("createdTime") or "") <= b:
            out.append(t)
    return out


def _tier2():
    """Optional Tier-2 fetcher module - absent/broken = sections untouched."""
    try:
        import periodic_fetch
        return periodic_fetch
    except Exception:
        return None


# ── sweep (✅ Today → real completions) ──────────────────────────────────────
SWEPT_FILE = run_path("tickal_pn_swept.json")


def _swept_load():
    """{note_date_iso: [tids]} - the per-day swept ledger. Checked lines stay
    in the note as the day's record (never pruned), so WITHOUT this ledger
    every refresh would re-POST the same completions all day."""
    try:
        with open(SWEPT_FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _ledger_expired(key, horizon):
    """Date-aware prune: daily keys by their date, weekly keys by their
    week's END + grace (a raw string compare dropped '2026-W53'
    mid-window once the horizon rolled into 2027)."""
    m = re.match(r"^(\d{4})-W(\d{2})$", key)
    if m:
        try:
            monday = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return True
        return monday + timedelta(days=8) < horizon
    try:
        return date.fromisoformat(key) < horizon
    except ValueError:
        return True


def _swept_add(key, tids):
    d = _swept_load()
    horizon = date.today() - timedelta(days=2)
    d = {k: v for k, v in d.items() if not _ledger_expired(k, horizon)}
    d[key] = sorted(set(d.get(key, [])) | set(tids))
    try:
        with open(SWEPT_FILE, "w") as f:
            json.dump(d, f)
    except Exception:
        pass


def _sweep_due(pairs, line_day):
    """(due_pairs, already_done_tids): one LIVE read per ticked task, judged
    by pm.sweep_verdict. A task that cannot be read is neither completed nor
    recorded - it is simply tried again on the next refresh."""
    api = _api()
    due, already = [], []
    for pid, tid in pairs:
        try:
            live = api.get_task(pid, tid)
        except Exception as e:
            _log(f"sweep read {tid[:8]}: {e}")
            continue
        if pm.sweep_verdict(live, line_day[tid], utc_str_to_local_date) == "done":
            already.append(tid)
            _log(f"sweep skip {tid[:8]}: already done for {line_day[tid]}")
        else:
            due.append((pid, tid))
    return due, already


def _complete_many(pairs):
    """Pooled completer over ALL [(pid, tid)] - the _sweep_from_doc pattern
    (max 4 workers, no truncation). Returns (done_tids, failed_tids)."""
    if not pairs:
        return [], []
    api = _api()
    done, failed = [], []

    def work(pair):
        pid, tid = pair
        try:
            api.complete_task(pid, tid)
            done.append(tid)
        except Exception as e:
            failed.append(tid)
            _log(f"sweep complete {tid[:8]}: {e}")

    with ThreadPoolExecutor(max_workers=min(4, len(pairs))) as ex:
        list(ex.map(work, pairs))
    if done:
        try:
            done_set = set(done)
            cached = cache_store.get("all_tasks")
            if cached is not None:
                cache_store.set("all_tasks",
                                [t for t in cached if t.get("id") not in done_set])
            from dispatch import _patch_project_data
            for pid, tid in pairs:
                if tid in done_set:
                    _patch_project_data(tid, pid_old=pid, remove=True)
        except Exception:
            cache_store.invalidate("all_tasks")
    return done, failed


# ── refresh pipelines ────────────────────────────────────────────────────────
# Sweepable checkbox sections per tier (⏩ Tomorrow and the ♻️ review
# mirror sweep exactly like ✅ Today - tick anywhere, real task completes).
_SWEEP_SECTIONS = {"daily": (pm.SEC_TODAY, pm.SEC_TOMORROW),
                   "weekly": (pm.SEC_REVIEW,),
                   "monthly": (pm.SEC_MREVIEW,)}


def refresh_period(p, index=None, force=False):
    """Refresh a note's generated sections. Note-date-anchored: live
    fillers run only while the period is current (+1 day of grace so the
    closing pass seals final numbers); historical notes get breadcrumb
    self-heal + money re-total only. Returns a short summary string."""
    index = index if index is not None else build_index()
    task = lookup(index, p)
    if not task:
        return "missing"
    pid = task.get("projectId") or areas.PERIODIC_LIST_ID
    tid = task.get("id")
    today = _today()
    notes_swept = []

    def mutate(doc, live):
        # step 0: complete checked+linked boxes BEFORE any merge; the
        # merges then dedupe against ALL lines so nothing re-enters unchecked.
        # Window = the period + one day of grace (late-night ticks survive the
        # rollover via mint_ahead's closing-period refresh); the swept ledger
        # stops re-POSTing the same completions on every refresh (checked
        # lines stay in the note as the record by design).
        if p.start <= today <= p.end + timedelta(days=1):
            key = pm.title_key(p)
            ledger = set(_swept_load().get(key, []))
            pairs, line_day = [], {}
            for sec_name in _SWEEP_SECTIONS.get(p.kind, ()):
                sec = ps.find(doc, sec_name)
                if sec:
                    # the day a ticked line stands for: ⏩ Tomorrow's lines
                    # are the NEXT day's occurrence, everything else the note's
                    d = (p.start + timedelta(days=1)
                         if sec_name == pm.SEC_TOMORROW else
                         (p.start if p.kind == "daily" else p.end))
                    for pp, tt in pm.checked_linked(sec.body):
                        if tt not in ledger:
                            pairs.append((pp, tt))
                            line_day.setdefault(tt, d)
            pairs = list(dict.fromkeys(pairs))
            # never complete blind: an occurrence already finished elsewhere
            # (a repeating task's id is still open, pointing at TOMORROW) is
            # recorded, not completed again - see pm.sweep_verdict
            due, already = _sweep_due(pairs, line_day)
            if already:
                _swept_add(key, already)
            if due:
                done, failed = _complete_many(due)
                if done:
                    _swept_add(key, done)
                notes_swept.append((len(done), len(failed)))
        # lead (crumb/nav/weather/quote/mood) is engine-owned on LIVE notes;
        # historical notes only get their breadcrumb healed (a sealed note's
        # quote is its record)
        if p.start <= today <= p.end + timedelta(days=1):
            _compose_lead(doc, p, index,
                          refetch=(p.kind == "daily" and p.start == today))
        else:
            pm.set_breadcrumb(doc, _crumb(p, index))
            # a sealed week's day links heal like the crumb above them, but
            # only where the block already is: inserting one would RESHAPE a
            # frozen note, and that is the opt-in tool's job, not a refresh's
            if any(pm.DAY_LINK_RE.match(l) for l in doc.lead):
                pm.set_day_links(doc, _day_links(p, index))
        # divider hygiene (--- hugs content - no blank lines around
        # separators): decor pre-lines lose stray blanks, and a body followed
        # by decor loses its trailing blanks
        for i, sec in enumerate(doc.sections):
            if sec.pre:
                sec.pre = [l for l in sec.pre if l.strip()]
                prevb = doc.sections[i - 1].body if i else doc.lead
                while prevb and not prevb[-1].strip():
                    prevb.pop()
        if p.kind == "daily":
            _fill_daily(doc, p, index, p.start == today)
        elif p.kind == "weekly":
            _fill_weekly(doc, p, index)
        elif p.kind == "monthly":
            _fill_monthly(doc, p, index)
            # the old skeleton's 💰 Money section, for a note the layout
            # guard left alone - harmless on a new one, which has no such
            # section and whose 💰 Income _fill_monthly just wrote
            _fill_rollup_money(doc, p, index)
        else:
            _fill_rollup_money(doc, p, index)
        return True

    _res, doc_out = _pn_rmw(pid, tid, mutate)
    # refresh mutates content → patch the index copy in place, or same-run
    # consumers (roll-ups, mirrors) read stale bodies (no extra API call)
    task["content"] = ps.serialize_sections(doc_out)
    swept = notes_swept[0] if notes_swept else (0, 0)
    return f"refreshed{f' · swept {swept[0]}' if swept[0] else ''}"


def _completed_tops(day):
    """Yesterday's/today's completions worth naming: top-level tasks only
    (a subtask is its parent's detail), deduped by title. A repeating task
    leaves one completion record per occurrence and testing can leave more -
    "I cannot complete the same recurring task twice that day" (Vex
    2026-09-12). None when the completed feed is unreadable."""
    comp = _completed_between(day, day)
    if comp is None:
        return None
    out, seen = [], set()
    for t in sorted(comp, key=lambda x: x.get("completedTime") or ""):
        if t.get("parentId"):
            continue
        name = mdtext.flatten_links(t.get("title") or "").strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _answer_in(doc, sec_name, needle):
    """The answer to the journal question containing `needle`, or ''."""
    sec = ps.find(doc, sec_name)
    if sec is None:
        return ""
    for _n, q, a, _i in pm.journal_pairs(sec.body):
        if a and needle.casefold() in (q or "").casefold():
            return a.strip()
    return ""


def _mood_of_doc(doc):
    """(score, note) from a parsed daily note's morning journal, or None."""
    msec = ps.find(doc, pm.SEC_MORNING)
    if msec is None:
        return None
    for _n, q, a, _i in pm.journal_pairs(msec.body):
        if a and "mood" in (q or "").casefold():
            hit = pm.answer_mood(a)
            if hit:
                return hit
    return None


def _weekly_highlight_of(wdoc):
    """A weekly note's ✨ highlight: the section where one survives, else the
    weekly journal's first ANSWER (which is the record since 2026-09-17 - the
    section was only ever its copy). '' when neither says anything."""
    hsec = ps.find(wdoc, pm.SEC_HIGHLIGHT)
    if hsec is not None:
        # a divider can sit in the last section's body (decor only migrates
        # when a NEXT section exists) - never let it through
        parts = [ln.strip().lstrip("-").strip() for ln in hsec.body
                 if ln.strip() and not ps.DECOR_RE.match(ln.strip())
                 and not pm.PENDING_RE.match(ln.strip())]
        hit = " ".join(x for x in parts if x)
        if hit:
            return hit
    return _answer_in(wdoc, pm.SEC_WEEKLY_JNL, "highlight of the week")


def _otd_memories(day, index):
    """[(date, url, stars, mood, wins, highlight)] for this date in every
    earlier year that has a daily note, newest first. Daily notes only exist
    once opened, so the first real memory is a year after the earliest note
    (2026-07-11 -> 2027-07-11); until then this returns []."""
    years = [d.year for (k, key) in index if k == "daily"
             for d in [pm.parse_daily_title(key)] if d]
    out = []
    if not years:
        return out
    for back in range(1, day.year - min(years) + 1):
        d = pm.same_day_back(day, back)
        t = lookup(index, pm.period_for("daily", d)) if d else None
        if not t:
            continue
        doc = ps.parse_sections(t.get("content") or "")
        stars = pm.answer_stars(_answer_in(doc, pm.SEC_EVENING, "rate the day"))
        mood = _mood_of_doc(doc)
        nsec = ps.find(doc, pm.SEC_NOTES)
        wins = [mdtext.flatten_links(b).strip()
                for _hm, g, b in (pm.harvest_entries(nsec.body) if nsec else [])
                if g == "🟢"]
        hl = ""
        wk = lookup(index, pm.period_for("weekly", d))
        if wk:
            wdoc = ps.parse_sections(wk.get("content") or "")
            hl = _weekly_highlight_of(wdoc)
        out.append((d, _note_url(t), stars,
                    pm.mood_text(mood[0], mood[1]) if mood else "",
                    wins, mdtext.flatten_links(hl)))
    return out


def _day_money(doc):
    """A daily note's money for the day → float | None. The evening journal
    answer, then a legacy 💰 section."""
    if doc is None:
        return None
    ans = _answer_in(doc, pm.SEC_EVENING, "money did you earn")
    amt = pm.parse_money_answer(ans) if ans else None
    if amt is not None:
        return amt
    msec = ps.find(doc, pm.SEC_MONEY)
    if msec is None or not any(pm.parse_money_entry(l) for l in msec.body):
        # an EMPTY legacy section is "not answered", not "earned 0" - read as
        # 0 it drew "Money: 0 ▼ 120" for a day the question was left blank
        return None
    return pm.section_money_sum(msec.body)


def _people_logged(day):
    """[(name, text)] for every person card whose Log has an entry stamped
    `day` - the 👥 side of the house showing up in the daily note (Vex
    2026-09-12: "if there is people log that day, it should show in summary").
    Newest first, silent when nothing was logged."""
    try:
        import people as _pe
        if not areas.people_configured():
            return []
    except Exception:
        return []
    stamp = day.strftime("%Y-%m-%d")
    out = []
    for t in (cache_store.get("all_tasks") or []):
        if (t.get("_projectId") or t.get("projectId")) != areas.PEOPLE_ID:
            continue
        title = t.get("title", "")
        if not _pe.is_person(title) or _pe.is_archive(title):
            continue
        name = _pe.person_name(title)
        for text, ts in _pe.log_entries(t.get("content") or ""):
            if (ts or "").startswith(stamp):
                out.append((ts, name, mdtext.flatten_links(text)))
    out.sort(reverse=True)
    return [(n, tx) for _ts, n, tx in out]


def _recap_lines(day, t2, nday, tab, pday=None, pdoc=None, extra=None):
    """Day · Mood · Money · Focus · Completed, in Vex's order (2026-09-12),
    each carrying a compact ▲/▼ against the day before it (Vex, same day:
    "small indicator compared to the day before?").

    The first three are EVENING/MORNING JOURNAL answers - the rating and the
    money are asked there, so the summary reflects them rather than keeping a
    second copy ("it is an answer in the evening journal, that is all that
    should be there"). Each line appears only when its data really exists, and
    its arrow only when the day before has the same number to compare with -
    so a blank yesterday costs you the arrow, never the line.

    `nday` is the day's parsed note; `pday`/`pdoc` are the comparison day and
    its note.
    """
    def dc(cur, prev, kind="count"):
        c = pm.delta_chip(cur, prev, kind)
        return f"  {c}" if c else ""

    lines = []
    if nday is not None:
        stars = pm.answer_stars(_answer_in(nday, pm.SEC_EVENING, "rate the day"))
        if stars:
            pst = (pm.answer_stars(_answer_in(pdoc, pm.SEC_EVENING, "rate the day"))
                   if pdoc is not None else "")
            lines.append(f"{tab}- Day: {stars}" + dc(len(stars), len(pst) or None))
        mood = _mood_of_doc(nday)
        if mood:
            pmood = _mood_of_doc(pdoc) if pdoc is not None else None
            lines.append(f"{tab}- Mood: {pm.mood_text(mood[0], mood[1])}"
                         + dc(mood[0], pmood[0] if pmood else None))
        # ALWAYS a line, 0 until the evening journal answers (Vex 2026-09-13:
        # "Money was not in the summary"). The arrow still needs both days.
        money = _day_money(nday)
        pmoney = _day_money(pdoc) if pdoc is not None else None
        lines.append(f"{tab}- Money: {pm.fmt_amount(money or 0)}"
                     + (dc(money, pmoney, "money")
                        if money is not None and pmoney is not None else ""))
    fm = getattr(t2, "focus_minutes", lambda a, b: None)(day, day) if t2 else None
    if fm:
        pfm = (getattr(t2, "focus_minutes", lambda a, b: None)(pday, pday)
               if (t2 and pday) else None)
        lines.append(f"{tab}- Focus: {pm.fmt_hm(fm)}" + dc(fm, pfm or None, "duration"))
    # the caller's own count lines (Won't do, Entries) sit here, above People
    lines += list(extra or [])
    plog = _people_logged(day)
    if plog:
        lines.append(f"{tab}- People: {len(plog)}")
        lines += [f"{tab}\t- {nm}" + (f" · {tx[:48]}" if tx else "")
                  for nm, tx in plog[:5]]
        if len(plog) > 5:
            lines.append(f"{tab}\t- _(+{len(plog) - 5} more)_")
    # 🚨 Completed goes LAST and nothing may be appended after it (Vex
    # 2026-09-12: "always keep completed tasks as last bullet point because it
    # is longest"). Anything new belongs in `extra` or beside People above.
    tops = _completed_tops(day)
    if tops is not None:
        ptops = _completed_tops(pday) if pday else None
        lines.append(f"{tab}- Completed: {len(tops)}"
                     + dc(len(tops), len(ptops) if ptops is not None else None))
        lines += [f"{tab}\t- {n[:64]}" for n in tops[:10]]
        if len(tops) > 10:
            lines.append(f"{tab}\t- _(+{len(tops) - 10} more)_")
    return lines


def _sync_ticks(doc, p, day):
    """Tick the ✅ Tasks / ⏩ Tomorrow lines whose task was completed in
    TickTick (Vex 2026-09-13: ticking a line completed the task, but
    completing the task never ticked the line, "even when I refresh").

    Every line ticked here goes into the sweep's ledger at once: it is done,
    and the ledger is what keeps the sweep from ever completing it again -
    so reopening that task in TickTick later is never undone by the note.
    Nothing is unticked. No completed feed (no v2 token, offline) = no
    change, never a guess."""
    comp = _completed_between(day - timedelta(days=1), day + timedelta(days=1))
    if comp is None:
        return
    ticked = []
    for sec_name, line_day in ((pm.SEC_TODAY, day),
                               (pm.SEC_TOMORROW, day + timedelta(days=1))):
        sec = ps.find(doc, sec_name)
        if sec is None:
            continue
        done = pm.done_tids_for(comp, line_day, utc_str_to_local_date)
        body, hit = pm.tick_lines(list(sec.body), done)
        if hit:
            ps.set_sec_body(doc, sec, body)
            ticked += hit
    if ticked:
        _swept_add(pm.title_key(p), ticked)


def _bridge_text(day):
    """The daily bridge saved FOR `day` (the "D • Bridge 🌉 YYYY/MM/DD" note
    in the Bridges list), or "" - from the cache, which the bridge save
    patches the moment it writes."""
    try:
        import bridges as br
        if not areas.bridges_configured():
            return ""
        want = br.daily_title(day)
        for key in ("all_notes", "all_tasks"):
            for t in (cache_store.get(key) or []):
                if (t.get("title") == want and
                        (t.get("_projectId") or t.get("projectId")) == areas.BRIDGES_ID):
                    return (t.get("content") or "").strip()
    except Exception:
        pass
    return ""


def bridge_quote(text):
    """Bridge text as the note shows it: every line a > quote (Vex's layout,
    2026-09-12/13). Blank lines stay blank so paragraphs survive."""
    return [f"> {ln.strip()}" if ln.strip() else ""
            for ln in (text or "").strip().splitlines()]


def _fill_daily(doc, p, index, is_today):
    day = p.start
    # 🌉 Yesterday's bridge - READ from the bridge saved yesterday, at the
    # top of the note. It used to be PUSHED in at save time, which created
    # tomorrow's note a day early from whatever template existed then; that
    # note then kept that old layout for good (2026-09-13's note was minted
    # at 17:35 the day before, two hours before the layout changed).
    btxt = _bridge_text(day - timedelta(days=1))
    if btxt:
        ps.set_body(doc, pm.SEC_YBRIDGE, bridge_quote(btxt))
    # ✨ Highlight - a MIRROR of the evening journal's answer, the same way
    # Mood, Day and Money are (Vex 2026-09-12: the answer is the record). It
    # sits at the top because that is where he reads it (2026-09-17), not
    # because anything is stored there; clearing the answer clears the line.
    _fill_day_highlight(doc)
    # 🎯 Week goals mirror - verbatim copy; absent/empty weekly keeps the
    # template pointer line (bootstrap window)
    wk = lookup(index, pm.period_for("weekly", day))
    if wk:
        wdoc = ps.parse_sections(wk.get("content") or "")
        goals, gsec = _week_goals_of(wdoc)
        if goals:
            ps.set_body(doc, pm.SEC_WEEK_GOALS, goals)
        elif gsec is not None:
            # weekly goals CLEARED → mirror resets to the pointer, never
            # keeps stale copies
            ps.set_body(doc, pm.SEC_WEEK_GOALS,
                        [f"{pm.T1}- _(mirrors this week's weekly note - "
                         "edit goals there)_"])

    if is_today:
        t2 = _tier2()
        if t2:
            cd = getattr(t2, "countdown_lines", lambda: None)()
            if cd:
                ps.set_body(doc, pm.SEC_COUNTDOWNS, pm.ind(cd))
            hb = getattr(t2, "habit_lines_daily", lambda: None)()
            if hb:
                ps.set_body(doc, pm.SEC_HABITS, pm.ind(hb))

        # ⏪ Yesterday recap - Day · Mood · Money · Focus · Completed
        yd = day - timedelta(days=1)
        yt = lookup(index, pm.period_for("daily", yd))
        ydoc = ps.parse_sections(yt.get("content") or "") if yt else None
        yd2 = yd - timedelta(days=1)
        y2t = lookup(index, pm.period_for("daily", yd2))
        y2doc = ps.parse_sections(y2t.get("content") or "") if y2t else None
        wd = _wontdo_between(yd, yd)
        yextra = ([f"{pm.T2}- Won't do: {len(wd)}"]
                  if wd is not None and len(wd) else [])
        lines = _recap_lines(yd, t2, ydoc, pm.T2, pday=yd2, pdoc=y2doc,
                             extra=yextra)
        ps.set_body(doc, pm.SEC_YESTERDAY, lines or [f"{pm.T1}_(no data)_"])

        # ✅ Tasks merge (sweep already ran in step 0)
        sec = ps.find(doc, pm.SEC_TODAY)
        if sec is not None:
            body = [ln for ln in sec.body if not pm.PENDING_RE.match(ln.strip())]
            merged, _added = pm.merge_checkboxes(body, _scheduled_today(day),
                                                 indent=pm.T2)
            ps.set_body(doc, pm.SEC_TODAY, pm.sort_checkboxes(merged))

        # ⏩ Tomorrow - same checkbox links, tomorrow's schedule
        tmw = ps.find(doc, pm.SEC_TOMORROW)
        if tmw is not None:
            body = [ln for ln in tmw.body if not pm.PENDING_RE.match(ln.strip())]
            merged, _added = pm.merge_checkboxes(
                body, _scheduled_today(day + timedelta(days=1)), indent=pm.T2)
            ps.set_body(doc, pm.SEC_TOMORROW, pm.sort_checkboxes(merged))

        # ☑️ ticks follow TickTick: a task completed anywhere shows ticked here
        _sync_ticks(doc, p, day)

        # 📊 Today summary - the SAME shape as ⏪ Yesterday (Vex 2026-09-12)
        nsec = ps.find(doc, pm.SEC_NOTES)
        entries = pm.harvest_entries(nsec.body) if nsec else []
        textra = []
        if entries:
            counts = {}
            for _hm, g, _b in entries:
                counts[g] = counts.get(g, 0) + 1
            detail = " · ".join(f"{n} {g}" for g, n in counts.items())
            textra.append(f"{pm.T2}- Entries: {len(entries)} ({detail})")
        sums = _recap_lines(day, t2, doc, pm.T2, pday=yd, pdoc=ydoc,
                            extra=textra)
        ps.set_body(doc, pm.SEC_DAY_SUM, sums or [f"{pm.T1}_(no data)_"])

        # 🌅/🌙 journal Q lines seed at refresh (never-empty sections,
        # phone-answerable); unanswered fixed prompts refresh their text so
        # the evening 'did you achieve {goal}' bakes in a goal set at noon
        _seed_daily_journals(doc, day)

    # 🕰️ On this day - any daily note, not just today's: opening an old note
    # shows ITS memories. Looked up only when the section is there (deleting
    # it is the kill switch, like every other section).
    if ps.find(doc, pm.SEC_OTD) is not None:
        ps.set_body(doc, pm.SEC_OTD, pm.otd_lines(_otd_memories(day, index)))

    # 💰 re-total ALWAYS (historical dailies included)
    msec = ps.find(doc, pm.SEC_MONEY)
    if msec is not None:
        ps.set_body(doc, pm.SEC_MONEY, pm.recompute_money_body(msec.body))


def _refresh_fixed_q(sec, fixed):
    """Rewrite UNANSWERED fixed-prompt Q lines to their current text (dynamic
    prompts bake in live goal text). Answered ones are frozen history; the
    Q line's own indentation survives.

    Matched BY KEY, never by position: rewriting "Q2" to whatever the current
    list's second question is would turn an older note's "What is on your
    mind?" into the goal question the day one was inserted."""
    by_key = {k: q for k, q in fixed if k != "free"}
    body = list(sec.body)
    changed = False
    for n, q, a, a_idx in pm.journal_pairs(body):
        key = pm.journal_key(q)
        if a or key not in by_key:
            continue
        raw = body[a_idx - 1]
        ws = raw[:len(raw) - len(raw.lstrip())] or pm.T1
        want = pm.journal_q_line(n, by_key[key], ws)
        if raw != want:
            body[a_idx - 1] = want
            changed = True
    if changed:
        sec.body = body


def _canon_journal_indent(sec):
    """Normalize journal nesting: every Q line at T1, every A line at
    T2 - answers keep their text, only the leading whitespace converges (old
    flat-seeded notes + phone-typed answers drift otherwise)."""
    out, changed = [], False
    for ln in sec.body:
        q = pm.JOURNAL_Q_RE.match(ln)
        if q:
            want = pm.journal_q_line(int(q.group("n")), q.group("q"))
            changed |= (want != ln)
            out.append(want)
            continue
        a = pm.JOURNAL_A_RE.match(ln)
        if a and ln.strip().startswith("A:"):
            want = f"{pm.T2}A: " + a.group("a")
            changed |= (want != ln)
            out.append(want)
            continue
        out.append(ln)
    if changed:
        sec.body = out


def _seed_slot(doc, sec_name, slot, d, ctx, insert=False):
    """Seed a journal section that has no questions; otherwise refresh the
    unanswered fixed questions' text. insert=True (the journal being RUN,
    never a background refresh) also gives an older journal any fixed
    question it predates - tonight's note got the 🎯 tomorrow question the
    day it was added (Vex 2026-09-15) without rewriting a past note."""
    sec = ps.find(doc, sec_name)
    if sec is None:
        return
    fixed = pm.journal_fixed(slot, ctx)
    if not any(pm.JOURNAL_Q_RE.match(ln) for ln in sec.body):
        prompts = ([q for _k, q in fixed]
                   + pm.select_prompts(pj.load_pool(slot), d, slot))
        sec.body = [ln for ln in sec.body if not pm.PENDING_RE.match(ln.strip())]
        ps.append_body(doc, sec_name, pm.seed_journal_lines(prompts))
    else:
        if insert:
            body, added = pm.insert_fixed_questions(sec.body, fixed)
            if added:
                sec.body = body
        _refresh_fixed_q(sec, fixed)
    _canon_journal_indent(sec)


def _seed_daily_journals(doc, day):
    # the SAME ctx the journal run builds, bridge echo included: a morning
    # seeded here without it had the echo inserted (and every question
    # renumbered) on each morning's first run (review 2026-09-15)
    _seed_slot(doc, pm.SEC_MORNING, "morning", day, journal_ctx("morning", doc))
    _seed_slot(doc, pm.SEC_EVENING, "evening", day, journal_ctx("evening", doc))


def _by_proj(tasks, projects):
    out = {}
    for t in (tasks or []):
        name = projects.get(t.get("projectId") or t.get("_projectId"), "Inbox")
        out[name] = out.get(name, 0) + 1
    return out


def _set_headed(doc, prefix, data, body_lines=None, within=None):
    """Data-in-header subsection: find by prefix, rewrite the header to
    '### <prefix>: <data>' (bare prefix when data is None) and optionally the
    body. Missing section = kill switch, skip."""
    sec = ps.find_prefix(doc, prefix, within)
    if sec is None:
        return
    ps.set_header(sec, f"{prefix}: {data}" if data else prefix)
    if body_lines is not None:
        ps.set_sec_body(doc, sec, body_lines)


def _stats_ignored_pids():
    """Lists whose traffic is pure routine and drowns the week's rankings
    (Vex 2026-09-17: "Start up and shutdown are always gonna appear as top
    tasks of the week since they are done 7 days a week. We do not need to
    see that").

    RANKINGS ONLY. The headline numbers stay whole - "Completed: 78" still
    means 78, still compares against a sealed note and still agrees with the
    daily summaries. Hiding the routines from the count would have made this
    week's total incomparable with every week already written."""
    ids = set()
    try:
        import routines as rt
        ids.add(rt.ROUTINES_LIST)
    except Exception:
        pass
    ids |= {x.strip() for x in
            (os.environ.get("stats_ignore_lists") or "").split(",") if x.strip()}
    return {i for i in ids if i}


def _drop_ignored(tasks):
    """`tasks` minus the ignored lists' rows (pm.drop_lists is the rule)."""
    return pm.drop_lists(tasks, _stats_ignored_pids())


def _fill_people(doc, t2, days=14, within=None):
    """### 👽 People - birthdays landing inside the window (countdowns)
    + stale cards, worst silence first. Weekly (14d) and monthly (31d)
    share this; a note without the header silently skips (kill switch)."""
    plines = list(getattr(t2, "bday_lines", lambda d=14: None)(days) or []) \
        if t2 else []
    try:
        import people as _pe
        if areas.people_configured():
            stale = []
            for t in (cache_store.get("all_tasks") or []):
                if t.get("status", 0) != 0 \
                        or (t.get("_projectId") or t.get("projectId")) \
                        != areas.PEOPLE_ID \
                        or not _pe.is_person(t.get("title", "")):
                    continue
                ds = _pe.nudge_silent_days(t)
                if _pe.is_stale_task(t):
                    chip = ("never logged" if
                            _pe.last_log_date(t.get("content") or "") is None
                            else f"{ds}d silent")
                    nm = _pe.person_name(t.get("title", ""))
                    stale.append((ds if ds is not None else 10**6,
                                  f"- 🕸️ {nm} · {chip}"))
            stale.sort(key=lambda kv: -kv[0])
            plines += [ln for _k, ln in stale[:6]]
    except Exception:
        pass
    if plines:
        ps.set_body(doc, pm.SEC_PEOPLE, pm.ind(plines), within)


def _fill_weekly(doc, p, index):
    """The 📊 Stats bullets + the 💿 Data bullets + 📔 journal seed +
    ♻️ review mirror + ⏪ Last week. Live while current (+1 closing-grace
    day); older weeklies keep their sealed numbers.

    Every anchor is looked up INSIDE its group header (pm.SECTION_SCOPE):
    since 2026-09-17 the note carries "- Completed:" twice, once for this
    week and once for last."""
    today = _today()
    if not (p.start <= today <= p.end + timedelta(days=1)):
        return
    def _in(anchor):
        return pm.scope_of("weekly", anchor)

    # ALL or NOTHING on the layout. A note minted under an older skeleton has
    # none of the 📊 Stats / 💿 Data bullets, but ⏪ Last week and the journal
    # still resolve - so a refresh would drop this week's new-shaped block
    # beside frozen old-style headers and leave the note looking half
    # rewritten. It sits still instead until tools/pnrepair/relayout_weekly.py
    # rebuilds it, or Monday mints a fresh one on the current template.
    # Tested by ANCHOR rather than by group name: Vex renames headers, and a
    # group he renamed must cost him that group, not the whole note.
    scoped = [a for a in pm.WRITER_ANCHORS["weekly"] if _in(a)]
    if not any(ps.find_prefix(doc, a, _in(a)) is not None for a in scoped):
        _log(f"weekly {pm.title(p)} predates the 2026-09-17 layout - left "
             f"alone (tools/pnrepair/relayout_weekly.py rebuilds it)")
        return

    # ── 🏆 Goals - the two parents mirrored in (Vex 2026-09-17: "under goals
    # … quarter goal, month goal and week goal", the daily's shape one tier
    # up). ♻️ Weekly is HIS - nothing here ever writes it. The month/quarter
    # of a week is its MONDAY's, the breadcrumb's own convention.
    _mirror_goal(doc, pm.SEC_WK_QTR, "quarterly", index, p.start,
                 pm.HINT_WK_QTR)
    _mirror_goal(doc, pm.SEC_WK_MONTH, "monthly", index, p.start,
                 pm.HINT_WK_MONTH)

    t2 = _tier2()
    prev = pm.prev_period(p)
    day_sums = _day_sums(index)
    projects = {pr.get("id"): pr.get("name")
                for pr in (cache_store.get("projects") or [])}
    live_end = min(p.end, today)

    comp_cur = _completed_between(p.start, live_end)
    comp_prev = _completed_between(prev.start, prev.end)
    created_cur = _created_between(p.start, live_end)
    created_prev = _created_between(prev.start, prev.end)

    done_bp = _by_proj(comp_cur, projects)
    created_bp = _by_proj(created_cur, projects)
    # the same two, with the routine lists dropped - RANKINGS read these,
    # headline counts read the ones above (see _stats_ignored_pids)
    rank_done_bp = _by_proj(_drop_ignored(comp_cur), projects)
    rank_created_bp = _by_proj(_drop_ignored(created_cur), projects)

    # ── Top lists / Top tasks - three each, routine lists left out
    tl = pm.top_list_lines(rank_done_bp, rank_created_bp)
    if tl:
        ps.set_body(doc, pm.SEC_TOP_LIST, tl, _in(pm.SEC_TOP_LIST))
    tt = pm.top_task_lines(_drop_ignored(comp_cur))
    if tt:
        ps.set_body(doc, pm.SEC_TOP_TASKS, tt, _in(pm.SEC_TOP_TASKS))

    # ── Created / Completed (header number+chip, 🗂 breakdown body). Created's
    # breakdown is NOT routine-filtered: Vex named Top lists, Top tasks and
    # Completed, and "what I made this week" reads differently from "what I
    # got through".
    head = str(len(created_cur))
    ch = pm.chip(len(created_cur), len(created_prev))
    _set_headed(doc, pm.SEC_CREATED, head + (f" · {ch}" if ch else ""),
                pm.ind([f"- 🗂 {nm} · {c}" for nm, c in
                        sorted(created_bp.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]),
                _in(pm.SEC_CREATED))
    if comp_cur is not None:
        head = str(len(comp_cur))
        ch = pm.chip(len(comp_cur),
                     len(comp_prev) if comp_prev is not None else None)
        _set_headed(doc, pm.SEC_COMPLETED, head + (f" · {ch}" if ch else ""),
                    pm.ind([f"- 🗂 {nm} · {c}" for nm, c in
                            sorted(rank_done_bp.items(),
                                   key=lambda kv: (-kv[1], kv[0]))[:3]]),
                    _in(pm.SEC_COMPLETED))
        # ── Daily Completed - per-day bars off the SAME comp_cur as the
        # headline above, routines included, so the seven bars add up to
        # "Completed: N". (Not the daily notes' own "Completed: n", which
        # counts deduped top-level titles only - a different question.)
        per_day = []
        for i in range(7):
            d = p.start + timedelta(days=i)
            per_day.append((d, sum(1 for t in comp_cur
                                   if utc_str_to_local_date(t.get("completedTime") or "")
                                   == d.isoformat())))
        ps.set_body(doc, pm.SEC_WBARS,
                    pm.ind(pm.done_week_lines(per_day)[:-1]), _in(pm.SEC_WBARS))

    # ── Focus - header total+chip, by-day body, Total bullet
    fbd = getattr(t2, "focus_by_day", lambda a, b: None)(p.start, live_end) if t2 else None
    if fbd is not None:
        total_min = sum(m for m, _t in fbd.values())
        prev_min = getattr(t2, "focus_minutes", lambda a, b: None)(prev.start, prev.end)
        head = pm.fmt_hm(total_min)
        ch = pm.chip(total_min, prev_min, "duration")
        day_lines = []
        for i in range(7):
            d = p.start + timedelta(days=i)
            if d > today:
                break
            rec = fbd.get(d.isoformat())
            if rec and rec[0]:
                ln = f"- {pm.DAY_ABBR[d.weekday()]} · {pm.fmt_hm(rec[0])}"
                if rec[1]:
                    ln += f" · {mdtext.flatten_links(rec[1])[:40]}"
                day_lines.append(ln)
        _set_headed(doc, pm.SEC_FOCUS_WEEK, head + (f" · {ch}" if ch else ""),
                    pm.ind(day_lines)
                    + [f"{pm.T3}- **Total = {pm.fmt_hm(total_min)}**"],
                    _in(pm.SEC_FOCUS_WEEK))

    # ── Habit consistency - Tier-2 hook (each habit against ITS OWN weekly
    # target, and habits with nothing due this week are not listed at all)
    hb = getattr(t2, "habit_lines_weekly", lambda a, b: None)(p.start, p.end) if t2 else None
    # `is not None`, not truthiness: since habits carry their own targets an
    # EMPTY list is a real answer ("nothing was due this week"), and it has to
    # be able to clear a list left behind by an earlier refresh. None is still
    # the unreadable-source case, which leaves the section alone.
    if hb is not None:
        ps.set_body(doc, pm.SEC_HABIT_WEEK, pm.ind(hb), _in(pm.SEC_HABIT_WEEK))

    # ── ✨ Highlights - one line per day that named one, newest first
    hls = _highlights_between(index, p.start, live_end)
    if hls:
        ps.set_body(doc, pm.SEC_HL_WEEK,
                    pm.ind([f"- {pm.DAY_ABBR[d.weekday()]} · {txt}"
                            for d, txt in reversed(hls)]),
                    _in(pm.SEC_HL_WEEK))

    # ── 📨 Entries - wins/nags/thoughts/links, grouped, newest first
    items = _entries_between(index, p.start, live_end)
    if any(it[2] in pm.GROUP_ORDER for it in items):
        ps.set_body(doc, pm.SEC_ENTRIES, pm.entries_grouped(items),
                    _in(pm.SEC_ENTRIES))

    # ── 😊 Moods - average (+ last week) in the header, the day's note as a
    # child bullet
    moods = _mood_by_day(index, p.start, live_end)
    if moods:
        avg = sum(m[0] for _d, m in moods) / len(moods)
        pavg = _mood_avg(index, prev.start, prev.end)
        ch = pm.chip(round(avg, 1),
                     round(pavg, 1) if pavg is not None else None, "avg")
        _set_headed(doc, pm.SEC_MOODS,
                    f"Average {avg:.1f}" + (f" · {ch}" if ch else ""),
                    pm.mood_week_lines(moods), _in(pm.SEC_MOODS))

    # ── 💰 Income - header total+chip, day lines, Total bullet
    inc_cur = pm.sum_in_period(day_sums, p)
    inc_prev = pm.sum_in_period(day_sums, prev)
    head = pm.fmt_amount(inc_cur)
    ch = pm.chip(inc_cur, inc_prev, "money") \
        if any(prev.start <= d <= prev.end for d in day_sums) else None
    _set_headed(doc, pm.SEC_INCOME, head + (f" · {ch}" if ch else ""),
                pm.ind([pm.money_day_line(p.start + timedelta(days=i),
                                          day_sums.get(p.start + timedelta(days=i), 0))
                        for i in range(7)])
                + [pm.money_total_line(inc_cur, 3)],
                _in(pm.SEC_INCOME))

    # ── 👽 People - birthdays inside 14d (countdowns) + stale cards
    _fill_people(doc, t2, days=14, within=_in(pm.SEC_PEOPLE))

    # ── 📔 Weekly journal - seed + dynamic-goal prompt refresh
    goals = "; ".join(pm.goal_titles(_week_goals_of(doc)[0])[:5])
    _seed_slot(doc, pm.SEC_WEEKLY_JNL, "weekly", p.start, {"goals": goals})

    # ── ♻️ Weekly Review mirror (sweep already completed ticked ones)
    _fill_review(doc)

    # ── ⏪ Last week - sealed composite: the five headline numbers first, then
    # the same two rankings this week gets (Vex's 2026-09-17 order), routine
    # lists left out of both for the same reason they are left out above.
    if comp_prev is not None:
        lw = [f"- Completed: {len(comp_prev)}",
              f"- Created: {len(created_prev)}"]
        pf = getattr(t2, "focus_minutes", lambda a, b: None)(prev.start, prev.end) if t2 else None
        if pf:
            lw.append(f"- Focus: {pm.fmt_hm(pf)}")
        pmood = _mood_avg(index, prev.start, prev.end)
        if pmood is not None:
            lw.append(f"- Mood: {pmood:.1f} avg")
        lw.append(f"- Income: {pm.fmt_amount(pm.sum_in_period(day_sums, prev))}")
        prev_done_bp = _by_proj(_drop_ignored(comp_prev), projects)
        top_tasks = pm.top_task_lines(_drop_ignored(comp_prev))
        top_lists = [f"{pm.T1}- 🗂 {nm} · {c}" for nm, c in
                     sorted(prev_done_bp.items(),
                            key=lambda kv: (-kv[1], kv[0]))[:3]]
        if top_tasks or top_lists:
            lw.append("")
        if top_tasks:
            lw += ["- Top Tasks:"] + top_tasks
        if top_lists:
            lw += ["- Top Lists"] + top_lists
        ps.set_body(doc, pm.SEC_LAST_WEEK, lw)


def _fill_review(doc, sec_name=None, rid=None):
    """♻️ Weekly Review - a LIVE mirror of the weekly_review_id source
    (focus-bar semantics, both directions). The sweep (step 0) completes
    ticked boxes; this rebuild then re-pulls the source, so note and source
    converge on every refresh. Check-states of still-open tasks survive via
    the tid map. Unset/unknown id or a failed pull → section untouched."""
    sec = ps.find(doc, sec_name or pm.SEC_REVIEW)
    if sec is None:
        return
    tgt = _review_target(rid)
    if not tgt:
        return
    url, kind, obj = tgt
    prev_checked = {tid for tid, ck in pm.checkbox_tids(sec.body).items() if ck}

    def _box(pid, tid, title):
        ln = fb.make_line(pid, tid, title or "Task").raw
        return ln.replace("- [ ]", "- [x]", 1) if tid in prev_checked else ln

    lines = [f"[♻️ Open the review]({url})"]
    if kind == "list":
        try:
            data = _api().get_project_data(obj.get("id"))
        except Exception as e:
            _log(f"review pull: {e}")
            return
        tasks = [t for t in (data.get("tasks") or []) if t.get("status", 0) == 0]
        cols = [(c.get("id"), c.get("name"))
                for c in (data.get("columns") or []) if c.get("id")]
        groups = {}
        for t in tasks:
            groups.setdefault(t.get("columnId") or "", []).append(t)
        order = [cid for cid, _n in cols if cid in groups]
        order += [k for k in groups if k not in order]
        names = dict(cols)
        for k in order:
            if names.get(k):
                lines += ["", f"**{names[k]}**"]
            for t in sorted(groups[k], key=lambda x: x.get("sortOrder") or 0):
                lines.append(_box(obj.get("id"), t.get("id"), t.get("title")))
    else:                                    # task/note → its open subtasks
        rid = obj.get("id")
        pid = obj.get("projectId") or obj.get("_projectId") or ""
        kids = [t for t in (cache_store.get("all_tasks") or [])
                if t.get("parentId") == rid and t.get("status", 0) == 0]
        for t in sorted(kids, key=lambda x: x.get("sortOrder") or 0):
            lines.append(_box(t.get("projectId") or t.get("_projectId") or pid,
                              t.get("id"), t.get("title")))
    ps.set_body(doc, sec_name or pm.SEC_REVIEW, lines)


def _week_stats_of(index, wp, drop_names=()):
    """What a week contributed, read back off its own weekly note - the money
    pyramid, one tier up. None when there is no note for it.

    A month cannot recount its own completions (the completed feed reaches
    back about nine days), and the weekly notes ARE the record for those.
    Everything else a monthly shows - created, focus, money, moods,
    highlights, entries, habits - is recomputed from sources that keep, so
    only this one goes through the notes.

    {"per_day": {date: n}, "by_proj": {list: n}, "top_lists": {list: (done,
    added)}, "top_tasks": {title: n}}
    """
    t = lookup(index, wp)
    if not t:
        return None
    doc = ps.parse_sections(t.get("content") or "")

    def body(anchor, *legacy):
        sec = ps.find_prefix(doc, anchor, pm.scope_of("weekly", anchor))
        for nm in legacy:                  # pre-2026-09-17 weeklies
            if sec is not None:
                break
            sec = ps.find_prefix(doc, nm)
        return sec.body if sec is not None else []

    # the old layout kept the same seven bars under "📈 Stats" and the
    # headline under "✅ Completed:", so a week written before the relayout
    # still gives up its numbers; its rankings do not survive (they lived in
    # the header, one list deep) and read as empty.
    def legacy_head(prefix):
        """The old layout put a ranking IN its header: "🔥 Top list: 🌅
        Routines · 186 done · 335 added". Returns what follows the colon."""
        sec = ps.find_prefix(doc, prefix)
        name = sec.name if sec is not None else ""
        return name.split(":", 1)[1].strip() if ":" in name else ""

    # A note that EXISTS but was never filled is NOT a zero week: mint_ahead
    # mints the coming week every Sunday, and _fill_weekly writes the bars
    # only when the completed feed answered. A filled week always carries all
    # seven rows, zeros included (pm.done_week_lines), so no bars means
    # unknown - and a hard 0 would read as a week he got nothing done in.
    per_day = pm.parse_day_bars(body(pm.SEC_WBARS, pm.SEC_STATS), wp.start)
    if not per_day:
        return None
    tls = pm.parse_top_list_lines(body(pm.SEC_TOP_LIST))
    if not tls:
        tls = pm.parse_top_list_lines(["- " + legacy_head("🔥 Top list")])
    tts = pm.parse_top_task_lines(body(pm.SEC_TOP_TASKS))
    if not tts:
        # the old header listed the titles comma-joined and countless, so each
        # one counts as the single occurrence it is known to have
        tts = {t.strip(): 1 for t in legacy_head("🚀 Top tasks").split(",")
               if t.strip()}
    created = 0
    csec = ps.find_prefix(doc, pm.SEC_CREATED, pm.scope_of("weekly",
                                                           pm.SEC_CREATED)) \
        or ps.find_prefix(doc, "➕ Created")
    if csec is not None and ":" in csec.name:
        head = pm.unescape_md(csec.name.split(":", 1)[1]).strip()
        m = re.match(r"^\s*(\d+)", head)
        created = int(m.group(1)) if m else 0
    def keep(mp):
        return {k: v for k, v in mp.items() if k not in drop_names}

    return {"per_day": per_day,
            "created": created,
            "created_by_proj": pm.parse_proj_lines(
                csec.body if csec is not None else []),
            "by_proj": keep(pm.parse_proj_lines(body(pm.SEC_COMPLETED,
                                                     "✅ Completed"))),
            "top_lists": keep(tls),
            "top_tasks": tts}


def _ignored_names(projects):
    """The routine lists BY NAME. A sealed week gives up its rankings as text,
    so the pid filter the live path uses cannot reach them - and a week
    written before the routines rule shipped (2026-09-17) has 🌅 Routines
    sitting at the top of its Top list, which is exactly what Vex asked to
    stop seeing."""
    return {nm for pid, nm in (projects or {}).items()
            if pid in _stats_ignored_pids()}


def _week_stats_live(wp, today, projects, clip_start=None):
    """The same shape, computed from the live feed - for the week that is
    still running, whose note may not have been refreshed yet. `clip_start`
    holds it inside the month asking (a week straddling two months must not
    put the neighbour's days into either one's numbers).

    Its rankings are cut to THREE, like a sealed week's: a weekly note only
    ever kept its top three, so letting the live week hand over everything it
    has would make the month's ranking a mix of two different questions.
    """
    start = max(wp.start, clip_start or wp.start)
    end = min(wp.end, today)
    if start > end:
        return None
    comp = _completed_between(start, end)
    if comp is None:
        return None
    rank = _drop_ignored(comp)
    created_all = _created_between(start, end)
    created = _drop_ignored(created_all)
    done_bp, created_bp = _by_proj(rank, projects), _by_proj(created, projects)
    per_day = {}
    d = start
    while d <= end:
        per_day[d] = sum(1 for t in comp
                         if utc_str_to_local_date(t.get("completedTime") or "")
                         == d.isoformat())
        d += timedelta(days=1)
    pairs = {nm: (done_bp.get(nm, 0), created_bp.get(nm, 0))
             for nm in set(done_bp) | set(created_bp)}
    traffic = {nm: a + b for nm, (a, b) in pairs.items()}
    return {"per_day": per_day,
            "created": len(created_all),
            "created_by_proj": dict(pm.top_n(_by_proj(created_all, projects))),
            "by_proj": dict(pm.top_n(done_bp)),
            "top_lists": {nm: pairs[nm] for nm, _c in pm.top_n(traffic)},
            "top_tasks": dict(pm.top_n(pm.task_counts(rank)))}


def _month_week_data(index, period, today, projects):
    """{week start: stats | None} for every week a month touches."""
    out, drop = {}, _ignored_names(projects)
    for _n, wp, _a, _b in pm.month_week_spans(period):
        live = (_week_stats_live(wp, today, projects, period.start)
                if wp.start <= today <= wp.end else None)
        out[wp.start] = (live if live is not None
                         else _week_stats_of(index, wp, drop))
    return out


def _month_done(data, period):
    """Σ completions inside the month's own days, from its weeks' per-day
    numbers - the straddle rule money has always used. None when not one week
    could be read (an unreadable month must not report 0)."""
    known = [st for st in data.values() if st]
    if not known:
        return None
    return sum(n for st in known for d, n in st["per_day"].items()
               if period.start <= d <= period.end)


def _fill_monthly(doc, p, index):
    """Vex's 2026-09-17 monthly: the weekly note's shape one tier up, counted
    by WEEK. Everything but the completions is recomputed from sources that
    keep; the completions come off the weekly notes (see _week_stats_of)."""
    today = _today()
    if not (p.start <= today <= p.end + timedelta(days=1)):
        return

    def _in(anchor):
        return pm.scope_of("monthly", anchor)

    # ALL or NOTHING on the layout, the weekly's rule: a note minted under the
    # old skeleton (🎯 Month goal · 📈 Stats · 📊 Sparklines · 🏆 Top wins) has
    # none of these anchors, and half-filling it would be worse than leaving
    # it alone until tools/pnrepair/relayout_monthly.py rebuilds it.
    scoped = [a for a in pm.WRITER_ANCHORS["monthly"] if _in(a)]
    if not any(ps.find_prefix(doc, a, _in(a)) is not None for a in scoped):
        _log(f"monthly {pm.title(p)} predates the 2026-09-17 layout - left "
             f"alone (tools/pnrepair/relayout_monthly.py rebuilds it)")
        return

    # 🏆 Goals - the quarter mirrored in; 🗓️ Monthly goal is his
    _mirror_goal(doc, pm.SEC_MTH_QTR, "quarterly", index, p.start,
                 pm.HINT_WK_QTR)

    t2 = _tier2()
    prev = pm.prev_period(p)
    live_end = min(p.end, today)
    spans = pm.month_week_spans(p)
    projects = {pr.get("id"): pr.get("name")
                for pr in (cache_store.get("projects") or [])}
    data = _month_week_data(index, p, today, projects)
    prev_data = _month_week_data(index, prev, today, projects)

    def ranked(period, wdata):
        """The weeks whose RANKINGS belong to a month: the ones lying wholly
        inside it, plus the live one, which _week_stats_live already clipped.
        A sealed week straddling two months keeps its ranking in WEEK shape
        and nothing can cut that by day, so it is left out rather than let
        the neighbouring month's traffic into this month's numbers."""
        out = []
        for _n, wp, a, b in pm.month_week_spans(period):
            st = wdata.get(wp.start)
            if st and ((a, b) == (wp.start, wp.end)
                       or wp.start <= today <= wp.end):
                out.append(st)
        return out

    rank_cur, rank_prev = ranked(p, data), ranked(prev, prev_data)

    # ── Top lists / Top tasks - the month's, summed from those weeks'
    tl = pm.count_list_lines(pm.merge_pairs([st["top_lists"] for st in rank_cur]))
    if tl:
        ps.set_body(doc, pm.SEC_TOP_LIST, tl, _in(pm.SEC_TOP_LIST))
    tt = pm.count_task_lines(pm.merge_counts(*[st["top_tasks"]
                                               for st in rank_cur]))
    if tt:
        ps.set_body(doc, pm.SEC_TOP_TASKS, tt, _in(pm.SEC_TOP_TASKS))

    # ── Created - off the same pyramid as Completed. NOT from the task cache:
    # that holds open tasks plus nine days of completed ones, so a month's own
    # early days are already short and LAST month is a fiction - the chip read
    # "🟢 ▲ 1204 (+1974%)" against an August that was really just its survivors.
    created_cur = sum(st["created"] for st in rank_cur) if rank_cur else None
    if created_cur is not None:
        cprev = sum(st["created"] for st in rank_prev) if rank_prev else None
        ch = pm.chip(created_cur, cprev)
        _set_headed(doc, pm.SEC_CREATED,
                    str(created_cur) + (f" · {ch}" if ch else ""),
                    pm.ind([f"- 🗂 {nm} · {c}" for nm, c in pm.top_n(
                        pm.merge_counts(*[st["created_by_proj"]
                                          for st in rank_cur]))]),
                    _in(pm.SEC_CREATED))

    # ── Completed + the per-week bars, both off the weeks' own numbers
    done_cur = _month_done(data, p)
    if done_cur is not None:
        ch = pm.chip(done_cur, _month_done(prev_data, prev))
        _set_headed(doc, pm.SEC_COMPLETED,
                    str(done_cur) + (f" · {ch}" if ch else ""),
                    pm.ind([f"- 🗂 {nm} · {c}" for nm, c in pm.top_n(
                        pm.merge_counts(*[st["by_proj"]
                                          for st in rank_cur]))]),
                    _in(pm.SEC_COMPLETED))
        rows = []
        for n, wp, a, b in spans:
            if a > today:
                break                      # a week that has not started yet
            st = data.get(wp.start)        # is not a week with a missing note
            rows.append((pm.week_span_label(n, a, b),
                         None if not st else
                         sum(v for d, v in st["per_day"].items() if a <= d <= b)))
        ps.set_body(doc, pm.SEC_MBARS, pm.ind(pm.done_span_lines(rows)[:-1]),
                    _in(pm.SEC_MBARS))

    # ── Focus - recomputed per week, with the week's own top task
    fspan = getattr(t2, "focus_by_span", lambda a, b: None)
    tot = fspan(p.start, live_end) if t2 else None
    if tot is not None:
        prev_min = getattr(t2, "focus_minutes", lambda a, b: None)(prev.start,
                                                                  prev.end)
        ch = pm.chip(tot[0], prev_min, "duration")
        wk_lines = []
        for n, wp, a, b in spans:
            if a > today:
                break
            rec = fspan(a, min(b, today))
            if rec and rec[0]:
                ln = f"- {pm.week_span_label(n, a, b)} · {pm.fmt_hm(rec[0])}"
                if rec[1]:
                    ln += f" · {mdtext.flatten_links(rec[1])[:40]}"
                wk_lines.append(ln)
        _set_headed(doc, pm.SEC_FOCUS_WEEK,
                    pm.fmt_hm(tot[0]) + (f" · {ch}" if ch else ""),
                    pm.ind(wk_lines)
                    + [f"{pm.T3}- **Total = {pm.fmt_hm(tot[0])}**"],
                    _in(pm.SEC_FOCUS_WEEK))

    # ── Habit consistency - each habit against its own MONTH SO FAR: the
    # denominator has to stop where the numerator does, or a perfect month
    # reads 6/19 on the 17th (every other section here stops at live_end)
    hb = getattr(t2, "habit_lines_weekly", lambda a, b: None)(p.start,
                                                              live_end) \
        if t2 else None
    if hb is not None:
        ps.set_body(doc, pm.SEC_HABIT_WEEK, pm.ind(hb), _in(pm.SEC_HABIT_WEEK))

    # ── ✨ Highlights - the WEEK's highlight, one line each, newest first
    hl_rows = []
    for n, wp, a, b in spans:
        wt = lookup(index, wp)
        if not wt:
            continue
        hl = _weekly_highlight_of(ps.parse_sections(wt.get("content") or ""))
        if hl and hl.strip():
            hl_rows.append(f"- {pm.week_span_label(n, a, b)} · "
                           f"{mdtext.flatten_links(hl).strip()}")
    if hl_rows:
        ps.set_body(doc, pm.SEC_HL_WEEK, pm.ind(list(reversed(hl_rows))),
                    _in(pm.SEC_HL_WEEK))

    # ── 📨 Entries - five a kind, spread across the month (pm.top_entries)
    items = _entries_between(index, p.start, live_end)
    if any(it[2] in pm.GROUP_ORDER for it in items):
        week_of = {}
        for n, _wp, a, b in spans:
            week_of.update({a + timedelta(days=i): n
                            for i in range((b - a).days + 1)})
        ps.set_body(doc, pm.SEC_ENTRIES,
                    pm.entries_grouped(pm.top_entries(
                        items, lambda d: week_of.get(d, 0)), dated=True),
                    _in(pm.SEC_ENTRIES))

    # ── 😊 Moods - the month average in the header, one line per WEEK
    moods = _mood_by_day(index, p.start, live_end)
    if moods:
        avg = sum(m[0] for _d, m in moods) / len(moods)
        pavg = _mood_avg(index, prev.start, prev.end)
        ch = pm.chip(round(avg, 1),
                     round(pavg, 1) if pavg is not None else None, "avg")
        rows = []
        for n, _wp, a, b in spans:
            wk = [m[0] for d, m in moods if a <= d <= b]
            rows.append((pm.week_span_label(n, a, b),
                         sum(wk) / len(wk) if wk else None))
        _set_headed(doc, pm.SEC_MOODS,
                    f"Average {avg:.1f}" + (f" · {ch}" if ch else ""),
                    pm.mood_span_lines(rows), _in(pm.SEC_MOODS))

    # ── 💰 Income - week lines, month total, both off the daily notes
    day_sums = _day_sums(index)
    inc_cur = pm.sum_in_period(day_sums, p)
    ch = (pm.chip(inc_cur, pm.sum_in_period(day_sums, prev), "money")
          if any(prev.start <= d <= prev.end for d in day_sums) else None)
    _set_headed(doc, pm.SEC_INCOME,
                pm.fmt_amount(inc_cur) + (f" · {ch}" if ch else ""),
                pm.ind([f"- {pm.week_span_label(n, a, b)} • "
                        f"{pm.fmt_amount(sum(v for d, v in day_sums.items() if a <= d <= b))}"
                        for n, _wp, a, b in spans])
                + [pm.money_total_line(inc_cur, 3)],
                _in(pm.SEC_INCOME))

    # ── 👽 People
    _fill_people(doc, t2, days=31, within=_in(pm.SEC_PEOPLE))

    # ── ⏳ Dates - the calendar half: every birthday and countdown LANDING in
    # this month, by date. Past days count: a birthday on the 3rd is still
    # what the month held (Vex 2026-09-17).
    dl = getattr(t2, "dates_in_span", lambda a, b: None)(p.start, p.end) \
        if t2 else None
    if dl is not None:
        ps.set_body(doc, pm.SEC_MDATES, pm.ind(dl), _in(pm.SEC_MDATES))

    # ── ⏪ Last month - the weekly's sealed composite one tier up: the five
    # headline numbers, then the same two rankings. Every one of them reads
    # the PREVIOUS month's weeks, so a month with none of them left just
    # keeps whatever is already written.
    if _month_done(prev_data, prev) is not None:
        lm = [f"- Completed: {_month_done(prev_data, prev)}",
              f"- Created: {sum(st['created'] for st in rank_prev)}"]
        pf = getattr(t2, "focus_minutes", lambda a, b: None)(prev.start,
                                                             prev.end) \
            if t2 else None
        if pf:
            lm.append(f"- Focus: {pm.fmt_hm(pf)}")
        pmood = _mood_avg(index, prev.start, prev.end)
        if pmood is not None:
            lm.append(f"- Mood: {pmood:.1f} avg")
        lm.append(f"- Income: {pm.fmt_amount(pm.sum_in_period(day_sums, prev))}")
        top_tasks = pm.count_task_lines(pm.merge_counts(*[st["top_tasks"]
                                                          for st in rank_prev]))
        top_lists = [f"{pm.T1}- 🗂 {nm} · {c}" for nm, c in pm.top_n(
            pm.merge_counts(*[st["by_proj"] for st in rank_prev]))]
        if top_tasks or top_lists:
            lm.append("")
        if top_tasks:
            lm += ["- Top Tasks:"] + top_tasks
        if top_lists:
            lm += ["- Top Lists"] + top_lists
        ps.set_body(doc, pm.SEC_LAST_MONTH, lm)

    # ── ♻️ Monthly Review - the weekly's mirror, its own source
    _fill_review(doc, pm.SEC_MREVIEW, cfg.get_monthly_review_id())


def _fill_rollup_money(doc, p, index):
    """Monthly/quarterly/yearly 💰 (v3.0 scope). Missing-history rule: a span
    with ZERO daily notes keeps its existing lines (deleted dailies must not
    rot old roll-ups to 0)."""
    day_sums = _day_sums(index)
    if not any(p.start <= d <= p.end for d in day_sums):
        return
    lines = []
    if p.kind == "monthly":
        weeks, seen = [], set()
        d = p.start
        while d <= p.end:
            wk = pm.period_for("weekly", d)
            if wk.start not in seen:
                seen.add(wk.start)
                weeks.append(wk)
            d += timedelta(days=7 - d.weekday())
        for wk in weeks:
            iso = wk.start.isocalendar()
            rng = (f"{wk.start.day:02d}-{wk.end.day:02d} "
                   f"{pm.MONTH_ABBR[wk.end.month]}")
            lines.append(f"- W{iso[1]:02d} ({rng}) • "
                         f"{pm.fmt_amount(pm.sum_in_period(day_sums, wk))}")
    elif p.kind == "quarterly":
        for m in range(3):
            mp = pm.period_for("monthly", date(p.start.year, p.start.month + m, 1))
            lines.append(f"- {pm.title(mp)} • "
                         f"{pm.fmt_amount(pm.sum_in_period(day_sums, mp))}")
    else:   # yearly
        for qm in (1, 4, 7, 10):
            qp = pm.period_for("quarterly", date(p.start.year, qm, 1))
            lines.append(f"- {pm.title(qp)} • "
                         f"{pm.fmt_amount(pm.sum_in_period(day_sums, qp))}")
    ps.set_body(doc, pm.SEC_MONEY,
                pm.rollup_money_lines(lines, pm.sum_in_period(day_sums, p)))


# ── the 04:30 run ────────────────────────────────────────────────────────────
def _read_stamp():
    try:
        with open(STAMP_FILE) as f:
            return f.read().strip()
    except Exception:
        return ""


def mint_ahead(force=False):
    """The agent run: mint the day that JUST STARTED - the 04:30 run creates
    TODAY's periods, so a 'tomorrow' card never sits in the kanban all day.
    Exception: the weekly still mints Sunday for the week AHEAD (Sunday
    planning - the weekly journal's three-things handoff writes into it).
    Plus catch-up (current period of ALL 5 tiers - heals powered-off gaps,
    first-run bootstrap, guarantees roll-up targets), refresh today,
    closing-period seals. Stamped: RunAtLoad re-fires cost zero network when
    fresh."""
    today = _today()
    stamp = _read_stamp()
    if not force and stamp == today.isoformat():
        return None                      # fresh stamp - nothing to do
    # Narrow lock: index + creates only. The old outer lock held
    # through every refresh's Tier-2 HTTP, so an interactive pn_open at
    # Monday-morning wake blocked for the whole agent run. Refreshes
    # serialize per-note via _pn_rmw's own lock.
    with _flock():
        index = build_index(force=True)
        targets = pm.periods_started_by(today)
        targets += [pm.period_for(k, today) for k in pm.KINDS]      # catch-up
        if today.weekday() == 6:         # Sunday → the coming week's weekly
            targets.append(pm.period_for("weekly", today + timedelta(days=1)))
        minted = []
        for p in targets:
            if not lookup(index, p):
                create_note(p, index)
                minted.append(pm.title(p))
    # Closing pass FIRST: sweep yesterday's late ✅/⏩ ticks and
    # seal ended periods BEFORE today's ✅ merge reads the cache - else a
    # task the sweep is about to complete re-enters today's note as a
    # permanent stale unchecked line. Stamp-gap walk (≤31 days): a
    # powered-off boundary day still gets its seals on the next run.
    last = None
    try:
        last = date.fromisoformat(stamp)
    except Exception:
        pass
    start = max(last + timedelta(days=1),
                today - timedelta(days=31)) if last else today
    closing, d = [], start
    while d <= today:
        for p in pm.periods_started_by(d):
            prev = pm.prev_period(p)
            if lookup(index, prev) and prev not in closing:
                closing.append(prev)
        d += timedelta(days=1)
    for p in closing:
        refresh_period(p, index=index)
    refresh_period(pm.period_for("daily", today), index=index)
    refresh_period(pm.period_for("weekly", today), index=index)
    for kind in ("monthly", "quarterly", "yearly"):
        refresh_period(pm.period_for(kind, today), index=index)
    try:
        with open(STAMP_FILE, "w") as f:
            f.write(today.isoformat())
    except Exception:
        pass
    _log(f"mint_ahead: minted={minted or 'none'} · closing={len(closing)}")
    return minted


# ── verbs' engine halves ─────────────────────────────────────────────────────
def resolve(spec):
    """spec → (Period, task | None, minted). 'yesterday' never back-mints."""
    today = _today()
    if spec == "yesterday":
        p = pm.period_for("daily", today - timedelta(days=1))
        return p, lookup(build_index(), p), False
    kind = "daily" if spec == "daily" else spec
    p = pm.period_for(kind, today)
    task, minted = ensure_note(p)
    return p, task, minted


def _refresh_fresh(p):
    """Refresh stamp: an open within REFRESH_TTL of the last refresh skips it."""
    st = cache_store.get("pn_refresh_stamp") or {}
    return (st.get("key") == f"{p.kind}:{pm.title_key(p)}"
            and time.time() - st.get("ts", 0) < REFRESH_TTL)


def _stamp_refresh(p):
    cache_store.set("pn_refresh_stamp",
                    {"key": f"{p.kind}:{pm.title_key(p)}", "ts": time.time()})


def open_period(spec, refresh=True):
    """resolve → refresh → deep link. Returns (url|None, toast)."""
    p, task, minted = resolve(spec)
    if not task:
        return None, f"💫 No note for {spec} yet"
    if minted or (refresh and not _refresh_fresh(p)):
        refresh_period(p)
        _stamp_refresh(p)
    verb = "minted" if minted else "open"
    return open_link(task), f"💫 {pm.title(p)} {verb}"


def refresh_spec(spec):
    """Refresh one period by spec - the background half of the instant-open
    path (opens were slow because refresh ran BEFORE the app opened).
    Ensures, refreshes, stamps. Returns a toast."""
    p, task, minted = resolve(spec)
    if not task:
        return f"💫 No note for {spec} yet"
    summary = refresh_period(p)
    _stamp_refresh(p)
    return f"🔄 {pm.title(p)} {summary}"


def append_entry(kind, text, when=None):
    """Entry into today's 📓 Notes (or ✅ Today for task-kind, which also
    creates the real Inbox task; mood routes to the 💬 Mood line). Returns
    toast."""
    if kind == "mood":
        m = pm.MOOD_RE.match(text.strip())
        if not m:
            return "😊 Mood is 1-5"
        return set_day_mood(int(m.group("score")), m.group("note") or "")

    hm = (when or datetime.now()).strftime("%H:%M")
    p = pm.period_for("daily", _today())
    task, _ = ensure_note(p)
    pid, tid = task.get("projectId") or areas.PERIODIC_LIST_ID, task.get("id")

    if kind == "task":
        real = _api().create_task(title=text)      # Inbox
        rpid, rtid = real.get("projectId"), real.get("id")
        # patch the new task into the local cache - else it's invisible in
        # search until the hourly sync (same fix as the old
        # fresh-inbox-add polish)
        try:
            cached = cache_store.get("all_tasks")
            if cached is not None:
                cache_store.set("all_tasks", cached + [real])
        except Exception:
            cache_store.invalidate("all_tasks")

        def mutate(doc, live):
            sec = ps.find(doc, pm.SEC_TODAY)
            if sec is None:
                return False
            merged, added = pm.merge_checkboxes(sec.body, [(rpid, rtid, text)])
            ps.set_body(doc, pm.SEC_TODAY, merged)
            return added
        _pn_rmw(pid, tid, mutate)
        return f"☑️ Task added: {text[:40]}"

    line = pm.T2 + pm.make_entry(kind, text, hm)

    def mutate(doc, live):
        sec = ps.find(doc, pm.SEC_NOTES)
        if sec:
            sec.body = [ln for ln in sec.body
                        if not pm.PENDING_RE.match(ln.strip())]
        return ps.append_body(doc, pm.SEC_NOTES, [line])
    ok, _doc = _pn_rmw(pid, tid, mutate)
    if not ok:
        return "💫 No 📓 Notes section in today's note"
    toasts = {"win": "🟢 Win logged", "nag": "🔴 Nag logged",
              "thought": "💭 Noted", "reminder": "❗️ Reminder noted",
              "link": "🔗 Link saved"}
    return toasts.get(kind, "💫 Logged")


def _journal_answer(slot, needle, text, day=None):
    """Write `text` as the answer to the journal question containing `needle`.
    True when it landed. The mood and the day rating are journal answers now,
    not lead lines, so their quick-entry verbs write where the question is."""
    p = pm.period_for("daily", day or _today())
    task, _ = ensure_note(p)
    pid, tid = task.get("projectId") or areas.PERIODIC_LIST_ID, task.get("id")
    sec_name = _JOURNAL_SECTIONS.get(slot)

    def mutate(doc, live):
        sec = ps.find(doc, sec_name)
        if sec is None:
            return False
        body = list(sec.body)
        for n, q, a, idx in pm.journal_pairs(body):
            if needle.casefold() not in (q or "").casefold():
                continue
            m = pm.JOURNAL_A_RE.match(body[idx])
            ws, dash = m.group("ws"), m.group("dash") or ""
            ital = m.group("ital")
            # callable = read-modify-write (the 💰 verb sums into whatever is
            # already answered there)
            val = text(a or "") if callable(text) else text
            body[idx] = f"{ws}{dash}{ital}A: {val}{ital}"
            ps.set_sec_body(doc, sec, body)
            return True
        return False
    ok, _doc = _pn_rmw(pid, tid, mutate)
    return ok


def set_day_mood(score, note="", day=None):
    """The morning journal's mood answer - the quick way to answer that one
    question without opening the whole dialog run.

    There is no lead-line fallback any more: _compose_lead rebuilds the lead
    from scratch on every refresh and no longer emits Mood:/Day:, so a
    fallback write there would be deleted within the hour. Better to say the
    question is missing than to pretend it landed."""
    shown = pm.mood_text(int(score), note)
    if not _seeded_answer("morning", "mood", shown, day):
        return f"💫 {_when(day)}no mood question in that morning journal"
    return (f"{pm.MOOD_FACES[int(score)]} {_when(day)}Mood logged"
            + (f" · {note}" if note else ""))


def set_day_rating(score, day=None):
    """The evening journal's rating answer (see set_day_mood on the fallback)."""
    stars = "★" * max(1, min(5, int(score)))
    if not _seeded_answer("evening", "rate the day", stars, day):
        return f"💫 {_when(day)}no rating question in that evening journal"
    return f"{stars} {_when(day)}Day rated"


def weekly_has_highlight(day=None):
    """Does this week's note still carry an ✨ Highlight section? Twin of
    _daily_has_money: Vex's 2026-09-17 layout dropped it, so the highlight
    lives as the weekly journal's first ANSWER and the section is written
    only where one survives."""
    task = lookup(build_index(), pm.period_for("weekly", day or _today()))
    if not task:
        return False
    return ps.find(ps.parse_sections(task.get("content") or ""),
                   pm.SEC_HIGHLIGHT) is not None


def set_highlight(text, day=None):
    """✨ Highlight of the week containing `day` (default: current week).

    Two homes, one verb: the ✨ section where a note still has one, and
    otherwise the weekly journal's highlight ANSWER, which is where the
    highlight lives since Vex dropped that section on 2026-09-17. The ⭐️ row
    keeps working either way, and 🕰️ On this day reads whichever exists.
    """
    p = pm.period_for("weekly", day or _today())
    task, _ = ensure_note(p)
    pid, tid = task.get("projectId") or areas.PERIODIC_LIST_ID, task.get("id")

    def mutate(doc, live):
        sec = ps.find(doc, pm.SEC_HIGHLIGHT)
        if sec is None:
            return False
        ps.set_body(doc, pm.SEC_HIGHLIGHT, [text])
        return True
    ok, _doc = _pn_rmw(pid, tid, mutate)
    if ok:
        return "✨ Highlight saved"
    if journal_answer_key("weekly", "highlight", text, p.start):
        return "✨ Highlight saved to the weekly journal"
    return "💫 Nowhere to save the highlight · the weekly note has no ✨ " \
           "section and no highlight question"


def day_goal_now():
    """Today's ☀️ goal display text | '' - the morning handoff checks this."""
    task = lookup(build_index(), pm.period_for("daily", _today()))
    if not task:
        return ""
    doc = ps.parse_sections(task.get("content") or "")
    sec = ps.find(doc, pm.SEC_DAY_GOAL)
    return pm.day_goal_title(sec.body) if sec else ""


def set_day_goal(pid_or_text, tid=None, title=None):
    """☀️ Day Goal (One Thing) - REPLACES the section body (one thing!).
    Linked form also schedules the task for today (picking a goal rides the
    schedule flow with today prefilled); text form creates a real Inbox
    task due today and links it."""
    today_iso = _today().strftime("%Y-%m-%dT00:00:00+0000")
    if tid:
        line = fb.make_line(pid_or_text, tid, title or "Task").raw
        # onto today at its own time - T00:00:00+0000 wiped a task's clock
        # and read as all-day (Vex 2026-09-15)
        info = _goal_task_to_day(pid_or_text, tid, _today(), title)
        merge_ok, title_label, note = info["merge"], info["label"], info["suffix"]
    else:
        real = _api().create_task(title=pid_or_text, due_date=today_iso)
        try:
            cached = cache_store.get("all_tasks")
            if cached is not None:
                cache_store.set("all_tasks", cached + [real])
        except Exception:
            cache_store.invalidate("all_tasks")
        line = fb.make_line(real.get("projectId"), real.get("id"),
                            pid_or_text).raw
        title = pid_or_text
        merge_ok, title_label, note = True, pid_or_text, ""

    p = pm.period_for("daily", _today())
    task, _ = ensure_note(p)
    pid, ntid = task.get("projectId") or areas.PERIODIC_LIST_ID, task.get("id")

    tail = fb.LINK_TAIL_RE.search(line)
    link_pid = tail.group("pid") if tail else ""
    link_tid = tail.group("tid") if tail else ""

    def mutate(doc, live):
        sec = ps.find(doc, pm.SEC_DAY_GOAL)
        if sec is None:
            return False
        ps.set_body(doc, pm.SEC_DAY_GOAL, [pm.T1 + line])
        # the ✅ Tasks merge on the next refresh would re-add it; put it there
        # now so the day list and the goal agree immediately
        tsec = ps.find(doc, pm.SEC_TODAY)
        if tsec is not None and link_tid and merge_ok:
            merged, _a = pm.merge_checkboxes(
                tsec.body, [(link_pid, link_tid, title_label or title or "Task")],
                indent=pm.T2)
            ps.set_body(doc, pm.SEC_TODAY, merged)
        return True
    ok, _doc = _pn_rmw(pid, ntid, mutate)
    return f"☀️ Day goal: {(title or pid_or_text)[:40]}{note}" if ok \
        else "💫 No ☀️ Day Goal section in today's note"


def _goal_task_to_day(pid, tid, day, title=None):
    """Move a daily goal's task onto `day`, keeping its time of day (Vex
    2026-09-15: "Move to tomorrow, keep time"). Untimed = all day; a repeating
    or already finished task is left where it is.

    Returns {suffix, merge, label}: the toast suffix ('' = moved), whether the
    task belongs in that day's ✅ Tasks (a repeat whose occurrence is another
    day must not be there - ticking its line would let the sweep call it done
    without completing it), and the Tasks label carrying the clock the ✅
    merge would have given it."""
    import day_move
    out = {"suffix": "", "merge": True, "label": title or "Task"}
    try:
        live = _api().get_task(pid, tid)
    except Exception as e:
        _log(f"goal task read: {e}")
        # unknown task: it could be a repeat due another day, so it stays out
        # of Tasks (the 04:30 ✅ merge adds it if it really is that day's)
        out.update(suffix=" · date not changed", merge=False)
        return out
    title = title or live.get("title") or "Task"
    fields, how = day_move.move_fields(live, day)
    if fields is None:
        if how == "done":
            out.update(suffix=" · already done", merge=False)
        else:
            on_day = day_move.occurs_on(live, day)
            out.update(suffix=" · repeats, date kept" + ("" if on_day else ", not in Tasks"),
                       merge=on_day)
        when = live
    else:
        try:
            posted = _api().update_task(tid, live.get("projectId") or pid, current=live,
                                        **fields) or {}
            when = {k: posted.get(k, fields.get(k)) for k in ("startDate", "dueDate", "isAllDay")}
            try:
                from dispatch import _patch_task_cache
                _patch_task_cache(tid, **when)          # isAllDay too, as posted
            except Exception:
                pass
        except Exception as e:
            _log(f"goal task move: {e}")
            out.update(suffix=" · date not changed", merge=day_move.occurs_on(live, day))
            when = live
    stamp = when.get("startDate") or when.get("dueDate")
    hm = pm.clock(stamp, when.get("isAllDay")) if stamp else None
    out["label"] = pm.timed_title(title, hm)
    return out


def set_period_goal(kind, text="", pid=None, tid=None, title=None, ahead=False,
                    day=None):
    """Set a goal on ANY tier (Vex 2026-09-12: "There should be goal setting
    for every periodic note"), in any of his three shapes - text, a task, or
    text anchored to a task (pm.goal_line).

    Daily REPLACES its body (the One Thing) and moves the picked task onto
    that day at its own time (day_move); every other tier APPENDS, so a
    month or a quarter can carry several. Weekly additionally re-mirrors into
    today's daily, since the daily shows the week's goals.

    `day` aims a DAILY goal at another day's note - the evening journal picks
    tomorrow's (Vex 2026-09-15) and creates that note if it is not there yet.

    The target sections are pm.GOAL_SECTION - all five ship in their
    templates and none is written by a filler, so a goal cannot be clobbered.
    """
    if kind not in pm.GOAL_SECTION:
        return f"💫 {kind} has no goal section"
    line = pm.goal_line(text, pid, tid, title)
    if not line:
        return "🎯 Nothing to set"
    target_day = day or _today()
    moved, merge, label = "", True, title or "Task"
    if kind == "daily" and tid:
        info = _goal_task_to_day(pid, tid, target_day, title)
        moved, merge, label = info["suffix"], info["merge"], info["label"]

    p = pm.period_for(kind, target_day if kind == "daily" else _today())
    if ahead:                       # the weekly journal's three-things pass
        p = pm.next_period(p)
    task, _ = ensure_note(p)
    npid = task.get("projectId") or areas.PERIODIC_LIST_ID
    sec_name = pm.GOAL_SECTION[kind]
    indent = pm.T1

    def mutate(doc, live):
        nonlocal sec_name
        if kind == "weekly":             # bullet on a tiered note, section on
            sec_name = _week_goal_home(doc)      # one minted before it
        else:                            # …and a note minted under an older
            for nm in pm.goal_section_names(kind):   # name still answers
                if ps.find(doc, nm) is not None:
                    sec_name = nm
                    break
        if ps.find(doc, sec_name) is None:
            return False
        if kind == "daily":
            ps.set_body(doc, sec_name, [indent + line])
            tail = fb.LINK_TAIL_RE.search(line)
            tsec = ps.find(doc, pm.SEC_TODAY)
            if tsec is not None and tail and merge:
                merged, _a = pm.merge_checkboxes(
                    tsec.body, [(tail.group("pid"), tail.group("tid"), label)],
                    indent=pm.T2)
                ps.set_body(doc, pm.SEC_TODAY, merged)
            return True
        return _goal_append(doc, sec_name, indent + line)

    ok, doc_out = _pn_rmw(npid, task.get("id"), mutate)
    if not ok:
        return f"💫 No {sec_name} section in the {kind} note"
    task["content"] = ps.serialize_sections(doc_out)
    if kind == "weekly" and not ahead:      # only THIS week mirrors into today
        _mirror_week_goals(doc_out)
    shown = text or title or ""
    when = " (next)" if ahead else ""
    if kind == "daily" and target_day != _today():
        when = f" {target_day.strftime('%a %d %b')}"
    return f"🎯 {pm.GOAL_SECTION[kind]}{when} · {shown[:40]}{moved}"


def day_goal_on(day):
    """☀️ Daily goal display text of `day`'s note, read LIVE (the index copy
    can be a phone edit behind) | '' (no note, no goal)."""
    task = lookup(build_index(), pm.period_for("daily", day))
    if not task:
        return ""
    try:
        task = _api().get_task(task.get("projectId") or areas.PERIODIC_LIST_ID,
                               task.get("id")) or task
    except Exception:
        pass
    doc = ps.parse_sections(task.get("content") or "")
    sec = ps.find(doc, pm.SEC_DAY_GOAL)
    return pm.day_goal_title(sec.body) if sec else ""


def _mirror_week_goals(wdoc):
    """Today's daily shows the week's goals - re-pull them after a write."""
    dtask = lookup(build_index(), pm.period_for("daily", _today()))
    if not dtask:
        return
    goals, _gsec = _week_goals_of(wdoc)

    def mirror(doc, live):
        if goals:
            ps.set_body(doc, pm.SEC_WEEK_GOALS, goals)
        return True
    _pn_rmw(dtask.get("projectId") or areas.PERIODIC_LIST_ID,
            dtask.get("id"), mirror)


def _daily_has_money(day=None):
    """True when that day's note still carries a 💰 section (older layouts)."""
    t = lookup(build_index(), pm.period_for("daily", day or _today()))
    if not t:
        return False
    return ps.find(ps.parse_sections(t.get("content") or ""),
                   pm.SEC_MONEY) is not None


MONEY_NEEDLE = "money did you earn"


def _daily_note(day, notes=None):
    """That day's daily note out of the CACHE, or None. No API call: the rows
    that use this render on every keystroke."""
    rows = notes if notes is not None else (cache_store.get("all_notes") or [])
    for t in rows:
        if (t.get("projectId") or t.get("_projectId")) != areas.PERIODIC_LIST_ID:
            continue
        if pm.parse_daily_title(t.get("title") or "") == day:
            return t
    return None


def day_answer_state(day, slot, needle, notes=None):
    """(state, text) for ONE journal answer on ONE day, from the cache:

        "answered"  the question has an answer
        "blank"     the question is there, unanswered
        "unasked"   that day has no such question, or no note at all

    The three must stay apart. A reader that collapses them (_day_money does,
    into None-or-0) is fine for a sum and useless for a row that offers to
    overwrite: "nothing yet" and "he answered 0" cannot look the same there.
    """
    t = _daily_note(day, notes)
    if t is None:
        return "unasked", ""
    sec = ps.find(ps.parse_sections(t.get("content") or ""),
                  _JOURNAL_SECTIONS.get(slot, pm.SEC_EVENING))
    if sec is None:
        return "unasked", ""
    for _n, q, a, _i in pm.journal_pairs(sec.body):
        if needle.casefold() not in (q or "").casefold():
            continue
        return ("answered", a.strip()) if a and a.strip() else ("blank", "")
    return "unasked", ""


def day_money_state(day, notes=None):
    """(state, amount, text) - day_answer_state plus the number, and plus the
    legacy 💰 section that older notes still keep their history in."""
    st, txt = day_answer_state(day, "evening", MONEY_NEEDLE, notes)
    if st == "answered":
        return "answered", pm.parse_money_answer(txt), txt
    t = _daily_note(day, notes)
    if t is not None:
        msec = ps.find(ps.parse_sections(t.get("content") or ""), pm.SEC_MONEY)
        if msec is not None and any(pm.parse_money_entry(l) for l in msec.body):
            return "answered", pm.section_money_sum(msec.body), ""
    return st, None, txt


def week_answer_states(slot, needle, monday=None, today=None, money=False):
    """[(date, state, value, text)] for Monday..today, NEWEST first - the day
    strip's whole data source, one cache read for the week."""
    today = today or _today()
    monday = monday or (today - timedelta(days=today.weekday()))
    notes = cache_store.get("all_notes") or []
    out = []
    d = monday
    while d <= today:
        if money:
            out.append((d, ) + day_money_state(d, notes))
        else:
            st, txt = day_answer_state(d, slot, needle, notes)
            out.append((d, st, txt, txt))
        d += timedelta(days=1)
    return list(reversed(out))


def week_money_states(monday=None, today=None):
    return week_answer_states("evening", MONEY_NEEDLE, monday, today, money=True)


def append_income(amount, label="", day=None, replace=False):
    # a taught-separator answer like "500 · client" splits into head+tail
    # leaving "· client" - shave leading separators, never double them
    """Log money to a day. Sums into whatever is there; `replace` swaps it.

    Money has ONE home since Vex moved it into the evening journal ("it is an
    answer in the evening journal, that is all that should be there",
    2026-09-12), so this verb and the journal write the SAME line and cannot
    diverge. `day` makes it retrospective (2026-09-17: "add money entries
    retrospectively to chosen day of the week ... like if I skip evening
    journal"), and every message names the day it hit - a toast saying
    "today" over a write into Tuesday reads as a failure.

    Ordering matters. A note old enough to carry a 💰 SECTION with entries in
    it keeps using that section, because that is where its history is and
    because _day_money only falls back to a section while no answer exists -
    writing the answer on such a note would hide its whole history behind one
    number. Every other note takes the answer, seeding the evening journal
    first when that day has no money question at all (a back-minted note has
    none: create_note renders the template and the questions are planted on
    refresh, which skips a past day).
    """
    # a taught-separator answer like "500 · client" splits into head+tail
    # leaving "· client" - shave leading separators, never double them
    label = (label or "").strip().lstrip("·-•").strip()
    d = day or _today()
    when = pm.day_label(d)
    p = pm.period_for("daily", d)
    task, _ = ensure_note(p)
    pid, tid = task.get("projectId") or areas.PERIODIC_LIST_ID, task.get("id")

    def legacy(doc, live):
        sec = ps.find(doc, pm.SEC_MONEY)
        if sec is None or not any(pm.parse_money_entry(l) for l in sec.body):
            return False
        body = [] if replace else [l for l in sec.body if l.strip()]
        ps.set_body(doc, pm.SEC_MONEY,
                    pm.recompute_money_body(
                        body + [pm.money_entry_line(amount, label)]))
        return True

    ok, _doc = _pn_rmw(pid, tid, legacy)
    seen = {}
    if not ok:
        def write(prev):
            new, had = pm.money_answer_update(prev, amount, label, replace)
            seen["had"], seen["now"] = had, pm.parse_money_answer(new)
            return new
        ok = _journal_answer("evening", MONEY_NEEDLE, write, day=d)
        if not ok:
            journal_seed("evening", day=d)       # mints the note AND the Qs
            ok = _journal_answer("evening", MONEY_NEEDLE, write, day=d)
    if not ok:
        return f"💫 {when} · no money question in that note"
    had, now = seen.get("had"), seen.get("now")
    if had is not None and now is not None:
        return (f"💰 {when} · {pm.fmt_amount(now)} (was {pm.fmt_amount(had)})"
                if replace else
                f"💰 {when} · {pm.fmt_amount(had)} + {pm.fmt_amount(amount)}"
                f" = {pm.fmt_amount(now)}")
    return (f"💰 {when} · {pm.fmt_amount(amount)}"
            + (f" · {label}" if label else ""))


_JOURNAL_SECTIONS = {"morning": pm.SEC_MORNING, "evening": pm.SEC_EVENING,
                     "weekly": pm.SEC_WEEKLY_JNL}


def _journal_target(slot, day=None):
    if slot == "weekly":
        return pm.period_for("weekly", day or _today())
    return pm.period_for("daily", day or _today())


def journal_seed(slot, day=None):
    """RMW#1: seed Q/A pairs iff the section has none; unanswered fixed Qs
    get their dynamic text refreshed, and a journal seeded before a fixed
    question existed gets that question (insert=True). Returns
    (route_keys, pairs, period) - route_keys {n: key}, read off each
    question's WORDING (pm.journal_key), routes answer n; pairs carry existing
    answers so the dialogs skip what's done; period PINS the note for the
    whole dialog run (a run that crosses midnight must keep writing the day it
    started on - `day` carries that pin into a journal resumed after the goal
    picker)."""
    sec_name = _JOURNAL_SECTIONS[slot]
    p = _journal_target(slot, day)
    task, _ = ensure_note(p)
    pid, tid = task.get("projectId") or areas.PERIODIC_LIST_ID, task.get("id")

    def mutate(doc, live):
        ctx = journal_ctx(slot, doc)
        sec = ps.find(doc, sec_name)
        if sec is None:
            return None
        _seed_slot(doc, sec_name, slot, p.start, ctx, insert=True)
        return pm.journal_pairs(ps.find(doc, sec_name).body)
    pairs, _doc = _pn_rmw(pid, tid, mutate)
    keys = pm.journal_keys(pairs) if pairs else {}
    return keys, pairs, p


def journal_ctx(slot, doc):
    """The live text a journal's fixed questions bake in, read off the note."""
    ctx = {}
    if slot == "morning":
        # 🌉 yesterday's bridge already lives IN this note - echo it as a prompt
        bsec = ps.find(doc, pm.SEC_YBRIDGE)
        if bsec:
            ctx["ybridge"] = " ".join(
                ln.strip().lstrip(">").strip() for ln in bsec.body
                if ln.strip() and "_(pending)_" not in ln
                and not ps.DECOR_RE.match(ln.strip()))
    if slot in ("morning", "evening"):
        gsec = ps.find(doc, pm.SEC_DAY_GOAL)
        ctx["goal"] = pm.day_goal_title(gsec.body) if gsec else ""
    elif slot == "weekly":
        ctx["goals"] = "; ".join(pm.goal_titles(_week_goals_of(doc)[0])[:5])
    return ctx


def _when(day):
    """"Tue 15 Sep · " for a day that is not today, "" for today. Every verb
    that can write BACKWARDS has to name the day it hit, or a toast reads as
    a failure on today's note (Vex's retro entries, 2026-09-17)."""
    return "" if day is None or day == _today() else pm.day_label(day) + " · "


def _seeded_answer(slot, needle, text, day=None):
    """_journal_answer, but planting that day's journal first when the
    question is not there. A day he skipped has no questions at all until
    they are seeded; see set_day_answer for why seeding an old day is safe."""
    if _journal_answer(slot, needle, text, day=day):
        return True
    journal_seed(slot, day=day or _today())
    return bool(_journal_answer(slot, needle, text, day=day))


def set_day_answer(slot, key, text, day=None):
    """Write one journal ANSWER on ANY day, seeding that day's journal first
    when the question is not there yet. True when it landed.

    Vex 2026-09-17: "What if I skip shutdown routine for whatever reason?" -
    a day he skipped has no evening questions at all, so there is nothing to
    answer until they are planted. Planting them on an old day is safe and
    gives that day what it would have had: select_prompts is seeded by
    f"{date}:{slot}" so the random prompts are the date's own, and journal_ctx
    reads the goal off THAT day's note, so nothing of today leaks backwards.

    The ✨ mirror rides the SAME write. Nothing in the UI can refresh an
    arbitrary past daily note, so a mirror left to "the next refresh" would
    never run on exactly the days this verb exists for.
    """
    d = day or _today()
    after = _fill_day_highlight if key == "dhighlight" else None
    if journal_answer_key(slot, key, text, d, also=after):
        return True
    journal_seed(slot, day=d)
    return journal_answer_key(slot, key, text, d, also=after)


def journal_answer_key(slot, key, text, day, also=None):
    """Write `text` as the answer to the journal question whose route key is
    `key` in `day`'s note, even over an earlier answer (the goal picker's
    pick is the answer). True when it landed. `also` is a callable(doc) run
    inside the SAME read-modify-write, for anything that mirrors the answer."""
    p = _journal_target(slot, day)
    task, _ = ensure_note(p)
    pid, tid = task.get("projectId") or areas.PERIODIC_LIST_ID, task.get("id")
    sec_name = _JOURNAL_SECTIONS.get(slot)

    def mutate(doc, live):
        sec = ps.find(doc, sec_name)
        if sec is None:
            return False
        body = list(sec.body)
        for n, q, a, idx in pm.journal_pairs(body):
            if pm.journal_key(q) != key:
                continue
            m = pm.JOURNAL_A_RE.match(body[idx])
            ws, dash, ital = m.group("ws"), m.group("dash") or "", m.group("ital")
            body[idx] = f"{ws}{dash}{ital}A: {text}{ital}"
            sec.body = body
            if also is not None:
                also(doc)
            return True
        return False
    ok, _doc = _pn_rmw(pid, tid, mutate)
    return bool(ok)


def journal_merge(slot, answers, period=None, questions=None):
    """RMW#2: fill collected answers into STILL-EMPTY A-lines (phone wins).
    `period` = the seed-time period (midnight-safe). `questions` {n: text} =
    what each answer was ASKED for: an answer only lands under that question,
    so a stale copy of the note saved mid-run (the app, the phone) cannot
    shift answers onto their neighbours."""
    sec_name = _JOURNAL_SECTIONS[slot]
    p = period or _journal_target(slot)
    task, _ = ensure_note(p)
    pid, tid = task.get("projectId") or areas.PERIODIC_LIST_ID, task.get("id")

    def mutate(doc, live):
        sec = ps.find(doc, sec_name)
        if sec is None:
            return 0
        merged, filled = pm.merge_journal_answers(sec.body, answers, questions)
        if filled:
            sec.body = merged
        return filled
    filled, _doc = _pn_rmw(pid, tid, mutate)
    return filled


def set_goal(pid_or_text, tid=None, title=None, week="current"):
    """Weekly 🎯 Goals append (+ re-mirror today's daily when it's the
    current week). week='next' targets the COMING week - the weekly
    journal's three-things picker writes there."""
    anchor = _today() if week == "current" else _today() + timedelta(days=7)
    wkp = pm.period_for("weekly", anchor)
    wtask, _ = ensure_note(wkp)
    wpid = wtask.get("projectId") or areas.PERIODIC_LIST_ID
    if tid:
        line = pm.T1 + fb.make_line(pid_or_text, tid, title or "Task").raw
    else:
        line = f"{pm.T1}- [ ] {pid_or_text}"

    def mutate(doc, live):
        return _goal_append(doc, _week_goal_home(doc), line)
    ok, wdoc_out = _pn_rmw(wpid, wtask.get("id"), mutate)
    if not ok:
        return "💫 No 🎯 Goals section in the weekly note"
    wtask["content"] = ps.serialize_sections(wdoc_out)
    if week != "current":
        return "🎯 Goal set for next week"
    # re-mirror today's daily from the fresh weekly body
    dtask = lookup(build_index(), pm.period_for("daily", _today()))
    if dtask:
        goals, _gsec = _week_goals_of(wdoc_out)

        def mirror(doc, live):
            if goals:
                ps.set_body(doc, pm.SEC_WEEK_GOALS, goals)
            return True
        _pn_rmw(dtask.get("projectId") or areas.PERIODIC_LIST_ID,
                dtask.get("id"), mirror)
    return "🎯 Goal set"
