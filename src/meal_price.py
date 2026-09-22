#!/usr/bin/env python3
"""meal_price.py - price speculation for the 🛒 lists (PURE, stdlib only,
except the two named I/O helpers and the one named network helper).

Vex 2026-09-22: "how feasible is the idea of price speculations? Like how
much will each ingredient cost and total per meal?", "Could we not scrape
prices of that site, write them in the pricebook and use that?",
"Speculation is all I need." So every 🛒 checklist line gets a rough euro
figure and the list a total and a per-portion figure - a SPECULATION, never
a receipt: the shop Vex ends up in, the brand he grabs and the week's
offers all differ from the number here, and that is fine by him.

WHY A BOOK: prices move slowly and a list has thirty lines, so the workflow
keeps one price per INGREDIENT in ~/.ticktick_alfred/meal_prices.json and
costs a list from that in memory; the network is touched only by the
manual 🏷 Prices refresh and a book row's ⌥⇧ search term, i.e. only by the
manual 🏷 Prices refresh (never a background job, Vex's rule of
2026-09-21). An entry can be typed by hand ("manual", never overwritten)
or "pinned" (the refresh re-reads the price but keeps the product).

WHY KNUSPR: knuspr.de (Rohlik's German shop) answers its own search
endpoint with plain JSON and no login - product name, pack text, price and
a price per kg / l / piece - where Amazon Fresh is gone and REWE sits
behind bot protection with per-market prices. It stands in for whatever
store Vex shops at: relative truth is all a speculation needs.

THE BASE UNITS: a line's amount and an entry's price are both brought to
one of g, ml, pc (a piece: an egg, a bunch, a can). A volume line against
a mass entry - "1 tsp salt" against salt sold by the kilo - is taken at
1 ml = 1 g and flagged approx, close enough for a spoon of anything. A
piece line against a per-gram entry ("3 chicken thighs" against thighs by
the kilo) is a "unit mismatch" until the entry says how many grams a piece
is (`piece_g`), because guessing that silently would be a lie, not a
speculation.

The ingredient KEY is the line's name canonicalised (`ingredient_key`):
parentheses dropped, cut at the comma, prep words removed, the last word
singularised - so "350 g Sliced Bacon (short cut …)" and "200 g bacon" are
one key, one price. Amounts come from meal_scale.parse_quantity, never
re-parsed here. The module is immune to its own output: a line that already
carries the " · ≈ 4.47 €" suffix keys and costs exactly as the bare line.

WHERE THE BOOK LIVES: load_book and save_book use `path` when given, else
config.CONFIG_DIR + BOOK_NAME (~/.ticktick_alfred/meal_prices.json), else
BOOK_PATH; a test that reassigns BOOK_PATH wins over config (_book_path).
"""
import json
import math
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from collections import namedtuple

import meal_scale as ms

Qty = ms.Qty
Cost = namedtuple("Cost", "line key cost per_line_note approx reason")
Total = namedtuple("Total", "total priced unpriced per_portion approx costs")
Product = namedtuple("Product", "id name pack price per per_unit in_stock url")

BOOK_NAME = "meal_prices.json"
# config.CONFIG_DIR + "/meal_prices.json", spelled out so the module imports
# without config; the two I/O helpers ask config itself unless a test has
# pointed BOOK_PATH somewhere else.
BOOK_PATH = os.path.expanduser("~/.ticktick_alfred/" + BOOK_NAME)
_BOOK_PATH_BORN = BOOK_PATH
BOOK_VERSION = 1

KNUSPR_URL = "https://www.knuspr.de/services/frontend-service/search-metadata"
KNUSPR_SITE = "https://www.knuspr.de/"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 "
       "(KHTML, like Gecko) Version/17.6 Safari/605.1.15")
_TIMEOUT = 15
_EPS = 1e-7                    # float noise guard for the half-up cent


# ── rounding ───────────────────────────────────────────────────────────────
def _round2(x):
    """Two decimals, half UP by hand: 350 g at 0.0129 is 4.515 and must read
    4.52; Python's round() says 4.51 (float 4.5149999, then banker's)."""
    return int(x * 100 + 0.5 + _EPS) / 100 if x >= 0 else -_round2(-x)


def _num(x):
    """An amount as a cook writes it: 350, 12.5, 0.5."""
    return f"{x:g}"


# ── the ingredient key ─────────────────────────────────────────────────────
# prep words and filler that never name the ingredient; "to taste" goes as
# a phrase because "taste" alone would survive.
STOPWORDS = ("fresh", "freshly", "large", "small", "medium", "big", "extra",
             "sliced", "chopped", "minced", "diced", "grated", "shredded",
             "toasted", "melted", "softened", "beaten", "peeled", "crushed",
             "finely", "roughly", "thinly", "cooked", "raw", "ripe", "optional",
             "divided", "drained",
             "to taste", "of", "or", "and", "each", "about", "approx")
_STOP_WORDS = frozenset(w for w in STOPWORDS if " " not in w)
_STOP_PHRASES = tuple(re.compile(r"\b" + re.escape(w) + r"\b") for w in STOPWORDS if " " in w)
_PARENS = re.compile(r"\([^)]*\)?")            # closed, or open to the end
_APOSTROPHE = re.compile(r"['’`]")
_PUNCT = re.compile(r"[^\w\s&-]|_")            # everything but letters, digits, & and -
# "2 x 400 g cans chopped tomatoes": parse_quantity stops at the x (not a
# unit), so the rest opens with the pack. The x-number, its unit when it is
# one meal_scale knows, and then a count word (a can, a jar, a bunch: the
# container, never the food) are dropped before keying. "clove" is NOT in
# the list: "3 cloves garlic" is already eaten by parse_quantity, and a
# bare "clove" line is the spice.
_X_NUM = re.compile(r"^x\s*\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?\s*")
_WORD = re.compile(r"^([^\W\d_]+)\.?\s*")
_COUNT_WORDS = frozenset(("can", "cans", "tin", "tins", "jar", "jars", "packet", "packets",
                          "pack", "packs", "bunch", "bunches", "sprig", "sprigs"))
_EDGE_TOKENS = frozenset(("&", "-", "+"))      # "olive oil - divided" leaves a bare dash
# plurals the -s rule gets wrong: "2 bay leaves" is the bay leaf
_IRREGULAR = {"leaves": "leaf", "halves": "half", "loaves": "loaf", "knives": "knife"}

FREE = frozenset(("water", "ice", "tap water", "cold water", "warm water", "hot water",
                  "boiling water", "lukewarm water", "ice cube", "ice water"))


def _singular(w):
    """The last word of a key, singular: eggs -> egg, potatoes -> potato,
    berries -> berry, peaches -> peach, leaves -> leaf (the four -ves
    plurals a cook meets are a map, everything else a rule). A 3-letter
    word, an -ss word and an -us word (hummus, couscous, asparagus) are
    left alone."""
    if w in _IRREGULAR:
        return _IRREGULAR[w]
    if len(w) > 3 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("oes"):
        return w[:-2]
    if w.endswith(("ches", "shes", "sses", "xes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us")):
        return w[:-1]
    return w


