#!/usr/bin/env python3
"""The 🥘 screens (Scripts/browse.py ctx:meal / mealq / mealw / meallib /
mealgroc / mealrate / mealprice) rendered against a FAKE cache in a temp
dir, no network, no Mela, no Calendar store, no price book on disk:
meal_write.plan_view, meal_write.hub_counts, mela_cal.plan, mela.library
and meal_price.load_book are stubbed, the routine's list is planted as the
meal_kids snapshot so the live read never fires, and meal_write.week_lists
is the REAL one over the planted pool.

What it pins (the traps that burned the other hubs):
  * every row spells out all six chords as fresh dicts, no xact: on ⌘ or ⌥,
    ⌘ dead on anything that is not a library task, task rows carry the full
    variable set
  * THE MEAL ROW: ⏎ open:mela://recipe, ⇧ open:<web> (dead "No web page"
    without a link), ⌥⌘ copy:mela://recipe, ⌥ dead on plan rows, ⌥⇧ =
    xact:meal_cooked {pid, tid, back = the screen's own ctx} on a row with
    a library task and dead ("No library task") without one; the legend
    says ⌥⇧👨‍🍳
  * the chips: a plan row of a 👨‍🍳cooked-tagged, rated entry says
    "👨‍🍳 cooked · ⭐️⭐️⭐️"; the library chip says "cooked before · ⭐️⭐️⭐️"
    for a tag-only entry with no calendar past, and never-cooked rows
    sort before it (tag-only after never, before the dated ones)
  * ctx:mealrate:<pid>:<tid>[:<back…>] = the ⭐️ picker: dead head + the
    comments already there, five star rows (⏎ and ⌥⇧ the same
    xact:meal_rate payload, the current one marked), 🚫 No rating (dead
    when unrated, stars 0 when rated), back = the trailing ids re-joined
    or ctx:meal; an unknown task = one dead row; sealed like every screen
  * the hub reads the cook week off the calendar plan anchored on the
    ROUTINE's cook Sunday; 🎲 Plan / 📥 Import / 📝 Fill are gone, 🔄 Sync is
    the one verb (⏎ and ⌥⇧ the same xact:meal_sync payload)
  * ctx:mealq = 13 weeks, this week starred, empty weeks dead
  * THE 🛒 ROW: the hub's 🛒 Groceries row ⌥⇧ = xact:meal_portions
    {all: true, back: ctx:meal} ("asks per list"), live with an open list,
    dead with none; a ctx:mealgroc row's ⌥⇧ = the same verb on THAT list
    {pid, tid, back: ctx:mealgroc}, its chip "· 7 portions" and the chord's
    "now 7" read off the yield note in the content, both missing (never
    wrong) on a list saved without one; the legends say ⌥⇧🔢, the head
    says "cut to 7 portions · ⌥⇧ re-cuts one"; still no xact on ⌘ or ⌥
  * THE 🏷 ROW: the hub's 🏷 Prices row sits right after 🛒, sums the
    week's lists off their cost lines ("nothing priced yet" without one,
    "≈ 1.75 € this week · 1 unpriced" with a planted one), ⏎ the
    trampoline to ctx:mealprice, ⌥ by variable, ⌥⇧ = xact:meal_prices
    {back: ctx:meal} (the one road to knuspr.de), the subtitle counts the
    book; a ctx:mealgroc chip gains " · ≈ 1.75 €" after the portions
    chip and a list without a cost line keeps its chip as it was
  * ctx:mealprice[:<back…>] = the price book: a dead head (entries, the
    week's holes, the book date or never), the week's keys unpriced FIRST
    (❓, searched as the default term), then priced (🧾 knuspr / ✍️ manual
    with the €/kg and the product), then the rest of the book (📖); a
    suffixed item title keys clean (rice, never "rice 1 75"); every key
    row ⏎ = xact:meal_price_set and ⌥⇧ = xact:meal_price_search {key,
    back: THIS ctx}, ⌥⌘ copies the knuspr page when there is one and is
    dead without, ⌘ ⌥ ⇧ ⌘⇧ dead; back = the trailing ids or ctx:meal; the
    bar filters on key + product; the book is read once a render; no
    lists + an empty book = the head and one dead row
  * typing "today" on a meal screen never jumps away (parse_ctx guard)
  * the Routines hub carries the zero-canvas door
  * the real ~/.ticktick_alfred/meal_prices.json is never written
  * THE TILL (2026-09-23, D27, "Let's do what you pay at the till
    please."): the hub's 🏷 row says "≈ 1.75 € used · till ≈ 5.97 €" (the
    used figure off the cost lines, the till pooled once across the
    week's lists off the book: 500 g + 200 g of rice = ONE 1 kg pack),
    "· N unpriced" after, "pantry 3.98 € of the till · " in front of the
    subtitle when a staple is in it, "till ≈ 1.99 €" alone on a list cut
    before the book existed (the book prices its bacon, no cost line says
    what it uses), "nothing priced yet" with neither; a ctx:mealgroc chip
    reads " · ≈ 0.70 € · till 3.49 €" off a D27 cost line and keeps its
    old shape on a pre-D27 one; a pantry entry's book row wears " · pantry"
    (rice, salt, flour by the default list; a ❓ soy sauce hole too; a
    bare {key, pantry: false} entry and an entry's own flag win over the
    list), the head says the price box takes pantry / not pantry

    python3 tests/test_meal_screens.py
"""
import base64
import json
import os
import re
import sys
import tempfile
import time
from collections import namedtuple
from datetime import date, timedelta
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
TMP = tempfile.mkdtemp(prefix="tickal-meals-")
LIST, RLIST, RID = "5eed00000000000000000a01", "5eed00000000000000000b01", "5eed00000000000000000b02"
os.environ["meal_list_id"] = LIST
os.environ["meal_routine_id"] = RID
os.environ.pop("browse_ctx", None)
os.environ.pop("browse_back", None)
import cache as cache_store                    # noqa: E402
cache_store.CACHE_DIR = os.path.join(TMP, "cache")
os.makedirs(cache_store.CACHE_DIR)
import meal                                    # noqa: E402
import meal_write as mw                        # noqa: E402
import mela                                    # noqa: E402
import mela_cal                                # noqa: E402
import meal_price as mp                        # noqa: E402
import browse                                  # noqa: E402

REAL_BOOK = os.path.expanduser("~/.ticktick_alfred/meal_prices.json")
HAD_BOOK = os.path.exists(REAL_BOOK)
mp.BOOK_PATH = os.path.join(TMP, "meal_prices.json")   # the temp path wins even unstubbed

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


U1 = "A84938FE-88F9-467C-9D01-745D92E75EE1"
U2 = "62946285-B1C4-4A50-BB17-6CA9B1417EA3"
U3 = "7EB6A2B6-0C98-4B8A-B10F-86E0C3CCA3D3"
U4 = "44444444-4444-4444-4444-444444444444"
U5 = "55555555-5555-5555-5555-555555555555"      # planned, unknown to Mela
U6 = "66666666-6666-6666-6666-666666666666"      # cooked by the TAG alone, rated
TODAY = date.today()
SUN = meal.next_sunday(TODAY)                  # the routine's cook Sunday (what 🔄 mirrors)
WK = meal.cook_week_of(TODAY)                  # THIS week's cook Sunday: the hub's anchor


def COOK(s):
    return ("cooked" if s < TODAY else "cook") + f" {s:%a %-d %b}"

HORIZON = 13
if not hasattr(mw, "HORIZON_WEEKS"):           # until the meal_write group lands
    mw.HORIZON_WEEKS = HORIZON


def T(tid, title, pid=LIST, tags=(), status=0, parent=None, **kw):
    t = {"id": tid, "projectId": pid, "_projectId": pid, "title": title, "tags": list(tags),
         "status": status, "parentId": parent, "content": "", "kind": "TEXT", "columnId": ""}
    t.update(kw)
    return t


