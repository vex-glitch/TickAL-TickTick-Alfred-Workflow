"""Photos.app bridge - AppleScript channel (probe-verified 2026-07-25).

Contracts that shaped this module:
- AS object refs DIE with the osascript process → every operation is a
  ONE-SHOT script; later runs re-address items by `media item id "X"`
  (direct reference, no whose-scan).
- Selection survives Photos being in the background - reading it does
  not need Photos frontmost.
- THE FAST ROAD (2026-09-08, Vex: 'selection takes FOREVER to move to
  Eagle'): a selection snapshot is METADATA ONLY (one osascript, no
  export) and each item id '<UUID>/L0/001' maps straight to the
  original on disk: <library>/originals/<UUID[0]>/<UUID>.<ext>.
  Alfred has Full Disk Access, so the file is read in place - no
  export session, no tmp copy. Live-Photo .mov sidecars sit beside the
  still as <UUID>_3.mov and are ignored (same primary rule as the
  export road: still wins, a real video IS its .mov). The original is
  HARDLINKED into the snapshot dir when the volume allows it (zero
  bytes copied; the tmp cleanup unlinks the LINK, never the library
  file) so Eagle reads a plain tmp path whatever its own TCC state;
  when linking fails the library path itself is handed over.
- Export is the FALLBACK only, for items whose original is missing or
  unreadable (iCloud not downloaded yet): ONE Apple Event per shot
  into a folder of its own, so the file→item mapping is exact and one
  bad shot cannot sink the others. `export ... with using originals`
  yields the true originals (HEIC, DNG, metadata intact).
- PATIENCE (2026-09-27, Vex: 'AppleEvent timed out (-1712)' twice in
  a row): AppleScript gives up on an unanswered Apple Event after
  120 s WHATEVER the subprocess allows. The 2026-09-08 road sent up
  to 20 ids in one event, and 16 cloud-only DNGs and videos (about
  1 GB) do not come down in 120 s. Every script now runs inside
  `with timeout` (_run) and each shot waits by the BYTES it has to
  pull (export_budget; the sizes come from the library's own
  Photos.sqlite, read-only, original_sizes).
  Probed live the same day on macOS 26.5: iCloud brings 4 to 5 MB/s
  whether four shots ride one event (10.3 s) or four events (8.7 s),
  so batching buys nothing; Photos KEEPS exporting after the sender
  gave up (-1712), answers other events beside a running export
  (count of selection in 0.18 s), recreates an export folder deleted
  under it without a dialog, and KEEPS every original it downloaded
  in originals/ - so a run that timed out makes the next one a
  fast-road run.
- NEVER A HALF SET: a shot that did not arrive whole fails the verb
  and nothing is handed over. A part import would number the
  stragglers out of shooting order on the rerun and shift the ♥ hero
  names. The error states FACTS only (how many, how big, which, each
  missing shot's OWN reason) and carries `.missing`; the road that
  asked words the ending ('nothing imported · send again'), because
  only the road knows what is safe to run again.
- THE ASKS: smallest pull first (a dead network then costs the
  smallest wait, and the small shots are in the library before a big
  one stalls), one second ask for a shot that left nothing, a timeout
  ends the asking, and a Photos that QUIT (-600, -609) or refuses
  automation (-1743) ends the run at once (PhotosFatal): one more
  `tell` would launch the Photos Vex just closed.
- NEVER A HALF FILE: a file counts as whole when it matches the byte
  size the library records. After an export that ended badly nothing
  else is trusted. On the direct road a file without a recorded size
  must at least have sat untouched for SETTLE seconds (Photos may
  still be writing it), else it takes the export road, whose answer
  is Photos saying it has finished. (Probed 2026-09-27 on a 146 MB
  video, stat every 0.2 s: nothing is visible in originals/ or in the
  export folder for 25 s, then the file is there WHOLE - Photos stages
  the download elsewhere. The checks are the belt, not the trousers.)
- Deleting photos is CLOSED, permanently (Vex ruling 2026-07-27):
  no AS verb exists; in-process PhotoKit SIGABRTs any interpreter
  lacking an NSPhotoLibraryUsageDescription bundle key (TCC kill,
  three crash reports 2026-07-26/27); a Shortcuts helper was built
  and REJECTED as a hack. THE design: imported shots go to the
  "✅ In Eagle" album after the verified import - Vex purges that
  album manually. Do not reopen this road. Nothing in this module
  ever writes INTO the Photos library either - reads and links only.
- Automation permission: first run pops the macOS dialog; a -1743
  error means it was denied → System Settings → Privacy → Automation.
"""

