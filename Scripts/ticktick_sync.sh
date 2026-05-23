#!/bin/bash
# Syncs TickTick and returns focus to the previously active app

osascript <<'EOF'
set previousApp to name of (info for (path to frontmost application))

tell application "TickTick" to activate
delay 0.5

tell application "System Events"
    tell process "TickTick"
        keystroke "s" using command down
    end tell
end tell

delay 0.3

tell application previousApp to activate
EOF

echo "TickTick Refreshed"
