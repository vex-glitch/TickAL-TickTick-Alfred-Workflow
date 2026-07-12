#!/usr/bin/env python3
"""
auth.py — Run Script
OAuth 2.0 flow for TickTick.
Opens browser to TickTick auth page, captures the redirect,
exchanges the code for a token, saves it to config.
"""
import sys
import os
import plistlib
import subprocess
import secrets
import webbrowser
import urllib.parse
import http.server
import threading

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    from script_base import bootstrap, WORKFLOW_DIR, SRC_DIR
    bootstrap()
except Exception as e:
    print(f"Path error: {e}")
    sys.exit(1)

try:
    import config as cfg
    import requests
except Exception as e:
    print(f"Import error: {e}")
    sys.exit(1)

REDIRECT_URI = "http://localhost:8080"
AUTH_URL     = "https://ticktick.com/oauth/authorize"
TOKEN_URL    = "https://ticktick.com/oauth/token"

LS_PLIST = os.path.expanduser(
    "~/Library/Preferences/com.apple.LaunchServices/"
    "com.apple.launchservices.secure.plist")


def _default_browser_bundle():
    """The user's default https handler bundle id, Safari when unset."""
    try:
        with open(LS_PLIST, "rb") as f:
            for h in plistlib.load(f).get("LSHandlers", []):
                if h.get("LSHandlerURLScheme") == "https":
                    b = h.get("LSHandlerRoleAll") or ""
                    if b and "ticktick" not in b.lower():
                        return b
    except Exception:
        pass
    return "com.apple.Safari"


def _open_in_browser(url):
    """Open the URL in the default BROWSER explicitly (`open -b`).

    A plain `webbrowser.open` runs `open location`, which honors universal
    links — TickTick.app claims the ticktick.com applinks domain, so the
    consent page gets swallowed by the desktop app and the OAuth dance never
    completes (GitHub issue #1). Naming the app bypasses link routing."""
    for bundle in (_default_browser_bundle(), "com.apple.Safari"):
        try:
            if subprocess.run(["open", "-b", bundle, url],
                              capture_output=True).returncode == 0:
                return
        except Exception:
            pass
    webbrowser.open(url)   # last resort — better a hijacked open than none

def main():
    client_id     = cfg.get_client_id()
    client_secret = cfg.get_client_secret()

    if not client_id or not client_secret:
        print("Error: client_id and client_secret are not configured.\nAdd them to the workflow Configure panel.")
        sys.exit(1)

    # ── Build auth URL ────────────────────────────────────────────────────────
    state = secrets.token_urlsafe(16)   # CSRF guard (RFC 8252 §8.9)
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id":     client_id,
        "response_type": "code",
        "redirect_uri":  REDIRECT_URI,
        "scope":         "tasks:read tasks:write",
        "state":         state,
    })

    # ── Local server to capture the redirect ──────────────────────────────────
    code_holder = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in qs and qs.get("state", [""])[0] == state:
                code_holder["code"] = qs["code"][0]
                body = b"<html><body><h2>Done. You can close this tab.</h2></body></html>"
            elif "code" in qs:
                # state mismatch — not our redirect; reject it and keep waiting
                body = (b"<html><body><h2>Login was denied or failed."
                        b" Close this tab and run tlogin again.</h2></body></html>")
            elif "error" in qs:
                code_holder["error"] = qs["error"][0]
                body = (b"<html><body><h2>Login was denied or failed."
                        b" Close this tab and run tlogin again.</h2></body></html>")
            else:
                body = b"<html><body><h2>Waiting for TickTick...</h2></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("localhost", 8080), Handler)
    server.timeout = 15

    # ── Open browser ──────────────────────────────────────────────────────────
    print("Opening TickTick login in your browser...")
    _open_in_browser(auth_url)

    # ── Wait for code (bounded — socketserver's timeout alone never breaks
    # the loop, so an abandoned login used to zombie on port 8080 forever) ──
    import time
    deadline = time.time() + 180
    while ("code" not in code_holder and "error" not in code_holder
           and time.time() < deadline):
        server.handle_request()
    server.server_close()
    if "error" in code_holder:
        print(f"Login denied or failed ({code_holder['error']}). Run tlogin again.")
        sys.exit(1)
    if "code" not in code_holder:
        print("No login within 3 minutes — run tlogin again.")
        sys.exit(1)

    # ── Exchange code for token ───────────────────────────────────────────────
    resp = requests.post(TOKEN_URL,
        data={
            "code":         code_holder["code"],
            "grant_type":   "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        auth=(client_id, client_secret),
    )

    if resp.status_code != 200:
        print(f"Token exchange failed ({resp.status_code}): {resp.text}")
        sys.exit(1)

    token = resp.json().get("access_token")
    if not token:
        print(f"No access_token in response: {resp.text}")
        sys.exit(1)

    # ── Save token ────────────────────────────────────────────────────────────
    data = cfg.load()
    data["token"] = token
    cfg.save(data)

    print("Authenticated successfully. Token saved.")

if __name__ == "__main__":
    main()