import os
import re
import subprocess
import unicodedata

ALBUM = "✅ In Eagle"
LIBRARY = (os.environ.get("photos_library")
           or os.path.expanduser("~/Pictures/Photos Library.photoslibrary"))
VIDEO_EXTS = (".mov", ".mp4", ".m4v")
SIDECARS = (".aae", ".xmp")   # edit recipes and metadata, never the shot
AE_GRACE = 20         # s the osascript process outlives its Apple Event
WAIT_MIN = 300        # s: the least one shot's export is given
WAIT_MAX = 3600       # s: the most one shot's export waits
STALE = 6 * 3600      # s: a snapshot dir this old is nobody's any more
#                       (well past WAIT_MAX plus the Eagle and attach tail
#                       of the run that owns it)
SETTLE = 5            # s a file of unknown size must have sat untouched
META_TOTAL = 600      # s: the selection read sends three events per shot
WAIT_BPS = 500000     # the wait assumes iCloud brings 0.5 MB/s or more
WAIT_BLIND = 180      # s per item when the library cannot tell sizes
# on-disk originals carry the UTI extension, the camera filename the
# camera's spelling - both spellings are tried before a dir scan
_EXT_ALIASES = {"jpg": ("jpeg",), "jpeg": ("jpg",),
                "tif": ("tiff",), "tiff": ("tif",),
                "heif": ("heic",), "heic": ("heif",)}
_UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")
# osascript ends an error line with its number: '… timed out. (-1712)'.
# Read THAT, never a bare substring: the text quotes the media item id
# and a UUID can hold '-1712' as a group of its own.
_CODE_RE = re.compile(r"\((-?\d+)\)\s*$", re.M)


class PhotosError(Exception):
    """Toast-ready message; callers fail closed."""


class NoSelection(PhotosError):
    """Nothing selected - callers fall through to their next source."""


class PhotosFatal(PhotosError):
    """Nothing more can be asked of Photos in this run: it quit, or
    automation is not allowed. Every further `tell` would launch it
    again or fail the same way."""


class PhotosTimeout(PhotosError):
    """Photos did not answer in time. It keeps working after the
    sender gave up and keeps what it downloaded, so the next run
    finds those originals on disk."""


def _esc(s):
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def _run(script, timeout=300, total=None):
    """ONE osascript whose Apple Events wait as long as the process
    does: the script is wrapped in `with timeout of <timeout> seconds`
    (without it AppleScript gives up after 120 s, error -1712) and the
    process gets AE_GRACE on top, so a script that sends ONE event
    sees the event expire first and report itself. `with timeout` is
    a deadline PER EVENT: a script that sends many (the selection
    read) passes `total`, the process's own limit. Both endings raise
    PhotosTimeout."""
    timeout = max(1, int(timeout))
    limit = max(int(total or 0), timeout + AE_GRACE)
    wrapped = f"with timeout of {timeout} seconds\n{script}\nend timeout"
    try:
        r = subprocess.run(["osascript", "-e", wrapped],
                           capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired:
        raise PhotosTimeout(f"Photos silent for {_mins(limit)}")
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        codes = _CODE_RE.findall(err)
        code = int(codes[-1]) if codes else 0
        if code == -1743:
            raise PhotosFatal("Photos automation not allowed - System "
                              "Settings → Privacy & Security → Automation")
        if code == -1712:
            raise PhotosTimeout(f"Photos silent for {_mins(timeout)}")
        if code in (-600, -609):
            raise PhotosFatal("Photos quit mid-way")
        if code == -1728:
            raise PhotosError("a selected shot is gone from Photos · "
                              "select again")
        raise PhotosError(f"Photos scripting failed: {err[:160]}")
    return r.stdout


def _mins(seconds):
    return (f"{int(seconds)} s" if seconds < 120
            else f"{int(round(seconds / 60.0))} min")


def fmt_size(nbytes):
    """'343 MB' / '1.2 GB' - toast-ready, '' for nothing known."""
    if not nbytes or nbytes <= 0:
        return ""
    mb = nbytes / 1e6
    if mb < 1000:
        return f"{max(1, int(round(mb)))} MB"
    return f"{mb / 1000:.1f} GB"


def _is_video(name):
    return (name or "").lower().endswith(VIDEO_EXTS)


# ------------------------------------------------ selection metadata

def parse_meta(raw):
    """counter TAB id TAB favorite TAB filename lines → ([items], bad).
    The counter (not enumerate) keys the line so a dropped line can
    never shift the mapping, and filename sits LAST so a tab inside it
    survives the split (review find 2026-07-25)."""
    items, bad = [], 0
    for line in (raw or "").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 3)
        if len(parts) != 4 or not parts[0].strip().isdigit():
            bad += 1
            continue
        idx, mid, fav, fname = parts
        items.append({"idx": int(idx), "id": mid.strip(),
                      "filename": fname.strip(),
                      "favorite": fav.strip().lower() == "true"})
    return items, bad


