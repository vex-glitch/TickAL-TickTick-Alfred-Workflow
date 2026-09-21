"""mela.py - Mela's recipe library, read from a COPY of its database.

WHY: Vex plans meals in TickTick, but the recipes live in Mela (the recipe
app). A planned meal is a task titled "[Name](mela://recipe/<UUID>)" whose
description is the recipe rendered as markdown - the format the
mela-to-ticktick script has put on the clipboard all along. This module is
that script's rendering ported byte-for-byte (same data in, same text out),
plus a library loader so the workflow can list, pick and tag recipes without
Mela in front: the meal categories ("01 • Meal", "02 • Breakfast", ...) map
to the plan's meal tags, cuisines ("Thai", "Mexican") ride along.

Mela keeps its Core Data store open (Curcuma.sqlite with -wal and -shm
beside it), so the live file is NEVER opened: all three are copied to a
snapshot dir first, and the copy is reused for a minute or until any of the
three changes. Images live in another table and are never read - explicit
column list, no SELECT *. The recipe<->category join table is named by Core
Data (Z_4TAGS today) and renumbered on a schema migration, so its name and
columns are discovered from sqlite_master rather than assumed.

Pure helpers first (render, link parsing, tag mapping, lookup); the loader
that touches the disk comes last.
"""
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import urllib.parse
from collections import Counter, defaultdict, namedtuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

try:                                   # the app's own escape stripper (pure)
    from periodic_model import unescape_md
except ImportError:                    # standalone: a local one is enough

    _MD_ESCAPE_RE = re.compile(r"\\([\[\]()_*#])")

    def unescape_md(text):
        """Drop the backslashes TickTick's app puts before [ ] ( ) _ * #."""
        text = text or ""
        for _ in range(4):             # the app can escape an escape again
            out = _MD_ESCAPE_RE.sub(r"\1", text)
            if out == text:
                break
            text = out
        return text

DB_DIR = os.path.expanduser("~/Library/Group Containers/66JC38RDUD.recipes.mela/Data")
DB_PATH = os.path.join(DB_DIR, "Curcuma.sqlite")
SNAP_DIR = os.path.expanduser("~/.ticktick_alfred/run/mela")   # 0700, on demand
SNAP_TTL = 600                         # seconds an unchanged copy is reused
                                       # (sources' mtimes are compared too, so
                                       # the TTL is a safety net; at 60 s every
                                       # browse render re-copied 19 MB)
PRUNE_AFTER = 600                      # older sibling copies are removed
APPLE_EPOCH = 978307200                # 2001-01-01 UTC as a unix timestamp
LINK_RE = re.compile(r"mela://recipe/([0-9A-Fa-f-]{36})")

# category title -> meal tag. ORDER IS PRIORITY for a recipe in several.
DEFAULT_TAG_MAP = {
    "02 • Breakfast": "🍳breakfast",
    "01 • Meal": "🍛lunch",
    "03 • Snack": "🌮snack",
}

_RETRY_S = 0.5                                 # pause before the one re-copy
_PREFIX_RE = re.compile(r"^\d+\s*[•·-]\s*")    # "01 • Meal" -> "Meal"
_SNAP_NAME_RE = re.compile(r"^(\d+)-\d+")      # <int(now)>-<pid>[-n]


class MelaError(RuntimeError):
    """One line, worded for a notification toast: what happened · what to do."""


@dataclass
class Recipe:
    id: str                            # UUID, upper-cased on load
    pk: int                            # Z_PK: the join key for categories
    title: str
    yield_text: str = ""
    prep: str = ""
    cook: str = ""
    total: str = ""
    link: str = ""
    ingredients: str = ""
    instructions: str = ""
    nutrition: str = ""
    notes: str = ""
    text: str = ""
    date: Optional[datetime] = None    # UTC
    favorite: bool = False
    want_to_cook: bool = False
    categories: List[str] = field(default_factory=list)

    @property
    def url(self):
        return f"mela://recipe/{self.id}"


