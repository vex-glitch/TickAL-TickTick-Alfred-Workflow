"""periodic_fetch.py — Tier-2 fetchers for periodic notes.

Weather + quote (first external HTTP in the repo) and the three v2 readers
probed live 2026-07-11: GET /api/v2/habits + POST /api/v2/habitCheckins/query,
GET /api/v2/countdown/list, GET /api/v2/pomodoros/timeline (records carry
startTime/endTime/pauseDuration).

CONTRACT: every public function returns None on ANY failure (no token, no
network, unexpected shape) — the engine then leaves that section untouched.
This whole module is the Tier-2 cut seam: delete it and the feature still
ships (the engine imports it inside try/except).
"""
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

_SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SRC, "lib"))       # vendored requests (api_v2 pattern)
import requests                                     # noqa: E402

import cache as cache_store                         # noqa: E402
import config as cfg                                # noqa: E402

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


def get_latlon():
    """Cached in config.json (periodic_lat/lon — manual override honored);
    bootstrapped ONCE via IP geolocation. None → retry next run."""
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
    """'☀️ 24–31°C · rain 10%' — Open-Meteo, no key. Cached ≤3 h per date."""
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
                f"{round(d['temperature_2m_min'][0])}–"
                f"{round(d['temperature_2m_max'][0])}°C · "
                f"rain {int(d['precipitation_probability_max'][0] or 0)}%")
        cache_store.set("pn_weather", {"date": today, "ts": time.time(),
                                       "line": line})
        return line
    except Exception:
        return None


def get_quote():
    """'> "text" — Author' from zenquotes.io, once per date. Deliberately
    easy to discard if it proves naggy."""
    today = date.today().isoformat()
    st = cache_store.get("pn_quote") or {}
    if st.get("date") == today:
        return st.get("line")
    try:
        r = requests.get("https://zenquotes.io/api/today", timeout=_TIMEOUT)
        j = r.json()[0]
        line = f"> “{j['q'].strip()}” — {j['a'].strip()}"
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
        _HABITS = [h for h in rows
                   if h.get("status") == 0 and not h.get("archivedTime")]
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
    """'- ✅ Meditate' / '- ⬜ Meditate' for today. None on any failure."""
    habits = _habits()
    if not habits:
        return None
    today = _stamp(date.today())
    checks = _checkins(today - 1)
    if checks is None:
        return None
    lines = []
    for h in habits[:8]:
        done = any(c.get("checkinStamp") == today and c.get("status", 2) == 2
                   for c in (checks.get(h["id"]) or []))
        lines.append(f"- {'✅' if done else '⬜'} {h.get('name', 'Habit')}")
    return lines


def habit_lines_weekly(d0, d1):
    """'- Meditate · 5/7 · 71%' per habit over [d0, d1]."""
    habits = _habits()
    if not habits:
        return None
    checks = _checkins(_stamp(d0 - timedelta(days=1)))
    if checks is None:
        return None
    days = (d1 - d0).days + 1
    a, b = _stamp(d0), _stamp(d1)
    lines = []
    for h in habits[:8]:
        done = len({c.get("checkinStamp") for c in (checks.get(h["id"]) or [])
                    if a <= (c.get("checkinStamp") or 0) <= b
                    and c.get("status", 2) == 2})
        lines.append(f"- {h.get('name', 'Habit')} · {done}/{days} · "
                     f"{int(done / days * 100)}%")
    return lines


# ── countdowns (v2 countdown/list — probed 2026-07-11) ───────────────────────
_BYDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _cd_date(n):
    try:
        return date(n // 10000, n // 100 % 100, n % 100)
    except Exception:
        return None


def _next_occurrence(cd, today):
    """(days_delta, suffix) — positive = ahead. Handles the common RRULEs
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
        return ahead, ""
    if "FREQ=MONTHLY" in rule:
        dom = target.day
        for k in range(0, 62):
            cand = today + timedelta(days=k)
            if cand.day == dom:
                return k, ""
        return None
    if "FREQ=YEARLY" in rule or cd.get("ignoreYear"):
        cand = target.replace(year=today.year)
        if cand < today:
            cand = target.replace(year=today.year + 1)
        return (cand - today).days, ""
    delta = (target - today).days
    if delta >= 0:
        return delta, ""
    return -delta, " since"


def countdown_lines():
    """'- Name · 23d' soonest-first (cap 6); '· today' at zero. None on
    reader failure."""
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
    return [line for _k, line in sorted(rows)[:6]]