def selection_meta(timeout=120):
    """The CURRENT Photos selection as metadata, selection order:
    [{'idx', 'id', 'filename', 'favorite'}]. One osascript, no export.
    Raises NoSelection on an empty selection - honest, never guesses;
    fails CLOSED on an unparseable line (a wrong-file import is worse
    than no import)."""
    script = '''
set out to ""
tell application "Photos"
    set sel to selection
    if (count of sel) is 0 then error "EMPTY_SELECTION"
    set i to 0
    repeat with mi in sel
        set i to i + 1
        set out to out & i & tab & (id of mi) & tab & (favorite of mi) & \
tab & (filename of mi) & linefeed
    end repeat
end tell
return out'''
    try:
        raw = _run(script, timeout=timeout, total=META_TOTAL)
    except PhotosTimeout:
        # no 'run again' here: only the road knows what is safe to run
        raise PhotosTimeout("Photos did not hand over the selection")
    except PhotosError as e:
        if "EMPTY_SELECTION" in str(e):
            raise NoSelection("nothing selected in Photos")
        raise
    items, bad = parse_meta(raw)
    if bad:
        raise PhotosError(f"{bad} selected items had unparseable names")
    if not items:
        raise NoSelection("nothing selected in Photos")
    return items


# ------------------------------------------------ sizes + patience

def _uuid_of(media_id):
    """'<UUID>/L0/001' → 'UUID' (upper), '' for anything else."""
    u = (media_id or "").split("/", 1)[0].strip()
    return u.upper() if _UUID_RE.match(u) else ""


def original_sizes(media_ids, lib=None):
    """What the library itself records about each item's original:
    {UUID: {'bytes': the primary original, 'pull': everything an
    originals export brings down - the Live-Photo movie and the RAW
    half of a pair included}}. A read-only look at <library>/database/
    Photos.sqlite (ZINTERNALRESOURCE: data store subtype 1 = the
    original, resource type 0 photo / 1 video; 17 = the RAW alternate,
    18 = the Live-Photo movie; read off the live library 2026-09-27).
    ANY trouble (no access, the schema moved, a lock, the library not
    open anywhere) answers {} and the callers fall back to blind
    patience and the settled check:
    sizes tune the wait and prove a file whole, they never pick what
    gets imported."""
    uuids = sorted({u for u in map(_uuid_of, media_ids or ()) if u})
    if not uuids:
        return {}
    db = os.path.join(lib or LIBRARY, "database", "Photos.sqlite")
    # the store is a WAL database: a reader that finds no -shm beside
    # it would CREATE one (and a -wal). Those exist whenever Photos or
    # its daemon has the library open - only then is it read, so this
    # never adds a file to the library.
    if not (_isfile(db) and _isfile(db + "-shm")):
        return {}
    out = {}
    try:
        import sqlite3
        from urllib.parse import quote
        con = sqlite3.connect(f"file:{quote(db)}?mode=ro", uri=True,
                              timeout=2)
        try:
            for i in range(0, len(uuids), 200):
                part = uuids[i:i + 200]
                rows = con.execute(
                    "SELECT a.ZUUID, r.ZRESOURCETYPE, r.ZDATASTORESUBTYPE, "
                    "r.ZDATALENGTH FROM ZASSET a JOIN ZINTERNALRESOURCE r "
                    "ON r.ZASSET = a.Z_PK WHERE a.ZUUID IN (%s) AND "
                    "r.ZDATASTORESUBTYPE IN (1, 17, 18)"
                    % ",".join("?" * len(part)), part).fetchall()
                for uuid, rtype, stype, n in rows:
                    n = int(n or 0)
                    if n <= 0:
                        continue
                    e = out.setdefault(str(uuid).upper(),
                                       {"bytes": 0, "pull": 0})
                    e["pull"] += n
                    if stype == 1 and rtype in (0, 1):
                        e["bytes"] = n
        finally:
            con.close()
    except Exception:
        return {}
    return out