# recipes: [Recipe]; path: the copy that was read (None for an injected
# conn); age_s: seconds since Mela last wrote (None for an injected conn);
# skipped: [(pk, why)] for the rows the loader refused.
Library = namedtuple("Library", "recipes path age_s skipped")


# ── rendering (ported from mela2ticktick.py: same data -> same bytes) ───────
def _lines(s):
    """Stripped, non-empty lines."""
    return [l.strip() for l in (s or "").splitlines() if l.strip()]


def bullets(text):
    """'- item' per line; a '# Header' line becomes a bold header."""
    out = []
    for l in _lines(text):
        out.append(f"**{l[1:].strip()}**" if l.startswith("#") else f"- {l}")
    return out


def numbered(text):
    """'n. step' per line, the count running on across bold '# Header's."""
    out, n = [], 0
    for l in _lines(text):
        if l.startswith("#"):
            out.append(f"**{l[1:].strip()}**")
        else:
            n += 1
            out.append(f"{n}. {l}")
    return out


# Mela has no rating column: a recipe Vex rated in the app carries a plain
# "Rating: ⭐️⭐️⭐️⭐️⭐️" line in its description (ZTEXT) or its notes
# (ZNOTES), verified on Burbon Asian Chicken 2026-09-21. Mela is never
# written (Core Data under CloudKit, no write intent, no URL verb): the
# rating is only READ, and meal.py's stars line in TickTick is the record.
STAR = "⭐️"                  # ⭐️ as Mela writes it: U+2B50 + VS16
RATING_RE = re.compile(r"^[ \t]*Rating:[ \t]*((?:⭐️?|★)+)[ \t]*$",
                       re.MULTILINE)


def rating_of(recipe):
    """The stars Mela shows for a recipe (1..5, more is capped), read off
    its first "Rating:" line, description first, then notes; None when
    unrated. VS16 blind: the count is the same with or without it."""
    for txt in (getattr(recipe, "text", "") or "", getattr(recipe, "notes", "") or ""):
        m = RATING_RE.search(txt)
        if m:
            return min(len(m.group(1).replace("️", "")), 5)
    return None


def strip_rating(text):
    """`text` without its "Rating:" line(s); a blank line the removal left
    doubled (or leading) goes with it. Byte-identical when there is none."""
    text = text or ""
    if not RATING_RE.search(text):
        return text
    out, gap = [], False
    for l in text.split("\n"):
        if RATING_RE.match(l):
            gap = True
            continue
        if gap and not l.strip() and (not out or not out[-1].strip()):
            continue
        gap = False
        out.append(l)
    return "\n".join(out)


def render_markdown(recipe):
    """The TickTick description of a recipe: link header, source site, the
    stars when Mela has a rating (right under the links, where meal.py
    keeps them), blurb, one meta line, then Ingredients / Steps / Nutrition
    / Notes - Mela's own "Rating:" line dropped from blurb and notes, a
    Notes section that leaves empty omitted. Ends with exactly one newline;
    an unrated recipe renders byte-identical to the pre-rating form."""
    r = recipe
    md = [f"> 🔗 [{r.title}]({r.url})"]
    if r.link:
        host = urllib.parse.urlparse(r.link).netloc.replace("www.", "") or r.link
        md.append(f"> 🌐 [{host}]({r.link})")
    rating = rating_of(r)
    if rating:
        md.append("> " + STAR * rating)
    md.append("")
    text = strip_rating(r.text)
    if text and (text == r.text or text.strip()):       # emptied by the strip = omitted
        md += [text.strip(), ""]
    meta = []
    if r.yield_text:
        meta.append(f"Serves: {r.yield_text}")
    if r.prep:
        meta.append(f"Prep: {r.prep}")
    if r.cook:
        meta.append(f"Cook: {r.cook}")
    if r.total:
        meta.append(f"Total: {r.total}")
    if meta:
        md.append(" · ".join(meta))
    if r.ingredients:
        md += ["## Ingredients:"] + bullets(r.ingredients) + [""]
    if r.instructions:
        md += ["## Steps:"] + numbered(r.instructions) + [""]
    if r.nutrition:
        md += ["## Nutrition:"] + [f"- {l}" for l in _lines(r.nutrition)] + [""]
    notes = strip_rating(r.notes)
    if notes and (notes == r.notes or _lines(notes)):   # emptied by the strip = omitted
        md += ["## Notes:"] + _lines(notes) + [""]
    return "\n".join(md).rstrip() + "\n"