def _key_words(s):
    """The words of a key fragment: punctuation but & and - dropped,
    stopwords and "to taste" out, a bare &, - or + at either end out
    (they join words, they never name one)."""
    s = _PUNCT.sub(" ", _APOSTROPHE.sub("", s))
    for pat in _STOP_PHRASES:
        s = pat.sub(" ", s)
    words = [w for w in s.split() if w not in _STOP_WORDS]
    while words and words[0] in _EDGE_TOKENS:
        words.pop(0)
    while words and words[-1] in _EDGE_TOKENS:
        words.pop()
    return words


def _drop_pack_head(s):
    """`s` (lowercased, parentheses gone) without a leading "x 400 g" and
    without a leading count word: the pack, not the ingredient."""
    m = _X_NUM.match(s)
    if m:
        s = s[m.end():]
        w = _WORD.match(s)
        if w and w.group(1) in ms._ALIAS:
            s = s[w.end():]
    w = _WORD.match(s)
    if w and w.group(1) in _COUNT_WORDS:
        s = s[w.end():]
    return s


def ingredient_key(line):
    """The canonical key of a line's ingredient, the name a price hangs on:
    the line without its own price suffix, parse_quantity's rest,
    lowercased, parentheses dropped, a leading "x 400 g" and a leading
    count word (can, jar, bunch) dropped, cut at the first comma,
    punctuation but & and - dropped, stopwords out, the last word
    singularised, whitespace collapsed. "14 Eggs" -> "egg", "14 Eggs · ≈
    4.47 €" -> "egg" too, "11-14 chicken thighs, boneless & skinless" ->
    "chicken thigh", "2 x 400 g cans chopped tomatoes" -> "tomato".
    Never raises; "" for a blank line."""
    try:
        raw = strip_price(line or "").lstrip("-\u2013\u2014 ").strip()
        if _STEP_LINE.match(raw):            # "14 . Finish with fresh parm": a step, not a thing
            return ""
        raw = _PLUS.split(raw, 1)[0]         # "olive oil + 2 tsp salt": the first thing
        q = ms.parse_quantity(raw)
        rest = q.rest or ""
        if q.amount is None:                 # "tbsp Black Pepper": a unit with no amount
            m = _WORD.match(rest.lower())
            if m and m.group(1) in ms._ALIAS:
                rest = rest[m.end():]
        s = _drop_pack_head(_PARENS.sub(" ", rest.lower()).strip())
        words = _key_words(s.split(",", 1)[0])
        if not words and "," in s:          # "fresh, chopped parsley": the cut left a stopword
            words = _key_words(s.replace(",", " "))
        if words:
            words[-1] = _singular(words[-1])
        return " ".join(words)
    except Exception:
        return ""


_STEP_LINE = re.compile(r"^\s*\d{1,2}\s*[.)]\s")     # "14 . Finish…", "3) Stir": instructions that leaked
_PLUS = re.compile(r"\s\+\s")                        # two things on one line: the first is keyed
_HEADER_BOLD = re.compile(r"^\*\*.*\*\*$")


def is_header_line(line):
    """A checklist line that names a section, not a thing to buy: a bold
    **Sauce**, a '#' header, a short 'For the sauce:' or an all-caps CHICKEN.
    Only asked about lines with no leading amount."""
    s = (line or "").strip()
    if not s:
        return False
    if ms.is_header(s) or _HEADER_BOLD.match(s):
        return True
    if s.endswith(":") and len(s) <= 40:
        return True
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and len(letters) >= 2 and all(c.isupper() for c in letters)


# ── base units ─────────────────────────────────────────────────────────────
# canonical unit (meal_scale.UNITS) -> (factor, base). Spoons and cups are
# volumes; count units and a bare number are pieces.
_TO_BASE = {"g": (1.0, "g"), "kg": (1000.0, "g"), "mg": (0.001, "g"),
            "lb": (454.0, "g"), "oz": (28.35, "g"),
            "ml": (1.0, "ml"), "l": (1000.0, "ml"), "dl": (100.0, "ml"),
            "tsp": (5.0, "ml"), "tbsp": (15.0, "ml"), "cup": (240.0, "ml")}
_CLASS_BASE = {"mass_g": (1.0, "g"), "mass_kg": (1000.0, "g"), "lb": (454.0, "g"),
               "oz": (28.35, "g"), "vol_ml": (1.0, "ml"), "vol_l": (1000.0, "ml")}
BASES = ("g", "ml", "pc")


def to_base(qty):
    """(amount, base) of a Qty in g / ml / pc; a range counts its midpoint;
    no amount -> (None, None). A unit meal_scale knows but this table does
    not falls back on its class, and a count unit is a piece."""
    if qty is None or qty.amount is None:
        return None, None
    amount = (qty.amount + qty.range_hi) / 2 if qty.range_hi is not None else qty.amount
    unit = qty.unit
    if unit in _TO_BASE:
        f, base = _TO_BASE[unit]
    elif unit in ms.UNITS and ms.UNITS[unit][0] in _CLASS_BASE:
        f, base = _CLASS_BASE[ms.UNITS[unit][0]]
    else:
        f, base = 1.0, "pc"
    return amount * f, base


