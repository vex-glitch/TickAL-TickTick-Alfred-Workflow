"""routine_runner.py - the routine step model (PURE: stdlib only, no I/O).

A routine is a workspace opener: quit and relaunch an app, place windows,
run a few TickAL link verbs, open a URL. Keyboard Maestro used to hold that
list; this module is the same list as DATA, so the workflow needs no KM and
works out of the box (Vex 2026-09-12: "it would be nicer if the workflow is
not dependant ... might be nice for it all to work out of the box").

A step is a dict {"do": <type>, …}:

    {"do": "quit",     "app": <bundle id>[, "secs": 15]}
    {"do": "activate", "app": <bundle id>[, "wait": true]}
    {"do": "hide_others"}
    {"do": "place",    "app": <bundle id>, "frame": [x, y, w, h]}
    {"do": "link",     "arg": "<link verb>"[, "sticky": [x,y,w,h]][, "bar": [x,y]]}
    {"do": "url",      "url": "<url>"}
    {"do": "pause",    "secs": 3}
    {"do": "key",      "key": "escape"[, "mods": ["shift", …]]}

`arg` may carry {tid} and {pid}: they expand to the routine's own task, so a
step list stays portable when a task is recreated or the file is shared.

Frames are AX coordinates (main screen top-left = 0,0, y down), the same
numbers the KM macros carried, so a ported list lands pixel for pixel.
"""

STEP_TYPES = ("quit", "activate", "hide_others", "place", "link", "url",
              "pause", "key")
KEYS = {"escape": 53, "return": 36, "tab": 48, "space": 49, "delete": 51,
        "f4": 118, "f6": 97}
MODS = ("command", "shift", "option", "control")
MAX_PAUSE = 60          # a step list is a workspace opener, not a scheduler
MAX_STEPS = 60


def expand(step, tid="", pid=""):
    """A copy of the step with {tid}/{pid} filled in."""
    out = dict(step)
    if isinstance(out.get("arg"), str):
        out["arg"] = out["arg"].replace("{tid}", tid).replace("{pid}", pid)
    if isinstance(out.get("url"), str):
        out["url"] = out["url"].replace("{tid}", tid).replace("{pid}", pid)
    return out


def _frame_ok(v, n):
    return (isinstance(v, (list, tuple)) and len(v) == n
            and all(isinstance(x, (int, float)) for x in v))


def validate(steps):
    """[] when every step is runnable, else a list of human problems. The
    runner refuses a list with ANY problem: half a workspace is worse than
    none, and a typo in a hand-edited file must not leave TickTick quit."""
    out = []
    if not isinstance(steps, list) or not steps:
        return ["no steps"]
    if len(steps) > MAX_STEPS:
        return [f"{len(steps)} steps (max {MAX_STEPS})"]
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            out.append(f"step {i}: not a dict")
            continue
        kind = s.get("do")
        if kind not in STEP_TYPES:
            out.append(f"step {i}: unknown do={kind!r}")
            continue
        if kind in ("quit", "activate", "place") and not s.get("app"):
            out.append(f"step {i}: {kind} needs app (a bundle id)")
        if kind == "place" and not _frame_ok(s.get("frame"), 4):
            out.append(f"step {i}: place needs frame [x, y, w, h]")
        if kind == "link":
            if not isinstance(s.get("arg"), str) or not s["arg"]:
                out.append(f"step {i}: link needs arg")
            if "sticky" in s and not _frame_ok(s["sticky"], 4):
                out.append(f"step {i}: sticky must be [x, y, w, h]")
            if "bar" in s and not _frame_ok(s["bar"], 2):
                out.append(f"step {i}: bar must be [x, y]")
        if kind == "url" and not isinstance(s.get("url"), str):
            out.append(f"step {i}: url needs url")
        if kind in ("pause", "quit"):
            secs = s.get("secs", 1)
            if not isinstance(secs, (int, float)) or not 0 <= secs <= MAX_PAUSE:
                out.append(f"step {i}: secs must be 0..{MAX_PAUSE}")
        if kind == "key":
            if s.get("key") not in KEYS:
                out.append(f"step {i}: key must be one of {', '.join(sorted(KEYS))}")
            if any(m not in MODS for m in s.get("mods") or []):
                out.append(f"step {i}: mods must be from {', '.join(MODS)}")
    return out


def describe(step):
    """One caveman line for the log and the dry run."""
    k = step.get("do")
    if k == "quit":
        return f"quit {step['app']}"
    if k == "activate":
        return f"open {step['app']}" + (" (wait)" if step.get("wait") else "")
    if k == "hide_others":
        return "hide others"
    if k == "place":
        x, y, w, h = step["frame"]
        return f"place {step['app']} at {x:g},{y:g} {w:g}x{h:g}"
    if k == "link":
        bits = [step["arg"]]
        if step.get("sticky"):
            bits.append("sticky " + ",".join(f"{v:g}" for v in step["sticky"]))
        if step.get("bar"):
            bits.append("bar " + ",".join(f"{v:g}" for v in step["bar"]))
        return "link " + " · ".join(bits)
    if k == "url":
        return f"open {step['url'][:60]}"
    if k == "pause":
        return f"wait {step.get('secs', 1):g}s"
    if k == "key":
        return "press " + "+".join((step.get("mods") or []) + [step["key"]])
    return str(k)


def default_steps(spec="daily"):
    """What a routine does with no config of its own: focus the task with its
    sticky, open the period note, show the calendar. No app juggling, no
    frames - a published user gets something that works, and layout is what
    the config file adds."""
    return [
        {"do": "activate", "app": "com.TickTick.task.mac", "wait": True},
        {"do": "link", "arg": "focus:{tid}:{pid}"},
        {"do": "link", "arg": f"notesticky:{spec}"},
        {"do": "link", "arg": "view:calendar"},
    ]
