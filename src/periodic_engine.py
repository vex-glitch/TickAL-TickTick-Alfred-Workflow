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
from display import md_links_display
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
    module can't import Scripts/)."""
    try:
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
                idx[(kind, title)] = t
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


# Smart-view rows: (label, url) - EXACTLY the VIEWS deep links shipped +
# verified against the app in everything_search; routes not in that table
# are dead. If the app doesn't hyperlink ticktick:// inside note bodies,
# drop row 1 - row 2 (https task-anchors) still works.
def _nav_lines():
    row1 = [("📅 Today", "ticktick://v1/show?smartlist=today"),
            ("🌄 Tomorrow", "ticktick://v1/show?smartlist=tomorrow"),
            ("7️⃣ Next 7", "ticktick://v1/show?smartlist=next_7_days"),
            ("✔️ Completed", "ticktick://v1/show?smartlist=completed"),
            ("🔄 Habits", "ticktick://habit")]
    lines = [" · ".join(f"[{t}]({u})" for t, u in row1)]
    row2 = []
    if areas.crm_configured():
        row2.append((f"👥 {areas.crm_list_name()}",
                     f"https://ticktick.com/webapp/#p/{areas.CRM_ID}/tasks"))
    row2.append(("💫 Periodic",
                 f"https://ticktick.com/webapp/#p/{areas.PERIODIC_LIST_ID}/tasks"))
    rv = _review_target()
    if rv:
        row2.append(("♻️ Review", rv[0]))
    lines.append(" · ".join(f"[{t}]({u})" for t, u in row2))
    return lines


def _review_target():
    """weekly_review_id → (https_url, kind, obj) | None. kind: 'list' when the
    id names a project, 'task' when it names a cached task (its subtasks are
    the checklist), else None (unknown id = feature off, honest silence)."""
    rid = (cfg.get_weekly_review_id() or "").strip()
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


def _compose_lead(doc, p, index, refetch):
    """The lead is ENGINE-OWNED (hand-tuned layout): crumb / nav / ---
    and, on dailies, weather + quote + Mood/Day lines + a closing ---.
    Existing weather/quote/mood/day lines carry over; refetch=True swaps in
    fresh weather+quote (today's note only). Returns changed?"""
    old = doc.lead
    q_lines = [l for l in old if l.strip().startswith(">")]
    w_line = next((l for l in old if "°C" in l
                   and not l.strip().startswith(">")), None)
    mood = next((l for l in old if pm.MOOD_LINE_RE.match(l.strip())), None)
    day = next((l for l in old if pm.RATING_LINE_RE.match(l.strip())), None)
    if refetch and p.kind == "daily":
        t2 = _tier2()
        q = getattr(t2, "get_quote", lambda: None)() if t2 else None
        w = getattr(t2, "get_weather", lambda: None)() if t2 else None
        if q:
            q_lines = [q]
        if w:
            w_line = w
    out = [_crumb(p, index)] + _nav_lines() + ["---"]
    if p.kind == "daily":
        tail = [x for x in [w_line] + q_lines + [mood, day] if x]
        if tail:
            out += tail + ["---"]
    if doc.lead != out:
        doc.lead = out
        return True
    return False


def _set_lead_line(doc, line_re, new_line):
    """Replace the first lead line matching line_re, else insert before the
    lead's LAST --- divider (mood/rating writers)."""
    lead = list(doc.lead)
    for i, ln in enumerate(lead):
        if line_re.match(ln.strip()):
            if lead[i] == new_line:
                return False
            lead[i] = new_line
            doc.lead = lead
            return True
    last_div = None
    for i, ln in enumerate(lead):
        if ln.strip().startswith("---"):
            last_div = i
    if last_div is not None:
        lead.insert(last_div, new_line)
    else:
        lead.append(new_line)
    doc.lead = lead
    return True


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
        "navlinks": "\n".join(_nav_lines()),
    })
    # Child tag ONLY - TickTick's group-by-tag prefers the PARENT when both
    # are attached, which would collapse the kanban into one 💫Periodic
    # column. The parent exists as the tree node, never on tasks.
    task = _api().create_task(
        title=pm.title(p), project_id=areas.PERIODIC_LIST_ID,
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
            out.append((pid, t.get("id"), t.get("title") or "Task"))
    return out


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
        sec = ps.find(doc, pm.SEC_MONEY)
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
                   "weekly": (pm.SEC_REVIEW,)}


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
            pairs = []
            for sec_name in _SWEEP_SECTIONS.get(p.kind, ()):
                sec = ps.find(doc, sec_name)
                if sec:
                    pairs += [(pp, tt) for pp, tt in pm.checked_linked(sec.body)
                              if tt not in ledger]
            pairs = list(dict.fromkeys(pairs))
            if pairs:
                done, failed = _complete_many(pairs)
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
        else:
            _fill_rollup_money(doc, p, index)
        return True

    _res, doc_out = _pn_rmw(pid, tid, mutate)
    # refresh mutates content → patch the index copy in place, or same-run
    # consumers (roll-ups, mirrors) read stale bodies (no extra API call)
    task["content"] = ps.serialize_sections(doc_out)
    swept = notes_swept[0] if notes_swept else (0, 0)
    return f"refreshed{f' · swept {swept[0]}' if swept[0] else ''}"