# ── search terms ───────────────────────────────────────────────────────────
# English key -> what to type into knuspr. The longest key contained in the
# line's key as whole words wins ("onion & garlic powder" -> "garlic
# powder" -> Knoblauchpulver), so a specific cut beats its generic word.
DEFAULT_SEARCH = {
    # eggs, meat, fish
    "egg": "Eier", "egg white": "Eiklar", "bacon": "Bacon", "bacon bit": "Bacon",
    "chicken breast": "Hähnchenbrust", "chicken thigh": "Hähnchenschenkel",
    "chicken wing": "Hähnchenflügel", "chicken drumstick": "Hähnchenkeule",
    "chicken": "Hähnchen", "beef": "Rindfleisch", "ground beef": "Rinderhackfleisch",
    "minced beef": "Rinderhackfleisch", "steak": "Rindersteak",
    "ground pork": "Schweinehackfleisch", "pork": "Schweinefleisch",
    "pork belly": "Schweinebauch", "pork chop": "Schweinekotelett",
    "minced meat": "Hackfleisch", "ground meat": "Hackfleisch",
    "turkey": "Pute", "turkey breast": "Putenbrust", "ground turkey": "Putenhackfleisch",
    "sausage": "Wurst", "ham": "Schinken", "salmon": "Lachs", "shrimp": "Garnelen",
    "prawn": "Garnelen", "tuna": "Thunfisch", "cod": "Kabeljau", "tofu": "Tofu",
    # grains, bread, pasta
    "rice": "Reis", "basmati rice": "Basmati Reis", "jasmine rice": "Jasminreis",
    "brown rice": "Naturreis", "quinoa": "Quinoa", "couscous": "Couscous",
    "bulgur": "Bulgur", "pasta": "Nudeln", "noodle": "Nudeln", "rice noodle": "Reisnudeln",
    "spaghetti": "Spaghetti", "penne": "Penne", "ramen": "Ramen",
    "tortilla": "Tortilla", "wrap": "Wraps", "bagel": "Bagel", "bread": "Brot",
    "pita": "Pita", "naan": "Naan", "breadcrumb": "Paniermehl", "panko": "Panko",
    "oat": "Haferflocken", "rolled oat": "Haferflocken", "granola": "Granola",
    # baking, sweet
    "flour": "Mehl", "whole wheat flour": "Vollkornmehl", "almond flour": "Mandelmehl",
    "sugar": "Zucker", "brown sugar": "Brauner Zucker", "powdered sugar": "Puderzucker",
    "icing sugar": "Puderzucker", "coconut sugar": "Kokosblütenzucker",
    "baking powder": "Backpulver", "baking soda": "Natron", "yeast": "Hefe",
    "vanilla": "Vanille", "vanilla extract": "Vanilleextrakt", "cocoa powder": "Kakao",
    "cocoa": "Kakao", "honey": "Honig", "maple syrup": "Ahornsirup", "agave": "Agavendicksaft",
    "chocolate": "Schokolade", "dark chocolate": "Zartbitterschokolade",
    "chocolate chip": "Schokodrops", "peanut butter": "Erdnussbutter",
    "protein powder": "Proteinpulver", "gelatin": "Gelatine",
    # dairy
    "butter": "Butter", "milk": "Milch", "whole milk": "Vollmilch", "cream": "Sahne",
    "heavy cream": "Sahne", "whipping cream": "Schlagsahne", "sour cream": "Schmand",
    "creme fraiche": "Crème fraîche", "greek yogurt": "Griechischer Joghurt",
    "greek yoghurt": "Griechischer Joghurt", "yogurt": "Joghurt", "yoghurt": "Joghurt",
    "skyr": "Skyr", "quark": "Quark", "cottage cheese": "Hüttenkäse",
    "cheese": "Käse", "cheddar": "Cheddar", "cheddar cheese": "Cheddar",
    "parmesan": "Parmigiano", "parmesan cheese": "Parmigiano", "mozzarella": "Mozzarella",
    "mozzarella cheese": "Mozzarella", "cream cheese": "Frischkäse", "feta": "Feta",
    "feta cheese": "Feta", "gouda": "Gouda", "ricotta": "Ricotta", "halloumi": "Halloumi",
    "goat cheese": "Ziegenkäse", "blue cheese": "Blauschimmelkäse",
    "emmental": "Emmentaler", "swiss cheese": "Emmentaler", "gruyere": "Gruyère",
    "coconut milk": "Kokosmilch", "coconut cream": "Kokoscreme",
    "almond milk": "Mandelmilch", "oat milk": "Hafermilch",
    # vegetables
    "onion": "Zwiebeln", "red onion": "Rote Zwiebeln", "shallot": "Schalotten",
    "garlic": "Knoblauch", "garlic clove": "Knoblauch", "ginger": "Ingwer",
    "scallion": "Lauchzwiebeln", "green onion": "Lauchzwiebeln",
    "spring onion": "Lauchzwiebeln", "leek": "Lauch", "lemongrass": "Zitronengras",
    "tomato": "Tomaten", "cherry tomato": "Cherrytomaten", "potato": "Kartoffeln",
    "baby potato": "Kartoffeln", "sweet potato": "Süßkartoffel", "carrot": "Karotten",
    "broccoli": "Brokkoli", "cauliflower": "Blumenkohl", "spinach": "Spinat",
    "kale": "Grünkohl", "cabbage": "Weißkohl", "red cabbage": "Rotkohl",
    "bell pepper": "Paprika", "red pepper": "Paprika", "cucumber": "Gurke",
    "zucchini": "Zucchini", "courgette": "Zucchini", "eggplant": "Aubergine",
    "aubergine": "Aubergine", "lettuce": "Salat", "romaine": "Römersalat",
    "arugula": "Rucola", "rocket": "Rucola", "celery": "Sellerie", "asparagus": "Spargel",
    "green bean": "Grüne Bohnen", "pea": "Erbsen", "edamame": "Edamame",
    "pumpkin": "Kürbis", "butternut squash": "Butternut Kürbis", "beet": "Rote Bete",
    "beetroot": "Rote Bete", "radish": "Radieschen", "mushroom": "Champignons",
    "corn": "Mais", "sweetcorn": "Mais", "avocado": "Avocado", "olive": "Oliven",
    "jalapeno": "Jalapeño", "chili": "Chili", "chilli": "Chili",
    # fruit
    "lemon": "Zitrone", "lime": "Limette", "orange": "Orangen", "banana": "Bananen",
    "apple": "Apfel", "pear": "Birnen", "peach": "Pfirsich", "mango": "Mango",
    "pineapple": "Ananas", "grape": "Trauben", "kiwi": "Kiwi", "berry": "Beeren",
    "frozen berry": "TK Beeren", "strawberry": "Erdbeeren", "blueberry": "Blaubeeren",
    "raspberry": "Himbeeren", "raisin": "Rosinen", "date": "Datteln",
    "apple juice": "Apfelsaft", "orange juice": "Orangensaft",
    "lemon juice": "Zitronensaft", "lime juice": "Limettensaft",
    # nuts, seeds
    "almond": "Mandeln", "walnut": "Walnüsse", "cashew": "Cashewkerne",
    "peanut": "Erdnüsse", "pumpkin seed": "Kürbiskerne", "sunflower seed": "Sonnenblumenkerne",
    "chia seed": "Chiasamen", "flaxseed": "Leinsamen", "sesame": "Sesam",
    "sesame seed": "Sesam", "coconut flake": "Kokosflocken",
    # tins, jars, pulses
    "bean": "Bohnen", "black bean": "Schwarze Bohnen", "kidney bean": "Kidneybohnen",
    "white bean": "Weiße Bohnen", "cannellini bean": "Weiße Bohnen",
    "pinto bean": "Pinto Bohnen", "refried bean": "Refried Beans",
    "chickpea": "Kichererbsen", "lentil": "Linsen", "tomato paste": "Tomatenmark",
    "tomato sauce": "Tomatensauce", "crushed tomato": "Tomaten stückig",
    "canned tomato": "Tomaten Dose", "passata": "Passata", "sun-dried tomato": "Getrocknete Tomaten",
    "artichoke": "Artischocken", "caper": "Kapern", "pickle": "Gewürzgurken",
    "kimchi": "Kimchi", "salsa": "Salsa", "pesto": "Pesto", "tahini": "Tahini",
    "hummus": "Hummus",
    # oils, sauces, vinegars
    "olive oil": "Olivenöl", "oil": "Öl", "sesame oil": "Sesamöl", "coconut oil": "Kokosöl",
    "vegetable oil": "Pflanzenöl", "canola oil": "Rapsöl", "rapeseed oil": "Rapsöl",
    "avocado oil": "Avocadoöl", "soy sauce": "Sojasauce", "hoisin sauce": "Hoisin",
    "oyster sauce": "Austernsauce", "fish sauce": "Fischsauce",
    "worcestershire sauce": "Worcestersauce", "teriyaki sauce": "Teriyaki Sauce",
    "bbq sauce": "BBQ Sauce", "sweet chili sauce": "Sweet Chili Sauce",
    "ketchup": "Ketchup", "mayonnaise": "Mayonnaise", "mayo": "Mayonnaise",
    "mustard": "Senf", "dijon mustard": "Dijon Senf", "sriracha": "Sriracha",
    "hot sauce": "Hot Sauce", "gochujang": "Gochujang", "miso": "Miso", "mirin": "Mirin",
    "vinegar": "Essig", "apple cider vinegar": "Apfelessig", "rice vinegar": "Reisessig",
    "balsamic vinegar": "Balsamico", "red wine vinegar": "Rotweinessig",
    "white wine": "Weißwein", "red wine": "Rotwein",
    # spices, herbs, stock
    "salt": "Salz", "pepper": "Pfeffer", "black pepper": "Pfeffer",
    "paprika": "Paprikapulver", "smoked paprika": "Geräuchertes Paprikapulver",
    "cumin": "Kreuzkümmel", "oregano": "Oregano", "thyme": "Thymian",
    "rosemary": "Rosmarin", "basil": "Basilikum", "parsley": "Petersilie",
    "cilantro": "Koriander", "coriander": "Koriander", "chive": "Schnittlauch",
    "dill": "Dill", "mint": "Minze", "bay leaf": "Lorbeer",
    "garlic powder": "Knoblauchpulver", "onion powder": "Zwiebelpulver",
    "chili flake": "Chiliflocken", "red pepper flake": "Chiliflocken",
    "chili powder": "Chilipulver", "cayenne": "Cayennepfeffer", "curry powder": "Currypulver",
    "curry paste": "Currypaste", "turmeric": "Kurkuma", "cinnamon": "Zimt",
    "nutmeg": "Muskat", "italian seasoning": "Italienische Kräuter",
    "taco seasoning": "Taco Gewürz", "cornstarch": "Speisestärke",
    "corn starch": "Speisestärke", "stock": "Brühe", "broth": "Brühe",
    "bouillon": "Brühe", "chicken stock": "Hühnerbrühe", "chicken broth": "Hühnerbrühe",
    "beef broth": "Rinderbrühe", "beef stock": "Rinderbrühe",
    "vegetable broth": "Gemüsebrühe", "vegetable stock": "Gemüsebrühe",
}


