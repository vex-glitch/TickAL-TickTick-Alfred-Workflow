"""browser_tab.py - the front browser tab's URL and title, cheaply.

Two callers with opposite budgets:

  * Scripts/grab_url.py (the Save link / URL road) runs ONCE per hotkey press
    and the browser is usually still frontmost, so it can afford to ask which
    app that is.
  * The add bar's `u ` link prefix runs on EVERY KEYSTROKE, where Alfred is
    always frontmost and the answer never changes while you type, because you
    are typing in Alfred and not in the browser. So it reads a 2 second cache
    and pays the real probe once per bar session.

Both go through `front_tab()`; only `prefer_front` and the cache differ.

Measured 2026-09-16, cold osascript per call: a bare `return 1` round trip is
~45 ms, `System Events` frontmost ~180 ms and its running-app list ~260 ms.
`/bin/ps -xco command` answers the same running question in ~30 ms, so that
is what the hot road uses. Asking a browser that is NOT running would LAUNCH
it, which is why nothing here ever tells an app it did not first see in that
list.
"""
import json
import os
import signal
import subprocess
import time

# Chromium-family apps all share the `active tab of front window` dialect.
CHROMIUM = {
    "Google Chrome", "Google Chrome Canary", "Google Chrome Beta",
    "Google Chrome Dev", "Chromium",
    "Brave Browser", "Brave Browser Beta", "Brave Browser Nightly",
    "Microsoft Edge", "Microsoft Edge Beta", "Microsoft Edge Dev",
    "Microsoft Edge Canary",
    "Vivaldi", "Opera", "Opera GX", "Opera Beta",
    "Arc", "Dia", "Sidekick", "Yandex", "Min",
}
# Safari family uses `current tab of front window`, title property is `name`.
SAFARI = {"Safari", "Safari Technology Preview", "WebKit"}

# Probe order when the frontmost app is not a browser (invoked from Alfred).
# Most-likely-primary browsers first.
PRIORITY = [
    "Safari", "Google Chrome", "Arc", "Brave Browser", "Microsoft Edge",
    "Vivaldi", "Opera", "Chromium", "Safari Technology Preview",
]

SCHEMES = ("http://", "https://", "file://")
CACHE = "tickal_browser_tab.json"
MAX_AGE = 2.0          # seconds; see the module docstring for why this is safe
HOT = 1.0              # per browser, on the per-keystroke road
HOT_BUDGET = 1.6       # for the whole probe, however many browsers are open


def _osa(script, timeout=5):
    """Run a one-liner AppleScript; return stripped stdout, or None.

    Its own process group, killed in a finally: an app that does not answer
    the Apple Event (beachballed, a modal sheet, or the first-run "Alfred
    wants to control Safari" prompt) holds osascript open, and the add bar's
    script filter is set to TERMINATE the previous run - so the python that
    would have enforced the timeout is the process Alfred kills. Without the
    group kill every keystroke would leave another osascript queued against
    the same unresponsive app.
    """
    proc = None
    try:
        proc = subprocess.Popen(["osascript", "-e", script],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        out, _err = proc.communicate(timeout=timeout)
        if proc.returncode == 0:
            return out.strip()
    except Exception:
        pass
    finally:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                proc.wait(timeout=1)
            except Exception:
                pass
    return None


def frontmost_app():
    """The app in front. ~180 ms, so only the hotkey road should ask."""
    return _osa('tell application "System Events" to get name of first '
                'application process whose frontmost is true') or ""


def running_apps():
    """Names of THIS USER's running processes. `ps` rather than System Events:
    8x cheaper, and an exact name match is enough (the Safari helper agents
    that run without Safari are all named something else).

    No `-a`: that spans every login session, so another account's Safari under
    fast user switching would pass the guard and `tell application "Safari"`
    would then LAUNCH Safari in this one - the exact thing the guard exists
    to stop."""
    try:
        out = subprocess.run(["/bin/ps", "-xco", "command"],
                             capture_output=True, text=True, timeout=5)
    except Exception:
        return set()
    return {ln.strip() for ln in out.stdout.splitlines() if ln.strip()}


def family(app):
    if app in CHROMIUM:
        return "chromium"
    if app in SAFARI:
        return "safari"
    return None


def read(app, timeout=5):
    """(url, title) from a known, RUNNING browser, or (None, None). One
    osascript for both: two calls would double the only real cost here.
    `timeout` is PER BROWSER, not per probe."""
    fam = family(app)
    if fam == "chromium":
        tab, prop = "active tab of front window", "title"
    elif fam == "safari":
        tab, prop = "current tab of front window", "name"
    else:
        return None, None
    out = _osa(f'tell application "{app}" to return (URL of {tab}) '
               f'& linefeed & ({prop} of {tab})', timeout=timeout)
    if not out:
        return None, None
    url, _, title = out.partition("\n")
    url = url.strip()
    if not url.startswith(SCHEMES):
        return None, None
    title = " ".join(title.split())
    return url, ("" if title == "missing value" else title)


def front_tab(prefer_front=True, front=None, timeout=5, budget=None):
    """(app, url, title), or ("", None, None) when no browser has a page.

    `prefer_front` asks which app is frontmost first - right for a hotkey
    fired while the browser is still in front, wasted (~180 ms) when the
    caller already knows Alfred is frontmost. `front` passes in an answer the
    caller already has, so nothing is asked twice.

    `budget` caps the WHOLE walk in seconds: `timeout` is per browser, and
    nine unresponsive browsers would otherwise cost nine times that.
    """
    if front is None:
        front = frontmost_app() if prefer_front else ""
    if front and family(front):
        url, title = read(front, timeout)
        if url:
            return front, url, title
    running = running_apps()
    deadline = None if budget is None else time.time() + budget
    for app in PRIORITY:
        if app == front or app not in running:
            continue
        if deadline is not None and time.time() >= deadline:
            break
        url, title = read(app, timeout)
        if url:
            return app, url, title
    return "", None, None


def _cache_path():
    try:
        from script_base import run_path
        return run_path(CACHE)
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".ticktick_alfred",
                            "run", CACHE)


def cached(max_age=MAX_AGE, now=None):
    """front_tab() for a per-keystroke caller: {app, url, title}, url "" when
    there is no tab to offer. A MISS is cached too, or a machine with no
    browser open would re-probe on every letter typed."""
    stamped = now
    now = time.time() if now is None else now
    path = _cache_path()
    try:
        with open(path) as f:
            hit = json.load(f)
        age = now - float(hit.get("t") or 0)
        if isinstance(hit, dict) and 0 <= age < max_age:
            return {"app": hit.get("app") or "", "url": hit.get("url") or "",
                    "title": hit.get("title") or ""}
    except Exception:
        pass
    app, url, title = front_tab(prefer_front=False, timeout=HOT,
                                budget=HOT_BUDGET)
    fresh = {"app": app or "", "url": url or "", "title": title or ""}
    try:
        with open(path, "w") as f:
            # The ANSWER's time, not the question's: a probe slower than
            # max_age would otherwise write an already-expired entry and
            # every keystroke would probe again, forever.
            json.dump(dict(fresh, t=stamped if stamped is not None
                           else time.time()), f)
    except OSError:
        pass
    return fresh
