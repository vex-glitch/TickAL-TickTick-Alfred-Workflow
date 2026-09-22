"""meal_scale.py - recipe yield + ingredient scaling (PURE: stdlib only, no I/O).

Vex preps a week of one meal at a time: SEVEN portions of whatever Mela
recipe is on the board. A recipe says "serves 4" - or nothing, or "10 Total"
inside a macros line, or only that it has 850 g of chicken in it - and every
ingredient line has to become its 7-portion amount before it is a shopping
list. Three jobs live here:

  infer_yield     how many portions the recipe makes AS WRITTEN, by a ladder:
                  Mela's yield field, then yield phrases in the text, then a
                  guess from protein weight (170 g a portion), then "unknown".
                  It says which rung answered, because a wrong yield scales
                  every line wrong and the note has to show its working.
  parse_quantity  the leading number + unit of an ingredient line: "1 1/2",
                  "1½", "1,5", "450g", "2-3", "2 x 400 g cans" (the x is not a
                  unit, so it stays at the front of the rest). A word after
                  the number is a unit ONLY if it is in the UNITS table.
  scale_line      the line at a factor, rounded the way a cook rounds: grams
                  to 5 above 50, spoons to quarters, counts to whole, never
                  to zero. Rounding is HALF-UP by hand (floor(x + .5)):
                  Python's round() is banker's rounding and turns 2.625 tsp
                  into "2 1/2" instead of "2 3/4" (a real regression).

A recipe is whatever the caller has - a dict or an object - with title,
yield_text, text, nutrition, instructions, ingredients, notes as strings;
ingredient/instruction lines starting with "#" are section headers.
"""
import math
import re
from collections import namedtuple
from fractions import Fraction

Qty = namedtuple("Qty", "amount amount_text unit rest range_hi")

GRAMS_PER_PORTION = 170        # Vex's plate: ~170 g raw protein a portion
SANE = (1, 40)                 # a yield outside this is a calorie count, not a yield
_EPS = 1e-9                    # float noise guard: 10.499999999 is a 10.5


def _get(recipe, key):
    """A recipe field as text, from a dict or an object; '' when absent.
    A list (some importers hand lines as a list) is joined with newlines."""
    if recipe is None:
        return ""
    v = recipe.get(key) if isinstance(recipe, dict) else getattr(recipe, key, None)
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "\n".join(str(x) for x in v)
    return str(v)


def lines(s):
    """Stripped, non-empty lines."""
    return [ln.strip() for ln in (s or "").splitlines() if ln.strip()]


def is_header(line):
    """A '#' line is a section header (Mela's convention)."""
    return (line or "").lstrip().startswith("#")


def header_text(line):
    """The header without its '#'s: '## Sauce' -> 'Sauce'."""
    return (line or "").strip().lstrip("#").strip()


