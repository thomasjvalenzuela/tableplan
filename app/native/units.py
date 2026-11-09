"""Kitchen unit conversion (stdlib only).

Units belong to one dimension: volume (base ml), weight (base g) or count. ``convert`` only converts within a
dimension and returns None otherwise, so callers can fall back to "amount unknown".
"""
from fractions import Fraction

VOLUME = {"tsp": 4.92892, "tbsp": 14.7868, "cup": 236.588, "fl oz": 29.5735, "pint": 473.176, "quart": 946.353,
          "gallon": 3785.41, "ml": 1.0, "l": 1000.0}
WEIGHT = {"oz": 28.3495, "lb": 453.592, "g": 1.0, "kg": 1000.0}
# Count units: "" (a plain number, e.g. "2 eggs") and the generic ones are interchangeable; specific containers
# (cans, cloves, ...) only convert to themselves or to a plain count.
GENERIC_COUNT = {"", "piece", "each", "whole", "item"}
COUNT = GENERIC_COUNT | {"clove", "can", "slice", "stick", "head", "bunch", "jar", "bag", "box", "package", "sprig",
                         "stalk", "bottle", "carton", "loaf", "dozen"}

_ALIASES = {
    "t": "tsp", "teaspoon": "tsp", "teaspoons": "tsp", "tsps": "tsp", "tsp": "tsp",
    "T": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsps": "tbsp", "tbs": "tbsp", "tbl": "tbsp", "tbsp": "tbsp",
    "c": "cup", "cup": "cup", "cups": "cup",
    "fl oz": "fl oz", "floz": "fl oz", "fl. oz": "fl oz", "fluid ounce": "fl oz", "fluid ounces": "fl oz",
    "pint": "pint", "pints": "pint", "pt": "pint", "pts": "pint",
    "quart": "quart", "quarts": "quart", "qt": "quart", "qts": "quart",
    "gallon": "gallon", "gallons": "gallon", "gal": "gallon",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "millilitres": "ml",
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "g": "g", "gram": "g", "grams": "g", "gr": "g",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "pieces": "piece", "pc": "piece", "pcs": "piece", "cloves": "clove", "cans": "can", "slices": "slice",
    "sticks": "stick", "heads": "head", "bunches": "bunch", "jars": "jar", "bags": "bag", "boxes": "box",
    "packages": "package", "pkg": "package", "pkgs": "package", "sprigs": "sprig", "stalks": "stalk",
    "bottles": "bottle", "cartons": "carton", "loaves": "loaf", "dozens": "dozen", "items": "item",
}
_PLURAL = {"cup": "cups", "pint": "pints", "quart": "quarts", "gallon": "gallons", "clove": "cloves", "can": "cans",
           "slice": "slices", "stick": "sticks", "head": "heads", "bunch": "bunches", "jar": "jars", "bag": "bags",
           "box": "boxes", "package": "packages", "sprig": "sprigs", "stalk": "stalks", "piece": "pieces",
           "bottle": "bottles", "carton": "cartons", "loaf": "loaves", "dozen": "dozen", "item": "items"}

# Units offered in the pantry amount editor.
CHOICES = ["", "tsp", "tbsp", "cup", "fl oz", "pint", "quart", "gallon", "ml", "l", "oz", "lb", "g", "kg",
           "piece", "clove", "can", "slice", "stick", "jar", "bag", "box", "package", "bottle", "loaf", "dozen"]


def normalize(unit):
    """Canonical unit name ('' for a plain count), or the cleaned input when it isn't a known unit."""
    if unit is None:
        return ""
    u = " ".join(str(unit).replace(".", " ").split())
    if u in ("T", "t"):
        return _ALIASES[u]
    return _ALIASES.get(u.lower(), u.lower())


def dimension(unit):
    u = normalize(unit)
    if u in VOLUME:
        return "volume"
    if u in WEIGHT:
        return "weight"
    if u in COUNT:
        return "count"
    return None


def convert(q, from_unit, to_unit):
    """Convert q from one unit to another; None when the units measure different things."""
    if q is None:
        return None
    a, b = normalize(from_unit), normalize(to_unit)
    if a == b:
        return float(q)
    da, db = dimension(a), dimension(b)
    if da != db or da is None:
        return None
    if da == "volume":
        return float(q) * VOLUME[a] / VOLUME[b]
    if da == "weight":
        return float(q) * WEIGHT[a] / WEIGHT[b]
    if a == "dozen" and b in GENERIC_COUNT:
        return float(q) * 12
    if b == "dozen" and a in GENERIC_COUNT:
        return float(q) / 12
    if a in GENERIC_COUNT or b in GENERIC_COUNT:
        return float(q)
    return None


def nice(q):
    if q is None:
        return ""
    if q <= 0:
        return "0"
    frac = Fraction(q).limit_denominator(8)
    if abs(float(frac) - q) > 0.02 or frac.denominator not in (1, 2, 3, 4, 8):
        return f"{q:.2f}".rstrip("0").rstrip(".")
    whole, rem = divmod(frac.numerator, frac.denominator)
    if not rem:
        return str(whole)
    return f"{whole} {rem}/{frac.denominator}" if whole else f"{rem}/{frac.denominator}"


def fmt(q, unit, food=""):
    """'1 cup', '2 1/2 cups', '3 eggs', '200 g flour'."""
    u = normalize(unit)
    shown = _PLURAL.get(u, u) if (q or 0) > 1 else u
    return " ".join(x for x in (nice(q), shown, food) if x)


__all__ = ["normalize", "dimension", "convert", "nice", "fmt", "CHOICES"]
