"""
TickTick internal v2 API client - quarantined.

The official Open API (src/api.py, OAuth) has no attachment endpoint, so image
attachments go through TickTick's own internal API. Kept SEPARATE from api.py so
this fragile, undocumented surface stays contained - v1 features keep working
regardless of v2 breakage.

Confirmed by capturing + reproducing the web app's requests:

  LOGIN   POST https://api.ticktick.com/api/v2/user/signon?wc=true&remember=true
          json {"username","password"} + x-device header  →  {"token": …}
          (TickTick rate-limits logins - see remainderTimes - so we cache the
           token and only log in when there isn't a valid one.)

  UPLOAD  POST https://api.ticktick.com/api/v1/attachment/upload/{projectId}/{taskId}/{attachmentId}
          multipart field "file"; auth = cookie t=<token> + x-device.
          (CSRF is NOT required - verified.) {attachmentId} is a client-generated
          24-hex ObjectId. The upload alone attaches + renders + syncs the image;
          no follow-up task update needed.

Credentials: a one-time masked sign-in (xact v2login) or a pasted session
token (Scripts/save_token.py - the Sign-in-with-Apple path). Only the session
token is ever stored: Keychain `ticktick_v2_token` or config.json (0600) -
never a password, and nothing in the Configure panel (Alfred prefs are
plaintext and often cloud-synced).
"""
import os
import re
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

# The x-device id is generated PER INSTALL (cached in config.json) - never a
# fingerprint baked into shipped source.
X_DEVICE_TMPL = ('{{"platform":"web","os":"macOS","device":"Chrome","name":"",'
                 '"version":8101,"id":"{did}","channel":"website",'
                 '"campaign":"","websocket":""}}')
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")


def _device_id():
    did = cfg.load().get("v2_device_id", "")
    if not re.fullmatch(r"[0-9a-f]{24}", did):
        did = new_object_id()
        data = cfg.load()
        data["v2_device_id"] = did
        cfg.save(data)
    return did


def _base_headers():
    return {"x-device": X_DEVICE_TMPL.format(did=_device_id()),
            "user-agent": USER_AGENT}


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