# ── links, tags, lookup ─────────────────────────────────────────────────────
def link_uuid(title):
    """The recipe UUID (upper-cased) in a task title, or None. The app may
    have saved the title as "\\[Name\\]\\(mela://…\\)", so unescape first."""
    m = LINK_RE.search(unescape_md(title or ""))
    return m.group(1).upper() if m else None


def _plain(category):
    """'02 • Breakfast' -> 'breakfast': the sort prefix and case are noise."""
    return _PREFIX_RE.sub("", (category or "").strip()).casefold()


def meal_tag_for(recipe, mapping=None):
    """The meal tag for a recipe's categories, or None. `mapping` order is
    priority; a key matches a category exactly, or once both are stripped of
    a leading 'NN • ' / 'NN · ' / 'NN - ' and casefolded."""
    mapping = DEFAULT_TAG_MAP if mapping is None else mapping
    cats = list(recipe.categories or [])
    for key, tag in mapping.items():
        want = _plain(key)
        for cat in cats:
            if cat == key or _plain(cat) == want:
                return tag
    return None


def categories_of(recipe):
    """The recipe's category titles, sorted."""
    return sorted(recipe.categories or [])


def by_id(uuid, recipes):
    """The recipe with this UUID (any case), or None."""
    want = (uuid or "").strip().upper()
    if not want:
        return None
    return next((r for r in recipes if (r.id or "").upper() == want), None)


def _apple_date(value):
    """Core Data stores seconds since 2001-01-01 UTC; None for junk."""
    try:
        return datetime.fromtimestamp(float(value) + APPLE_EPOCH, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


# ── the snapshot: Mela holds the live file, so read a copy ──────────────────
def db_present():
    return os.path.isfile(DB_PATH)


def _sources():
    """(live path, basename) for the main file and the -wal / -shm beside
    it - only those that exist. The three travel together or the copy is torn."""
    out = []
    for suffix in ("", "-wal", "-shm"):
        src = DB_PATH + suffix
        if os.path.exists(src):
            out.append((src, os.path.basename(DB_PATH) + suffix))
    return out


def _mtimes(sources):
    return {name: os.stat(src).st_mtime_ns for src, name in sources}


def _stamp_path():
    return os.path.join(SNAP_DIR, "stamp.json")


def _read_stamp():
    try:
        with open(_stamp_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_stamp(stamp):
    tmp = _stamp_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stamp, f)
    os.replace(tmp, _stamp_path())


def _verify(path):
    """Raise sqlite3.DatabaseError unless the copy opens and checks clean."""
    con = sqlite3.connect(path)
    try:
        row = con.execute("PRAGMA quick_check").fetchone()
    finally:
        con.close()
    if not row or row[0] != "ok":
        raise sqlite3.DatabaseError(row[0] if row else "quick_check: no result")


def _copy_into(dest, sources):
    if os.path.isdir(dest):
        shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, 0o700)
    for src, name in sources:
        shutil.copy2(src, os.path.join(dest, name))


def _prune(keep, now):
    """Remove sibling copies older than PRUNE_AFTER - never the one in use."""
    try:
        names = os.listdir(SNAP_DIR)
    except OSError:
        return
    for name in names:
        m = _SNAP_NAME_RE.match(name)
        path = os.path.join(SNAP_DIR, name)
        if not m or path == keep or not os.path.isdir(path):
            continue
        if now - int(m.group(1)) > PRUNE_AFTER:
            shutil.rmtree(path, ignore_errors=True)


