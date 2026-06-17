#!/usr/bin/env python3
"""
save_token.py — Alfred Run Script

Stores the TickTick v2 session token (the `t` cookie) into the macOS Keychain
(service `ticktick_v2_token`) so the image-attachment feature can authenticate.
No password needed — works with Sign-in-with-Apple accounts. Re-run whenever the
attach action says the token has expired.

Usage: copy the token to the clipboard, then run this (e.g. an Update-menu item).
  Get the value: TickTick web → DevTools (⌘⌥I) → Application → Cookies →
  https://ticktick.com → copy the value of `t`.

Reads the clipboard, sanity-checks it, verifies it against TickTick, then saves.
"""
import sys
import os
import re
import subprocess

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
sys.path.insert(0, SRC_DIR)

clip = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()

if not clip:
    print("Clipboard empty — copy your TickTick `t` cookie value first")
    sys.exit(1)

# The `t` cookie is a long hex string; catch obvious wrong-paste mistakes.
if not re.fullmatch(r"[0-9A-Fa-f]{64,}", clip):
    print("That doesn't look like a token — copy the `t` cookie value from TickTick")
    sys.exit(1)

# Verify against TickTick before saving (reject only on an explicit auth failure).
verified = ""
try:
    import requests
    import api_v2
    r = requests.get(
        "https://api.ticktick.com/api/v1/attachment/isUnderQuota",
        headers={"x-device": api_v2.X_DEVICE, "user-agent": api_v2.USER_AGENT},
        cookies={"t": clip}, timeout=15,
    )
    if r.status_code in (401, 403):
        print("TickTick rejected that token — copy a fresh `t` cookie and try again")
        sys.exit(1)
    if r.status_code == 200:
        verified = " · verified"
except Exception:
    pass  # offline / transient → save anyway

try:
    subprocess.run(
        ["security", "add-generic-password", "-U",
         "-s", "ticktick_v2_token", "-a", os.environ.get("USER", "ticktick"),
         "-w", clip],
        check=True, capture_output=True,
    )
    print(f"TickTick attachment token saved ✓{verified}")
except subprocess.CalledProcessError:
    print("Couldn't save the token to Keychain")
    sys.exit(1)