# ── units ──────────────────────────────────────────────────────────────────
# canonical: (class, plural, aliases). Only a word IN this table is a unit;
# any other word after the number is the ingredient ("2 large eggs",
# "2 scallions", "2 x 400 g cans"). The class picks the rounding rule.
_UNIT_ROWS = (
    ("g", "mass_g", None, ("g", "gr", "gram", "grams")),
    ("kg", "mass_kg", None, ("kg", "kilo", "kilos", "kilogram", "kilograms")),
    ("mg", "mass_g", None, ("mg", "milligram", "milligrams")),
    ("ml", "vol_ml", None, ("ml", "millilitre", "millilitres", "milliliter", "milliliters")),
    ("l", "vol_l", None, ("l", "litre", "litres", "liter", "liters")),
    ("dl", "vol_l", None, ("dl", "decilitre", "decilitres", "deciliter", "deciliters")),
    ("tsp", "spoon", None, ("tsp", "tsps", "teaspoon", "teaspoons")),
    ("tbsp", "spoon", None, ("tbsp", "tbsps", "tbs", "tablespoon", "tablespoons")),
    ("cup", "spoon", "cups", ("cup", "cups")),
    ("lb", "lb", None, ("lb", "lbs", "pound", "pounds")),
    ("oz", "oz", None, ("oz", "ounce", "ounces")),
    ("can", "count", "cans", ("can", "cans", "tin", "tins")),
    ("packet", "count", "packets",
     ("packet", "packets", "pack", "packs", "package", "packages", "pkg")),
    ("bunch", "count", "bunches", ("bunch", "bunches")),
    ("clove", "count", "cloves", ("clove", "cloves")),
    ("stalk", "count", "stalks", ("stalk", "stalks")),
    ("slice", "count", "slices", ("slice", "slices")),
    ("sprig", "count", "sprigs", ("sprig", "sprigs")),
    ("piece", "count", "pieces", ("piece", "pieces")),
    ("stick", "count", "sticks", ("stick", "sticks")),
    ("head", "count", "heads", ("head", "heads")),
    ("handful", "count", "handfuls", ("handful", "handfuls")),
    ("pinch", "count", "pinches", ("pinch", "pinches")),
    ("jar", "count", "jars", ("jar", "jars")),
    ("block", "count", "blocks", ("block", "blocks")),
    ("sheet", "count", "sheets", ("sheet", "sheets")),
    ("fillet", "count", "fillets", ("fillet", "fillets")),
    ("scoop", "count", "scoops", ("scoop", "scoops")),
)
UNITS = {canon: (cls, plural) for canon, cls, plural, _ in _UNIT_ROWS}
_ALIAS = {a: canon for canon, _, _, aliases in _UNIT_ROWS for a in aliases}
_MASS_G = {"g": 1.0, "kg": 1000.0, "lb": 454.0, "oz": 28.35}   # for the protein guess

# ── numbers ────────────────────────────────────────────────────────────────
_VULGAR = {"½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75,
           "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875}
_VF = "".join(_VULGAR)
# one number token; alternatives longest-first, so "1 1/2" is never read as "1"
_NUMTOK = re.compile(
    r"\d+\s+\d+/[1-9]\d*"                    # 1 1/2
    r"|\d+/[1-9]\d*"                         # 1/2
    r"|\d+(?:[.,]\d+)?\s?[" + _VF + "]"      # 1½  1 ½
    r"|[" + _VF + "]"                        # ½
    r"|\d+(?:[.,]\d+)?"                      # 2  1.5  1,5
    r"|[.,]\d+")                             # .5
_RANGE_SEP = re.compile(r"\s*[-–—]\s*|\s+to\s+", re.I)
_UNIT_WORD = re.compile(r"^([^\W\d_]+)\.?(?![^\W\d_])")     # "tsp", "tsp.", "g"


def _dec(s):
    """'1.5' / '1,5' -> 1.5; '1,500' (comma + exactly three digits) -> 1500."""
    s = s.strip()
    if re.fullmatch(r"\d{1,3},\d{3}", s):
        return float(s.replace(",", ""))
    return float(s.replace(",", "."))


def _to_float(tok):
    """The value of one number token: '1 1/2', '1/2', '1½', '½', '1,5', '.5'."""
    tok = tok.strip()
    m = re.fullmatch(r"(\d+)\s+(\d+)/(\d+)", tok)
    if m:
        return int(m[1]) + int(m[2]) / int(m[3])
    m = re.fullmatch(r"(\d+)/(\d+)", tok)
    if m:
        return int(m[1]) / int(m[2])
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)?\s?([" + _VF + "])", tok)
    if m:
        return (_dec(m[1]) if m[1] else 0.0) + _VULGAR[m[2]]
    return _dec(tok)


def _lead(text):
    """(lo, hi, end) of the number or range that opens `text`, or None.
    Done by hand, not one big regex: the engine would otherwise back off
    "1 1/2" to "1" when what follows is not a range, and read
    "1 1/2-inch piece" as one and a half-inch pieces."""
    m = _NUMTOK.match(text)
    if not m:
        return None
    lo, hi, end = m.group(0), None, m.end()
    sep = _RANGE_SEP.match(text, end)
    if sep:
        h = _NUMTOK.match(text, sep.end())
        if h:
            hi, end = h.group(0), h.end()
    nxt = text[end:end + 1]
    if nxt and not nxt.isspace() and not nxt.isalpha():   # "1-inch", "2(large)"
        return None
    return lo, hi, end