# Oats: planned this week AND tagged 👨‍🍳cooked, rated ⭐️⭐️⭐️ under its links
# (the hub chip); Kimchi Stew: cooked by the tag ALONE, no calendar past,
# rated with two comments (the library chip, the ⭐️ picker)
OATS_DESC = (f"> 🔗 [Oats](mela://recipe/{U2})\n> 🌐 [oats.example](https://oats.example/recipe)\n"
             "> ⭐️⭐️⭐️\n\nServes: 4\n## Ingredients:\n- oats\n")
KIMCHI_DESC = (f"> 🔗 [Kimchi Stew](mela://recipe/{U6})\n> ⭐️⭐️⭐️\n> less salt next time\n"
               "> more chili\n\nServes: 4\n")
LIB = [T("t1", f"[Oats](mela://recipe/{U2})", tags=["🍳breakfast", "👨‍🍳cooked"], content=OATS_DESC),
       T("t2", f"[Beef Bulgogi](mela://recipe/{U1})", tags=["🍛lunch"], content="body"),
       T("t3", f"[Pockets](mela://recipe/{U3})", tags=["🌮snack"]),
       T("t4", f"[Second Lunch](mela://recipe/{U4})", tags=["🍛lunch"]),
       T("t5", f"[Kimchi Stew](mela://recipe/{U6})", tags=["🍛lunch", "👨‍🍳Cooked"], content=KIMCHI_DESC),
       T("g1", meal.grocery_title("Oats", U2), tags=["🛒groceries"], kind="CHECKLIST",
         dueDate="2026-09-26T00:00:00+0000",
         items=[{"title": "350 g bacon", "status": 2}, {"title": "2 eggs", "status": 0}],
         content="Scaled ×1.75: 4 → 7 portions\n_(yield: '4' in yield)_")]
# a second list as the very first sync saved them: EMPTY content, no yield note
G2 = T("g2", meal.grocery_title("Pockets", U3), tags=["🛒groceries"], kind="CHECKLIST",
       items=[{"title": "x", "status": 0}])
# a third list as a PRICED sync saves them: the cost line first in the
# content, a priced line suffixed, a manual salt, a hole (thighs by the
# piece against nothing in the book); sortOrder puts it first in the week
G3 = T("g3", meal.grocery_title("Beef Bulgogi", U1), tags=["🛒groceries"], kind="CHECKLIST",
       sortOrder=-10,
       items=[{"title": "500 g rice · ≈ 1.75 €", "status": 0}, {"title": "1 tsp salt", "status": 0},
              {"title": "3 chicken thighs", "status": 0}],
       content="≈ 1.75 € · 0.25 €/portion · 1 unpriced\nScaled ×1.75: 4 → 7 portions\n_(yield: '4' in yield)_")
# a fourth list as a D27 sync saves them: the till chip on the cost line;
# more rice (pooled with G3's into the same 1 kg pack at the hub) and a
# pantry hole (soy sauce: no entry, but the default list knows it)
G4 = T("g4", meal.grocery_title("Second Lunch", U4), tags=["🛒groceries"], kind="CHECKLIST",
       sortOrder=-5,
       items=[{"title": "200 g rice · ≈ 0.70 €", "status": 0}, {"title": "1 tbsp soy sauce", "status": 0}],
       content="≈ 0.70 € · 0.10 €/portion · till ≈ 3.49 € · 1 unpriced\nScaled ×1.75: 4 → 7 portions\n_(yield: '4' in yield)_")


def E(key, product, pack, price, per, url="", search=None, source="knuspr", date="2026-09-22"):
    return {"key": key, "search": search or product, "product": product, "product_id": hash(key) & 0xffff,
            "pack": pack, "pack_amount": 1000, "pack_unit": "g", "price": price, "per": per,
            "per_unit": "g", "source": source, "date": date, "pinned": False, "url": url}


# the fake book: two knuspr entries on this week's lists, a manual salt,
# and flour that no list wants (the 📖 row); load_book hands out a COPY
BOOK = {"version": 1, "updated": "2026-09-22", "entries": {
    "bacon": E("bacon", "Tulip Bacon", "150 g", 1.99, 0.01327, "https://www.knuspr.de/tulip-bacon", search="Bacon"),
    "rice": E("rice", "Basmati Reis", "1 kg", 3.49, 0.00349, "https://www.knuspr.de/basmati-reis"),
    "salt": {"key": "salt", "product": "", "pack": "1 kg", "pack_amount": 1000, "pack_unit": "g",
             "price": 0.49, "per": 0.00049, "per_unit": "g", "source": "manual", "date": "2026-09-20", "url": ""},
    "flour": E("flour", "Mehl Type 405", "1 kg", 0.89, 0.00089, "https://www.knuspr.de/mehl-405", search="Mehl")}}
LOADS = [0]


def fake_load_book(path=None):
    LOADS[0] += 1
    return json.loads(json.dumps(BOOK))


mp.load_book = fake_load_book

# stand-ins for what the price groups add beside this one (installed only
# while missing, the HORIZON_WEEKS pattern): the cost-line reader and the
# week's sum off the cached lists. The fake week_cost parses the line
# itself so its answer never rides the reader's shape.
ROUTINE = T(RID, "🥘 Meal Prep", pid=RLIST, startDate=f"{SUN.isoformat()}T17:00:00.000+0000")
PTR = T("p1", meal.pointer_title("b", "Oats", U2), pid=RLIST, parent=RID)


def R(uid, title, cats, link=""):
    return SimpleNamespace(id=uid, title=title, categories=list(cats), link=link)


RECIPES = {U2: R(U2, "Oats", ["02 • Breakfast"], "https://oats.example/recipe"),
           U1: R(U1, "Beef Bulgogi", ["01 • Meal"]),
           U3: R(U3, "Pockets", ["03 • Snack"], "https://pockets.example"),
           U4: R(U4, "Second Lunch", ["01 • Meal"], "https://second.example")}


def P(day, uuid, title):
    return SimpleNamespace(date=day, uuid=uuid, title=title, start=None, all_day=False)


# the calendar: this cook week has a breakfast, a lunch and a recipe Mela
# does not know (dropped on the Monday, still this week); Pockets in two
# weeks; Bulgogi cooked two cook-weeks before today's
PLANNED = [P(SUN, U2, "Oats"), P(SUN, U1, "Beef Bulgogi"), P(SUN, U5, "Mystery Pie"),
           P(SUN + timedelta(days=14), U3, "Pockets"),
           P(meal.cook_week_of(TODAY) - timedelta(days=14), U1, "Beef Bulgogi")]
CALLS = []
ERROR = [""]


def fake_plan_view(today=None, n_weeks=HORIZON, planned=None, recipes=None, tasks=None, first_sunday=None):
    CALLS.append((today, n_weeks, first_sunday))
    first = meal.cook_week_of(first_sunday) if first_sunday else meal.next_sunday(today or TODAY)
    if ERROR[0]:
        return {"weeks": [], "first_sunday": first, "planned_count": 0, "error": ERROR[0]}
    entries = meal.library_entries(LIB, LIST)
    return {"weeks": meal.weeks_plan(PLANNED, RECIPES, None, entries, first, n_weeks),
            "first_sunday": first, "planned_count": len(PLANNED), "error": "",
            "planned": list(PLANNED), "by_id": RECIPES, "entries": entries, "tag_map": None}


mw.plan_view = fake_plan_view
mw.hub_counts = lambda: {"new": 2, "missing": 14, "uncategorised": 1, "mela_ok": True,
                         "mela_age_s": 240, "mela_error": None, "list_id": LIST}
mela_cal.plan = lambda since=None, until=None, path=None, now=None: [
    p for p in PLANNED if (since is None or p.date >= since) and (until is None or p.date <= until)]
mela.library = lambda path=None: list(RECIPES.values())