def _contains(haystack, needle):
    """Is `needle` inside `haystack` as whole words ("garlic powder" in
    "onion & garlic powder", never "egg" in "eggplant")? Both are keys:
    lowercase words with single spaces."""
    h, n = haystack.split(), needle.split()
    if not n or len(n) > len(h):
        return False
    return any(h[i:i + len(n)] == n for i in range(len(h) - len(n) + 1))


def _longest_contained(key, keys):
    """The longest of `keys` contained in `key` as whole words, or None;
    a tie goes to the alphabetically first, so the answer is stable."""
    hits = [k for k in keys if _contains(key, k)]
    return min(hits, key=lambda k: (-len(k), k)) if hits else None


def search_term(key, book=None):
    """What to type into knuspr for `key`: the book entry's own "search"
    when it has one, else DEFAULT_SEARCH by the longest key contained in
    `key` ("cheddar cheese slice" -> "cheddar cheese" -> Cheddar), else
    the key itself (knuspr's search tolerates English for many words)."""
    key = (key or "").strip()
    entries = (book or {}).get("entries") or {}
    e = entries.get(key)
    if isinstance(e, dict) and e.get("search"):
        return str(e["search"])
    terms = (book or {}).get("terms") or {}     # a term typed for a key with no entry yet
    if isinstance(terms, dict) and terms.get(key):
        return str(terms[key])
    hit = _longest_contained(key, DEFAULT_SEARCH)
    return DEFAULT_SEARCH[hit] if hit else key


# ── the book ───────────────────────────────────────────────────────────────
def empty_book():
    """A book with nothing in it, the shape load_book hands out for a
    missing or broken file, so a caller costs against it and never tests
    for None."""
    return {"version": BOOK_VERSION, "updated": "", "entries": {}}


def _book_path(path):
    """`path`, else BOOK_PATH when a caller (a test) has pointed it away
    from its birth value, else config's dir + the name. config is imported
    here and nowhere else so the module stays importable without it."""
    if path:
        return path
    if BOOK_PATH != _BOOK_PATH_BORN:
        return BOOK_PATH
    try:
        import config as cfg
        return os.path.join(cfg.CONFIG_DIR, BOOK_NAME)
    except Exception:
        return BOOK_PATH


def load_book(path=None):
    """The book at `path` (default BOOK_PATH); an empty book when the file
    is missing or unreadable, so a first cost never crashes and a refresh
    starts from nothing. I/O."""
    try:
        with open(_book_path(path), encoding="utf-8") as fh:
            book = json.load(fh)
        if not isinstance(book, dict) or not isinstance(book.get("entries"), dict):
            return empty_book()
        book.setdefault("version", BOOK_VERSION)
        book.setdefault("updated", "")
        return book
    except Exception:
        return empty_book()


