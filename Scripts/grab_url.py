#!/usr/bin/env python3
"""
grab_url.py - Alfred Run Script

Grab the front browser tab's URL + title, build a markdown link, and hand it to
the Add Task flow as the `prefill_note` session variable. The add window then
opens "as usual" (empty title for you to type) with the link already sitting in
the task description - and every follow-up action (time / duration / reminder /
list) still works, because the link rides along as a variable, not as typed text.

Two ways in:
  • Hotkey ▸ [Run Script: grab_url.py] ▸ [Call External Trigger "TT"]
      - the browser is still frontmost, so its tab is read directly.
  • Main menu "Save link / URL" ▸ conditional (arg "URL") ▸ same Run Script
      - here Alfred is frontmost, so we probe running browsers instead.

Run Script config: language /bin/bash, no input needed:
    bash "Scripts/py.sh" "Scripts/grab_url.py"
Call External Trigger: id "TT", passinputasargument ON, passvariables ON.

Cross-browser: Safari family + every Chromium browser (Chrome, Brave, Edge,
Arc, Vivaldi, Opera, …) via AppleScript. Other browsers (e.g. Firefox) report a
friendly message in the add window rather than failing silently - no clipboard
or keystroke side effects.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


def emit(variables):
    """Print the envelope a Run Script uses to pass variables onward to TT."""
    print(json.dumps({"alfredworkflow": {"arg": "", "variables": variables}}))


try:
    import browser_tab as bt
except Exception as _e:                     # src/ unreachable: say so, don't die
    emit({"prefill_error": f"Could not load the browser reader: {_e}"})
    raise SystemExit(0)


def md_link(url, title):
    """Build a markdown link, sanitised so it can't break the [..](..) syntax."""
    title = " ".join((title or "").split())            # collapse whitespace/newlines
    if not title:
        return url
    title = title.replace("[", "(").replace("]", ")")   # ] would close the label
    if any(c in url for c in " ()"):                    # CommonMark angle-bracket form
        return f"[{title}](<{url}>)"
    return f"[{title}]({url})"


def main():
    # Frontmost first (hotkey path: the browser is still in front), then the
    # running browsers in priority order (menu path: Alfred is frontmost).
    # browser_tab owns both, and the add bar's `u ` prefix reads the same tab
    # through its cached() door.
    front = bt.frontmost_app()
    _app, url, title = bt.front_tab(front=front)

    if url:
        emit({"prefill_note": md_link(url, title)})
    elif bt.family(front) is None and front:
        emit({"prefill_error": "No browser tab to read · open a page in Safari "
                               "or a Chromium browser (Chrome, Brave, Edge, Arc…)"})
    else:
        emit({"prefill_error": f"Couldn't read the current tab's URL from {front}"})


if __name__ == "__main__":
    main()
