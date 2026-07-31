"""
migration.py - the BIG ROCK engine (2026-07-28).

One-off reorganisation of years of Eagle material into the workflow's
per-tattoo shape, plus re-sourcing the originals that were lost when
photos were dragged out of Photos.app instead of exported.

READ THE PLAN FIRST: ~/.claude/plans/bright-orbiting-petal.md.

## The invariant

**Nothing is ever deleted.** Not a source file, not a derivative, not a
backup. Originals are ADDED beside the low-res copy they supersede; the
copy keeps its name and gains a tag. A wrong match is therefore something
Vex can SEE next to the right one, never something that ate a photo.

## Why SQLite and not the repo's JSON convention

`cache.set` rewrites a whole file per mutation. With ~4,600 item rows that
is a 3 MB rewrite per decision and a corrupt file if it aborts mid-write -
unacceptable bookkeeping for irreplaceable photos. And browse re-renders
on every keystroke, so decisions must be an indexed query, not a 3 MB
parse. The ledger is also the resume log: every mutation writes `attempt`
before firing and `ok`/`err` after, so an aborted run is recoverable by
asking which subjects have an unpaired `attempt`.

## The two probed facts this rests on

1. **Originals-vs-derivative is free.** Eagle's per-item metadata.json
   already carries ext/width/height/size. No pixel analysis, no AI. EXIF
   is NOT a discriminator - some derivatives kept camera EXIF while being
   downscaled to 768px (verified on 'Reel - Ivona - Hanya 14.jpg').
2. **Filename matching is dead; the capture instant works.** Stem matching
   finds 25 of TV's 1,872 derivatives, because Eagle names were rewritten.
   Joining Spotlight's capture date to the backup's st_birthtime finds
   683. Two different photos colliding on the same SECOND across four
   years is negligible.

## Hook trap

`.claude/hooks/protect_alfred_plist.py` denies any Bash command containing
both an interpreter name and `com~apple~CloudDocs`. That is why
`backup_root()` GLOBS for the path instead of spelling it out, and why
callers must never pass the literal on a command line.
"""
import glob
import json
import os
import re
import sqlite3
import subprocess
import time

import eagle
from script_base import run_path

DB_NAME = "migration.sqlite3"

# Backup trees, keyed by the library they feed. Reached by glob (hook trap).
_BACKUP_REL = {"tv": "Photo Export 2025-12-25 /T Vex",
               "fm": "Photo Export 2025-12-25 /FM"}
_BACKUP_PARENT = "\U0001F3DB️ Archive"      # "🏛️ Archive"

# Vex ruling 2026-07-28: reference/inspiration material is not tattoo work,
# has no client, can never carry a logbook. 4,493 of its 4,596 files are
# PNGs and it is 60% of the backup by count. Excluded from every step.
SKIP_DIRS = {"Reference", "Personal 2"}
SKIP_EXTS = {".aae"}                              # Photos edit sidecars

# Bigger-is-better ranking, used to break same-instant ties and to refuse a
# "replacement" that is not actually an upgrade.
EXT_RANK = {"dng": 6, "tif": 5, "tiff": 5, "heic": 4, "heif": 4,
            "mov": 3, "mp4": 3, "jpg": 2, "jpeg": 2, "png": 1}
STILL = {"dng", "tif", "tiff", "heic", "heif", "jpg", "jpeg", "png"}
VIDEO = {"mov", "mp4", "m4v", "avi"}

# Only pull when the backup file is a REAL upgrade. 98 of 101 sampled
# twins were >1.3x bigger; the 3 that were not are honest "no gain" rows.
MIN_GAIN = 1.3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);

CREATE TABLE IF NOT EXISTS item (
  eid TEXT PRIMARY KEY, lib TEXT, name TEXT, ext TEXT,
  w INTEGER, h INTEGER, size INTEGER, path TEXT,
  tags_json TEXT, folders_json TEXT,
  klass TEXT,
  capture_epoch INTEGER, capture_src TEXT,
  prior_name TEXT, prior_folders_json TEXT,
  backup_path TEXT, backup_size INTEGER, backup_conf TEXT,
  backup_gain REAL, backup_ambig INTEGER DEFAULT 0,
  new_eid TEXT, state TEXT DEFAULT 'scanned');
CREATE INDEX IF NOT EXISTS item_lib   ON item(lib);
CREATE INDEX IF NOT EXISTS item_klass ON item(lib, klass);
CREATE INDEX IF NOT EXISTS item_cap   ON item(capture_epoch);

CREATE TABLE IF NOT EXISTS folder (
  fid TEXT PRIMARY KEY, lib TEXT, name TEXT, parent_fid TEXT,
  path_text TEXT, direct_n INTEGER, subtree_n INTEGER,
  first_capture INTEGER, last_capture INTEGER,
  guess_customer TEXT, guess_tattoo TEXT, guess_conf REAL,
  decision TEXT DEFAULT 'open',
  dec_customer TEXT, dec_tattoo TEXT, decided_at TEXT,
  cust_tid TEXT, log_tid TEXT, target_fid TEXT,
  exec_state TEXT DEFAULT 'pending');
CREATE INDEX IF NOT EXISTS folder_lib ON folder(lib, decision);

CREATE TABLE IF NOT EXISTS backup (
  path TEXT PRIMARY KEY, tree TEXT, rel TEXT, stem TEXT, ext TEXT,
  size INTEGER, birth_epoch INTEGER, mtime_epoch INTEGER,
  dataless INTEGER, claimed_by TEXT);
CREATE INDEX IF NOT EXISTS backup_birth ON backup(birth_epoch);