def save_book(book, path=None):
    """Write the book atomically: a temp file beside it, then os.replace,
    so a refresh killed halfway never leaves half a JSON. I/O."""
    target = _book_path(path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(book, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, target)
    return target


def _base_of(entry):
    """An entry's per_unit when it is one of BASES, else None."""
    return entry.get("per_unit") if isinstance(entry, dict) and entry.get("per_unit") in BASES else None


def lookup(key, book, base=None):
    """The entry for `key`: exact; else the entry whose key is contained in
    `key` as whole words, longest first ("boneless chicken thigh" ->
    "chicken thigh" before "chicken"); else the entry `key` is contained in,
    shortest first ("thigh" -> "chicken thigh"). None when nothing. Pure.

    `base` is the line's own base (g / ml / pc): among the candidates of
    one level an entry priced in that base comes first, then the level's
    length rule, then the name, so "500 g chicken" against "chicken stock"
    (ml) and "chicken thigh" (g) takes the thigh, not the alphabet."""
    key = (key or "").strip()
    entries = (book or {}).get("entries") or {}
    if not key:
        return None
    if key in entries:
        return entries[key]

    def off_base(k):
        return 1 if base and _base_of(entries[k]) != base else 0
    inner = [k for k in entries if _contains(key, k)]
    if inner:
        return entries[min(inner, key=lambda k: (off_base(k), -len(k), k))]
    outer = [k for k in entries if _contains(k, key)]
    if outer:
        return entries[min(outer, key=lambda k: (off_base(k), len(k), k))]
    return None


# ── cost ───────────────────────────────────────────────────────────────────
def _per_text(per, unit):
    """A price the way the shelf tag says it: 12.90 €/kg, 15.98 €/l, 0.32 €/pc."""
    if unit == "g":
        return f"{per * 1000:.2f} €/kg"
    if unit == "ml":
        return f"{per * 1000:.2f} €/l"
    return f"{per:.2f} €/pc"


def _entry_per(entry):
    """(per, per_unit) of an entry, or (None, None) when it is unusable."""
    try:
        per = float(entry.get("per"))
        unit = entry.get("per_unit")
    except Exception:
        return None, None
    if unit not in BASES or per < 0:
        return None, None
    return per, unit


def _piece_g(entry):
    """An entry's grams a piece, 0.0 when unset or unreadable: the one
    number a piece line needs against a per-gram price, typed by hand
    (or carried across a refresh), never guessed by the module."""
    try:
        g = float(entry.get("piece_g") or 0)
    except Exception:
        return 0.0
    return g if g > 0 else 0.0


def line_cost(line, book):
    """Cost(line, key, cost, per_line_note, approx, reason) for one
    checklist line, its own price suffix ignored (a re-price reads the
    titles it wrote). cost is euro to the cent or None; reason is "priced",
    "free" (water, ice), "no amount" (a header, a bare "Avocado oil"),
    "no entry" (nothing in the book) or "unit mismatch" (pieces against a
    per-gram price without piece_g). approx: a spoon taken as grams, a
    range at its midpoint, a piece converted through piece_g. Cost.line is
    the line as given."""
    key = ingredient_key(line)
    q = ms.parse_quantity(strip_price(line or ""))
    amount, base = to_base(q)
    if not key:                              # a step line, a blank: nothing to buy
        return Cost(line, key, None, "not an ingredient", False, "no amount")
    if key in FREE:
        return Cost(line, key, 0.0, "free", False, "free")
    if amount is None:
        return Cost(line, key, None, "no amount", False, "no amount")
    entry = lookup(key, book, base) if key else None
    per, unit = _entry_per(entry) if entry else (None, None)
    if per is None:
        return Cost(line, key, None, f"no price for {key or 'this line'}", False, "no entry")
    approx = q.range_hi is not None
    amt_text = f"{_num(amount)} {base}" + (" (midpoint)" if approx else "")
    if unit == base:
        cost = amount * per
        note = f"{amt_text} at {_per_text(per, unit)}"
    elif {unit, base} == {"g", "ml"}:
        cost = amount * per
        approx = True
        note = f"{amt_text} as {unit} at {_per_text(per, unit)}"
    elif base == "pc" and _piece_g(entry):
        g = _piece_g(entry)
        cost = amount * g * per
        approx = True
        note = f"{amt_text} x {_num(g)} g at {_per_text(per, unit)}"
    elif unit == "pc" and _piece_g(entry):
        g = _piece_g(entry)
        cost = amount / g * per
        approx = True
        note = f"{amt_text} / {_num(g)} g a piece at {_per_text(per, unit)}"
    else:
        return Cost(line, key, None, f"{base} line, {unit} price", False, "unit mismatch")
    if entry.get("product"):
        note += f" · {entry['product']}"
    return Cost(line, key, _round2(cost), note, approx, "priced")


UNPRICED_REASONS = ("no entry", "unit mismatch")


def list_cost(lines, book, portions=7):
    """Total(total, priced, unpriced, per_portion, approx, costs) for a 🛒
    list: total is the sum to the cent, priced the count of priced rows,
    unpriced the LINES the book could not price (no entry, unit mismatch,
    or an ingredient with no amount - headers are not ingredients),
    per_portion = total / portions when portions. approx when any row is
    approx or any line is unpriced: a speculation with holes in it."""
    costs = [line_cost(ln, book) for ln in (lines or [])]
    total = 0.0
    priced = 0
    unpriced = []
    approx = False
    for c in costs:
        if c.reason == "priced":
            total += c.cost
            priced += 1
            approx = approx or c.approx
        elif c.reason in UNPRICED_REASONS:
            unpriced.append(c.line)
        elif c.reason == "no amount" and c.key and not is_header_line(c.line):
            unpriced.append(c.line)
    approx = approx or bool(unpriced)
    total = _round2(total)
    per_portion = _round2(total / portions) if portions else None
    return Total(total, priced, unpriced, per_portion, approx, costs)


def cost_line(total):
    """The one line for the top of the checklist description:
    "≈ 18.40 € · 2.60 €/portion", plus " · 3 unpriced" when the book had
    holes, or "≈ 0.00 € · nothing priced yet" when it had nothing."""
    if not total.priced and total.unpriced and not total.total:
        return "≈ 0.00 € · nothing priced yet"
    s = f"≈ {total.total:.2f} €"
    if total.per_portion is not None:
        s += f" · {total.per_portion:.2f} €/portion"
    if total.unpriced:
        s += f" · {len(total.unpriced)} unpriced"
    return s


# the cost line's own shape, "≈ 18.40 €" and whatever follows it, taken
# with the ONE blank line the writer may have put under it
_COST_LINE = re.compile(r"(?m)^≈ \d+\.\d\d €[^\n]*(?:\n(?:[ \t]*\n)?|$)")
_COST_READ = re.compile(r"(?m)^≈ (\d+\.\d\d) €(?: · (\d+\.\d\d) €/portion)?"
                        r"(?: · (\d+) unpriced)?( · nothing priced yet)?[ \t]*$")


def strip_cost_line(desc):
    """`desc` without a previous cost line: a line of cost_line's own shape
    ("≈ 18.40 €" then anything), gone together with ONE blank line under
    it, so a description that was cost line + blank + body comes back as
    the body. Anchored to the cents on purpose: the yield note "≈ Scaled
    ×1.75: 4 → 7 portions" and a recipe's "≈ 3 € worth of saffron" both
    start with "≈ " and MUST stay. Idempotent."""
    return _COST_LINE.sub("", desc or "")


def read_cost_line(desc):
    """(total, per_portion, unpriced) from the module's own cost line in
    `desc`, or None when there is none: "≈ 18.40 € · 2.60 €/portion · 3
    unpriced" -> (18.4, 2.6, 3); "≈ 8.99 € · 1.28 €/portion" -> (8.99,
    1.28, 0), no holes were reported; "≈ 0.00 € · nothing priced yet" ->
    (0.0, None, None), the count of holes was never said. Only the shape
    cost_line writes is read; a recipe's own "≈ 3.00 € worth" is not."""
    m = _COST_READ.search(desc or "")
    if not m:
        return None
    total = float(m.group(1))
    per = float(m.group(2)) if m.group(2) else None
    if m.group(4):
        return total, per, None
    return total, per, int(m.group(3)) if m.group(3) else 0


def price_suffix(cost):
    """" · ≈ 1.10 €" for an item title; "" when there is no cost."""
    return "" if cost is None else f" · ≈ {cost:.2f} €"


_PRICE_SUFFIX = re.compile(r"\s*·\s*≈\s*\d+(?:[.,]\d+)?\s*€\s*$")


def strip_price(title):
    """The title without its price suffix (the portions re-cut strips it
    before keying ticks by ingredient name)."""
    return _PRICE_SUFFIX.sub("", title or "")


# ── knuspr ─────────────────────────────────────────────────────────────────
def knuspr_fetch(term):
    """The parsed JSON of knuspr's search-metadata endpoint for `term`. The
    ONE network call in the module; errors propagate to knuspr_search,
    which swallows them. NETWORK."""
    qs = urllib.parse.urlencode({"search": term, "referer": "whisperer"})
    req = urllib.request.Request(KNUSPR_URL + "?" + qs, headers={
        "User-Agent": _UA, "Accept": "application/json",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


_PACK = re.compile(r"^\s*(?:ca\.?\s*|~\s*)?(\d+(?:[.,]\d+)?)\s*(?:x\s*(\d+(?:[.,]\d+)?)\s*)?"
                   r"([^\W\d_]+)\.?\s*$", re.I)
_PACK_UNITS = {"g": (1.0, "g"), "gr": (1.0, "g"), "kg": (1000.0, "g"), "mg": (0.001, "g"),
               "ml": (1.0, "ml"), "l": (1000.0, "ml"), "cl": (10.0, "ml"), "dl": (100.0, "ml"),
               "stk": (1.0, "pc"), "stück": (1.0, "pc"), "stueck": (1.0, "pc"), "st": (1.0, "pc"),
               "bund": (1.0, "pc"), "packung": (1.0, "pc"), "pack": (1.0, "pc"), "pck": (1.0, "pc"),
               "pkg": (1.0, "pc"), "beutel": (1.0, "pc"), "dose": (1.0, "pc"), "flasche": (1.0, "pc"),
               "glas": (1.0, "pc"), "tüte": (1.0, "pc"), "paar": (2.0, "pc"), "stange": (1.0, "pc"),
               "kopf": (1.0, "pc"), "knolle": (1.0, "pc"), "rolle": (1.0, "pc"), "becher": (1.0, "pc"),
               "scheibe": (1.0, "pc"), "scheiben": (1.0, "pc")}


def _shop_num(s):
    """A number the way the shop writes it, the comma a decimal point:
    "0,530" is 0.53, never meal_scale._dec's 530 (its "1,500" rule reads a
    recipe's thousands separator, and a pack text has none)."""
    return float(s.replace(",", "."))


def pack_parse(text):
    """(amount, base) of a knuspr pack text: "10 Stk" -> (10, pc), "100 g"
    -> (100, g), "ca. 0,53 kg" -> (530, g), "0,530 kg" -> (530, g), "0,75 l"
    -> (750, ml), "1 Bund" -> (1, pc), "2 x 100 g" -> (200, g); unknown ->
    (None, None)."""
    m = _PACK.match(text or "")
    if not m:
        return None, None
    unit = m.group(3).lower()
    if unit not in _PACK_UNITS:
        return None, None
    f, base = _PACK_UNITS[unit]
    n = _shop_num(m.group(1))
    if m.group(2):
        n *= _shop_num(m.group(2))
    return n * f, base


_PPU_TOLERANCE = 0.05


def _product(p):
    """One Product from one productList item, or None when it is archived
    or has no price. per is brought to the base of its pack: knuspr's
    pricePerUnit is per kg for a g/kg pack, per l for a ml/l pack, per
    piece for Stk/Bund. The shop rounds that figure to the cent (10 eggs at
    3.19 say 0.32), so when price / pack amount agrees with it within 5
    percent the division is stored (0.319, six decimals) and the rounded
    tag only stands in when they disagree (a pack text the shop priced
    another way) or when there is no pack to divide by."""
    if p.get("archived"):
        return None
    price = float((p.get("price") or {}).get("full") or 0)
    pack = str(p.get("textualAmount") or "").strip()
    amount, base = pack_parse(pack)
    ppu = (p.get("pricePerUnit") or {}).get("full")
    ppu = float(ppu) if ppu else 0.0
    if base in ("g", "ml"):
        tag = ppu / 1000 if ppu else None
    elif base == "pc":
        tag = ppu if ppu else None
    else:                                   # an unreadable pack: one of it
        tag, amount, base = None, 1.0, "pc"
    by_pack = price / amount if amount else None
    if tag and by_pack is not None and abs(by_pack - tag) <= _PPU_TOLERANCE * tag + 1e-12:
        per = by_pack
    else:
        per = tag if tag else by_pack
    if per is None:
        return None
    link = str(p.get("baseLink") or "")
    return Product(p.get("productId"), str(p.get("productName") or ""), pack,
                   _round2(price), round(per, 6), base, bool(p.get("inStock")),
                   KNUSPR_SITE + link if link else "")


def knuspr_search(term, fetch=None):
    """[Product] for `term` from data.productList; `fetch` (term -> dict)
    is injectable for tests. Network or JSON trouble -> [] and nothing
    else: a refresh over forty keys must not stop at one bad answer."""
    try:
        data = (fetch or knuspr_fetch)(term)
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        items = inner.get("productList") or []
    except Exception:
        return []
    if not isinstance(items, list):         # a string would iterate its letters
        return []
    out = []
    for p in items:
        try:
            prod = _product(p) if isinstance(p, dict) else None
        except Exception:
            prod = None
        if prod is not None:
            out.append(prod)
    return out


_UMLAUT = (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"))


_NON_LETTERS = re.compile(r"[^a-z]+")
def _fold(s):
    """Lowercase, umlaut-blind, accent-blind: 'Hähnchen' and 'Haehnchen'
    compare equal (product names spell both ways), 'Crème' reads 'creme'."""
    s = (s or "").lower()
    for a, b in _UMLAUT:
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _name_words(s):
    """The letter runs of a folded name: "Bio-Eier 10er M/L" -> bio, eier,
    er, m, l."""
    return [w for w in _NON_LETTERS.split(_fold(s)) if w]


_WINDOW = 5                    # knuspr's relevance order is trusted this deep


def _stem(word):
    """A term word minus its last letter (rote -> rot, zwiebeln -> zwiebel,
    eier -> eie): German plural, gender and case endings vary the tail of
    a word, never its head."""
    return word[:-1] if len(word) > 3 else word


def _word_hit(term_word, name_word):
    """Does a NAME word say this TERM word: the word itself, its stem, or
    the stem plus one letter ("rot" / "rote" / "roter", "zwiebel" /
    "zwiebeln"). A compound is NOT a hit ("eierspaetzle" is not "eier"),
    which is what keeps eggs apart from egg noodles."""
    stem = _stem(term_word)
    return (name_word == term_word or name_word == stem
            or (name_word.startswith(stem) and len(name_word) <= len(term_word) + 1))


def _tier(name, words):
    """How well a product name answers the term: 1 = every term word is a
    WORD of the name (Eier, Rote Zwiebeln), 2 = every term word sits whole
    inside the name with its spaces removed (a compound written apart or
    together: "Hähnchen Schenkel" for Hähnchenschenkel, Jodsalz for Salz,
    but also Eierspätzle for Eier, which is why tier 1 comes first), 3 =
    every term word's stem is somewhere in it, 4 = none of that."""
    if not words:
        return 4
    nw = _name_words(name)
    if all(any(_word_hit(t, w) for w in nw) for t in words):
        return 1
    joined = "".join(nw)
    if all(t in joined for t in words):
        return 2
    if all(_stem(t) in joined for t in words):
        return 3
    return 4


# Words that mark a PRODUCT MADE OF the thing rather than the thing: a
# buttermilk "Zitrone", an egg-salad spread "mit Schnittlauch", airfryer
# snack balls "Polenta / Parmesan", a salami "mit Walnüssen" (a bare "/"
# is a size, "10er M/L", so only a spaced one counts). Each is ignored when
# the term itself carries it (Knoblauchpulver asks for pulver, Hot Sauce for
# sauce, Milch for milch), so a search for the processed thing still works.
_PROCESSED = ("mit ", "&", " / ", "salat", "aufstrich", "snack", "milch", "getraenk",
              "saft", "riegel", "chips", "sauce", "sosse", "pizza", "fertig", "dressing",
              "pulver", "wurst", "salami", "spray", "nudeln", "spaetzle", "keks", "kuchen",
              "joghurt", "quark", "dip", "creme", "likoer", "sirup", "marinade", "gewuerz",
              "brot", "knoedel", "kloesse", "burger", "torte", "suppe", "eintopf", "auflauf",
              "pastete", "fuellung", "gericht")


def _processed(name, term):
    """True when the product name says it is made WITH the thing asked for
    (see _PROCESSED), unless the term asks for that kind of thing."""
    n, t = " " + _fold(name) + " ", _fold(term)
    return any(w in n and w.strip() not in t for w in _PROCESSED)


def rank(products, term):
    """The products in pick order. Candidates: in stock with a price > 0
    (all of them when nothing is in stock), in knuspr's own relevance
    order, and PLAIN before processed (_processed: a "Zitrone" buttermilk
    or a spread "mit Schnittlauch" only count when nothing plain answers).
    The best tier present (_tier) names the group; the FIRST plain product
    of that tier sets the base (g / ml / pc) - knuspr's first answer of the
    right kind is the kind of thing asked for - and only that base is
    compared: among the first _WINDOW plain products of that base whose
    tier is at most max(best, 2) the LOWEST per wins (so a compound spelt
    apart competes with one spelt together, and eggs never lose to egg
    noodles because the tier-1 eggs set the base). per is NEVER compared
    across bases (0.004 €/g of Eierspätzle is not cheaper than 0.32 €/pc
    of eggs, it is a different thing) and never beyond the window (a cheap
    wrong thing the shop ranks 20th must not beat the right thing it ranks
    1st: the live probe had Salzstangen beating salt and a herring salad
    beating red onions that way). Then the rest, in knuspr's order. The CLI
    shows the top five; pick takes the first."""
    cands = [p for p in products or [] if p.price and p.price > 0]
    stock = [p for p in cands if p.in_stock]
    if stock:
        cands = stock
    if not cands:
        return []
    plain = [p for p in cands if not _processed(p.name, term)]
    pool = plain or cands
    words = [w for w in _name_words(term) if len(w) >= 3]
    tiers = {id(p): _tier(p.name, words) for p in cands}
    best = min(tiers[id(p)] for p in pool)
    first = next(p for p in pool if tiers[id(p)] == best)
    base = first.per_unit
    limit = max(best, 2)
    window = [p for p in pool if tiers[id(p)] <= limit and p.per_unit == base][:_WINDOW]
    same = sorted(window, key=lambda p: p.per if p.per is not None else float("inf"))
    rest = [p for p in cands if not any(p is q for q in same)]
    return same + rest


def pick(products, term):
    """The one product to price `term` by (see rank), or None."""
    ranked = rank(products, term)
    return ranked[0] if ranked else None


def _iso(today):
    """`today` as ISO text whether it came as a date or already as text:
    the book stamps dates as strings so JSON round-trips them unchanged."""
    return today if isinstance(today, str) else today.isoformat()


def entry_from(product, key, term, today):
    """A knuspr book entry for `key` from `product`: what was searched,
    what was found, its pack and price, the price per base unit."""
    amount, base = pack_parse(product.pack)
    return {"key": key, "search": term, "product": product.name,
            "product_id": product.id, "pack": product.pack,
            "pack_amount": amount, "pack_unit": base, "price": product.price,
            "per": product.per, "per_unit": product.per_unit, "source": "knuspr",
            "date": _iso(today), "pinned": False, "url": product.url}


def refresh(keys, book, today, fetch=None, pace=0.5, sleep=None):
    """Re-price `keys` in order into book["entries"] and stamp
    book["updated"]: {"updated": [..], "unpriced": [..], "kept": [..],
    "stale": [..]}. A manual entry is never touched (kept). A pinned entry
    searches its OWN product name and takes the new price when the same
    product_id is in the results, else keeps what it had (kept); a pinned
    entry with no product name to search by is kept as it is, never
    re-picked and never unpinned (the pin is Vex's word that this entry is
    right). Everything else is searched by search_term, picked, written;
    nothing found leaves an old entry as it was, reported under BOTH kept
    and stale (its price is from an earlier day and the shop no longer
    answers for it, which the book screen should show), or leaves the key
    out of the book (unpriced). Never raises for a fetch that throws or
    answers junk: that key is simply not found. Network calls are `pace`
    seconds apart (sleep injectable) because forty keys in a burst is rude
    to a shop we are not paying."""
    if sleep is None:
        import time
        sleep = time.sleep
    book.setdefault("version", BOOK_VERSION)
    entries = book.setdefault("entries", {})
    out = {"updated": [], "unpriced": [], "kept": [], "stale": []}
    calls = 0

    def search(term):
        nonlocal calls
        if calls and pace:
            sleep(pace)
        calls += 1
        return knuspr_search(term, fetch)

    for key in keys or []:
        old = entries.get(key)
        if isinstance(old, dict) and old.get("source") == "manual":
            out["kept"].append(key)
            continue
        if isinstance(old, dict) and old.get("pinned"):
            if not old.get("product"):
                out["kept"].append(key)
                continue
            same = [p for p in search(old["product"]) if p.id == old.get("product_id")]
            if same:
                fresh = entry_from(same[0], key, old.get("search") or search_term(key, book), today)
                fresh["pinned"] = True
                if _piece_g(old):
                    fresh["piece_g"] = old["piece_g"]
                entries[key] = fresh
                out["updated"].append(key)
            else:
                out["kept"].append(key)
            continue
        term = search_term(key, book)
        product = pick(search(term), term)
        if product is None:
            if isinstance(old, dict):
                out["kept"].append(key)
                out["stale"].append(key)
            else:
                out["unpriced"].append(key)
            continue
        fresh = entry_from(product, key, term, today)
        if isinstance(old, dict) and _piece_g(old):
            fresh["piece_g"] = old["piece_g"]
        entries[key] = fresh
        out["updated"].append(key)
    book["updated"] = _iso(today)
    return out


def keys_of(lines):
    """The distinct ingredient keys of grocery lines, in order; headers,
    blanks and the free ones (water) dropped, a line's own price suffix
    ignored: what a refresh prices."""
    out, seen = [], set()
    for ln in lines or []:
        bare = strip_price(ln)
        key = ingredient_key(bare)
        if not key or key in FREE or key in seen:
            continue
        if ms.parse_quantity(bare).amount is None and is_header_line(bare):
            continue
        seen.add(key)
        out.append(key)
    return out


# ── a price typed by hand ──────────────────────────────────────────────────
# The book screen asks "price / amount unit" for a key knuspr cannot answer
# (or answers wrong): "2.99 / 10 pc", "1.49 / 100 g", "2,99 / 10 Stk". A
# bare price is one piece. The pack words are meal_scale's units plus the
# piece words a German shelf and an English cook both use.
_ANSWER = re.compile(r"^\s*(?:€\s*)?(\d+(?:[.,]\d+)?)\s*(?:€\s*)?"
                     r"(?:/\s*(\d+(?:[.,]\d+)?)?\s*([^\W\d_]+)?\.?\s*)?$")
_PIECE_WORDS = frozenset(("pc", "pcs", "piece", "pieces", "stk", "stück", "stueck", "st", "x", "each"))


def parse_price_answer(text):
    """(price, amount, unit_text) from what Vex typed: "2.99 / 10 pc" ->
    (2.99, 10.0, "pc"), "2,99 / 10 Stk" -> (2.99, 10.0, "Stk"), "3.19/10pc"
    -> (3.19, 10.0, "pc"), "0.89 / 1 Bund" -> (0.89, 1.0, "Bund"), "2.99"
    alone -> (2.99, 1.0, "pc"), a euro sign tolerated. The unit comes back
    as typed; manual_entry is the one that judges it. ValueError, one
    line, on anything else."""
    m = _ANSWER.match(text or "")
    if not m:
        raise ValueError(f"not a price: {text!r} (want e.g. 2.99 / 10 pc)")
    price = _shop_num(m.group(1))
    amount = _shop_num(m.group(2)) if m.group(2) else 1.0
    if amount <= 0:
        raise ValueError(f"amount must be above zero: {text!r}")
    return price, amount, m.group(3) or "pc"


def _manual_base(amount, unit_text):
    """(base amount, base) of a hand-typed pack: a meal_scale unit goes
    through parse_quantity + to_base ("1 lb" -> 454 g), a knuspr pack word
    through _PACK_UNITS ("1 Bund" -> 1 pc), a piece word is pieces.
    ValueError on a word nobody knows."""
    u = (unit_text or "").strip().rstrip(".").lower()
    if not u or u in _PIECE_WORDS:
        return amount, "pc"
    if u in ms._ALIAS:
        q = ms.parse_quantity(f"{_num(amount)} {u}")
        base_amount, base = to_base(q)
        if base_amount is not None and q.unit:
            return base_amount, base
    if u in _PACK_UNITS:
        f, base = _PACK_UNITS[u]
        return amount * f, base
    raise ValueError(f"unknown unit {unit_text!r} (want g, kg, ml, l, pc, Stk, Bund ...)")


def manual_entry(key, price, amount, unit_text, today, search=None):
    """A book entry typed by hand, source "manual", the shape entry_from
    writes with no product behind it: `price` for `amount` of `unit_text`
    ("10 pc", "100 g", "1 l", "1 lb", "12 Stk") brought to per / per_unit
    and pack_amount / pack_unit through meal_scale.parse_quantity + to_base.
    refresh never touches it (Vex typed it, the shop does not get a say).
    ValueError, one line, on a blank key, a price or amount that is not a
    number, a negative price, an amount of zero or a unit nobody knows."""
    if not (key or "").strip():
        raise ValueError("a manual price needs an ingredient key")
    try:
        price, amount = _hand_num(price), _hand_num(amount)
    except (TypeError, ValueError):
        raise ValueError(f"price and amount must be numbers, got {price!r} / {amount!r}") from None
    if not (math.isfinite(price) and math.isfinite(amount)) or price < 0 or amount <= 0:
        raise ValueError(f"price {price!r} for {amount!r} makes no sense")
    base_amount, base = _manual_base(amount, unit_text)
    unit_text = (unit_text or "pc").strip()
    return {"key": key.strip(), "search": search or "", "product": "", "product_id": None,
            "pack": f"{_num(amount)} {unit_text}", "pack_amount": round(base_amount, 6), "pack_unit": base,
            "price": _round2(price), "per": round(price / base_amount, 6), "per_unit": base,
            "source": "manual", "date": _iso(today), "pinned": False, "url": ""}


def _hand_num(x):
    """A number as handed in: a float, an int, or text with a comma or a
    point ("0,29"); a bool is never a price. ValueError otherwise."""
    if isinstance(x, bool):
        raise ValueError(repr(x))
    if isinstance(x, (int, float)):
        return float(x)
    return _shop_num(str(x).strip())


if __name__ == "__main__":       # python3 src/meal_price.py Eier | --cost "14 Eggs" ...
    import sys
    _args = sys.argv[1:]
    if not _args:
        sys.exit("usage: meal_price.py <knuspr term>  |  meal_price.py --cost <line>...")
    if _args[0] == "--cost":
        _book = load_book()
        _lines = _args[1:]
        for _c in list_cost(_lines, _book).costs:
            _euro = "" if _c.cost is None else f"{_c.cost:.2f} €"
            print(f"{_euro:>9}  {_c.reason:<14} {_c.key:<24} {_c.per_line_note}")
        print(cost_line(list_cost(_lines, _book)))
    else:
        _term = " ".join(_args)
        _found = knuspr_search(_term)
        for _p in rank(_found, _term)[:5]:
            print(f"{str(_p.id or ''):>7}  {_p.price:>6.2f} €  {str(_p.pack):<12} {_per_text(_p.per, _p.per_unit):>12}"
                  f"  {'' if _p.in_stock else '(out) '}{_p.name}")
        if not _found:
            print("nothing found")
