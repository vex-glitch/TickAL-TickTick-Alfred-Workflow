"""albums.py - the ALBUMS substrate (move shots · new album · rename ·
merge · customer-later; Vex green 2026-09-09, ALBUMS_SPEC §2).

An ALBUM is a tattoo folder of a CONTENT library (eagle.LIBS tv / fm /
studio) under one of three stages: 01 Raw, 02 Edit (any depth - Edit
albums may have children) or 04 Portfolio. 03 Post is a flat shelf and
never an album target. `🗑 Deleted` at the library root is the bin
(matched by normalized name, never by the emoji); its child `Duplicates`
holds byte-identical twins.

Two kinds of function live here, kept apart on purpose:

PURE (no I/O, unit-tested in tests/test_albums.py): rebase_name,
rebased_items, base_tags, stage_label, stage_tag, plan_merge,
stash/unstash (a JSON round-trip on STASH_PATH), Ledger.

LIVE (Eagle only - the raw API + the MCP plugin through eagle.py): every
one of them is a thin composition of eagle.* calls so the verbs in
xact.py can be proven over a fake eagle module (monkeypatch
`albums.eagle`). NOTHING here touches TickTick: the ledger records what
the verbs did on the TickTick side and undo_last LISTS those pieces in
its toast for Vex to restore by hand (TickTick Trash keeps them).

Naming follows the closed vocabulary in eagle.py: a shot is
'{base} • {Label} • n' (Label = Raw under 01 Raw / 02 Edit, Portfolio
under 04 Portfolio), item tags carry [customer, tattoo] from the base
split on ' - ' (John Doe: [base]). A move to another album REBASES the
name + those two tags and keeps everything else (branch tags, dest
keys, annotations).

Ledger: ~/.ticktick_alfred/run/albums.jsonl, one JSON object per line
(ALBUMS_SPEC §1). LEDGER_PATH / STASH_PATH are module constants so tests
point them at tmp files. Undo records (verb "undo") are the trail:
Ledger.last() / pop_last() skip them, so undo is a proper stack.
"""
import datetime
import hashlib
import json
import os
import re
import time

import areas
import cache as cache_store
import eagle

LIBS_CONTENT = ("tv", "fm", "studio")
LEDGER_PATH = os.path.expanduser("~/.ticktick_alfred/run/albums.jsonl")
STASH_PATH = os.path.expanduser("~/.ticktick_alfred/run/albsel.json")
BIN_NAME = "🗑 Deleted"
DUP_NAME = "Duplicates"
STAGES = ("Raw", "Edit", "Portfolio")
# Pace between two folder re-parents (HANDOFF_CONTENT trap: back-to-back
# moves double-parent). Tests set it to 0.
PACE = 0.4
# capture_days plausibility window: a camera-clock reset (1970) or a
# future stamp must not become Started/Finished + the 📦crm<year> tag.
DAY_FLOOR = "2000-01-01"


class AlbumError(Exception):
    """Toast-ready message; every verb catches it and _crm_say()s it."""


# ------------------------------------------------------------- helpers

def _norm(s):
    """Loose name key: casefold, punctuation and emoji gone, digits kept
    ('🗑 Deleted' → 'deleted', '04 Portfolio' → '04 portfolio')."""
    return " ".join(re.sub(r"[^\w\s]", " ", (s or "").casefold()).split())


def _is_portfolio_name(name):
    return bool(re.fullmatch(r"(?:\d+\s*)?portfolio", _norm(name)))


def _lib_path(lib):
    if lib not in eagle.LIBS:
        raise AlbumError(f"Unknown library {lib!r}")
    return eagle.LIBS[lib][1]


def _lib_label(lib):
    return (areas.CONTENT_DESTS.get(lib) or ("", "", lib.upper()))[2]


def _folder_names(tree):
    """{folder id: name} over a whole tree."""
    out = {}

    def walk(nodes):
        for f in nodes or []:
            out[f.get("id")] = f.get("name") or ""
            walk(f.get("children"))
    walk(tree)
    return out


