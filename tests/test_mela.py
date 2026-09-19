#!/usr/bin/env python3
"""Unit suite for src/mela.py (the Mela recipe library) - NO real database:
an in-memory sqlite with Mela's schema subset, and a throwaway file for the
snapshot machinery. Run: python3 tests/test_mela.py
"""
import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import mela  # noqa: E402

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


SCHEMA = """
CREATE TABLE ZRECIPEOBJECT (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER,
  ZFAVORITE INTEGER, ZWANTTOCOOK INTEGER, ZDATE TIMESTAMP, ZID VARCHAR, ZTITLE VARCHAR,
  ZYIELD VARCHAR, ZPREPTIME VARCHAR, ZCOOKTIME VARCHAR, ZTOTALTIME VARCHAR, ZLINK VARCHAR,
  ZINGREDIENTS VARCHAR, ZINSTRUCTIONS VARCHAR, ZNUTRITION VARCHAR, ZNOTES VARCHAR,
  ZTEXT VARCHAR);
CREATE TABLE ZRECIPETAG (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER,
  ZTITLE VARCHAR);
"""
JOIN_STD = ("CREATE TABLE Z_4TAGS (Z_4RECIPES INTEGER, Z_5TAGS INTEGER, "
            "PRIMARY KEY (Z_4RECIPES, Z_5TAGS));")
JOIN_MIGRATED = ("CREATE TABLE Z_7TAGS (Z_7RECIPES INTEGER, Z_8TAGS INTEGER, "
                 "PRIMARY KEY (Z_7RECIPES, Z_8TAGS));")

A_ID = "3F2504E0-4F89-11D3-9A0C-0305E82C3301"
B_ID = "0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9"      # lower-case in the DB
C_ID = "C0FFEE00-0000-4000-8000-000000000003"
E_ID = "C0FFEE00-0000-4000-8000-000000000005"

TAGS = [(1, 3, 1, "01 • Meal"), (2, 3, 1, "02 • Breakfast"),
        (3, 3, 1, "03 • Snack"), (4, 3, 1, "Thai")]
COLS = ("Z_PK", "Z_ENT", "Z_OPT", "ZFAVORITE", "ZWANTTOCOOK", "ZDATE", "ZID",
        "ZTITLE", "ZYIELD", "ZPREPTIME", "ZCOOKTIME", "ZTOTALTIME", "ZLINK",
        "ZINGREDIENTS", "ZINSTRUCTIONS", "ZNUTRITION", "ZNOTES", "ZTEXT")
RECIPES = [
    # A: every field, a Meal + Thai
    (1, 2, 1, 1, 0, 780000000.0, A_ID, "Pad Thai", "4", "10 min", "20 min", "30 min",
     "https://www.example.com/x",
     "# Sauce\n2 tbsp fish sauce\n1 tbsp sugar\n\n# Noodles\n200 g rice noodles",
     "# Cook\nSoak noodles.\nFry everything.", "Calories: 500\nProtein: 20 g",
     "Best fresh.", "Nice."),
    # B: Breakfast + Snack, no link, no yield, lower-case id
    (2, 2, 1, 0, 1, 780000001.0, B_ID, "Oats", None, None, None, None, None,
     "50 g oats\n200 ml milk", "Cook 3 min.", None, None, None),
    # C: no tags, junk date
    (3, 2, 1, 0, 0, "junk", C_ID, "Bread", "", "", "", "", "", "Flour.", "Bake.",
     "", "", ""),
    # D: no ZID -> skipped
    (4, 2, 1, 0, 0, 780000002.0, None, "Ghost") + (None,) * 10,
    # E: no ZTITLE -> skipped
    (5, 2, 1, 0, 0, 780000003.0, E_ID, None) + (None,) * 10,
]
LINKS = [(1, 1), (1, 4), (2, 2), (2, 3)]


def fixture(join_sql=JOIN_STD, join_table="Z_4TAGS"):
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA + join_sql)
    con.executemany("INSERT INTO ZRECIPETAG VALUES (?,?,?,?)", TAGS)
    con.executemany("INSERT INTO ZRECIPEOBJECT VALUES (" + ",".join("?" * 18) + ")",
                    RECIPES)
    if join_table:
        con.executemany(f"INSERT INTO {join_table} VALUES (?,?)", LINKS)
    con.commit()
    return con


