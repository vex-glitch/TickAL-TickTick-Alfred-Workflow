#!/usr/bin/env python3
"""
tt_shortcut.py — trigger TickTick's own global shortcuts from Alfred.

Reads the key combination the user assigned in TickTick → Settings →
Shortcuts directly from TickTick's preferences (MASShortcut archives)
and sends the same keystroke via System Events. Self-contained — no
third-party tools required.

$1 = tts:<action>   action ∈ quick_add | mini_window | pomo | sticky
"""
import sys
import time
import plistlib
import subprocess

DOMAIN = "com.TickTick.task.mac"

PREF_KEYS = {
    "quick_add":   "TKQuickAddTaskHotkeyIdentifier",
    "mini_window": "TKShowOrHideAppHotkeyIdentifier",
    "pomo":        "TTStartOrAbandonPomoHotkeyIdentifier",
    "sticky":      "hotkey_id_new_sticky",
}

LABELS = {
    "quick_add":   "Quick Add",
    "mini_window": "Mini Window",
    "pomo":        "Pomodoro",
    "sticky":      "Sticky Note",
}

# NSEvent modifier flag bits → AppleScript key code modifiers
MOD_FLAGS = [
    (1 << 17, "shift down"),
    (1 << 18, "control down"),
    (1 << 19, "option down"),
    (1 << 20, "command down"),
]


def read_shortcut(pref_key):
    """Returns (keycode, [modifier strings]) or None if not assigned."""
    out = subprocess.run(
        ["defaults", "export", DOMAIN, "-"],
        capture_output=True,
    ).stdout
    blob = plistlib.loads(out).get(pref_key)
    if not blob:
        return None
    inner = plistlib.loads(blob)
    obj = next((o for o in inner.get("$objects", [])
                if isinstance(o, dict) and "KeyCode" in o), None)
    if obj is None:
        return None
    flags = obj.get("ModifierFlags", 0)
    mods = [name for bit, name in MOD_FLAGS if flags & bit]
    return obj["KeyCode"], mods


def fire(pref_key, label=None):
    """Decode the MASShortcut blob for pref_key and send its keystroke via
    System Events. Returns None on success, an error string on failure.
    Importable (xact.py sticky verb) — accepts ANY hotkey_id_* defaults key,
    not just the PREF_KEYS aliases."""
    label = label or pref_key
    shortcut = read_shortcut(pref_key)
    if shortcut is None:
        return (f"No TickTick shortcut set for {label}\n"
                f"Assign one in TickTick → Settings → Shortcuts")
    keycode, mods = shortcut

    # TickTick must be running for its shortcut to land
    running = subprocess.run(["pgrep", "-x", "TickTick"],
                             capture_output=True).returncode == 0
    if not running:
        subprocess.run(["open", "-a", "TickTick"], check=False)
        time.sleep(2)

    using = f" using {{{', '.join(mods)}}}" if mods else ""
    script = f'tell application "System Events" to key code {keycode}{using}'
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return f"{label} failed\n{r.stderr.strip()}"
    return None


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    action = arg[4:] if arg.startswith("tts:") else arg
    pref_key = PREF_KEYS.get(action)
    if not pref_key:
        print(f"Unknown shortcut action: {action}")
        return

    err = fire(pref_key, LABELS[action])
    if err:
        print(err)
    # success → no output → no notification


if __name__ == "__main__":
    main()