def _find_node(tree, fid):
    """(node, parent_id) for a folder id, (None, None) when absent."""
    def walk(nodes, parent):
        for f in nodes or []:
            if f.get("id") == fid:
                return f, parent
            hit = walk(f.get("children"), f.get("id"))
            if hit[0] is not None:
                return hit
        return None, None
    return walk(tree, None)


def _stage_roots(tree):
    """{stage: root node} for the working folders present in a tree
    (suffix-matched, root only - eagle.find_folder_suffix's rules)."""
    out = {}
    for stage in STAGES:
        hit = eagle.find_folder_suffix(stage, tree=tree)
        if hit:
            out[stage] = hit
    return out


def _shot_order(it):
    """Renumber in the order the shots were taken (the trailing index of
    the old name), not in disk-walk order - bulk_move's rule."""
    _b, _s, n = eagle.item_base(it.get("name") or "")
    return (n or 10 ** 6, it.get("name") or "")


def _now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


# -------------------------------------------------------------- ledger

class Ledger:
    """One JSON object per line. Undo records (verb 'undo') are the trail
    and are never handed back by last() / pop_last()."""

    def __init__(self, path=None):
        self.path = path or LEDGER_PATH

    def all(self):
        out = []
        try:
            with open(self.path) as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        out.append(json.loads(ln))
                    except ValueError:
                        continue
        except OSError:
            pass
        return out

    def append(self, op):
        op = dict(op)
        op.setdefault("when", _now())
        for k in ("items", "folders", "ticktick"):
            op.setdefault(k, [])
        op.setdefault("note", "")
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(op, ensure_ascii=False) + "\n")

    def last(self):
        for op in reversed(self.all()):
            if op.get("verb") != "undo":
                return op
        return None

    def pop_last(self):
        ops = self.all()
        for i in range(len(ops) - 1, -1, -1):
            if ops[i].get("verb") != "undo":
                op = ops.pop(i)
                self._rewrite(ops)
                return op
        return None

    def _rewrite(self, ops):
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            for op in ops:
                f.write(json.dumps(op, ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)


def new_op(verb, lib, note=""):
    """An empty ledger op the live functions fill as they go."""
    return {"when": _now(), "verb": verb, "lib": lib, "items": [],
            "folders": [], "ticktick": [], "note": note}


# --------------------------------------------------------- pure naming

def stage_label(stage):
    """The item-name label an album's shots carry: Portfolio under
    04 Portfolio, Raw everywhere else (Raw, Edit, unknown)."""
    return "Portfolio" if stage == "Portfolio" else "Raw"


def stage_tag(stage):
    """The pipeline-row state tag for a stage; '' = no row (Portfolio)."""
    return {"Raw": "📸raw", "Edit": "📸edit"}.get(stage, "")


def base_tags(base):
    """[customer, tattoo] from '{C} - {T}'; a John Doe base → [base]."""
    cust, sep, tat = (base or "").partition(" - ")
    if not sep:
        return [cust.strip()] if cust.strip() else []
    return [t for t in (cust.strip(), tat.strip()) if t]


def rebase_name(name, old_base, new_base):
    """'{old} • Raw • 3' → '{new} • Raw • 3'. old_base given: only that
    base rebases; old_base empty: any convention name. Unknown shapes
    (hand-named, legacy) come back unchanged."""
    b, stage, n = eagle.item_base(name)
    if not b:
        return name
    if old_base and b != old_base:
        return name
    return eagle.item_name(new_base, stage, n)


def rebased_items(items, new_base, label, existing_names, old_base=None):
    """Plan the names + tags of `items` landing in an album named
    `new_base` under `label`: numbering CONTINUES the destination's
    (`existing_names`, extended in-loop so a batch never collides with
    itself), shooting order kept, customer/tattoo tags swapped, every
    other tag kept. A shot already wearing the exact destination name
    keeps it (a move into the same album renames nothing). A shelf edit
    ('• Edit • n', file_edited's export) KEEPS its Edit label wherever
    it lands (renumbered under the new base) - a raw-named edit is
    invisible to the 📤 Posted sweep and indistinguishable from the
    raws. old_base names the source album so hand-named shots can shed
    its tags too. Returns [{"id", "name", "tags"}]."""
    existing = list(existing_names or [])
    taken = set(existing)
    new_tags = base_tags(new_base)
    new_lc = {t.lower() for t in new_tags}
    old_lc = {t.lower() for t in base_tags(old_base)} if old_base else set()
    out = []
    for it in sorted(items, key=_shot_order):
        name = it.get("name") or ""
        b, stage, n = eagle.item_base(name)
        lab = "Edit" if stage == "Edit" else label
        if b == new_base and stage == lab and name not in taken:
            nm = name
        else:
            nm = eagle.item_name(new_base, lab,
                                 eagle.next_index(existing, new_base, lab))
        existing.append(nm)
        taken.add(nm)
        drop = set(old_lc)
        if b:
            drop |= {t.lower() for t in base_tags(b)}
        drop -= new_lc
        tags = [t for t in (it.get("tags") or [])
                if str(t).lower() not in drop]
        have = {str(t).lower() for t in tags}
        tags += [t for t in new_tags if t.lower() not in have]
        out.append({"id": it.get("id"), "name": nm, "tags": tags})
    return out


def file_md5(path, chunk=1 << 20):
    """md5 hex of a file's bytes ('' when unreadable) - the twin test."""
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for blk in iter(lambda: f.read(chunk), b""):
                h.update(blk)
        return h.hexdigest()
    except OSError:
        return ""


def hash_items(items):
    """Fill it['hash'] from it['path'] where missing (in place; returns
    the list)."""
    for it in items:
        if not it.get("hash") and it.get("path"):
            it["hash"] = file_md5(it["path"])
    return items


def plan_merge(a_items, b_items, a_base, label="Raw"):
    """PURE merge planner: B's shots into album A (base `a_base`).
    Item dicts: {"id", "name", "tags", "child": <name of the level-1
    subfolder holding the shot, '' at the album root>, "hash": md5}.
    - a hash already in A (or earlier in B) → "dupes" (twin named), for
      the Duplicates bin instead of A
    - B's Portfolio child pairs with A's Portfolio child, other children
      pair by loose name (create = A lacks it), the rest land at A's root
    - names continue A's numbering per child (rebased_items), Portfolio
      children take the Portfolio label, the root takes `label`
    Returns {"moves": [{"id", "child", "create", "label", "name",
    "tags", "prior_name"}], "dupes": [{"id", "name", "twin"}],
    "renames": [{"id", "from", "to"}]}."""
    a_hash = {}
    a_children, names_by_child = {}, {}
    for it in a_items or []:
        if it.get("hash"):
            a_hash.setdefault(it["hash"], it.get("id"))
        ch = it.get("child") or ""
        if ch:
            a_children.setdefault(_norm(ch), ch)
        names_by_child.setdefault(ch, []).append(it.get("name") or "")
    seen = dict(a_hash)
    moves, dupes, renames = [], [], []
    for it in sorted(b_items or [], key=_shot_order):
        h = it.get("hash")
        if h and h in seen:
            dupes.append({"id": it.get("id"), "name": it.get("name") or "",
                          "twin": seen[h]})
            continue
        if h:
            seen[h] = it.get("id")
        bch = it.get("child") or ""
        if not bch:
            child = ""
        elif _is_portfolio_name(bch):
            child = next((v for v in a_children.values()
                          if _is_portfolio_name(v)), bch)
        else:
            child = a_children.get(_norm(bch), bch)
        lab = "Portfolio" if _is_portfolio_name(child) else label
        existing = names_by_child.setdefault(child, [])
        plan = rebased_items([it], a_base, lab, existing)[0]
        existing.append(plan["name"])
        prior = it.get("name") or ""
        moves.append({"id": it.get("id"), "child": child,
                      "create": bool(bch) and _norm(child) not in a_children,
                      "label": lab, "name": plan["name"],
                      "tags": plan["tags"], "prior_name": prior})
        if plan["name"] != prior:
            renames.append({"id": it.get("id"), "from": prior,
                            "to": plan["name"]})
    return {"moves": moves, "dupes": dupes, "renames": renames}


# ---------------------------------------------------------------- stash

def stash(sel):
    """Park a selection for the picker screen (a fresh process)."""
    d = os.path.dirname(STASH_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = STASH_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(dict(sel, when=_now()), f, ensure_ascii=False)
    os.replace(tmp, STASH_PATH)


def unstash():
    """The parked selection, or None. Does NOT clear it - the picker
    re-renders on every keystroke; the verb that consumed it calls
    clear_stash()."""
    try:
        with open(STASH_PATH) as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("items") else None
    except (OSError, ValueError):
        return None


def clear_stash():
    try:
        os.remove(STASH_PATH)
    except OSError:
        pass


# ------------------------------------------------------- live: reading

def open_lib():
    """Key of the content library Eagle has open ('' = none / CRM /
    unknown / Eagle asleep)."""
    name = eagle.current_library()
    if not name:
        return ""
    for k in LIBS_CONTENT:
        if eagle.LIBS.get(k, ("",))[0] == name:
            return k
    return ""


def selection(lib=None):
    """What is selected in Eagle RIGHT NOW, read without switching (a
    switch drops the selection). lib given: that library must be open;
    None: any content library. Returns {"lib", "items": [{"id", "name",
    "folders", "tags", "annotation", "ext", "path"}], "sources":
    {fid: [ids]}, "source_names": {fid: name}}."""
    try:
        eagle.ensure_running(launch=False)
    except eagle.EagleError as e:
        raise AlbumError(str(e))
    cur = open_lib()
    if lib:
        if cur != lib:
            raise AlbumError(f"Open the {_lib_label(lib)} library in Eagle first")
    elif not cur:
        raise AlbumError("Open the TV/FM/Studio library in Eagle first")
    lib = lib or cur
    try:
        sel = eagle.selected_items()
    except eagle.EagleError as e:
        raise AlbumError(str(e))
    if not sel:
        raise AlbumError("Nothing selected in Eagle")
    ids = [s.get("id") for s in sel if s.get("id")]
    # item_get_selected is SHALLOW: folders / tags / filePath come from
    # the full read. It FAILS CLOSED: a half-read selection would stash
    # folders=[] / tags=[] and ↩️ Undo would later unfile the shots and
    # wipe their tags (prior state = nothing).
    full = {}
    try:
        for f in eagle.get_items(ids, full=True) or []:
            full[f.get("id")] = f
    except eagle.EagleError as e:
        raise AlbumError(f"Selection unreadable · {e}")
    missing = [i for i in ids if i not in full]
    if missing:
        raise AlbumError(f"Selection unreadable · {len(missing)} of {len(ids)}"
                         " shots came back without details")
    try:
        names = _folder_names(eagle.folder_tree())
    except eagle.EagleError as e:
        raise AlbumError(f"Folder tree unreadable · {e}")
    items, sources = [], {}
    for s in sel:
        f = dict(s)
        f.update(full.get(s.get("id")) or {})
        entry = {"id": f.get("id"), "name": f.get("name") or "",
                 "folders": list(f.get("folders") or []),
                 "tags": list(f.get("tags") or []),
                 "annotation": f.get("annotation") or "",
                 "ext": f.get("ext") or "",
                 "path": f.get("filePath") or f.get("path") or ""}
        items.append(entry)
        for fid in entry["folders"]:
            sources.setdefault(fid, []).append(entry["id"])
    return {"lib": lib, "items": items, "sources": sources,
            "source_names": {f: names.get(f, "") for f in sources}}


def library_albums(lib):
    """Every album of a content library, read from DISK (closed-library
    readers; looking never switches). Stages: 01 Raw children, 02 Edit
    recursively, 04 Portfolio children; never 03 Post, bins or inboxes.
    [{"fid", "name", "stage", "parent", "depth", "path", "n"}] in stage
    order then by name; n = shots in the album's subtree."""
    path = _lib_path(lib)
    try:
        tree = eagle.disk_folder_tree(path)
    except eagle.EagleError as e:
        raise AlbumError(str(e))
    counts = eagle.disk_subtree_counts(path)
    roots = _stage_roots(tree)
    out = []

    def walk(nodes, stage, parent, depth, prefix, recursive):
        rows = []
        for f in nodes or []:
            nm = f.get("name") or ""
            key = _norm(nm)
            if key in ("deleted", "duplicates") or key.startswith("eagle inbox"):
                continue
            p = f"{prefix}/{nm}"
            rows.append({"fid": f.get("id"), "name": nm, "stage": stage,
                         "parent": parent, "depth": depth, "path": p,
                         "n": counts.get(f.get("id"), 0)})
            if recursive:
                rows.extend(walk(f.get("children"), stage, f.get("id"),
                                 depth + 1, p, True))
        return rows

    for stage in STAGES:
        root = roots.get(stage)
        if not root:
            continue
        rows = walk(root.get("children"), stage, root.get("id"), 1,
                    root.get("name") or stage, stage == "Edit")
        rows.sort(key=lambda r: (r["path"].casefold()))
        out.extend(rows)
    return out


def album_stage(lib, fid):
    """'Raw' | 'Edit' | 'Portfolio' for a folder anywhere under that
    stage's root; '' when it is a stage root itself, elsewhere, or
    unknown."""
    try:
        tree = eagle.disk_folder_tree(_lib_path(lib))
    except eagle.EagleError:
        return ""
    for stage, root in _stage_roots(tree).items():
        node, _p = _find_node(root.get("children") or [], fid)
        if node is not None:
            return stage
    return ""


def items_of_album(lib, fid):
    """Disk items of the album subtree, each with "child" = the name of
    the level-1 subfolder holding it ('' at the root) and "child_fid" -
    what plan_merge pairs on."""
    path = _lib_path(lib)
    try:
        root, ids = eagle.disk_subtree_ids(path, fid)
        items = eagle.disk_items_in(path, ids)
    except eagle.EagleError as e:
        raise AlbumError(str(e))
    owner = {}
    for c in root.get("children") or []:
        _r, sub = eagle.disk_subtree_ids(path, c.get("id"))
        for s in sub:
            owner.setdefault(s, (c.get("name") or "", c.get("id")))
    for it in items:
        hit = next((owner[f] for f in it.get("folders") or [] if f in owner),
                   None)
        it["child"], it["child_fid"] = hit if hit else ("", "")
    return items


def _rows_pool():
    seen, out = set(), []
    for key in ("all_tasks", "all_notes"):
        for t in cache_store.get(key) or []:
            if t.get("id") in seen:
                continue
            seen.add(t.get("id"))
            out.append(t)
    return out


def row_for_folder(lib, fid):
    """The open pipeline row whose TITLE links eagle://folder/<fid> (the
    legacy localhost link shape too), from the cache; the row in
    `lib`'s list wins when two libraries carry one. None when absent."""
    if not fid:
        return None
    want = (f"eagle://folder/{fid}", f"localhost:41595/folder?id={fid}")
    hits = []
    for t in _rows_pool():
        pid = t.get("_projectId") or t.get("projectId")
        if pid not in areas.CONTENT_PIDS or t.get("status", 0) != 0:
            continue
        title = t.get("title") or ""
        if any(re.search(re.escape(w) + r"(?![A-Za-z0-9])", title)
               for w in want):
            hits.append(t)
    if not hits:
        return None
    pid_want = (areas.CONTENT_DESTS.get(lib) or ("",))[0]
    return next((t for t in hits
                 if (t.get("_projectId") or t.get("projectId")) == pid_want),
                hits[0])


# ------------------------------------------------------- capture dates

def _mdls(paths):
    """Spotlight capture dates via migration._mdls_dates (lazy: the
    module is heavy, the call is pure). Tests monkeypatch this."""
    import migration
    return migration._mdls_dates(paths)


def _bulk_dates():
    try:
        import migration
        return set(migration.BULK_DATES)
    except Exception:
        return set()


def _btime_epoch(path):
    """Eagle's own import instant from the item's metadata.json (ms)."""
    try:
        with open(os.path.join(os.path.dirname(path), "metadata.json")) as f:
            bt = json.load(f).get("btime")
        return float(bt) / 1000.0 if bt else None
    except Exception:
        return None


def capture_days(lib, items):
    """Sorted unique ISO days the shots were taken (mdls creation date,
    Eagle btime as the fallback, bulk-export days vetoed - the
    migration's rules; days before DAY_FLOOR or after today (UTC) are
    dropped, so one zeroed camera clock never decides the tattoo).
    Paths come from the items ("path"/"filePath"); ids without one are
    looked up live (the open library). [] when no date is known."""
    paths, missing = [], []
    for it in items or []:
        p = it.get("path") or it.get("filePath")
        (paths if p else missing).append(p if p else it.get("id"))
    if missing:
        try:
            for f in eagle.get_items([m for m in missing if m], full=True) or []:
                if f.get("filePath"):
                    paths.append(f["filePath"])
        except eagle.EagleError:
            pass
    paths = [p for p in paths if p]
    if not paths:
        return []
    epochs = _mdls(paths) or {}
    veto = _bulk_dates()
    today = time.strftime("%Y-%m-%d", time.gmtime())
    days = set()
    for p in paths:
        e = epochs.get(p)
        if e is None:
            e = _btime_epoch(p)
        if e is None:
            continue
        d = time.strftime("%Y-%m-%d", time.gmtime(e))
        if d in veto or d < DAY_FLOOR or d > today:
            continue
        days.add(d)
    return sorted(days)


# ------------------------------------------------------- live: writing

def _open_tree(lib):
    try:
        eagle.ensure_library(lib)
        return eagle.folder_tree()
    except eagle.EagleError as e:
        raise AlbumError(str(e))


def move_items(lib, items, dest_fid, dest_base, label, ledger_op,
               old_base=None):
    """LIVE: `items` (selection / disk dicts with id, name, folders, tags)
    into album `dest_fid` named `dest_base` under `label`. Membership is
    REPLACED with [dest_fid] (the move idiom) except: a shot that also
    sits on 03 Post keeps that shelf, and a Raw/Edit move keeps any
    placement under 04 Portfolio (the ⭐ dual placement; a move INTO a
    Portfolio album replaces it - there the Portfolio folder IS the
    source). Names + customer/tattoo tags rebased, everything else kept.
    Prior state lands in ledger_op["items"] only once update_items
    succeeded: nothing moved = nothing ledgered (no phantom ↩️ Undo).
    Returns {"moved": n, "renamed": n}."""
    if not items:
        return {"moved": 0, "renamed": 0}
    tree = _open_tree(lib)
    try:
        existing = eagle.list_item_names(dest_fid)
        post = (eagle.pipeline_folders(create=False) or {}).get("Post") or ""
        port = _stage_roots(tree).get("Portfolio") or {}
        port_ids = set(_folder_names(port.get("children")))
        keep = {post} if post else set()
        if dest_fid not in port_ids:
            keep |= port_ids
        keep.discard(dest_fid)
        plan = rebased_items(items, dest_base, label, existing,
                             old_base=old_base)
        by_id = {it.get("id"): it for it in items}
        payload, staged, renamed = [], [], 0
        for p in plan:
            it = by_id.get(p["id"]) or {}
            folders = [dest_fid]
            for f in it.get("folders") or []:
                if f in keep and f not in folders:
                    folders.append(f)
            payload.append({"id": p["id"], "name": p["name"],
                            "folders": folders})
            if p["name"] != (it.get("name") or ""):
                renamed += 1
            staged.append({
                "id": p["id"], "prior_name": it.get("name") or "",
                "prior_folders": list(it.get("folders") or []),
                "prior_tags": list(it.get("tags") or []),
                "name": p["name"], "folders": folders})
        eagle.update_items(payload)
        ledger_op.setdefault("items", []).extend(staged)
        ids = [p["id"] for p in plan]
        new_lc = {t.lower() for t in base_tags(dest_base)}
        stale = set()
        for it in items:
            b = eagle.item_base(it.get("name") or "")[0]
            for t in base_tags(b) + (base_tags(old_base) if old_base else []):
                if t.lower() not in new_lc:
                    stale.add(t)
        if stale:
            try:
                eagle.remove_item_tags(ids, sorted(stale))
            except eagle.EagleError:
                pass
        add = base_tags(dest_base)
        if add:
            eagle.add_item_tags(ids, add)
    except eagle.EagleError as e:
        raise AlbumError(str(e))
    return {"moved": len(plan), "renamed": renamed}


def new_album(lib, stage, base, ledger_op):
    """LIVE: create '{base}' under the OPEN library's stage folder
    (created flat at the root when missing). A same-named album already
    under that stage (loose name match, DIRECT children of the stage
    root only - a level-2 child of another album such as 'Video' or a
    copied skeleton's '01 Consultation' is never adopted) is adopted
    instead of twinned - Eagle cannot delete folders. Returns the fid."""
    if stage not in STAGES:
        raise AlbumError(f"No such stage {stage!r}")
    tree = _open_tree(lib)
    try:
        parent = eagle.pipeline_folders(tree=tree)[stage]
        root, _p = _find_node(tree, parent)
        want = _norm(base)
        hit = None
        if root is not None:
            hit = next((f for f in root.get("children") or []
                        if _norm(f.get("name")) == want), None)
        if hit:
            ledger_op["note"] = (ledger_op.get("note") or "") + \
                f" · adopted existing {hit.get('name')}"
            ledger_op.setdefault("folders", []).append({
                "id": hit.get("id"), "prior_name": hit.get("name") or "",
                "prior_parent": parent, "name": hit.get("name") or "",
                "parent": parent, "created": False})
            return hit.get("id")
        fid = eagle.create_folder(base, parent=parent)
    except eagle.EagleError as e:
        raise AlbumError(str(e))
    ledger_op.setdefault("folders", []).append({
        "id": fid, "prior_name": "", "prior_parent": "", "name": base,
        "parent": parent, "created": True})
    return fid


def bin_folder(lib, create=True):
    """The '🗑 Deleted' bin of the OPEN library (root, normalized-name
    match so the emoji can never fork a twin), minted when missing."""
    tree = _open_tree(lib)
    hit = next((n for n in tree if _norm(n.get("name")) == "deleted"), None)
    if hit:
        return hit["id"]
    if not create:
        return ""
    try:
        return eagle.create_folder(BIN_NAME)
    except eagle.EagleError as e:
        raise AlbumError(str(e))


def dup_folder(lib):
    """The bin's 'Duplicates' child (byte-identical twins), minted when
    missing."""
    bin_id = bin_folder(lib)
    try:
        node = eagle.folder_node(bin_id)
        hit = next((c for c in (node or {}).get("children") or []
                    if _norm(c.get("name")) == "duplicates"), None)
        if hit:
            return hit["id"]
        return eagle.create_folder(DUP_NAME, parent=bin_id)
    except eagle.EagleError as e:
        raise AlbumError(str(e))


def _subtree_item_count(node):
    n = len(eagle.items_in_folder(node["id"]))
    for c in node.get("children") or []:
        n += _subtree_item_count(c)
    return n


def husk_to_bin(lib, fid, ledger_op):
    """Park an EMPTY folder (whole subtree empty) under the bin. Refuses
    (False) when it still holds shots or does not exist."""
    tree = _open_tree(lib)
    node, parent = _find_node(tree, fid)
    if node is None:
        return False
    try:
        if _subtree_item_count(node):
            return False
        bin_id = bin_folder(lib)
        if parent == bin_id:
            return True
        eagle.move_folder(fid, bin_id)
        if PACE:
            time.sleep(PACE)
    except eagle.EagleError as e:
        raise AlbumError(str(e))
    ledger_op.setdefault("folders", []).append({
        "id": fid, "prior_name": node.get("name") or "",
        "prior_parent": parent or "", "name": node.get("name") or "",
        "parent": bin_id, "created": False})
    return True


def _ticktick_pieces(op):
    out = []
    for p in op.get("ticktick") or []:
        kind, act, tid = p.get("kind", "?"), p.get("action", ""), p.get("id", "")
        if act == "minted":
            out.append(f"Trash {kind} {tid}")
        elif act == "trashed":
            out.append(f"restore {kind} {tid} from Trash")
        else:
            prior = p.get("prior") or {}
            hint = " · ".join(f"{k} {v}" for k, v in prior.items()
                              if v not in (None, "", [], {}))
            out.append(f"{kind} {tid} was {act}" + (f" (prior {hint})" if hint else ""))
    return out


def undo_last():
    """Reverse the EAGLE side of the last ledger op: shots back to their
    prior folders / names / tags, created folders → bin, renamed →
    prior name, moved → prior parent. Never touches TickTick - the
    toast lists those pieces for Vex to put back by hand."""
    ledger = Ledger()
    op = ledger.last()
    if not op:
        return "↩️ Nothing to undo"
    lib = op.get("lib") or ""
    if lib not in eagle.LIBS:
        return f"↩️ Cannot undo · unknown library {lib!r}"
    _open_tree(lib)
    n_items = n_folders = 0
    notes = []
    try:
        items = [i for i in op.get("items") or [] if i.get("id")]
        if items:
            eagle.update_items([{"id": i["id"],
                                 "name": i.get("prior_name") or "",
                                 "folders": list(i.get("prior_folders") or [])}
                                for i in items])
            n_items = len(items)
            cur = {}
            try:
                for f in eagle.get_items([i["id"] for i in items], full=False) or []:
                    cur[f.get("id")] = [str(t) for t in (f.get("tags") or [])]
            except eagle.EagleError:
                cur = {}
            for i in items:
                prior = [str(t) for t in (i.get("prior_tags") or [])]
                now = cur.get(i["id"])
                if now is None:
                    continue
                plc, nlc = {t.lower() for t in prior}, {t.lower() for t in now}
                extra = [t for t in now if t.lower() not in plc]
                gone = [t for t in prior if t.lower() not in nlc]
                if extra:
                    eagle.remove_item_tags([i["id"]], extra)
                if gone:
                    eagle.add_item_tags([i["id"]], gone)
        for f in reversed(op.get("folders") or []):
            fid = f.get("id")
            if not fid:
                continue
            if f.get("created"):
                node = eagle.folder_node(fid) or {"id": fid, "children": []}
                if _subtree_item_count(node):
                    notes.append(f"{f.get('name')} kept (not empty)")
                    continue
                eagle.move_folder(fid, bin_folder(lib))
                if PACE:
                    time.sleep(PACE)
                n_folders += 1
                continue
            if f.get("prior_name") and f.get("prior_name") != f.get("name"):
                eagle.rename_folder(fid, f["prior_name"])
                n_folders += 1
            if (f.get("prior_parent") or "") != (f.get("parent") or ""):
                eagle.move_folder(fid, f.get("prior_parent") or None)
                if PACE:
                    time.sleep(PACE)
                n_folders += 1
    except eagle.EagleError as e:
        raise AlbumError(f"undo stopped: {e}")
    ledger.pop_last()
    ledger.append({"verb": "undo", "lib": lib,
                   "note": f"undid {op.get('verb')} of {op.get('when')}"})
    bits = [f"↩️ Undid {op.get('verb') or 'op'}", f"{n_items} shots back"]
    if n_folders:
        bits.append(f"{n_folders} folder(s) back")
    bits += notes
    pieces = _ticktick_pieces(op)
    if pieces:
        bits.append("TickTick by hand: " + " · ".join(pieces))
    return " · ".join(bits)
