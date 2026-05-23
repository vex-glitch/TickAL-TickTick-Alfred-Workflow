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
