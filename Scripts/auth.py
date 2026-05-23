#!/usr/bin/env python3
"""
auth.py — Run Script
OAuth 2.0 flow for TickTick.
Opens browser to TickTick auth page, captures the redirect,
exchanges the code for a token, saves it to config.
"""
import sys
import os
import webbrowser
import urllib.parse
import http.server
import threading

try:
    SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
    WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
    SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
    sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
    sys.path.insert(0, SRC_DIR)
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

def main():
    client_id     = cfg.get_client_id()
    client_secret = cfg.get_client_secret()

    if not client_id or not client_secret:
        print("Error: client_id and client_secret are not configured.\nAdd them to the workflow Configure panel.")
        sys.exit(1)

    # ── Build auth URL ────────────────────────────────────────────────────────
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id":     client_id,
        "response_type": "code",
        "redirect_uri":  REDIRECT_URI,
        "scope":         "tasks:read tasks:write",
    })

    # ── Local server to capture the redirect ──────────────────────────────────
    code_holder = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in qs:
                code_holder["code"] = qs["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Done. You can close this tab.</h2></body></html>")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("localhost", 8080), Handler)
    server.timeout = 120

    # ── Open browser ──────────────────────────────────────────────────────────
    print("Opening TickTick login in your browser...")
    webbrowser.open(auth_url)

    # ── Wait for code ─────────────────────────────────────────────────────────
    while "code" not in code_holder:
        server.handle_request()
    server.server_close()

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
