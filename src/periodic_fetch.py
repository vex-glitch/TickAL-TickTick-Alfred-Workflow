"""periodic_fetch.py - Tier-2 fetchers for periodic notes.

Weather + quote (first external HTTP in the repo) and the three v2 readers
probed live 2026-07-11: GET /api/v2/habits + POST /api/v2/habitCheckins/query,
GET /api/v2/countdown/list, GET /api/v2/pomodoros/timeline (records carry
startTime/endTime/pauseDuration).

CONTRACT: every public function returns None on ANY failure (no token, no
network, unexpected shape) - the engine then leaves that section untouched.
This whole module is the Tier-2 cut seam: delete it and the feature still
ships (the engine imports it inside try/except).
"""
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

_SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SRC, "lib"))       # vendored requests (api_v2 pattern)
import requests                                     # noqa: E402

import cache as cache_store                         # noqa: E402
import config as cfg                                # noqa: E402
import habits_model as hm                           # noqa: E402

_TIMEOUT = 3          # external HTTP
_V2_TIMEOUT = 8


# ── v2 plumbing ──────────────────────────────────────────────────────────────
def _v2_get(path, params=None):
    try:
        from api_v2 import TickTickV2, _base_headers
        v2 = TickTickV2()
        if not v2.token:
            return None
        r = requests.get(f"https://api.ticktick.com/api/v2/{path}",
                         params=params or {}, cookies={"t": v2.token},
                         headers=_base_headers(), timeout=_V2_TIMEOUT)
        if not r.ok:
            return None
        return r.json() if r.text.strip() else None
    except Exception:
        return None


def _v2_post(path, body):
    try:
        from api_v2 import TickTickV2, _base_headers
        v2 = TickTickV2()
        if not v2.token:
            return None
        hd = dict(_base_headers())
        hd["content-type"] = "application/json"
        r = requests.post(f"https://api.ticktick.com/api/v2/{path}",
                          json=body, cookies={"t": v2.token}, headers=hd,
                          timeout=_V2_TIMEOUT)
        if not r.ok:
            return None
        return r.json() if r.text.strip() else None
    except Exception:
        return None


# ── weather / quote ──────────────────────────────────────────────────────────
_WMO = [((0,), "☀️"), ((1, 2), "🌤"), ((3,), "☁️"), ((45, 48), "🌫"),
        (tuple(range(51, 68)), "🌦"), (tuple(range(71, 78)), "🌨"),
        ((80, 81, 82), "🌧"), ((85, 86), "🌨"), ((95, 96, 99), "⛈")]


def _wmo_emoji(code):
    for codes, emoji in _WMO:
        if code in codes:
            return emoji
    return "🌡"


def geocode(name):
    """City name → (lat, lon, label) via Open-Meteo's geocoding (no key), or
    None. Used to PIN a location by name instead of guessing it."""
    if not (name or "").strip():
        return None
    try:
        r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": name.strip(), "count": 1,
                                 "language": "en", "format": "json"},
                         timeout=_TIMEOUT)
        hits = (r.json() or {}).get("results") or []
        if not hits:
            return None
        h = hits[0]
        bits = [h.get("name"), h.get("admin1"), h.get("country")]
        label = ", ".join(b for b in bits if b)
        return h["latitude"], h["longitude"], label
    except Exception:
        return None


def pin_place(name):
    """Geocode `name` and pin it in config.json as the weather location.
    Returns the label on success, None on a miss."""
    hit = geocode(name)
    if not hit:
        return None
    lat, lon, label = hit
    data = cfg.load()
    data["periodic_lat"], data["periodic_lon"] = lat, lon
    data["periodic_place"] = label
    data["periodic_geo_pinned"] = True
    cfg.save(data)
    return label


def get_latlon():
    """Cached in config.json (periodic_lat/lon). A PINNED location (set by
    name, periodic_geo_pinned) is final - nothing may overwrite it. Otherwise
    bootstrapped ONCE via IP geolocation, which is only as good as the exit
    node: behind a VPN it reports the VPN's city, which is exactly how this
    ended up frozen on the wrong one (Vex 2026-09-12). None → retry next run.
    """
    data = cfg.load()
    if data.get("periodic_lat") is not None and data.get("periodic_lon") is not None:
        return data["periodic_lat"], data["periodic_lon"]
    try:
        r = requests.get("https://ipwho.is/", timeout=_TIMEOUT)
        j = r.json()
        lat, lon = j.get("latitude"), j.get("longitude")
        if lat is None or lon is None:
            return None
        data["periodic_lat"], data["periodic_lon"] = lat, lon
        cfg.save(data)
        return lat, lon
    except Exception:
        return None


