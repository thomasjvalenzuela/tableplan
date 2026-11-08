"""Native shopping lists stored in TablePlan's own SQLite DB (strangler replacement for Mealie lists).

Every function takes an open sqlite3 connection (row_factory=sqlite3.Row). The caller owns the
transaction (e.g. ``with db() as c:``); nothing here commits. Collaborators the server provides
(ingredient parser, aisle categorizer, Mealie client) are passed in as arguments.

``get_list`` returns Mealie's ShoppingList shape so existing rendering code keeps working.
"""
import json
import uuid
from datetime import datetime, timezone
from fractions import Fraction

SCHEMA = """
CREATE TABLE IF NOT EXISTS shopping_lists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shopping_items (
    id TEXT PRIMARY KEY,
    list_id TEXT NOT NULL REFERENCES shopping_lists(id) ON DELETE CASCADE,
    text TEXT NOT NULL DEFAULT '',
    food TEXT,
    quantity REAL,
    unit TEXT,
    unit_plural TEXT,
    note TEXT NOT NULL DEFAULT '',
    label TEXT,
    checked INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0,
    recipe_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    checked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_shopping_items_list ON shopping_items(list_id, checked, position);
CREATE INDEX IF NOT EXISTS idx_shopping_items_merge ON shopping_items(list_id, food, unit) WHERE checked = 0;
"""

