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
  unreadable (iCloud not downloaded yet), and it runs CHUNKED: one
  export session per group of ids into one folder per chunk, a chunk
  never holding two items with the same filename stem so the
  file→item mapping stays exact. `export ... with using originals`
  yields the true originals (HEIC, metadata intact).
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

ALBUM = "✅ In Eagle"
LIBRARY = (os.environ.get("photos_library")
           or os.path.expanduser("~/Pictures/Photos Library.photoslibrary"))
VIDEO_EXTS = (".mov", ".mp4", ".m4v")
CHUNK = 20            # ids per fallback export session
# on-disk originals carry the UTI extension, the camera filename the
# camera's spelling - both spellings are tried before a dir scan
_EXT_ALIASES = {"jpg": ("jpeg",), "jpeg": ("jpg",),
                "tif": ("tiff",), "tiff": ("tif",),
                "heif": ("heic",), "heic": ("heif",)}
_UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")


class PhotosError(Exception):
    """Toast-ready message; callers fail closed."""


class NoSelection(PhotosError):
    """Nothing selected - callers fall through to their next source."""


def _esc(s):
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def _run(script, timeout=300):
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PhotosError("Photos took too long (big videos still "
                          "downloading from iCloud?)")
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        if "-1743" in err:
            raise PhotosError("Photos automation not allowed - System "
                              "Settings → Privacy & Security → Automation")
        raise PhotosError(f"Photos scripting failed: {err[:160]}")
    return r.stdout


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
        raw = _run(script, timeout=timeout)
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


# ------------------------------------------------ chunked export road

def _chunks(items, size=CHUNK):
    """Group items for one export session each: at most `size` per
    chunk and NO two items sharing a filename stem (Photos would
    suffix the twin ' (1)' and the file→item mapping would be a
    guess). Order preserved."""
    out, cur, stems = [], [], set()
    for it in items:
        stem = os.path.splitext(it["filename"])[0].lower()
        if cur and (len(cur) >= size or stem in stems):
            out.append(cur)
            cur, stems = [], set()
        cur.append(it)
        stems.add(stem)
    if cur:
        out.append(cur)
    return out


def _export_chunk(media_ids, dest, timeout=600):
    """ONE export session for a batch of ids (direct reference, no
    whose-scan) into `dest`. Originals, so Live Photos land as pairs."""
    os.makedirs(dest, exist_ok=True)
    refs = ", ".join(f'media item id "{_esc(m)}"' for m in media_ids)
    _run(f'''
tell application "Photos"
    export {{{refs}}} to (POSIX file "{_esc(dest)}") with using originals
end tell''', timeout=timeout)


def _match_exported(subdir, filename):
    """The exported file that belongs to `filename` inside a chunk dir:
    exact name first (case-insensitive), else the same stem with the
    primary rule (still over sidecar, unless the item is a video).
    None when the export left nothing for it."""
    try:
        files = [f for f in os.listdir(subdir) if not f.startswith(".")]
    except OSError:
        return None
    want = (filename or "").lower()
    for f in files:
        if f.lower() == want:
            return os.path.join(subdir, f)
    stem = os.path.splitext(want)[0]
    same = [f for f in files if os.path.splitext(f)[0].lower() == stem]
    if not same:
        return None
    want_video = _is_video(filename)
    pref = [f for f in same if _is_video(f) == want_video]
    return os.path.join(subdir, sorted(pref or same)[0])


# ------------------------------------------------ THE snapshot verb

def selection_snapshot_export(dest_dir, timeout=600, lib=None):
    """Snapshot the CURRENT Photos selection as original files.

    Returns [{'id', 'filename', 'favorite', 'path', 'direct'}] in
    selection order - path = the primary file (Live-Photo .MOV
    sidecars skipped), direct = True when it came off the disk without
    an export. Items whose original is on disk are linked/handed over
    at once; the rest ride ONE chunked export. Raises NoSelection on an
    empty selection (a PhotosError, so old callers still fail closed)."""
    os.makedirs(dest_dir, exist_ok=True)
    items = selection_meta()
    cache = {}
    pending = []
    for it in items:
        it["path"], it["direct"] = None, False
        src = original_path(it["id"], it["filename"], lib=lib,
                            dir_cache=cache)
        if src and _readable(src):
            it["path"] = _stage_link(
                src, os.path.join(dest_dir, str(it["idx"])), it["filename"])
            it["direct"] = True
        else:
            pending.append(it)
    for k, chunk in enumerate(_chunks(pending), 1):
        sub = os.path.join(dest_dir, f"c{k}")
        _export_chunk([c["id"] for c in chunk], sub, timeout=timeout)
        for c in chunk:
            c["path"] = _match_exported(sub, c["filename"])
    good = [it for it in items if it["path"]]
    if not good:
        raise PhotosError("export produced no files")
    return good


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


def export_by_id(media_id, dest_dir, timeout=300):
    """Export ONE item by id (the ♥ hero for a TickTick attach).
    Returns the exported primary file path."""
    os.makedirs(dest_dir, exist_ok=True)
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
