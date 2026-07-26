"""
crm_home.py - ONE source of truth for the CRM home rows.

crm_menu.py (the keyword/hotkey entry) and browse.py render_crmhub
(the in-browse home every ⌃ lands on) were near-twin lists maintained
by hand twice - rows drifted (each home missed four of the other's),
subtitles diverged. Vex simplification green 2026-07-26: both homes
consume THIS list with their own arg mechanics; adding a row here
lands in both, always.

Row defs: key → (title, subtitle, kind, val)
  kind "ctx"  → a browse context (menu wraps it in the conditional's
                browse branch; the hub trampolines xact:crmbrowse)
  kind "xact" → a direct verb arg, identical in both homes.
Per-home ORDER + UID maps preserve each home's muscle memory and
Alfred frecency; keys one home lacked historically are appended at
its tail (the union - the drift this file kills).
"""

ROWS = {
    "cal":     ("📅 Calendar", "Tasks · search · row 1 opens TickTick",
                "ctx", "ctx:crmcal"),
    "cust":    ("👥 Customers", "Leads too · search · row 1 opens TickTick",
                "ctx", "ctx:crmcusts"),
    "logs":    ("🎨 Logbooks", "Archived too · search · row 1 opens TickTick",
                "ctx", "ctx:crmlbs"),
    "week":    ("📆 Week", "Who's coming + needs-booking radar",
                "ctx", "ctx:crmweek"),
    "done":    ("✅ Session done", "Tick off · log · schedule next",
                "ctx", "ctx:crmdone"),
    "next":    ("▶️ Next session", "Pick logbook → S<n>",
                "ctx", "ctx:crmnew:session"),
    "tattoo":  ("➕ New tattoo", "Customer → logbook → S1",
                "ctx", "ctx:crmnew:tattoo"),
    "consult": ("➕ New consultation", "Customer → logbook → schedule",
                "ctx", "ctx:crmnew:consult"),
    "person":  ("➕ New lead / customer", "Dialogs · lead lands in Records",
                "xact", "xact:crmperson"),
    "photos":  ("📸 Photos import", "Selection or clipboard → Eagle + TickTick",
                "ctx", "ctx:tph"),
    "triage":  ("🦅 Eagle triage", "Eagle selection → tattoo folder",
                "ctx", "ctx:triage"),
    "content": ("🎬 Content pipeline", "To edit · To post · Raw queues",
                "ctx", "ctx:contentpl"),
    "backlog": ("📕 Backlog", "Import · past session · adopt task · image · batch",
                "ctx", "ctx:crmback"),
    "sched":   ("📅 Schedule", "Dormant tasks → schedule + link",
                "ctx", "ctx:crmsched"),
    "prep":    ("🔥 Prepare", "Pick booking → prep task",
                "ctx", "ctx:crmprep"),
    "search":  ("🔍 Search", "Everything CRM · / scopes",
                "ctx", "ctx:crmsearch"),
    "log":     ("📝 Log", "Line into a customer / logbook note",
                "ctx", "ctx:crmlog"),
    "stats":   ("📊 Stats", "Earnings + sessions per month",
                "ctx", "ctx:crmstats"),
    "money":   ("💰 Money", "Totals · periods · per customer",
                "ctx", "ctx:crmmoney"),
    "sweep":   ("🦅 Eagle sweep", "Skeleton folders for logbooks missing one",
                "xact", "xact:eaglesweep"),
}

MENU_ORDER = ("cal", "cust", "logs", "week", "done", "next", "tattoo",
              "consult", "person", "backlog", "sched", "prep", "search",
              "money", "stats", "log",
              # union tail - rows the menu historically lacked
              "photos", "triage", "content", "sweep")

HUB_ORDER = ("done", "next", "tattoo", "consult", "person", "photos",
             "triage", "content", "backlog", "sched", "search", "log",
             "stats", "money", "week", "sweep",
             # union tail - rows the hub historically lacked
             "cal", "cust", "logs", "prep")

MENU_UIDS = {"cal": "crm-open-cal", "cust": "crm-open-cust",
             "logs": "crm-open-logs", "week": "crm-week",
             "done": "crm-session-done", "next": "crm-next-session",
             "tattoo": "crm-new-tattoo", "consult": "crm-new-consult",
             "person": "crm-person", "backlog": "crm-backlog",
             "sched": "crm-sched", "prep": "crm-prep",
             "search": "crm-search", "money": "crm-money",
             "stats": "crm-stats", "log": "crm-log"}

HUB_UIDS = {"done": "hub-done", "next": "hub-next", "tattoo": "hub-tattoo",
            "consult": "hub-consult", "person": "hub-person",
            "photos": "hub-photos", "triage": "hub-triage",
            "content": "hub-content", "backlog": "hub-backlog",
            "sched": "hub-sched", "search": "hub-search",
            "log": "hub-log", "stats": "hub-stats", "money": "hub-money",
            "week": "hub-week", "sweep": "hub-eaglesweep"}


def rows_for(order, uids, prefix):
    """(uid, title, subtitle, kind, val) per home."""
    out = []
    for key in order:
        title, subtitle, kind, val = ROWS[key]
        out.append((uids.get(key, f"{prefix}{key}"),
                    title, subtitle, kind, val))
    return out
