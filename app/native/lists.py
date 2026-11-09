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
CREATE TABLE IF NOT EXISTS stores (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS food_store (
    food_key TEXT PRIMARY KEY,
    store_id TEXT NOT NULL REFERENCES stores(id) ON DELETE CASCADE
);
"""

MAX_STORES = 12
MAX_STORE_NAME = 40

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
        "storeId": r["store_id"], "checkedAt": r["checked_at"],
        "checkedHow": (r["checked_how"] if "checked_how" in r.keys() else None) if r["checked"] else None,
    }


def _require_list(c, list_id):
    if not c.execute("SELECT 1 FROM shopping_lists WHERE id=?", (list_id,)).fetchone():
        raise KeyError(f"shopping list {list_id} not found")


# ------------------------------------------------------------------ lists

def init(c):
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(shopping_items)")}
    if "store_id" not in cols:
        c.execute("ALTER TABLE shopping_items ADD COLUMN store_id TEXT")
    if "contrib" not in cols:   # {recipe_id: quantity in the item's unit} each recipe added
        c.execute("ALTER TABLE shopping_items ADD COLUMN contrib TEXT NOT NULL DEFAULT '{}'")
    if "checked_how" not in cols:   # 'have' = ticked as "I already have this" (no purchase); NULL = bought
        c.execute("ALTER TABLE shopping_items ADD COLUMN checked_how TEXT")
    if "manual" not in cols:    # 1 = typed in by someone (quick add), so recipe removals never delete it
        c.execute("ALTER TABLE shopping_items ADD COLUMN manual INTEGER NOT NULL DEFAULT 0")


def single_list(c, name="Groceries"):
    """The one ongoing list: created if missing; if several exist, every item moves into the oldest one."""
    rows = c.execute("SELECT id FROM shopping_lists ORDER BY created_at, rowid").fetchall()
    if not rows:
        return create_list(c, name)
    keep = rows[0]["id"]
    for r in rows[1:]:
        base = c.execute("SELECT coalesce(max(position), -1) + 1 FROM shopping_items WHERE list_id=?", (keep,)).fetchone()[0]
        c.execute("UPDATE shopping_items SET list_id=?, position=position+? WHERE list_id=?", (keep, base, r["id"]))
        c.execute("DELETE FROM shopping_lists WHERE id=?", (r["id"],))
    return keep


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

def _contrib(r):
    try:
        d = json.loads(r["contrib"] or "{}")
    except (ValueError, TypeError, IndexError, KeyError):
        d = {}
    return d if isinstance(d, dict) else {}


def _add_one(c, list_id, text, parse, categorize, scale=1.0, recipe_id=None, store_key=None, store_id=None, manual=False):
    """Insert one line, merging into an unchecked item with the same food+unit. Returns the item id.

    New items get ``store_id`` if given, else the store remembered for ``store_key(food or text)``.
    A recipe's share of the quantity is recorded in ``contrib`` so removing the recipe later subtracts exactly it;
    ``manual`` marks lines someone typed in."""
    text = (text or "").strip()
    if not text:
        return None
    p = parse(text) if parse else None
    food = (p.get("food") or "").strip() if p else ""
    if food:
        unit, plural, note = p.get("unit") or "", p.get("unit_plural") or "", (p.get("note") or "").strip()
        qty = float(p.get("quantity") or 0) * scale or None
        dup = c.execute("SELECT id, quantity, note, recipe_ids, contrib, manual FROM shopping_items WHERE list_id=? "
                        "AND checked=0 AND food IS NOT NULL AND lower(food)=? AND coalesce(unit,'')=?",
                        (list_id, food.lower(), unit)).fetchone()
    else:
        unit = plural = ""
        food, note, qty = None, text, 1.0
        dup = c.execute("SELECT id, quantity, note, recipe_ids, contrib, manual FROM shopping_items WHERE list_id=? "
                        "AND checked=0 AND food IS NULL AND lower(note)=?", (list_id, text.lower())).fetchone()
    share = (qty or 0) if food else 0
    if dup:
        rids = json.loads(dup["recipe_ids"] or "[]")
        contrib = _contrib(dup)
        if recipe_id:
            if recipe_id not in rids:
                rids.append(recipe_id)
            contrib[recipe_id] = (contrib.get(recipe_id) or 0) + share
        new_qty = ((dup["quantity"] or 0) + (qty or 0)) or None if food else dup["quantity"]
        new_note = dup["note"] if not note or _key(note) in _key(dup["note"]).split("; ") else \
            "; ".join(x for x in (dup["note"], note) if x)
        c.execute("UPDATE shopping_items SET quantity=?, note=?, recipe_ids=?, contrib=?, manual=? WHERE id=?",
                  (new_qty, new_note, json.dumps(rids), json.dumps(contrib), int(bool(dup["manual"]) or manual), dup["id"]))
        return dup["id"]
    pos = c.execute("SELECT coalesce(max(position), -1) + 1 FROM shopping_items WHERE list_id=?", (list_id,)).fetchone()[0]
    if store_id is None and store_key:
        store_id = store_for(c, store_key(food or text))
    iid = str(uuid.uuid4())
    c.execute("INSERT INTO shopping_items (id, list_id, text, food, quantity, unit, unit_plural, note, label, checked, "
              "position, recipe_ids, created_at, store_id, contrib, manual) VALUES (?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?)",
              (iid, list_id, text, food, qty, unit or None, plural or None, note,
               (categorize(food or text) if categorize else None) or None, pos,
               json.dumps([recipe_id] if recipe_id else []), _now(), store_id,
               json.dumps({recipe_id: share} if recipe_id else {}), int(bool(manual))))
    return iid


def add_items(c, list_id, texts, parse=None, categorize=None, store_key=None, store_id=None):
    """Add free-text lines. parse(text) -> {quantity, unit, unit_plural, food, note} | None;
    categorize(food_or_text) -> aisle label | None. Returns the affected item ids (merged items included)."""
    _require_list(c, list_id)
    if store_id is not None and not get_store(c, store_id):
        raise KeyError(f"store {store_id} not found")
    ids = [_add_one(c, list_id, t, parse, categorize, store_key=store_key, store_id=store_id, manual=True)
           for t in texts or []]
    return [i for i in ids if i]


def add_recipe_ingredients(c, list_id, recipe_id, lines, scale, parse, categorize, store_key=None):
    """Add a recipe's ingredient lines with parsed quantities multiplied by `scale`."""
    _require_list(c, list_id)
    scale = float(scale or 1)
    ids = [_add_one(c, list_id, t, parse, categorize, scale, str(recipe_id) if recipe_id else None, store_key)
           for t in lines or []]
    return [i for i in ids if i]


def get_item(c, item_id):
    r = c.execute("SELECT * FROM shopping_items WHERE id=?", (item_id,)).fetchone()
    return dict(_item(r), list_id=r["list_id"]) if r else None


def _linked(c, list_id, recipe_id):
    """Unchecked rows on the list linked to recipe_id (recipe_ids is a JSON array of ids)."""
    return [r for r in c.execute("SELECT * FROM shopping_items WHERE list_id=? AND checked=0 AND recipe_ids LIKE ? "
                                 "ORDER BY position, created_at", (list_id, f'%"{recipe_id}"%'))
            if str(recipe_id) in json.loads(r["recipe_ids"] or "[]")]


def unchecked_for_recipe(c, list_id, recipe_id):
    """Unchecked items still needed for a recipe, as [{id, text}]."""
    return [{"id": r["id"], "text": _display(r)} for r in _linked(c, list_id, str(recipe_id))]


def missing_counts(c, list_id):
    """{recipe_id: number of unchecked items linked to it}."""
    out = {}
    for r in c.execute("SELECT recipe_ids FROM shopping_items WHERE list_id=? AND checked=0 AND recipe_ids != '[]'",
                       (list_id,)):
        for rid in set(json.loads(r["recipe_ids"] or "[]")):
            out[rid] = out.get(rid, 0) + 1
    return out


def remove_recipe_items(c, list_id, recipe_id):
    """Take a recipe back off the list: subtract exactly the quantity it added to each unchecked item.

    An item is deleted when nothing is left of it, no other recipe needs it and nobody typed it in; unparsed
    lines (no quantity) linked only to this recipe are deleted too. Items from before contributions were tracked
    fall back to unlinking. Checked (bought) items are never touched. Returns the number of items deleted."""
    removed = 0
    rid = str(recipe_id)
    for r in _linked(c, list_id, rid):
        rids = [x for x in json.loads(r["recipe_ids"] or "[]") if x != rid]
        contrib = _contrib(r)
        tracked = rid in contrib
        share = float(contrib.pop(rid, 0) or 0)
        qty = r["quantity"]
        if r["food"] and tracked and qty is not None:
            qty = qty - share
            if qty <= 1e-6:
                qty = None
        gone = not rids and not r["manual"] and (not r["food"] or not tracked or qty is None)
        if gone:
            c.execute("DELETE FROM shopping_items WHERE id=?", (r["id"],))
            removed += 1
            continue
        if r["food"] and tracked and qty is None:
            # nothing left of the share, but another recipe or a typed line still wants it: keep their amounts
            qty = sum(float(v or 0) for v in contrib.values()) or None
        c.execute("UPDATE shopping_items SET recipe_ids=?, contrib=?, quantity=? WHERE id=?",
                  (json.dumps(rids), json.dumps(contrib), qty if (r["food"] and tracked) else r["quantity"], r["id"]))
    return removed


def set_item_text(c, item_id, text, parse=None, categorize=None):
    """Rewrite an item from new free text (re-parsed and re-categorized); keeps its store and recipe links."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Item text is required.")
    p = parse(text) if parse else None
    food = (p.get("food") or "").strip() if p else ""
    if food:
        vals = (text, food, float(p.get("quantity") or 0) or None, p.get("unit") or None, p.get("unit_plural") or None,
                (p.get("note") or "").strip())
    else:
        vals = (text, None, 1.0, None, None, text)
    label = (categorize(food or text) if categorize else None) or None
    return c.execute("UPDATE shopping_items SET text=?, food=?, quantity=?, unit=?, unit_plural=?, note=?, label=? "
                     "WHERE id=?", (*vals, label, item_id)).rowcount > 0


def mark_have(c, item_ids):
    """"I already have this": check items off without the bought flow. Returns how many changed."""
    n = 0
    for iid in item_ids:
        n += c.execute("UPDATE shopping_items SET checked=1, checked_at=?, checked_how='have' WHERE id=? AND checked=0",
                       (_now(), iid)).rowcount
    return n


def recently_checked(c, list_id, limit=20, before=None):
    """Checked items, newest first; with ``before`` (ISO time) only those checked earlier than it."""
    if before:
        rows = c.execute("SELECT * FROM shopping_items WHERE list_id=? AND checked=1 AND coalesce(checked_at, created_at) < ? "
                         "ORDER BY coalesce(checked_at, created_at) DESC LIMIT ?", (list_id, before, int(limit)))
    else:
        rows = c.execute("SELECT * FROM shopping_items WHERE list_id=? AND checked=1 "
                         "ORDER BY coalesce(checked_at, created_at) DESC LIMIT ?", (list_id, int(limit)))
    return [_item(r) for r in rows]


def checked_since(c, list_id, since):
    """Items checked at or after ``since`` (ISO time): they stay visible in place for a while."""
    rows = c.execute("SELECT * FROM shopping_items WHERE list_id=? AND checked=1 AND checked_at >= ? "
                     "ORDER BY position, created_at", (list_id, since))
    return [_item(r) for r in rows]


# ------------------------------------------------------------------ stores

def _store_name(name):
    if not isinstance(name, str):
        raise ValueError("Store names must be text.")
    name = " ".join(name.split())
    if not 1 <= len(name) <= MAX_STORE_NAME:
        raise ValueError(f"Store names are 1-{MAX_STORE_NAME} characters.")
    return name


def list_stores(c):
    return [dict(r) for r in c.execute("SELECT id, name, position FROM stores ORDER BY position, name COLLATE NOCASE")]


def get_store(c, store_id):
    r = c.execute("SELECT id, name, position FROM stores WHERE id=?", (str(store_id),)).fetchone()
    return dict(r) if r else None


def seed_stores(c, names):
    """Insert default stores only when there are none."""
    if c.execute("SELECT 1 FROM stores").fetchone():
        return False
    for i, n in enumerate(names):
        c.execute("INSERT INTO stores (id, name, position) VALUES (?,?,?)", (str(uuid.uuid4()), _store_name(n), i))
    return True


def replace_stores(c, stores):
    """Replace the store list with [{id?, name}] in order. Known ids are kept; stores left out are removed
    (their items go back to "any store" and their remembered foods are forgotten)."""
    if not isinstance(stores, list) or len(stores) > MAX_STORES:
        raise ValueError(f"Send a list of at most {MAX_STORES} stores.")
    existing = {r["id"] for r in c.execute("SELECT id FROM stores")}
    clean, seen_ids, seen_names = [], set(), set()
    for s in stores:
        if not isinstance(s, dict):
            raise ValueError("Each store needs a name.")
        name = _store_name(s.get("name"))
        if name.lower() in seen_names:
            raise ValueError(f"{name} is listed twice.")
        seen_names.add(name.lower())
        sid = s.get("id")
        sid = str(sid) if sid is not None and str(sid) in existing and str(sid) not in seen_ids else None
        sid = sid or str(uuid.uuid4())
        seen_ids.add(sid)
        clean.append((sid, name))
    gone = existing - seen_ids
    for sid in gone:
        c.execute("UPDATE shopping_items SET store_id=NULL WHERE store_id=?", (sid,))
        c.execute("DELETE FROM food_store WHERE store_id=?", (sid,))
        c.execute("DELETE FROM stores WHERE id=?", (sid,))
    for i, (sid, name) in enumerate(clean):
        c.execute("INSERT INTO stores (id, name, position) VALUES (?,?,?) "
                  "ON CONFLICT(id) DO UPDATE SET name=excluded.name, position=excluded.position", (sid, name, i))
    return list_stores(c)


def store_for(c, key):
    if not key:
        return None
    r = c.execute("SELECT store_id FROM food_store WHERE food_key=?", (key,)).fetchone()
    return r["store_id"] if r else None


def set_item_store(c, item_id, store_id, key=None):
    """Put an item in a store (None = any store) and remember the choice for that food."""
    if store_id is not None and not get_store(c, store_id):
        raise KeyError(f"store {store_id} not found")
    if not c.execute("UPDATE shopping_items SET store_id=? WHERE id=?", (store_id, item_id)).rowcount:
        return False
    if key:
        if store_id is None:
            c.execute("DELETE FROM food_store WHERE food_key=?", (key,))
        else:
            c.execute("INSERT INTO food_store (food_key, store_id) VALUES (?,?) "
                      "ON CONFLICT(food_key) DO UPDATE SET store_id=excluded.store_id", (key, store_id))
    return True


def set_checked(c, list_id, item_id, checked):
    return c.execute("UPDATE shopping_items SET checked=?, checked_at=?, checked_how=NULL WHERE id=? AND list_id=?",
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


__all__ = ["init", "single_list", "get_item", "unchecked_for_recipe", "missing_counts", "remove_recipe_items",
           "mark_have", "recently_checked", "checked_since", "list_stores", "get_store", "seed_stores", "replace_stores", "store_for",
           "set_item_store", "set_item_text", "list_lists", "create_list", "rename_list", "delete_list", "get_list", "add_items",
           "add_recipe_ingredients", "set_checked", "update_item", "delete_item", "clear_checked",
           "migrate_from_mealie"]
