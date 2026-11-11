"""Is this new recipe one we already have? Normalized-title similarity, ingredient-set overlap and the same source URL.

Pure functions (stdlib only) so the thresholds can be tested directly.
"""
import re
import urllib.parse
from difflib import SequenceMatcher

STOP = set("""a an and the of with in on for to my our best easy quick simple homemade classic recipe recipes style
favorite favourite perfect ultimate world's grandma's mom's moms grandmas""".split())
UNITS = set("""cup cups c tbsp tablespoon tablespoons tsp teaspoon teaspoons oz ounce ounces lb lbs pound pounds g gram grams kg
ml l liter liters litre clove cloves can cans package packages pkg pinch dash large small medium whole stick sticks slice slices
bunch head heads sprig sprigs handful quart quarts pint pints""".split())
PREP = set("""chopped diced minced sliced grated shredded fresh freshly ground divided softened melted room temperature to taste
optional finely roughly thinly peeled packed beaten cold warm hot cubed halved crushed plus more for serving""".split())

# Thresholds (tested in tests/test_dupes.py)
TITLE_SAME = 0.92            # titles this close are "the same name"
TITLE_CLOSE = 0.75           # …close enough when the ingredients agree too
INGS_CLOSE = 0.5             # ingredient overlap (Jaccard) that backs up a close title
INGS_SAME = 0.8              # nearly the same ingredients…
TITLE_LOOSE = 0.45           # …with a loosely similar title


def norm_title(s):
    words = re.findall(r"[a-z0-9]+", (s or "").lower().replace("&", " and "))
    words = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words]
    return " ".join(w for w in words if w not in STOP)


def title_similarity(a, b):
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jac = len(ta & tb) / len(ta | tb)
    return round(max(seq, jac), 3)


def ingredient_key(line):
    """The food in an ingredient line: '2 cups all-purpose flour, sifted' -> 'all purpose flour'."""
    s = re.sub(r"\(.*?\)", " ", (line or "").lower())
    s = s.split(",")[0]
    words = [w for w in re.findall(r"[a-z]+", s) if w not in UNITS and w not in PREP and w != "of"]
    words = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words]
    return " ".join(words[-3:])


def ingredient_set(lines):
    return {k for k in (ingredient_key(x) for x in lines or []) if k}


def ingredient_overlap(a, b):
    a, b = set(a), set(b)
    if not a or not b:
        return 0.0
    # partial credit when one key contains the other ("flour" vs "all purpose flour")
    hits = 0
    for x in a:
        if x in b or any(x in y or y in x for y in b if min(len(x), len(y)) >= 4):
            hits += 1
    return round(hits / len(a | b) if hits <= len(a | b) else 1.0, 3)


def norm_url(u):
    try:
        p = urllib.parse.urlparse((u or "").strip())
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not p.hostname:
        return ""
    host = p.hostname.lower()
    host = host[4:] if host.startswith("www.") else host
    return host + re.sub(r"/+$", "", p.path or "")


def match(new, old):
    """new/old: {"name", "ingredients": [lines], "url"}. Returns (score, reasons) — score 0 means no match."""
    if new.get("url") and norm_url(new["url"]) and norm_url(new["url"]) == norm_url(old.get("url")):
        return 1.0, ["same source"]
    t = title_similarity(new.get("name"), old.get("name"))
    i = ingredient_overlap(ingredient_set(new.get("ingredients")), ingredient_set(old.get("ingredients")))
    reasons = []
    if t >= TITLE_SAME and (i >= 0.3 or not new.get("ingredients") or not old.get("ingredients")):
        reasons = ["same name"]
    elif t >= TITLE_CLOSE and i >= INGS_CLOSE:
        reasons = ["similar name", "same ingredients"]
    elif i >= INGS_SAME and t >= TITLE_LOOSE:
        reasons = ["same ingredients"]
    if not reasons:
        return 0.0, []
    return round(0.6 * t + 0.4 * i, 3), reasons


def find(new, existing, limit=3):
    """Likely duplicates of `new` among `existing` ([{"id","slug","name","ingredients","url",...}]), best first."""
    out = []
    for old in existing:
        score, why = match(new, old)
        if score:
            out.append({**{k: old.get(k) for k in ("id", "slug", "name", "url", "has_image")}, "score": score, "reasons": why})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


def keep_both_name(name, taken):
    """'Lemon Bars' -> 'Lemon Bars (2)' only when that exact title is taken (case-insensitive)."""
    low = {t.lower() for t in taken}
    if (name or "").lower() not in low:
        return name
    n = 2
    while f"{name} ({n})".lower() in low:
        n += 1
    return f"{name} ({n})"