def get_weather():
    """'☀️ 24-31°C · rain 10%' - Open-Meteo, no key. Cached ≤3 h per date."""
    today = date.today().isoformat()
    st = cache_store.get("pn_weather") or {}
    if st.get("date") == today and time.time() - st.get("ts", 0) < 3 * 3600:
        return st.get("line")
    ll = get_latlon()
    if not ll:
        return None
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": ll[0], "longitude": ll[1],
                    "daily": "temperature_2m_max,temperature_2m_min,"
                             "precipitation_probability_max,weather_code",
                    "timezone": "auto", "forecast_days": 1},
            timeout=_TIMEOUT)
        d = r.json()["daily"]
        line = (f"{_wmo_emoji(int(d['weather_code'][0]))} "
                f"{round(d['temperature_2m_min'][0])}-"
                f"{round(d['temperature_2m_max'][0])}°C · "
                f"rain {int(d['precipitation_probability_max'][0] or 0)}%")
        cache_store.set("pn_weather", {"date": today, "ts": time.time(),
                                       "line": line})
        return line
    except Exception:
        return None


def get_quote():
    """'> "text" - Author' from zenquotes.io, once per date. Deliberately
    easy to discard if it proves naggy."""
    today = date.today().isoformat()
    st = cache_store.get("pn_quote") or {}
    if st.get("date") == today:
        return st.get("line")
    try:
        r = requests.get("https://zenquotes.io/api/today", timeout=_TIMEOUT)
        j = r.json()[0]
        line = f"> “{j['q'].strip()}” · {j['a'].strip()}"
        cache_store.set("pn_quote", {"date": today, "line": line})
        return line
    except Exception:
        return None


# ── focus records (v2 pomodoros/timeline) ────────────────────────────────────
_TIMELINE = None


def _timeline():
    global _TIMELINE
    if _TIMELINE is None:
        _TIMELINE = _v2_get("pomodoros/timeline")
    return _TIMELINE


def _rec_local_date(ts):
    try:
        dt = datetime(int(ts[0:4]), int(ts[5:7]), int(ts[8:10]),
                      int(ts[11:13]), int(ts[14:16]), int(ts[17:19]))
        from datetime import timezone
        return dt.replace(tzinfo=timezone.utc).astimezone().date()
    except Exception:
        return None


_TL_MORE = [None, False]     # [every record paged in so far, reached the end]
TL_PAGE = 31                 # records per timeline page (probed 2026-09-19)
TL_MAX_PAGES = 12


