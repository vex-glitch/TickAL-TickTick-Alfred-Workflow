#!/usr/bin/env python3
"""
routine_link.py - the clickable-link grammar (PURE: stdlib only, no I/O).
One contract shared by the executor (Scripts/link.py, behind ET "Link")
and the generator (⌘ Actions > ☑️ TickTick Internals).

    alfred://runtrigger/com.vex.tickal/Link/?argument=<verb>[:<tid>[:<pid>]]

ET Link is the ONLY TickAL trigger with Alfred's "Available via URL
Handler" ticked. Alfred never prompts on a URL-fired trigger, so ANY page,
mail or shared TickTick list can fire it: the grammar is closed. Hard verb
allowlist, exact field counts, 24-hex ids, ASCII only, never a raw xact
passthrough, never echo link text back. Add a verb here AND in link.py.

    ping                  toast only (smoke test)
    focus:<tid>[:<pid>]   sticky (best effort) + timer
    sticky:<tid>[:<pid>]  sticky only
    timer:<tid>[:<pid>]   timer only
    pause | resume        the running timer
    journal:<morning|evening>  the periodic journal dialogs. Even with zero
                          input it lazy-mints today's daily and seeds its
                          journal Qs (like any pn open); answers are only
                          what Vex types, the link carries no text
    view:<calendar|countdowns>  destinations the app has NO link for:
                          calendar = ET OpenCalendar's List-menu flow,
                          countdowns = the Alfred ⏳ hub
    note:daily            TODAY's daily note on whatever day the click
                          happens (lazy-mints it). A pasted note link
                          would be stuck on one day; this one never is

Destinations the app routes itself (APP_LINKS) are plain ticktick://
links, no Alfred at all. ⌘ Actions "☑️ TickTick Internals" lists every
link (internal_links) - ONE row, never a row per link (Vex 2026-09-10).

pid is a HINT (the cache's projectId wins), so a list move never breaks a
pasted link. A repeating task keeps its series id through every
completion (each completed instance gets its own id, repeatTaskId points
back), so a routine link lives as long as the series.
"""
import re
from urllib.parse import quote, unquote

BUNDLE  = "com.vex.tickal"
TRIGGER = "Link"
MAX_LEN = 200

TASK_VERBS = ("focus", "sticky", "timer")
BARE_VERBS = ("ping", "pause", "resume")
SLOT_VERBS = {"journal": ("morning", "evening"),
              "view": ("calendar", "countdowns"),
              "note": ("daily",)}

# Plain app links. Probed live 2026-09-10 on TickTick 8.0.75: habit, matrix,
# focus and v1/show smartlists navigate; ticktick://calendar, countdown,
# task and tasks are DEAD (the window stays put) - calendar + countdowns
# ride view: instead.
APP_LINKS = {"habits": "ticktick://habit",
             "focus": "ticktick://focus",
             "matrix": "ticktick://matrix",
             "tasks": "ticktick://v1/show?smartlist=today"}
LABELS = {"focus": "🖥 Focus + sticky", "sticky": "🖥 Sticky", "timer": "🖥 Focus"}

_TID = re.compile(r"[0-9a-f]{24}")
_PID = re.compile(r"[0-9a-f]{24}|inbox\d{6,12}")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def parse(arg):
    """'<verb>[:<tid>[:<pid>]]' → (verb, tid, pid). tid/pid are '' when
    absent; a slot verb carries its slot in the tid position. Raises
    ValueError with a short toast-safe reason (never the link's own text).
    Alfred percent-decodes the argument; a still-encoded one is decoded
    ONCE here, anything double-encoded stays invalid."""
    arg = (arg or "").strip()
    if "%" in arg:
        arg = unquote(arg)
    if not arg:
        raise ValueError("empty link")
    if len(arg) > MAX_LEN or not arg.isascii() or any(c.isspace() for c in arg):
        raise ValueError("malformed link")
    verb, *fields = arg.split(":")
    if verb in BARE_VERBS:
        if fields:
            raise ValueError(f"{verb} takes no id")
        return verb, "", ""
    if verb in SLOT_VERBS:
        if len(fields) != 1 or fields[0] not in SLOT_VERBS[verb]:
            raise ValueError(f"{verb} needs {' or '.join(SLOT_VERBS[verb])}")
        return verb, fields[0], ""
    if verb not in TASK_VERBS:
        raise ValueError("unknown verb")
    if not 1 <= len(fields) <= 2:
        raise ValueError(f"{verb} needs a task id")
    tid = fields[0]
    pid = fields[1] if len(fields) == 2 else ""
    if not _TID.fullmatch(tid):
        raise ValueError("bad task id")
    if pid and not _PID.fullmatch(pid):
        raise ValueError("bad list id")
    return verb, tid, pid