def parse_quantity(line):
    """The leading amount of an ingredient line as
    Qty(amount, amount_text, unit, rest, range_hi); unit is the canonical
    name from UNITS or None, rest is the line after it, verbatim.
    No leading number -> Qty(None, "", None, line, None)."""
    text = (line or "").strip()
    lead = _lead(text)
    if not lead:
        return Qty(None, "", None, text, None)
    lo, hi, end = lead
    rest = text[end:].lstrip()
    unit = None
    u = _UNIT_WORD.match(rest)
    if u and u.group(1).lower() in _ALIAS:
        unit = _ALIAS[u.group(1).lower()]
        rest = rest[u.end():].lstrip()
    return Qty(_to_float(lo), text[:end].strip(), unit, rest.strip(),
               _to_float(hi) if hi else None)


# ── rounding + formatting ──────────────────────────────────────────────────
def _half_up(x):
    """Round half UP, by hand: 10.5 -> 11. NEVER round(): banker's rounding
    gives 10, and 2 5/8 tsp becomes "2 1/2" instead of "2 3/4"."""
    return int(math.floor(x + 0.5 + _EPS))


def _dec1(tenths):
    """tenths/10 as text, trailing '.0' dropped: 28 -> '2.8', 10 -> '1'."""
    return f"{tenths / 10:.1f}".rstrip("0").rstrip(".")


def _mixed(n, den):
    """n/den as a cook writes it: 7/4 -> '1 3/4', 2/4 -> '1/2', 8/4 -> '2'."""
    whole, part = divmod(n, den)
    frac = str(Fraction(part, den)) if part else ""
    if whole and frac:
        return f"{whole} {frac}"
    return frac or str(whole)


def _scaled(value, cls):
    """(text, number) of a scaled amount, rounded by unit class. Nothing
    ever rounds to zero: a pinch scaled down is still a pinch."""
    if cls in ("mass_g", "vol_ml"):
        if value >= 50:                                  # to the nearest 5
            n = 5 * _half_up(value / 5)
            return str(n), n
        if value >= 1:                                   # whole grams
            n = max(1, _half_up(value))
            return str(n), n
        n = max(1, _half_up(value * 10))                 # one decimal
        return _dec1(n), n / 10
    if cls in ("mass_kg", "vol_l"):
        n = max(1, _half_up(value * 10))
        return _dec1(n), n / 10
    if cls in ("spoon", "lb"):                           # quarters
        q = max(1, _half_up(value * 4))
        return _mixed(q, 4), q / 4
    if cls == "oz":                                      # halves
        h = max(1, _half_up(value * 2))
        return _mixed(h, 2), h / 2
    n = max(1, _half_up(value))                          # count units, bare counts
    return str(n), n


def _unit_text(unit, num):
    cls, plural = UNITS[unit]
    return plural if plural and num > 1 else unit


def _assemble(amount_text, unit, rest):
    head = f"{amount_text} {unit}" if unit else amount_text
    if not rest:
        return head
    if rest[0] in ",;:)":                    # "450g, diced" -> "790 g, diced"
        return head + rest
    return f"{head} {rest}"


def scale_line(line, factor):
    """The line at `factor` (7 portions from 4 = 1.75). Blanks, headers and
    lines with no leading number come back untouched; a range scales both
    ends; cup and the count units pluralise past 1."""
    if not line or not line.strip() or is_header(line):
        return line
    q = parse_quantity(line)
    if q.amount is None:
        return line
    cls = UNITS[q.unit][0] if q.unit else "count"
    text, num = _scaled(q.amount * factor, cls)
    if q.range_hi is not None:
        hi_text, num = _scaled(q.range_hi * factor, cls)
        text = f"{text}-{hi_text}"
    return _assemble(text, _unit_text(q.unit, num) if q.unit else "", q.rest)


