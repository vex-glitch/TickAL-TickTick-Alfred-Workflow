"""Token and credential management for TickTick Alfred Workflow."""
import json
import os

CONFIG_DIR = os.path.expanduser("~/.ticktick_alfred")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "token": "",
    "client_id": "",
    "client_secret": "",
    "token_expiry": None,
    "tags": [],
    "v2_token": "",
}


def load():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        return {**DEFAULTS, **data}
    with open(CONFIG_FILE, "w") as f:
        json.dump(DEFAULTS, f, indent=2)
    return dict(DEFAULTS)


def save(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_token():
    return os.environ.get("token") or load()["token"]

def get_client_id():
    return os.environ.get("client_id") or load().get("client_id", "")

def get_client_secret():
    return os.environ.get("client_secret") or load().get("client_secret", "")

def get_tags():
    return load().get("tags", [])

# ── Internal v2 API (attachments) ──────────────────────────────────────────────
# Email + password come from the Configure panel (env vars tt_username/tt_password,
# like client_id/secret); the v2 session token is fetched by signon and cached here
# so we only log in when there's no valid token (TickTick rate-limits logins).
def get_v2_username():
    return os.environ.get("tt_username") or load().get("v2_username", "")

def get_v2_password():
    return os.environ.get("tt_password") or load().get("v2_password", "")

def get_v2_token():
    return load().get("v2_token", "")

def save_v2_token(token):
    data = load()
    data["v2_token"] = token or ""
    save(data)

def get_folders():
    """Returns {groupId: folderName} dict."""
    return load().get("folders", {})

def set_folder(group_id, name):
    """Save or update a single folder name mapping."""
    data = load()
    folders = data.get("folders", {})
    folders[group_id] = name
    data["folders"] = folders
    save(data)

def delete_folder(group_id):
    """Remove a folder name mapping."""
    data = load()
    folders = data.get("folders", {})
    folders.pop(group_id, None)
    data["folders"] = folders
    save(data)
