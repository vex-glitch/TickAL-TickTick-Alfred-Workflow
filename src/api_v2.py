"""
TickTick internal v2 API client — quarantined.

The official Open API (src/api.py, OAuth) has no attachment endpoint, so image
attachments go through TickTick's own internal API. Kept SEPARATE from api.py so
this fragile, undocumented surface stays contained — v1 features keep working
regardless of v2 breakage.

Confirmed by capturing + reproducing the web app's requests:

  LOGIN   POST https://api.ticktick.com/api/v2/user/signon?wc=true&remember=true
          json {"username","password"} + x-device header  →  {"token": …}
          (TickTick rate-limits logins — see remainderTimes — so we cache the
           token and only log in when there isn't a valid one.)

  UPLOAD  POST https://api.ticktick.com/api/v1/attachment/upload/{projectId}/{taskId}/{attachmentId}
          multipart field "file"; auth = cookie t=<token> + x-device.
          (CSRF is NOT required — verified.) {attachmentId} is a client-generated
          24-hex ObjectId. The upload alone attaches + renders + syncs the image;
          no follow-up task update needed.

Credentials: TickTick email + password from the Configure panel (env vars
tt_username / tt_password); the session token is cached in config.json.
"""
import os
import sys
import time
import secrets
import subprocess

_SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SRC)
sys.path.insert(0, os.path.join(_SRC, "lib"))
import requests  # noqa: E402
import config as cfg  # noqa: E402

SIGNON_URL   = "https://api.ticktick.com/api/v2/user/signon?wc=true&remember=true"
UPLOAD_BASE  = "https://api.ticktick.com/api/v1/attachment/upload"

X_DEVICE = ('{"platform":"web","os":"macOS","device":"Chrome","name":"",'
            '"version":8101,"id":"6a32cb17287e7e132eea4e58","channel":"website",'
            '"campaign":"","websocket":""}')
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")
_BASE_HEADERS = {"x-device": X_DEVICE, "user-agent": USER_AGENT}


class V2AuthError(Exception):
    pass


def new_object_id():
    """TickTick-style 24-hex ObjectId: 8-hex timestamp + 16-hex random."""
    return format(int(time.time()), "08x") + secrets.token_hex(8)


def _keychain(service):
    """Read a secret from the login Keychain (local, encrypted, off iCloud)."""
    try:
        out = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                             capture_output=True, text=True)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


class TickTickV2:
    def __init__(self):
        # Token sources, in order: env (testing) → Keychain (recommended, off
        # iCloud) → config.json. Sign-in-with-Apple accounts have no password, so
        # the token is captured from a logged-in session, not fetched via signon.
        self.token = (os.environ.get("TT_V2_TOKEN")
                      or _keychain("ticktick_v2_token")
                      or cfg.get_v2_token())

    def _has_login(self):
        """True only for username/password accounts (not Sign-in-with-Apple)."""
        return bool(cfg.get_v2_username() and cfg.get_v2_password())

    def signon(self):
        """Log in with the configured email + password → token (cached). Called
        only when there's no valid token, never in a retry loop (login is
        rate-limited)."""
        user = cfg.get_v2_username()
        pw   = cfg.get_v2_password()
        if not user or not pw:
            raise V2AuthError("add your TickTick email + password in the workflow's "
                              "Configure panel (tt_username / tt_password)")
        r = requests.post(SIGNON_URL, json={"username": user, "password": pw},
                          headers={**_BASE_HEADERS, "content-type": "application/json"},
                          timeout=20)
        token = (r.json().get("token") if r.text.strip() else None) if r.ok else None
        if not token:
            # Surface TickTick's message (e.g. wrong password / locked out) plainly.
            msg = ""
            try:
                msg = r.json().get("errorCode") or r.json().get("errorMessage") or ""
            except Exception:
                pass
            raise V2AuthError(f"TickTick login failed ({r.status_code}{': '+msg if msg else ''})")
        self.token = token
        cfg.save_v2_token(token)
        return token

    def _upload(self, project_id, task_id, file_bytes, file_name, mime):
        att_id = new_object_id()
        url = f"{UPLOAD_BASE}/{project_id}/{task_id}/{att_id}"
        r = requests.post(
            url,
            headers={**_BASE_HEADERS, "origin": "https://ticktick.com",
                     "referer": "https://ticktick.com/", "accept": "*/*"},
            cookies={"t": self.token},
            files={"file": (file_name, file_bytes, mime)},
            timeout=30,
        )
        if r.status_code in (401, 403):
            raise V2AuthError("token expired")
        r.raise_for_status()
        return r.json() if r.text.strip() else {}

    def upload_attachment(self, project_id, task_id, file_bytes, file_name, mime="image/png"):
        """Upload an image as a real attachment on the task. Uses the saved session
        token; for password accounts it can refresh via signon, but a Sign-in-with-
        Apple account just gets a clear 'recapture token' message when it expires."""
        if not self.token:
            if not self._has_login():
                raise V2AuthError("no TickTick session token saved — capture it once "
                                  "into the Keychain (service ticktick_v2_token)")
            self.signon()
            return self._upload(project_id, task_id, file_bytes, file_name, mime)
        try:
            return self._upload(project_id, task_id, file_bytes, file_name, mime)
        except V2AuthError:
            if not self._has_login():
                raise V2AuthError("attachment session expired — recapture your "
                                  "TickTick session token (Keychain ticktick_v2_token)")
            self.signon()  # password accounts only: refresh once
            return self._upload(project_id, task_id, file_bytes, file_name, mime)