def _store_token(token):
    """Persist the session token to BOTH stores. The Keychain is read FIRST
    (see __init__), so a signon that only refreshed config.json left any stale
    Keychain entry shadowing the fresh token forever (bit us 2026-07-19).
    Write via `security -i` - the whole command arrives on stdin, so the value
    never hits argv/ps AND avoids the interactive `-w` prompt reader, which
    truncates stdin-fed values at 128 chars. Returns True when the Keychain
    write took; config.json is written regardless."""
    ok = False
    # The value gets embedded in a `security -i` command line - refuse anything
    # that could break out of the quoting (real `t` cookies are url-safe).
    if not re.fullmatch(r"[A-Za-z0-9._\-]+", token or ""):
        cfg.save_v2_token(token)
        return False
    try:
        cmd = ('add-generic-password -U -s ticktick_v2_token -a "{}" -w "{}"\n'
               .format(os.environ.get("USER", "ticktick"), token))
        r = subprocess.run(["security", "-i"], input=cmd.encode(),
                           capture_output=True)
        ok = (r.returncode == 0
              and _keychain("ticktick_v2_token") == token)
    except Exception:
        pass
    cfg.save_v2_token(token)
    return ok


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

    def signon(self, user=None, pw=None):
        """Log in → token (cached). Credentials come from the caller (xact
        v2login's masked dialogs); legacy config.json values are a silent
        fallback. Called only when there's no valid token, never in a retry
        loop (login is rate-limited)."""
        user = user or cfg.get_v2_username()
        pw   = pw or cfg.get_v2_password()
        if not user or not pw:
            raise V2AuthError("no session token · run Settings → Attachment Login, "
                              "or paste one via Settings → Attachment Token")
        r = requests.post(SIGNON_URL, json={"username": user, "password": pw},
                          headers={**_base_headers(), "content-type": "application/json"},
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
        _store_token(token)
        return token

    def _upload(self, project_id, task_id, file_bytes, file_name, mime):
        att_id = new_object_id()
        url = f"{UPLOAD_BASE}/{project_id}/{task_id}/{att_id}"
        r = requests.post(
            url,
            headers={**_base_headers(), "origin": "https://ticktick.com",
                     "referer": "https://ticktick.com/", "accept": "*/*"},
            cookies={"t": self.token},
            files={"file": (file_name, file_bytes, mime)},
            timeout=30,
        )
        if r.status_code in (401, 403):
            raise V2AuthError("token expired")
        r.raise_for_status()
        return r.json() if r.text.strip() else {}

    def get_completed(self, days=60, limit=200):
        """Completed tasks across ALL projects - server truth (the Open API
        can't list completed; the old local snapshots only knew workflow-side
        completions). GET /api/v2/project/all/completed, verified 2026-07-07.
        Returns full task dicts incl. completedTime/status/tags/content."""
        from datetime import datetime, timedelta
        now = datetime.now()
        r = requests.get(
            "https://api.ticktick.com/api/v2/project/all/completed",
            params={"from": (now - timedelta(days=days)).strftime("%Y-%m-%d 00:00:00"),
                    "to": now.strftime("%Y-%m-%d 23:59:59"),
                    "limit": limit},
            cookies={"t": self.token}, headers=_base_headers(), timeout=20)
        if r.status_code in (401, 403):
            raise V2AuthError("token expired")
        r.raise_for_status()
        return r.json() if r.text.strip() else []

    def get_abandoned(self, days=60, limit=200):
        """Won't-do ("Abandoned") tasks across ALL projects - same route
        family as get_completed but /closed with a status param
        (probe-verified 2026-07-11). Returns the list on success ([] = the
        account truly has none), None on any failure so callers keep their
        last-known-good cache."""
        if not self.token:
            return None
        from datetime import datetime, timedelta
        now = datetime.now()
        try:
            r = requests.get(
                "https://api.ticktick.com/api/v2/project/all/closed",
                params={"from": (now - timedelta(days=days)).strftime("%Y-%m-%d 00:00:00"),
                        "to": now.strftime("%Y-%m-%d 23:59:59"),
                        "status": "Abandoned", "limit": limit},
                cookies={"t": self.token}, headers=_base_headers(), timeout=20)
            if not r.ok:
                return None
            d = r.json() if r.text.strip() else []
            return d if isinstance(d, list) else None
        except Exception:
            return None

    def abandon_task(self, task):
        """Mark a task Won't Do the way the app does: POST /api/v2/batch/task
        update with status -1 AND a client-stamped completedTime - without the
        stamp the task never enters the closed index (probe-verified
        2026-07-11: v1 carries status -1 but silently drops the stamp).
        `task` = the FULL task dict (v1 GET shape). True on a clean ack."""
        if not self.token or not task.get("id"):
            return False
        from datetime import datetime, timezone
        body = {k: v for k, v in task.items() if not k.startswith("_")}
        body["status"] = -1
        body.setdefault("completedTime", None)
        body["completedTime"] = (body["completedTime"] or
                                 datetime.now(timezone.utc).strftime(
                                     "%Y-%m-%dT%H:%M:%S.000+0000"))
        try:
            r = requests.post(
                "https://api.ticktick.com/api/v2/batch/task",
                headers={**_base_headers(), "cookie": f"t={self.token}",
                         "content-type": "application/json"},
                json={"add": [], "update": [body], "delete": []},
                timeout=15)
            return bool(r.ok) and not (r.json().get("id2error") or {})
        except Exception:
            return False

    def get_tags(self):
        """GET /api/v2/tags - the full tag list incl. `parent` links (the open
        API has no tag endpoint). Returns the list on success ([] = the
        account truly has no tags), None on any failure - callers keep their
        last-known-good tree so a transient blip can't shrink the tags cache."""
        if not self.token:
            return None
        try:
            r = requests.get("https://api.ticktick.com/api/v2/tags",
                             headers={**_base_headers(), "cookie": f"t={self.token}"},
                             timeout=15)
            if not r.ok:
                return None
            d = r.json()
            # 200-with-error-envelope (dict) must not poison the tags_tree cache
            return d if isinstance(d, list) else None
        except Exception:
            return None

    def get_sync_meta(self):
        """One GET /api/v2/batch/check/0 → the metadata the open API hides:
        project groups (folders) WITH names, and native filters WITH rules -
        both with sortOrder (ascending = the sidebar order; probe-verified
        2026-07-09, the dedicated /projectgroups route 404s). Returns
        {"groups": [...], "filters": [...]} on success (possibly empty -
        that IS the account's truth), None on any failure so callers can
        keep their last-known-good caches."""
        if not self.token:
            return None
        try:
            r = requests.get("https://api.ticktick.com/api/v2/batch/check/0",
                             headers={**_base_headers(), "cookie": f"t={self.token}"},
                             timeout=20)
            if not r.ok:
                return None
            d = r.json()
            if not isinstance(d, dict):
                return None
            return {
                "groups": [{"id": g["id"], "name": g["name"],
                            # `or 0` - an explicit JSON null slips past a .get
                            # default and would TypeError the sort downstream
                            "sortOrder": g.get("sortOrder") or 0}
                           for g in (d.get("projectGroups") or [])
                           if g.get("id") and g.get("name")],
                "filters": [{"id": f.get("id", ""), "name": f["name"],
                             "rule": f.get("rule") or "",
                             "sortOrder": f.get("sortOrder") or 0}
                            for f in (d.get("filters") or []) if f.get("name")],
            }
        except Exception:
            return None

    def get_project_groups(self):
        """Back-compat shim - see get_sync_meta."""
        return (self.get_sync_meta() or {"groups": []})["groups"]

    def create_tag(self, label, parent=None):
        """Create a tag, optionally nested under an existing parent tag, via
        POST /api/v2/batch/tag (probe-verified 2026-07-09 incl. nesting).
        True when the server acks without an id2error entry."""
        label = (label or "").strip().lstrip("#")
        if not self.token or not label:
            return False
        try:
            r = requests.post(
                "https://api.ticktick.com/api/v2/batch/tag",
                headers={**_base_headers(), "cookie": f"t={self.token}",
                         "content-type": "application/json"},
                json={"add": [{"label": label, "name": label.lower(),
                               "sortType": "project",
                               "parent": (parent or "").lower().lstrip("#") or None}],
                      "update": []},
                timeout=15)
            return bool(r.ok) and not (r.json().get("id2error") or {})
        except Exception:
            return False

    def delete_tag(self, name):
        """DELETE /api/v2/tag?name= (probe-verified 2026-07-09). Tasks keep
        living - only the tag entity goes. True on a 2xx ack."""
        name = (name or "").strip().lstrip("#").lower()
        if not self.token or not name:
            return False
        try:
            r = requests.delete("https://api.ticktick.com/api/v2/tag",
                                headers={**_base_headers(), "cookie": f"t={self.token}"},
                                params={"name": name}, timeout=15)
            return bool(r.ok)
        except Exception:
            return False

    def upload_attachment(self, project_id, task_id, file_bytes, file_name, mime="image/png"):
        """Upload an image as a real attachment on the task. Uses the saved session
        token; for password accounts it can refresh via signon, but a Sign-in-with-
        Apple account just gets a clear 'recapture token' message when it expires."""
        if not self.token:
            if not self._has_login():
                raise V2AuthError("no session token · run Settings → Attachment "
                                  "Login (or Settings → Attachment Token)")
            self.signon()
            return self._upload(project_id, task_id, file_bytes, file_name, mime)
        try:
            return self._upload(project_id, task_id, file_bytes, file_name, mime)
        except V2AuthError:
            if not self._has_login():
                raise V2AuthError("session expired · run Settings → Attachment "
                                  "Login again (or re-paste it via Settings → "
                                  "Attachment Token)")
            self.signon()  # stored-credential fallback only: refresh once
            return self._upload(project_id, task_id, file_bytes, file_name, mime)
