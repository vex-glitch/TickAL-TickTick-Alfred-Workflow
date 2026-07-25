"""Eagle client - editing-pipeline plumbing (probe-verified 2026-07-25).

Two channels, one module:

RAW HTTP API (port 41595, alive while Eagle.app runs):
    application/info, library/info, library/switch (near-instant, but we
    POLL library/info until the target NAME reports - the switch ack is
    fire-and-forget), item/addFromPaths (RETURNS ids: {"data": [id, ...]}),
    item/moveToTrash, folder/create ({"folderName", "parent"}).
    TRAP: freshly added items may take seconds to appear in item/list -
    NEVER look an import up by name right after adding; the ids from the
    addFromPaths response are the only reliable handle.

OFFICIAL EAGLE MCP PLUGIN (port 41596, streamable HTTP at /mcp):
    the raw API cannot re-parent folders, edit folder memberships, or
    batch-rename - the plugin's tools can (probe: round-trip re-parent,
    multi-folder membership, rename propagating to the ON-DISK filename).
    We speak minimal MCP JSON-RPC straight to it; if the plugin is off,
    every plugin-backed call fails CLOSED with a fix-it message.

Both channels see ONLY the currently open library - ensure_library()
first, always. Closed libraries are read from DISK (metadata.json for
the folder tree, images/*.info/metadata.json per item) - that is how
promote copies a CRM tattoo tree without a second switch.
"""

import json
import os
import re
import subprocess
import time
import unicodedata
import urllib.request

RAW = "http://localhost:41595/api/"
MCP = "http://localhost:41596/mcp"

# key -> (library display name, .library path on the T9)
LIBS = {
    "crm": ("04 CRM Library", "/Volumes/T9/Eagle Libraries/04 CRM Library.library"),
    "tv":  ("02 Content Library TV", "/Volumes/T9/Eagle Libraries/02 Content Library TV.library"),
    "fm":  ("03 Content Library FM", "/Volumes/T9/Eagle Libraries/03 Content Library FM.library"),
}

# Lightroom/PS export intake folders (iCloud ON PURPOSE: they must exist
# even with the T9 unplugged, or LR would write into a phantom /Volumes
# path on the boot drive). Our filing action reads these directly - the
# global "Eagle Inbox" auto-import folder is the open-library trap.
_ICLOUD = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs")
INTAKE = {
    "tv": os.path.join(_ICLOUD, "Eagle Inbox TV"),
    "fm": os.path.join(_ICLOUD, "Eagle Inbox FM"),
}

# CRM per-tattoo lifecycle skeleton (created WHOLE so consult refs can be
# dragged in on day one). Order = sidebar order.
SKELETON = ["01 Consultation", "02 Preparation", "03 Design",
            "04 Sessions", "05 Finished", "06 Healed"]


class EagleError(Exception):
    """Raised with a toast-ready, honest message. Every caller fails closed."""


# ---------------------------------------------------------------- raw API

def _raw(path, payload=None, timeout=15):
    try:
        if payload is None:
            r = urllib.request.urlopen(RAW + path, timeout=timeout)
        else:
            req = urllib.request.Request(
                RAW + path, json.dumps(payload).encode(),
                {"Content-Type": "application/json"})
            r = urllib.request.urlopen(req, timeout=timeout)
        out = json.load(r)
    except Exception as e:
        raise EagleError(f"Eagle API unreachable ({e.__class__.__name__})")
    if out.get("status") != "success":
        raise EagleError(f"Eagle API error on {path}: "
                         f"{out.get('message') or out.get('code') or out}")
    return out.get("data")