def plant(kids=(PTR,), lib=None):
    lib = LIB if lib is None else list(lib)
    rl = [ROUTINE] + list(kids)
    cache_store.set("all_tasks", lib + rl)
    cache_store.set("projects", [{"id": LIST, "name": "🍳Meal Prep"}, {"id": RLIST, "name": "🌅 Routines"}])
    cache_store.set(f"project_data_{LIST}", {"project": {"id": LIST}, "tasks": lib})
    cache_store.set(f"project_data_{RLIST}", {"project": {"id": RLIST}, "tasks": rl})
    cache_store.set("meal_kids", {"rid": RID, "ts": time.time(), "routine": ROUTINE, "tasks": rl})


def render(ctx, query=""):
    os.environ["browse_ctx"] = ctx
    level, ids, q = browse.parse_ctx(query)
    os.environ.pop("browse_ctx", None)
    return level, ids, q


def rows_for(ctx, query=""):
    level, ids, q = render(ctx, query)
    fn = {"meal": lambda: browse.render_meal(ids, q),
          "mealq": lambda: browse.render_mealq(ids, q),
          "mealw": lambda: browse.render_mealw(ids, q),
          "meallib": lambda: browse.render_meallib(ids, q),
          "mealgroc": lambda: browse.render_mealgroc(q),
          "mealrate": lambda: browse.render_mealrate(ids, q),
          "mealprice": lambda: browse.render_mealprice(ids, q)}[level]
    return fn()


def by_uid(rows):
    return {r.get("uid"): r for r in rows}


def sealed(rows, where):
    """The six-chord + ⌘-dead-on-non-task invariants (test_okr_screens)."""
    ok = True
    for r in rows:
        mods = r.get("mods") or {}
        for k in browse._OKR_CHORDS:
            if k not in mods:
                check(f"{where}: {r.get('uid')} missing chord {k}", False)
                ok = False
        for k in ("cmd", "alt"):
            if (mods.get(k) or {}).get("arg", "").startswith("xact:"):
                check(f"{where}: {r.get('uid')} xact on {k}", False)
                ok = False
        v = r.get("variables") or {}
        if not v.get("task_id") and (mods.get("cmd") or {}).get("valid"):
            check(f"{where}: {r.get('uid')} ⌘ live on a non-task row", False)
            ok = False
        if v.get("task_id") and set(v) < {"task_id", "task_list_id", "list_id", "section_id", "task_title", "item_type"}:
            check(f"{where}: {r.get('uid')} task row lacks the full variable set", False)
            ok = False
    ids = [id(r.get("mods", {}).get("cmd")) for r in rows]
    if len(ids) != len(set(ids)):
        check(f"{where}: rows share a mods dict", False)
        ok = False
    return ok


def payload(row):
    arg = row.get("arg") or ""
    return json.loads(base64.b64decode(arg.split(":", 2)[2]))


def mod_payload(mod):
    return json.loads(base64.b64decode((mod.get("arg") or "").split(":", 2)[2]))


def meal_row_ok(r, uuid, web, where, tid=None, back="ctx:meal"):
    """THE MEAL ROW's chords. `tid` = the library task behind the meal (⌥⇧
    then fires xact:meal_cooked on it, `back` in the payload), None = no
    library task, ⌥⇧ dead."""
    m = r["mods"]
    check(f"{where}: ⏎ opens the recipe in Mela", r["arg"] == f"open:mela://recipe/{uuid}" and r["valid"], r["arg"])
    if web:
        check(f"{where}: ⇧ opens the web page", m["shift"]["arg"] == f"open:{web}" and m["shift"]["valid"], m["shift"])
    else:
        check(f"{where}: ⇧ dead without a web page", m["shift"]["arg"] == "" and not m["shift"]["valid"]
              and m["shift"]["subtitle"] == "No web page", m["shift"])
    check(f"{where}: ⌥⌘ copies the Mela link", m["alt+cmd"]["arg"] == f"copy:mela://recipe/{uuid}" and m["alt+cmd"]["valid"])
    if tid:
        check(f"{where}: ⌥⇧ = xact:meal_cooked on the library task, back = the screen",
              m["alt+shift"]["arg"].startswith("xact:meal_cooked:") and m["alt+shift"]["valid"]
              and mod_payload(m["alt+shift"]) == {"pid": LIST, "tid": tid, "back": back}
              and "Cooked" in m["alt+shift"]["subtitle"], m["alt+shift"])
    else:
        check(f"{where}: ⌥⇧ dead without a library task", not m["alt+shift"]["valid"] and m["alt+shift"]["arg"] == ""
              and m["alt+shift"]["subtitle"] == "No library task", m["alt+shift"])
    check(f"{where}: the legend says ⌥⇧👨‍🍳", "⌥⇧👨‍🍳" in r["subtitle"], r["subtitle"])


# ── the hub root ──────────────────────────────────────────────────────────────
plant()
CALLS.clear()
rows = rows_for("ctx:meal")
r = by_uid(rows)
uids = [x["uid"] for x in rows]
check("hub: sealed", sealed(rows, "hub"))
check("hub: plan_view anchored on THIS week's cook Sunday (first_sunday), the full horizon",
      CALLS and CALLS[-1] == (TODAY, HORIZON, WK), CALLS)
check("hub: head = the BATCH: the upcoming prep task's day · 3 meals, dead",
      r["meal-head"]["title"] == f"🥘 {COOK(SUN)} · 3 meals" and f"{meal.week_label(WK)} · groceries" in r["meal-head"]["subtitle"]
      and not r["meal-head"]["valid"], (r["meal-head"]["title"], r["meal-head"]["subtitle"]))
check("hub: rows in order (b, l, x), then 📆 🔄 🛒 🏷 📚×3 ℹ️",
      uids == ["meal-head", f"meal-b-{U2[:8]}", f"meal-l-{U1[:8]}", f"meal-x-{U5[:8]}", "meal-next", "meal-sync",
               "meal-groc", "meal-price", "meal-lib-b", "meal-lib-l", "meal-lib-s", "meal-status"], uids)
check("hub: the retired rows are gone",
      not any(u in r for u in ("meal-plan", "meal-import", "meal-fill", "meal-b", "meal-l", "meal-s")))
b = r[f"meal-b-{U2[:8]}"]
check("hub: breakfast title carries the glyph and the planned day",
      b["title"] == f"🍳 Oats · {SUN:%a %-d %b}", b["title"])
meal_row_ok(b, U2, "https://oats.example/recipe", "hub breakfast", tid="t1", back="ctx:meal")
check("hub: the chip of a 👨‍🍳cooked-tagged, rated entry says the word and the stars",
      b["subtitle"].startswith("Breakfast · 👨‍🍳 cooked · ⭐️⭐️⭐️  |  "), b["subtitle"])
check("hub: the chip is stamped once (no second 'cooked', no second stars run)",
      b["subtitle"].count("cooked") == 2 and b["subtitle"].count("⭐️⭐️⭐️") == 1, b["subtitle"])
check("hub: ⌘ live on a meal with a library task, the task variables ride",
      b["mods"]["cmd"]["valid"] and b["variables"]["task_id"] == "t1" and b["variables"]["task_list_id"] == LIST
      and b["variables"]["item_type"] == "task" and "Oats" in b["variables"]["task_title"], b["variables"])
check("hub: ⌥ dead on a plan row", not b["mods"]["alt"]["valid"] and b["mods"]["alt"]["arg"] == "")
l = r[f"meal-l-{U1[:8]}"]
meal_row_ok(l, U1, "", "hub lunch", tid="t2", back="ctx:meal")
check("hub: an untagged, unrated entry's chip is the bare slot", l["subtitle"].startswith("Lunch  |  "), l["subtitle"])
x = r[f"meal-x-{U5[:8]}"]
check("hub: a recipe Mela does not know is a 🍽️ row named after the event, ⌘ dead, no task id",
      x["title"].startswith("🍽️ Mystery Pie") and x["arg"] == f"open:mela://recipe/{U5}"
      and not x["mods"]["cmd"]["valid"] and not x["variables"].get("task_id"), x)