def export_budget(n_items, nbytes=0):
    """Seconds ONE export event may take. By bytes when the library
    told them (two minutes of slack plus the pull at WAIT_BPS), else
    WAIT_BLIND per item; never under WAIT_MIN, never over WAIT_MAX."""
    if nbytes and nbytes > 0:
        want = 120 + nbytes / float(WAIT_BPS)
    else:
        want = max(1, int(n_items or 0)) * WAIT_BLIND
    return int(min(WAIT_MAX, max(WAIT_MIN, want)))


def _want(sizes, media_id):
    return int((sizes.get(_uuid_of(media_id)) or {}).get("bytes") or 0)


def _pull(sizes, items):
    return sum(int((sizes.get(_uuid_of(it["id"])) or {}).get("pull") or 0)
               for it in items)


def _told(sizes, items):
    """The bytes to SAY for a group: their pull when the library told
    every shot's size, else 0 (say nothing) - a sum that counts an
    unknown shot as nothing would pass for the whole."""
    each = [_pull(sizes, [it]) for it in items]
    return sum(each) if each and all(each) else 0


# ------------------------------------------------ direct-disk road

def original_path(media_id, filename, lib=None, dir_cache=None):
    """The on-disk original for a Photos item, or None when it is not
    there (iCloud original not downloaded, foreign id, no read access -
    every miss means 'take the export road', never an error).
    '<UUID>/L0/001' + 'IMG_1.HEIC' → <lib>/originals/<U>/<UUID>.heic.
    The extension is tried as the camera spelt it, lowercased, and via
    the UTI aliases; then the directory is scanned once (cached per
    run) for '<UUID>.*', still preferred unless the item IS a video -
    the '<UUID>_3.mov' Live-Photo sidecar never matches the bare stem."""
    lib = lib or LIBRARY
    uuid = (media_id or "").split("/", 1)[0].strip()
    if not _UUID_RE.match(uuid):
        return None
    uuid = uuid.upper()
    d = os.path.join(lib, "originals", uuid[0])
    ext = os.path.splitext(filename or "")[1].lstrip(".")
    tried = []
    for e in (ext.lower(), ext, *_EXT_ALIASES.get(ext.lower(), ())):
        if e and e not in tried:
            tried.append(e)
    for e in tried:
        p = os.path.join(d, f"{uuid}.{e}")
        if _isfile(p):
            return p
    # spelling unknown: one dir scan, cached per run
    if dir_cache is None:
        dir_cache = {}
    names = dir_cache.get(d)
    if names is None:
        try:
            names = os.listdir(d)
        except OSError:
            names = []
        dir_cache[d] = names
    cands = [n for n in names
             if n.upper().startswith(uuid + ".") and not n.startswith(".")]
    if not cands:
        return None
    want_video = _is_video(filename)
    pref = [n for n in cands if _is_video(n) == want_video]
    return os.path.join(d, sorted(pref or cands)[0])


def _isfile(p):
    try:
        return os.path.isfile(p)
    except OSError:
        return False


def _readable(p):
    """Can THIS process actually read the bytes? TCC hands back EPERM
    on open, an iCloud stub is empty - both mean export."""
    try:
        if os.path.getsize(p) <= 0:
            return False
        with open(p, "rb") as f:
            return bool(f.read(16))
    except OSError:
        return False


def _complete(p, want=0):
    """Readable AND whole. When the library told the original's size
    the file must match it byte for byte: Photos may still be writing
    it, and a half file must never pass for an original. No size
    known = non-empty and untouched for SETTLE seconds."""
    if not _readable(p):
        return False
    try:
        if want:
            return os.path.getsize(p) == want
        import time
        return time.time() - os.path.getmtime(p) >= SETTLE
    except OSError:
        return False