def ensure_running(launch=True, wait=20.0):
    """Eagle up + T9 mounted, else EagleError. Launches Eagle (background,
    no focus steal) when it is merely not running yet."""
    if not os.path.isdir("/Volumes/T9/Eagle Libraries"):
        raise EagleError("T9 drive not mounted - plug it in first")
    try:
        _raw("application/info", timeout=2)
        return
    except EagleError:
        if not launch:
            raise EagleError("Eagle is not running")
    subprocess.run(["open", "-g", "-a", "Eagle"], capture_output=True)
    t0 = time.time()
    while time.time() - t0 < wait:
        try:
            _raw("application/info", timeout=2)
            return
        except EagleError:
            time.sleep(0.5)
    raise EagleError("Eagle did not come up in time")


def current_library():
    """Display name of the open library ('' when unknowable)."""
    try:
        return (_raw("library/info", timeout=5)
                .get("library", {}).get("name", ""))
    except EagleError:
        return ""


def ensure_library(key, wait=25.0):
    """Switch Eagle to LIBS[key] and block until the API serves it.
    The switch ack means nothing - poll library/info for the NAME."""
    name, path = LIBS[key]
    ensure_running()
    if current_library() == name:
        return
    if not os.path.isdir(path):
        raise EagleError(f"library missing on disk: {path}")
    _raw("library/switch", {"libraryPath": path})
    t0 = time.time()
    while time.time() - t0 < wait:
        if current_library() == name:
            time.sleep(0.4)          # tiny settle before writes
            return
        time.sleep(0.25)
    raise EagleError(f"Eagle never finished switching to {name}")


def folder_tree():
    """Open library's folder tree (list of nested dicts)."""
    return _raw("folder/list")


def find_folder(name, parent_id=None, tree=None):
    """First folder matching name (exact) - optionally under parent_id.
    Returns the folder dict or None."""
    def walk(nodes, pid):
        for f in nodes:
            if f.get("name") == name and (parent_id is None or pid == parent_id):
                return f
            hit = walk(f.get("children") or [], f.get("id"))
            if hit:
                return hit
        return None
    return walk(tree if tree is not None else folder_tree(), None)


def create_folder(name, parent=None):
    """folder/create - returns the new folder's id."""
    payload = {"folderName": name}
    if parent:
        payload["parent"] = parent
    data = _raw("folder/create", payload)
    fid = (data or {}).get("id")
    if not fid:
        raise EagleError(f"folder create gave no id for {name!r}")
    return fid


def add_items(specs, folder_id=None):
    """item/addFromPaths - specs = [{'path', 'name', 'tags', 'annotation'}].
    Returns the new item ids IN ORDER (probe: data == list of ids)."""
    items = []
    for s in specs:
        it = {"path": s["path"]}
        for k in ("name", "tags", "annotation", "website"):
            if s.get(k):
                it[k] = s[k]
        items.append(it)
    payload = {"items": items}
    if folder_id:
        payload["folderId"] = folder_id
    ids = _raw("item/addFromPaths", payload, timeout=120)
    if not isinstance(ids, list) or len(ids) != len(items):
        raise EagleError(f"import returned {ids!r} for {len(items)} items")
    return ids


def trash_items(ids):
    _raw("item/moveToTrash", {"itemIds": list(ids)})


def list_item_names(folder_id, limit=400):
    """Item names inside one folder of the OPEN library (numbering
    input). TRAP: imports from the last few seconds may not appear yet -
    compute numbering BEFORE importing, never after."""
    data = _raw(f"item/list?limit={limit}&folders={folder_id}")
    return [i.get("name") or "" for i in (data or [])]


def folder_node(fid, tree=None):
    """The folder dict with this id from the OPEN library's tree."""
    def walk(nodes):
        for f in nodes:
            if f.get("id") == fid:
                return f
            hit = walk(f.get("children") or [])
            if hit:
                return hit
        return None
    return walk(tree if tree is not None else folder_tree())


# ------------------------------------------------- MCP plugin channel

