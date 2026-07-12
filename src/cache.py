"""JSON file cache with 5-minute TTL, stored in ~/.ticktick_alfred/cache/."""
import json
import os
import time

CACHE_DIR = os.path.expanduser("~/.ticktick_alfred/cache")
TTL = None  # no expiry — cache lives until explicitly invalidated by sync or a write op


def _path(key):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{key}.json")


def get(key):
    f = _path(key)
    if not os.path.exists(f):
        return None
    try:
        with open(f) as fp:
            data = json.load(fp)
        if TTL is not None and time.time() - data.get("ts", 0) > TTL:
            return None
        return data.get("value")
    except Exception:
        return None


def find_task(tid):
    """Return the cached task/note object with this id, or None (no API call)."""
    for key in ("all_tasks", "all_notes"):
        for t in (get(key) or []):
            if t.get("id") == tid:
                return t
    return None


def set(key, value):
    with open(_path(key), "w") as fp:
        json.dump({"ts": time.time(), "value": value}, fp)


def invalidate(key=None):
    if key:
        f = _path(key)
        if os.path.exists(f):
            os.remove(f)
    else:
        if os.path.exists(CACHE_DIR):
            for name in os.listdir(CACHE_DIR):
                if name.endswith(".json"):
                    os.remove(os.path.join(CACHE_DIR, name))


def age_seconds(key):
    f = _path(key)
    if not os.path.exists(f):
        return None
    try:
        with open(f) as fp:
            data = json.load(fp)
        return time.time() - data.get("ts", 0)
    except Exception:
        return None
