"""
crm_home.py - ONE source of truth for the unified home rows.

THE UNIFIED HOME (Vex design 2026-07-28). CRM and Content stopped being
two workflows: one top level, eight rows, and everything that used to
sit up here moved onto the entity it acts on (via the row chords) or
into 🎛 Manage. Vex: "Stuff is all over the place... they are too
similar to be in two different places."

    📅 Calendar · 🎨 Logbooks · 👥 Customers · 🎬 Pipelines
    🎛 Manage   · 💰 Money    · 📊 Stats

(📕 Backlog moved into 🎛 Manage > CRM, Vex 2026-07-28 - it is a
retro-entry chooser, not a daily door.)

Both homes (crm_menu.py = the keyword/hotkey entry, browse.py
render_crmhub = the in-browse home every ⌃ lands on) consume THIS list
with their own arg mechanics; adding a row here lands in both, always.

Row defs: key → (title, static_subtitle, kind, val)
  kind "ctx"  → a browse context (menu wraps it in the conditional's
                browse branch; the hub trampolines xact:crmbrowse)
  kind "xact" → a direct verb arg, identical in both homes.

Subtitles are LIVE where a number helps you decide whether to go there
(Vex: "show stats in description"). subtitles() computes them from the
cache only - no API call - and every row falls back to its static text
if anything raises, so a stats bug can never blank the home.
"""

ROWS = {
    "cal":     ("📅 Calendar", "Bookings · week · row 1 opens TickTick",
                "ctx", "ctx:crmcal"),
    "logs":    ("🎨 Logbooks", "Tattoos · / scopes · row 1 opens TickTick",
                "ctx", "ctx:crmlbs"),
    "cust":    ("👥 Customers", "People · leads too · / scopes",
                "ctx", "ctx:crmcusts"),
    "pipes":   ("🎬 Pipelines", "TV · FM · Studio",
                "ctx", "ctx:contentpl"),
    "manage":  ("🎛 Manage", "New things · backlog · Eagle housekeeping",
                "ctx", "ctx:manage"),
    "money":   ("💰 Money", "Totals · periods · per customer",
                "ctx", "ctx:crmmoney"),
    "stats":   ("📊 Stats", "CRM + content pipeline",
                "ctx", "ctx:stats"),
}

HOME_ORDER = ("cal", "logs", "cust", "pipes",
              "manage", "money", "stats")

# Old uids kept where the row survived, so Alfred frecency carries over.
MENU_UIDS = {"cal": "crm-open-cal", "logs": "crm-open-logs",
             "cust": "crm-open-cust", "pipes": "crm-content",
             "manage": "crm-manage", "money": "crm-money",
             "stats": "crm-stats"}

HUB_UIDS = {"cal": "hub-cal", "logs": "hub-logs", "cust": "hub-cust",
            "pipes": "hub-content", "manage": "hub-manage",
            "money": "hub-money", "stats": "hub-stats"}

# Kept for the legacy screens that still render behind the new tree.
MENU_ORDER = HOME_ORDER
HUB_ORDER = HOME_ORDER


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def subtitles():
    """key → live subtitle. Cache-only, each row independently
    guarded: one failing stat never takes the home down with it."""
    out = {}
    try:
        import areas
        import cache as cache_store
        import crm_records as cr
    except Exception:
        return out

    def guard(key, fn):
        try:
            v = fn()
            if v:
                out[key] = v
        except Exception:
            pass

    def logs():
        lbs = cr.logbook_notes()
        active = [l for l in lbs if not cr.logbook_archived(l)]
        sched = sum(1 for l in active if cr.next_session_task(l["id"]))
        return (f"{_plural(len(lbs), 'tattoo')} · {len(active)} active · "
                f"🟢 {sched} scheduled")

    def cust():
        people = cr.records_notes(areas.CUSTOMER_TAG)
        leads = cr.records_notes(areas.LEAD_TAG)
        seen, n = set(), 0
        for p in people:
            if p["id"] not in seen:
                seen.add(p["id"])
                n += 1
        return (f"{_plural(n, 'customer')}"
                + (f" · 🎣 {len(leads)} leads" if leads else ""))

    def cal():
        import datetime
        from filtering import utc_str_to_local_date
        today = datetime.date.today().isoformat()
        wk_end = (datetime.date.today()
                  + datetime.timedelta(days=7)).isoformat()
        n_today = n_week = dormant = 0
        for t in cache_store.get("all_tasks") or []:
            if ((t.get("_projectId") or t.get("projectId")) != areas.CRM_ID
                    or t.get("status", 0) != 0):
                continue
            due = t.get("dueDate") or t.get("startDate") or ""
            if not due:
                dormant += 1
                continue
            try:
                day = utc_str_to_local_date(due)
            except Exception:
                day = due[:10]
            if day == today:
                n_today += 1
            if today <= day <= wk_end:
                n_week += 1
        bits = [f"{n_week} this week"]
        if n_today:
            bits.insert(0, f"🔴 {n_today} today")
        if dormant:
            bits.append(f"{dormant} unscheduled")
        return " · ".join(bits)

    def pipes():
        states = {"📸raw", "📸edit", "📸post"}
        counts = {}
        for t in cache_store.get("all_tasks") or []:
            pid = t.get("_projectId") or t.get("projectId")
            if t.get("status", 0) != 0:
                continue
            tags = {str(x).lower() for x in (t.get("tags") or [])}
            if not (tags & states):
                continue
            counts[pid] = counts.get(pid, 0) + 1
        bits = []
        for key, (pid, emoji, label) in areas.CONTENT_DESTS.items():
            bits.append(f"{emoji} {counts.get(pid, 0)}")
        return " · ".join(bits) + " open"

    def money():
        import datetime
        mo = datetime.date.today().isoformat()[:7]
        hit = cr.monthly_stats().get(mo)
        if not hit:
            return ""
        total, n, sym, pre = hit
        amt = cr._fmt_money(total, sym or "€", pre)
        return f"{amt} · {_plural(n, 'session')} this month"

    guard("logs", logs)
    guard("cust", cust)
    guard("cal", cal)
    guard("pipes", pipes)
    guard("money", money)
    return out


def rows_for(order, uids, prefix, live=True):
    """(uid, title, subtitle, kind, val) per home - subtitle live where
    a number exists, static otherwise."""
    subs = subtitles() if live else {}
    out = []
    for key in order:
        title, subtitle, kind, val = ROWS[key]
        out.append((uids.get(key, f"{prefix}{key}"),
                    title, subs.get(key) or subtitle, kind, val))
    return out