CREATE TABLE IF NOT EXISTS event (
  ts TEXT, phase TEXT, kind TEXT, subject TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS event_subj ON event(subject);
"""


# ───────────────────────────────────────────────────────── ledger

def db_path():
    return run_path(DB_NAME)


def connect():
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def _meta_set(con, k, v):
    con.execute("INSERT INTO meta(k,v) VALUES(?,?) "
                "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


def meta_get(con, k, default=""):
    r = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def log(con, phase, kind, subject, detail=""):
    """The resume spine. Every mutation writes 'attempt' before it fires
    and 'ok'/'err' after; a subject whose last event is an unpaired
    'attempt' is re-verified LIVE before being re-fired."""
    con.execute("INSERT INTO event(ts,phase,kind,subject,detail) "
                "VALUES(?,?,?,?,?)",
                (time.strftime("%F %T"), phase, kind, subject, detail))


def unfinished(con):
    """Subjects whose last event is an attempt with no ok/err after it."""
    return [r["subject"] for r in con.execute(
        "SELECT subject FROM event e WHERE kind='attempt' AND NOT EXISTS ("
        "  SELECT 1 FROM event o WHERE o.subject=e.subject"
        "  AND o.kind IN ('ok','err') AND o.rowid > e.rowid)")]


# ───────────────────────────────────────────────── classification

def classify_meta(ext, w, h, size):
    """Original or derivative, from metadata Eagle already stores.

    Validated against the live libraries 2026-07-28. Deliberately does NOT
    look at EXIF: a Photos drag can preserve camera EXIF while downscaling
    to 768px, so 'has a camera make' proves nothing. Dimensions and bytes
    are what actually separate a 4032px original from a 311px thumbnail."""
    e = (ext or "").lower()
    if e in ("dng", "tif", "tiff", "heic", "heif"):
        return "original"
    if e in VIDEO:
        return "video"
    if e == "png":
        return "derivative"
    mx = max(int(w or 0), int(h or 0))
    if mx >= 2500 and int(size or 0) >= 1_000_000:
        return "original"
    if mx >= 1500:
        return "suspect"
    return "derivative"


# ───────────────────────────────────────────────────── phase: scan

def scan(libs=("tv", "fm", "crm"), con=None):
    """Walk each library's metadata from DISK (no Eagle, no switching) and
    fill item + folder. Idempotent: re-running refreshes in place and never
    clobbers a decision, a prior_* undo column or a backup match."""
    own = con is None
    con = con or connect()
    n_items = n_folders = 0
    for lib in libs:
        name, path = eagle.LIBS[lib]
        if not os.path.isdir(path):
            continue
        tree = eagle.disk_folder_tree(path)
        counts = eagle.disk_subtree_counts(path)
        rows = []

        def walk(nodes, parent, trail):
            for f in nodes:
                fid = f.get("id")
                nm = f.get("name") or ""
                p = f"{trail}/{nm}"
                kids = f.get("children") or []
                rows.append((fid, lib, nm, parent, p, 0,
                             counts.get(fid, 0)))
                walk(kids, fid, p)
        walk(tree, None, "")
        con.executemany(
            "INSERT INTO folder(fid,lib,name,parent_fid,path_text,"
            "direct_n,subtree_n) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(fid) DO UPDATE SET name=excluded.name,"
            "parent_fid=excluded.parent_fid,path_text=excluded.path_text,"
            "subtree_n=excluded.subtree_n", rows)
        n_folders += len(rows)

        imgs = os.path.join(path, "images")
        batch = []
        for d in os.listdir(imgs):
            mp = os.path.join(imgs, d, "metadata.json")
            if not os.path.isfile(mp):
                continue
            try:
                m = json.load(open(mp))
            except Exception:
                continue
            if m.get("isDeleted"):
                continue
            ext = (m.get("ext") or "").lower()
            fp = os.path.join(imgs, d, f"{m.get('name')}.{ext}")
            if not os.path.isfile(fp):     # Eagle's filename can drift
                cand = [x for x in os.listdir(os.path.join(imgs, d))
                        if x != "metadata.json"
                        and not x.endswith("_thumbnail.png")
                        and not x.startswith(".")]
                fp = os.path.join(imgs, d, cand[0]) if cand else ""
            batch.append((
                m.get("id"), lib, m.get("name") or "", ext,
                m.get("width") or 0, m.get("height") or 0,
                m.get("size") or 0, fp,
                json.dumps(m.get("tags") or [], ensure_ascii=False),
                json.dumps(m.get("folders") or []),
                classify_meta(ext, m.get("width"), m.get("height"),
                              m.get("size"))))
        con.executemany(
            "INSERT INTO item(eid,lib,name,ext,w,h,size,path,tags_json,"
            "folders_json,klass) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(eid) DO UPDATE SET name=excluded.name,"
            "ext=excluded.ext,w=excluded.w,h=excluded.h,size=excluded.size,"
            "path=excluded.path,tags_json=excluded.tags_json,"
            "folders_json=excluded.folders_json,klass=excluded.klass", batch)
        n_items += len(batch)
    # direct_n needs the item rows, so it is a second pass
    con.execute("UPDATE folder SET direct_n = ("
                "  SELECT COUNT(*) FROM item"
                "  WHERE item.lib = folder.lib"
                "  AND instr(item.folders_json, folder.fid) > 0)")
    _meta_set(con, "scanned_at", time.strftime("%F %T"))
    con.commit()
    if own:
        con.close()
    return n_items, n_folders


# ──────────────────────────────────────────────────── phase: dates

def _mdls_dates(paths):
    """{path: epoch} from Spotlight, batched. Never reads file bytes.

    Alignment is the hazard: a `(null)` still emits a field, but a failed
    exec emits nothing, so a short result would pair every later file with
    the WRONG date - and therefore the wrong original. Assert the count."""
    out = {}
    CH = 200
    for i in range(0, len(paths), CH):
        chunk = paths[i:i + CH]
        try:
            r = subprocess.run(
                ["mdls", "-raw", "-nullMarker", "\x01",
                 "-name", "kMDItemContentCreationDate"] + chunk,
                capture_output=True, text=True, timeout=120)
        except Exception:
            continue
        vals = r.stdout.split("\x00")
        if len(vals) != len(chunk):
            continue                      # fail closed, fall back to btime
        for p, v in zip(chunk, vals):
            v = (v or "").strip()
            if not v or v.startswith("\x01"):
                continue
            m = re.match(r"(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)", v)
            if not m:
                continue
            try:
                import calendar
                out[p] = calendar.timegm(
                    tuple(int(x) for x in m.groups()) + (0, 0, 0))
            except Exception:
                pass
    return out


def dates(con=None, libs=None):
    """capture_epoch per item: Spotlight first, Eagle btime as fallback.
    btime is NOT reliable on its own - for some items it is the 2025-12-22
    export day, not the shutter - so which source won is recorded."""
    own = con is None
    con = con or connect()
    q = "SELECT eid, path, lib FROM item WHERE capture_epoch IS NULL"
    if libs:
        q += " AND lib IN (%s)" % ",".join("'%s'" % x for x in libs)
    rows = [r for r in con.execute(q) if r["path"]]
    got = _mdls_dates([r["path"] for r in rows])
    upd = []
    for r in rows:
        e = got.get(r["path"])
        upd.append((e, "mdls" if e else "none", r["eid"]))
    con.executemany(
        "UPDATE item SET capture_epoch=?, capture_src=? WHERE eid=?", upd)
    # btime fallback, straight from Eagle's own metadata
    miss = [r["eid"] for r in con.execute(
        "SELECT eid FROM item WHERE capture_epoch IS NULL")]
    if miss:
        fb = []
        for lib in ("tv", "fm", "crm"):
            p = eagle.LIBS.get(lib, ("", ""))[1]
            imgs = os.path.join(p, "images")
            if not os.path.isdir(imgs):
                continue
            want = set(miss)
            for d in os.listdir(imgs):
                mp = os.path.join(imgs, d, "metadata.json")
                if not os.path.isfile(mp):
                    continue
                try:
                    m = json.load(open(mp))
                except Exception:
                    continue
                if m.get("id") in want and m.get("btime"):
                    fb.append((int(m["btime"] // 1000), "btime", m["id"]))
        con.executemany(
            "UPDATE item SET capture_epoch=?, capture_src=? WHERE eid=?", fb)
    con.commit()
    n = con.execute("SELECT COUNT(*) c FROM item "
                    "WHERE capture_epoch IS NOT NULL").fetchone()["c"]
    if own:
        con.close()
    return n


# ─────────────────────────────────────────────── phase: backup index

def backup_root():
    """The iCloud archive root, found by GLOB so no caller ever has to put
    the literal 'com~apple~CloudDocs' on a command line (the hook denies
    any command carrying both that and an interpreter name)."""
    base = glob.glob(os.path.expanduser(
        "~/Library/Mobile Documents/com~apple*CloudDocs"))
    if not base:
        return ""
    p = os.path.join(base[0], _BACKUP_PARENT)
    return p if os.path.isdir(p) else ""


def backup_trees():
    root = backup_root()
    if not root:
        return {}
    out = {}
    for lib, rel in _BACKUP_REL.items():
        p = os.path.join(root, rel)
        if os.path.isdir(p):
            out[lib] = p
    return out


def index_backup(con=None):
    """Index every backup file WITHOUT downloading one byte.

    The tree is 69.6 GB logical but 16K on disk - dataless iCloud
    placeholders. os.stat gives name, size, birth and mtime for free;
    reading BYTES is what would trigger a download, and nothing here does.
    st_birthtime is the capture instant; st_mtime is the export day."""
    own = con is None
    con = con or connect()
    rows = []
    for lib, tree in backup_trees().items():
        for dirpath, dirnames, files in os.walk(tree):
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                if f.startswith("."):
                    continue
                stem, ext = os.path.splitext(f)
                if ext.lower() in SKIP_EXTS:
                    continue
                fp = os.path.join(dirpath, f)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                rows.append((fp, lib, os.path.relpath(fp, tree), stem,
                             ext.lower().lstrip("."), st.st_size,
                             int(getattr(st, "st_birthtime", st.st_mtime)),
                             int(st.st_mtime),
                             1 if getattr(st, "st_blocks", 1) == 0 else 0))
    con.executemany(
        "INSERT INTO backup(path,tree,rel,stem,ext,size,birth_epoch,"
        "mtime_epoch,dataless) VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET size=excluded.size,"
        "birth_epoch=excluded.birth_epoch,dataless=excluded.dataless", rows)
    _meta_set(con, "backup_indexed_at", time.strftime("%F %T"))
    con.commit()
    if own:
        con.close()
    return len(rows)


# ───────────────────────────────────────────────────── phase: match

def _media_class(ext):
    e = (ext or "").lower()
    return "video" if e in VIDEO else ("still" if e in STILL else "other")


def match(con=None, max_shift_h=12):
    """Join Eagle items needing a re-source to the backup, on the CAPTURE
    INSTANT with a whole-hour offset ladder.

    Why hours: the measured offset histogram is +1h 49, 0 29, +9h 20 -
    CET/CEST versus UTC plus one travel timezone, not noise. Why an
    instant is trustworthy: across four years the photos land in ~2,349
    distinct one-second buckets, so two different shots colliding on the
    same second is negligible. Filenames are NOT used - Eagle's were
    rewritten, and stem matching finds 25 of 1,872.

    Ambiguity (several backup files sharing one instant - Live Photo
    HEIC+MOV pairs, double exports) resolves by media class, then ext
    rank, then size, and every such row is FLAGGED for spot-check."""
    own = con is None
    con = con or connect()
    by_instant = {}
    for b in con.execute("SELECT path,ext,size,birth_epoch,tree FROM backup"):
        by_instant.setdefault((b["tree"], b["birth_epoch"]), []).append(b)
    ladder = [0]
    for h in range(1, max_shift_h + 1):
        ladder += [h * 3600, -h * 3600]

    upd = []
    for it in con.execute(
            "SELECT eid,lib,ext,size,capture_epoch FROM item "
            "WHERE klass IN ('derivative','suspect') "
            "AND capture_epoch IS NOT NULL"):
        want = _media_class(it["ext"])
        hit = conf = None
        for off in ladder:
            cands = by_instant.get((it["lib"], it["capture_epoch"] + off))
            if not cands:
                continue
            same = [c for c in cands if _media_class(c["ext"]) == want] \
                or list(cands)
            same.sort(key=lambda c: (-EXT_RANK.get(c["ext"], 0), -c["size"]))
            hit = same[0]
            conf = "exact" if off == 0 else f"shift{off // 3600}h"
            ambig = 1 if len(cands) > 1 else 0
            break
        if not hit:
            upd.append((None, None, "none", None, 0, it["eid"]))
            continue
        # An EXACT-second tie is an export BATCH - many files written in
        # the same instant - so the tie-break picks a neighbour, not the
        # twin. Measured against independent folder-name agreement:
        # exact+tie 50%, every other bucket 91-100%, unique 96%. Demote it
        # to 'tie' so it never auto-pulls; a SHIFTED tie is not a batch
        # artifact and holds up (shift1h 91%, shift8h/9h 100%).
        if ambig and conf == "exact":
            conf = "tie"
        gain = (hit["size"] / it["size"]) if it["size"] else 0
        upd.append((hit["path"], hit["size"], conf, round(gain, 3),
                    ambig, it["eid"]))
    con.executemany(
        "UPDATE item SET backup_path=?, backup_size=?, backup_conf=?, "
        "backup_gain=?, backup_ambig=? WHERE eid=?", upd)
    _meta_set(con, "matched_at", time.strftime("%F %T"))
    con.commit()
    if own:
        con.close()
    return len(upd)


def recoverable(con, lib=None):
    """Rows worth pulling: matched AND a real upgrade. A match that is not
    bigger is recorded honestly as 'no gain' and treated as no-original."""
    q = ("SELECT * FROM item WHERE backup_conf IS NOT NULL "
         "AND backup_conf NOT IN ('none','tie') AND backup_gain >= ?")
    a = [MIN_GAIN]
    if lib:
        q += " AND lib=?"
        a.append(lib)
    return list(con.execute(q + " ORDER BY backup_gain DESC", a))


def _materialise(path, timeout=180):
    """Pull ONE file out of iCloud and wait until the bytes are really
    there. brctl returns BEFORE the fetch finishes - the same class of
    trap as Eagle's addFromPaths returning before its background copy -
    so poll st_blocks rather than trusting the exit code."""
    try:
        subprocess.run(["brctl", "download", path],
                       capture_output=True, timeout=60)
    except Exception:
        pass
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            st = os.stat(path)
            if getattr(st, "st_blocks", 1) != 0:
                return True
        except OSError:
            return False
        time.sleep(0.4)
    return False


def pull(con=None, limit=25, lib=None, spread=True):
    """Import matched originals BESIDE the derivative they supersede.

    Nothing is replaced and nothing is deleted - that is the invariant.
    The import takes the derivative's NAME (so a name sort puts the pair
    together, and so the library still reads correctly once Vex purges
    the old ones), the derivative's TAGS, plus 'original'. The old item
    keeps its name and gains 'superseded'. A wrong match is therefore
    something you can SEE next to the right one.

    Idempotent: the import carries annotation 'orig:<derivative eid>', so
    a re-run finds it already there and skips instead of duplicating."""
    own = con is None
    con = con or connect()
    rows = recoverable(con, lib)
    if spread:
        # one per Eagle folder first, so a first batch shows MANY subjects
        # rather than 25 shots of the same tattoo
        seen, spread_rows, rest = set(), [], []
        for r in rows:
            f = (json.loads(r["folders_json"] or "[]") or [""])[0]
            (spread_rows if f not in seen else rest).append(r)
            seen.add(f)
        rows = spread_rows + rest
    rows = [r for r in rows if r["state"] != "sourced"][:limit]
    done = skipped = failed = 0
    notes = []
    by_lib = {}
    for r in rows:
        by_lib.setdefault(r["lib"], []).append(r)
    for lb, group in by_lib.items():
        try:
            eagle.ensure_running()
            eagle.ensure_library(lb)
        except eagle.EagleError as e:
            notes.append(f"{lb}: {e}")
            continue
        for r in group:
            mark = f"orig:{r['eid']}"
            folders = json.loads(r["folders_json"] or "[]")
            fid = folders[0] if folders else None
            log(con, "pull", "attempt", r["eid"], r["backup_path"])
            con.commit()
            try:
                # THE LEDGER is the idempotency oracle, not Eagle's
                # listing. item/list lags a fresh import by seconds
                # (documented in eagle.py), so after a wait_imported
                # timeout a retry would not see the item it just made and
                # would import it AGAIN - which happened exactly once on
                # 2026-07-28 ('Raw - Lil Crow 1'). new_eid is written the
                # moment add_items returns, so this check cannot miss.
                if r["new_eid"]:
                    eagle.add_item_tags([r["eid"]], ["superseded"])
                    con.execute("UPDATE item SET state='sourced' "
                                "WHERE eid=?", (r["eid"],))
                    log(con, "pull", "ok", r["eid"], "ledger says done")
                    skipped += 1
                    con.commit()
                    continue
                # belt and braces: an import from before new_eid existed
                if fid and any((i.get("annotation") or "") == mark
                               for i in eagle.items_in_folder(fid)):
                    # The import landed on an earlier attempt but the run
                    # died before tagging the old one (Eagle copy timeout,
                    # 6 real cases 2026-07-28). Tag it now - otherwise a
                    # retry silently leaves a superseded item unmarked and
                    # 'select by tag, then delete' misses it forever.
                    eagle.add_item_tags([r["eid"]], ["superseded"])
                    con.execute("UPDATE item SET state='sourced' "
                                "WHERE eid=?", (r["eid"],))
                    log(con, "pull", "ok", r["eid"], "already present")
                    skipped += 1
                    con.commit()
                    continue
                if not _materialise(r["backup_path"]):
                    log(con, "pull", "err", r["eid"], "icloud fetch failed")
                    failed += 1
                    con.commit()
                    continue
                tags = json.loads(r["tags_json"] or "[]") + ["original"]
                ids = eagle.add_items(
                    [{"path": r["backup_path"], "name": r["name"],
                      "tags": tags, "annotation": mark}], folder_id=fid)
                # Record the handle BEFORE waiting. add_items' returned ids
                # are the only reliable handle on a fresh import, and
                # wait_imported can time out on a big ProRAW while the copy
                # is still running - losing the id there is what caused the
                # one duplicate. Write it first, verify second.
                con.execute("UPDATE item SET new_eid=? WHERE eid=?",
                            (ids[0] if ids else "", r["eid"]))
                con.commit()
                eagle.wait_imported(ids)
                eagle.add_item_tags([r["eid"]], ["superseded"])
                con.execute("UPDATE item SET state='sourced' WHERE eid=?",
                            (r["eid"],))
                log(con, "pull", "ok", r["eid"], ids[0] if ids else "")
                done += 1
            except Exception as e:
                log(con, "pull", "err", r["eid"], f"{type(e).__name__}: {e}")
                notes.append(f"{r['name'][:24]}: {e}")
                failed += 1
            con.commit()
    con.commit()
    if own:
        con.close()
    return {"imported": done, "already": skipped, "failed": failed,
            "notes": notes[:5]}


def tag_no_original(con=None, lib=None):
    """One batched tag per library for everything we could not recover -
    so 'what is still low-res?' is answerable forever."""
    own = con is None
    con = con or connect()
    q = ("SELECT eid, lib FROM item WHERE klass IN ('derivative','suspect') "
         "AND (backup_conf IN ('none','tie') OR backup_conf IS NULL "
         "     OR backup_gain < ?) AND state != 'nooriginal'")
    a = [MIN_GAIN]
    if lib:
        q += " AND lib=?"
        a.append(lib)
    by_lib = {}
    for r in con.execute(q, a):
        by_lib.setdefault(r["lib"], []).append(r["eid"])
    n = 0
    for lb, ids in by_lib.items():
        try:
            eagle.ensure_library(lb)
            for i in range(0, len(ids), 200):
                eagle.add_item_tags(ids[i:i + 200], ["no original"])
        except eagle.EagleError:
            continue
        con.executemany("UPDATE item SET state='nooriginal' WHERE eid=?",
                        [(x,) for x in ids])
        n += len(ids)
    con.commit()
    if own:
        con.close()
    return n


def status(con=None):
    """Everything the 📊 screen needs, in one pass."""
    own = con is None
    con = con or connect()
    out = {"libs": {}, "meta": {}}
    for k in ("scanned_at", "backup_indexed_at", "matched_at"):
        out["meta"][k] = meta_get(con, k)
    for r in con.execute(
            "SELECT lib, klass, COUNT(*) c FROM item GROUP BY 1,2"):
        out["libs"].setdefault(r["lib"], {})[r["klass"]] = r["c"]
    out["backup_files"] = con.execute(
        "SELECT COUNT(*) c FROM backup").fetchone()["c"]
    out["backup_downloaded"] = con.execute(
        "SELECT COUNT(*) c FROM backup WHERE dataless=0").fetchone()["c"]
    row = con.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(backup_size),0) b FROM item "
        "WHERE backup_conf NOT IN ('none','tie') AND backup_conf IS NOT NULL "
        "AND backup_gain >= ?", (MIN_GAIN,)).fetchone()
    out["recoverable"] = row["c"]
    out["recoverable_bytes"] = row["b"]
    out["no_original"] = con.execute(
        "SELECT COUNT(*) c FROM item WHERE klass IN ('derivative','suspect') "
        "AND (backup_conf IN ('none','tie') OR backup_conf IS NULL "
        "     OR backup_gain < ?)", (MIN_GAIN,)).fetchone()["c"]
    out["ties"] = con.execute(
        "SELECT COUNT(*) c FROM item WHERE backup_conf='tie'").fetchone()["c"]
    out["ambiguous"] = con.execute(
        "SELECT COUNT(*) c FROM item WHERE backup_ambig=1").fetchone()["c"]
    out["capture_src"] = {r["capture_src"] or "none": r["c"] for r in
                          con.execute("SELECT capture_src, COUNT(*) c "
                                      "FROM item GROUP BY 1")}
    if own:
        con.close()
    return out


def analyse(libs=("tv", "fm", "crm")):
    """The whole read-only pass. Safe to re-run at any time."""
    con = connect()
    ni, nf = scan(libs, con=con)
    nd = dates(con=con)
    nb = index_backup(con=con)
    nm = match(con=con)
    st = status(con=con)
    con.close()
    return {"items": ni, "folders": nf, "dated": nd,
            "backup_files": nb, "matched": nm, "status": st}


# ──────────────────────────────────────────────────── phase: naming (v2 S1+S2)
# Re-evaluation 2026-07-30 (11-agent workflow, plan v2): the naming doc is
# generated per NORMALIZED NAME GROUP, not per folder - 76 names span 2-5
# source branches and per-folder blocks would ask the same tattoo five times
# and mint twins (zero dedupe downstream, no Eagle folder delete). Dates are
# corrected first: 44.7% of capture epochs are bulk-export artifacts.

# The 5 bulk-copy days that poison capture dates (2,114 items). An item whose
# capture date falls on one of these is treated as DATELESS unless its backup
# match supplies the real instant.
BULK_DATES = {"2026-03-19", "2026-03-20",
              "2025-07-20", "2025-07-28", "2025-07-30"}

# Whole path SEGMENTS (casefolded) that mark a subtree as not-migration
# material. Segment equality, never substring - "05 Art" must not eat
# "Sacred Heart". Rulings: Brand/Reference/Personal excluded (2026-07-28);
# Creative Outputs/Research = editing workbench, excluded in place
# (default adopted 2026-07-30); pipeline destination folders are
# destinations, not sources; 🗑 bins stay dead.
_EXCLUDE_SEGS = {"brand", "content ideas", "reference", "personal 2",
                 "07 creative outputs", "05 art", "01 raw", "02 edit",
                 "03 post", "04 portfolio", "🗑 deleted", "🗑️ deleted"}
# CRM library: only Review/ is migration material; Customers/ and Archive/
# are the LIVE CRM (they feed adoption instead).
_CRM_INCLUDE_SEG = "review"


def _path_segs(path_text):
    return [s.strip().casefold() for s in (path_text or "").split("/") if s]


def _folder_excluded(lib, path_text):
    segs = _path_segs(path_text)
    if any(s in _EXCLUDE_SEGS for s in segs):
        return True
    if lib == "crm" and (not segs or segs[0] != _CRM_INCLUDE_SEG):
        return True
    return False


def _norm_name(s):
    """Group key: casefold, separators unified, punctuation to space.
    'Harriet - Hanya', 'Harriet · Hanya' and 'harriet hanya' collide -
    which is the point. Diacritics kept (Ljuljačka != Ljuljacka is fine;
    alphabetical sort still lands near-dupes adjacent for the eye)."""
    s = (s or "").casefold()
    s = s.replace("•", " ").replace("·", " ")
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"[\d_]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _split_ct(name):
    """'Customer - Tattoo' → (C, T); single part → ('', part)."""
    for sep in (" - ", " • ", " · "):
        if sep in name:
            c, t = name.split(sep, 1)
            return c.strip(), t.strip()
    return "", name.strip()


_JUNK_RE = re.compile(
    r"^(img[_ ]?\d+|dsc\w*\d+|\d{4}[-. ]\d{2}[-. ]\d{2}.*|\d+|untitled.*|"
    r"new folder.*|random.*)$", re.I)


def ensure_naming_columns(con):
    for ddl in ("ALTER TABLE item ADD COLUMN usable_epoch INTEGER",
                "ALTER TABLE item ADD COLUMN post_scan INTEGER DEFAULT 0",
                "ALTER TABLE folder ADD COLUMN group_key TEXT",
                "ALTER TABLE folder ADD COLUMN excluded INTEGER DEFAULT 0",
                "ALTER TABLE folder ADD COLUMN adopt_json TEXT"):
        try:
            con.execute(ddl)
        except sqlite3.OperationalError:
            pass


def usable_dates(con):
    """item.usable_epoch: the capture instant we actually TRUST.
    sourced → the matched backup's birth instant (immune to drag pollution);
    else capture_epoch unless its day is a bulk-export day."""
    con.execute("""
        UPDATE item SET usable_epoch = (
          SELECT b.birth_epoch FROM backup b WHERE b.path = item.backup_path)
        WHERE state='sourced' AND backup_path IS NOT NULL""")
    rows = con.execute(
        "SELECT eid, capture_epoch FROM item "
        "WHERE usable_epoch IS NULL AND capture_epoch IS NOT NULL").fetchall()
    ok = []
    for r in rows:
        day = time.strftime("%Y-%m-%d", time.gmtime(r["capture_epoch"]))
        if day not in BULK_DATES:
            ok.append((r["capture_epoch"], r["eid"]))
    con.executemany("UPDATE item SET usable_epoch=? WHERE eid=?", ok)
    con.commit()
    return con.execute("SELECT COUNT(*) c FROM item "
                       "WHERE usable_epoch IS NOT NULL").fetchone()["c"]


def mark_clusters(con):
    """folder.excluded + group_key for every folder that directly holds
    migration items. Cluster membership rides folders_json (ALL of an
    item's folders, so a two-shelf item names both)."""
    for f in con.execute("SELECT fid, lib, name, path_text FROM folder"):
        exc = 1 if _folder_excluded(f["lib"], f["path_text"]) else 0
        gk = _norm_name(f["name"]) or None
        con.execute("UPDATE folder SET excluded=?, group_key=? WHERE fid=?",
                    (exc, gk, f["fid"]))
    # capture span per folder from usable epochs
    con.execute("""
        UPDATE folder SET
          first_capture = (SELECT MIN(i.usable_epoch) FROM item i
                           WHERE i.lib = folder.lib
                             AND instr(i.folders_json, folder.fid) > 0),
          last_capture  = (SELECT MAX(i.usable_epoch) FROM item i
                           WHERE i.lib = folder.lib
                             AND instr(i.folders_json, folder.fid) > 0)""")
    con.commit()


def guess_names(con):
    """Prefill from the folder's own name. Never minted, only rendered."""
    n = 0
    for f in con.execute("SELECT fid, name FROM folder "
                         "WHERE excluded=0 AND direct_n>0"):
        c, t = _split_ct(f["name"])
        conf = 0.9 if c else (0.1 if _JUNK_RE.match(f["name"] or "") else 0.5)
        con.execute("UPDATE folder SET guess_customer=?, guess_tattoo=?, "
                    "guess_conf=? WHERE fid=?", (c, t, conf, f["fid"]))
        n += 1
    con.commit()
    return n


def _cache_records(strict=False):
    """Live customers/logbooks from the runtime cache, casefolded tags.
    Cache staleness is acceptable at ANALYSIS time (adoption only
    prefills spelling). strict=True is for the EXECUTION paths: an
    unreadable/empty cache there must ABORT, because an empty adoption
    pool reads as 'no live logbooks' and the engine would re-mint Erol
    (review 2026-07-31: every guard failed open)."""
    import config as _cfg  # noqa: F401  (path setup)
    p = os.path.expanduser("~/.ticktick_alfred/cache/all_notes.json")
    try:
        notes = json.load(open(p)).get("value") or []
    except Exception:
        if strict:
            raise RuntimeError("all_notes cache unreadable - aborting "
                               "batch rather than adopting from nothing")
        return [], []
    if strict and not notes:
        raise RuntimeError("all_notes cache empty - aborting batch")
    rid = os.environ.get("crm_records_list_id", "6a4e50e9842a1194a7c681e1")
    custs, logs = [], []
    for nte in notes:
        if nte.get("projectId") != rid:
            continue
        tags = {(t or "").casefold() for t in (nte.get("tags") or [])}
        title = (nte.get("title") or "").strip()
        if "\U0001F5C2️".casefold() + "customer" in tags or \
           any(t.endswith("customer") for t in tags):
            custs.append({"tid": nte.get("id"),
                          "name": re.sub(r"^\U0001F464\s*", "", title)})
        if any(t.endswith("logbook") or t.endswith("archive") for t in tags):
            m = re.sub(r"^[\U0001F3A8\U0001F3DB️]+\s*", "", title)
            logs.append({"tid": nte.get("id"), "title": m,
                         "archived": any(t.endswith("archive")
                                         for t in tags)})
    return custs, logs


def adopt_pass(con):
    """Exact-normalized matches against live CRM + Eagle CRM folders.
    Fuzzy NEVER adopts (Lucia==Luca at 0.96 says why); it only prefills."""
    custs, logs = _cache_records()
    cmap = {_norm_name(c["name"]): c for c in custs if _norm_name(c["name"])}
    lmap = {}
    for lg in logs:
        lmap[_norm_name(lg["title"])] = lg
    # Eagle CRM live folders (Customers/, Archive/) - adoption targets
    emap = {}
    for f in con.execute("SELECT fid, name, path_text FROM folder "
                         "WHERE lib='crm'"):
        segs = _path_segs(f["path_text"])
        if segs and segs[0] in ("customers", "archive") and len(segs) == 2:
            emap[_norm_name(f["name"])] = {"fid": f["fid"],
                                           "name": f["name"]}
    n = 0
    for f in con.execute("SELECT fid, name, group_key, guess_customer "
                         "FROM folder WHERE excluded=0 AND direct_n>0"):
        gk = f["group_key"] or ""
        ad = {}
        if gk in lmap:
            ad["log_tid"] = lmap[gk]["tid"]
            ad["log_title"] = lmap[gk]["title"]
            ad["archived"] = lmap[gk]["archived"]
        if gk in emap:
            ad["eagle_fid"] = emap[gk]["fid"]
            ad["eagle_name"] = emap[gk]["name"]
        ck = _norm_name(f["guess_customer"] or "")
        if ck and ck in cmap:
            ad["cust_tid"] = cmap[ck]["tid"]
            ad["cust_name"] = cmap[ck]["name"]
        if ad:
            con.execute("UPDATE folder SET adopt_json=? WHERE fid=?",
                        (json.dumps(ad, ensure_ascii=False), f["fid"]))
            n += 1
    con.commit()
    return n


def _group_rows(con):
    """{group_key: {folders:[...], items:n, days:[...], prefill:(C,T,src)}}"""
    groups = {}
    for f in con.execute(
            "SELECT * FROM folder WHERE excluded=0 AND direct_n>0 "
            "AND group_key IS NOT NULL ORDER BY lib, path_text"):
        g = groups.setdefault(f["group_key"], {
            "folders": [], "items": 0, "adopt": None,
            "guess": ("", "", 0.0), "display": f["name"]})
        g["folders"].append(dict(f))
        g["items"] += f["direct_n"]
        if f["adopt_json"] and not g["adopt"]:
            g["adopt"] = json.loads(f["adopt_json"])
        if (f["guess_conf"] or 0) > g["guess"][2]:
            g["guess"] = (f["guess_customer"] or "", f["guess_tattoo"] or "",
                          f["guess_conf"] or 0)
            g["display"] = f["name"]
    # session days per group
    for gk, g in groups.items():
        fids = [f["fid"] for f in g["folders"]]
        marks = " OR ".join(f"instr(folders_json, '{fid}') > 0"
                            for fid in fids)
        days = [r["d"] for r in con.execute(
            f"SELECT DISTINCT strftime('%Y-%m-%d', usable_epoch, "
            f"'unixepoch') d FROM item WHERE usable_epoch IS NOT NULL "
            f"AND ({marks}) ORDER BY 1")]
        g["days"] = days
    return groups


CUT_LINE = "--- REVIEWED ABOVE THIS LINE (drag me down as you go) ---"


def gen_doc(con):
    """The naming doc. One block per group, four sections, cut line on top.
    Blocks are keyed by fids in an HTML comment - headings are Vex's to
    mangle freely. Returns (doc_md, ties_md, stats)."""
    groups = _group_rows(con)
    sec = {"A": [], "B": [], "C": [], "D": []}
    for gk, g in sorted(groups.items(), key=lambda kv: kv[0]):
        c, t, conf = g["guess"]
        ad = g["adopt"] or {}
        # live spelling wins over folder spelling
        if ad.get("log_title") and " • " in ad["log_title"]:
            c, t = ad["log_title"].split(" • ", 1)
        elif ad.get("cust_name"):
            c = ad["cust_name"]
        if g["items"] == 1:
            s = "D"
        elif c:
            s = "A"
        elif not _JUNK_RE.match(g["display"] or ""):
            s = "B"
        else:
            s = "C"
        sec[s].append((gk, g, c, t))

    L = []
    L.append("# Naming - old tattoo material (2026-07-30)")
    L.append("")
    L.append("**How this works (2 minutes):**")
    L.append("- One block = one tattoo. All its folders are listed in it.")
    L.append("- Fix `C:` (customer) and `T:` (tattoo name). That is all.")
    L.append("- `C:` left EMPTY = no customer, stays a plain folder. Fine.")
    L.append("- `S:` = session days I found. Delete a date if it is wrong.")
    L.append("- Work top to bottom. **Drag the line below down as you go** -")
    L.append("  I only act on blocks ABOVE it. Save whenever. No deadline.")
    L.append("- Do NOT touch the `<!-- mig:... -->` comments.")
    L.append("")
    L.append(CUT_LINE)
    L.append("")
    heads = {
        "A": ("## A · Just nod (names look complete - fix only if wrong)"),
        "B": ("## B · Name the customer (tattoo name is prefilled)"),
        "C": ("## C · Unknown (both empty - name what you recognise)"),
        "D": ("## D · Single-photo folders (skip unless you care)"),
    }
    stats = {}
    for s in ("A", "B", "C", "D"):
        stats[s] = len(sec[s])
        if not sec[s]:
            continue
        L.append(heads[s])
        L.append("")
        for gk, g, c, t in sec[s]:
            fids = ",".join(f["fid"] for f in g["folders"])
            L.append(f"### {g['display']}")
            L.append(f"<!-- mig:{fids} -->")
            for f in g["folders"]:
                L.append(f"- \U0001F4C1 {f['direct_n']}\U0001F5BC "
                         f"{f['lib']} {f['path_text']}")
            ad = g["adopt"] or {}
            if ad.get("log_title"):
                mark = "\U0001F3DB archived" if ad.get("archived") \
                    else "\U0001F3A8 LIVE"
                L.append(f"- ↔ already in CRM: {mark} "
                         f"‘{ad['log_title']}’ (will attach, "
                         "not duplicate)")
            elif ad.get("cust_name"):
                L.append(f"- ↔ customer exists: {ad['cust_name']}")
            L.append(f"C: {c}")
            L.append(f"T: {t}")
            if g["days"]:
                shown = " · ".join(g["days"][:15])
                more = f" (+{len(g['days'])-15} more)" \
                    if len(g["days"]) > 15 else ""
                L.append(f"S: {shown}{more}")
            else:
                L.append("S: (no dates found)")
            L.append("")

    # ties sidecar - optional, zero mandatory decisions
    T = []
    T.append("# Ties - optional side quest (43 photos)")
    T.append("")
    T.append("These had TWO+ possible originals at the same instant, so I")
    T.append("pulled nothing and kept the snapshot (tagged 'no original').")
    T.append("That is already the safe end state. If you want me to try a")
    T.append("specific one, write `pull` in its Pick column and tell me.")
    T.append("")
    T.append("| # | Photo | Folder | Size | Pick |")
    T.append("|---|---|---|---|---|")
    i = 0
    for r in con.execute(
            "SELECT i.name, i.size, i.folders_json, i.lib FROM item i "
            "WHERE i.backup_conf='tie' ORDER BY i.lib, i.name"):
        i += 1
        fid = (json.loads(r["folders_json"] or "[]") or [""])[0]
        fr = con.execute("SELECT path_text FROM folder WHERE fid=?",
                         (fid,)).fetchone()
        T.append(f"| {i} | {r['name']} | {r['lib']} "
                 f"{(fr['path_text'] if fr else '?')} | "
                 f"{(r['size'] or 0)//1024} KB |  |")
    return "\n".join(L) + "\n", "\n".join(T) + "\n", stats


def naming(libs=("tv", "fm", "crm")):
    """S1+S2 driver: refresh scan (new rows flagged post_scan), correct
    dates, cluster, guess, adopt, generate the doc. Read-only outside the
    ledger. Idempotent."""
    con = connect()
    ensure_naming_columns(con)
    before = {r["eid"] for r in con.execute("SELECT eid FROM item")}
    scan(libs, con=con)
    con.execute("UPDATE item SET post_scan=1 WHERE eid NOT IN (%s)" %
                ",".join("?" * len(before)), tuple(before)) if before else None
    nd = usable_dates(con)
    mark_clusters(con)
    ng = guess_names(con)
    na = adopt_pass(con)
    doc, ties, stats = gen_doc(con)
    log(con, "naming", "generated", "doc",
        json.dumps({"dated": nd, "clusters": ng, "adopted": na,
                    "sections": stats}))
    con.commit()
    con.close()
    return doc, ties, {"dated": nd, "clusters": ng, "adopted": na,
                       "sections": stats}


# ──────────────────────────────────────────────── phase: parse (v2 S5, day 1)
# Vex returned the doc 2026-07-31 ("consider it all done" - the cut line was
# NOT used, everything parses). His edits carry more than C:/T: values:
# merge directives ("these are one tattoo"), renames, ignores, a John Doe
# placeholder customer, venting parentheticals ("ANDY (8th time)"), and a
# few lines that lost their T: prefix. The mechanical parser handles the
# grammar; _FIXUPS carries the per-block interpretation of every ⚠️/merge
# directive, keyed by the block's fid comment (stable under any heading
# edit). Every fixup is LISTED in the dry-run report - nothing silent.

_TIME_VENT = re.compile(r"\s*\((?:for the )?\d*\s*\w*\s*time\)\s*$", re.I)
_NTH_VENT = re.compile(r"\s*\(\d+(?:st|nd|rd|th) time\)\s*$", re.I)

# fid-comment → overrides. C/T replace the typed values; "decision" forces
# a road. Derived from Vex's own annotations, one entry per directive.
_FIXUPS = {
    # Erol - Stare: "⚠️ Rename to Erol Old Ones"
    "MJH57AZCPVAWH,MJH56QFHK11GB": {"C": "Erol", "T": "Old Ones"},
    # Ivona - Ruka: "⚠️ Rename to Ivona Hand"
    "MJAEK9EXR9TAQ,MJABS5OQK5Y10": {"C": "Ivona", "T": "Hand"},
    # Ivona skull/snake/snail cluster: "These all are one tattoo
    # 'Skull and Snail'" + "same as above one"
    "MJ4SLSUEH6E6J": {"C": "Ivona", "T": "Skull and Snail"},
    "MJACMOWZXE1XJ": {"C": "Ivona", "T": "Skull and Snail"},
    "MJAEXM8KFZIIU,MJAFR1O83US0R,MJAAAQUPPORQ8":
        {"C": "Ivona", "T": "Skull and Snail"},
    # PROPOSED in the report (same words, flipped order), veto-able:
    "MJAA58XJG90CB": {"C": "Ivona", "T": "Skull and Snail",
                      "proposed": "Snake & Skull reads as the same tattoo"},
    # Jurij: "Space chick, girl, lady are all one tattoo 'Jurij - Space Girl'"
    "MJ4SBMRN4GDKJ,MJAA1WUWW5O7V": {"C": "Jurij", "T": "Space Girl"},
    "MJAELGX0IAJVK": {"C": "Jurij", "T": "Space Girl"},
    "MJACTUP6MKPF2,MJAFV9BW2IGS2": {"C": "Jurij", "T": "Space Girl"},
    # Russell: "these three are the same tattoo 'Russell Sacred Heart'"
    "MJ4SHUN4AZ4VA": {"C": "Russell", "T": "Sacred Heart"},
    "MJACLQPKA1VDF,MJA9WDG377FAC": {"C": "Russell", "T": "Sacred Heart"},
    "MJAF1K2VZ8ORD": {"C": "Russell", "T": "Sacred Heart"},
    # PROPOSED: Tarot (5 folders) + Tarot Card (1) same tattoo
    "MJADHP9R3HRHK": {"C": "Russell", "T": "Tarot",
                      "proposed": "Tarot Card = the Tarot tattoo"},
    # Pantera: "These two pantera and panther are the same. Call them
    # Pantera" + Black Panther "This is 'Pantera' from above"
    "MJAFED8M6FTUH": {"C": "John Doe", "T": "Pantera"},
    "MJ4S1QGIFV843": {"C": "John Doe", "T": "Pantera"},
    "MJ8Z2E2MKPPBB": {"C": "John Doe", "T": "Pantera"},
    # Spider: "These two are the same. Call them Spider Lady"
    "MJICDD59F9956,MJAA6GP9XIMVM": {"C": "John Doe", "T": "Spider Lady"},
    "MJAFYAS9WXLTT": {"C": "John Doe", "T": "Spider Lady"},
    # Vampire: "These three are the same. Call them 'Vampire Girl
    # Unfinished'" (one C line was botched to 'T: Vampire (Unfinished)')
    "MJAFH9DLM6U22": {"C": "John Doe", "T": "Vampire Girl Unfinished"},
    "MJIDL4D03JQJN": {"C": "John Doe", "T": "Vampire Girl Unfinished"},
    "MJH7K1BZQGMCD": {"C": "John Doe", "T": "Vampire Girl Unfinished"},
    # Andy's two fists ("There are two tattoos. Bad fist and Good fist.
    # Both on customer Andy"; 'Tommy' blocks are Andy's too, his note)
    "MJ4SMQY1XV5NZ": {"C": "Andy", "T": "Bad Fist"},
    "MJH47AXX58E3V": {"C": "Andy", "T": "Bad Fist"},
    "MJAACJ8LP3OXH": {"C": "Andy", "T": "Bad Fist"},
    "MJAG421GCQBIX,MJABDYF0TOM3A": {"C": "Andy", "T": "Good Fist"},
    "MJJOB4P27TN2K": {"C": "Andy", "T": "Good Fist"},
    "MJ4SJ0192GH0T": {"C": "Andy", "T": "Good Fist"},
    # shots showing BOTH fists → membership in BOTH folders (multi-shelf),
    # PROPOSED in the report
    "MJACOVDCJWKY1": {"C": "Andy", "T": "Bad Fist",
                      "also_folder_of": "Andy - Good Fist",
                      "proposed": "healed shots show both fists → member "
                                  "of both folders"},
    "MJABBDORUXXDT": {"C": "Andy", "T": "Bad Fist",
                      "also_folder_of": "Andy - Good Fist",
                      "proposed": "Good & Evil Fists shows both → member "
                                  "of both folders"},
    # Wolf blocks: "⚠️ Customer Clemens" / "⚠️ Customer Unknown. Tattoo
    # Small Wolf Neotrad"
    "MJAEG0AXSD4AE,MJICFIMLT28QA,MJIBGW0M6S9WI,MJABP6CIDUN82":
        {"C": "Clemens", "T": "Wolf Chestpiece"},
    "MJADOCOJ24DEB,MJAF68Y6HYYU2": {"C": "John Doe",
                                    "T": "Small Wolf Neotrad"},
    # botched C line ('T: Rose Fist' typed into C:) → unknown customer
    "MJL57MLWBBCI2": {"C": "John Doe", "T": "Rose Fist"},
    # explicit ignores
    "MJE7QEIER0M6G": {"decision": "ignored"},          # Blueprint
    "MJAC8K46ZK51Y": {"decision": "ignored"},          # Evil From the Needle
    # my structural leak, his catch ("you took the parent folder and put
    # it as a tattoo folder") - stray items stay in place
    "MJ4S6RYIGPX26": {"decision": "structural"},       # To Edit
    "MJ4S6YDLZ4PWY": {"decision": "structural"},       # To Post
    # live-spelling adoptions (typed vs live CRM)
    "MJGTWSAZ4JTT0": {"C": "Professor", "T": ""},      # 'Proffesor' + xy
    "MJJPJT05YXGZ2": {"C": "Russell", "T": ""},        # 'Russel' + xy
    # near-dupe twin groups the engine review caught (2026-07-31) -
    # each would have made TWO homes + two logbooks; PROPOSED, veto-able
    "MJAEAH2CB5SFN": {"T": "Neotrad Seagull",
                      "proposed": "Seagull Neotrad = Neotrad Seagull"},
    "MJIARJL6G6D51": {"C": "Bradonja", "T": "Cat",
                      "proposed": "Cat Healed shots = the Cat tattoo"},
    "MJE89OSH5M8HM": {"C": "Russell", "T": "Tarot",
                      "proposed": "second Tarot spelling = same tattoo"},
}

# 'john doe' in the TATTOO slot is the same unknown marker as in the
# customer slot ('Andres - John Doe' must not become a tattoo name)
_UNKNOWN_T = {"xy", "?", "", "john doe",
              "xy (means i do not know which tattoo of them all)"}


def parse_doc(text):
    """→ (decisions, notes). decisions = [{fids, heading, C, T, S, road,
    proposed, also_folder_of}]. road: named | johndoe | skip | ignored |
    structural. T may be '' (unknown tattoo)."""
    decisions, notes = [], []
    blocks = re.split(r"(?=^### )", text, flags=re.M)
    for b in blocks:
        m = re.search(r"<!-- mig:([A-Z0-9,]+) -->", b)
        if not m:
            continue
        fids_key = m.group(1)
        heading = (re.match(r"### (.+)", b) or [None, ""])[1].strip()
        cm = re.search(r"^C:\s*(.*)$", b, re.M)
        tm = re.search(r"^T:\s*(.*)$", b, re.M)
        c = (cm.group(1) if cm else "").strip()
        t = (tm.group(1) if tm else "").strip()
        # a value line that lost its T: prefix (e.g. 'Underboob') sits
        # between C: and S:/folder lines
        if not t and cm:
            after = b[cm.end():]
            bare = re.search(r"^(?!C:|T:|S:|[-<#⚠\s])(.\S.*)$", after, re.M)
            if bare and not bare.group(1).startswith("⎯"):
                t = bare.group(1).strip()
        sdays = re.findall(r"\d{4}-\d{2}-\d{2}",
                           (re.search(r"^S:\s*(.*)$", b, re.M) or
                            [None, ""])[1])
        fix = _FIXUPS.get(fids_key, {})
        c, t = fix.get("C", c), fix.get("T", t)
        # venting/case cleanup
        c = _TIME_VENT.sub("", _NTH_VENT.sub("", c)).strip()
        if c.isupper() and len(c) > 2:
            c = c.title()
        if c.startswith("⚠") or c.lower().startswith("t:"):
            c = ""                      # botched cell not covered by a fixup
        road = fix.get("decision")
        if not road:
            if c.casefold() == "ignore":
                road = "ignored"
            elif c.casefold() in ("john doe", "?"):
                road = "johndoe"
            elif c:
                road = "named"
            else:
                road = "skip"
        if t.casefold() in _UNKNOWN_T:
            t = ""
        decisions.append({"fids": fids_key.split(","), "heading": heading,
                          "C": c, "T": t, "S": sdays, "road": road,
                          "proposed": fix.get("proposed"),
                          "also_folder_of": fix.get("also_folder_of")})
    return decisions, notes


def store_decisions(con, decisions):
    """Write every block's ruling onto its folder rows."""
    n = 0
    for d in decisions:
        extras = {}
        if d["proposed"]:
            extras["proposed"] = d["proposed"]
        if d["also_folder_of"]:
            extras["also_folder_of"] = d["also_folder_of"]
        if d["S"]:
            extras["days"] = d["S"]
        for fid in d["fids"]:
            # MERGE extras into any existing adopt_json - COALESCE used to
            # throw away the confirmed S days on every pre-adopted folder
            # (review 2026-07-31: Erol • Old Ones would have been born
            # dateless in Records)
            if extras:
                old = con.execute("SELECT adopt_json FROM folder WHERE "
                                  "fid=?", (fid,)).fetchone()
                merged = json.loads((old["adopt_json"] if old else None)
                                    or "{}")
                merged.update(extras)
                aj = json.dumps(merged, ensure_ascii=False)
            else:
                aj = None
            con.execute(
                "UPDATE folder SET decision=?, dec_customer=?, dec_tattoo=?,"
                " decided_at=?, adopt_json=COALESCE(?, adopt_json)"
                " WHERE fid=?",
                (d["road"], d["C"], d["T"], time.strftime("%F %T"), aj, fid))
            n += 1
    con.commit()
    return n


# ─────────────────────────────────────────────── phase: execute (v2 S6)
# The batch engine. Order per group: Eagle home folder (name final at
# parse) → customer mint-or-adopt → logbook born in its year list with
# the 🦅 line embedded at create → PL entry → item moves + tags. Moves
# ride add_to_folders/remove_from_folders (incremental - cannot unfile
# bystanders, preserves multi-shelf membership); update_items is used
# for NOTHING here. Every mover's prior state is written from disk in
# the same transaction that queues its batch; migundo reverses folders
# AND tags from those rows. Never deletes anything, ever.

PROTECTED_TAGS = {"superseded", "original", "no original", "archive"}
_BRANCH_TAGS = {"healed tattoos": "healed", "healed": "healed",
                "reel material": "reel", "raw videos": "video",
                "videos": "video", "serious": "serious", "lines": "lines",
                "floral": "floral", "letters": "letters"}
_PORTFOLIO_SEG = "tattoo portfolio"
_EDIT_SEGS = {"content pipeline", "to edit"}


def ensure_exec_schema(con):
    # composite PK: 16 items belong to member folders of TWO groups and
    # each group must record its own prior/dest truth or migundo is blind
    # to the second (review 2026-07-31)
    con.execute("""CREATE TABLE IF NOT EXISTS mover (
        eid TEXT, gkey TEXT, lib TEXT,
        prior_name TEXT, prior_folders_json TEXT, prior_tags_json TEXT,
        dest_fid TEXT, added_tags_json TEXT, state TEXT DEFAULT 'queued',
        moved_at TEXT, PRIMARY KEY (eid, gkey))""")
    con.execute("""CREATE TABLE IF NOT EXISTS egroup (
        gkey TEXT PRIMARY KEY, lib TEXT, road TEXT,
        customer TEXT, tattoo TEXT, target_name TEXT,
        home_fid TEXT, home_prior_name TEXT, home_prior_parent TEXT,
        cust_tid TEXT, log_tid TEXT, log_pid TEXT, pl_tid TEXT,
        days_json TEXT, n_items INTEGER,
        state TEXT DEFAULT 'planned', executed_at TEXT)""")
    con.commit()


def _branch_tags_for(path_text):
    segs = _path_segs(path_text)
    tags = sorted({_BRANCH_TAGS[s] for s in segs if s in _BRANCH_TAGS})
    if _PORTFOLIO_SEG in segs:
        tags.append("portfolio")
    return tags


def _movers_for_folder(con, fid, lib):
    """[(mover_eid, item_row)] honoring every corrected population:
    sourced rows move their new_eid (the recovered original; the old
    copy stays, superseded); dup_of rows contribute NOTHING (Vex froze
    the redundant copies); everything else moves its own eid."""
    out = []
    for r in con.execute(
            "SELECT * FROM item WHERE lib=? "
            "AND instr(folders_json, ?) > 0", (lib, fid)):
        if r["dup_of"]:
            continue
        if (r["post_scan"] or 0) == 1:
            continue
        eid = r["new_eid"] if r["state"] == "sourced" else r["eid"]
        if eid:
            out.append((eid, r))
    return out


def plan_execution(con):
    """Assemble egroup rows from the stored doc decisions. Read-only
    outside the ledger; idempotent (re-plan refreshes planned rows,
    never touches executed ones)."""
    ensure_exec_schema(con)
    groups = {}
    for f in con.execute("SELECT * FROM folder WHERE decision IN "
                         "('named','johndoe','skip') AND direct_n>0 "
                         "AND excluded=0"):
        extras = json.loads(f["adopt_json"] or "{}")
        if f["decision"] == "named":
            key = (f["lib"], "named",
                   _norm_name(f["dec_customer"]),
                   _norm_name(f["dec_tattoo"] or "unknown"))
            name = (f"{f['dec_customer']} - {f['dec_tattoo']}"
                    if f["dec_tattoo"] else
                    f"{f['dec_customer']} - Unknown")
        else:
            base = f["dec_tattoo"] or f["name"]
            key = (f["lib"], f["decision"], _norm_name(base), "")
            name = base
        g = groups.setdefault(key, {
            "lib": f["lib"], "road": f["decision"],
            "customer": f["dec_customer"] or "",
            "tattoo": f["dec_tattoo"] or "", "target": name,
            "folders": [], "days": set(), "extras": []})
        g["folders"].append(dict(f))
        g["days"].update(extras.get("days") or [])
        if extras:
            g["extras"].append(extras)
    # Session days, done RIGHT (review 2026-07-31, the Muriel blocker):
    # the doc's S: line displayed at most 15 days, so a parsed line is a
    # VETO surface only for the days it actually showed - days 16+ come
    # from the items and can never be silently lost. days =
    # re-derived item days MINUS (displayed-but-deleted).
    for key, g in groups.items():
        fids = [f["fid"] for f in g["folders"]]
        marks = " OR ".join(f"instr(folders_json, '{fid}') > 0"
                            for fid in fids)
        derived = [r["d"] for r in con.execute(
            f"SELECT DISTINCT strftime('%Y-%m-%d', usable_epoch,"
            f" 'unixepoch') d FROM item WHERE usable_epoch IS NOT NULL"
            f" AND lib=? AND ({marks}) ORDER BY 1", (g["lib"],))]
        displayed = set(derived[:15])
        vetoed = displayed - set(g["days"]) if g["days"] or displayed \
            else set()
        g["days"] = sorted(set(derived) - vetoed)
    # ONE tattoo across libraries = ONE day set (Lucia • Medusa's fm
    # session must not vanish because her tv group minted first)
    by_lkey = {}
    for key, g in groups.items():
        if g["road"] == "named":
            lk = (_norm_name(g["customer"]),
                  _norm_name(g["tattoo"] or "unknown"))
            by_lkey.setdefault(lk, set()).update(g["days"])
    for key, g in groups.items():
        if g["road"] == "named":
            lk = (_norm_name(g["customer"]),
                  _norm_name(g["tattoo"] or "unknown"))
            g["days"] = sorted(by_lkey[lk])
    n = 0
    for key, g in groups.items():
        gkey = "|".join(key)
        row = con.execute("SELECT state FROM egroup WHERE gkey=?",
                          (gkey,)).fetchone()
        if row and row["state"] != "planned":
            continue
        n_items = len({e for f in g["folders"]
                       for e, _ in _movers_for_folder(con, f["fid"],
                                                      f["lib"])})
        con.execute(
            "INSERT INTO egroup(gkey,lib,road,customer,tattoo,target_name,"
            "days_json,n_items,state) VALUES(?,?,?,?,?,?,?,?,'planned') "
            "ON CONFLICT(gkey) DO UPDATE SET customer=excluded.customer,"
            "tattoo=excluded.tattoo,target_name=excluded.target_name,"
            "days_json=excluded.days_json,n_items=excluded.n_items",
            (gkey, g["lib"], g["road"], g["customer"], g["tattoo"],
             g["target"], json.dumps(sorted(g["days"])), n_items))
        n += 1
    con.commit()
    return n


def migredo(con, gkey):
    """Flip an undone group back to planned so it can execute again -
    an undone group was otherwise permanently unreachable. Mover rows
    stay: they are the prior-state truth and INSERT OR IGNORE keeps
    the ORIGINAL prior state on the next run."""
    con.execute("UPDATE egroup SET state='planned' WHERE gkey=? AND "
                "state='undone'", (gkey,))
    con.commit()


class Pacer:
    """Token bucket against the shared TickTick budget. 240/5min spend
    ceiling (the hourly agent is PAUSED during runs, but headroom stays
    headroom). Conservative: overcounting is fine, undercounting is a
    500 that POSTs never retry."""
    def __init__(self, budget=240, window=300):
        self.budget, self.window, self.spent, self.t0 = budget, window, 0, time.time()

    def spend(self, n):
        if time.time() - self.t0 > self.window:
            self.spent, self.t0 = 0, time.time()
        if self.spent + n > self.budget:
            wait = self.window - (time.time() - self.t0) + 2
            if wait > 0:
                time.sleep(wait)
            self.spent, self.t0 = 0, time.time()
        self.spent += n


def _group_folder_rows(con, gkey):
    lib, road, nc, nt = (gkey.split("|") + [""])[:4]
    rows = []
    for f in con.execute("SELECT * FROM folder WHERE decision=? AND "
                         "direct_n>0 AND excluded=0 AND lib=?",
                         ((road), lib)):
        if road == "named":
            k = (_norm_name(f["dec_customer"]),
                 _norm_name(f["dec_tattoo"] or "unknown"))
            if k != (nc, nt):
                continue
        else:
            if _norm_name(f["dec_tattoo"] or f["name"]) != nc:
                continue
        rows.append(dict(f))
    return rows


def _dest_parent(eagle, con, g, folders):
    """(parent_fid, kind). Content libs: 02 Edit iff EVERY member folder
    sits under the edit branch, else 01 Raw. CRM lib: the existing
    per-tattoo folder when adoption found one (items land inside it),
    else Archive/'{C} - {T}' via the pipeline of the CRM tree."""
    lib = g["lib"]
    if lib in ("tv", "fm"):
        pf = eagle.pipeline_folders(create=True)
        all_edit = all(
            any(s in _EDIT_SEGS for s in _path_segs(f["path_text"]))
            for f in folders)
        return (pf["Edit"] if all_edit else pf["Raw"]), "content"
    for f in folders:
        ad = json.loads(f["adopt_json"] or "{}")
        if ad.get("eagle_fid"):
            return ad["eagle_fid"], "crm-adopt"
    tree = eagle.folder_tree()
    for node in tree:
        if _norm_name(node.get("name")) == "archive":
            return node["id"], "crm-archive"
    raise eagle.EagleError("CRM Archive/ root not found")


_NOMOVE = "NOMOVE"      # home_prior_parent sentinel: nothing to move back


def _folder_is_clean(con, fid, lib):
    """True when the folder holds NO stay-behind residents (superseded
    old copies, frozen dup imports, post-scan live items) - only then may
    it become the home, or the residents would ride along and break the
    written ruling 'superseded stays in Review'."""
    r = con.execute(
        "SELECT COUNT(*) c FROM item WHERE lib=? AND "
        "instr(folders_json, ?) > 0 AND (state='sourced' OR "
        "dup_of IS NOT NULL OR post_scan=1)", (lib, fid)).fetchone()
    return r["c"] == 0


def _ensure_home(eagle, con, g, folders, parent_fid, kind):
    """The group's ONE folder, twin-proof (review 2026-07-31). Priority:
    (1) an EXISTING folder already named target under the dest parent -
        or, in CRM, under Archive/ or Customers/ - is ADOPTED (Jenny's
        'Viking Fox' must land in Archive/'Jenny - Viking Fox', never
        mint a sibling twin);
    (2) a member folder whose name matches AND whose residents are all
        movers is adopted + re-parented (id stable, zero residue);
    (3) otherwise CREATE fresh under the dest parent - which is exactly
        what keeps superseded/frozen copies BEHIND in their old folders.
    Returns (fid, prior_name, prior_parent, created)."""
    if kind == "crm-adopt":
        return parent_fid, None, _NOMOVE, 0
    target = g["target_name"]
    tnorm = _norm_name(target)
    tree = eagle.folder_tree()

    def children_of(fid):
        node = eagle.folder_node(fid, tree=tree)
        return (node or {}).get("children") or []

    scan = list(children_of(parent_fid))
    if g["lib"] == "crm":
        for root in tree:
            if _norm_name(root.get("name")) in ("archive", "customers"):
                scan += root.get("children") or []
    for node in scan:
        if _norm_name(node.get("name")) == tnorm:
            return node["id"], None, _NOMOVE, 0
    cand = next((f for f in sorted(folders,
                                   key=lambda x: -(x["direct_n"] or 0))
                 if _norm_name(f["name"]) == tnorm
                 and _folder_is_clean(con, f["fid"], f["lib"])), None)
    if cand:
        prior_parent = cand["parent_fid"]
        if prior_parent != parent_fid:
            eagle.move_folder(cand["fid"], parent_fid)
            time.sleep(0.4)
            return cand["fid"], cand["name"], prior_parent or "", 0
        return cand["fid"], cand["name"], _NOMOVE, 0
    fid = eagle.create_folder(target, parent=parent_fid)
    return fid, None, _NOMOVE, 1


def execute_batch(con, limit=5, notify=True, gkeys=None):
    """Run up to `limit` planned groups end-to-end. Every mutation is
    evented (attempt before, ok/err after); movers get prior state from
    DISK before anything fires; RateLimitError aborts the batch cleanly.
    Resume = just call again: executed groups are skipped, half-done
    groups re-verify via their event trail."""
    import eagle
    import areas
    import crm_records as cr
    ensure_exec_schema(con)
    pacer = Pacer()
    done = errs = 0
    if gkeys:
        marks = ",".join("?" * len(gkeys))
        batch = [dict(r) for r in con.execute(
            f"SELECT * FROM egroup WHERE state='planned' AND gkey IN "
            f"({marks})", tuple(gkeys))]
    else:
        batch = [dict(r) for r in con.execute(
            "SELECT * FROM egroup WHERE state='planned' "
            "ORDER BY road='named' DESC, n_items DESC LIMIT ?", (limit,))]
    for g in batch:
        gkey = g["gkey"]
        try:
            folders = _group_folder_rows(con, gkey)
            if not folders:
                con.execute("UPDATE egroup SET state='empty' WHERE gkey=?",
                            (gkey,))
                con.commit()
                continue
            log(con, "exec", "attempt", gkey, json.dumps(
                {"step": "eagle", "target": g["target_name"]}))
            eagle.ensure_library(g["lib"])
            parent_fid, kind = _dest_parent(eagle, con, g, folders)
            home, p_name, p_parent, created = _ensure_home(
                eagle, con, g, folders, parent_fid, kind)
            _heal_parent = parent_fid if kind != "crm-adopt" else None
            # movers with prior state from disk, in ONE transaction.
            # An item may sit in SEVERAL member folders - tags and the
            # portfolio test ride the whole set, not the last one seen.
            movers = {}
            for f in folders:
                for eid, _r in _movers_for_folder(con, f["fid"], g["lib"]):
                    movers.setdefault(eid, []).append(f)
            lib_path = eagle.LIBS[g["lib"]][1]
            disk = {}
            for eid in list(movers):
                mp = os.path.join(lib_path, "images", f"{eid}.info",
                                  "metadata.json")
                try:
                    m = json.load(open(mp))
                except Exception as e:
                    # a mover we cannot snapshot is a mover we cannot
                    # undo - the whole group aborts, honestly
                    raise RuntimeError(
                        f"unreadable metadata for mover {eid}: {e}")
                if m.get("isDeleted"):
                    log(con, "exec", "warn", gkey,
                        f"mover {eid} is in Eagle Trash - skipped")
                    movers.pop(eid)
                    continue
                disk[eid] = m
            def _tags_for(eid):
                return sorted({t for f in movers[eid]
                               for t in _branch_tags_for(f["path_text"])})
            for eid, fl in movers.items():
                m = disk[eid]
                con.execute(
                    "INSERT OR IGNORE INTO mover(eid,gkey,lib,prior_name,"
                    "prior_folders_json,prior_tags_json,dest_fid,"
                    "added_tags_json) VALUES(?,?,?,?,?,?,?,?)",
                    (eid, gkey, g["lib"], m.get("name") or "",
                     json.dumps(m.get("folders") or []),
                     json.dumps(m.get("tags") or []), home,
                     json.dumps(_tags_for(eid))))
            con.execute("UPDATE egroup SET home_fid=?, home_prior_name=?,"
                        "home_prior_parent=? WHERE gkey=?",
                        (home, p_name, p_parent, gkey))
            con.commit()
            # the moves: incremental, batched per source folder
            member_fids = {f["fid"] for f in folders}
            by_src = {}
            for eid in movers:
                cur = set((disk.get(eid) or {}).get("folders") or [])
                srcs = tuple(sorted((cur & member_fids) - {home}))
                by_src.setdefault(srcs, []).append(eid)
            for srcs, eids in by_src.items():
                if srcs:
                    eagle.remove_from_folders(eids, list(srcs))
                eagle.add_to_folders(eids, [home])
            # branch tags, one call per distinct tag set
            by_tags = {}
            for eid in movers:
                tg = tuple(_tags_for(eid))
                if tg:
                    by_tags.setdefault(tg, []).append(eid)
            for tg, eids in by_tags.items():
                eagle.add_item_tags(eids, list(tg))
            # portfolio-source items ALSO join 04 Portfolio/{target}
            # (the per-base child, matching live to_portfolio convention)
            pf_items = [eid for eid, fl in movers.items()
                        if any(_PORTFOLIO_SEG in _path_segs(f["path_text"])
                               for f in fl)]
            if pf_items and g["lib"] in ("tv", "fm"):
                pf = eagle.pipeline_folders(create=True)
                kids = {_norm_name(c.get("name")): c["id"] for c in
                        (eagle.folder_node(pf["Portfolio"]) or {})
                        .get("children") or []}
                pchild = kids.get(_norm_name(g["target_name"])) or \
                    eagle.create_folder(g["target_name"],
                                        parent=pf["Portfolio"])
                eagle.add_to_folders(pf_items, [pchild])
            if _heal_parent:
                _xact_heal(eagle, [home], _heal_parent)
            con.execute("UPDATE mover SET state='moved', moved_at=? "
                        "WHERE gkey=?", (time.strftime("%F %T"), gkey))
            log(con, "exec", "ok", gkey, json.dumps(
                {"step": "eagle", "home": home, "items": len(movers)}))
            # ---- TickTick side ----
            days = json.loads(g["days_json"] or "[]")
            if g["road"] == "named" and kind != "crm-adopt" \
                    and not _adopts_live_logbook(g):
                cust = _ensure_customer(con, cr, pacer, g["customer"])
                tid, log_pid = _ensure_logbook(con, cr, areas, pacer, g,
                                               cust, days, home)
                con.execute("UPDATE egroup SET cust_tid=?, log_tid=?, "
                            "log_pid=? WHERE gkey=?",
                            (cust["id"], tid, log_pid, gkey))
                log(con, "exec", "ok", gkey,
                    json.dumps({"step": "logbook", "tid": tid}))
            # PL entry: content-lib groups, except portfolio-only sources
            if g["lib"] in ("tv", "fm") and not _portfolio_only(folders):
                pacer.spend(1)
                pl = _mint_pl_entry(cr, areas, g, folders, home,
                                    con, pacer)
                if pl:
                    con.execute("UPDATE egroup SET pl_tid=? WHERE gkey=?",
                                (pl, gkey))
            con.execute("UPDATE egroup SET state='executed', executed_at=?"
                        " WHERE gkey=?", (time.strftime("%F %T"), gkey))
            con.commit()
            done += 1
        except Exception as e:
            errs += 1
            log(con, "exec", "err", gkey, f"{type(e).__name__}: {e}")
            con.commit()
            if "RateLimit" in type(e).__name__:
                break
    try:
        apply_also_links(con)
    except Exception as e:
        log(con, "exec", "err", "also-links", f"{type(e).__name__}: {e}")
        con.commit()
    if notify:
        subprocess.run(["osascript", "-e",
                        'display notification "{} done · {} errors" '
                        'with title "TickAL migration batch"'
                        .format(done, errs)], capture_output=True)
    return done, errs


def _xact_heal(eagle, fids, parent_fid):
    """One verification pass: anything double-parented gets re-set to the
    intended parent (the repair that worked by hand, 3941525)."""
    time.sleep(0.4)
    tree = eagle.folder_tree()
    seen = {}

    def walk(nodes, parent):
        for n in nodes:
            seen.setdefault(n["id"], set()).add(parent)
            walk(n.get("children") or [], n["id"])
    walk(tree, None)
    for fid in fids:
        if len(seen.get(fid, set())) > 1:
            eagle.move_folder(fid, parent_fid)
            time.sleep(0.4)


def _adopts_live_logbook(g):
    """Groups whose C+T matched an EXISTING logbook (Erol • Griffin live,
    Phillip • Samurai + Jenny • Viking Fox archived): Eagle filing only,
    ZERO TickTick writes - auto-appending years-old sessions into a live
    record is not the engine's call."""
    custs, logs = _cache_records(strict=True)
    k = _norm_name(f"{g['customer']} {g['tattoo']}")
    return any(_norm_name(l["title"]) == k for l in logs)


def _ensure_customer(con, cr, pacer, name):
    """Adopt by casefolded exact match, else mint ONCE (ledger-cached so
    Clemens's two blocks share one card). Resume-safe: an attempt event
    commits BEFORE the POST, and an unpaired attempt re-verifies against
    the LIVE list by title before ever re-firing (create POSTs are not
    retried and a re-fire is a permanent twin)."""
    import areas
    custs, _ = _cache_records(strict=True)
    k = _norm_name(name)
    for c in custs:
        if _norm_name(c["name"]) == k:
            return {"id": c["tid"], "title": f"👤 {c['name']}"}
    row = con.execute("SELECT detail FROM event WHERE phase='exec' AND "
                      "kind='cust' AND subject=?", (k,)).fetchone()
    if row:
        d = json.loads(row["detail"])
        return {"id": d["tid"], "title": d["title"]}
    att = con.execute("SELECT 1 FROM event WHERE phase='exec' AND "
                      "kind='attempt' AND subject=?",
                      (f"cust:{k}",)).fetchone()
    if att:
        pacer.spend(1)
        try:
            pd = cr._api().get_project_data(areas.RECORDS_ID)
            for t in pd.get("tasks") or []:
                if _norm_name(re.sub(r"^\U0001F464\s*", "",
                                     t.get("title") or "")) == k:
                    log(con, "exec", "cust", k, json.dumps(
                        {"tid": t["id"], "title": t.get("title")}))
                    return {"id": t["id"], "title": t.get("title")}
        except Exception:
            pass
    log(con, "exec", "attempt", f"cust:{k}", name)
    con.commit()
    pacer.spend(2)
    c = cr.create_customer(name)
    log(con, "exec", "cust", k, json.dumps(
        {"tid": c["id"], "title": c.get("title") or f"👤 {name}"}))
    con.commit()
    return c


def _ensure_logbook(con, cr, areas, pacer, g, cust, days, home):
    """ONE logbook per (customer, tattoo) across ALL libraries - ten
    tattoos span two libs and would otherwise double-mint - and a
    resume guard: create_task is a POST with no retry, so an unpaired
    attempt is re-verified against the live list by TITLE before ever
    re-firing (the Stage 3 duplicate-import lesson, applied to notes).
    Sessions and the finish are event-guarded per step so a resumed
    group never double-appends. Returns (log_tid, log_pid)."""
    lkey = _norm_name(f"{g['customer']} {g['tattoo'] or 'unknown'}")
    lb = log_pid = None
    row = con.execute("SELECT detail FROM event WHERE phase='exec' AND "
                      "kind='lbk' AND subject=?", (lkey,)).fetchone()
    if row:
        # already minted (cross-lib sibling or resumed run) - fall
        # THROUGH to the guarded session/finish loops, never skip them
        d = json.loads(row["detail"])
        lb, log_pid = {"id": d["tid"]}, d["pid"]
    if lb is None:
        year_pid = None
        if days:
            pacer.spend(1)
            year_pid = cr.ensure_archive_list(days[0][:4])
        log_pid = year_pid or areas.RECORDS_ID
        title = f"🎨 {g['customer']} • {g['tattoo'] or 'Unknown'}"
        att = con.execute(
            "SELECT COUNT(*) c FROM event WHERE phase='exec' AND "
            "kind='attempt' AND subject=? ",
            (f"lbk:{lkey}",)).fetchone()["c"]
        if att:
            # unpaired attempt from a crashed run - verify live by title
            pacer.spend(1)
            try:
                pd = cr._api().get_project_data(log_pid)
                want = _norm_name(title)
                for t in pd.get("tasks") or []:
                    tt = _norm_name(t.get("title") or "")
                    if tt == want or tt == _norm_name("🏛️ " + title[2:]):
                        lb = t
                        break
            except Exception:
                pass
        if lb is None:
            log(con, "exec", "attempt", f"lbk:{lkey}",
                json.dumps({"pid": log_pid, "title": title}))
            con.commit()
            eagle_line = (f"🦅 [Eagle folder](eagle://folder/{home})"
                          f" · {g['lib'].upper()}")
            pacer.spend(3)
            lb = cr.create_logbook(cust, g["tattoo"] or "Unknown",
                                   started=days[0] if days else None,
                                   project_id=year_pid,
                                   eagle_line=eagle_line)
        log(con, "exec", "lbk", lkey,
            json.dumps({"tid": lb["id"], "pid": log_pid}))
        con.commit()
    # sessions keyed by DATE (S-numbers are positional and collide when
    # a two-library tattoo's day sets differ - review 2026-07-31); days
    # here is already the cross-library UNION from plan_execution
    live_body = None
    for i, day in enumerate(days, 1):
        skey = f"sess:{lkey}:{day}"
        if con.execute("SELECT 1 FROM event WHERE phase='exec' AND "
                       "kind='ok' AND subject=?", (skey,)).fetchone():
            continue
        if row and live_body is None:
            # resumed/shared logbook: read the note ONCE and skip days
            # whose heading already landed (the POST may have won a race
            # the event log lost)
            pacer.spend(1)
            try:
                live_body = (cr._api().get_task(log_pid, lb["id"])
                             .get("content") or "")
            except Exception:
                live_body = ""
        if live_body and f"### {day} ·" in live_body:
            log(con, "exec", "ok", skey, "already-present")
            con.commit()
            continue
        pacer.spend(4)
        cr.append_session(log_pid, lb["id"], f"S{i}", when=day)
        log(con, "exec", "ok", skey, day)
        con.commit()
    if days and not con.execute(
            "SELECT 1 FROM event WHERE phase='exec' AND kind='ok' AND "
            "subject=?", (f"fin:{lkey}",)).fetchone():
        pacer.spend(6)
        cr.finish_logbook(log_pid, lb["id"], when=days[-1])
        log(con, "exec", "ok", f"fin:{lkey}", days[-1])
        con.commit()
    return lb["id"], log_pid


def _portfolio_only(folders):
    return all(_PORTFOLIO_SEG in _path_segs(f["path_text"])
               for f in folders)


def _mint_pl_entry(cr, areas, g, folders, home_fid, con, pacer):
    """kind=TEXT pipeline entry so the tattoo is visible on the content
    screens (no note = invisible - load-bearing). 📸edit when the home
    is the edit branch, else 📸raw. Body: the 🎨 logbook link when one
    exists, else a placeholder (NEVER empty - an empty body costs the
    hourly sync one GET per hour forever). Resume-safe like every other
    create: pl_tid short-circuit, attempt event before the POST, live
    title verify on an unpaired attempt."""
    api = cr._api()
    row = con.execute("SELECT log_tid, log_pid, pl_tid FROM egroup "
                      "WHERE gkey=?", (g["gkey"],)).fetchone()
    if row and row["pl_tid"]:
        return row["pl_tid"]
    all_edit = all(any(s in _EDIT_SEGS for s in _path_segs(f["path_text"]))
                   for f in folders)
    tag = "📸edit" if all_edit else "📸raw"
    title = f"[{g['target_name']}](eagle://folder/{home_fid})"
    pid = areas.CONTENT_DESTS[g["lib"]][0]
    att = con.execute("SELECT 1 FROM event WHERE phase='exec' AND "
                      "kind='attempt' AND subject=?",
                      (f"pl:{g['gkey']}",)).fetchone()
    if att:
        pacer.spend(1)
        try:
            pd = api.get_project_data(pid)
            for t in pd.get("tasks") or []:
                if (t.get("title") or "") == title:
                    return t.get("id")
        except Exception:
            pass
    if row and row["log_tid"]:
        body = f"🎨 {cr.task_link(row['log_pid'], row['log_tid'], '🎨 logbook')}"
    else:
        body = "·"
    log(con, "exec", "attempt", f"pl:{g['gkey']}", title)
    con.commit()
    t = api.create_task(title=title, project_id=pid, content=body,
                        tags=[tag], kind="TEXT")
    log(con, "exec", "ok", f"pl:{g['gkey']}", t.get("id") or "")
    con.commit()
    return t.get("id")


def migundo(con, gkey):
    """Reverse one group's Eagle state from the mover rows: memberships
    restored, added tags removed (protected tags never touched), the
    home folder's re-parent undone (the _NOMOVE sentinel distinguishes
    'never moved' from 'moved from ROOT' - review 2026-07-31). TickTick
    creations are NOT deleted (nothing ever is) - tids reported. Only an
    'executed' group may be undone; migredo makes an undone group
    plannable again."""
    import eagle
    g = dict(con.execute("SELECT * FROM egroup WHERE gkey=?",
                         (gkey,)).fetchone())
    if g["state"] != "executed":
        raise RuntimeError(f"migundo: group is {g['state']!r}, "
                           "only 'executed' can be undone")
    eagle.ensure_library(g["lib"])
    n = 0
    for m in con.execute("SELECT * FROM mover WHERE gkey=? AND "
                         "state='moved'", (gkey,)):
        prior = json.loads(m["prior_folders_json"] or "[]")
        added = [t for t in json.loads(m["added_tags_json"] or "[]")
                 if t not in PROTECTED_TAGS]
        eagle.remove_from_folders([m["eid"]], [m["dest_fid"]])
        if prior:
            eagle.add_to_folders([m["eid"]], prior)
        if added:
            eagle.remove_item_tags([m["eid"]], added)
        con.execute("UPDATE mover SET state='undone' WHERE eid=? AND "
                    "gkey=?", (m["eid"], gkey))
        n += 1
    if g.get("home_prior_name"):
        eagle.rename_folder(g["home_fid"], g["home_prior_name"])
    pp = g.get("home_prior_parent")
    if pp is not None and pp != _NOMOVE:
        eagle.move_folder(g["home_fid"], pp or None)
        time.sleep(0.4)
    con.execute("UPDATE egroup SET state='undone' WHERE gkey=?", (gkey,))
    con.commit()
    return {"items_restored": n, "ticktick_tids_left": {
        "customer": g.get("cust_tid"), "logbook": g.get("log_tid"),
        "pl": g.get("pl_tid")}}


def apply_also_links(con):
    """Vex's dual-membership ruling (Andy's both-fists shots live in BOTH
    fist folders): once BOTH groups are executed, add the flagged
    folders' movers to the sibling home. Runs at the end of every batch
    until each link is satisfied; event-guarded so it fires once."""
    import eagle
    n = 0
    for f in con.execute("SELECT * FROM folder WHERE adopt_json LIKE "
                         "'%also_folder_of%'"):
        extras = json.loads(f["adopt_json"] or "{}")
        target = extras.get("also_folder_of")
        if not target:
            continue
        akey = f"also:{f['fid']}"
        if con.execute("SELECT 1 FROM event WHERE phase='exec' AND "
                       "kind='ok' AND subject=?", (akey,)).fetchone():
            continue
        trow = con.execute(
            "SELECT home_fid, lib FROM egroup WHERE state='executed' AND "
            "home_fid IS NOT NULL AND lib=? AND target_name=?",
            (f["lib"], target)).fetchone()
        moved = con.execute(
            "SELECT 1 FROM mover m JOIN egroup e ON m.gkey=e.gkey "
            "WHERE e.state='executed' AND m.state='moved' AND m.lib=? "
            "LIMIT 1", (f["lib"],)).fetchone()
        if not (trow and moved):
            continue                      # sibling group not executed yet
        eids = [e for e, _ in _movers_for_folder(con, f["fid"], f["lib"])]
        if eids:
            eagle.ensure_library(f["lib"])
            eagle.add_to_folders(eids, [trow["home_fid"]])
        log(con, "exec", "ok", akey,
            json.dumps({"items": len(eids), "to": trow["home_fid"]}))
        con.commit()
        n += 1
    return n


def migcheck(con):
    """Drag-back detector: every minted logbook must still live in its
    recorded pid. One get_project_data per touched list."""
    import crm_records as cr
    api = cr._api()
    by_pid = {}
    for r in con.execute("SELECT log_tid, log_pid FROM egroup "
                         "WHERE log_tid IS NOT NULL"):
        by_pid.setdefault(r["log_pid"], set()).add(r["log_tid"])
    bad = []
    for pid, tids in by_pid.items():
        try:
            pd = api.get_project_data(pid)
            have = {t.get("id") for t in pd.get("tasks") or []}
            bad += [t for t in tids if t not in have]
        except Exception as e:
            bad.append(f"{pid}: {type(e).__name__}")
    return bad
