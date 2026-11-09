"""Canonical foods: one row per real food ("Table salt", "Sea salt", "Unsalted butter"), plus aliases.

Every ingredient line, shopping item, pantry item and barcode resolves to a food id, so "Morton Iodized Salt 26 oz",
"table salt" and "Salt, table" are the same food while sea salt stays different. Stdlib only; callers own the
transaction (row_factory=sqlite3.Row).
"""
import json
import re
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS foods (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    key TEXT NOT NULL UNIQUE,
    category TEXT,
    location TEXT,
    shelf_rule_id INTEGER,
    store_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_aliases (
    alias_key TEXT PRIMARY KEY,
    food_id INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
    raw TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_food_aliases_food ON food_aliases(food_id);
CREATE TABLE IF NOT EXISTS food_merges (
    token TEXT PRIMARY KEY, at TEXT NOT NULL, data TEXT NOT NULL
);
"""

# Words that never change what the food is.
MARKETING = set("""organic natural all-natural premium family size value pack original classic fresh freshly pure iodized
brand select choice signature store kirkland great fancy deluxe homestyle traditional authentic gourmet best quality
naturally simply finest real genuine imported fine domestic grade a non-gmo gmo gluten-free kosher-certified new improved""".split())
CONTAINERS = set("""can cans jar jars bag bags bottle bottles box boxes carton cartons package packages pkg pkgs container
containers tub tubs canister canisters pouch pouches tin tins packet packets sleeve case""".split())
PREP = set("""chopped diced minced sliced grated shredded large small medium boneless skinless raw peeled softened melted
finely roughly thinly room temperature cold cubed halved quartered crushed beaten divided packed heaping level optional
trimmed rinsed drained cooked uncooked frozen thawed""".split())
STOPWORDS = set("of and the a an or with for to in".split())
UNIT_WORDS = set("""oz ounce ounces fl lb lbs pound pounds g gram grams kg ml l liter liters litre litres ct count pk qt pt
gal gallon gallons quart quarts pint pints cup cups tbsp tsp tablespoon tablespoons teaspoon teaspoons dozen each ea""".split())
KEEP_PLURAL = set("greens oats grits molasses hummus couscous asparagus swiss brussels chives".split())
KNOWN_BRANDS = set("""morton diamond kraft heinz hunt's hunts campbell's campbells kellogg's kelloggs nestle nestlé barilla
ragu prego o'lakes tillamook kerrygold philadelphia chobani fage dannon yoplait hormel tyson perdue domino pillsbury
mccormick goya dole stouffer's lipton folgers maxwell starbucks quaker nabisco ritz kroger safeway kirkland""".split())

# Same food, different words (normalised keys on both sides).
SYNONYMS = {
    "salt": "table salt", "iodized salt": "table salt", "fine salt": "table salt", "table salt": "table salt",
    "salt table": "table salt",
    "evoo": "extra virgin olive oil", "virgin olive oil": "extra virgin olive oil",
    "flour": "all purpose flour", "ap flour": "all purpose flour", "plain flour": "all purpose flour",
    "white flour": "all purpose flour",
    "sugar": "granulated sugar", "white sugar": "granulated sugar", "cane sugar": "granulated sugar",
    "confectioner's sugar": "powdered sugar", "confectioners sugar": "powdered sugar", "icing sugar": "powdered sugar",
    "whipping cream": "heavy cream", "heavy whipping cream": "heavy cream",
    "scallion": "green onion", "spring onion": "green onion",
    "cilantro leaf": "cilantro", "coriander leaf": "cilantro",
    "garbanzo bean": "chickpea", "egg": "egg", "black peppercorn": "black pepper", "ground black pepper": "black pepper",
    "pepper": "black pepper",
}

# Canonical foods everyone needs from day one, with the modifiers that make them different foods.
SEED = ["Table salt", "Sea salt", "Kosher salt", "Black pepper", "Salted butter", "Unsalted butter", "Butter", "Milk",
        "Whole milk", "2% milk", "Skim milk", "Heavy cream", "Half-and-half", "Granulated sugar", "Light brown sugar",
        "Dark brown sugar", "Powdered sugar", "All-purpose flour", "Bread flour", "Olive oil", "Extra-virgin olive oil",
        "Vegetable oil", "Eggs", "Chicken breast", "Chicken thigh", "Ground beef", "Garlic", "Onion", "Green onion",
        "Baking soda", "Baking powder", "Water", "Cooking spray", "Ground cinnamon", "Cinnamon stick"]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def singular(w):
    if w in KEEP_PLURAL or len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("oes", "ches", "shes", "xes", "sses")):
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


_QTY_RE = re.compile(r"\b\d+(?:[.,/]\d+)?\s*(?:x|×)\s*\d+(?:[.,]\d+)?\s*[a-z]*|\b\d+(?:[.,/]\d+)?\s*(?:fl\.?\s*oz|[a-z]+)?\b")


def normalize(text, brand=""):
    """A matching key: 'Morton Iodized Table Salt, 26 oz' -> 'table salt'; 'Salt, table' -> 'table salt';
    'unsalted butter' stays 'unsalted butter'; 'tomatoes' -> 'tomato'."""
    t = (text or "").lower()
    t = t.replace("&amp;", "&").replace("’", "'")
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t)
    # "Salt, table" / "Cheese, shredded": a short qualifier after the comma goes first
    if "," in t:
        head, _, tail = t.partition(",")
        hw, tw = head.split(), re.sub(r"[^a-z% ]", " ", tail).split()
        if 1 <= len(hw) <= 2 and 1 <= len(tw) <= 2 and not any(re.search(r"\d", x) for x in tw):
            t = f"{tail} {head}"
        else:
            t = head
    t = t.replace("extra-virgin", "extra virgin").replace("all-purpose", "all purpose")
    t = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"\1pct", t)          # keep 2% milk distinct
    t = _QTY_RE.sub(lambda m: m.group(0) if m.group(0).endswith("pct") else " ", t)
    t = t.replace("-", " ")
    brand_words = set(re.findall(r"[a-z0-9&'.]+", (brand or "").lower()))
    words = re.findall(r"[a-z0-9&'.%]+", t)
    out = []
    for w in words:
        w = w.strip(".'")
        if not w or w in STOPWORDS or w in MARKETING or w in CONTAINERS or w in PREP or w in UNIT_WORDS:
            continue
        if w in brand_words or w in KNOWN_BRANDS:
            continue
        if w.isdigit():
            continue
        out.append(w.replace("pct", "%") if w.endswith("pct") else singular(w))
    key = " ".join(out)
    return SYNONYMS.get(key, key)


