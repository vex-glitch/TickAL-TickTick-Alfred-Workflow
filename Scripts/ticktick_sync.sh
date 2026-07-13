#!/bin/bash
# Syncs the TickTick app in the background via its File > Sync menu item.
# System Events can click a background app's menus without activating it,
# so the frontmost app keeps focus. (The old approach activated TickTick,
# sent ⌘S, then re-activated the "previous" app - and whenever that app
# was Finder, macOS treated the activation like a Dock click and popped
# open a Finder window.)

osascript -e 'tell application "System Events" to tell process "TickTick" to click menu item "Sync" of menu "File" of menu bar 1' >/dev/null 2>&1

echo "TickTick Refreshed"