# ── what is a grocery line? ────────────────────────────────────────────────
# Mela imports drag step numbers, macro lines, "(serves 4)" remarks and
# "For the sauce:" headers into the ingredient list; none of those are
# bought. "1 scoop protein powder" and "1 tbsp bacon fat" ARE bought, so a
# nutrient word only counts when it is followed by ":" or "- <digit>".
_STEP = re.compile(r"^\s*(?:step\s*)?\d{1,2}[.)]\s+\S", re.I)
_MACRO = re.compile(
    r"\bmacros?\b|\bper\s+serving\b"
    r"|\b(?:calories|kcal|protein|carbs?|carbohydrates?|fat|fibre|fiber|sodium|sugars?)\b"
    r"\s*(?::|[-–—]\s*\d)", re.I)
_YIELD_REMARK = re.compile(r"^\s*\(?\s*(?:serves|makes|yields?)\b[^,]{0,20}\)?\s*$", re.I)


def is_grocery_item(line):
    """Is this ingredient line something to buy?"""
    s = (line or "").strip()
    if not s or is_header(s):
        return False
    if _STEP.match(s) or _MACRO.search(s) or _YIELD_REMARK.match(s):
        return False
    if len(s) <= 40 and s.endswith(":") and "(" not in s and not any(c.isdigit() for c in s):
        return False                                     # "For the sauce:"
    return True


# ── yield ──────────────────────────────────────────────────────────────────
# Patterns in PRIORITY order; the first sane hit wins, and the field order is
# nutrition, text, notes, instructions, ingredients. "7 Total" outranks
# "serves 4": Vex's own macro lines say "(Per Serving - 7 Total)" and are the
# truth even when the imported text still says what the site said.
_ABOUT = r"(?:(?:about|approx\.?|approximately|around|roughly|circa|~)\s*)?"
_CNT = (r"(?P<lo>\d+(?:[.,]\d+)?)"
        r"(?:(?:\s*[-–—]\s*|\s+to\s+)(?P<hi>\d+(?:[.,]\d+)?))?")
_NOT_AFTER_TOTAL = r"(?!\s*(?:time|carbs?|carbohydrates?|fat|cal\b|kcal|calories|sugars?|protein))"
_MEASURE = (r"(?:cups?|g\b|grams?|kgs?|kilos?|ml\b|l\b|litres?|liters?|tbsps?|tsps?"
            r"|tablespoons?|teaspoons?|oz\b|ounces?|lbs?|pounds?|cm\b|mm\b|inch|inches|\""
            r"|minutes?|mins?|hours?|hrs?|seconds?|secs?|%|x\b|×)")
_THINGS = (r"(?:burritos?|wraps?|tacos?|bowls?|patties|patty|meatballs?|muffins?|bars?"
           r"|cookies?|pancakes?|rolls?|jars?|containers?|servings?|portions?|meals?"
           r"|plates?|sandwich(?:es)?|pizzas?|balls?|skewers?|fritters?|box(?:es)?)")
_YIELD_PATTERNS = tuple(re.compile(p, re.I) for p in (
    rf"\b{_ABOUT}{_CNT}\s+total\b{_NOT_AFTER_TOTAL}",
    rf"\bserves\b\s*:?\s*{_ABOUT}{_CNT}\b",
    rf"\b{_ABOUT}{_CNT}\s+(?:servings|portions|people|persons)\b",
    rf"\b(?:makes|yields?)\b\s*:?\s*{_ABOUT}{_CNT}\b(?![\s-]*{_MEASURE})",
    rf"\b(?:makes|yields?|serves|enough\s+for|for)\b\s*:?\s*{_ABOUT}{_CNT}\s+"
    rf"(?:(?:large|small|medium|big|generous|hearty|mini|individual)\s+)?{_THINGS}\b",
))
_YIELD_FIELDS = ("nutrition", "text", "notes", "instructions", "ingredients")
_CNT_RE = re.compile(_CNT)



