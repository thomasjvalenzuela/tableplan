"""Meals: named groups of recipes that are planned, shopped for and cooked together
(e.g. "Milanese Night" = Chicken Milanese + Spicy Marinara + Cacio e Pepe), plus pairing suggestions.

Stdlib only. Functions take a sqlite3 connection with row_factory=sqlite3.Row and never commit.
"""
import re
import uuid
from datetime import datetime

MAX_ITEMS = 8


def _now():
    return datetime.now().isoformat(timespec="seconds")


def init(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS meals (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, note TEXT DEFAULT '', created_at TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS meal_items (
      meal_id TEXT NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
      recipe_id TEXT NOT NULL, position INTEGER DEFAULT 0, role TEXT DEFAULT '',
      PRIMARY KEY (meal_id, recipe_id));
    CREATE INDEX IF NOT EXISTS meal_items_recipe ON meal_items(recipe_id);
    CREATE TABLE IF NOT EXISTS pairing_hints (          -- "serve with …" names captured at import
      recipe_id TEXT NOT NULL, hint TEXT NOT NULL, PRIMARY KEY (recipe_id, hint));
    CREATE TABLE IF NOT EXISTS pairing_dismissed (
      recipe_id TEXT NOT NULL, other_id TEXT NOT NULL, PRIMARY KEY (recipe_id, other_id));
    """)


def _clean_name(name):
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if not name:
        raise ValueError("Give the meal a name.")
    return name[:80]


def create(c, name, recipe_ids=(), note=""):
    mid = str(uuid.uuid4())
    c.execute("INSERT INTO meals (id, name, note, created_at, updated_at) VALUES (?,?,?,?,?)",
              (mid, _clean_name(name), str(note or "")[:500], _now(), _now()))
    for rid in recipe_ids or []:
        add_recipe(c, mid, rid)
    return mid


def rename(c, meal_id, name):
    return c.execute("UPDATE meals SET name=?, updated_at=? WHERE id=?", (_clean_name(name), _now(), meal_id)).rowcount > 0


def delete(c, meal_id):
    c.execute("DELETE FROM meal_items WHERE meal_id=?", (meal_id,))
    return c.execute("DELETE FROM meals WHERE id=?", (meal_id,)).rowcount > 0


def add_recipe(c, meal_id, recipe_id, role=""):
    if not c.execute("SELECT 1 FROM meals WHERE id=?", (meal_id,)).fetchone():
        raise KeyError("meal not found")
    n = c.execute("SELECT COUNT(*) FROM meal_items WHERE meal_id=?", (meal_id,)).fetchone()[0]
    if c.execute("SELECT 1 FROM meal_items WHERE meal_id=? AND recipe_id=?", (meal_id, recipe_id)).fetchone():
        return False
    if n >= MAX_ITEMS:
        raise ValueError(f"A meal can hold up to {MAX_ITEMS} recipes.")
    c.execute("INSERT INTO meal_items (meal_id, recipe_id, position, role) VALUES (?,?,?,?)",
              (meal_id, str(recipe_id), n, str(role or "")[:40]))
    c.execute("UPDATE meals SET updated_at=? WHERE id=?", (_now(), meal_id))
    return True


def remove_recipe(c, meal_id, recipe_id):
    ok = c.execute("DELETE FROM meal_items WHERE meal_id=? AND recipe_id=?", (meal_id, recipe_id)).rowcount > 0
    if ok and not c.execute("SELECT 1 FROM meal_items WHERE meal_id=?", (meal_id,)).fetchone():
        delete(c, meal_id)   # an empty meal has no reason to exist
    return ok


def get(c, meal_id, recipe_lookup):
    m = c.execute("SELECT * FROM meals WHERE id=?", (meal_id,)).fetchone()
    if not m:
        return None
    items = []
    for r in c.execute("SELECT * FROM meal_items WHERE meal_id=? ORDER BY position", (meal_id,)):
        rec = recipe_lookup(r["recipe_id"])
        if rec:   # recipes deleted since are skipped silently
            items.append({**rec, "role": r["role"]})
    return {"id": m["id"], "name": m["name"], "note": m["note"], "recipes": items}


def list_meals(c, recipe_lookup):
    return [x for x in (get(c, r["id"], recipe_lookup) for r in c.execute("SELECT id FROM meals ORDER BY name COLLATE NOCASE")) if x]


def meals_for_recipe(c, recipe_id):
    return [dict(r) for r in c.execute(
        "SELECT m.id, m.name FROM meals m JOIN meal_items i ON i.meal_id=m.id WHERE i.recipe_id=? ORDER BY m.name", (str(recipe_id),))]


def forget_recipe(c, recipe_id):
    """Call when a recipe is deleted."""
    for r in c.execute("SELECT meal_id FROM meal_items WHERE recipe_id=?", (str(recipe_id),)).fetchall():
        remove_recipe(c, r["meal_id"], str(recipe_id))
    c.execute("DELETE FROM pairing_hints WHERE recipe_id=?", (str(recipe_id),))
    c.execute("DELETE FROM pairing_dismissed WHERE recipe_id=? OR other_id=?", (str(recipe_id), str(recipe_id)))


# ------------------------------------------------------------------ pairing suggestions

SERVE_WITH = re.compile(r"\b(?:serve[ds]?|serving|pair(?:s|ed)?|goes?|great|delicious|enjoy|top(?:ped)?)\b[^.]{0,40}?\b(?:with|over|alongside|on top of|on)\b\s+([^.;\n]{3,120})", re.I)
_STOP = {"the", "a", "an", "my", "our", "your", "some", "and", "or", "of", "with", "fresh", "homemade", "easy", "best", "recipe", "sauce"}


def _words(s):
    return [w for w in re.findall(r"[a-z]+", (s or "").lower()) if w not in _STOP and len(w) > 2]


def save_hints(c, recipe_id, hints):
    for h in hints or []:
        h = re.sub(r"\s+", " ", str(h)).strip()[:120]
        if h:
            c.execute("INSERT OR IGNORE INTO pairing_hints (recipe_id, hint) VALUES (?,?)", (str(recipe_id), h))


def dismiss(c, recipe_id, other_id):
    for a, b in ((recipe_id, other_id), (other_id, recipe_id)):
        c.execute("INSERT OR IGNORE INTO pairing_dismissed (recipe_id, other_id) VALUES (?,?)", (str(a), str(b)))


def _name_hit(name, text):
    """True when the distinctive words of a recipe name all appear in the text (order-free)."""
    ws = _words(name)
    if not ws:
        return False
    t = set(_words(text))
    hits = sum(1 for w in ws if w in t)
    # short names need every word ("chicken milanese"); longer ones most of them ("cacio … pepe" for "Spaghetti Cacio e Pepe")
    return hits == len(ws) if len(ws) <= 2 else hits >= 2 and hits * 3 >= len(ws) * 2


def suggest(c, recipe, library, co_planned=None, limit=4):
    """Recipes that seem meant to go with `recipe`.

    recipe:     Mealie-shaped dict (id, name, description, recipeInstructions, ...).
    library:    list of {id, name} for every recipe.
    co_planned: {other_id: times planned on the same day as this recipe}.
    Returns [{id, name, reason}] best first; recipes already in a meal with it are excluded.
    """
    rid = str(recipe.get("id"))
    together = {r["recipe_id"] for r in c.execute(
        "SELECT i2.recipe_id FROM meal_items i1 JOIN meal_items i2 ON i1.meal_id=i2.meal_id WHERE i1.recipe_id=?", (rid,))}
    dismissed = {r["other_id"] for r in c.execute("SELECT other_id FROM pairing_dismissed WHERE recipe_id=?", (rid,))}
    text = " ".join([recipe.get("description") or ""] + [s.get("text") or "" for s in recipe.get("recipeInstructions") or []]
                    + [s.get("title") or "" for s in recipe.get("recipeInstructions") or []])
    phrases = [m.group(1) for m in SERVE_WITH.finditer(text)]
    phrases += [r["hint"] for r in c.execute("SELECT hint FROM pairing_hints WHERE recipe_id=?", (rid,))]
    # reverse direction: other recipes whose hints name this one
    reverse = {r["recipe_id"] for r in c.execute("SELECT recipe_id, hint FROM pairing_hints WHERE recipe_id<>?", (rid,))
               if _name_hit(recipe.get("name") or "", r["hint"])}
    out = {}
    for other in library:
        oid = str(other.get("id"))
        if oid == rid or oid in together or oid in dismissed:
            continue
        name = other.get("name") or ""
        if any(_name_hit(name, p) for p in phrases):
            out[oid] = (3, "This recipe says to serve it with " + name)
        elif oid in reverse:
            out[oid] = (3, f"{name} says to serve it with this")
        elif (co_planned or {}).get(oid, 0) >= 2:
            out[oid] = (2, f"You've planned these together {(co_planned or {})[oid]} times")
    ranked = sorted(out.items(), key=lambda kv: -kv[1][0])[:limit]
    names = {str(o.get("id")): o.get("name") for o in library}
    return [{"id": oid, "name": names.get(oid), "reason": why} for oid, (_, why) in ranked]
