#!/usr/bin/env python3
"""Unit suite for src/meal_price.py (price speculation for the 🛒 lists:
the ingredient key (the pack head "x 400 g cans", a leading count word,
edge & / - tokens, the -ves plurals, immunity to the module's own price
suffix), base units, the price book, lookup's base tie-break, knuspr
parsing over FAKE responses built from live shapes of 2026-09-22 (the
comma-decimal pack, the 5 percent price / pack rule, junk answers), rank
and pick never comparing per across bases, refresh (pinned without a
product, stale entries, a fetch that throws), the cost lines (strip by
shape, read_cost_line), the hand-typed price (parse_price_answer,
manual_entry)). Never touches the network or the real ~/.ticktick_alfred:
the real book's existence and mtime are recorded first and asserted
unchanged last.
Run: python3 tests/test_meal_price.py
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import meal_price as mp  # noqa: E402
import meal_scale as ms  # noqa: E402

FAILS, COUNT = [], [0]
REAL_BOOK = os.path.expanduser("~/.ticktick_alfred/meal_prices.json")
REAL_BOOK_BEFORE = (os.path.exists(REAL_BOOK), os.path.getmtime(REAL_BOOK) if os.path.exists(REAL_BOOK) else None)


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


def same(name, got, want):
    check(name, got == want, f"got {got!r}, want {want!r}")


def near(name, got, want, tol=1e-9):
    check(name, got is not None and want is not None and abs(got - want) <= tol,
          f"got {got!r}, want {want!r}")


TODAY = date(2026, 9, 22)

# ── ingredient_key: the spec's examples ────────────────────────────────────
KEYS = [
    ("14 Eggs", "egg"),
    ("350 g Sliced Bacon (short cut bacon, beef bacon, turkey bacon or any cut of lean bacon)", "bacon"),
    ("11-14 chicken thighs, boneless & skinless", "chicken thigh"),
    ("1/2 cup butter, melted", "butter"),
    ("1 tsp Onion & Garlic Powder", "onion & garlic powder"),
    ("7 Toasted Bagels (Abe's Low Carb Bagels - the good ones)", "bagel"),
    ("3 garlic cloves", "garlic clove"),
    ("CHICKEN", "chicken"),
    ("1 tsp Salt", "salt"),
    ("2 3/4 lb baby potatoes (680 g)", "baby potato"),
]
for src, want in KEYS:
    same(f"key: {src[:34]!r}", mp.ingredient_key(src), want)

# ── ingredient_key: edges ──────────────────────────────────────────────────
same("key: blank line", mp.ingredient_key(""), "")
same("key: None", mp.ingredient_key(None), "")
same("key: whitespace only", mp.ingredient_key("   "), "")
same("key: parentheses only", mp.ingredient_key("(for serving)"), "")
same("key: an unclosed parenthesis is dropped to the end", mp.ingredient_key("2 limes (juiced"), "lime")
same("key: cut at the first comma", mp.ingredient_key("500 g chicken breast, boneless, cubed"), "chicken breast")
same("key: comma first falls back on the whole text", mp.ingredient_key(", comma first"), "comma first")
same("key: a stopword before the comma is not the key", mp.ingredient_key("1 tsp fresh, chopped parsley"), "parsley")
same("key: 'to taste' goes as a phrase", mp.ingredient_key("salt to taste"), "salt")
same("key: adjectives out", mp.ingredient_key("2 large eggs"), "egg")
same("key: prep words out, & kept", mp.ingredient_key("1 tbsp finely chopped onion & garlic"), "onion & garlic")
same("key: hyphen kept", mp.ingredient_key("2 tbsp extra-virgin olive oil"), "extra-virgin olive oil")
same("key: apostrophe dropped, other punctuation a space", mp.ingredient_key("1 cup Abe's salt/pepper mix"),
     "abes salt pepper mix")
same("key: ies -> y", mp.ingredient_key("2 cups berries"), "berry")
same("key: oes -> o", mp.ingredient_key("3 tomatoes"), "tomato")
same("key: ches -> ch", mp.ingredient_key("2 peaches"), "peach")
same("key: shes -> sh", mp.ingredient_key("4 radishes"), "radish")
same("key: xes -> x", mp.ingredient_key("2 boxes"), "box")
same("key: a plain s dropped past 3 letters", mp.ingredient_key("1 cup oats"), "oat")
same("key: a 3-letter word keeps its s", mp.ingredient_key("1 cup gas"), "gas")
same("key: -ss keeps its s", mp.ingredient_key("1 bunch watercress"), "watercress")
same("key: -us keeps its s", mp.ingredient_key("200 g hummus"), "hummus")
same("key: only the LAST word is singularised", mp.ingredient_key("2 cans beans sprouts"), "beans sprout")
same("key: a count unit is not part of the key", mp.ingredient_key("3 cloves garlic"), "garlic")
same("key: whitespace collapsed", mp.ingredient_key("  Avocado    Oil "), "avocado oil")
same("key: a bold header keys by its word", mp.ingredient_key("**Sauce**"), "sauce")
same("key: no leading number keeps the whole name", mp.ingredient_key("Avocado oil"), "avocado oil")
# the pack head, count words, edge tokens, the new stopwords (fix 10)
same("key: 'x 400 g cans' is the pack, not the food", mp.ingredient_key("2 x 400 g cans chopped tomatoes"), "tomato")
same("key: a can after a parenthesis is the container", mp.ingredient_key("1 (15 oz) can black beans, drained"), "black bean")
same("key: 'divided' behind a dash goes, the dash with it", mp.ingredient_key("2 tbsp olive oil - divided"), "olive oil")
same("key: 'drained' is a stopword", mp.ingredient_key("1 jar artichokes, drained"), "artichoke")
same("key: a leading count word without parens", mp.ingredient_key("2 x 400g tins tomatoes"), "tomato")
same("key: 'x 2' with no unit word keeps the food", mp.ingredient_key("1 x 2 avocados"), "avocado")
same("key: a bunch is dropped, the herb keyed", mp.ingredient_key("1 (large) bunch parsley"), "parsley")
same("key: clove is NOT a count word to drop", mp.ingredient_key("1 (whole) clove"), "clove")
same("key: a leading & goes", mp.ingredient_key("1 tsp & salt"), "salt")
same("key: a trailing + goes", mp.ingredient_key("1 tsp salt +"), "salt")
same("key: & in the middle stays", mp.ingredient_key("1 tbsp onion & garlic"), "onion & garlic")
same("key: only edge tokens leaves nothing", mp.ingredient_key("1 tsp & -"), "")
check("STOPWORDS carries divided and drained", {"divided", "drained"} <= set(mp.STOPWORDS))
# the -ves plurals (fix 7)
for src, want in (("2 bay leaves", "bay leaf"), ("2 halves", "half"), ("2 loaves", "loaf"), ("2 knives", "knife")):
    same(f"key: {src!r} singular by the map", mp.ingredient_key(src), want)
same("key: the map changes nothing else (olives)", mp.ingredient_key("10 olives"), "olive")
same("key: the map changes nothing else (chives)", mp.ingredient_key("1 tbsp chives"), "chive")
# immune to its own output (fix 2)
same("key: the module's own price suffix is ignored", mp.ingredient_key("14 Eggs · ≈ 4.47 €"), "egg")
same("key: a suffixed thigh line", mp.ingredient_key("500 g chicken thighs · ≈ 4.80 €"), "chicken thigh")

# ── FREE, headers ──────────────────────────────────────────────────────────
check("FREE is a frozenset with water, ice, tap water",
      isinstance(mp.FREE, frozenset) and {"water", "ice", "tap water"} <= mp.FREE)
check("STOPWORDS is a tuple carrying 'to taste'", isinstance(mp.STOPWORDS, tuple) and "to taste" in mp.STOPWORDS)
same("header: bold, #, colon, CAPS", [mp.is_header_line(x) for x in ("**Sauce**", "# Sauce", "For the sauce:", "CHICKEN")],
     [True, True, True, True])
same("header: a plain ingredient is not one", [mp.is_header_line(x) for x in ("Avocado oil", "BBQ sauce", "")],
     [False, False, False])

# ── to_base ────────────────────────────────────────────────────────────────
Q = ms.parse_quantity
same("base: g", mp.to_base(Q("350 g bacon")), (350, "g"))
same("base: kg", mp.to_base(Q("1.2 kg beef")), (1200, "g"))
near("base: mg", mp.to_base(Q("500 mg saffron"))[0], 0.5)
same("base: mg is grams", mp.to_base(Q("500 mg saffron"))[1], "g")
same("base: lb", mp.to_base(Q("1 lb pork")), (454, "g"))
near("base: oz", mp.to_base(Q("8 oz cream cheese"))[0], 226.8)
same("base: ml", mp.to_base(Q("500 ml stock")), (500, "ml"))
same("base: l", mp.to_base(Q("1 l water")), (1000, "ml"))
same("base: dl", mp.to_base(Q("2 dl milk")), (200, "ml"))
same("base: tsp", mp.to_base(Q("1 tsp salt")), (5, "ml"))
same("base: tbsp", mp.to_base(Q("2 tbsp oil")), (30, "ml"))
same("base: cup", mp.to_base(Q("1/2 cup butter")), (120, "ml"))
same("base: a count unit is pieces", mp.to_base(Q("2 cans tomatoes")), (2, "pc"))
same("base: no unit is pieces", mp.to_base(Q("14 Eggs")), (14, "pc"))
same("base: a range is its midpoint", mp.to_base(Q("11-14 chicken thighs")), (12.5, "pc"))
same("base: a mass range too", mp.to_base(Q("400-500 g chicken")), (450, "g"))
same("base: no amount", mp.to_base(Q("Avocado oil")), (None, None))
same("base: None survives", mp.to_base(None), (None, None))
check("base: every spoon/cup class unit is a volume",
      all(mp.to_base(Q(f"1 {u} x"))[1] == "ml" for u, (cls, _) in ms.UNITS.items() if cls == "spoon"))
check("base: every mass class unit is grams",
      all(mp.to_base(Q(f"1 {u} x"))[1] == "g" for u, (cls, _) in ms.UNITS.items()
          if cls in ("mass_g", "mass_kg", "lb", "oz")))

# ── DEFAULT_SEARCH, search_term ────────────────────────────────────────────
check("DEFAULT_SEARCH has at least 80 terms", len(mp.DEFAULT_SEARCH) >= 80, str(len(mp.DEFAULT_SEARCH)))
for k, v in (("egg", "Eier"), ("chicken thigh", "Hähnchenschenkel"), ("garlic powder", "Knoblauchpulver"),
             ("sweet potato", "Süßkartoffel"), ("scallion", "Lauchzwiebeln"), ("cheddar cheese", "Cheddar"),
             ("sour cream", "Schmand"), ("cornstarch", "Speisestärke")):
    same(f"DEFAULT_SEARCH[{k!r}]", mp.DEFAULT_SEARCH.get(k), v)
same("search_term: the longest contained key wins", mp.search_term("onion & garlic powder"), "Knoblauchpulver")
same("search_term: 'cheddar cheese slice' -> Cheddar", mp.search_term("cheddar cheese slice"), "Cheddar")
same("search_term: whole words only (egg is not in eggplant)", mp.search_term("eggplant"), "Aubergine")
same("search_term: 'oil' inside 'olive oil' loses", mp.search_term("olive oil"), "Olivenöl")
same("search_term: the key itself when nothing matches", mp.search_term("unicorn horn"), "unicorn horn")
BOOK_S = {"entries": {"egg": {"search": "Bio Eier"}, "salt": {"source": "manual"}}}
same("search_term: the book's own search beats the table", mp.search_term("egg", BOOK_S), "Bio Eier")
same("search_term: an entry without a search falls through", mp.search_term("salt", BOOK_S), "Salz")
same("search_term: no book", mp.search_term("egg", None), "Eier")

# ── lookup ─────────────────────────────────────────────────────────────────
E = {"chicken": {"per": 1, "per_unit": "g"}, "chicken thigh": {"per": 2, "per_unit": "g"},
     "garlic powder": {"per": 3, "per_unit": "g"}, "olive oil": {"per": 4, "per_unit": "ml"}}
BOOK_L = {"entries": E}
same("lookup: exact", mp.lookup("chicken thigh", BOOK_L), E["chicken thigh"])
same("lookup: the longest contained entry", mp.lookup("boneless chicken thigh", BOOK_L), E["chicken thigh"])
same("lookup: a contained entry, whole words", mp.lookup("onion & garlic powder", BOOK_L), E["garlic powder"])
same("lookup: the shortest entry containing the key", mp.lookup("oil", BOOK_L), E["olive oil"])
same("lookup: nothing", mp.lookup("unicorn", BOOK_L), None)
same("lookup: empty key", mp.lookup("", BOOK_L), None)
same("lookup: no book", mp.lookup("chicken", None), None)
same("lookup: a book without entries", mp.lookup("chicken", {}), None)
# the base tie-break (fix 8)
E2 = {"chicken stock": {"per": 0.001, "per_unit": "ml"}, "chicken thigh": {"per": 0.00959, "per_unit": "g"}}
BOOK_L2 = {"entries": E2}
same("lookup: base breaks the tie (500 g chicken -> the thigh, not the stock)",
     mp.lookup("chicken", BOOK_L2, "g"), E2["chicken thigh"])
same("lookup: the other base takes the stock", mp.lookup("chicken", BOOK_L2, "ml"), E2["chicken stock"])
same("lookup: no base is the old order (shortest, then the name)", mp.lookup("chicken", BOOK_L2), E2["chicken stock"])
same("lookup: base=None is the default", mp.lookup("chicken", BOOK_L2, None), E2["chicken stock"])
same("lookup: exact beats base", mp.lookup("chicken thigh", BOOK_L2, "ml"), E2["chicken thigh"])
same("lookup: the longest contained still wins when both are in base",
     mp.lookup("boneless chicken thigh", BOOK_L, "g"), E["chicken thigh"])
E3 = {"chicken": {"per": 1, "per_unit": "g"}, "chicken thigh": {"per": 2, "per_unit": "pc", "piece_g": 120}}
same("lookup: among contained entries the line's base comes before length",
     mp.lookup("boneless chicken thigh", {"entries": E3}, "g"), E3["chicken"])
same("lookup: an entry without a per_unit is off base", mp.lookup("chicken", {"entries": {"chicken stock": {"per": 1},
     "chicken thigh": {"per": 2, "per_unit": "g"}}}, "g")["per"], 2)
same("line_cost: hands the line's base to lookup", mp.line_cost("500 g chicken", BOOK_L2).cost, 4.8)
same("line_cost: an ml line takes the stock", mp.line_cost("500 ml chicken", BOOK_L2).cost, 0.5)

# ── line_cost ──────────────────────────────────────────────────────────────
BOOK = {"version": 1, "updated": "2026-09-22", "entries": {
    "bacon": {"key": "bacon", "per": 0.0129, "per_unit": "g", "product": "Bacon 100 g", "source": "knuspr"},
    "egg": {"key": "egg", "per": 0.319, "per_unit": "pc", "source": "knuspr"},
    "salt": {"key": "salt", "per": 0.00058, "per_unit": "g", "source": "manual"},
    "chicken thigh": {"key": "chicken thigh", "per": 0.00959, "per_unit": "g", "source": "knuspr"},
    "chicken breast": {"key": "chicken breast", "per": 0.012, "per_unit": "g", "piece_g": 150, "source": "knuspr"},
    "scallion": {"key": "scallion", "per": 0.89, "per_unit": "pc", "piece_g": 60, "source": "knuspr"},
    "olive oil": {"key": "olive oil", "per": 0.01598, "per_unit": "ml", "source": "knuspr"},
    "broken": {"key": "broken", "per": "lots", "per_unit": "g"},
}}
c = mp.line_cost("350 g Sliced Bacon (short cut bacon)", BOOK)
same("cost: 350 g bacon at 12.90/kg is 4.52 (half up, not 4.51)", (c.cost, c.reason, c.approx), (4.52, "priced", False))
same("cost: the key and line ride along", (c.line, c.key), ("350 g Sliced Bacon (short cut bacon)", "bacon"))
check("cost: the note reads like a shelf tag", "350 g at 12.90 €/kg" in c.per_line_note, c.per_line_note)
check("cost: the note names the product", "Bacon 100 g" in c.per_line_note, c.per_line_note)
same("cost: 14 eggs at 0.319 is 4.47", mp.line_cost("14 Eggs", BOOK)[2:], (4.47, "14 pc at 0.32 €/pc", False, "priced"))
c = mp.line_cost("1 tsp Salt", BOOK)
same("cost: a spoon against a per-gram price rounds to 0.0, approx", (c.cost, c.approx, c.reason), (0.0, True, "priced"))
c = mp.line_cost("1 cup olive oil", BOOK)
near("cost: 240 ml oil at 15.98/l", c.cost, 3.84)
same("cost: same base is exact", c.approx, False)
c = mp.line_cost("200 g olive oil", BOOK)
same("cost: a mass line against a volume price is approx", (c.cost, c.approx), (3.2, True))
same("cost: a pc line against a g price is a unit mismatch",
     mp.line_cost("3 chicken thighs", BOOK)[2:], (None, "pc line, g price", False, "unit mismatch"))
c = mp.line_cost("3 chicken breasts", BOOK)
same("cost: with piece_g the pieces convert (3 x 150 g at 0.012)", (c.cost, c.approx, c.reason), (5.4, True, "priced"))
c = mp.line_cost("120 g scallions", BOOK)
same("cost: a g line against a pc price with piece_g (120/60 x 0.89)", (c.cost, c.approx, c.reason), (1.78, True, "priced"))
same("cost: a g line against a pc price without piece_g", mp.line_cost("100 g eggs", BOOK).reason, "unit mismatch")
c = mp.line_cost("11-14 chicken breasts", BOOK)
same("cost: a range is its midpoint, approx", (c.cost, c.approx), (22.5, True))
check("cost: the midpoint is said", "midpoint" in c.per_line_note, c.per_line_note)
same("cost: a header line", mp.line_cost("CHICKEN", BOOK)[2:], (None, "no amount", False, "no amount"))
same("cost: a bold header", mp.line_cost("**Sauce**", BOOK).reason, "no amount")
same("cost: no leading number", mp.line_cost("Avocado oil", BOOK).reason, "no amount")
same("cost: water is free", mp.line_cost("1 cup water", BOOK)[2:], (0.0, "free", False, "free"))
same("cost: ice is free, even with no amount", mp.line_cost("Ice", BOOK)[2:], (0.0, "free", False, "free"))
same("cost: nothing in the book", mp.line_cost("2 unicorns", BOOK)[2:],
     (None, "no price for unicorn", False, "no entry"))
same("cost: an entry with a broken price is no entry", mp.line_cost("100 g broken", BOOK).reason, "no entry")
same("cost: a containing entry prices a longer key", mp.line_cost("500 g boneless chicken thigh", BOOK).cost, 4.8)
same("cost: empty book", mp.line_cost("14 Eggs", {}).reason, "no entry")
same("cost: None book", mp.line_cost("14 Eggs", None).reason, "no entry")
same("cost: blank line", mp.line_cost("", BOOK).reason, "no amount")
check("cost: a Cost has the six fields", mp.Cost._fields == ("line", "key", "cost", "per_line_note", "approx", "reason"))
c = mp.line_cost("14 Eggs · ≈ 4.47 €", BOOK)
same("cost: a line with the module's own suffix costs as the bare line", (c.key, c.cost, c.reason), ("egg", 4.47, "priced"))
same("cost: Cost.line is the line as given", c.line, "14 Eggs · ≈ 4.47 €")
same("cost: a suffixed range line", mp.line_cost("11-14 chicken breasts · ≈ 22.50 €", BOOK).cost, 22.5)
same("cost: a suffixed water line is free", mp.line_cost("1 cup water · ≈ 0.00 €", BOOK).reason, "free")
same("list: suffixed lines cost the same as bare ones",
     mp.list_cost(["350 g bacon · ≈ 4.52 €", "14 Eggs · ≈ 4.47 €"], BOOK).total, 8.99)

# ── list_cost ──────────────────────────────────────────────────────────────
LINES = ["**Meat**", "350 g bacon", "14 Eggs", "1 tsp salt", "2 unicorns", "3 chicken thighs", "1 cup water", "Avocado oil"]
t = mp.list_cost(LINES, BOOK)
same("list: total to the cent (4.52 + 4.47 + 0.00)", t.total, 8.99)
same("list: priced counts the priced rows", t.priced, 3)
same("list: unpriced = no entry, unit mismatch, a nameless-amount ingredient; never the header",
     t.unpriced, ["2 unicorns", "3 chicken thighs", "Avocado oil"])
same("list: per portion of 7", t.per_portion, 1.28)
same("list: approx when anything is unpriced", t.approx, True)
same("list: one Cost per line, in order", [c.line for c in t.costs], LINES)
same("list: portions is a parameter", mp.list_cost(["14 Eggs"], BOOK, portions=2).per_portion, 2.24)
same("list: no portions, no per_portion", mp.list_cost(["14 Eggs"], BOOK, portions=0).per_portion, None)
t2 = mp.list_cost(["350 g bacon", "14 Eggs"], BOOK)
same("list: exact when everything is priced exactly", (t2.approx, t2.unpriced, t2.priced), (False, [], 2))
same("list: a spoon makes it approx", mp.list_cost(["1 tsp salt"], BOOK).approx, True)
same("list: empty", mp.list_cost([], BOOK)[:5], (0.0, 0, [], 0.0, False))
same("list: None lines", mp.list_cost(None, BOOK).total, 0.0)
check("list: a Total has the six fields", mp.Total._fields == ("total", "priced", "unpriced", "per_portion", "approx", "costs"))

# ── cost_line, strip_cost_line, price_suffix, strip_price ──────────────────
same("cost_line: with holes", mp.cost_line(t), "≈ 8.99 € · 1.28 €/portion · 3 unpriced")
same("cost_line: clean", mp.cost_line(t2), "≈ 8.99 € · 1.28 €/portion")
same("cost_line: the spec's example", mp.cost_line(mp.Total(18.4, 5, ["a", "b", "c"], 2.6, True, [])),
     "≈ 18.40 € · 2.60 €/portion · 3 unpriced")
same("cost_line: nothing priced yet", mp.cost_line(mp.list_cost(["2 unicorns", "3 dragons"], BOOK)),
     "≈ 0.00 € · nothing priced yet")
same("cost_line: no portions", mp.cost_line(mp.list_cost(["14 Eggs"], BOOK, portions=None)), "≈ 4.47 €")
same("cost_line: empty list", mp.cost_line(mp.list_cost([], BOOK)), "≈ 0.00 € · 0.00 €/portion")
DESC = "≈ 8.99 € · 1.28 €/portion · 3 unpriced\n≈ Scaled ×1.75: 4 → 7 portions\n[Recipe](mela://recipe/X)"
same("strip_cost_line: the cost line goes, the yield note stays", mp.strip_cost_line(DESC),
     "≈ Scaled ×1.75: 4 → 7 portions\n[Recipe](mela://recipe/X)")
same("strip_cost_line: never strips a bare yield note", mp.strip_cost_line("≈ Scaled ×1.75: 4 → 7 portions"),
     "≈ Scaled ×1.75: 4 → 7 portions")
same("strip_cost_line: a cost line in the middle", mp.strip_cost_line("a\n≈ 1.00 € · 0.14 €/portion\nb"), "a\nb")
same("strip_cost_line: a cost line at the end", mp.strip_cost_line("a\n≈ 1.00 €"), "a\n")
same("strip_cost_line: nothing to strip", mp.strip_cost_line("plain\ntext"), "plain\ntext")
same("strip_cost_line: None", mp.strip_cost_line(None), "")
same("strip_cost_line: idempotent", mp.strip_cost_line(mp.strip_cost_line(DESC)), mp.strip_cost_line(DESC))
# anchored to the cost line's own shape (fix 11)
same("strip_cost_line: cost line + blank + body comes back as the body",
     mp.strip_cost_line("≈ 18.40 € · 2.60 €/portion · 3 unpriced\n\nScaled ×1.75: 4 → 7 portions\n[R](mela://recipe/X)"),
     "Scaled ×1.75: 4 → 7 portions\n[R](mela://recipe/X)")
same("strip_cost_line: only ONE blank line goes with it",
     mp.strip_cost_line("≈ 18.40 €\n\n\nbody"), "\nbody")
same("strip_cost_line: '≈ 3 € worth of saffron' is not a cost line", mp.strip_cost_line("≈ 3 € worth of saffron\nbody"),
     "≈ 3 € worth of saffron\nbody")
same("strip_cost_line: the yield note under a cost line survives, the cost line does not",
     mp.strip_cost_line("≈ 0.00 € · nothing priced yet\n≈ Scaled ×1.75: 4 → 7 portions"), "≈ Scaled ×1.75: 4 → 7 portions")
same("strip_cost_line: the yield note with an estimate is untouched",
     mp.strip_cost_line("≈ Already 7 portions (est. from 850 g protein), unscaled"),
     "≈ Already 7 portions (est. from 850 g protein), unscaled")
same("strip_cost_line: a euro amount without cents is not the shape", mp.strip_cost_line("≈ 18 € · x\nbody"), "≈ 18 € · x\nbody")
same("strip_cost_line: only at the start of a line", mp.strip_cost_line("cost ≈ 1.00 € here"), "cost ≈ 1.00 € here")
same("strip_cost_line: a cost line alone is nothing", mp.strip_cost_line("≈ 4.47 €"), "")
D2 = "≈ 18.40 € · 2.60 €/portion\n\nbody"
same("strip_cost_line: idempotent on the blank-line shape", mp.strip_cost_line(mp.strip_cost_line(D2)), "body")
same("strip_cost_line: round trip with cost_line",
     mp.strip_cost_line(mp.cost_line(t) + "\n" + "≈ Scaled ×1.75: 4 → 7 portions"), "≈ Scaled ×1.75: 4 → 7 portions")
# read_cost_line (fix 12)
same("read_cost_line: the spec's line", mp.read_cost_line("≈ 18.40 € · 2.60 €/portion · 3 unpriced"), (18.4, 2.6, 3))
same("read_cost_line: nothing priced yet", mp.read_cost_line("≈ 0.00 € · nothing priced yet"), (0.0, None, None))
same("read_cost_line: missing", mp.read_cost_line("Scaled ×1.75: 4 → 7 portions\n[R](mela://recipe/X)"), None)
same("read_cost_line: None / empty", (mp.read_cost_line(None), mp.read_cost_line("")), (None, None))
same("read_cost_line: a clean line reports 0 unpriced", mp.read_cost_line("≈ 8.99 € · 1.28 €/portion"), (8.99, 1.28, 0))
same("read_cost_line: no portions", mp.read_cost_line("≈ 4.47 €"), (4.47, None, 0))
same("read_cost_line: unpriced without portions", mp.read_cost_line("≈ 4.47 € · 2 unpriced"), (4.47, None, 2))
same("read_cost_line: reads it from inside a description",
     mp.read_cost_line("≈ 18.40 € · 2.60 €/portion · 3 unpriced\n\nScaled ×1.75: 4 → 7 portions"), (18.4, 2.6, 3))
same("read_cost_line: a recipe's own euro line is not the shape", mp.read_cost_line("≈ 3.00 € worth of saffron"), None)
same("read_cost_line: the yield note is not the shape", mp.read_cost_line("≈ Scaled ×1.75: 4 → 7 portions"), None)
for tot in (t, t2, mp.list_cost([], BOOK), mp.list_cost(["14 Eggs"], BOOK, portions=None),
            mp.list_cost(["2 unicorns"], BOOK)):
    got = mp.read_cost_line(mp.cost_line(tot))
    want = (tot.total, tot.per_portion, len(tot.unpriced)) if tot.priced or not tot.unpriced else (0.0, None, None)
    same(f"read_cost_line: round trip of {mp.cost_line(tot)!r}", got, want)
same("price_suffix", mp.price_suffix(1.1), " · ≈ 1.10 €")
same("price_suffix: None is nothing", mp.price_suffix(None), "")
same("price_suffix: zero is honest", mp.price_suffix(0.0), " · ≈ 0.00 €")
same("strip_price: round trip", mp.strip_price("350 g bacon" + mp.price_suffix(4.52)), "350 g bacon")
same("strip_price: untouched without a suffix", mp.strip_price("350 g bacon · smoked"), "350 g bacon · smoked")
same("strip_price: None", mp.strip_price(None), "")
same("strip_price: only a trailing suffix", mp.strip_price("≈ 1.10 € of bacon"), "≈ 1.10 € of bacon")

# ── pack_parse ─────────────────────────────────────────────────────────────
for text, want in (("10 Stk", (10, "pc")), ("100 g", (100, "g")), ("ca. 0,53 kg", (530, "g")),
                   ("1 l", (1000, "ml")), ("0,75 l", (750, "ml")), ("1 Bund", (1, "pc")),
                   ("4 Stück", (4, "pc")), ("500 ml", (500, "ml")), ("2 x 100 g", (200, "g")),
                   ("1 St", (1, "pc")), ("250g", (250, "g")), ("ca 1 kg", (1000, "g")),
                   # the comma is a decimal point, never a thousands separator (fix 4)
                   ("0,530 kg", (530, "g")), ("1,250 kg", (1250, "g")), ("2,500 l", (2500, "ml")),
                   ("1,500 g", (1.5, "g")), ("2 x 0,250 kg", (500, "g")),
                   ("", (None, None)), (None, (None, None)), ("Stk", (None, None)), ("3 Elefanten", (None, None))):
    got = mp.pack_parse(text)
    check(f"pack_parse({text!r})", got[1] == want[1] and (got[0] == want[0] or (got[0] is not None and want[0] is not None
                                                                              and abs(got[0] - want[0]) < 1e-9)),
          f"got {got!r}, want {want!r}")

# ── knuspr_search over FAKE responses (the live shapes of 2026-09-22) ──────
def prod(pid, name, pack, price, ppu, in_stock=True, archived=False, link=None):
    return {"productId": pid, "productName": name, "baseLink": link or f"{pid}-{name.lower().replace(' ', '-')}",
            "unit": pack.split()[-1], "textualAmount": pack, "price": {"full": price, "currency": "€"},
            "pricePerUnit": {"full": ppu}, "inStock": in_stock, "archived": archived}


EGGS = prod(79031, "Berliner Eisbären Eier Bodenhaltung 10er M/L", "10 Stk", 3.19, 0.32,
            link="79031-berliner-eisbaeren-eier-bodenhaltung-10er-m-l")
EGGS_OUT = prod(79032, "Eier Freiland 6er", "6 Stk", 1.49, 0.25, in_stock=False)
EGGS_BIO = prod(79033, "Bio Eier 6er", "6 Stk", 2.49, 0.42)
EGGS_GONE = prod(79034, "Eier 30er", "30 Stk", 5.99, 0.2, archived=True)
BACON = prod(11111, "Bacon in Scheiben", "100 g", 1.29, 12.9)
SPECK = prod(11112, "Speck geräuchert", "100 g", 0.99, 9.9)
OIL = prod(22222, "Olivenöl Nativ Extra", "500 ml", 7.99, 15.98)
THIGHS = prod(33333, "Hähnchenschenkel ohne Knochen", "ca. 0,53 kg", 5.05, 9.59)
SCALLIONS = prod(44444, "Lauchzwiebeln", "1 Bund", 0.89, 0.89)
NOPPU = {"productId": 55555, "productName": "Salz", "baseLink": "55555-salz", "textualAmount": "500 g",
         "price": {"full": 0.29}, "inStock": True}
FREEBIE = prod(66666, "Eier Gratis", "1 Stk", 0, 0)
FAKE = {
    "Eier": [EGGS, EGGS_OUT, EGGS_BIO, EGGS_GONE, FREEBIE],
    "Bacon": [SPECK, BACON],
    "Olivenöl": [OIL],
    "Hähnchenschenkel": [THIGHS],
    "Lauchzwiebeln": [SCALLIONS],
    "Salz": [NOPPU],
    "Berliner Eisbären Eier Bodenhaltung 10er M/L": [EGGS_BIO, dict(EGGS, price={"full": 3.49}, pricePerUnit={"full": 0.35})],
}
CALLS = []


def fake_fetch(term):
    CALLS.append(term)
    return {"status": 200, "data": {"productList": FAKE.get(term, [])}}


found = mp.knuspr_search("Eier", fake_fetch)
same("search: archived products are dropped, the rest kept in order", [p.id for p in found], [79031, 79032, 79033, 66666])
p = found[0]
same("search: eggs per pc is price / pack (0.319), not the shop's rounded 0.32", (p.per, p.per_unit, p.pack, p.price),
     (0.319, "pc", "10 Stk", 3.19))
same("search: name, stock, url", (p.name, p.in_stock, p.url),
     ("Berliner Eisbären Eier Bodenhaltung 10er M/L", True,
      "https://www.knuspr.de/79031-berliner-eisbaeren-eier-bodenhaltung-10er-m-l"))
same("search: out of stock is carried", mp.knuspr_search("Eier", fake_fetch)[1].in_stock, False)
b = [p for p in mp.knuspr_search("Bacon", fake_fetch) if p.id == 11111][0]
near("search: bacon 12.9 per kg -> 0.0129 per g", b.per, 0.0129)
same("search: bacon per unit g", b.per_unit, "g")
o = mp.knuspr_search("Olivenöl", fake_fetch)[0]
near("search: oil 15.98 per l -> 0.01598 per ml", o.per, 0.01598)
same("search: oil per unit ml", o.per_unit, "ml")
th = mp.knuspr_search("Hähnchenschenkel", fake_fetch)[0]
near("search: thighs 5.05 / 530 g agrees with 9.59 per kg within 5 percent -> 0.009528 per g", th.per, 0.009528)
same("search: thighs pack ca. 0,53 kg -> 530 g", mp.pack_parse(th.pack), (530, "g"))
# the 5 percent rule (fix 5)
same("search: price / pack within 5 percent of the tag is stored at 6 dp",
     mp.knuspr_search("x", lambda t: {"data": {"productList": [prod(1, "Eier 6er", "6 Stk", 1.99, 0.33)]}})[0].per, 0.331667)
same("search: a tag that disagrees (per kg on a Stk pack) stands as the tag",
     mp.knuspr_search("x", lambda t: {"data": {"productList": [prod(1, "Avocado", "2 Stk", 2.49, 6.99)]}})[0].per, 6.99)
same("search: a g pack whose tag disagrees takes the tag",
     mp.knuspr_search("x", lambda t: {"data": {"productList": [prod(1, "Mehl", "1 kg", 0.99, 1.49)]}})[0].per, 0.00149)
same("search: no tag and an unreadable pack is one piece at the price",
     mp.knuspr_search("x", lambda t: {"data": {"productList": [dict(NOPPU, textualAmount="Stk")]}})[0][4:6], (0.29, "pc"))
same("search: exactly 5 percent off still agrees",
     mp.knuspr_search("x", lambda t: {"data": {"productList": [prod(1, "Salz", "500 g", 0.95, 2.0)]}})[0].per, 0.0019)
same("search: 5.1 percent off does not",
     mp.knuspr_search("x", lambda t: {"data": {"productList": [prod(1, "Salz", "500 g", 0.949, 2.0)]}})[0].per, 0.002)
sc = mp.knuspr_search("Lauchzwiebeln", fake_fetch)[0]
same("search: a Bund is a piece", (sc.per, sc.per_unit), (0.89, "pc"))
sa = mp.knuspr_search("Salz", fake_fetch)[0]
near("search: no pricePerUnit -> price / pack amount", sa.per, 0.29 / 500)
same("search: nothing found", mp.knuspr_search("Einhorn", fake_fetch), [])
same("search: a fetch that raises gives []", mp.knuspr_search("x", lambda t: 1 / 0), [])
same("search: garbage JSON gives []", mp.knuspr_search("x", lambda t: {"data": "nope"}), [])
same("search: a top-level productList is read too",
     len(mp.knuspr_search("x", lambda t: {"productList": [EGGS]})), 1)
same("search: a broken item is skipped, not fatal",
     len(mp.knuspr_search("x", lambda t: {"data": {"productList": [None, "junk", EGGS]}})), 1)
check("search: a Product has the eight fields",
      mp.Product._fields == ("id", "name", "pack", "price", "per", "per_unit", "in_stock", "url"))
# junk answers never raise (fix 3)
for junk in (5, "abc", {"a": 1}, 3.5, True):
    same(f"search: productList = {junk!r} gives []", mp.knuspr_search("x", lambda t, j=junk: {"data": {"productList": j}}), [])
for answer in (None, 42, "text", [EGGS], {"data": None}, {"data": []}, {"data": {"productList": None}}):
    same(f"search: a fetch answering {answer!r:.30} gives []", mp.knuspr_search("x", lambda t, a=answer: a), [])
same("search: a fetch raising KeyError gives []", mp.knuspr_search("x", lambda t: {}["nope"]), [])

# ── pick ───────────────────────────────────────────────────────────────────
same("pick: in stock, named, cheapest per unit", mp.pick(found, "Eier").id, 79031)
same("pick: a cheaper product out of stock loses", mp.pick(found, "Eier").id != 79032, True)
same("pick: price 0 is never picked", all(p.id != 66666 for p in mp.rank(found, "Eier")), True)
same("pick: the named product beats a cheaper unnamed one", mp.pick(mp.knuspr_search("Bacon", fake_fetch), "Bacon").id, 11111)
same("pick: umlaut-blind naming", mp.pick(mp.knuspr_search("Hähnchenschenkel", fake_fetch), "Haehnchenschenkel").id, 33333)
same("pick: no product meets every term word, so any word will do (Eier)",
     mp.pick(mp.knuspr_search("Eier", fake_fetch), "Eier Bodenhaltung Bio").id, 79031)
allout = [p._replace(in_stock=False) for p in found]
same("pick: none in stock falls back on all", mp.pick(allout, "Eier").id, 79032)
same("pick: nothing", mp.pick([], "Eier"), None)
same("pick: None", mp.pick(None, "Eier"), None)
same("rank: named first, then cheapest, then the rest", [p.id for p in mp.rank(found, "Eier")], [79031, 79033])
# per is NEVER compared across bases (fix 1)
SPAETZLE = prod(70001, "Eierspätzle", "500 g", 1.99, 3.98)
found2 = mp.knuspr_search("x", lambda t: {"data": {"productList": [EGGS, SPAETZLE, EGGS_BIO]}})
same("pick: eggs (pc) beat Eierspätzle (g) although 0.004 per g is the smaller number", mp.pick(found2, "Eier").id, 79031)
same("rank: the group's own base first, then its other base", [p.id for p in mp.rank(found2, "Eier")], [79031, 79033, 70001])
found3 = mp.knuspr_search("x", lambda t: {"data": {"productList": [SPAETZLE, EGGS, EGGS_BIO]}})
same("rank: tier 1 (the whole word Eier) sets the base even when Eierspätzle comes first",
     [p.id for p in mp.rank(found3, "Eier")], [79031, 79033, 70001])
KEULE = prod(70002, "KIKOK Hähnchen Schenkel ohne Rückenstück", "ca. 1 kg", 8.29, 8.29)
LANDES = prod(70003, "Les Landes Hähnchenschenkel", "ca. 0,5 kg", 8.99, 17.99)
found4 = mp.knuspr_search("x", lambda t: {"data": {"productList": [LANDES, KEULE]}})
same("pick: 'Hähnchen Schenkel' 8.29 (spelt apart, tier 2) beats Les Landes 17.99 (tier 1): one window",
     mp.pick(found4, "Hähnchenschenkel").id, 70002)
same("rank: both in the window, cheapest per kg first", [p.id for p in mp.rank(found4, "Hähnchenschenkel")], [70002, 70003])
same("pick: a synonym (Hähnchenkeule) is not the thing asked for, however cheap (a known limit)",
     mp.pick(mp.knuspr_search("x", lambda t: {"data": {"productList": [LANDES, prod(70006, "Hähnchenkeule", "1 kg", 5.0, 5.0)]}}),
             "Hähnchenschenkel").id, 70003)
same("pick: a product MADE WITH the thing loses to the plain thing (buttermilk vs lemons)",
     mp.pick(mp.knuspr_search("x", lambda t: {"data": {"productList": [
         prod(81001, "Milram Fruchtbuttermilch Zitrone", "0,75 kg", 1.89, 2.52),
         prod(81002, "Zitronen, Netz", "500 g", 1.99, 3.98)]}}), "Zitrone").id, 81002)
same("pick: a spread mit Schnittlauch (g) loses to the bunch (pc) although it comes first",
     mp.pick(mp.knuspr_search("x", lambda t: {"data": {"productList": [
         prod(81003, "Popp Brotaufstrich Eiersalat mit Schnittlauch", "150 g", 1.99, 13.27),
         prod(81004, "Schnittlauch, Bund", "1 Bund", 0.99, 0.99)]}}), "Schnittlauch").id, 81004)
same("pick: the processed filter is off when the term asks for it (Knoblauchpulver)",
     mp.pick(mp.knuspr_search("x", lambda t: {"data": {"productList": [
         prod(81005, "Ostmann Knoblauch granuliert", "50 g", 2.39, 47.8),
         prod(81006, "Fuchs Knoblauchpulver", "45 g", 1.99, 44.2)]}}), "Knoblauchpulver").id, 81006)
same("pick: nothing plain at all falls back on the processed ones",
     mp.pick(mp.knuspr_search("x", lambda t: {"data": {"productList": [
         prod(81007, "Bürger Airfryer snack BALLS Polenta / Parmesan", "200 g", 2.49, 12.45)]}}), "Parmesan").id, 81007)
same("pick: a cheap wrong thing ranked past the window never wins (Salzstangen vs Tafelsalz)",
     mp.pick(mp.knuspr_search("x", lambda t: {"data": {"productList": [
         prod(80001, "Jeden Tag Tafelsalz", "500 g", 0.29, 0.58), prod(80002, "Bad Reichenhaller Jodsalz", "500 g", 0.79, 1.58),
         prod(80003, "Jeden Tag Salzstangen mit Meersalz", "250 g", 0.69, 2.76)]}}), "Salz").id, 80001)
same("pick: 'Hähnchen Schenkel' spelt apart is named too",
     mp.pick(mp.knuspr_search("x", lambda t: {"data": {"productList": [prod(1, "Hähnchen Schenkel", "1 kg", 9.99, 9.99)]}}),
             "Hähnchenschenkel").id, 1)
BETE = prod(70004, "Rote Bete", "500 g", 1.29, 2.58)
ZWIEBELN = prod(70005, "Rote Zwiebeln", "1 kg", 1.99, 1.99)
found5 = mp.knuspr_search("x", lambda t: {"data": {"productList": [BETE, ZWIEBELN]}})
same("pick: Rote Zwiebeln beats Rote Bete (every term word must be met)", mp.pick(found5, "Rote Zwiebeln").id, 70005)
same("rank: Rote Bete meets one word, so it follows", [p.id for p in mp.rank(found5, "Rote Zwiebeln")], [70005, 70004])
same("pick: a single in-stock product is returned", mp.pick([sc], "Lauchzwiebeln").id, 44444)
same("pick: a single product that is not named is still returned", mp.pick([sc], "Frühlingszwiebeln").id, 44444)
same("pick: an all-out-of-stock list falls back on all of it",
     mp.pick([p._replace(in_stock=False) for p in found5], "Rote Zwiebeln").id, 70005)
same("pick: nothing named, nothing meeting a word: knuspr's first",
     mp.pick(mp.knuspr_search("x", lambda t: {"data": {"productList": [SPECK, BACON]}}), "Kabeljau").id, 11112)
same("rank: with no word met knuspr's order stands",
     [p.id for p in mp.rank(mp.knuspr_search("x", lambda t: {"data": {"productList": [SPECK, BACON]}}), "Kabeljau")],
     [11112, 11111])
same("rank: a term word under 3 letters is not asked for (TK Beeren)",
     mp.pick(mp.knuspr_search("x", lambda t: {"data": {"productList": [prod(1, "Beeren Mix", "500 g", 3.99, 7.98)]}}),
             "TK Beeren").id, 1)
same("rank: the prefix is five letters, so Tomatenmark is named by Tomaten",
     mp.pick(mp.knuspr_search("x", lambda t: {"data": {"productList": [prod(1, "Tomatenmark", "200 g", 0.99, 4.95)]}}),
             "Tomaten").id, 1)
same("rank: an out-of-stock named product loses to an in-stock unnamed one",
     mp.pick(mp.knuspr_search("x", lambda t: {"data": {"productList": [prod(1, "Eier 6er", "6 Stk", 1.49, 0.25, in_stock=False),
                                                                        prod(2, "Frühstück", "1 Stk", 2.0, 2.0)]}}), "Eier").id, 2)
same("rank: accent-blind (Crème fraîche)",
     mp.pick(mp.knuspr_search("x", lambda t: {"data": {"productList": [prod(1, "Creme Fraiche 30%", "200 g", 0.99, 4.95)]}}),
             "Crème fraîche").id, 1)
same("rank: a per of None sorts last within the base",
     [p.id for p in mp.rank([sc._replace(id=1, per=None), sc._replace(id=2)], "Lauchzwiebeln")], [2, 1])

# ── entry_from ─────────────────────────────────────────────────────────────
e = mp.entry_from(th, "chicken thigh", "Hähnchenschenkel", TODAY)
same("entry_from: the book shape", e, {
    "key": "chicken thigh", "search": "Hähnchenschenkel", "product": "Hähnchenschenkel ohne Knochen",
    "product_id": 33333, "pack": "ca. 0,53 kg", "pack_amount": 530.0, "pack_unit": "g", "price": 5.05,
    "per": 0.009528, "per_unit": "g", "source": "knuspr", "date": "2026-09-22", "pinned": False,
    "url": "https://www.knuspr.de/33333-hähnchenschenkel-ohne-knochen"})
e = mp.entry_from(mp.pick(found, "Eier"), "egg", "Eier", TODAY)
same("entry_from: eggs, 10 pc a pack, per 0.319", (e["pack_amount"], e["pack_unit"], e["per"], e["per_unit"]), (10, "pc", 0.319, "pc"))
same("entry_from: a date string passes through", mp.entry_from(sc, "scallion", "Lauchzwiebeln", "2026-09-21")["date"], "2026-09-21")

# ── refresh ────────────────────────────────────────────────────────────────
BOOK_R = {"version": 1, "updated": "", "entries": {
    "salt": {"key": "salt", "price": 0.29, "pack_amount": 500, "pack_unit": "g", "per": 0.00058,
             "per_unit": "g", "source": "manual", "date": "2026-09-20"},
    "egg": {"key": "egg", "search": "Eier", "product": "Berliner Eisbären Eier Bodenhaltung 10er M/L",
            "product_id": 79031, "pack": "10 Stk", "pack_amount": 10, "pack_unit": "pc", "price": 3.19,
            "per": 0.319, "per_unit": "pc", "source": "knuspr", "date": "2026-09-20", "pinned": True,
            "url": "https://www.knuspr.de/79031-berliner-eisbaeren-eier-bodenhaltung-10er-m-l"},
    "oil": {"key": "oil", "search": "Öl", "product": "Rapsöl", "product_id": 1, "per": 0.004, "per_unit": "ml",
            "source": "knuspr", "date": "2026-09-01", "pinned": False},
    "chicken breast": {"key": "chicken breast", "search": "Hähnchenschenkel", "product": "old", "product_id": 2,
                       "per": 0.02, "per_unit": "g", "piece_g": 150, "source": "knuspr", "date": "2026-09-01",
                       "pinned": False},
}}
SLEPT = []
del CALLS[:]
res = mp.refresh(["salt", "egg", "bacon", "unicorn", "oil", "chicken breast"], BOOK_R, TODAY,
                 fetch=fake_fetch, pace=0.5, sleep=SLEPT.append)
same("refresh: manual kept, pinned re-read, new priced, unknown unpriced, a stale one kept AND stale, an old one re-priced",
     res, {"updated": ["egg", "bacon", "chicken breast"], "unpriced": ["unicorn"], "kept": ["salt", "oil"], "stale": ["oil"]})
same("refresh: the manual entry is untouched", BOOK_R["entries"]["salt"]["date"], "2026-09-20")
same("refresh: the pinned entry searched its own product name", CALLS[0], "Berliner Eisbären Eier Bodenhaltung 10er M/L")
eg = BOOK_R["entries"]["egg"]
same("refresh: the pinned entry took the new price (3.49 / 10 = 0.349), kept product, id, search and pin",
     (eg["price"], eg["per"], eg["product_id"], eg["search"], eg["pinned"], eg["date"]),
     (3.49, 0.349, 79031, "Eier", True, "2026-09-22"))
same("refresh: a new key is searched by its default term", CALLS[1], "Bacon")
bc = BOOK_R["entries"]["bacon"]
same("refresh: the new entry", (bc["product_id"], bc["per"], bc["per_unit"], bc["pack_amount"], bc["source"], bc["pinned"]),
     (11111, 0.0129, "g", 100, "knuspr", False))
same("refresh: an unknown key stays out of the book", "unicorn" in BOOK_R["entries"], False)
same("refresh: the unknown key was searched by itself", CALLS[2], "unicorn")
same("refresh: the stale entry stays when nothing is found", BOOK_R["entries"]["oil"]["date"], "2026-09-01")
same("refresh: an old entry's search term is reused", CALLS[3], "Öl")
same("refresh: an old entry's piece_g survives a re-price", BOOK_R["entries"]["chicken breast"].get("piece_g"), 150)
same("refresh: sleep between network calls only (5 calls, 4 sleeps)", (len(CALLS), SLEPT), (5, [0.5] * 4))
same("refresh: the book is stamped", BOOK_R["updated"], "2026-09-22")
same("refresh: a pinned product that vanished is kept, not stale (the pin holds)",
     mp.refresh(["egg"], {"entries": {"egg": dict(eg, product="Nirgendwo")}}, TODAY, fetch=fake_fetch, sleep=lambda s: None),
     {"updated": [], "unpriced": [], "kept": ["egg"], "stale": []})
b_empty = {"entries": {}}
same("refresh: no keys, no calls, still stamped",
     (mp.refresh([], b_empty, TODAY, fetch=lambda t: 1 / 0, sleep=lambda s: None), b_empty["updated"]),
     ({"updated": [], "unpriced": [], "kept": [], "stale": []}, "2026-09-22"))
b0 = {}
mp.refresh([], b0, TODAY, fetch=fake_fetch, sleep=lambda s: None)
same("refresh: version + entries + updated on an empty dict", (b0.get("version"), b0.get("entries"), b0.get("updated")),
     (1, {}, "2026-09-22"))
same("refresh: pace 0 never sleeps",
     (mp.refresh(["bacon", "egg"], {"entries": {}}, TODAY, fetch=fake_fetch, pace=0, sleep=SLEPT.append), len(SLEPT)),
     ({"updated": ["bacon", "egg"], "unpriced": [], "kept": [], "stale": []}, 4))
# a pinned entry without a product name is KEPT as it is (fix 6)
PIN_NONAME = {"key": "egg", "search": "Eier", "product": "", "product_id": None, "per": 0.5, "per_unit": "pc",
              "source": "knuspr", "date": "2026-09-01", "pinned": True}
b_pin = {"entries": {"egg": dict(PIN_NONAME)}}
del CALLS[:]
same("refresh: a pinned entry with no product name is kept, never re-picked",
     mp.refresh(["egg"], b_pin, TODAY, fetch=fake_fetch, sleep=lambda s: None),
     {"updated": [], "unpriced": [], "kept": ["egg"], "stale": []})
same("refresh: ... and not searched at all", CALLS, [])
same("refresh: ... still pinned, price and date untouched", b_pin["entries"]["egg"], PIN_NONAME)
b_pin2 = {"entries": {"egg": dict(PIN_NONAME, product=None)}}
same("refresh: product None counts as no name", mp.refresh(["egg"], b_pin2, TODAY, fetch=fake_fetch, sleep=lambda s: None)["kept"],
     ["egg"])
same("refresh: ... pinned survives", b_pin2["entries"]["egg"]["pinned"], True)
# stale: an old knuspr entry the shop no longer answers for (fix 6)
b_stale = {"entries": {"oil": {"key": "oil", "search": "Öl", "product": "Rapsöl", "product_id": 1, "per": 0.004,
                               "per_unit": "ml", "source": "knuspr", "date": "2026-09-01", "pinned": False}}}
r = mp.refresh(["oil", "unicorn"], b_stale, TODAY, fetch=fake_fetch, sleep=lambda s: None)
same("refresh: the result carries the four lists", sorted(r), ["kept", "stale", "unpriced", "updated"])
same("refresh: a stale entry is under kept AND stale, an unknown key only under unpriced",
     (r["kept"], r["stale"], r["unpriced"]), (["oil"], ["oil"], ["unicorn"]))
same("refresh: the stale entry is byte for byte what it was", b_stale["entries"]["oil"]["date"], "2026-09-01")
same("refresh: a manual entry is kept, never stale",
     mp.refresh(["salt"], {"entries": {"salt": {"source": "manual", "per": 1, "per_unit": "g"}}}, TODAY, fetch=fake_fetch,
                sleep=lambda s: None), {"updated": [], "unpriced": [], "kept": ["salt"], "stale": []})
# never raises on a fetch that throws or answers junk (fix 3)
for bad in (lambda t: 1 / 0, lambda t: None, lambda t: 42, lambda t: "junk", lambda t: {"data": {"productList": 7}},
            lambda t: {"data": {"productList": "abc"}}, lambda t: [EGGS]):
    try:
        r = mp.refresh(["bacon", "oil"], {"entries": {"oil": {"source": "knuspr", "product": "x", "per": 1, "per_unit": "ml"}}},
                       TODAY, fetch=bad, sleep=lambda s: None)
        same("refresh: a bad fetch is an unpriced new key and a stale old one", r,
             {"updated": [], "unpriced": ["bacon"], "kept": ["oil"], "stale": ["oil"]})
    except Exception as exc:                                     # noqa: BLE001
        check("refresh: a bad fetch never raises", False, repr(exc))
try:
    r = mp.refresh(["egg"], {"entries": {"egg": dict(eg, product="Eier")}}, TODAY, fetch=lambda t: 1 / 0, sleep=lambda s: None)
    same("refresh: a pinned re-read over a fetch that throws is kept", r["kept"], ["egg"])
except Exception as exc:                                         # noqa: BLE001
    check("refresh: a pinned re-read over a fetch that throws never raises", False, repr(exc))

# ── load_book / save_book in a temp dir ────────────────────────────────────
TMP = tempfile.mkdtemp(prefix="tickal_meal_price_")
mp.BOOK_PATH = os.path.join(TMP, "sub", "meal_prices.json")
same("load_book: missing file is an empty book", mp.load_book(), {"version": 1, "updated": "", "entries": {}})
mp.save_book(BOOK_R)
check("save_book: mkdir -p and the file lands at BOOK_PATH", os.path.exists(mp.BOOK_PATH))
check("save_book: no temp file left", not os.path.exists(mp.BOOK_PATH + ".tmp"))
same("load_book: round trip", mp.load_book(), BOOK_R)
with open(mp.BOOK_PATH, encoding="utf-8") as fh:
    raw = fh.read()
check("save_book: readable JSON, umlauts unescaped", "Hähnchenschenkel" in raw and json.loads(raw)["version"] == 1)
other = os.path.join(TMP, "other.json")
mp.save_book({"version": 1, "updated": "x", "entries": {"a": {"per": 1, "per_unit": "g"}}}, other)
same("save_book/load_book: an explicit path", mp.load_book(other)["entries"]["a"]["per"], 1)
with open(other, "w") as fh:
    fh.write("{not json")
same("load_book: unreadable is an empty book", mp.load_book(other)["entries"], {})
with open(other, "w") as fh:
    fh.write('{"entries": []}')
same("load_book: a wrong shape is an empty book", mp.load_book(other), {"version": 1, "updated": "", "entries": {}})
with open(other, "w") as fh:
    fh.write('{"entries": {"b": {}}}')
same("load_book: missing version/updated are filled", mp.load_book(other), {"version": 1, "updated": "", "entries": {"b": {}}})
check("BOOK_PATH ends in meal_prices.json under the config dir by birth",
      mp._BOOK_PATH_BORN == os.path.expanduser("~/.ticktick_alfred/meal_prices.json"))
check("the module never wrote the real book during this run",
      not os.path.exists(mp._BOOK_PATH_BORN + ".tmp"))

# ── keys_of ────────────────────────────────────────────────────────────────
same("keys_of: distinct, in order, headers and water out",
     mp.keys_of(["**Meat**", "350 g bacon", "14 Eggs", "200 g bacon", "1 cup water", "CHICKEN", "Avocado oil", "", "2 large eggs"]),
     ["bacon", "egg", "avocado oil"])
same("keys_of: None", mp.keys_of(None), [])
same("keys_of: the module's own suffix is ignored (fix 2)",
     mp.keys_of(["350 g bacon · ≈ 4.52 €", "14 Eggs · ≈ 4.47 €", "1 cup water · ≈ 0.00 €", "Avocado oil"]),
     ["bacon", "egg", "avocado oil"])
same("keys_of: a suffixed and a bare line of one ingredient are one key",
     mp.keys_of(["14 Eggs · ≈ 4.47 €", "2 eggs"]), ["egg"])

# ── parse_price_answer, manual_entry (fix 13) ──────────────────────────────
for text, want in (("2.99 / 10 pc", (2.99, 10.0, "pc")), ("2,99 / 10 Stk", (2.99, 10.0, "Stk")),
                   ("1.49 / 100 g", (1.49, 100.0, "g")), ("7.97 / 1 l", (7.97, 1.0, "l")),
                   ("3.19/10pc", (3.19, 10.0, "pc")), ("0.89 / 1 Bund", (0.89, 1.0, "Bund")),
                   ("2.99", (2.99, 1.0, "pc")), ("  2.99  ", (2.99, 1.0, "pc")), ("2.99 €", (2.99, 1.0, "pc")),
                   ("€ 2.99 / 6 Stück", (2.99, 6.0, "Stück")), ("2.99 / 10", (2.99, 10.0, "pc")),
                   ("2.99 / kg", (2.99, 1.0, "kg")), ("0.5 / 250 ml", (0.5, 250.0, "ml")), ("3", (3.0, 1.0, "pc"))):
    same(f"parse_price_answer({text!r})", mp.parse_price_answer(text), want)
for garbage in ("", None, "abc", "2.99 / 10 pc extra", "/ 10 pc", "2.99 / 0 pc", "-2.99", "2.99 / -1 pc", "2.99 / 10 pc / 2",
                "2.99 // 10"):
    try:
        got = mp.parse_price_answer(garbage)
        check(f"parse_price_answer({garbage!r}) raises", False, f"got {got!r}")
    except ValueError as exc:
        check(f"parse_price_answer({garbage!r}) raises ValueError, one line", "\n" not in str(exc) and str(exc), repr(exc))
    except Exception as exc:                                     # noqa: BLE001
        check(f"parse_price_answer({garbage!r}) raises ValueError", False, repr(exc))

m = mp.manual_entry("egg", 2.99, 10, "pc", TODAY)
same("manual_entry: the book shape, source manual, no product behind it", m, {
    "key": "egg", "search": "", "product": "", "product_id": None, "pack": "10 pc", "pack_amount": 10.0,
    "pack_unit": "pc", "price": 2.99, "per": 0.299, "per_unit": "pc", "source": "manual", "date": "2026-09-22",
    "pinned": False, "url": ""})
check("manual_entry: the keys are entry_from's keys", set(m) == set(mp.entry_from(th, "chicken thigh", "x", TODAY)))
for args, want in ((("flour", 1.49, 100, "g"), (100.0, "g", 0.0149)), (("milk", 7.97, 1, "l"), (1000.0, "ml", 0.00797)),
                   (("stock", 0.5, 500, "ml"), (500.0, "ml", 0.001)), (("rice", 2.0, 2, "kg"), (2000.0, "g", 0.001)),
                   (("pork", 4.54, 1, "lb"), (454.0, "g", 0.01)), (("egg", 2.99, 12, "Stk"), (12.0, "pc", 0.249167)),
                   (("egg", 0.3, 1, "Stück"), (1.0, "pc", 0.3)), (("avocado", 1.0, 1, "piece"), (1.0, "pc", 1.0)),
                   (("avocado", 2.0, 2, "pieces"), (2.0, "pc", 1.0)), (("parsley", 0.89, 1, "Bund"), (1.0, "pc", 0.89)),
                   (("cream", 1.2, 1, "cup"), (240.0, "ml", 0.005)), (("tomato", 0.99, 1, "can"), (1.0, "pc", 0.99)),
                   (("butter", 2.5, 8.8, "oz"), (249.48, "g", 0.010021)), (("egg", 2.99, 10, ""), (10.0, "pc", 0.299)),
                   (("egg", 2.99, 10, "PC"), (10.0, "pc", 0.299)), (("egg", 2.99, 10, "stk."), (10.0, "pc", 0.299)),
                   (("salt", "0,29", "500", "g"), (500.0, "g", 0.00058))):
    got = mp.manual_entry(*args, TODAY)
    check(f"manual_entry{args!r} -> {want!r}",
          (got["pack_amount"], got["pack_unit"], got["per"]) == want and got["per_unit"] == want[1] and got["source"] == "manual",
          f"got {(got['pack_amount'], got['pack_unit'], got['per'])!r}")
same("manual_entry: the pack text keeps the unit as typed", mp.manual_entry("egg", 2.99, 12, "Stk", TODAY)["pack"], "12 Stk")
same("manual_entry: a fractional amount reads like a cook's", mp.manual_entry("oil", 3.99, 0.5, "l", TODAY)["pack"], "0.5 l")
same("manual_entry: a search rides along", mp.manual_entry("egg", 2.99, 10, "pc", TODAY, search="Bio Eier")["search"], "Bio Eier")
same("manual_entry: the date string passes through", mp.manual_entry("egg", 2.99, 10, "pc", "2026-09-21")["date"], "2026-09-21")
same("manual_entry: the key is stripped", mp.manual_entry("  egg ", 2.99, 10, "pc", TODAY)["key"], "egg")
same("manual_entry: a price of zero is allowed (already in the house)", mp.manual_entry("salt", 0, 1, "pc", TODAY)["per"], 0.0)
for args in (("", 2.99, 10, "pc"), (None, 2.99, 10, "pc"), ("egg", "lots", 10, "pc"), ("egg", 2.99, "ten", "pc"),
             ("egg", 2.99, 0, "pc"), ("egg", 2.99, -1, "pc"), ("egg", -2.99, 10, "pc"), ("egg", 2.99, 10, "elephants"),
             ("egg", float("inf"), 10, "pc"), ("egg", None, 10, "pc"), ("egg", 2.99, float("nan"), "pc")):
    try:
        got = mp.manual_entry(*args, TODAY)
        check(f"manual_entry{args!r} raises", False, f"got {got!r}")
    except ValueError as exc:
        check(f"manual_entry{args!r} raises ValueError, one line", "\n" not in str(exc) and str(exc), repr(exc))
    except Exception as exc:                                     # noqa: BLE001
        check(f"manual_entry{args!r} raises ValueError", False, repr(exc))
# the round trip: what Vex types becomes an entry the costing reads
price, amount, unit = mp.parse_price_answer("2,99 / 10 Stk")
b_hand = {"entries": {"egg": mp.manual_entry("egg", price, amount, unit, TODAY)}}
same("manual_entry: 14 eggs at 2.99 / 10 Stk cost 4.19", mp.line_cost("14 Eggs", b_hand).cost, 4.19)
same("manual_entry: refresh leaves it alone",
     mp.refresh(["egg"], b_hand, TODAY, fetch=fake_fetch, sleep=lambda s: None)["kept"], ["egg"])
same("manual_entry: search_term falls through to the table (no search typed)", mp.search_term("egg", b_hand), "Eier")
b_hand2 = {"entries": {"egg": mp.manual_entry("egg", price, amount, unit, TODAY, search="Bio Eier")}}
same("manual_entry: a typed search is what search_term says", mp.search_term("egg", b_hand2), "Bio Eier")

# ── the real book was never touched, the temp dir goes ─────────────────────
same("the real book's existence and mtime are what they were at the start",
     (os.path.exists(REAL_BOOK), os.path.getmtime(REAL_BOOK) if os.path.exists(REAL_BOOK) else None), REAL_BOOK_BEFORE)
shutil.rmtree(TMP, ignore_errors=True)
check("the temp dir is gone", not os.path.exists(TMP))

print(f"\ntest_meal_price: {COUNT[0] - len(FAILS)} passed, {len(FAILS)} failed")
if __name__ == "__main__":
    sys.exit(1 if FAILS else 0)
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