# ── the loader on an injected connection ───────────────────────────────────
lib = mela.load(conn=fixture())
A, B, C = (mela.by_id(i, lib.recipes) for i in (A_ID, B_ID, C_ID))

check("three recipes load", len(lib.recipes) == 3, [r.title for r in lib.recipes])
check("two rows are skipped, each with a reason",
      sorted(pk for pk, _ in lib.skipped) == [4, 5] and all(why for _, why in lib.skipped),
      lib.skipped)
check("the reasons name the column",
      any("ZID" in why for _, why in lib.skipped) and any("ZTITLE" in why for _, why in lib.skipped))
check("an injected conn has no path and no age", lib.path is None and lib.age_s is None)
check("by_id is case-insensitive", A is not None and mela.by_id(A_ID.lower(), lib.recipes) is A)
check("by_id misses cleanly",
      mela.by_id("nope", lib.recipes) is None and mela.by_id(None, []) is None)
check("ids are upper-cased on load", B is not None and B.id == B_ID.upper(), B)
check("url is the mela link", A.url == f"mela://recipe/{A_ID}", A.url)
check("categories_of sorts", mela.categories_of(A) == ["01 • Meal", "Thai"], mela.categories_of(A))
check("no categories is an empty list", C is not None and mela.categories_of(C) == [])
check("favorite / want_to_cook are booleans",
      A.favorite is True and A.want_to_cook is False and B.want_to_cook is True)
check("date is a UTC datetime",
      A.date == datetime(2025, 9, 19, 18, 40, tzinfo=timezone.utc), A.date)
check("junk ZDATE is None", C.date is None, C.date)
check("text fields are '' never None", B.link == "" and B.yield_text == "" and B.notes == "")
check("pk is kept", A.pk == 1 and B.pk == 2)

# ── meal tags ───────────────────────────────────────────────────────────────
check("meal tag: Meal -> lunch", mela.meal_tag_for(A) == "🍛lunch", mela.meal_tag_for(A))
check("meal tag: mapping order beats Snack", mela.meal_tag_for(B) == "🍳breakfast")
check("meal tag: none for an untagged recipe", mela.meal_tag_for(C) is None)
check("meal tag: a prefix-less key matches", mela.meal_tag_for(B, {"Breakfast": "x"}) == "x")
check("meal tag: custom order wins",
      mela.meal_tag_for(B, {"03 • Snack": "s", "02 • Breakfast": "b"}) == "s")
check("meal tag: casefolded", mela.meal_tag_for(B, {"SNACK": "s"}) == "s")
check("meal tag: '·' and '-' prefixes too",
      mela.meal_tag_for(mela.Recipe("X", 9, "x", categories=["04 · Dessert"]),
                        {"04 - Dessert": "d"}) == "d")
check("meal tag: a cuisine key matches exactly", mela.meal_tag_for(A, {"Thai": "t"}) == "t")
check("meal tag: empty mapping", mela.meal_tag_for(A, {}) is None)
check("DEFAULT_TAG_MAP covers the three meals",
      list(mela.DEFAULT_TAG_MAP) == ["02 • Breakfast", "01 • Meal", "03 • Snack"])

