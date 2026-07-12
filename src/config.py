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
    save(dict(DEFAULTS))
    return dict(DEFAULTS)


def save(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(CONFIG_FILE, 0o600)   # holds session tokens — owner-only
    except OSError:
        pass


def get_token():
    return os.environ.get("token") or load()["token"]

def get_client_id():
    return os.environ.get("client_id") or load().get("client_id", "")

def get_client_secret():
    return os.environ.get("client_secret") or load().get("client_secret", "")

def get_tags():
    return load().get("tags", [])

# ── Internal v2 API (attachments / completed / tag tree) ───────────────────────
# NO credential fields in the Configure panel (Alfred prefs are plaintext and
# often cloud-synced). The session token comes from a one-time masked sign-in
# (xact v2login) or a pasted token (save_token.py) and is cached here / in the
# Keychain. Legacy config.json credentials remain a silent signon fallback.
def get_v2_username():
    return load().get("v2_username", "")

def get_v2_password():
    return load().get("v2_password", "")

def get_v2_token():
    return load().get("v2_token", "")

def save_v2_token(token):
    data = load()
    data["v2_token"] = token or ""
    save(data)

def get_periodic_list_id():
    """Periodic-notes home list (R5a). Under Alfred the field ALWAYS exports
    an env var — a present-but-blank var means the user turned the feature
    OFF, so it must NOT fall through to the config.json mirror (that mirror
    exists solely for the headless launchd agent, which has no Alfred env)."""
    if "periodic_list_id" in os.environ:
        return os.environ["periodic_list_id"]
    return load().get("periodic_list_id", "")

def get_weekly_review_id():
    """♻️ Weekly-review source (R5a-R2): the list/task id the weekly note
    mirrors. Same env-present-wins semantics as periodic_list_id."""
    if "weekly_review_id" in os.environ:
        return os.environ["weekly_review_id"]
    return load().get("weekly_review_id", "")

def get_folders():
    """{groupId: folderName} — v2 auto-names (the folder_groups cache, filled
    at sync when an Attachment-Login token exists) overlaid by manual names
    from Settings → Folders. Manual always wins."""
    auto = {}
    try:
        import cache as cache_store
        for g in (cache_store.get("folder_groups") or []):
            gid, name = g.get("id"), g.get("name")
            if gid and name:      # one malformed entry must not drop the rest
                auto[gid] = name
    except Exception:
        pass
    auto.update(load().get("folders", {}))
    return auto


def get_manual_folders():
    """Names the user placed in config.json's `folders` map — a silent,
    UI-less override on top of the v2 auto-names (R4.2: the Settings naming
    flow is gone; this stays as the power-user escape hatch)."""
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