def display_name(key):
    """'all purpose flour' -> 'All-purpose flour'; 'extra virgin olive oil' -> 'Extra-virgin olive oil'."""
    n = key.replace("all purpose", "all-purpose").replace("extra virgin", "extra-virgin").replace("half half", "half-and-half")
    return n[:1].upper() + n[1:] if n else n


def init(c):
    c.executescript(SCHEMA)


def get(c, food_id):
    r = c.execute("SELECT * FROM foods WHERE id=?", (food_id,)).fetchone()
    return dict(r) if r else None


def _create(c, name, key, **extra):
    cur = c.execute("INSERT INTO foods(name, key, category, location, shelf_rule_id, store_id, created_at) "
                    "VALUES (?,?,?,?,?,?,?)", (name, key, extra.get("category"), extra.get("location"),
                                                extra.get("shelf_rule_id"), extra.get("store_id"), _now()))
    return cur.lastrowid


def alias(c, raw, food_id, key=None):
    key = key if key is not None else normalize(raw)
    if key:
        c.execute("INSERT INTO food_aliases(alias_key, food_id, raw) VALUES (?,?,?) "
                  "ON CONFLICT(alias_key) DO UPDATE SET food_id=excluded.food_id, raw=excluded.raw", (key, food_id, raw[:120]))


def lookup(c, text, brand=""):
    """The food id for text if it's already known (alias, exact key or same words in another order), else None."""
    key = normalize(text, brand)
    if not key:
        return None
    r = c.execute("SELECT food_id FROM food_aliases WHERE alias_key=?", (key,)).fetchone()
    if r:
        return r["food_id"]
    r = c.execute("SELECT id FROM foods WHERE key=?", (key,)).fetchone()
    if r:
        return r["id"]
    toks = sorted(key.split())
    for f in c.execute("SELECT id, key FROM foods WHERE length(key)=?", (len(key),)):
        if sorted(f["key"].split()) == toks:     # word order only; modifiers must all match
            return f["id"]
    return None


def resolve(c, text, brand="", create=True, **extra):
    """Food id for an ingredient, list line, pantry name or product title. Creates a canonical food when new."""
    fid = lookup(c, text, brand)
    key = normalize(text, brand)
    if fid is None and key and create:
        fid = _create(c, display_name(key), key, **extra)
    if fid is not None and key and (text or "").strip().lower() != key:
        if not c.execute("SELECT 1 FROM food_aliases WHERE alias_key=?", (key,)).fetchone():
            alias(c, text.strip(), fid, key)
    return fid


def resolve_many(c, texts, classify=None):
    """Resolve several names at once. Unknown ones can go to classify(unknown_texts, existing_foods) ->
    [{text, food_id | None, new_name}] (an AI call); its answers are cached as aliases. Returns {text: food_id}."""
    out, unknown = {}, []
    for t in dict.fromkeys(x for x in texts if x and x.strip()):
        fid = lookup(c, t)
        if fid is None and normalize(t):
            unknown.append(t)
        out[t] = fid
    if unknown and classify:
        existing = [{"id": r["id"], "name": r["name"]} for r in c.execute("SELECT id, name FROM foods ORDER BY name")]
        valid = {f["id"] for f in existing}
        try:
            answers = classify(unknown, existing) or []
        except Exception:
            answers = []
        for a in answers:
            t = a.get("text")
            if t not in unknown or out.get(t) is not None:
                continue
            fid = a.get("food_id")
            if isinstance(fid, int) and fid in valid:
                alias(c, t, fid)
                out[t] = fid
            elif (a.get("new_name") or "").strip():
                nk = normalize(a["new_name"])
                if nk:
                    out[t] = lookup(c, a["new_name"]) or _create(c, display_name(nk), nk)
                    alias(c, t, out[t])
    for t in unknown:
        if out.get(t) is None:
            out[t] = resolve(c, t)
    return out