def _mcp_call(tool, arguments, timeout=60):
    """One tools/call against the official Eagle MCP plugin. Speaks just
    enough streamable-HTTP JSON-RPC; parses both bare-JSON and SSE
    ('data: {...}') response bodies. Fails closed when the plugin is off."""
    def post(payload, sid):
        req = urllib.request.Request(MCP, json.dumps(payload).encode(), {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **({"Mcp-Session-Id": sid} if sid else {})})
        r = urllib.request.urlopen(req, timeout=timeout)
        sid = r.headers.get("Mcp-Session-Id") or sid
        return r.read().decode("utf-8", "replace"), sid

    def parse(body):
        for ln in body.splitlines():
            if ln.startswith("data: "):
                return json.loads(ln[6:])
        return json.loads(body) if body.strip() else {}

    try:
        body, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-03-26",
                                     "capabilities": {},
                                     "clientInfo": {"name": "tickal",
                                                    "version": "1.0"}}}, None)
        post({"jsonrpc": "2.0",
              "method": "notifications/initialized"}, sid)
        body, sid = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                          "params": {"name": tool,
                                     "arguments": arguments}}, sid)
    except Exception as e:
        raise EagleError("Eagle MCP plugin unreachable - enable it in "
                         f"Eagle → Plugins ({e.__class__.__name__})")
    msg = parse(body)
    if "error" in msg:
        raise EagleError(f"Eagle MCP {tool}: {msg['error'].get('message')}")
    content = (msg.get("result") or {}).get("content") or []
    text = next((c.get("text") for c in content if c.get("type") == "text"), "")
    try:
        out = json.loads(text)
    except Exception:
        raise EagleError(f"Eagle MCP {tool}: unparseable reply")
    if out.get("success") is False:
        raise EagleError(f"Eagle MCP {tool}: {out.get('message')}")
    return out


def move_folder(folder_id, new_parent):
    """Re-parent (None = root). Raw API can't - plugin can (probe-proven)."""
    _mcp_call("folder_update",
              {"folders": [{"id": folder_id, "parentId": new_parent}]})


def update_items(items):
    """Batch item mutation via the plugin: name / tags / folders / star.
    items = [{'id', ...fields}]. Renames propagate to the on-disk file."""
    _mcp_call("item_update", {"items": items})


def add_to_folders(ids, folder_ids):
    """Incremental membership - the multi-shelf trick (To post AND
    Portfolio, one file)."""
    _mcp_call("item_add_to_folders",
              {"ids": list(ids), "folders": list(folder_ids)})


def remove_from_folders(ids, folder_ids):
    _mcp_call("item_remove_from_folders",
              {"ids": list(ids), "folders": list(folder_ids)})


def selected_items():
    """What is selected in Eagle RIGHT NOW (triage + promote selection)."""
    out = _mcp_call("item_get_selected", {})
    return out.get("data") or []


def add_item_tags(ids, tags):
    _mcp_call("item_add_tags", {"ids": list(ids), "tags": list(tags)})


# ------------------------------------------------ closed-library disk

def disk_folder_tree(lib_path):
    """Folder tree of a CLOSED library, straight from metadata.json."""
    try:
        with open(os.path.join(lib_path, "metadata.json")) as f:
            return json.load(f).get("folders", [])
    except Exception as e:
        raise EagleError(f"cannot read library metadata: {e.__class__.__name__}")


def disk_subtree_ids(lib_path, root_id):
    """root folder id + every descendant id, from disk."""
    def find(nodes):
        for f in nodes:
            if f.get("id") == root_id:
                return f
            hit = find(f.get("children") or [])
            if hit:
                return hit
        return None
    root = find(disk_folder_tree(lib_path))
    if not root:
        raise EagleError("folder not found in library metadata")
    out = []

    def collect(f):
        out.append(f["id"])
        for c in f.get("children") or []:
            collect(c)
    collect(root)
    return root, out


