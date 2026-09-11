#!/usr/bin/env python3
"""
tt_shortcut.py - trigger TickTick's own global shortcuts from Alfred.

Reads the key combination the user assigned in TickTick → Settings →
Shortcuts directly from TickTick's preferences (MASShortcut archives)
and sends the same keystroke via System Events. Self-contained - no
third-party tools required.

$1 = tts:<action>   action ∈ quick_add | mini_window | pomo | sticky
"""
import os
import sys
import time
import plistlib
import subprocess

DOMAIN = "com.TickTick.task.mac"
# TickTick is sandboxed: its prefs live in its container. CFPreferences given
# that plist's PATH as the app id reads ONE key through cfprefsd in ~0.05 s.
# `defaults export` of the whole domain reads the container file itself and
# can block behind macOS's app-data gate (hung for minutes from a Claude
# shell 2026-09-11), so it is only the fallback, and time-boxed.
CONTAINER_PREFS = os.path.expanduser(
    f"~/Library/Containers/{DOMAIN}/Data/Library/Preferences/{DOMAIN}")
EXPORT_TIMEOUT = 5

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


def _cf_data(key):
    """The key's raw bytes via CFPreferences (container path first, then
    the plain domain), or None."""
    try:
        import ctypes
        import ctypes.util
        cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFPreferencesCopyAppValue.restype = ctypes.c_void_p
        cf.CFPreferencesCopyAppValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFGetTypeID.restype = ctypes.c_ulong
        cf.CFGetTypeID.argtypes = [ctypes.c_void_p]
        cf.CFDataGetTypeID.restype = ctypes.c_ulong
        cf.CFDataGetLength.restype = ctypes.c_long
        cf.CFDataGetLength.argtypes = [ctypes.c_void_p]
        cf.CFDataGetBytePtr.restype = ctypes.c_void_p
        cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        cf.CFRelease.argtypes = [ctypes.c_void_p]

        def cfstr(s):
            return cf.CFStringCreateWithCString(None, s.encode(), 0x08000100)   # UTF-8

        k = cfstr(key)
        try:
            for app in (CONTAINER_PREFS, DOMAIN):
                a = cfstr(app)
                v = cf.CFPreferencesCopyAppValue(k, a)
                cf.CFRelease(a)
                if not v:
                    continue
                try:
                    if cf.CFGetTypeID(v) == cf.CFDataGetTypeID():
                        return ctypes.string_at(cf.CFDataGetBytePtr(v), cf.CFDataGetLength(v))
                finally:
                    cf.CFRelease(v)
        finally:
            cf.CFRelease(k)
    except Exception:
        pass
    return None


def read_shortcut(pref_key):
    """Returns (keycode, [modifier strings]) or None if not assigned."""
    blob = _cf_data(pref_key)
    if blob is None:
        try:
            out = subprocess.run(["defaults", "export", DOMAIN, "-"],
                                 capture_output=True, timeout=EXPORT_TIMEOUT).stdout
            blob = plistlib.loads(out).get(pref_key)
        except (subprocess.TimeoutExpired, OSError, ValueError, plistlib.InvalidFileException):
            blob = None
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
    Importable (xact.py sticky verb) - accepts ANY hotkey_id_* defaults key,
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