def snapshot(max_age=SNAP_TTL, now=None):
    """Path of a readable copy of the database. A copy younger than
    `max_age` whose sources have not changed is reused; otherwise the files
    are copied into their own SNAP_DIR/<int(now)>-<pid>/ and checked. A
    torn copy (Mela mid-write) is copied once more after a short pause."""
    if not db_present():
        raise MelaError(f"Mela database not found at {DB_PATH} · "
                        "Mela not installed, or never run on this Mac")
    now = time.time() if now is None else now
    sources = _sources()
    mtimes = _mtimes(sources)
    base = os.path.basename(DB_PATH)
    os.makedirs(SNAP_DIR, 0o700, exist_ok=True)
    stamp = _read_stamp()
    if stamp and stamp.get("db") == DB_PATH and stamp.get("src") == mtimes:
        copy = os.path.join(str(stamp.get("dir") or ""), base)
        age = now - float(stamp.get("copied_at") or 0)
        if 0 <= age < max_age and os.path.isfile(copy):
            return copy
    dest = os.path.join(SNAP_DIR, f"{int(now)}-{os.getpid()}")
    n = 1
    while os.path.exists(dest):        # same second, same pid: stay fresh
        n += 1
        dest = os.path.join(SNAP_DIR, f"{int(now)}-{os.getpid()}-{n}")
    copy = os.path.join(dest, base)
    for attempt in (1, 2):
        try:
            _copy_into(dest, sources)
            _verify(copy)
            break
        except (sqlite3.DatabaseError, FileNotFoundError) as e:
            if attempt == 2:
                shutil.rmtree(dest, ignore_errors=True)
                raise MelaError("Mela database copy unreadable (Mela busy?) "
                                "· try again") from e
            time.sleep(_RETRY_S)
            sources = _sources()
            mtimes = _mtimes(sources)
    _write_stamp({"db": DB_PATH, "dir": dest, "copied_at": now, "src": mtimes})
    _prune(dest, now)
    return copy


# ── the loader ──────────────────────────────────────────────────────────────
_RECIPE_COLS = ("Z_PK", "ZID", "ZTITLE", "ZYIELD", "ZPREPTIME", "ZCOOKTIME",
                "ZTOTALTIME", "ZLINK", "ZINGREDIENTS", "ZINSTRUCTIONS",
                "ZNUTRITION", "ZNOTES", "ZTEXT", "ZDATE", "ZFAVORITE",
                "ZWANTTOCOOK")         # never *: image blobs live next door


def _join_table(conn):
    """(table, recipes column, tags column) of the recipe<->tag join, found
    rather than assumed: Core Data names it Z_<n>TAGS with Z_<n>RECIPES and
    Z_<m>TAGS columns, and renumbers <n>/<m> on a schema migration."""
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                        "AND name LIKE 'Z\\_%TAGS' ESCAPE '\\'").fetchall()
    for name in sorted((r[0] for r in rows), key=lambda n: (n != "Z_4TAGS", n)):
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{name}")')]
        rc = next((c for c in cols if "RECIPES" in c.upper()), None)
        tc = next((c for c in cols if "TAGS" in c.upper()), None)
        if rc and tc:
            return name, rc, tc
    return None


def _categories(conn):
    """{recipe pk: [category title, ...]}; empty when the join is not there."""
    out = defaultdict(list)
    try:
        join = _join_table(conn)
        if not join:
            return out
        table, rc, tc = join
        sql = (f'SELECT j."{rc}", t.ZTITLE FROM "{table}" j '
               f'JOIN ZRECIPETAG t ON t.Z_PK = j."{tc}"')
        for pk, title in conn.execute(sql):
            if title:
                out[pk].append(title)
    except sqlite3.Error:
        return defaultdict(list)
    return out


