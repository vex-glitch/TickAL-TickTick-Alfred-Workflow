#!/usr/bin/env python3
"""Unit suite for src/eagle.py + src/photos_bridge.py pure logic.
Run: python3 tests/test_eagle.py
Live channels (raw API / MCP plugin / Photos) are NOT exercised here -
they were probe-verified 2026-07-25 and get smoke-tested per feature.
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
import eagle  # noqa: E402
import photos_bridge  # noqa: E402

FAILS = []
COUNT = [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


# ---------------------------------------------------------- naming
BASE = "John Doe - Best Tattoo Ever"

check("item_name session",
      eagle.item_name(BASE, "S1", 3) == "John Doe - Best Tattoo Ever • S1 • 3")
check("item_name edit",
      eagle.item_name(BASE, "Edit", 1) == "John Doe - Best Tattoo Ever • Edit • 1")

names = [eagle.item_name(BASE, "S1", 1), eagle.item_name(BASE, "S1", 2),
         eagle.item_name(BASE, "S2", 1), eagle.item_name(BASE, "Edit", 7),
         "random other"]
check("next_index continues", eagle.next_index(names, BASE, "S1") == 3)
check("next_index other stage", eagle.next_index(names, BASE, "S2") == 2)
check("next_index fresh stage", eagle.next_index(names, BASE, "Design") == 1)
check("next_index respects gaps",
      eagle.next_index([eagle.item_name(BASE, "Edit", 7)], BASE, "Edit") == 8)
check("next_index ignores other base",
      eagle.next_index(["Other Guy - Rose • S1 • 9"], BASE, "S1") == 1)
check("next_index handles None names",
      eagle.next_index([None, ""], BASE, "S1") == 1)

# ------------------------------------------------------- normalize
check("normalize basic", eagle.normalize("  Erol -  Snake! ") == "erol snake")
check("normalize diacritics", eagle.normalize("Néskø") == "nesk")
check("normalize case+punct",
      eagle.normalize("JOHN_DOE-best.tattoo") == "john doe best tattoo")
check("normalize empty", eagle.normalize(None) == "")

# ----------------------------------------------------- fuzzy_match
CANDS = ["John Doe - Best Tattoo Ever", "Erol - Snake",
         "Ian - Crow Ribs", "Luka - Anubis Sleeve"]

best, score, conf = eagle.fuzzy_match("john doe best tattoo", CANDS)
check("fuzzy exact-ish hit", best == CANDS[0] and conf, f"{best} {score:.2f}")

best, score, conf = eagle.fuzzy_match("Jon Doe - Best Tatoo", CANDS)
check("fuzzy typo hit", best == CANDS[0] and conf, f"{best} {score:.2f}")

best, score, conf = eagle.fuzzy_match("erol snak", CANDS)
check("fuzzy improvised hit", best == "Erol - Snake" and conf,
      f"{best} {score:.2f}")

best, score, conf = eagle.fuzzy_match("completely unrelated words", CANDS)
check("fuzzy garbage NOT confident", not conf, f"{best} {score:.2f}")

best, score, conf = eagle.fuzzy_match("", CANDS)
check("fuzzy empty needle", best is None and not conf)

best, score, conf = eagle.fuzzy_match("erol", [])
check("fuzzy no candidates", best is None and not conf)

# identical duplicate folder names tie → pick list, never auto-file
best, score, conf = eagle.fuzzy_match("gangsta goose",
                                      ["Gangsta Goose", "Gangsta Goose"])
check("fuzzy identical dupes not confident", not conf, f"{best} {score:.2f}")

# exact needle with a suffixed sibling keeps its lead
best, score, conf = eagle.fuzzy_match("Fox", ["Fox", "Fox 2"])
check("fuzzy exact beats suffixed sibling", best == "Fox" and conf,
      f"{best} {score:.2f}")

# ------------------------------------------------- closed-lib disk
TMP = tempfile.mkdtemp(prefix="eagletest_")
LIB = os.path.join(TMP, "Test.library")
os.makedirs(os.path.join(LIB, "images"))

TREE = [{"id": "ROOT1", "name": "Customers", "children": [
            {"id": "TAT1", "name": "John Doe - Best Tattoo Ever", "children": [
                {"id": "SUB1", "name": "04 Sessions", "children": []}]}]},
        {"id": "ARCH", "name": "Archive", "children": []}]
with open(os.path.join(LIB, "metadata.json"), "w") as f:
    json.dump({"folders": TREE}, f)


def mk_item(iid, name, ext, folders, deleted=False, realfile=True):
    d = os.path.join(LIB, "images", f"{iid}.info")
    os.makedirs(d)
    with open(os.path.join(d, "metadata.json"), "w") as f:
        json.dump({"id": iid, "name": name, "ext": ext, "folders": folders,
                   "tags": ["x"], "isDeleted": deleted}, f)
    if realfile:
        with open(os.path.join(d, f"{name}.{ext}"), "w") as f:
            f.write("data")


mk_item("I1", "John Doe - Best Tattoo Ever • S1 • 1", "jpg", ["SUB1"])
mk_item("I2", "John Doe - Best Tattoo Ever • S1 • 2", "jpg", ["TAT1"])
mk_item("I3", "elsewhere", "png", ["ARCH"])
mk_item("I4", "deleted one", "png", ["SUB1"], deleted=True)
mk_item("I5", "odd disk name", "png", ["SUB1"], realfile=False)
# I5: metadata name mismatch - drop a differently named media file
with open(os.path.join(LIB, "images", "I5.info", "actual.png"), "w") as f:
    f.write("data")

tree = eagle.disk_folder_tree(LIB)
check("disk tree read", tree[0]["name"] == "Customers")

root, ids = eagle.disk_subtree_ids(LIB, "TAT1")
check("subtree root", root["name"] == "John Doe - Best Tattoo Ever")
check("subtree ids", set(ids) == {"TAT1", "SUB1"})

items = eagle.disk_items_in(LIB, ids)
got = {i["id"] for i in items}
check("disk items scoped", got == {"I1", "I2", "I5"}, str(got))
check("deleted skipped", "I4" not in got)
i1 = next(i for i in items if i["id"] == "I1")
check("disk item path real", i1["path"] and os.path.exists(i1["path"]))
i5 = next(i for i in items if i["id"] == "I5")
check("mismatched filename fallback",
      i5["path"] and i5["path"].endswith("actual.png"), str(i5["path"]))

try:
    eagle.disk_subtree_ids(LIB, "NOPE")
    check("missing folder raises", False)
except eagle.EagleError:
    check("missing folder raises", True)

# ------------------------------------------- photos primary file
P = os.path.join(TMP, "exp1")
os.makedirs(P)
for f in ("IMG_1.HEIC", "IMG_1.MOV"):
    open(os.path.join(P, f), "w").write("x")
check("live photo pair → still",
      photos_bridge._primary_file(P).endswith("IMG_1.HEIC"))

P2 = os.path.join(TMP, "exp2")
os.makedirs(P2)
open(os.path.join(P2, "clip.mov"), "w").write("x")
check("lone video → video", photos_bridge._primary_file(P2).endswith("clip.mov"))

P3 = os.path.join(TMP, "exp3")
os.makedirs(P3)
check("empty export dir → None", photos_bridge._primary_file(P3) is None)
check("missing dir → None", photos_bridge._primary_file(P3 + "zzz") is None)

# intake constants sanity
check("intake tv path",
      eagle.INTAKE["tv"].endswith("Eagle Inbox TV"))
check("skeleton six", len(eagle.SKELETON) == 6
      and eagle.SKELETON[3] == "04 Sessions")

shutil.rmtree(TMP)

print(f"\n{COUNT[0]} checks, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