def _stage_link(src, subdir, filename):
    """Hardlink the original into the snapshot dir (zero bytes copied)
    so downstream readers see a plain tmp path. Falls back to the
    library path itself when the link cannot be made (other volume,
    odd filesystem) - a link is an optimisation, never a gate."""
    try:
        os.makedirs(subdir, exist_ok=True)
        name = os.path.basename(filename) or os.path.basename(src)
        # keep the on-disk spelling so the hero attach derives a real ext
        ext = os.path.splitext(src)[1]
        if ext and not name.lower().endswith(ext.lower()):
            name = os.path.splitext(name)[0] + ext
        dst = os.path.join(subdir, name)
        if os.path.lexists(dst):
            os.unlink(dst)
        os.link(src, dst)
        return dst
    except OSError:
        return src


# ------------------------------------------------ export road

def _export_chunk(media_ids, dest, timeout=WAIT_MIN):
    """ONE export event for the given ids (direct reference, no
    whose-scan) into `dest`. Originals, so Live Photos land as pairs.
    The snapshot verb sends one id per event."""
    os.makedirs(dest, exist_ok=True)
    refs = ", ".join(f'media item id "{_esc(m)}"' for m in media_ids)
    _run(f'''
tell application "Photos"
    export {{{refs}}} to (POSIX file "{_esc(dest)}") with using originals
end tell''', timeout=timeout)


def _nfc(name):
    """Photos hands names composed (NFC), the disk may hold them
    decomposed (NFD): 'Šešir' must equal 'Šešir'."""
    return unicodedata.normalize("NFC", name or "").lower()


def _match_exported(subdir, filename, alone=False):
    """The exported file that belongs to `filename` inside an export dir:
    exact name first (case and normal form blind), else the same stem
    with the primary rule (still over the Live-Photo movie, unless the
    item is a video). Sidecars (.aae, .xmp) are never the shot.
    `alone` = the folder was made for THIS shot only: when no name
    matches, a lone file of the right kind is it. None when the export
    left nothing for it."""
    try:
        files = sorted(f for f in os.listdir(subdir)
                       if not f.startswith(".")
                       and not f.lower().endswith(SIDECARS))
    except OSError:
        return None
    want = _nfc(filename)
    for f in files:
        if _nfc(f) == want:
            return os.path.join(subdir, f)
    want_video = _is_video(filename)
    stem = os.path.splitext(want)[0]
    same = [f for f in files if os.path.splitext(_nfc(f))[0] == stem]
    if not same:
        kind = [f for f in files if _is_video(f) == want_video]
        return (os.path.join(subdir, kind[0])
                if alone and len(kind) == 1 else None)
    pref = [f for f in same if _is_video(f) == want_video]
    return os.path.join(subdir, (pref or same)[0])


# ------------------------------------------------ THE snapshot verb

