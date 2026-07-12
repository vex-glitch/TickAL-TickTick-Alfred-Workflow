#!/usr/bin/env python3
"""
grab_url.py — Alfred Run Script

Grab the front browser tab's URL + title, build a markdown link, and hand it to
the Add Task flow as the `prefill_note` session variable. The add window then
opens "as usual" (empty title for you to type) with the link already sitting in
the task description — and every follow-up action (time / duration / reminder /
list) still works, because the link rides along as a variable, not as typed text.

Two ways in:
  • Hotkey ▸ [Run Script: grab_url.py] ▸ [Call External Trigger "TT"]
      — the browser is still frontmost, so its tab is read directly.
  • Main menu "Save link / URL" ▸ conditional (arg "URL") ▸ same Run Script
      — here Alfred is frontmost, so we probe running browsers instead.

Run Script config: language /bin/bash, no input needed:
    /opt/homebrew/bin/python3 "Scripts/grab_url.py"
Call External Trigger: id "TT", passinputasargument ON, passvariables ON.

Cross-browser: Safari family + every Chromium browser (Chrome, Brave, Edge,
Arc, Vivaldi, Opera, …) via AppleScript. Other browsers (e.g. Firefox) report a
friendly message in the add window rather than failing silently — no clipboard
or keystroke side effects.
"""
import json
import subprocess

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

# Probe order when the frontmost app isn't a browser (e.g. invoked from Alfred's
# menu). Most-likely-primary browsers first.
PRIORITY = [
    "Safari", "Google Chrome", "Arc", "Brave Browser", "Microsoft Edge",
    "Vivaldi", "Opera", "Chromium", "Safari Technology Preview",
]


def _osa(script):
    """Run a one-liner AppleScript; return stripped stdout, or None on failure."""
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def frontmost_app():
    return _osa('tell application "System Events" to get name of first '
                'application process whose frontmost is true') or ""


def running_apps():
    out = _osa('tell application "System Events" to get name of every '
               'application process whose background only is false')
    return {a.strip() for a in (out or "").split(",")}


def family(app):
    if app in CHROMIUM:
        return "chromium"
    if app in SAFARI:
        return "safari"
    return None


def grab_from(app):
    """Read (url, title) from a known browser, or (None, None)."""
    fam = family(app)
    if fam == "chromium":
        tab_spec, title_prop = "active tab of front window", "title"
    elif fam == "safari":
        tab_spec, title_prop = "current tab of front window", "name"
    else:
        return None, None
    url   = _osa(f'tell application "{app}" to get URL of {tab_spec}')
    title = _osa(f'tell application "{app}" to get {title_prop} of {tab_spec}')
    if url and url.startswith(("http://", "https://", "file://")):
        return url, (title or "")
    return None, None


def md_link(url, title):
    """Build a markdown link, sanitised so it can't break the [..](..) syntax."""
    title = " ".join((title or "").split())            # collapse whitespace/newlines
    if not title:
        return url
    title = title.replace("[", "(").replace("]", ")")   # ] would close the label
    if any(c in url for c in " ()"):                    # CommonMark angle-bracket form
        return f"[{title}](<{url}>)"
    return f"[{title}]({url})"


def emit(variables):
    """Print the envelope a Run Script uses to pass variables onward to TT."""
    print(json.dumps({"alfredworkflow": {"arg": "", "variables": variables}}))


def main():
    front = frontmost_app()

    # Frontmost first (hotkey path: the browser is still in front). If that's
    # not a usable browser (menu path: Alfred is frontmost), probe the running
    # browsers in priority order.
    url = title = None
    if family(front):
        url, title = grab_from(front)
    if not url:
        running = running_apps()
        for app in PRIORITY:
            if app == front or app not in running:
                continue
            url, title = grab_from(app)
            if url:
                break

    if url:
        emit({"prefill_note": md_link(url, title)})
    elif family(front) is None and front:
        emit({"prefill_error": "No browser tab to read — open a page in Safari "
                               "or a Chromium browser (Chrome, Brave, Edge, Arc…)"})
    else:
        emit({"prefill_error": f"Couldn't read the current tab's URL from {front}"})


if __name__ == "__main__":
    main()