_EDITABLE = {"text", "food", "quantity", "unit", "unit_plural", "note", "label", "position"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _key(s):
    return " ".join((s or "").lower().split())


def _qty(q):
    if not q or q <= 0:
        return ""
    frac = Fraction(q).limit_denominator(16)
    if abs(float(frac) - q) > 0.005:
        return f"{q:.2f}".rstrip("0").rstrip(".")
    whole, rem = divmod(frac.numerator, frac.denominator)
    if not rem:
        return str(whole)
    return f"{whole} {rem}/{frac.denominator}" if whole else f"{rem}/{frac.denominator}"


def _display(r):
    if not r["food"]:
        return r["note"] or r["text"]
    q = r["quantity"] or 0
    unit = (r["unit_plural"] or r["unit"]) if q > 1 else r["unit"]
    out = " ".join(x for x in (_qty(q), unit, r["food"]) if x)
    return f"{out}, {r['note']}" if r["note"] else out


def _item(r):
    return {
        "id": r["id"], "display": _display(r), "note": r["note"], "quantity": r["quantity"],
        "unit": {"name": r["unit"], "pluralName": r["unit_plural"] or None} if r["unit"] else None,
        "food": {"name": r["food"]} if r["food"] else None,
        "label": {"name": r["label"]} if r["label"] else None,
        "checked": bool(r["checked"]), "position": r["position"],
        "recipeIds": json.loads(r["recipe_ids"] or "[]"),
    }


def _require_list(c, list_id):
    if not c.execute("SELECT 1 FROM shopping_lists WHERE id=?", (list_id,)).fetchone():
        raise KeyError(f"shopping list {list_id} not found")


# ------------------------------------------------------------------ lists

def init(c):
    c.executescript(SCHEMA)


def list_lists(c):
    return [dict(r) for r in c.execute("SELECT id, name FROM shopping_lists ORDER BY name COLLATE NOCASE, created_at")]


def create_list(c, name):
    lid = str(uuid.uuid4())
    c.execute("INSERT INTO shopping_lists (id, name, created_at) VALUES (?,?,?)",
              (lid, (name or "").strip() or "Shopping list", _now()))
    return lid


def rename_list(c, list_id, name):
    name = (name or "").strip()
    if not name:
        raise ValueError("List name required")
    return c.execute("UPDATE shopping_lists SET name=? WHERE id=?", (name, list_id)).rowcount > 0


def delete_list(c, list_id):
    c.execute("DELETE FROM shopping_items WHERE list_id=?", (list_id,))
    return c.execute("DELETE FROM shopping_lists WHERE id=?", (list_id,)).rowcount > 0


def get_list(c, list_id):
    row = c.execute("SELECT id, name FROM shopping_lists WHERE id=?", (list_id,)).fetchone()
    if not row:
        return None
    items = c.execute("SELECT * FROM shopping_items WHERE list_id=? ORDER BY checked, position, created_at", (list_id,))
    return {"id": row["id"], "name": row["name"], "listItems": [_item(r) for r in items]}


# ------------------------------------------------------------------ items

def _add_one(c, list_id, text, parse, categorize, scale=1.0, recipe_id=None):
    """Insert one line, merging into an unchecked item with the same food+unit. Returns the item id."""
    text = (text or "").strip()
    if not text:
        return None
    p = parse(text) if parse else None
    food = (p.get("food") or "").strip() if p else ""
    if food:
        unit, plural, note = p.get("unit") or "", p.get("unit_plural") or "", (p.get("note") or "").strip()
        qty = float(p.get("quantity") or 0) * scale or None
        dup = c.execute("SELECT id, quantity, note, recipe_ids FROM shopping_items WHERE list_id=? AND checked=0 "
                        "AND food IS NOT NULL AND lower(food)=? AND coalesce(unit,'')=?",
                        (list_id, food.lower(), unit)).fetchone()
    else:
        unit = plural = ""
        food, note, qty = None, text, 1.0
        dup = c.execute("SELECT id, quantity, note, recipe_ids FROM shopping_items WHERE list_id=? AND checked=0 "
                        "AND food IS NULL AND lower(note)=?", (list_id, text.lower())).fetchone()
    if dup:
        rids = json.loads(dup["recipe_ids"] or "[]")
        if recipe_id and recipe_id not in rids:
            rids.append(recipe_id)
        new_qty = ((dup["quantity"] or 0) + (qty or 0)) or None if food else dup["quantity"]
        new_note = dup["note"] if not note or _key(note) in _key(dup["note"]).split("; ") else \
            "; ".join(x for x in (dup["note"], note) if x)
        c.execute("UPDATE shopping_items SET quantity=?, note=?, recipe_ids=? WHERE id=?",
                  (new_qty, new_note, json.dumps(rids), dup["id"]))
        return dup["id"]
    pos = c.execute("SELECT coalesce(max(position), -1) + 1 FROM shopping_items WHERE list_id=?", (list_id,)).fetchone()[0]
    iid = str(uuid.uuid4())
    c.execute("INSERT INTO shopping_items (id, list_id, text, food, quantity, unit, unit_plural, note, label, checked, "
              "position, recipe_ids, created_at) VALUES (?,?,?,?,?,?,?,?,?,0,?,?,?)",
              (iid, list_id, text, food, qty, unit or None, plural or None, note,
               (categorize(food or text) if categorize else None) or None, pos,
               json.dumps([recipe_id] if recipe_id else []), _now()))
    return iid


def add_items(c, list_id, texts, parse=None, categorize=None):
    """Add free-text lines. parse(text) -> {quantity, unit, unit_plural, food, note} | None;
    categorize(food_or_text) -> aisle label | None. Returns the affected item ids (merged items included)."""
    _require_list(c, list_id)
    ids = [_add_one(c, list_id, t, parse, categorize) for t in texts or []]
    return [i for i in ids if i]


def add_recipe_ingredients(c, list_id, recipe_id, lines, scale, parse, categorize):
    """Add a recipe's ingredient lines with parsed quantities multiplied by `scale`."""
    _require_list(c, list_id)
    scale = float(scale or 1)
    ids = [_add_one(c, list_id, t, parse, categorize, scale, str(recipe_id) if recipe_id else None) for t in lines or []]
    return [i for i in ids if i]


def set_checked(c, list_id, item_id, checked):
    return c.execute("UPDATE shopping_items SET checked=?, checked_at=? WHERE id=? AND list_id=?",
                     (int(bool(checked)), _now() if checked else None, item_id, list_id)).rowcount > 0


def update_item(c, list_id, item_id, **fields):
    """Update editable fields (text, food, quantity, unit, unit_plural, note, label, position, checked)."""
    bad = set(fields) - _EDITABLE - {"checked"}
    if bad:
        raise ValueError(f"Unknown item field(s): {', '.join(sorted(bad))}")
    if "checked" in fields and not set_checked(c, list_id, item_id, fields.pop("checked")):
        return False
    if not fields:
        return bool(c.execute("SELECT 1 FROM shopping_items WHERE id=? AND list_id=?", (item_id, list_id)).fetchone())
    if "quantity" in fields and fields["quantity"] is not None:
        fields["quantity"] = float(fields["quantity"])
    cols = sorted(fields)
    return c.execute(f"UPDATE shopping_items SET {', '.join(f'{k}=?' for k in cols)} WHERE id=? AND list_id=?",
                     [fields[k] for k in cols] + [item_id, list_id]).rowcount > 0


def delete_item(c, list_id, item_id):
    return c.execute("DELETE FROM shopping_items WHERE id=? AND list_id=?", (item_id, list_id)).rowcount > 0


def clear_checked(c, list_id):
    return c.execute("DELETE FROM shopping_items WHERE list_id=? AND checked=1", (list_id,)).rowcount


# ------------------------------------------------------------------ migration

def migrate_from_mealie(c, mealie):
    """Copy every Mealie shopping list and item, keeping Mealie ids. Rows that already exist are left
    untouched, so re-running is safe and never clobbers native edits. Returns counts."""
    out = {"lists": 0, "items": 0, "lists_skipped": 0, "items_skipped": 0}
    summaries = (mealie("GET", "/api/households/shopping/lists?perPage=-1") or {}).get("items") or []
    for s in summaries:
        sl = mealie("GET", f"/api/households/shopping/lists/{s['id']}") or {}
        cur = c.execute("INSERT OR IGNORE INTO shopping_lists (id, name, created_at) VALUES (?,?,?)",
                        (s["id"], sl.get("name") or s.get("name") or "Shopping list",
                         sl.get("createdAt") or s.get("createdAt") or _now()))
        out["lists" if cur.rowcount else "lists_skipped"] += 1
        for i, it in enumerate(sl.get("listItems") or []):
            unit, food = it.get("unit") or {}, it.get("food") or {}
            note = (it.get("note") or "").strip()
            text = (it.get("display") or "").strip() or note
            rids = [r["recipeId"] for r in it.get("recipeReferences") or [] if r.get("recipeId")]
            checked = bool(it.get("checked"))
            cur = c.execute(
                "INSERT OR IGNORE INTO shopping_items (id, list_id, text, food, quantity, unit, unit_plural, note, "
                "label, checked, position, recipe_ids, created_at, checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (it["id"], s["id"], text, food.get("name") or None,
                 float(it["quantity"]) if it.get("quantity") is not None else None,
                 unit.get("name") or None, unit.get("pluralName") or None,
                 note if food.get("name") else (note or text),
                 (it.get("label") or {}).get("name") or None, int(checked),
                 it.get("position") if it.get("position") is not None else i, json.dumps(rids),
                 it.get("createdAt") or _now(),
                 (it.get("updatedAt") or it.get("updateAt") or _now()) if checked else None))
            out["items" if cur.rowcount else "items_skipped"] += 1
    return out


__all__ = ["init", "list_lists", "create_list", "rename_list", "delete_list", "get_list", "add_items",
           "add_recipe_ingredients", "set_checked", "update_item", "delete_item", "clear_checked",
           "migrate_from_mealie"]