meal_row_ok(x, U5, "", "hub mystery pie", tid=None)
check("hub: 📆 row → ctx:mealq by trampoline, ⌥ by variable, counts the calendar",
      r["meal-next"]["arg"] == "xact:crmbrowse:ctx:mealq" and r["meal-next"]["mods"]["alt"]["variables"]["browse_ctx"] == "ctx:mealq"
      and r["meal-next"]["title"] == f"📆 Next {HORIZON} weeks" and "5 planned meals" in r["meal-next"]["subtitle"], r["meal-next"])
s = r["meal-sync"]
check("hub: 🔄 row = xact:meal_sync with the back payload, ⌥⇧ the same verb, counts new + to fill",
      s["arg"].startswith("xact:meal_sync:") and payload(s) == {"back": "ctx:meal"} and s["valid"]
      and s["mods"]["alt+shift"]["arg"] == s["arg"] and s["title"] == "🔄 Sync with Mela · 2 new · 14 to fill"
      and "onto the prep task + groceries + note" in s["subtitle"], s)
check("hub: 🔄 never on ⌘ or ⌥", not s["mods"]["cmd"]["valid"] and not s["mods"]["alt"]["valid"])
g = r["meal-groc"]
check("hub: groceries row counts, ⏎ the trampoline, ⌥ by variable",
      "1 open list" in g["title"] and g["arg"] == "xact:crmbrowse:ctx:mealgroc"
      and g["mods"]["alt"]["variables"]["browse_ctx"] == "ctx:mealgroc", g)
check("hub: 🛒 ⌥⇧ = xact:meal_portions {all, back: ctx:meal}, live with an open list, asks per list",
      g["mods"]["alt+shift"]["arg"].startswith("xact:meal_portions:") and g["mods"]["alt+shift"]["valid"]
      and mod_payload(g["mods"]["alt+shift"]) == meal.portions_payload(back="ctx:meal") == {"all": True, "back": "ctx:meal"}
      and g["mods"]["alt+shift"]["subtitle"] == "🔢 Portions… (asks per list)", g["mods"]["alt+shift"])
check("hub: 🛒 legend says ⏎⤵️  ⌥⤵️  ⌥⇧🔢", g["subtitle"].endswith("  |  ⏎⤵️  ⌥⤵️  ⌥⇧🔢"), g["subtitle"])
check("hub: 🛒 never an xact on ⌘ or ⌥", not g["mods"]["cmd"]["valid"] and not g["mods"]["alt"]["arg"])
p = r["meal-price"]
check("hub: 🏷 sits right after 🛒", uids[uids.index("meal-groc") + 1] == "meal-price", uids)
# D27 changed this pin on purpose: g1 was cut before the book existed (no
# cost line, so no used figure) but the book prices its 350 g of bacon at
# the till (one 1 kg pack, 1.99), and the till is read off the book, not
# off the cost line; no unpriced count because no line was ever costed
check("hub: 🏷 with no cost line on any list says the till alone (the book prices the bacon), no used figure, no unpriced count",
      p["title"] == "🏷 Prices · till ≈ 1.99 €", p["title"])
check("hub: 🏷 subtitle = knuspr.de speculation · the book's size · ⌥⇧ refresh · the legend (no pantry chip: bacon is not a staple)",
      p["subtitle"] == "knuspr.de speculation · book 4 entries · ⌥⇧ refresh (≈ 0.5 s a key)  |  ⏎⤵️  ⌥⤵️  ⌥⇧🏷",
      p["subtitle"])
check("hub: 🏷 ⏎ the trampoline to ctx:mealprice, ⌥ by variable",
      p["arg"] == "xact:crmbrowse:ctx:mealprice" and p["valid"]
      and p["mods"]["alt"]["variables"]["browse_ctx"] == "ctx:mealprice" and p["mods"]["alt"]["valid"], p)
check("hub: 🏷 ⌥⇧ = xact:meal_prices {back: ctx:meal}, the one road to knuspr.de",
      p["mods"]["alt+shift"]["arg"].startswith("xact:meal_prices:") and p["mods"]["alt+shift"]["valid"]
      and mod_payload(p["mods"]["alt+shift"]) == {"back": "ctx:meal"}
      and "knuspr" in p["mods"]["alt+shift"]["subtitle"], p["mods"]["alt+shift"])
check("hub: 🏷 never an xact on ⌘ or ⌥, ⇧ and ⌥⌘ dead",
      not p["mods"]["cmd"]["valid"] and not p["mods"]["alt"]["arg"]
      and not p["mods"]["shift"]["valid"] and not p["mods"]["alt+cmd"]["valid"], p["mods"])
plant(lib=LIB + [G3])
pp = by_uid(rows_for("ctx:meal"))["meal-price"]
# used = the planted cost line (1.75, the noteless g1 adds nothing); till =
# rice 1 pack 3.49 + salt 1 pack 0.49 + bacon 1 pack 1.99 = 5.97, of which
# rice and salt are pantry staples (3.98)
check("hub: 🏷 says used off the cost line and the till off the book: ≈ 1.75 € used · till ≈ 5.97 € · 1 unpriced",
      pp["title"] == "🏷 Prices · ≈ 1.75 € used · till ≈ 5.97 € · 1 unpriced", pp["title"])
check("hub: 🏷 subtitle leads with the pantry share of the till",
      pp["subtitle"] == "pantry 3.98 € of the till · knuspr.de speculation · book 4 entries · ⌥⇧ refresh (≈ 0.5 s a key)  |  ⏎⤵️  ⌥⤵️  ⌥⇧🏷",
      pp["subtitle"])
plant(lib=LIB + [G3, G4])
pp = by_uid(rows_for("ctx:meal"))["meal-price"]
check("hub: 🏷 pools the till ONCE across the week: G3's 500 g + G4's 200 g of rice = one 1 kg pack, used summed, holes summed",
      pp["title"] == "🏷 Prices · ≈ 2.45 € used · till ≈ 5.97 € · 2 unpriced"
      and pp["subtitle"].startswith("pantry 3.98 € of the till · "), (pp["title"], pp["subtitle"]))
plant()
plant(lib=[t for t in LIB if t["id"] != "g1"])
g0 = by_uid(rows_for("ctx:meal"))["meal-groc"]
check("hub: 🛒 ⌥⇧ dead with no open list, the row itself still opens the screen",
      "0 open lists" in g0["title"] and not g0["mods"]["alt+shift"]["valid"] and g0["valid"]
      and g0["arg"] == "xact:crmbrowse:ctx:mealgroc", g0)
plant()
check("hub: library rows", r["meal-lib-l"]["arg"] == "xact:crmbrowse:ctx:meallib:lunch" and "Lunches · 3" in r["meal-lib-l"]["title"])
check("hub: status row = Mela age · calendar count", r["meal-status"]["title"] == "ℹ️ Mela data 4 min old · calendar: 5 planned meals"
      and "5 recipes" in r["meal-status"]["subtitle"] and not r["meal-status"]["valid"], r["meal-status"]["title"])