# ── rendering: the golden text follows mela2ticktick.py's rules by hand ─────
GOLDEN_A = (
    f"> 🔗 [Pad Thai](mela://recipe/{A_ID})\n"
    "> 🌐 [example.com](https://www.example.com/x)\n"
    "\n"
    "Nice.\n"
    "\n"
    "Serves: 4 · Prep: 10 min · Cook: 20 min · Total: 30 min\n"
    "## Ingredients:\n"
    "**Sauce**\n"
    "- 2 tbsp fish sauce\n"
    "- 1 tbsp sugar\n"
    "**Noodles**\n"
    "- 200 g rice noodles\n"
    "\n"
    "## Steps:\n"
    "**Cook**\n"
    "1. Soak noodles.\n"
    "2. Fry everything.\n"
    "\n"
    "## Nutrition:\n"
    "- Calories: 500\n"
    "- Protein: 20 g\n"
    "\n"
    "## Notes:\n"
    "Best fresh.\n"
)
GOLDEN_B = (
    f"> 🔗 [Oats](mela://recipe/{B_ID.upper()})\n"
    "\n"
    "## Ingredients:\n"
    "- 50 g oats\n"
    "- 200 ml milk\n"
    "\n"
    "## Steps:\n"
    "1. Cook 3 min.\n"
)
md_a, md_b = mela.render_markdown(A), mela.render_markdown(B)
check("render A equals the hand golden", md_a == GOLDEN_A, repr(md_a))
check("render B equals the hand golden", md_b == GOLDEN_B, repr(md_b))
check("render B: no site line, no Serves", "🌐" not in md_b and "Serves:" not in md_b)
check("render ends with exactly one newline",
      md_a.endswith(".\n") and not md_a.endswith("\n\n") and md_b.endswith(".\n"))
check("bullets", mela.bullets("# H\n a \n\n b") == ["**H**", "- a", "- b"],
      mela.bullets("# H\n a \n\n b"))
check("numbered runs on across headers",
      mela.numbered("# H\nx\n# J\ny") == ["**H**", "1. x", "**J**", "2. y"])
check("empty text renders nothing", mela.bullets("") == [] and mela.numbered(None) == [])

# cross-check against the reference script itself, when it is on this Mac
REF = ("/Users/vex/Library/Mobile Documents/com~apple~CloudDocs/💫 DarwOS/💼 Projects/"
       "💼 P • Scripts/mela-to-ticktick/mela2ticktick.py")
if os.path.isfile(REF):
    try:
        spec = importlib.util.spec_from_file_location("mela2ticktick", REF)
        ref = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ref)
        check("the reference script renders A identically",
              ref.to_markdown(dict(zip(COLS, RECIPES[0])), A_ID) == md_a)
        check("the reference script renders B identically",
              ref.to_markdown(dict(zip(COLS, RECIPES[1])), B_ID.upper()) == md_b)
    except Exception as e:  # noqa: BLE001 - the hand golden stands on its own
        print(f"  --  reference script not importable ({e}); hand golden stands")
else:
    print("  --  reference script not on this Mac; hand golden stands")

# ── links ───────────────────────────────────────────────────────────────────
ESCAPED = rf"\[Pad Thai\]\(mela://recipe/{A_ID.lower()}\)"
check("link_uuid unescapes and upper-cases", mela.link_uuid(ESCAPED) == A_ID,
      mela.link_uuid(ESCAPED))
check("link_uuid on a plain title", mela.link_uuid(f"[Pad Thai]({A.url})") == A_ID)
check("link_uuid: no link is None",
      mela.link_uuid("Bread") is None and mela.link_uuid(None) is None and mela.link_uuid("") is None)
check("link_uuid ignores a short id", mela.link_uuid("mela://recipe/abc") is None)
check("LINK_RE is the reference pattern",
      mela.LINK_RE.pattern == r"mela://recipe/([0-9A-Fa-f-]{36})")

# ── the join table can be renumbered by Core Data ───────────────────────────
lib2 = mela.load(conn=fixture(JOIN_MIGRATED, "Z_7TAGS"))
A2 = mela.by_id(A_ID, lib2.recipes)
check("a renumbered join table is discovered",
      A2 is not None and mela.categories_of(A2) == ["01 • Meal", "Thai"], A2)
check("... and tags still resolve",
      mela.meal_tag_for(mela.by_id(B_ID, lib2.recipes)) == "🍳breakfast")
lib3 = mela.load(conn=fixture("", None))
check("no join table at all: recipes load, uncategorised",
      len(lib3.recipes) == 3 and all(r.categories == [] for r in lib3.recipes))

