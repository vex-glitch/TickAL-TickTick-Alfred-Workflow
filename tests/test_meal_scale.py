#!/usr/bin/env python3
"""Unit suite for src/meal_scale.py (yield inference + ingredient scaling,
and carry_ticks: a re-cut list's ticks following the ingredient name, the
portions verb's helper, 2026-09-22).
Run: python3 tests/test_meal_scale.py
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import meal_scale as ms  # noqa: E402

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


def same(name, got, want):
    check(name, got == want, f"got {got!r}, want {want!r}")


def R(**fields):
    """A Mela recipe as the caller hands it: a dict of strings."""
    return fields


# ── scale_line: the worked rows (4 -> 7 portions = x1.75, 3 -> 7 = x2.33) ──
ROWS_175 = [
    ("500 g chicken breast, boneless and skinless, cut into 1-inch cubes",
     "875 g chicken breast, boneless and skinless, cut into 1-inch cubes"),
    ("1/4 tsp salt", "1/2 tsp salt"),
    ("1 1/2 tsp sesame oil", "2 3/4 tsp sesame oil"),      # half-up: round() says 2 1/2
    ("1.2 kg petite top sirloin , thinly sliced", "2.1 kg petite top sirloin , thinly sliced"),
    ("2 scallions", "4 scallions"),
    ("1/3 cup roasted/unsalted peanuts", "1/2 cup roasted/unsalted peanuts"),
    ("10 dried chilies, cut into 2 cm pieces", "18 dried chilies, cut into 2 cm pieces"),
    ("1 lb ground pork", "1 3/4 lb ground pork"),
    ("2 tbsp chili crisp", "3 1/2 tbsp chili crisp"),
    ("Avocado oil", "Avocado oil"),
    ("Bok choy or choy sum (for blanching)", "Bok choy or choy sum (for blanching)"),
]
for src, want in ROWS_175:
    same(f"x1.75: {src[:30]}", ms.scale_line(src, 1.75), want)

ROWS_233 = [
    ("500 g chicken breast, boneless and skinless, cut into 1-inch cubes",
     "1165 g chicken breast, boneless and skinless, cut into 1-inch cubes"),
    ("1 1/2 tsp sesame oil", "3 1/2 tsp sesame oil"),
    ("1.2 kg petite top sirloin , thinly sliced", "2.8 kg petite top sirloin , thinly sliced"),
    ("2 scallions", "5 scallions"),
    ("1/3 cup roasted/unsalted peanuts", "3/4 cup roasted/unsalted peanuts"),
    ("1 lb ground pork", "2 1/4 lb ground pork"),
    ("2 tbsp chili crisp", "4 3/4 tbsp chili crisp"),
]
for src, want in ROWS_233:
    same(f"x2.33: {src[:30]}", ms.scale_line(src, 2.33), want)

# ── rounding floors, plurals, ranges, glue ─────────────────────────────────
same("a pinch scaled down is still a pinch", ms.scale_line("1/4 tsp salt", 0.5), "1/4 tsp salt")
same("cup pluralises past 1", ms.scale_line("1/2 cup oats", 3), "1 1/2 cups oats")
same("can pluralises", ms.scale_line("1 can chickpeas", 2), "2 cans chickpeas")
same("cloves back to singular", ms.scale_line("3 cloves garlic", 0.3), "1 clove garlic")
same("a range scales both ends", ms.scale_line("2-3 cloves garlic", 1.75), "4-5 cloves garlic")
same("a 'to' range", ms.scale_line("2 to 3 eggs", 2), "4-6 eggs")
same("x is not a unit", ms.scale_line("2 x 400 g cans tomatoes", 2), "4 x 400 g cans tomatoes")
same("count never rounds to zero", ms.scale_line("1 egg", 0.3), "1 egg")
same("grams to the nearest 5 above 50", ms.scale_line("450g chicken thighs", 1.75),
     "790 g chicken thighs")
same("whole grams under 50", ms.scale_line("20 g butter", 1.75), "35 g butter")
same("one decimal under a gram", ms.scale_line("1 g saffron", 0.5), "0.5 g saffron")
same("ml like grams", ms.scale_line("500 ml stock", 1.75), "875 ml stock")
same("litres to one decimal", ms.scale_line("1 l water", 1.75), "1.8 l water")
same("kg drops a trailing .0", ms.scale_line("1 kg potatoes", 2), "2 kg potatoes")
same("oz to halves", ms.scale_line("8 oz cream cheese", 1.75), "14 oz cream cheese")
same("oz never below a half", ms.scale_line("1 oz nuts", 0.3), "1/2 oz nuts")
same("aliases come out canonical", ms.scale_line("2 tablespoons soy sauce", 2), "4 tbsp soy sauce")
same("a glued comma stays glued", ms.scale_line("450g, diced", 1.75), "790 g, diced")
same("header lines untouched", ms.scale_line("# Sauce", 2), "# Sauce")
same("blank lines untouched", ms.scale_line("", 2), "")
same("a whole number of spoons", ms.scale_line("1 tsp cumin", 2), "2 tsp cumin")
same("half-up at exactly .5 on a count", ms.scale_line("1 onion", 2.5), "3 onion")

# ── parse_quantity ─────────────────────────────────────────────────────────
q = ms.parse_quantity("450g chicken thighs")
same("glued unit: amount", q.amount, 450)
same("glued unit: unit", q.unit, "g")
same("glued unit: rest", q.rest, "chicken thighs")
q = ms.parse_quantity("1½ cups oats")
same("glued vulgar: amount", q.amount, 1.5)
same("glued vulgar: unit", q.unit, "cup")
same("spaced vulgar", ms.parse_quantity("1 ½ cups oats").amount, 1.5)
same("bare vulgar", ms.parse_quantity("½ tsp salt").amount, 0.5)
q = ms.parse_quantity("1,5 kg potatoes")
same("comma decimal: amount", q.amount, 1.5)
same("comma decimal: unit", q.unit, "kg")
same("comma thousands", ms.parse_quantity("1,500 g flour").amount, 1500)
q = ms.parse_quantity("2 x 400 g cans tomatoes")
same("x keeps the rest whole", (q.amount, q.unit, q.rest), (2, None, "x 400 g cans tomatoes"))
same("an adjective is not a unit", ms.parse_quantity("2 large eggs").rest, "large eggs")
same("no unit, plain count", ms.parse_quantity("2 scallions")[:4], (2, "2", None, "scallions"))
q = ms.parse_quantity("1 1/2 tsp sesame oil")
same("mixed number", (q.amount, q.amount_text, q.unit, q.rest), (1.5, "1 1/2", "tsp", "sesame oil"))
q = ms.parse_quantity("2-3 cloves garlic")
same("range: lo/hi", (q.amount, q.range_hi), (2, 3))
same("range: text", q.amount_text, "2-3")
same("range with 'to'", ms.parse_quantity("2 to 3 eggs").range_hi, 3)
same("no number at all", ms.parse_quantity("Avocado oil"), ms.Qty(None, "", None, "Avocado oil", None))
same("a broken import line has no amount",
     ms.parse_quantity("g Frozen summer berries (approx. 1.25 cups)").amount, None)
same("1-inch is not a quantity", ms.parse_quantity("1-inch piece ginger").amount, None)
same("a mixed number followed by -inch is not a range",
     ms.parse_quantity("1 1/2-inch piece ginger").amount, None)
same("unit with a period", ms.parse_quantity("2 tbsp. olive oil")[2:4], ("tbsp", "olive oil"))
same("unit is case-blind", ms.parse_quantity("2 TBSP olive oil").unit, "tbsp")

# ── infer_yield: the ladder ────────────────────────────────────────────────
same("field: '3'", ms.infer_yield(R(yield_text="3"))[:2], (3, "field"))
same("field: '4 servings'", ms.infer_yield(R(yield_text="4 servings"))[:2], (4, "field"))
same("field: '2-3' is the midpoint", ms.infer_yield(R(yield_text="2-3"))[:2], (2.5, "field"))
same("field outranks text", ms.infer_yield(R(yield_text="3", text="serves 4"))[:2], (3, "field"))
same("field: 550 is not a yield", ms.infer_yield(R(yield_text="550"))[1], "none")
same("an object recipe works too", ms.infer_yield(SimpleNamespace(yield_text="4"))[:2], (4, "field"))
TEXT_HITS = [
    ("(Macros: Per Serving - 7 Total)", 7),
    ("Per Burrito - 10 Total)", 10),
    ("makes 7", 7),
    ("Serves 3 |550 calo", 3),
    ("# SERVES: 2", 2),
    ("makes 13", 13),
    ("(serves 4)", 4),
    ("Makes 4)", 4),
    ("serves 4-6", 5),
    ("Serves 4 to 6 people", 5),
    ("makes about 12", 12),
    ("enough for 4 large burritos", 4),
    ("Yield: 6 muffins", 6),
    ("2 portions", 2),
]
for txt, want in TEXT_HITS:
    same(f"text: {txt!r}", ms.infer_yield(R(text=txt))[:2], (want, "text"))
TEXT_MISSES = ["Total Time: 20 minutes", "Total: 45 min", "makes 2 cups", "cut into 8 pieces",
               "for the other 9 burritos", "3. Serve with rice", "serves 550", "Per serving",
               "Serving size: 1 serving", "Bake for 20 minutes", "550 total calories"]
for txt in TEXT_MISSES:
    same(f"no yield in {txt!r}", ms.infer_yield(R(text=txt)), (None, "none", ""))

same("'N total' outranks 'serves N'",
     ms.infer_yield(R(text="serves 4", nutrition="(Per Serving - 7 Total)"))[0], 7)
same("detail names the field",
     ms.infer_yield(R(nutrition="Serves 3 |550 calo"))[2], "'Serves 3' in nutrition")
same("detail: field", ms.infer_yield(R(yield_text="2-3"))[2], "'2-3' in yield")
same("a remark in the ingredients is read",
     ms.infer_yield(R(ingredients="1 tsp salt\n(serves 4)"))[:2], (4, "text"))

# ── the protein estimate (170 g a portion) ─────────────────────────────────
same("estimate: chicken + pork", ms.infer_yield(R(ingredients="500 g chicken breast\n1 lb ground pork")),
     (6, "estimate", "954 g protein"))
same("estimate: 850 g -> 5", ms.infer_yield(R(ingredients="850 g chicken thighs"))[:2], (5, "estimate"))
same("stock is not protein", ms.infer_yield(R(ingredients="500 ml chicken stock"))[1], "none")
same("nor is powder", ms.infer_yield(R(ingredients="500 g chicken stock powder"))[1], "none")
same("nor chili crisp", ms.infer_yield(R(ingredients="2 tbsp chili crisp"))[1], "none")
same("nor chicken skin", ms.infer_yield(R(ingredients="300 g chicken skin"))[1], "none")
same("bone-in, skin-on IS the meat",
     ms.infer_yield(R(ingredients="1 kg bone-in, skin-on chicken thighs"))[:2], (6, "estimate"))
same("under 100 g is no estimate", ms.infer_yield(R(ingredients="50 g chicken"))[1], "none")
same("a range counts its midpoint", ms.protein_grams(R(ingredients="400-500 g chicken thighs")), 450)
same("kg, lb and oz convert", ms.protein_grams(R(ingredients="1 kg beef\n1 lb pork\n8 oz tofu")),
     1000 + 454 + 8 * 28.35)
same("text outranks the estimate",
     ms.infer_yield(R(text="serves 2", ingredients="850 g chicken thighs"))[:2], (2, "text"))
same("nothing at all", ms.infer_yield(R()), (None, "none", ""))
same("None is survivable", ms.infer_yield(None), (None, "none", ""))

# ── the note ───────────────────────────────────────────────────────────────
same("note: scaled from a field", ms.scaled_ingredients(R(yield_text="4", ingredients="1 tsp salt"))[1]["note"],
     "Scaled ×1.75: 4 → 7 portions")
same("note: estimate", ms.scaled_ingredients(R(ingredients="850 g chicken thighs"))[1]["note"],
     "≈ Scaled ×1.4: est. 5 portions from 850 g protein → 7")
same("note: already", ms.scaled_ingredients(R(yield_text="7", ingredients="1 tsp salt"))[1]["note"],
     "Already 7 portions, unscaled")
same("note: unknown", ms.scaled_ingredients(R(ingredients="1 tsp salt"))[1]["note"],
     "⚠️ Yield unknown, quantities unscaled")
same("note: ⚠️ at factor 7", ms.scaled_ingredients(R(yield_text="1", ingredients="1 egg"))[1]["note"],
     "⚠️ check yield · Scaled ×7: 1 → 7 portions")
same("note: ⚠️ at a tiny factor", ms.scaled_ingredients(R(yield_text="40"), portions=2)[1]["note"][:16],
     "⚠️ check yield ·")
same("note: factor to two decimals", ms.scaled_ingredients(R(yield_text="3"))[1]["note"],
     "Scaled ×2.33: 3 → 7 portions")
same("note: a midpoint yield", ms.scaled_ingredients(R(yield_text="2-3"), portions=5)[1]["note"],
     "Scaled ×2: 2.5 → 5 portions")

# ── is_grocery_item ────────────────────────────────────────────────────────
for bad in ("1. Heat the oil", "Macros (Per Serving)", "Protein: 45 g", "6 g Fibre: (Estimated)",
            "(serves 4)", "For the sauce:", "", "   ", "# Sauce", "Step 2) Stir well",
            "Fat - 20 g", "Calories: 550", "Makes 4)"):
    check(f"not grocery: {bad!r}", not ms.is_grocery_item(bad))
for good in ("1 scoop protein powder", "1 tbsp bacon fat", "500 g chicken breast", "Avocado oil",
             "1 tsp sugar, or to taste", "2 cups protein-rich flour", "1.5 kg potatoes",
             "Bok choy or choy sum (for blanching)", "g Frozen summer berries (approx. 1.25 cups)",
             "2 tbsp fat-free yoghurt"):
    check(f"grocery: {good!r}", ms.is_grocery_item(good))

# ── scaled_ingredients ─────────────────────────────────────────────────────
ING = "\n".join([
    "# Marinade",
    "500 g chicken breast, boneless and skinless, cut into 1-inch cubes",
    "1 1/2 tsp sesame oil",
    "# Salad",
    "g Frozen summer berries (approx. 1.25 cups)",      # a broken Mela import line
    "Avocado oil",
    "1. Heat the oil",
    "Protein: 45 g",
    "(serves 4)",
])
out, info = ms.scaled_ingredients(R(yield_text="4", ingredients=ING))
same("headers dropped by default, rows scaled", out,
     ["875 g chicken breast, boneless and skinless, cut into 1-inch cubes", "2 3/4 tsp sesame oil",
      "g Frozen summer berries (approx. 1.25 cups)", "Avocado oil"])
same("unscaled lines are reported", info["unscaled"],
     ["g Frozen summer berries (approx. 1.25 cups)", "Avocado oil"])
same("dropped lines are counted", info["dropped"], 3)
same("info keys", sorted(info),
     ["detail", "dropped", "factor", "note", "portions", "source", "unscaled", "yield"])
same("info: factor/yield/source/portions",
     (info["factor"], info["yield"], info["source"], info["portions"]), (1.75, 4, "field", 7))
out_b, _ = ms.scaled_ingredients(R(yield_text="4", ingredients=ING), headers="bold")
same("bold headers", [x for x in out_b if x.startswith("**")], ["**Marinade**", "**Salad**"])
same("a bold header keeps its place", out_b[0], "**Marinade**")
same("yield read from the ingredients remark", ms.scaled_ingredients(R(ingredients=ING))[1]["yield"], 4)
same("unscaled at factor 1 keeps the line as written",
     ms.scaled_ingredients(R(yield_text="7", ingredients="450g chicken"))[0], ["450g chicken"])
same("unknown yield keeps the line as written",
     ms.scaled_ingredients(R(ingredients="450g rice"))[0], ["450g rice"])
same("a protein line alone gives an estimate, and scales",
     ms.scaled_ingredients(R(ingredients="450g chicken"))[0], ["1050 g chicken"])
same("portions is a parameter",
     ms.scaled_ingredients(R(yield_text="2", ingredients="1 cup rice"), portions=4)[0], ["2 cups rice"])
same("an object recipe scales",
     ms.scaled_ingredients(SimpleNamespace(yield_text="4", ingredients="2 tbsp oil"))[0], ["3 1/2 tbsp oil"])
same("headers='keep' leaves them as written",
     ms.scaled_ingredients(R(yield_text="7", ingredients="# Sauce\n1 tsp salt"), headers="keep")[0],
     ["# Sauce", "1 tsp salt"])

# ── helpers ────────────────────────────────────────────────────────────────
same("lines strips and drops blanks", ms.lines(" a \n\n b\r\n"), ["a", "b"])
same("is_header", (ms.is_header("  # Sauce"), ms.is_header("Sauce")), (True, False))
same("header_text", ms.header_text("## Sauce "), "Sauce")
same("_get on a missing key", ms._get({}, "title"), "")
same("_get on an object", ms._get(SimpleNamespace(title="x"), "title"), "x")
same("_get joins a list", ms._get({"ingredients": ["a", "b"]}, "ingredients"), "a\nb")

# ── carry_ticks: a re-cut list keeps its ticks by ingredient name ──────────
OLD_ITEMS = [{"id": "i1", "status": 2, "title": "875 g chicken", "sortOrder": 0},
             {"id": "i2", "status": 0, "title": "1 3/4 tbsp oil", "sortOrder": 1},
             {"id": "i3", "status": 2, "title": "**Sauce**", "sortOrder": 2},
             {"id": "i4", "status": 2, "title": "1 tsp salt", "sortOrder": 3},
             {"id": "i5", "status": 0, "title": "Avocado oil", "sortOrder": 4}]
NEW_LINES = ["625 g chicken", "1 1/4 tbsp oil", "**Sauce**", "3/4 tsp salt", "3/4 tsp salt",
             "Avocado oil", "2 eggs"]
out = ms.carry_ticks(OLD_ITEMS, NEW_LINES)
same("carry_ticks: the lines, in order", [it["title"] for it in out], NEW_LINES)
same("carry_ticks: ticked carried by name past a new amount, a header keyed whole, an open item"
     " stays open, a duplicate name consumed once, a new line open",
     [it["status"] for it in out], [2, 0, 2, 2, 0, 0, 0])
same("carry_ticks: sortOrder sequential, the sync's own keys, no ids",
     ([it["sortOrder"] for it in out], sorted(out[0])), (list(range(7)), ["sortOrder", "status", "title"]))
same("carry_ticks: None old items = every line open",
     ms.carry_ticks(None, ["1 egg", "2 tsp salt"]), [{"title": "1 egg", "status": 0, "sortOrder": 0},
                                                     {"title": "2 tsp salt", "status": 0, "sortOrder": 1}])
same("carry_ticks: empty old items, empty lines", (ms.carry_ticks([], ["1 egg"])[0]["status"], ms.carry_ticks(OLD_ITEMS, [])),
     (0, []))
same("carry_ticks: case and spacing do not break a match",
     ms.carry_ticks([{"status": 2, "title": "500 g  Chicken"}], ["875 g chicken"])[0]["status"], 2)
same("carry_ticks: the unit's plural is not part of the key",
     ms.carry_ticks([{"status": 2, "title": "1 cup oats"}], ["1 3/4 cups oats"])[0]["status"], 2)
same("carry_ticks: a status given as text counts, a stray non-dict is skipped",
     ms.carry_ticks([{"status": "2", "title": "1 egg"}, None, "x"], ["2 egg"])[0]["status"], 2)
same("carry_ticks: a tick follows its ORDINAL, the sauce's salt does not jump to the marinade's",
     [it["status"] for it in ms.carry_ticks([{"title": "1 tsp salt", "status": 0}, {"title": "875 g chicken", "status": 0},
                                              {"title": "2 tbsp salt", "status": 2}],
                                             ["3/4 tsp salt", "625 g chicken", "1 1/2 tbsp salt"])], [0, 0, 2])
same("carry_ticks: an ordinal that is gone falls back to the first open line of that key",
     [it["status"] for it in ms.carry_ticks([{"title": "1 tsp salt", "status": 0}, {"title": "2 tbsp salt", "status": 2}],
                                             ["3/4 tsp salt"])], [2])
same("carry_ticks: two old ticks carry to two new lines, a third stays open",
     [it["status"] for it in ms.carry_ticks([{"status": 2, "title": "1 tsp salt"}, {"status": 2, "title": "2 tsp salt"}],
                                            ["2 tsp salt", "4 tsp salt", "6 tsp salt"])], [2, 2, 0])
same("tick_key", (ms.tick_key("875 g chicken"), ms.tick_key("  Avocado  Oil "), ms.tick_key("")),
     ("chicken", "avocado oil", ""))

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if __name__ == "__main__":
    sys.exit(1 if FAILS else 0)
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