check("hub: ⌃ backs to the folders", all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:folders" for x in rows))
ERROR[0] = "Calendar store unreadable · give Alfred Full Disk Access (System Settings › Privacy › Full Disk Access)"
r2 = by_uid(rows_for("ctx:meal"))
check("hub: plan_view error → head wears the cache chip, says nothing planned, status shows the line",
      "nothing planned in Mela" in r2["meal-head"]["title"] and r2["meal-head"]["title"].endswith("· cache") and r2["meal-status"]["title"] == f"ℹ️ {ERROR[0]}"
      and not any(u.startswith("meal-b-") for u in r2), r2["meal-head"]["title"])
ERROR[0] = ""
saved = PLANNED[:]
del PLANNED[:3]
r3 = by_uid(rows_for("ctx:meal"))
check("hub: nothing planned this week → head says so, no meal rows, the rest stays",
      "nothing planned in Mela" in r3["meal-head"]["title"] and "meal-next" in r3 and "meal-sync" in r3
      and not any(u.startswith(("meal-b-", "meal-l-", "meal-x-")) for u in r3), list(r3))
PLANNED[:] = saved
rq = rows_for("ctx:meal", "grocer")
check("hub: a typed bar filters the rows", [x["uid"] for x in rq] == ["meal-groc"], [x["uid"] for x in rq])
os.environ["meal_list_id"] = ""
ro = rows_for("ctx:meal")
check("hub: blank list id = off row", len(ro) == 1 and ro[0]["uid"] == "meal-off" and not ro[0]["valid"])
os.environ["meal_list_id"] = LIST

# ── parse_ctx guard ───────────────────────────────────────────────────────────
plant()
check("parse_ctx: 'today' typed on the quarter stays put", render("ctx:mealq", "today") == ("mealq", [], "today"))
check("parse_ctx: 'inbox' on the hub stays put", render("ctx:meal", "inbox") == ("meal", [], "inbox"))
check("parse_ctx: a week ctx carries its Sunday", render("ctx:mealw:2026-10-04") == ("mealw", ["2026-10-04"], ""))
os.environ["browse_ctx"] = "ctx:countdowns"
check("parse_ctx: elsewhere the alias still works", browse.parse_ctx("today")[0] == "smart")
os.environ.pop("browse_ctx", None)

# ── the quarter ───────────────────────────────────────────────────────────────
rows = rows_for("ctx:mealq")
r = by_uid(rows)
check("quarter: sealed", sealed(rows, "quarter"))
check("quarter: 13 rows, one per cook Sunday from this week's",
      [x["uid"] for x in rows] == [f"mq-{(WK + timedelta(days=7 * i)).isoformat()}" for i in range(HORIZON)], [x["uid"] for x in rows])
BW = meal.cook_week_of(SUN)                    # the batch's week
w0 = r[f"mq-{WK.isoformat()}"]
check("quarter: this week starred", w0["title"].startswith("⭐️ ") and not w0["mods"]["cmd"]["valid"], w0["title"])
wb = r[f"mq-{BW.isoformat()}"]
check("quarter: the batch week lists its meals, ⏎ trampoline to the week, ⌥ by variable, ⌘ dead",
      wb["title"].endswith(f"{meal.week_label(BW)} · 🍳 Oats · 🍛 Beef Bulgogi · 🍽️ Mystery Pie") and wb["valid"]
      and wb["arg"] == f"xact:crmbrowse:ctx:mealw:{BW.isoformat()}"
      and wb["mods"]["alt"]["variables"]["browse_ctx"] == f"ctx:mealw:{BW.isoformat()}"
      and not wb["mods"]["cmd"]["valid"], wb)
EW = WK + timedelta(days=35)                   # a week with nothing in it
w1 = r[f"mq-{EW.isoformat()}"]
check("quarter: an empty week is dead and says where to plan it",
      w1["title"] == f"{meal.week_label(EW)} · nothing planned" and not w1["valid"]
      and "Plan it in Mela: ⌘⌥A Add to Calendar" in w1["subtitle"] and not w1["title"].startswith("⭐️"), w1)
w2 = r[f"mq-{(SUN + timedelta(days=14)).isoformat()}"]
check("quarter: a later planned week is live", w2["valid"] and "🌮 Pockets" in w2["title"] and "1 meal " in w2["subtitle"], w2)
check("quarter: ⌃ backs to the hub", all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:meal" for x in rows))
check("quarter: the bar filters on meal names", [x["uid"] for x in rows_for("ctx:mealq", "pockets")] == [f"mq-{(SUN + timedelta(days=14)).isoformat()}"])
check("quarter: the bar filters on the week label",
      [x["uid"] for x in rows_for("ctx:mealq", meal.week_label(EW))][:1] == [f"mq-{EW.isoformat()}"])

# ── one week ──────────────────────────────────────────────────────────────────
wk = (SUN + timedelta(days=14)).isoformat()
rows = rows_for(f"ctx:mealw:{wk}")
r = by_uid(rows)
check("week: sealed", sealed(rows, "week"))
check("week: head + the meal row", [x["uid"] for x in rows] == ["mw-head", f"mw-s-{U3[:8]}"]
      and r["mw-head"]["title"] == f"🥘 {meal.week_label(SUN + timedelta(days=14))} · {COOK(SUN + timedelta(days=14))} · 1 meal", [x["uid"] for x in rows])
meal_row_ok(r[f"mw-s-{U3[:8]}"], U3, "https://pockets.example", "week snack", tid="t3", back=f"ctx:mealw:{wk}")
check("week: ⌘ live (Pockets is t3)", r[f"mw-s-{U3[:8]}"]["variables"]["task_id"] == "t3" and r[f"mw-s-{U3[:8]}"]["mods"]["cmd"]["valid"])
check("week: ⌃ backs to the quarter", all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:mealq" for x in rows))
rows = rows_for(f"ctx:mealw:{EW.isoformat()}")
check("week: an empty one = the head alone, nothing planned", len(rows) == 1 and "nothing planned in Mela" in rows[0]["title"]
      and "⌘⌥A" in rows[0]["subtitle"], rows)
check("week: a weekday resolves to its cook Sunday",
      by_uid(rows_for(f"ctx:mealw:{(SUN + timedelta(days=3)).isoformat()}"))["mw-head"]["title"].startswith(f"🥘 {meal.week_label(SUN)}"))
check("week: a bad date", "needs" in browse.render_mealw(["yesterday"], "")[0]["title"])
check("week: the bar filters", [x["uid"] for x in rows_for(f"ctx:mealw:{SUN.isoformat()}", "bulg")] == ["mw-head", f"mw-l-{U1[:8]}"])

# ── the library + groceries ───────────────────────────────────────────────────
rows = rows_for("ctx:meallib:lunch")
r = by_uid(rows)
check("library: sealed", sealed(rows, "lib"))
check("library: never cooked first, then the tag-only cooked, then least recently cooked",
      [x["uid"] for x in rows] == ["ml-head", "ml-t4", "ml-t5", "ml-t2"], [x["uid"] for x in rows])
check("library: chips read off the calendar",
      r["ml-t4"]["subtitle"].startswith("never cooked · no description yet")
      and r["ml-t2"]["subtitle"].startswith(f"{meal.lib_chip(PLANNED, U1, TODAY)} · recipe in the description"),
      (r["ml-t4"]["subtitle"], r["ml-t2"]["subtitle"]))
check("library: a tag-only entry with no calendar past says 'cooked before · ⭐️⭐️⭐️', stamped once",
      r["ml-t5"]["subtitle"].startswith("cooked before · ⭐️⭐️⭐️ · recipe in the description  |  ")
      and r["ml-t5"]["subtitle"].count("⭐️⭐️⭐️") == 1 and r["ml-t5"]["subtitle"].count("cooked") == 2, r["ml-t5"]["subtitle"])
meal_row_ok(r["ml-t4"], U4, "https://second.example", "library lunch", tid="t4", back="ctx:meallib:lunch")
meal_row_ok(r["ml-t2"], U1, "", "library bulgogi", tid="t2", back="ctx:meallib:lunch")
meal_row_ok(r["ml-t5"], U6, "", "library kimchi", tid="t5", back="ctx:meallib:lunch")
check("library: ⌘ live with the task variables", r["ml-t2"]["mods"]["cmd"]["valid"] and r["ml-t2"]["variables"]["task_id"] == "t2"
      and r["ml-t2"]["variables"]["task_title"] == LIB[1]["title"])
check("library: ⌥ dead without subtasks, still the drill hop", not r["ml-t2"]["mods"]["alt"]["valid"]
      and r["ml-t2"]["mods"]["alt"]["variables"]["browse_ctx"] == f"ctx:subtasks:{LIST}:t2")
rs = by_uid(rows_for("ctx:meallib:snack"))
check("library: the next planned Sunday shows", f"next {SUN + timedelta(days=14):%a %-d %b}" in rs["ml-t3"]["subtitle"], rs["ml-t3"]["subtitle"])
check("library: filter", [x["uid"] for x in rows_for("ctx:meallib:lunch", "second")] == ["ml-head", "ml-t4"])
check("library: a bad tag", "needs" in browse.render_meallib(["dinner"], "")[0]["title"])
check("library: ⌃ backs to the hub", all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:meal" for x in rows))
rows = rows_for("ctx:mealgroc")
r = by_uid(rows)
check("groceries: sealed", sealed(rows, "groc"))
check("groceries: one list, ticked count, due, ⇧ completes",
      "1/2 ticked" in r["mg-g1"]["subtitle"] and f"due {meal.task_date(next(t for t in LIB if t['id'] == 'g1')):%a %-d %b}" in r["mg-g1"]["subtitle"]
      and r["mg-g1"]["mods"]["shift"]["arg"].startswith(f"complete:{LIST}:g1:") and r["mg-g1"]["variables"]["task_id"] == "g1", r["mg-g1"])
check("groceries: head says cut to 7 portions · ⌥⇧ re-cuts one, dead",
      r["mg-head"]["subtitle"] == "one checklist per planned meal, cut to 7 portions · ⌥⇧ re-cuts one  |  ⌃🔙"
      and not r["mg-head"]["valid"] and "1 open list" in r["mg-head"]["title"], r["mg-head"])
g1 = r["mg-g1"]
check("groceries: ⌥⇧ = xact:meal_portions on THAT list {pid, tid, back: ctx:mealgroc}, live",
      g1["mods"]["alt+shift"]["arg"].startswith("xact:meal_portions:") and g1["mods"]["alt+shift"]["valid"]
      and mod_payload(g1["mods"]["alt+shift"]) == meal.portions_payload(LIST, "g1", "ctx:mealgroc")
      == {"pid": LIST, "tid": "g1", "back": "ctx:mealgroc"}, g1["mods"]["alt+shift"])
check("groceries: the chord says the count the list was cut for (off the yield note)",
      g1["mods"]["alt+shift"]["subtitle"] == "🔢 Portions… (now 7)", g1["mods"]["alt+shift"])
check("groceries: the chip says 1/2 ticked · 7 portions", "1/2 ticked · 7 portions  |  " in g1["subtitle"], g1["subtitle"])
check("groceries: the legend ⏎↗️  ⇧✅  ⌥⇧🔢  ⌥⌘🔗  ⌘⚡", g1["subtitle"].endswith("  |  ⏎↗️  ⇧✅  ⌥⇧🔢  ⌥⌘🔗  ⌘⚡"), g1["subtitle"])
check("groceries: ⏎ still opens the task, ⌥⌘ still copies its link",
      g1["arg"] == f"open:{browse._meal_link(LIST, 'g1')}" and g1["mods"]["alt+cmd"]["arg"] == f"copy:{browse._meal_link(LIST, 'g1')}", g1)
plant(lib=LIB + [G2])
rows2 = rows_for("ctx:mealgroc")
r2 = by_uid(rows2)
check("groceries: two lists: sealed (no xact on ⌘ or ⌥)", sealed(rows2, "groc2"))
check("groceries: two lists counted in the head", "2 open lists" in r2["mg-head"]["title"] and "mg-g2" in r2, list(r2))
g2 = r2["mg-g2"]
check("groceries: a list saved without a yield note: no portions chip, the chord plain",
      "portions" not in g2["subtitle"] and "0/1 ticked  |  " in g2["subtitle"]
      and g2["mods"]["alt+shift"]["subtitle"] == "🔢 Portions…" and g2["mods"]["alt+shift"]["valid"]
      and mod_payload(g2["mods"]["alt+shift"]) == {"pid": LIST, "tid": "g2", "back": "ctx:mealgroc"}, g2)
check("groceries: the noted list keeps its chip beside the plain one",
      "1/2 ticked · 7 portions" in r2["mg-g1"]["subtitle"] and r2["mg-g1"]["mods"]["alt+shift"]["subtitle"] == "🔢 Portions… (now 7)")
check("groceries: ⌃ backs to the hub", all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:meal" for x in rows2))
plant(lib=LIB + [G3])
r3 = by_uid(rows_for("ctx:mealgroc"))
g3 = r3["mg-g3"]
check("groceries: the chip gains ' · ≈ 1.75 €' off the list's cost line, after the portions chip",
      "0/3 ticked · 7 portions · ≈ 1.75 €  |  " in g3["subtitle"], g3["subtitle"])
check("groceries: a list without a cost line keeps its chip as it was",
      "1/2 ticked · 7 portions  |  " in r3["mg-g1"]["subtitle"], r3["mg-g1"]["subtitle"])
check("groceries: the priced list is sealed, ⌥⇧ still the portions verb on it, ⏎ still opens it",
      sealed([g3], "groc3") and mod_payload(g3["mods"]["alt+shift"]) == {"pid": LIST, "tid": "g3", "back": "ctx:mealgroc"}
      and g3["arg"] == f"open:{browse._meal_link(LIST, 'g3')}", g3)
plant(lib=LIB + [G3, G4])
r4 = by_uid(rows_for("ctx:mealgroc"))
check("groceries: a D27 cost line gives the chip ' · ≈ 0.70 € · till 3.49 €' (used, then the till)",
      "0/2 ticked · 7 portions · ≈ 0.70 € · till 3.49 €  |  " in r4["mg-g4"]["subtitle"], r4["mg-g4"]["subtitle"])
check("groceries: a pre-D27 cost line keeps its chip without a till, never 'till 0.00 €'",
      "0/3 ticked · 7 portions · ≈ 1.75 €  |  " in r4["mg-g3"]["subtitle"] and "till" not in r4["mg-g3"]["subtitle"],
      r4["mg-g3"]["subtitle"])
check("groceries: _meal_cost_total = (used, till), till None on a pre-D27 line, None without a line",
      browse._meal_cost_total(G4["content"]) == (0.70, 3.49) and browse._meal_cost_total(G3["content"]) == (1.75, None)
      and browse._meal_cost_total(G2["content"]) is None and browse._meal_cost_total(None) is None,
      (browse._meal_cost_total(G4["content"]), browse._meal_cost_total(G3["content"])))
plant()

# ── the ⭐️ picker ─────────────────────────────────────────────────────────────
rows = rows_for(f"ctx:mealrate:{LIST}:t5")
r = by_uid(rows)
check("rate: sealed (no xact on ⌘ or ⌥, ⌘ dead: not task rows)", sealed(rows, "rate"))
check("rate: head + the two comments + five star rows + 🚫, in that order",
      [x["uid"] for x in rows] == ["mr-head", "mr-c0", "mr-c1", "mr-1", "mr-2", "mr-3", "mr-4", "mr-5", "mr-0"],
      [x["uid"] for x in rows])
check("rate: the head names the recipe and its rating now, dead",
      r["mr-head"]["title"] == "⭐️ Rate · Kimchi Stew · now ⭐️⭐️⭐️" and not r["mr-head"]["valid"], r["mr-head"]["title"])
check("rate: the comments already under the rating, oldest first, dead",
      r["mr-c0"]["title"] == "💬 less salt next time" and r["mr-c1"]["title"] == "💬 more chili"
      and not r["mr-c0"]["valid"] and not r["mr-c1"]["valid"], (r["mr-c0"], r["mr-c1"]))
for n in range(1, 6):
    s = r[f"mr-{n}"]
    check(f"rate: {n} stars = xact:meal_rate with rate_payload(LIST, t5, {n}, ctx:meal), ⏎ and ⌥⇧ the same",
          s["title"] == meal.stars(n) and s["valid"] and s["arg"].startswith("xact:meal_rate:")
          and payload(s) == meal.rate_payload(LIST, "t5", n, "ctx:meal") == {"pid": LIST, "tid": "t5", "stars": n, "back": "ctx:meal"}
          and s["mods"]["alt+shift"]["arg"] == s["arg"] and s["mods"]["alt+shift"]["valid"], s)
check("rate: the current rating is marked, the others plain",
      r["mr-3"]["subtitle"] == "⏎ rate · current" and all(r[f"mr-{n}"]["subtitle"] == "⏎ rate" for n in (1, 2, 4, 5)),
      [r[f"mr-{n}"]["subtitle"] for n in range(1, 6)])
check("rate: 🚫 No rating is live on a rated recipe, stars 0, ⌥⇧ the same",
      r["mr-0"]["title"] == "🚫 No rating" and r["mr-0"]["valid"] and payload(r["mr-0"]) == {"pid": LIST, "tid": "t5", "stars": 0, "back": "ctx:meal"}
      and r["mr-0"]["mods"]["alt+shift"]["arg"] == r["mr-0"]["arg"], r["mr-0"])
check("rate: ⌃ backs to the hub when the ctx names no screen",
      all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:meal" for x in rows))
check("rate: the bar filters ('3' keeps the 3-star row)",
      [x["uid"] for x in rows_for(f"ctx:mealrate:{LIST}:t5", "3")] == ["mr-3"],
      [x["uid"] for x in rows_for(f"ctx:mealrate:{LIST}:t5", "3")])
ru = by_uid(rows_for(f"ctx:mealrate:{LIST}:t4"))
check("rate: an unrated recipe: head says so, no comment rows, 🚫 dead, no 'current'",
      ru["mr-head"]["title"] == "⭐️ Rate · Second Lunch · not rated" and not any(u.startswith("mr-c") for u in ru)
      and not ru["mr-0"]["valid"] and ru["mr-0"]["arg"] == "" and not ru["mr-0"]["mods"]["alt+shift"]["valid"]
      and all(ru[f"mr-{n}"]["subtitle"] == "⏎ rate" for n in range(1, 6)), (ru["mr-head"]["title"], ru["mr-0"]))
rb = rows_for(f"ctx:mealrate:{LIST}:t5:meallib:lunch")
check("rate: a back level in the ctx = the ⌃ target AND the payloads' back",
      all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:meallib:lunch" for x in rb)
      and payload(by_uid(rb)["mr-4"]) == meal.rate_payload(LIST, "t5", 4, "ctx:meallib:lunch")
      and payload(by_uid(rb)["mr-0"])["back"] == "ctx:meallib:lunch", [x["mods"]["ctrl"]["variables"] for x in rb][:1])
check("rate: the ctx carries the trailing ids", render(f"ctx:mealrate:{LIST}:t5:meallib:lunch") == ("mealrate", [LIST, "t5", "meallib", "lunch"], ""))
check("rate: the pid in the ctx wins for the payload",
      payload(by_uid(rows_for("ctx:mealrate:otherlist:t5"))["mr-2"])["pid"] == "otherlist")
rn = rows_for(f"ctx:mealrate:{LIST}:nope")
check("rate: an unknown task = one dead row, ⌃ still backs",
      len(rn) == 1 and rn[0]["uid"] == "mr-none" and not rn[0]["valid"] and "not in the cache" in rn[0]["title"]
      and rn[0]["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:meal" and sealed(rn, "rate none"), rn)

# ── the 🏷 price book ─────────────────────────────────────────────────────────
plant(lib=LIB + [G3])
LOADS[0] = 0
rows = rows_for("ctx:mealprice")
r = by_uid(rows)
uids = [x["uid"] for x in rows]
check("prices: sealed (no xact on ⌘ or ⌥, ⌘ dead: not task rows)", sealed(rows, "prices"))
check("prices: the book is read once a render", LOADS[0] == 1, LOADS[0])
check("prices: head, the week's holes first (list order: g3 then g1), then the priced week keys, then the rest of the book",
      uids == ["mp-head", "mp-chicken thigh", "mp-egg", "mp-rice", "mp-salt", "mp-bacon", "mp-flour"], uids)
check("prices: the head counts the book, the week's holes and the book date, says the box takes pantry / not pantry, dead",
      r["mp-head"]["title"] == "🏷 Price book · 4 entries · 2 unpriced this week · updated 2026-09-22"
      and r["mp-head"]["subtitle"] == "knuspr.de prices as speculation · ⏎ type a price (or pantry / not pantry in the price box)"
                                      " · ⌥⇧ change the search term  |  ⌃🔙"
      and not r["mp-head"]["valid"], r["mp-head"])
h = r["mp-chicken thigh"]
check("prices: a hole = ❓ key · no price yet, searched as its default term",
      h["title"] == "❓ chicken thigh · no price yet"
      and h["subtitle"] == "searched as Hähnchenschenkel · ⏎ type a price · ⌥⇧ search term", h)
check("prices: a suffixed item title keys clean (rice, never 'rice 1 75')",
      "mp-rice" in r and not any(u.startswith("mp-rice ") for u in uids), uids)
k = r["mp-rice"]
# D27: rice, salt and flour are pantry staples by the default list, so
# their rows end in " · pantry" (the pins below changed on purpose)
check("prices: a knuspr entry = 🧾 key · €/kg · product pack price · knuspr date (· pantry: rice is a staple)",
      k["title"] == "🧾 rice · 3.49 €/kg · Basmati Reis 1 kg 3.49 € · knuspr 22 Sep · pantry", k["title"])
check("prices: the entry's own search term shows",
      k["subtitle"].startswith("searched as Basmati Reis · ⏎ type a price · ⌥⇧ search term"), k["subtitle"])
check("prices: the manual glyph: ✍️ key · €/kg · manual date (· pantry)",
      r["mp-salt"]["title"] == "✍️ salt · 0.49 €/kg · manual 20 Sep · pantry", r["mp-salt"]["title"])
check("prices: an entry not on this week's lists wears 📖, same shape (· pantry: flour)",
      r["mp-flour"]["title"] == "📖 flour · 0.89 €/kg · Mehl Type 405 1 kg 0.89 € · knuspr 22 Sep · pantry", r["mp-flour"]["title"])
check("prices: bacon and the holes are not staples: no pantry marker",
      not any(x["title"].endswith("· pantry") for x in (r["mp-bacon"], h, r["mp-egg"])),
      [x["title"] for x in (r["mp-bacon"], h, r["mp-egg"])])
for uid in uids[1:]:
    row, key = r[uid], uid[3:]
    check(f"prices: {key}: ⏎ = xact:meal_price_set {{key, back: ctx:mealprice}}",
          row["arg"].startswith("xact:meal_price_set:") and row["valid"]
          and payload(row) == {"key": key, "back": "ctx:mealprice"}, row["arg"])
    check(f"prices: {key}: ⌥⇧ = xact:meal_price_search, the same payload, 🔍",
          row["mods"]["alt+shift"]["arg"].startswith("xact:meal_price_search:") and row["mods"]["alt+shift"]["valid"]
          and mod_payload(row["mods"]["alt+shift"]) == {"key": key, "back": "ctx:mealprice"}
          and row["mods"]["alt+shift"]["subtitle"] == "🔍 Search term…", row["mods"]["alt+shift"])
    check(f"prices: {key}: ⌘ ⌥ ⇧ ⌘⇧ dead",
          all(not row["mods"][c]["valid"] and not row["mods"][c]["arg"] for c in ("cmd", "alt", "shift", "cmd+shift")),
          row["mods"])
check("prices: ⌥⌘ copies the knuspr page when the entry has one, the legend says so",
      k["mods"]["alt+cmd"]["arg"] == "copy:https://www.knuspr.de/basmati-reis" and k["mods"]["alt+cmd"]["valid"]
      and k["subtitle"].endswith("  |  ⌥⌘🔗"), k["mods"]["alt+cmd"])
check("prices: ⌥⌘ dead without a url (a hole, a manual entry)",
      not h["mods"]["alt+cmd"]["valid"] and not h["mods"]["alt+cmd"]["arg"]
      and not r["mp-salt"]["mods"]["alt+cmd"]["valid"] and "⌥⌘" not in r["mp-salt"]["subtitle"], (h["mods"]["alt+cmd"], r["mp-salt"]["subtitle"]))
check("prices: ⌃ backs to the hub when the ctx names no screen",
      all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:meal" for x in rows))
rb = rows_for("ctx:mealprice:mealgroc")
check("prices: a back level in the ctx = the ⌃ target, the payloads' back = THIS ctx (the verb reopens the book)",
      all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:mealgroc" for x in rb)
      and payload(by_uid(rb)["mp-rice"]) == {"key": "rice", "back": "ctx:mealprice:mealgroc"}
      and mod_payload(by_uid(rb)["mp-rice"]["mods"]["alt+shift"])["back"] == "ctx:mealprice:mealgroc",
      [x["mods"]["ctrl"]["variables"] for x in rb][:1])
check("prices: the ctx carries the trailing ids", render("ctx:mealprice:mealgroc") == ("mealprice", ["mealgroc"], ""))
check("prices: the bar filters on the key", [x["uid"] for x in rows_for("ctx:mealprice", "chick")] == ["mp-head", "mp-chicken thigh"],
      [x["uid"] for x in rows_for("ctx:mealprice", "chick")])
check("prices: the bar filters on the product too", [x["uid"] for x in rows_for("ctx:mealprice", "basm")] == ["mp-head", "mp-rice"],
      [x["uid"] for x in rows_for("ctx:mealprice", "basm")])
rz = rows_for("ctx:mealprice", "zzzz")
check("prices: nothing matches = the head and one dead row",
      [x["uid"] for x in rz] == ["mp-head", "mp-none"] and not rz[1]["valid"] and sealed(rz, "prices none"), [x["uid"] for x in rz])
check("prices: 'today' typed on the book stays put", render("ctx:mealprice", "today") == ("mealprice", [], "today"))
# the pantry marker on a hole, and the two overrides that beat the default
# list: an entry's own flag, and the bare {key, pantry} entry a "not
# pantry" answer mints under a key the book cannot price
plant(lib=LIB + [G3, G4])
rp = by_uid(rows_for("ctx:mealprice"))
check("prices: G4's soy sauce is a hole AND a staple: ❓ soy sauce · no price yet · pantry, the egg hole plain",
      list(rp)[:4] == ["mp-head", "mp-chicken thigh", "mp-soy sauce", "mp-egg"]
      and rp["mp-soy sauce"]["title"] == "❓ soy sauce · no price yet · pantry"
      and rp["mp-egg"]["title"] == "❓ egg · no price yet", (list(rp), rp["mp-soy sauce"]["title"]))
check("prices: a pantry hole still fires the price verb with its own key",
      payload(rp["mp-soy sauce"]) == {"key": "soy sauce", "back": "ctx:mealprice"} and rp["mp-soy sauce"]["valid"])
BOOK["entries"]["soy sauce"] = {"key": "soy sauce", "pantry": False}
BOOK["entries"]["bacon"]["pantry"] = True
BOOK["entries"]["rice"]["pantry"] = False
rp = by_uid(rows_for("ctx:mealprice"))
check("prices: a bare {key, pantry: false} entry keeps the key a hole (it prices nothing) and drops the marker",
      rp["mp-soy sauce"]["title"] == "❓ soy sauce · no price yet" and "mp-soy sauce" in list(rp)[:4], rp["mp-soy sauce"]["title"])
check("prices: an entry's own flag wins over the default list both ways (bacon pantry, rice not)",
      rp["mp-bacon"]["title"].endswith("· knuspr 22 Sep · pantry") and not rp["mp-rice"]["title"].endswith("· pantry"),
      (rp["mp-bacon"]["title"], rp["mp-rice"]["title"]))
hp = by_uid(rows_for("ctx:meal"))["meal-price"]
check("hub: the flags move the pantry share (bacon 1.99 + salt 0.49 in, rice out), the till itself unchanged",
      hp["title"] == "🏷 Prices · ≈ 2.45 € used · till ≈ 5.97 € · 2 unpriced"
      and hp["subtitle"].startswith("pantry 2.48 € of the till · "), (hp["title"], hp["subtitle"]))
del BOOK["entries"]["soy sauce"]
del BOOK["entries"]["bacon"]["pantry"]
del BOOK["entries"]["rice"]["pantry"]
plant(lib=[t for t in LIB if t["id"] != "g1"])
saved_entries, BOOK["entries"], BOOK["updated"] = BOOK["entries"], {}, ""
re_ = by_uid(rows_for("ctx:mealprice"))
check("prices: no lists + an empty book = head says 0 entries · 0 unpriced · updated never, one dead row",
      re_["mp-head"]["title"] == "🏷 Price book · 0 entries · 0 unpriced this week · updated never"
      and list(re_) == ["mp-head", "mp-none"] and "Sync with Mela" in re_["mp-none"]["subtitle"], list(re_))
hp = by_uid(rows_for("ctx:meal"))["meal-price"]
check("hub: 🏷 with an empty book and no list: nothing priced yet · book 0 entries",
      hp["title"] == "🏷 Prices · nothing priced yet" and "book 0 entries" in hp["subtitle"], hp)
BOOK["entries"], BOOK["updated"] = saved_entries, "2026-09-22"
plant()

# ── the Routines hub's door ───────────────────────────────────────────────────
rr = by_uid(browse.render_routines(""))
door = rr.get("rt-meal-hub")
check("routines hub: the 🥘 door row (trampoline ⏎, ⌥ by variable, ⌃ dead)",
      door is not None and door["arg"] == "xact:crmbrowse:ctx:meal" and door["mods"]["alt"]["variables"]["browse_ctx"] == "ctx:meal"
      and door["mods"]["ctrl"]["arg"] == "" and not door["mods"]["cmd"].get("valid", True), door)
check("routines hub: the meal routine itself is listed", "rt-meal" in rr)

# ── main() end to end through argv ────────────────────────────────────────────
import contextlib, io                          # noqa: E402
os.environ["browse_ctx"] = "ctx:meal"
sys.argv = ["browse.py", ""]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    browse.main()
os.environ.pop("browse_ctx", None)
out = json.loads(buf.getvalue())
check("main(): the hub renders through argv + env", any(i.get("uid") == "meal-head" for i in out.get("items", [])))
sys.argv = ["browse.py", "ctx:mealq"]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    browse.main()
out = json.loads(buf.getvalue())
check("main(): the quarter renders by explicit ctx", sum(1 for i in out.get("items", []) if i.get("uid", "").startswith("mq-")) == HORIZON)
sys.argv = ["browse.py", f"ctx:mealrate:{LIST}:t5"]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    browse.main()
out = json.loads(buf.getvalue())
check("main(): the ⭐️ picker renders by explicit ctx", [i.get("uid") for i in out.get("items", [])][:2] == ["mr-head", "mr-c0"]
      and sum(1 for i in out.get("items", []) if i.get("uid", "") in ("mr-1", "mr-2", "mr-3", "mr-4", "mr-5")) == 5)
sys.argv = ["browse.py", f"ctx:mealrate:{LIST}"]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    browse.main()
out = json.loads(buf.getvalue())
check("main(): ctx:mealrate with one id = the grammar row", len(out.get("items", [])) == 1
      and "needs <listId>:<taskId>" in out["items"][0]["title"], out.get("items"))
sys.argv = ["browse.py", "ctx:mealprice"]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    browse.main()
out = json.loads(buf.getvalue())
check("main(): the 🏷 book renders by explicit ctx (the week's hole first, then bacon, then the 📖 rest)",
      [i.get("uid") for i in out.get("items", [])] == ["mp-head", "mp-egg", "mp-bacon", "mp-flour", "mp-rice", "mp-salt"],
      [i.get("uid") for i in out.get("items", [])])
check("the real price book is never written by this file", os.path.exists(REAL_BOOK) == HAD_BOOK, REAL_BOOK)

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print(f"\nmeal screens: {COUNT[0] - len(FAILS)} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