def _fill_daily(doc, p, index, is_today):
    day = p.start
    # 🎯 Week goals mirror - verbatim copy; absent/empty weekly keeps the
    # template pointer line (bootstrap window)
    wk = lookup(index, pm.period_for("weekly", day))
    if wk:
        wdoc = ps.parse_sections(wk.get("content") or "")
        gsec = ps.find(wdoc, pm.SEC_GOALS)
        goals = [ln for ln in (gsec.body if gsec else []) if ln.strip()]
        if goals:
            ps.set_body(doc, pm.SEC_WEEK_GOALS, goals)
        elif gsec is not None:
            # weekly goals CLEARED → mirror resets to the pointer, never
            # keeps stale copies
            ps.set_body(doc, pm.SEC_WEEK_GOALS,
                        [f"{pm.T1}_(mirrors this week's weekly note — "
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

        # ⏪ Yesterday recap - honest-absence rule per line; FULL completed
        # list, nested one level deeper
        yd = day - timedelta(days=1)
        lines = []
        comp = _completed_between(yd, yd)
        if comp is not None:
            lines.append(f"{pm.T2}- ✅ Completed: {len(comp)}")
            lines += [f"{pm.T3}- {md_links_display(t.get('title') or '')[:64]}"
                      for t in comp]
        fm = getattr(t2, "focus_minutes", lambda a, b: None)(yd, yd) if t2 else None
        if fm:
            lines.append(f"{pm.T2}- 🍅 Focus: {pm.fmt_hm(fm)}")
        wd = _wontdo_between(yd, yd)
        if wd is not None and len(wd):
            lines.append(f"{pm.T2}- 🗑 Wontdo: {len(wd)}")
        yt = lookup(index, pm.period_for("daily", yd))
        if yt:
            ydoc = ps.parse_sections(yt.get("content") or "")
            msec = ps.find(ydoc, pm.SEC_MONEY)
            if msec:
                lines.append(f"{pm.T2}- 💰 Money: "
                             f"{pm.fmt_amount(pm.section_money_sum(msec.body))}")
            mood = _day_mood_of(yt)
            if mood:
                lines.append(f"{pm.T2}- Mood: {pm.MOOD_FACES[mood[0]]}"
                             + (f" · {mood[1]}" if mood[1] else ""))
        ps.set_body(doc, pm.SEC_YESTERDAY, lines or [f"{pm.T1}_(no data)_"])

        # ✅ Tasks merge (sweep already ran in step 0)
        sec = ps.find(doc, pm.SEC_TODAY)
        if sec is not None:
            body = [ln for ln in sec.body if not pm.PENDING_RE.match(ln.strip())]
            merged, _added = pm.merge_checkboxes(body, _scheduled_today(day),
                                                 indent=pm.T2)
            ps.set_body(doc, pm.SEC_TODAY, merged)

        # ⏩ Tomorrow - same checkbox links, tomorrow's schedule
        tmw = ps.find(doc, pm.SEC_TOMORROW)
        if tmw is not None:
            body = [ln for ln in tmw.body if not pm.PENDING_RE.match(ln.strip())]
            merged, _added = pm.merge_checkboxes(
                body, _scheduled_today(day + timedelta(days=1)), indent=pm.T2)
            ps.set_body(doc, pm.SEC_TOMORROW, merged)

        # 📊 Today summary - own sections, zero extra calls
        tsec = ps.find(doc, pm.SEC_TODAY)
        boxes = pm.checkbox_tids(tsec.body) if tsec else {}
        nsec = ps.find(doc, pm.SEC_NOTES)
        entries = pm.harvest_entries(nsec.body) if nsec else []
        counts = {}
        for _hm, g, _b in entries:
            counts[g] = counts.get(g, 0) + 1
        msec = ps.find(doc, pm.SEC_MONEY)
        sums = []
        if boxes:
            sums.append(f"- ⏳ Today: {sum(boxes.values())} of {len(boxes)} done")
        fm_t = getattr(t2, "focus_minutes", lambda a, b: None)(day, day) if t2 else None
        if fm_t:
            sums.append(f"- 🍅 Focus so far: {pm.fmt_hm(fm_t)}")
        if entries:
            detail = " · ".join(f"{n} {g}" for g, n in counts.items())
            sums.append(f"- 📓 Entries: {len(entries)} ({detail})")
        if msec:
            sums.append(f"- 💰 Today: {pm.fmt_amount(pm.section_money_sum(msec.body))}")
        ps.set_body(doc, pm.SEC_DAY_SUM,
                    pm.ind(sums) if sums else [f"{pm.T1}_(no data)_"])

        # 🌅/🌙 journal Q lines seed at refresh (never-empty sections,
        # phone-answerable); unanswered fixed prompts refresh their text so
        # the evening 'did you achieve {goal}' bakes in a goal set at noon
        _seed_daily_journals(doc, day)

    # 💰 re-total ALWAYS (historical dailies included)
    msec = ps.find(doc, pm.SEC_MONEY)
    if msec is not None:
        ps.set_body(doc, pm.SEC_MONEY, pm.recompute_money_body(msec.body))


def _refresh_fixed_q(sec, fixed):
    """Rewrite UNANSWERED fixed-prompt Q lines to their current text (dynamic
    prompts bake in live goal text). Answered ones are frozen history; the
    Q line's own indentation survives."""
    body = list(sec.body)
    changed = False
    for n, _q, a, a_idx in pm.journal_pairs(body):
        if n <= len(fixed) and not a:
            raw = body[a_idx - 1]
            ws = raw[:len(raw) - len(raw.lstrip())] or pm.T1
            want = pm.journal_q_line(n, fixed[n - 1][1], ws)
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


def _seed_slot(doc, sec_name, slot, d, ctx):
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
        _refresh_fixed_q(sec, fixed)
    _canon_journal_indent(sec)


def _seed_daily_journals(doc, day):
    gsec = ps.find(doc, pm.SEC_DAY_GOAL)
    goal = pm.day_goal_title(gsec.body) if gsec else ""
    _seed_slot(doc, pm.SEC_MORNING, "morning", day, {})
    _seed_slot(doc, pm.SEC_EVENING, "evening", day, {"goal": goal})


def _by_proj(tasks, projects):
    out = {}
    for t in (tasks or []):
        name = projects.get(t.get("projectId") or t.get("_projectId"), "Inbox")
        out[name] = out.get(name, 0) + 1
    return out


def _set_headed(doc, prefix, data, body_lines=None):
    """Data-in-header subsection: find by prefix, rewrite the header to
    '### <prefix>: <data>' (bare prefix when data is None) and optionally the
    body. Missing section = kill switch, skip."""
    sec = ps.find_prefix(doc, prefix)
    if sec is None:
        return
    ps.set_header(sec, f"{prefix}: {data}" if data else prefix)
    if body_lines is not None:
        ps.set_sec_body(doc, sec, body_lines)


def _fill_weekly(doc, p, index):
    """The 📌 This Week subsections (data-in-header) + 📨
    Entries + 😊 Moods + habits + 📔 journal seed + ♻️ review mirror + ⏪
    Last week. Live while current (+1 closing-grace day); older weeklies
    keep their sealed numbers."""
    today = _today()
    if not (p.start <= today <= p.end + timedelta(days=1)):
        return
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
    traffic = dict(done_bp)
    for nm, c in created_bp.items():
        traffic[nm] = traffic.get(nm, 0) + c

    # ── 🔥 Top list / 🚀 Top tasks
    if traffic:
        top = max(traffic.items(), key=lambda kv: kv[1])[0]
        _set_headed(doc, pm.SEC_TOP_LIST,
                    f"{top} — {done_bp.get(top, 0)} done · "
                    f"{created_bp.get(top, 0)} added")
    if comp_cur:
        top3 = ", ".join(md_links_display(t.get("title") or "")[:32]
                         for t in comp_cur[:3])
        _set_headed(doc, pm.SEC_TOP_TASKS, top3)

    # ── ➕ Created / ✅ Completed (header number+chip, 🗂 breakdown body)
    head = str(len(created_cur))
    ch = pm.chip(len(created_cur), len(created_prev))
    _set_headed(doc, pm.SEC_CREATED, head + (f" · {ch}" if ch else ""),
                pm.ind([f"- 🗂 {nm} · {c}" for nm, c in
                        sorted(created_bp.items(), key=lambda kv: -kv[1])[:3]]))
    if comp_cur is not None:
        head = str(len(comp_cur))
        ch = pm.chip(len(comp_cur),
                     len(comp_prev) if comp_prev is not None else None)
        _set_headed(doc, pm.SEC_COMPLETED, head + (f" · {ch}" if ch else ""),
                    pm.ind([f"- 🗂 {nm} · {c}" for nm, c in
                            sorted(done_bp.items(), key=lambda kv: -kv[1])[:3]]))
        # ── 📈 Stats - per-day bars
        per_day = []
        for i in range(7):
            d = p.start + timedelta(days=i)
            per_day.append((d, sum(1 for t in comp_cur
                                   if utc_str_to_local_date(t.get("completedTime") or "")
                                   == d.isoformat())))
        ps.set_body(doc, pm.SEC_WBARS,
                    pm.ind(pm.done_week_lines(per_day)[:-1]))

    # ── 🎯 Focus - header total+chip, by-day body, Total bullet
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
                    ln += f" · {md_links_display(rec[1])[:40]}"
                day_lines.append(ln)
        _set_headed(doc, pm.SEC_FOCUS_WEEK, head + (f" · {ch}" if ch else ""),
                    pm.ind(day_lines)
                    + [f"{pm.T3}- **Total = {pm.fmt_hm(total_min)}**"])

    # ── 📨 Entries - wins/nags/thoughts/links, grouped, newest first
    items = _entries_between(index, p.start, live_end)
    if any(it[2] in pm.GROUP_ORDER for it in items):
        ps.set_body(doc, pm.SEC_ENTRIES, pm.entries_grouped(items))

    # ── 😊 Moods - by day + average
    moods = _mood_by_day(index, p.start, live_end)
    if moods:
        avg = sum(m[0] for _d, m in moods) / len(moods)
        mlines = [f"- {pm.DAY_ABBR[d.weekday()]} {pm.MOOD_FACES[m[0]]}"
                  + (f" · {m[1]}" if m[1] else "") for d, m in moods]
        mlines.append(f"- Average: {avg:.1f}")
        ps.set_body(doc, pm.SEC_MOODS, pm.ind(mlines))

    # ── 🔄 Habit consistency - Tier-2 hook
    hb = getattr(t2, "habit_lines_weekly", lambda a, b: None)(p.start, p.end) if t2 else None
    if hb:
        ps.set_body(doc, pm.SEC_HABIT_WEEK, pm.ind(hb))

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
                + [pm.money_total_line(inc_cur, 3)])

    # ── 📔 Weekly journal - seed + dynamic-goal prompt refresh
    gsec = ps.find(doc, pm.SEC_GOALS)
    goals = "; ".join(pm.goal_titles(gsec.body)[:5]) if gsec else ""
    _seed_slot(doc, pm.SEC_WEEKLY_JNL, "weekly", p.start, {"goals": goals})

    # ── ♻️ Weekly Review mirror (sweep already completed ticked ones)
    _fill_review(doc)

    # ── ⏪ Last week - compact sealed composite
    if comp_prev is not None:
        prev_bp = _by_proj(comp_prev, projects)
        prev_created_bp = _by_proj(created_prev, projects)
        lw = []
        traffic = dict(prev_bp)
        for nm, c in prev_created_bp.items():
            traffic[nm] = traffic.get(nm, 0) + c
        if traffic:
            top = max(traffic.items(), key=lambda kv: kv[1])[0]
            lw.append(f"- 🔥 Top list: {top} — {prev_bp.get(top, 0)} done · "
                      f"{prev_created_bp.get(top, 0)} added")
        lw.append(f"- Completed: {len(comp_prev)}")
        top3 = ", ".join(md_links_display(t.get("title") or "")[:32]
                         for t in comp_prev[:3])
        if top3:
            lw.append(f"{pm.T1}- top: {top3}")
        lw += [f"{pm.T1}- 🗂 {nm} · {c}" for nm, c in
               sorted(prev_bp.items(), key=lambda kv: -kv[1])[:3]]
        lw.append(f"- Created: {len(created_prev)}")
        lw.append(f"- Income: {pm.fmt_amount(pm.sum_in_period(day_sums, prev))}")
        pf = getattr(t2, "focus_minutes", lambda a, b: None)(prev.start, prev.end) if t2 else None
        if pf:
            lw.append(f"- Focus: {pm.fmt_hm(pf)}")
        pmood = _mood_avg(index, prev.start, prev.end)
        if pmood is not None:
            lw.append(f"- Mood: {pmood:.1f} avg")
        ps.set_body(doc, pm.SEC_LAST_WEEK, pm.ind(lw, 1))


def _fill_review(doc):
    """♻️ Weekly Review - a LIVE mirror of the weekly_review_id source
    (focus-bar semantics, both directions). The sweep (step 0) completes
    ticked boxes; this rebuild then re-pulls the source, so note and source
    converge on every refresh. Check-states of still-open tasks survive via
    the tid map. Unset/unknown id or a failed pull → section untouched."""
    sec = ps.find(doc, pm.SEC_REVIEW)
    if sec is None:
        return
    tgt = _review_target()
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
    ps.set_body(doc, pm.SEC_REVIEW, lines)


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
            rng = (f"{wk.start.day:02d}–{wk.end.day:02d} "
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
    toasts = {"win": "🏆 Win logged", "nag": "👎 Nag logged",
              "thought": "💭 Noted", "link": "🔗 Link saved"}
    return toasts.get(kind, "💫 Logged")


def _lead_rmw_line(line_re, new_line, day=None):
    """Replace-or-insert one managed line in a daily note's LEAD (the
    Mood:/Day: lines live beside the quote). day pins journal flows that
    cross midnight."""
    p = pm.period_for("daily", day or _today())
    task, _ = ensure_note(p)
    pid, tid = task.get("projectId") or areas.PERIODIC_LIST_ID, task.get("id")

    def mutate(doc, live):
        return _set_lead_line(doc, line_re, new_line)
    _pn_rmw(pid, tid, mutate)
    return None


def set_day_mood(score, note="", day=None):
    """Lead Mood: line (replace-or-insert - last mood wins)."""
    err = _lead_rmw_line(pm.MOOD_LINE_RE, pm.mood_line(score, note), day=day)
    return err or (f"{pm.MOOD_FACES[int(score)]} Mood logged"
                   + (f" · {note}" if note else ""))


def set_day_rating(score, day=None):
    """Lead Day: ★ line."""
    err = _lead_rmw_line(pm.RATING_LINE_RE, pm.rating_line(score), day=day)
    return err or f"{'★' * max(1, min(5, int(score)))} Day rated"


def set_highlight(text, day=None):
    """✨ Highlight of the week containing `day` (default: current week)."""
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
    return "✨ Highlight saved" if ok else "💫 No ✨ Highlight section in the weekly note"


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
        try:
            from dispatch import _cached_task, _patch_task_cache
            _api().update_task(tid, pid_or_text, current=_cached_task(tid),
                               startDate=today_iso, dueDate=today_iso)
            _patch_task_cache(tid, startDate=today_iso, dueDate=today_iso)
        except Exception as e:
            _log(f"day_goal schedule: {e}")
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
        if tsec is not None and link_tid:
            merged, _a = pm.merge_checkboxes(
                tsec.body, [(link_pid, link_tid, title or "Task")],
                indent=pm.T2)
            ps.set_body(doc, pm.SEC_TODAY, merged)
        return True
    ok, _doc = _pn_rmw(pid, ntid, mutate)
    return f"☀️ Day goal: {(title or pid_or_text)[:40]}" if ok \
        else "💫 No ☀️ Day Goal section in today's note"


def append_income(amount, label, day=None):
    # a taught-separator answer like "500 · client" splits into head+tail
    # leaving "· client" - shave leading separators, never double them
    label = (label or "").strip().lstrip("·-•").strip()
    p = pm.period_for("daily", day or _today())
    task, _ = ensure_note(p)
    pid, tid = task.get("projectId") or areas.PERIODIC_LIST_ID, task.get("id")
    entry = pm.money_entry_line(amount, label)

    def mutate(doc, live):
        sec = ps.find(doc, pm.SEC_MONEY)
        if sec is None:
            return False
        body = list(sec.body)
        while body and not body[-1].strip():
            body.pop()
        ps.set_body(doc, pm.SEC_MONEY, pm.recompute_money_body(body + [entry]))
        return True
    ok, _doc = _pn_rmw(pid, tid, mutate)
    if not ok:
        return "💫 No 💰 Money section in today's note"
    return f"💰 {pm.fmt_amount(amount)}" + (f" · {label}" if label else "")


_JOURNAL_SECTIONS = {"morning": pm.SEC_MORNING, "evening": pm.SEC_EVENING,
                     "weekly": pm.SEC_WEEKLY_JNL}


def _journal_target(slot):
    if slot == "weekly":
        return pm.period_for("weekly", _today())
    return pm.period_for("daily", _today())


def journal_seed(slot):
    """RMW#1: seed Q/A pairs iff the section has none; unanswered fixed Qs
    get their dynamic text refreshed. Returns (route_keys, pairs, period) -
    keys[n-1] routes answer n (mood/money/rating/highlight land outside the
    journal); pairs carry existing answers so the dialogs skip what's done;
    period PINS the note for the whole dialog run (a run that crosses
    midnight must keep writing the day it started on)."""
    sec_name = _JOURNAL_SECTIONS[slot]
    p = _journal_target(slot)
    task, _ = ensure_note(p)
    pid, tid = task.get("projectId") or areas.PERIODIC_LIST_ID, task.get("id")
    keys_out = []

    def mutate(doc, live):
        ctx = {}
        if slot == "evening":
            gsec = ps.find(doc, pm.SEC_DAY_GOAL)
            ctx["goal"] = pm.day_goal_title(gsec.body) if gsec else ""
        elif slot == "weekly":
            gsec = ps.find(doc, pm.SEC_GOALS)
            ctx["goals"] = "; ".join(pm.goal_titles(gsec.body)[:5]) if gsec else ""
        keys_out[:] = [k for k, _q in pm.journal_fixed(slot, ctx)]
        sec = ps.find(doc, sec_name)
        if sec is None:
            return None
        _seed_slot(doc, sec_name, slot, p.start, ctx)
        return pm.journal_pairs(ps.find(doc, sec_name).body)
    pairs, _doc = _pn_rmw(pid, tid, mutate)
    return keys_out, pairs, p


def journal_merge(slot, answers, period=None):
    """RMW#2: fill collected answers into STILL-EMPTY A-lines (phone wins).
    `period` = the seed-time period (midnight-safe)."""
    sec_name = _JOURNAL_SECTIONS[slot]
    p = period or _journal_target(slot)
    task, _ = ensure_note(p)
    pid, tid = task.get("projectId") or areas.PERIODIC_LIST_ID, task.get("id")

    def mutate(doc, live):
        sec = ps.find(doc, sec_name)
        if sec is None:
            return 0
        merged, filled = pm.merge_journal_answers(sec.body, answers)
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
        return ps.append_body(doc, pm.SEC_GOALS, [line])
    ok, wdoc_out = _pn_rmw(wpid, wtask.get("id"), mutate)
    if not ok:
        return "💫 No 🎯 Goals section in the weekly note"
    wtask["content"] = ps.serialize_sections(wdoc_out)
    if week != "current":
        return "🎯 Goal set for next week"
    # re-mirror today's daily from the fresh weekly body
    dtask = lookup(build_index(), pm.period_for("daily", _today()))
    if dtask:
        gsec = ps.find(wdoc_out, pm.SEC_GOALS)
        goals = [ln for ln in (gsec.body if gsec else []) if ln.strip()]

        def mirror(doc, live):
            if goals:
                ps.set_body(doc, pm.SEC_WEEK_GOALS, goals)
            return True
        _pn_rmw(dtask.get("projectId") or areas.PERIODIC_LIST_ID,
                dtask.get("id"), mirror)
    return "🎯 Goal set"