def selection_snapshot_export(dest_dir, timeout=None, lib=None,
                              notice=None, only=None):
    """Snapshot the CURRENT Photos selection as original files.

    Returns [{'id', 'filename', 'favorite', 'path', 'direct'}] in
    selection order - path = the primary file (Live-Photo .MOV
    sidecars skipped), direct = True when it came off the disk without
    an export. Items whose original is on disk (and whole) are
    linked/handed over at once; the rest are exported ONE PER EVENT,
    smallest pull first, each waiting by the bytes it has to pull
    (`timeout` overrides that per shot) and asked a second time when
    the first ask left nothing.
    `notice(n, nbytes, seconds)` is called ONCE before the first
    export - the callers' 'downloading' banner. `only(items) → items`
    narrows the selection BEFORE any file is touched (the attach road
    needs the ♥ shots, not the whole shoot); an empty answer returns
    [] without an export, a PhotosError raised in it passes through.

    ALL OR NOTHING: a shot that did not arrive whole raises
    PhotosError (PhotosTimeout when Photos is still pulling,
    PhotosFatal when Photos quit) carrying `.missing`, `.head` and
    `.tail`, and no shot is handed over. Raises NoSelection on an
    empty selection (a PhotosError, so old callers still fail
    closed)."""
    os.makedirs(dest_dir, exist_ok=True)
    _sweep_stale(dest_dir)
    items = selection_meta()
    if only is not None:
        items = list(only(items))
        if not items:
            return []
    sizes = original_sizes([it["id"] for it in items], lib=lib)
    cache = {}
    pending = []
    for it in items:
        it["path"], it["direct"] = None, False
        src = original_path(it["id"], it["filename"], lib=lib,
                            dir_cache=cache)
        if src and _complete(src, _want(sizes, it["id"])):
            it["path"] = _stage_link(
                src, os.path.join(dest_dir, str(it["idx"])), it["filename"])
            it["direct"] = True
        else:
            pending.append(it)
    pending.sort(key=lambda it: (_pull(sizes, [it]), it["idx"]))

    def wait_for(it):
        return timeout or export_budget(1, _pull(sizes, [it]))

    if pending and notice:
        try:
            notice(len(pending), _told(sizes, pending),
                   sum(wait_for(it) for it in pending))
        except Exception:
            pass
    for k, it in enumerate(pending, 1):
        for ask in ("", "r"):
            sub = os.path.join(dest_dir, f"c{k}{ask}")
            why = None                      # None = Photos left no file
            try:
                if not photos_running():
                    raise PhotosFatal("Photos quit mid-way")
                _export_chunk([it["id"]], sub, timeout=wait_for(it))
                it["path"] = _match_exported(sub, it["filename"],
                                             alone=True)
            except PhotosFatal as e:
                raise _facts(e, str(e), "",
                             [m for m in items if not m["path"]])
            except PhotosError as e:
                why = e
            if not it["path"]:
                _salvage([it], sub, dest_dir, sizes, lib)
            if it["path"]:
                break
            it["why"] = why
            if isinstance(why, PhotosTimeout):
                break
        if not it["path"] and isinstance(it["why"], PhotosTimeout):
            # Photos is still pulling THIS shot: more asks only pile up
            # beside it, the rest of the selection waits for the next
            # run. A timed-out shot that salvage proved whole (the
            # answer got lost) does not stop anything.
            break
    missing = [it for it in items if not it["path"]]
    if missing:
        raise _incomplete(missing, items, sizes)
    for it in items:
        it.pop("why", None)
    return items


def _salvage(chunk, sub, dest_dir, sizes, lib):
    """After an export that ended badly (or left nothing) keep what is
    PROVABLY whole: the file in the export folder, else the original
    Photos downloaded into the library meanwhile - both only against
    the byte size the library told. No size known = nothing trusted."""
    for c in chunk:
        want = _want(sizes, c["id"])
        if c.get("path") or not want:
            continue
        p = _match_exported(sub, c["filename"], alone=True)
        if p and _complete(p, want):
            c["path"] = p
            continue
        src = original_path(c["id"], c["filename"], lib=lib, dir_cache={})
        if src and _complete(src, want):
            c["path"] = _stage_link(
                src, os.path.join(dest_dir, str(c["idx"])), c["filename"])
            c["direct"] = True


def _facts(e, head, tail, missing):
    """Dress an error for the road that asked: `.head` = the count in
    one fragment, `.tail` = size, names and reasons, `.missing` = the
    ids. The road puts ITS verdict and ITS next step in front of the
    tail, because a banner shows two lines and only the road knows
    what is safe to run again."""
    e.head, e.tail = head, tail
    e.missing = [m["id"] for m in missing]
    e.waiting = getattr(e, "waiting", False)
    return e