def seed(c, rules=()):
    """Canonical foods from the built-in list and the shelf-life rule names (linked to their rule)."""
    n = 0
    for name in SEED:
        key = normalize(name)
        if key and not c.execute("SELECT 1 FROM foods WHERE key=?", (key,)).fetchone():
            _create(c, name, key)
            n += 1
    for r in rules:
        key = normalize(r["name"])
        if not key:
            continue
        row = c.execute("SELECT id, shelf_rule_id FROM foods WHERE key=?", (key,)).fetchone()
        if row:
            if row["shelf_rule_id"] is None:
                c.execute("UPDATE foods SET shelf_rule_id=? WHERE id=?", (r["id"], row["id"]))
        else:
            _create(c, display_name(key), key, shelf_rule_id=r["id"], location=r["default_location"])
            n += 1
    return n


def rename(c, food_id, name):
    name = " ".join((name or "").split())
    if not 1 <= len(name) <= 60:
        raise ValueError("Names are 1-60 characters.")
    old = get(c, food_id)
    if not old:
        raise KeyError(food_id)
    key = normalize(name) or name.lower()
    other = c.execute("SELECT id FROM foods WHERE key=? AND id<>?", (key, food_id)).fetchone()
    if other:
        raise ValueError(f"{name} already exists. Merge the two instead.")
    alias(c, old["name"], food_id, old["key"])
    c.execute("UPDATE foods SET name=?, key=? WHERE id=?", (name[:1].upper() + name[1:], key, food_id))
    return get(c, food_id)


def update(c, food_id, **fields):
    allowed = {k: v for k, v in fields.items() if k in ("category", "location", "store_id")}
    if not allowed:
        return get(c, food_id)
    cols = sorted(allowed)
    c.execute(f"UPDATE foods SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?", [allowed[k] for k in cols] + [food_id])
    return get(c, food_id)


def aliases(c, food_id):
    return [r["raw"] or r["alias_key"] for r in c.execute("SELECT * FROM food_aliases WHERE food_id=? ORDER BY raw", (food_id,))]


def merge(c, ids, into, repoint):
    """Merge foods `ids` into `into`. repoint(c, from_id, to_id) moves references held elsewhere (recipes, list, pantry)
    and returns what it moved, for Undo. Returns an undo token."""
    import secrets
    target = get(c, into)
    if not target:
        raise KeyError(into)
    gone, moved = [], {}
    for fid in ids:
        if fid == into:
            continue
        f = get(c, fid)
        if not f:
            continue
        als = [dict(r) for r in c.execute("SELECT * FROM food_aliases WHERE food_id=?", (fid,))]
        moved[str(fid)] = {"food": f, "aliases": als, "refs": repoint(c, fid, into)}
        c.execute("UPDATE food_aliases SET food_id=? WHERE food_id=?", (into, fid))
        alias(c, f["name"], into, f["key"])
        c.execute("DELETE FROM foods WHERE id=?", (fid,))
        gone.append(fid)
    token = secrets.token_urlsafe(10)
    c.execute("INSERT INTO food_merges(token, at, data) VALUES (?,?,?)", (token, _now(), json.dumps({"into": into, "moved": moved})))
    return token, gone


def unmerge(c, token, unpoint):
    r = c.execute("SELECT data FROM food_merges WHERE token=?", (token,)).fetchone()
    if not r:
        raise KeyError(token)
    data = json.loads(r["data"])
    for fid, m in data["moved"].items():
        f = m["food"]
        c.execute("INSERT OR REPLACE INTO foods(id, name, key, category, location, shelf_rule_id, store_id, created_at) "
                  "VALUES (?,?,?,?,?,?,?,?)", (f["id"], f["name"], f["key"], f["category"], f["location"],
                                               f["shelf_rule_id"], f["store_id"], f["created_at"]))
        c.execute("DELETE FROM food_aliases WHERE alias_key=?", (f["key"],))
        for a in m["aliases"]:
            c.execute("INSERT OR REPLACE INTO food_aliases(alias_key, food_id, raw) VALUES (?,?,?)",
                      (a["alias_key"], a["food_id"], a["raw"]))
        unpoint(c, int(fid), data["into"], m["refs"])
    c.execute("DELETE FROM food_merges WHERE token=?", (token,))
    return True


__all__ = ["normalize", "display_name", "init", "get", "lookup", "resolve", "resolve_many", "seed", "rename", "update",
           "aliases", "merge", "unmerge", "alias", "singular"]
