"""routines.py - the routine registry (PURE: stdlib only, no I/O).

Vex's routines are TickTick tasks whose steps are subtasks, and each has a
Keyboard Maestro macro that opens the whole workspace for it ("… • Start":
quit and relaunch TickTick, focus + sticky the routine task, place the
stickies and the focus bar, open the apps). The Alfred surface lists them.

The map is CONFIG, never name matching: a renamed macro or a retitled task
must not change which routine a row fires (HANDOFF_ROUTINES §7). Titles are
read LIVE from the cached task, so the emoji Vex puts on the task in
TickTick is the emoji the row shows; LABEL is only the fallback for a task
the cache has not seen yet.

A macro is addressed by UID for the same reason: two macros can share a name
(there are two "YNAB"), and a rename breaks a name link.
"""

ROUTINES_LIST = "6a268ea18f081f1de80eaeb5"      # 🌅 Routines

# key, fallback label, task id, FALLBACK list id, KM macro UID. The list id
# is a hint only: the renderer takes the live task's projectId, so moving a
# routine between lists never breaks its row (Vex moved 🌓 Quarterly Review
# out of 🌓 Quarterly Retreat into 🌅 Routines hours after it was minted).
ROUTINES = (
    {"key": "startup", "label": "🌅 Startup",
     "tid": "6a9faa51635ed1022425af34", "pid": ROUTINES_LIST,
     "macro": "3BE75925-603A-4962-98B1-55686A7DDE6C",
     "habit": "6aa5379e8f081102b4f0d1ec"},          # 🌅 Startup (daily)
    {"key": "shutdown", "label": "🌆 Shutdown",
     "tid": "6a268ea28f081f1de80eb10b", "pid": ROUTINES_LIST,
     "macro": "D896DA99-5DD0-4247-9C4E-17DA9E657009",
     "habit": "6aa537a58f087a63208091fe"},          # 🌆 Shutdown (daily)
    {"key": "weekly", "label": "♻️ Weekly Review",
     "tid": "6aa4eaad7c035e06a3686a2f", "pid": ROUTINES_LIST,
     "macro": "676A175C-92D8-4F5E-9A66-B81E0E4AE6AC",
     "habit": "6a271b2ce2995158ed6ab3a6"},          # Weekly Review (Sun)
    {"key": "monthly", "label": "🗓️ Monthly Review",
     "tid": "6aa517f607a3ba2e0339b7bd", "pid": ROUTINES_LIST,
     "macro": "524BE77F-4BEE-4B8D-AC16-34F128D616DD",
     "habit": "6a271bbda9b89158ed6ab457"},          # Monthly Review (30d)
    {"key": "quarterly", "label": "🌓 Quarterly Review",
     "tid": "6aa520b28f084b1907ea08e2", "pid": ROUTINES_LIST,
     "macro": "28115256-AF19-42FC-A6DA-5CAF2F18D6C6",
     "habit": "6a271c1c30a9d158ed6ab8ad"},          # Quarterly Retreat (90d)
)

_HEX = "0123456789abcdefABCDEF"


def by_key(key):
    """The routine with this key, or None."""
    return next((r for r in ROUTINES if r["key"] == key), None)


def by_tid(tid):
    """The routine whose task this is, or None."""
    return next((r for r in ROUTINES if r["tid"] == tid), None)


def valid_macro(uid):
    """A KM macro UID is 8-4-4-4-12 hex. Anything else never reaches `open`:
    the row arg rides the XAct road, and that road takes what a row hands it.
    """
    if not uid or len(uid) != 36:
        return False
    groups = uid.split("-")
    if [len(g) for g in groups] != [8, 4, 4, 4, 12]:
        return False
    return all(c in _HEX for g in groups for c in g)


def macro_url(uid):
    """kmtrigger:// URL for a macro UID, or None when the UID is malformed."""
    return f"kmtrigger://macro={uid}" if valid_macro(uid) else None