# ── the snapshot, on a throwaway file ───────────────────────────────────────
TMP = tempfile.mkdtemp(prefix="test_mela-")
SAVED = (mela.DB_PATH, mela.SNAP_DIR, mela._RETRY_S)
try:
    src_dir = os.path.join(TMP, "Data")
    os.makedirs(src_dir)
    db = os.path.join(src_dir, "Curcuma.sqlite")
    con = sqlite3.connect(db)
    con.executescript(SCHEMA + JOIN_STD)
    con.executemany("INSERT INTO ZRECIPETAG VALUES (?,?,?,?)", TAGS)
    con.executemany("INSERT INTO ZRECIPEOBJECT VALUES (" + ",".join("?" * 18) + ")", RECIPES)
    con.executemany("INSERT INTO Z_4TAGS VALUES (?,?)", LINKS)
    con.commit()
    con.close()
    mela.DB_PATH, mela.SNAP_DIR, mela._RETRY_S = db, os.path.join(TMP, "snap"), 0

    check("db_present sees the file", mela.db_present())
    p1 = mela.snapshot(now=1000.0)
    check("the first call copies into SNAP_DIR/<now>-<pid>",
          os.path.isfile(p1)
          and os.path.dirname(p1) == os.path.join(mela.SNAP_DIR, f"1000-{os.getpid()}"), p1)
    cnt = sqlite3.connect(p1)
    check("the copy is a working database",
          cnt.execute("SELECT count(*) FROM ZRECIPEOBJECT").fetchone()[0] == 5)
    cnt.close()
    check("SNAP_DIR is 0700", (os.stat(mela.SNAP_DIR).st_mode & 0o777) == 0o700)
    check("stamp.json is written", os.path.isfile(os.path.join(mela.SNAP_DIR, "stamp.json")))
    p2 = mela.snapshot(now=1030.0)
    check("a second call within the TTL reuses the copy", p2 == p1, (p1, p2))
    st = os.stat(db)
    os.utime(db, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    p3 = mela.snapshot(now=1040.0)
    check("a touched source forces a new copy", p3 != p1 and os.path.isfile(p3), (p1, p3))
    p4 = mela.snapshot(now=1040.0 + mela.SNAP_TTL + 1)
    check("an expired copy is replaced", p4 != p3 and os.path.isfile(p4), (p3, p4))
    old = os.path.join(mela.SNAP_DIR, "1-1")
    os.makedirs(old)
    p5 = mela.snapshot(now=5000.0)
    check("old sibling copies are pruned, the fresh one kept",
          not os.path.exists(old) and os.path.isfile(p5) and not os.path.exists(p1), (old, p5))
    check("stamp records the copy", mela._read_stamp()["dir"] == os.path.dirname(p5))

    live = mela.load()                   # real clock: a new copy, then reused
    check("load() reads a snapshot end to end",
          len(live.recipes) == 3 and str(live.path).startswith(mela.SNAP_DIR)
          and isinstance(live.age_s, float), (live.path, live.age_s))
    check("library() is the recipe list",
          [r.title for r in mela.library()] == ["Pad Thai", "Oats", "Bread"])
    fr = mela.freshness()
    newest = datetime.fromtimestamp(780000001 + mela.APPLE_EPOCH, tz=timezone.utc).isoformat()
    check("freshness reports the newest recipe",
          fr["present"] and fr["newest_recipe_date"] == newest and fr["db_path"] == db
          and fr["age_s"] is not None, fr)

    with open(db, "wb") as f:            # a torn copy: not a database at all
        f.write(b"not a database at all")
    try:
        mela.snapshot(now=9000.0)
        check("a torn copy raises", False, "no error")
    except mela.MelaError as e:
        check("a torn copy raises MelaError after one retry", "unreadable" in str(e), str(e))
    mela.DB_PATH = os.path.join(TMP, "nowhere", "Curcuma.sqlite")
    check("db_present is False when missing", not mela.db_present())
    try:
        mela.snapshot()
        check("a missing db raises", False, "no error")
    except mela.MelaError as e:
        check("a missing db names the path", mela.DB_PATH in str(e), str(e))
    fr = mela.freshness()
    check("freshness without a db",
          fr == {"age_s": None, "newest_recipe_date": None, "db_path": mela.DB_PATH,
                 "present": False}, fr)
finally:
    mela.DB_PATH, mela.SNAP_DIR, mela._RETRY_S = SAVED
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if __name__ == "__main__":
    sys.exit(1 if FAILS else 0)
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