def _incomplete(missing, items, sizes):
    """The error for a set that did not arrive whole. FACTS only: how
    many, how big, which, and each shot's OWN reason - a shot's
    trouble that its second ask cured is nobody's reason, and shots
    that failed differently are named apart. Shots whose ask timed
    out and shots never asked (they sat behind the stall) are 'still
    in iCloud'; a shot that failed or left no file is 'not exported'
    with its words. PhotosTimeout when waiting is all that is wrong,
    else PhotosError; `.waiting` tells the road that time will help."""
    def names(group):
        out = ", ".join(m["filename"] for m in group[:2])
        return out + (f" +{len(group) - 2}" if len(group) > 2 else "")

    def reason(m):
        why = str(m["why"] or "Photos left no file")
        return why.replace("Photos scripting failed: ", "")[:90]

    waiting = [m for m in missing
               if "why" not in m or isinstance(m["why"], PhotosTimeout)]
    failed = [m for m in missing if m not in waiting]
    head, tail = [], []
    if waiting:
        head.append(f"{len(waiting)} of {len(items)} still in iCloud")
        size = fmt_size(_told(sizes, waiting))
        tail.append((f"{size} · " if size else "") + names(waiting))
    if failed:
        head.append(f"{len(failed)} of {len(items)} not exported")
        groups = {}
        for m in failed:
            groups.setdefault(reason(m), []).append(m)
        for why, group in groups.items():
            tail.append(f"{names(group)} · {why}")
    if waiting:
        tail.append("Photos keeps downloading")
    head, tail = " · ".join(head), " · ".join(tail)
    e = (PhotosError if failed else PhotosTimeout)(f"{head} · {tail}")
    e.waiting = bool(waiting)
    return _facts(e, head, tail, missing)


def _sweep_stale(dest_dir, age=STALE):
    """Drop snapshot dirs of EARLIER runs: siblings of `dest_dir`
    wearing its mkdtemp prefix, untouched for `age` seconds. A run
    that timed out leaves one behind - Photos goes on writing into an
    export folder after the sender gave up, and recreates it when it
    was deleted under it (probed 2026-09-27). Links and exports only,
    the library is never touched. Silent on any trouble."""
    import shutil
    import time
    try:
        parent, name = os.path.split(os.path.abspath(dest_dir))
        prefix = name[:-8]          # mkdtemp: prefix + 8 random chars
        if not prefix.startswith("tickal_") or len(name) <= 8:
            return
        now = time.time()
        for n in os.listdir(parent):
            p = os.path.join(parent, n)
            if (n == name or not n.startswith(prefix)
                    or len(n) != len(name) or not os.path.isdir(p)
                    or os.path.islink(p)):
                continue
            if now - os.path.getmtime(p) > age:
                shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


def _primary_file(subdir):
    """The exported file that counts: the image half of a Live-Photo
    pair, or the lone file. None when the export left nothing."""
    try:
        files = sorted(f for f in os.listdir(subdir) if not f.startswith("."))
    except OSError:
        return None
    if not files:
        return None
    stills = [f for f in files if not _is_video(f)]
    pick = stills[0] if stills else files[0]
    return os.path.join(subdir, pick)


def file_to_album(media_ids, album=ALBUM):
    """Add items (by Photos id) to the album, creating it if missing.
    Called only AFTER the Eagle import verified - the album means
    'safely in Eagle', it must never lie."""
    if not media_ids:
        return
    refs = ", ".join(f'media item id "{_esc(m)}"' for m in media_ids)
    _run(f'''
tell application "Photos"
    if not (exists album "{_esc(album)}") then
        make new album named "{_esc(album)}"
    end if
    add {{{refs}}} to album "{_esc(album)}"
end tell''')


def export_by_id(media_id, dest_dir, timeout=None):
    """Export ONE item by id (the ♥ hero for a TickTick attach).
    Returns the exported primary file path. Waits by the bytes the
    library records for it unless `timeout` says otherwise."""
    os.makedirs(dest_dir, exist_ok=True)
    if not timeout:
        timeout = export_budget(1, _pull(original_sizes([media_id]),
                                         [{"id": media_id}]))
    _run(f'''
tell application "Photos"
    export {{media item id "{_esc(media_id)}"}} to \
(POSIX file "{_esc(dest_dir)}") with using originals
end tell''', timeout=timeout)
    return _primary_file(dest_dir)


def photos_running():
    """True when Photos.app is up. Surfaces check this BEFORE
    selection_count - an AS call would otherwise LAUNCH Photos as a
    render side effect."""
    try:
        return subprocess.run(["pgrep", "-x", "Photos"],
                              capture_output=True).returncode == 0
    except Exception:
        return False


def selection_count():
    """Cheap peek for surfaces that want to show '3 selected'. 0 on any
    scripting trouble - display only, never a gate (the import verb
    reads the selection itself and never calls this)."""
    if not photos_running():
        return 0
    try:
        return int(_run('tell application "Photos" to count of selection',
                        timeout=30).strip() or "0")
    except (PhotosError, ValueError):
        return 0