def _count_of(m):
    """The count a yield match names (a range is its midpoint), if sane."""
    lo = _dec(m.group("lo"))
    hi = _dec(m.group("hi")) if m.group("hi") else None
    n = (lo + hi) / 2 if hi is not None else lo
    return n if SANE[0] <= n <= SANE[1] else None


def _read_count(text):
    """The first sane count in free text: '3', '4 servings', '2-3' -> 2.5."""
    for m in _CNT_RE.finditer(text or ""):
        n = _count_of(m)
        if n is not None:
            return n
    return None


# the protein guess: main-protein words, minus the things named after them
# that are not meat ("chicken stock", "chicken skin", "curry paste").
# bone-in / skin-on ARE the meat, so those two only exclude when bare.
_PROTEIN = re.compile(
    r"\b(?:chicken|beef|pork|turkey|mince|minced|sirloin|thighs?|breasts?|lamb|salmon"
    r"|tofu|steak|tuna|cod|prawns?|shrimp|tempeh|drumsticks?)\b", re.I)
_NOT_PROTEIN = re.compile(
    r"\b(?:stock|broth|bouillon|powder|sauce|seasoning|fat|oil|paste|rub|crisp)\b"
    r"|\b(?:skin|bones?)\b(?![-\s]?(?:in|on)\b)", re.I)


def protein_grams(recipe):
    """Grams of main protein across the ingredient lines (mass units only)."""
    total = 0.0
    for ln in lines(_get(recipe, "ingredients")):
        if is_header(ln):
            continue
        q = parse_quantity(ln)
        if q.amount is None or q.unit not in _MASS_G:
            continue
        if not _PROTEIN.search(q.rest) or _NOT_PROTEIN.search(q.rest):
            continue
        amount = (q.amount + q.range_hi) / 2 if q.range_hi is not None else q.amount
        total += amount * _MASS_G[q.unit]
    return total


def infer_yield(recipe):
    """(portions, source, detail): how many portions the recipe makes.
    source is the rung that answered - "field" (Mela's yield), "text" (a
    yield phrase in the recipe), "estimate" (protein weight at 170 g a
    portion), "none" - and detail is what was read, for the note:
    "'Serves 3' in nutrition", "850 g protein"."""
    yt = _get(recipe, "yield_text").strip()
    n = _read_count(yt)
    if n is not None:
        return n, "field", f"'{yt}' in yield"
    for pat in _YIELD_PATTERNS:
        for field in _YIELD_FIELDS:
            for m in pat.finditer(_get(recipe, field)):
                n = _count_of(m)
                if n is not None:
                    snippet = " ".join(m.group(0).split())
                    return n, "text", f"'{snippet}' in {field}"
    grams = protein_grams(recipe)
    if grams >= 100:
        est = float(max(1, _half_up(grams / GRAMS_PER_PORTION)))
        return est, "estimate", f"{_half_up(grams)} g protein"
    return None, "none", ""


# ── the whole list ─────────────────────────────────────────────────────────
def _fmt_factor(f):
    return f"{f:.2f}".rstrip("0").rstrip(".")


def yield_note(y, source, detail, factor, portions):
    """One line for the top of a scaled list: what was done, from what."""
    p = f"{portions:g}"
    if y is None:
        return "⚠️ Yield unknown, quantities unscaled"
    if factor == 1:
        note = f"Already {p} portions, unscaled"
        if source == "estimate":
            note = f"≈ Already {p} portions (est. from {detail}), unscaled"
    elif source == "estimate":
        note = f"≈ Scaled ×{_fmt_factor(factor)}: est. {y:g} portions from {detail} → {p}"
    else:
        note = f"Scaled ×{_fmt_factor(factor)}: {y:g} → {p} portions"
    # x7 is a one-portion recipe - nearly always a misread "1 serving" size
    if factor >= 7 or factor < 0.2:
        note = "⚠️ check yield · " + note
    return note