def _age_s(now=None):
    """Seconds since Mela last wrote: the newer of the main file and -wal."""
    now = time.time() if now is None else now
    stamps = [os.stat(p).st_mtime for p in (DB_PATH, DB_PATH + "-wal")
              if os.path.exists(p)]
    return now - max(stamps) if stamps else None


def _recipe(row, cats):
    return Recipe(
        id=str(row["ZID"]).strip().upper(), pk=row["Z_PK"], title=row["ZTITLE"],
        yield_text=row["ZYIELD"] or "", prep=row["ZPREPTIME"] or "",
        cook=row["ZCOOKTIME"] or "", total=row["ZTOTALTIME"] or "",
        link=row["ZLINK"] or "", ingredients=row["ZINGREDIENTS"] or "",
        instructions=row["ZINSTRUCTIONS"] or "", nutrition=row["ZNUTRITION"] or "",
        notes=row["ZNOTES"] or "", text=row["ZTEXT"] or "",
        date=_apple_date(row["ZDATE"]), favorite=bool(row["ZFAVORITE"]),
        want_to_cook=bool(row["ZWANTTOCOOK"]), categories=sorted(cats))


def load(conn=None, path=None):
    """Every recipe, as a Library. `conn` is for tests (an open connection,
    left open); otherwise `path` or a fresh snapshot() is opened and closed.
    A row without a ZID (no link possible) or with a NULL title is skipped
    and named in Library.skipped rather than sinking the whole list."""
    own = conn is None
    if own:
        path = path or snapshot()
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    recipes, skipped = [], []
    try:
        cats = _categories(conn)
        sql = f"SELECT {', '.join(_RECIPE_COLS)} FROM ZRECIPEOBJECT ORDER BY Z_PK"
        for row in conn.execute(sql):
            pk = row["Z_PK"]
            if not str(row["ZID"] or "").strip():
                skipped.append((pk, "empty ZID (no mela:// link possible)"))
            elif row["ZTITLE"] is None:
                skipped.append((pk, "NULL ZTITLE"))
            else:
                recipes.append(_recipe(row, cats.get(pk, [])))
    except sqlite3.Error as e:
        raise MelaError(f"Mela database unreadable ({e}) · schema changed?") from e
    finally:
        if own:
            conn.close()
    return Library(recipes, path, _age_s() if own else None, skipped)


def library(path=None):
    """Just the recipes (see load)."""
    return load(path=path).recipes


def freshness():
    """{age_s, newest_recipe_date, db_path, present} for a status line:
    how long since Mela wrote, and the newest recipe's date (ISO, UTC)."""
    out = {"age_s": None, "newest_recipe_date": None, "db_path": DB_PATH,
           "present": db_present()}
    if not out["present"]:
        return out
    out["age_s"] = _age_s()
    try:
        dates = [r.date for r in load().recipes if r.date]
    except MelaError:
        return out
    if dates:
        out["newest_recipe_date"] = max(dates).isoformat()
    return out


def main():
    """A live summary: count, freshness, category histogram, first titles."""
    try:
        lib = load()
    except MelaError as e:
        sys.exit(f"mela: {e}")
    fresh = freshness()
    print(f"{len(lib.recipes)} recipes · copy at {lib.path}")
    age = fresh["age_s"]
    print(f"freshness: Mela wrote {age:.0f} s ago · newest recipe "
          f"{fresh['newest_recipe_date']}" if age is not None else "freshness: unknown")
    if lib.skipped:
        print(f"skipped {len(lib.skipped)}: {lib.skipped[:5]}")
    hist = Counter(c for r in lib.recipes for c in r.categories)
    print("categories:")
    for cat, n in sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {n:4d}  {cat}")
    print(f"  {sum(1 for r in lib.recipes if not r.categories):4d}  (none)")
    print("first 3:")
    for r in lib.recipes[:3]:
        print(f"  {r.title}  ·  {r.url}  ·  {meal_tag_for(r) or '-'}")


if __name__ == "__main__":
    main()