def focus_records(d0, d1):
    """The raw focus records whose LOCAL start date is in [d0, d1], PAGED
    back as far as d0 needs: the timeline answers 31 records a call, newest
    first, and ?to=<epoch ms of the oldest startTime> the next 31 older
    (probed 2026-09-19 - one page reached back only eight days). Kept for
    the process like _timeline; page 1 IS _timeline's. None when page 1
    failed; a later page failing keeps what came (the window's oldest days
    may then read short). The okr_stats focus-per-objective reader rides
    this; the older Focus lines still read page 1 alone."""
    first = _timeline()
    if first is None:
        return None
    if _TL_MORE[0] is None:
        _TL_MORE[0] = list(first)
        _TL_MORE[1] = len(first) < TL_PAGE
    recs = _TL_MORE[0]
    pages = 1
    while not _TL_MORE[1] and pages < TL_MAX_PAGES:
        oldest = min((r.get("startTime") or "" for r in recs if r.get("startTime")),
                     default="")
        od = _rec_local_date(oldest) if oldest else None
        if od is None or od < d0:
            break
        try:
            ms = int(datetime.strptime(oldest[:19], "%Y-%m-%dT%H:%M:%S")
                     .replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            break
        page = _v2_get("pomodoros/timeline", {"to": ms})
        pages += 1
        if not page:
            _TL_MORE[1] = True
            break
        seen = {r.get("id") for r in recs}
        recs.extend(r for r in page if r.get("id") not in seen)
        if len(page) < TL_PAGE:
            _TL_MORE[1] = True
    return [r for r in recs
            if (lambda ld: ld is not None and d0 <= ld <= d1)(
                _rec_local_date(r.get("startTime") or ""))]


def focus_minutes(d0, d1):
    """True focused minutes across records whose LOCAL start date ∈ [d0, d1].
    None when the timeline reader failed (line dropped, never fake zeros)."""
    recs = _timeline()
    if recs is None:
        return None
    total = 0.0
    for r in recs:
        ld = _rec_local_date(r.get("startTime") or "")
        if not ld or not (d0 <= ld <= d1):
            continue
        try:
            fmt = "%Y-%m-%dT%H:%M:%S"
            s = datetime.strptime((r["startTime"] or "")[:19], fmt)
            e = datetime.strptime((r["endTime"] or "")[:19], fmt)
            total += max(0.0, (e - s).total_seconds()
                         - float(r.get("pauseDuration") or 0)) / 60.0
        except Exception:
            continue
    return int(round(total))


def focus_by_span(d0, d1):
    """(minutes, top_task_title|None) for the whole span - focus_by_day's
    bucket, one size up, so a MONTH can name the task a week actually went
    into. Same rule: the top task is surfaced only when the span had more
    than one distinct task. None when the timeline reader failed."""
    recs = _timeline()
    if recs is None:
        return None
    total, per_task = 0.0, {}
    for r in recs:
        ld = _rec_local_date(r.get("startTime") or "")
        if not ld or not (d0 <= ld <= d1):
            continue
        try:
            fmt = "%Y-%m-%dT%H:%M:%S"
            st = datetime.strptime((r["startTime"] or "")[:19], fmt)
            en = datetime.strptime((r["endTime"] or "")[:19], fmt)
            mins = max(0.0, (en - st).total_seconds()
                       - float(r.get("pauseDuration") or 0)) / 60.0
        except Exception:
            continue
        total += mins
        # a record's minutes are SPLIT across its tasks, exactly as
        # focus_by_day does it - adding the full span to each would let a
        # two-task pomodoro outrank a longer single-task one
        rtasks = [t for t in (r.get("tasks") or [])
                  if (t.get("title") or "").strip()]
        for tk in rtasks:
            ttl = tk["title"].strip()
            per_task[ttl] = per_task.get(ttl, 0.0) + mins / len(rtasks)
    top = None
    if len(per_task) > 1:
        top = max(per_task.items(), key=lambda kv: kv[1])[0]
    return int(round(total)), top


def focus_by_day(d0, d1):
    """{iso_date: (minutes, top_task_title|None)} for LOCAL start dates in
    [d0, d1]. Top task = the title with the most focused minutes that day,
    surfaced only when the day had MORE than one distinct task.
    None when the timeline reader failed."""
    recs = _timeline()
    if recs is None:
        return None
    days = {}
    for r in recs:
        ld = _rec_local_date(r.get("startTime") or "")
        if not ld or not (d0 <= ld <= d1):
            continue
        try:
            fmt = "%Y-%m-%dT%H:%M:%S"
            s = datetime.strptime((r["startTime"] or "")[:19], fmt)
            e = datetime.strptime((r["endTime"] or "")[:19], fmt)
            mins = max(0.0, (e - s).total_seconds()
                       - float(r.get("pauseDuration") or 0)) / 60.0
        except Exception:
            continue
        iso = ld.isoformat()
        total, by_task = days.get(iso, (0.0, {}))
        rtasks = [t for t in (r.get("tasks") or []) if (t.get("title") or "").strip()]
        for t in rtasks:
            ttl = t.get("title").strip()
            by_task[ttl] = by_task.get(ttl, 0.0) + mins / len(rtasks)
        days[iso] = (total + mins, by_task)
    out = {}
    for iso, (total, by_task) in days.items():
        top = max(by_task.items(), key=lambda kv: kv[1])[0] if len(by_task) > 1 else None
        out[iso] = (int(round(total)), top)
    return out


# ── habits ───────────────────────────────────────────────────────────────────
_HABITS = None


def _habits():
    global _HABITS
    if _HABITS is None:
        rows = _v2_get("habits")
        if rows is None:
            _HABITS = None
            return None
        # status==0 is the only archive flag; archivedTime carries a
        # 2001-01-01 sentinel on NEVER-archived habits - filtering on its
        # truthiness silently dropped live habits (bug caught 2026-07-24)
        _HABITS = [h for h in rows if h.get("status") == 0]
    return _HABITS


def _stamp(d):
    return d.year * 10000 + d.month * 100 + d.day


def _checkins(after):
    habits = _habits()
    if not habits:
        return None
    j = _v2_post("habitCheckins/query",
                 {"habitIds": [h["id"] for h in habits], "afterStamp": after})
    if not isinstance(j, dict):
        return None
    return j.get("checkins") or {}


def habit_lines_daily():
    """'- ✅ Meditate' / '- ⬜ Meditate' for the habits DUE today. None on any
    failure. Vex 2026-09-12: the note listed every habit, so a Sunday review
    and a 30-day one sat there unticked all week pretending to be today's
    work - pm.habit_due reads each habit's own rule."""
    import periodic_model as pm
    habits = _habits()
    if not habits:
        return None
    day = date.today()
    today = _stamp(day)
    checks = _checkins(today - 1)
    if checks is None:
        return None
    habits = [h for h in habits
              if pm.habit_due(h.get("repeatRule"), h.get("targetStartDate"), day)]
    lines = []
    for h in habits[:8]:
        done = any(c.get("checkinStamp") == today and c.get("status", 2) == 2
                   for c in (checks.get(h["id"]) or []))
        lines.append(f"- {'✅' if done else '⬜'} {h.get('name', 'Habit')}")
    return lines


def habit_lines_weekly(d0, d1):
    """'- Meditate · 5/7 · 71%' per habit over [d0, d1], each against ITS OWN
    target for that week.

    Vex 2026-09-17: "call mum is shown as 0/7 when it should be happening once
    a week … Actually all of them are showing 7 … There are also some habits
    that are not even supposed to happen this week like monthly and quarterly
    review". The denominator used to be the number of DAYS in the window,
    which is 7 for every habit that ever existed; it is now what the habit's
    own repeatRule asks of that week, and a habit that asks for nothing is not
    listed at all. The cap of 8 lines applies AFTER that filter, so the eight
    that show are eight that are actually due.
    """
    habits = _habits()
    if not habits:
        return None
    checks = _checkins(_stamp(d0 - timedelta(days=1)))
    if checks is None:
        return None
    a, b = _stamp(d0), _stamp(d1)
    lines = []
    for h in habits:
        done = len({c.get("checkinStamp") for c in (checks.get(h["id"]) or [])
                    if a <= (c.get("checkinStamp") or 0) <= b
                    and c.get("status", 2) == 2})
        # target first, but a habit you actually did is never dropped: doing
        # something that was not asked of you this week still counts, and
        # dropping the row would take its check-ins with it
        target = hm.week_target(h, d0, d1) or done
        if not target:
            continue
        # a check-in on a day the habit was not due still counts (TickTick
        # lets you tick any day), so done CAN exceed target - "2/1" is the
        # honest fraction, and the percentage is a consistency score, capped
        lines.append(f"- {h.get('name', 'Habit')} · {done}/{target} · "
                     f"{min(100, int(done / target * 100))}%")
        if len(lines) >= 8:
            break
    return lines


# ── countdowns (v2 countdown/list - probed 2026-07-11) ───────────────────────
_BYDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _cd_date(n):
    try:
        return date(n // 10000, n // 100 % 100, n % 100)
    except Exception:
        return None


def _next_occurrence(cd, today):
    """(days_delta, suffix) - positive = ahead. Handles the common RRULEs
    (WEEKLY/BYDAY, MONTHLY, YEARLY) + ignoreYear anniversaries; past
    non-repeating dates render as '{n}d since' (days-since counters)."""
    target = _cd_date(cd.get("date") or 0)
    if not target:
        return None
    rule = cd.get("repeatFlag") or ""
    if "FREQ=WEEKLY" in rule:
        m = re.search(r"BYDAY=([A-Z,]+)", rule)
        days = sorted(_BYDAY[d] for d in (m.group(1).split(",") if m else [])
                      if d in _BYDAY)
        if not days:
            return None
        ahead = min((d - today.weekday()) % 7 for d in days)
        im = re.search(r"INTERVAL=(\d+)", rule)
        k = int(im.group(1)) if im else 1
        if k > 1:
            # biweekly+ parity, anchored at the entity date's week
            # (mirrors src/countdowns.days_until - keep in step)
            cand = today + timedelta(days=ahead)
            a_mon = target - timedelta(days=target.weekday())
            c_mon = cand - timedelta(days=cand.weekday())
            off = ((c_mon - a_mon).days // 7) % k
            if off:
                cand += timedelta(days=7 * (k - off))
                ahead = (cand - today).days
        return ahead, ""
    if "FREQ=MONTHLY" in rule:
        dom = target.day
        for k in range(0, 62):
            cand = today + timedelta(days=k)
            if cand.day == dom:
                return k, ""
        return None
    if "FREQ=YEARLY" in rule or cd.get("ignoreYear"):
        def _yr(y):   # Feb-29 in a non-leap year clamps to the 28th
            try:
                return target.replace(year=y)
            except ValueError:
                return date(y, target.month, 28)
        cand = _yr(today.year)
        if cand < today:
            cand = _yr(today.year + 1)
        return (cand - today).days, ""
    delta = (target - today).days
    if delta >= 0:
        return delta, ""
    return -delta, " since"


def dates_in_span(d0, d1):
    """'- 🎂 Kira · Thu 3rd Sep' for every countdown LANDING inside [d0, d1],
    by date, earliest first - the calendar half of a monthly note (Vex
    2026-09-17). Past days in the span count: a birthday on the 3rd is still
    what the month held, which is why this walks the occurrence rather than
    asking _next_occurrence how far away it is. None on reader failure."""
    import periodic_model as pm
    j = _v2_get("countdown/list")
    if not isinstance(j, dict):
        return None
    today = date.today()
    rows = []
    for cd in j.get("countdowns") or []:
        if cd.get("status") != 0 or cd.get("archivedTime"):
            continue
        target = _cd_date(cd.get("date") or 0)
        if not target:
            continue
        rule = cd.get("repeatFlag") or ""
        hits = []
        if "FREQ=YEARLY" in rule or cd.get("ignoreYear"):
            for y in {d0.year, d1.year}:          # a span can cross New Year
                try:
                    hits.append(target.replace(year=y))
                except ValueError:                 # 29 Feb in a common year
                    hits.append(date(y, target.month, 28))
        elif "FREQ=MONTHLY" in rule:
            d = d0
            while d <= d1:
                if d.day == target.day:
                    hits.append(d)
                d += timedelta(days=1)
        elif rule:
            continue            # weekly and friends are not calendar dates
        else:
            hits.append(target)
        for h in {x for x in hits if d0 <= x <= d1}:
            glyph = "🎂" if cd.get("type") == 2 else "⏳"
            when = (f"{pm.DAY_ABBR[h.weekday()]} {pm._ord(h.day)} "
                    f"{pm.MONTH_ABBR[h.month]}")
            tail = " · today 🎉" if h == today else ""
            rows.append((h, f"- {glyph} {cd.get('name', '?')} · {when}{tail}"))
    return [line for _d, line in sorted(rows)]


def countdown_lines():
    """'- Name · 23d' soonest-first (cap 4, Vex 2026-09-12 - they were never
    random, just six deep); '· today' at zero. None on reader failure."""
    j = _v2_get("countdown/list")
    if not isinstance(j, dict):
        return None
    today = date.today()
    rows = []
    for cd in j.get("countdowns") or []:
        if cd.get("status") != 0 or cd.get("archivedTime"):
            continue
        try:
            occ = _next_occurrence(cd, today)   # Feb-29 anniversaries raise
        except Exception:
            continue
        if occ is None:
            continue
        n, suffix = occ
        label = "today" if (n == 0 and not suffix) else f"{n}d{suffix}"
        rows.append((n if not suffix else 10000 + n,
                     f"- {cd.get('name', '?')} · {label}"))
    if not rows:
        return None
    return [line for _k, line in sorted(rows)[:4]]


def bday_lines(days=14):
    """'- 🎂 Name · in 3d' - birthday countdowns (type 2) landing inside
    the window, soonest first. None on reader failure, [] when quiet."""
    j = _v2_get("countdown/list")
    if not isinstance(j, dict):
        return None
    today = date.today()
    rows = []
    for cd in j.get("countdowns") or []:
        if cd.get("type") != 2 or cd.get("status") != 0 \
                or cd.get("archivedTime"):
            continue
        try:
            occ = _next_occurrence(cd, today)   # Feb-29 birthdays raise
        except Exception:
            continue
        if occ is None or occ[1]:               # 'since' = not upcoming
            continue
        n = occ[0]
        if n > days:
            continue
        label = "today 🎉" if n == 0 else f"in {n}d"
        rows.append((n, f"- 🎂 {cd.get('name', '?')} · {label}"))
    return [line for _k, line in sorted(rows)]