def series_id(tid, *pools):
    """repeatTaskId of a completed/won't-do INSTANCE of a repeating task,
    looked up in the given task lists (the caller passes cache pools),
    else ''. The instance id is dead the moment it completes; links heal
    to the series on both sides (generator + executor)."""
    for pool in pools:
        for t in pool or ():
            if t.get("id") == tid:
                s = t.get("repeatTaskId") or ""
                return s if s != tid and _TID.fullmatch(s) else ""
    return ""


def url(verb, tid="", pid=""):
    """The clickable URL. Round-trips through parse() first, so the
    generator can never mint a link the executor refuses. The argument is
    fully percent-encoded (':' → %3A): raw colons parse too, but TickTick's
    markdown should never see a bare delimiter."""
    arg = ":".join(p for p in (verb, tid, pid) if p)
    parse(arg)
    return (f"alfred://runtrigger/{BUNDLE}/{TRIGGER}/"
            f"?argument={quote(arg, safe='')}")


def markdown(title, verb, tid, pid=""):
    """'[🖥 Focus <title>](url)', ready to paste into a TickTick description.
    Markdown links in the title flatten to their text; brackets and
    backslashes drop (a bracket ends the link text early, a trailing
    backslash escapes the closing one); capped at 40 chars. 🖥 = Mac
    only: alfred:// has no handler on iPhone."""
    t = _MD_LINK.sub(r"\1", title or "")
    t = re.sub(r"[\[\]\\]", "", t).strip()[:40].strip()
    label = LABELS.get(verb, "🖥 " + verb)
    text = f"{label} {t}" if t else label
    return f"[{text}]({url(verb, tid, pid)})"


def _task_md(title, verb, tid, pid):
    try:
        return markdown(title, verb, tid, pid)
    except ValueError:
        return markdown(title, verb, tid)      # pid is only a hint


def internal_links(title="", tid="", pid="", periodic=True):
    """The ☑️ TickTick Internals list: [(key, row title, subtitle, markdown)].
    Item rows only for a valid tid (callers heal a completed instance to
    its series first); destinations + periodic rows (daily note, journals:
    only when periodic notes are set up) are item-free. 🖥 in the
    link text = rides Alfred, Mac only."""
    rows = []
    if tid:
        try:
            rows += [("focus", "🖥 Focus + sticky", "Sticky + timer",
                      _task_md(title, "focus", tid, pid)),
                     ("sticky", "🗒️ Sticky", "Sticky only",
                      _task_md(title, "sticky", tid, pid)),
                     ("timer", "⏱ Focus", "Timer only",
                      _task_md(title, "timer", tid, pid))]
        except ValueError:
            rows = []
    rows += [
        ("calendar", "📅 Calendar", "App calendar",
         f"[🖥 Calendar]({url('view', 'calendar')})"),
        ("habits", "🔄 Habits", "App habits", f"[🔄 Habits]({APP_LINKS['habits']})"),
        ("focusview", "🍅 Focus view", "App focus tab", f"[🍅 Focus]({APP_LINKS['focus']})"),
        ("matrix", "🧭 Matrix", "App matrix", f"[🧭 Matrix]({APP_LINKS['matrix']})"),
        ("countdowns", "⏳ Countdowns", "Alfred hub, app has no link",
         f"[🖥 Countdowns]({url('view', 'countdowns')})"),
        ("tasks", "✅ Tasks", "App Today list", f"[✅ Tasks]({APP_LINKS['tasks']})"),
    ]
    if periodic:
        rows += [("daily", "💫 Daily note", "Always today's",
                  f"[🖥 Daily note]({url('note', 'daily')})"),
                 ("morning", "🌅 Morning journal", "Journal dialogs",
                  f"[🖥 Morning journal]({url('journal', 'morning')})"),
                 ("evening", "🌙 Evening journal", "Journal dialogs",
                  f"[🖥 Evening journal]({url('journal', 'evening')})")]
    return rows