def disk_items_in(lib_path, folder_ids):
    """Items of a CLOSED library belonging to any of folder_ids.
    Walks images/*.info/metadata.json; returns [{'id','name','ext',
    'tags','folders','path'}] with path = the actual media file."""
    want = set(folder_ids)
    images = os.path.join(lib_path, "images")
    out = []
    try:
        entries = os.listdir(images)
    except Exception as e:
        raise EagleError(f"cannot list library images: {e.__class__.__name__}")
    for entry in entries:
        if not entry.endswith(".info"):
            continue
        info = os.path.join(images, entry)
        try:
            with open(os.path.join(info, "metadata.json")) as f:
                meta = json.load(f)
        except Exception:
            continue
        if meta.get("isDeleted") or not (set(meta.get("folders") or []) & want):
            continue
        fname = f"{meta.get('name')}.{meta.get('ext')}"
        path = os.path.join(info, fname)
        if not os.path.exists(path):
            cands = [x for x in os.listdir(info)
                     if not x.startswith(".")
                     and x != "metadata.json"
                     and not x.endswith("_thumbnail.png")]
            path = os.path.join(info, cands[0]) if cands else None
        out.append({"id": meta.get("id"), "name": meta.get("name") or "",
                    "ext": meta.get("ext") or "", "tags": meta.get("tags") or [],
                    "folders": meta.get("folders") or [], "path": path})
    return out


# ---------------------------------------------------- naming + matching

def item_name(base, stage, n):
    """'{Customer} - {tattoo} • S1 • 3' / '• Design • 1' / '• Edit • 2'."""
    return f"{base} • {stage} • {n}"


def next_index(existing_names, base, stage):
    """1 + highest existing '• {stage} • n' suffix for this base.
    Numbering continues per folder - never reuses a slot."""
    pat = re.compile(re.escape(f"{base} • {stage} • ") + r"(\d+)$")
    top = 0
    for name in existing_names:
        m = pat.match(name or "")
        if m:
            top = max(top, int(m.group(1)))
    return top + 1


def normalize(s):
    """Fuzzy-compare form: casefold, strip diacritics, collapse
    punctuation to single spaces. 'Erol  - snake!' == 'erol snake'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s.casefold())
    return " ".join(s.split())


def _soft_overlap(a_toks, b_toks):
    """Matched-token count where 'tatoo'≈'tattoo' still counts (pairwise
    SequenceMatcher ≥ 0.8, each token used once)."""
    import difflib
    remaining = list(b_toks)
    m = 0
    for t in a_toks:
        best_i, best_r = -1, 0.0
        for i, u in enumerate(remaining):
            r = 1.0 if t == u else difflib.SequenceMatcher(None, t, u).ratio()
            if r > best_r:
                best_i, best_r = i, r
        if best_i >= 0 and best_r >= 0.8:
            remaining.pop(best_i)
            m += 1
    return m


def fuzzy_match(needle, candidates):
    """Best candidate for a possibly typo'd / improvised '{C} - {T}'
    prefix (Vex types from memory - 'Jon Doe - Best Tatoo' must still
    hit). Returns (candidate, score 0..1, confident). Soft token
    overlap blended with a SequenceMatcher ratio; confident needs a
    clear score AND a clear lead over the runner-up - identical
    duplicate names (two 'Gangsta Goose' folders exist) tie at the top
    and correctly fall through to the pick list. An exact needle with a
    suffixed sibling ('Fox' vs 'Fox 2') keeps its lead and auto-files."""
    import difflib
    n = normalize(needle)
    if not n or not candidates:
        return None, 0.0, False
    scored = []
    for c in candidates:
        m = normalize(c)
        toks_n, toks_c = n.split(), m.split()
        hit = _soft_overlap(toks_n, toks_c)
        union = len(toks_n) + len(toks_c) - hit
        jac = hit / union if union else 0.0
        seq = difflib.SequenceMatcher(None, n, m).ratio()
        scored.append((0.6 * jac + 0.4 * seq, c))
    scored.sort(key=lambda t: -t[0])
    best_score, best = scored[0]
    lead = best_score - (scored[1][0] if len(scored) > 1 else 0.0)
    return best, best_score, (best_score >= 0.75 and lead >= 0.15)
