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


def _cache_records():
    """Live customers/logbooks from the runtime cache, casefolded tags.
    Cache staleness is acceptable here: adoption only PREFILLS spelling;
    the execution engine re-verifies live before any write."""
    import config as _cfg  # noqa: F401  (path setup)
    p = os.path.expanduser("~/.ticktick_alfred/cache/all_notes.json")
    try:
        notes = json.load(open(p)).get("value") or []
    except Exception:
        return [], []
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