def scaled_ingredients(recipe, portions=7, headers="drop"):
    """The recipe's ingredient lines at `portions`, plus how they got there:
    (lines, {factor, yield, source, detail, note, portions, unscaled, dropped}).
    headers: "drop" (default), "bold" (**Sauce**) or "keep" (as written).
    Non-grocery lines are dropped and counted; a line with no leading number
    is kept as written and listed in info["unscaled"], so the caller can say
    "check these" instead of silently under-buying."""
    y, source, detail = infer_yield(recipe)
    factor = portions / y if y else 1.0
    out, unscaled, dropped = [], [], 0
    for ln in lines(_get(recipe, "ingredients")):
        if is_header(ln):
            if headers == "bold":
                if header_text(ln):
                    out.append(f"**{header_text(ln)}**")
            elif headers != "drop":
                out.append(ln)
            continue
        if not is_grocery_item(ln):
            dropped += 1
            continue
        if parse_quantity(ln).amount is None:
            unscaled.append(ln)
            out.append(ln)
            continue
        out.append(scale_line(ln, factor) if factor != 1 else ln)
    info = {"factor": factor, "yield": y, "source": source, "detail": detail,
            "note": yield_note(y, source, detail, factor, portions),
            "portions": portions, "unscaled": unscaled, "dropped": dropped}
    return out, info


# ── a re-cut list keeps its ticks ──────────────────────────────────────────
# Vex 2026-09-22: "a row that would ask me how many portions of each meal I
# would like to cook this week and then adjust groceries accordingly". A
# re-cut replaces every checklist item (the amounts change, so the titles
# do), and a tick made in the shop would go with the old item; the tick
# follows the INGREDIENT instead, the part of the line that does not move.
def tick_key(line):
    """The ingredient without its amount, the name a tick follows across a
    re-cut: parse_quantity's rest (the whole line when it has no leading
    number - a bold header, "Avocado oil"), casefolded, whitespace
    collapsed. "875 g chicken" and "625 g Chicken" are one key."""
    return " ".join((parse_quantity(line).rest or "").split()).casefold()


def _ticked(item):
    return isinstance(item, dict) and str(item.get("status", 0)) == "2"


def carry_ticks(old_items, lines):
    """The sync's own item shape for `lines` in order - {title, status,
    sortOrder = index}, no ids (the update posts a fresh list) - with
    status 2 wherever the SAME ingredient was ticked before, else 0. The
    new lines come from the same recipe in the same order as the old
    items, so a tick follows (tick_key, ordinal among same-key items): the
    salt of the sauce section stays ticked, the salt of the marinade does
    not swap places with it. A tick whose ordinal no longer exists (the
    recipe lost a line) falls back to the first still-open line of that
    key, so a tick is never dropped while its ingredient is on the list.
    Pure; None or empty old_items = every line open."""
    ticked, seen = {}, {}
    for it in old_items or []:
        if not isinstance(it, dict):
            continue
        k = tick_key(it.get("title") or "")
        o = seen.get(k, 0)
        seen[k] = o + 1
        if _ticked(it):
            ticked.setdefault(k, set()).add(o)
    out, seen = [], {}
    for i, ln in enumerate(lines or []):
        k = tick_key(ln)
        o = seen.get(k, 0)
        seen[k] = o + 1
        status = 2 if o in ticked.get(k, ()) else 0
        if status:
            ticked[k].discard(o)
        out.append({"title": ln, "status": status, "sortOrder": i})
    for k, left in ticked.items():             # the fallback: ordinals gone
        for it in out:
            if not left:
                break
            if it["status"] == 0 and tick_key(it["title"]) == k:
                it["status"] = 2
                left.pop()
    return out


if __name__ == "__main__":                 # python3 src/meal_scale.py 1.75 "1 1/2 tsp salt" ...
    import sys
    if len(sys.argv) < 3:
        sys.exit("usage: meal_scale.py <factor> <line>...")
    try:
        _f = float(sys.argv[1])
    except ValueError:
        sys.exit(f"not a factor: {sys.argv[1]!r}")
    for _ln in sys.argv[2:]:
        print(scale_line(_ln, _f))
