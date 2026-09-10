#!/usr/bin/env python3
"""
routine_link.py - the clickable-link grammar (PURE: stdlib only, no I/O).
One contract shared by the executor (Scripts/link.py, behind ET "Link")
and the generator (⌘ Actions "🖥 Copy focus link").

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
LABELS = {"focus": "🖥 Focus", "sticky": "🖥 Sticky", "timer": "🖥 Timer"}

_TID = re.compile(r"[0-9a-f]{24}")
_PID = re.compile(r"[0-9a-f]{24}|inbox\d{6,12}")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def parse(arg):
    """'<verb>[:<tid>[:<pid>]]' → (verb, tid, pid). tid/pid are '' when
    absent. Raises ValueError with a short toast-safe reason (never the
    link's own text). Alfred percent-decodes the argument; a still-encoded
    one is decoded ONCE here, anything double-encoded stays invalid."""
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
