"""Native meal-plan storage in TablePlan's SQLite (replaces Mealie meal plans).

Stdlib only; never imports server.py. Callers pass an open sqlite3 connection
with row_factory=sqlite3.Row and commit/close it themselves.
"""
import sqlite3
import urllib.parse
from datetime import date, datetime, timedelta, timezone

ENTRY_TYPES = ("breakfast", "lunch", "dinner", "side", "snack", "dessert", "drink")
ENTRY_ORDER = {t: i for i, t in enumerate(ENTRY_TYPES)}
_UPDATABLE = ("date", "entry_type", "recipe_id", "title", "text", "scale")

_ORDER_SQL = "CASE entry_type " + " ".join(
    f"WHEN '{t}' THEN {i}" for t, i in ENTRY_ORDER.items()) + f" ELSE {len(ENTRY_TYPES)} END"


def init(c):
    c.executescript(f"""
        CREATE TABLE IF NOT EXISTS meal_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            entry_type TEXT NOT NULL CHECK (entry_type IN ({",".join(f"'{t}'" for t in ENTRY_TYPES)})),
            recipe_id TEXT,
            title TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '',
            scale REAL NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            source_id TEXT UNIQUE
        );
        CREATE INDEX IF NOT EXISTS idx_meal_plans_date ON meal_plans(date);
    """)


def _date(v):
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"invalid ISO date: {v!r}") from None


def _entry_type(v):
    t = str(v or "").strip().lower()
    if t not in ENTRY_ORDER:
        raise ValueError(f"invalid entry_type: {v!r} (allowed: {', '.join(ENTRY_TYPES)})")
    return t


def _scale(v):
    try:
        s = float(1 if v is None else v)
    except (TypeError, ValueError):
        raise ValueError(f"invalid scale: {v!r}") from None
    if not s > 0:
        raise ValueError(f"scale must be positive: {v!r}")
    return s


def _clean(fields):
    out = {}
    for k, v in fields.items():
        if k == "date":
            out[k] = _date(v)
        elif k == "entry_type":
            out[k] = _entry_type(v)
        elif k == "recipe_id":
            out[k] = str(v) if v else None
        elif k in ("title", "text"):
            out[k] = (v or "").strip()
        elif k == "scale":
            out[k] = _scale(v)
        else:
            raise ValueError(f"unknown field: {k}")
    return out


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _recipe(recipe_id, recipe_lookup):
    if not recipe_id:
        return None
    try:
        r = recipe_lookup(recipe_id)
    except Exception:
        r = None
    if not r:
        return None
    return {"id": r.get("id") or recipe_id, "name": r.get("name"), "slug": r.get("slug"),
            "has_image": bool(r.get("has_image")), "image_v": r.get("image_v")}


def get_plans(c, start_iso, end_iso, recipe_lookup):
    rows = c.execute(
        f"SELECT * FROM meal_plans WHERE date BETWEEN ? AND ? ORDER BY date, {_ORDER_SQL}, id",
        (_date(start_iso), _date(end_iso))).fetchall()
    cache = {}
    out = []
    for r in rows:
        rid = r["recipe_id"]
        if rid not in cache:
            cache[rid] = _recipe(rid, recipe_lookup)
        out.append({"id": r["id"], "date": r["date"], "entry_type": r["entry_type"],
                    "title": r["title"], "text": r["text"], "scale": r["scale"],
                    "recipeId": rid, "recipe": cache[rid]})
    return out


def add_entry(c, date, entry_type, recipe_id=None, title="", text="", scale=1, _source_id=None):
    f = _clean({"date": date, "entry_type": entry_type, "recipe_id": recipe_id,
                "title": title, "text": text, "scale": scale})
    if not (f["recipe_id"] or f["title"] or f["text"]):
        raise ValueError("entry needs a recipe_id, title or text")
    cur = c.execute(
        "INSERT INTO meal_plans (date, entry_type, recipe_id, title, text, scale, created_at, source_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (f["date"], f["entry_type"], f["recipe_id"], f["title"], f["text"], f["scale"], _now(), _source_id))
    return cur.lastrowid


def delete_entry(c, id):
    return c.execute("DELETE FROM meal_plans WHERE id = ?", (id,)).rowcount > 0


def update_entry(c, id, **fields):
    f = _clean(fields)
    if not f:
        return c.execute("SELECT 1 FROM meal_plans WHERE id = ?", (id,)).fetchone() is not None
    cols = ", ".join(f"{k} = ?" for k in f)
    return c.execute(f"UPDATE meal_plans SET {cols} WHERE id = ?", (*f.values(), id)).rowcount > 0


def migrate_from_mealie(c, mealie, days_back=365, days_forward=365, today=None):
    """Copy Mealie meal plans in the window into SQLite. Safe to re-run."""
    t = today or date.today()
    q = urllib.parse.urlencode({"start_date": (t - timedelta(days=days_back)).isoformat(),
                                "end_date": (t + timedelta(days=days_forward)).isoformat(),
                                "perPage": -1})
    data = mealie("GET", f"/api/households/mealplans?{q}") or {}
    counts = {"fetched": 0, "imported": 0, "skipped": 0, "errors": 0}
    for p in data.get("items") or []:
        counts["fetched"] += 1
        sid = p.get("id")
        if sid is None:
            counts["errors"] += 1
            continue
        sid = str(sid)
        if c.execute("SELECT 1 FROM meal_plans WHERE source_id = ?", (sid,)).fetchone():
            counts["skipped"] += 1
            continue
        rid = p.get("recipeId") or (p.get("recipe") or {}).get("id")
        try:
            add_entry(c, p.get("date"), p.get("entryType"), rid, p.get("title") or "",
                      p.get("text") or "", p.get("recipeScale") or 1, _source_id=sid)
        except (ValueError, sqlite3.IntegrityError):
            counts["errors"] += 1
            continue
        counts["imported"] += 1
    c.commit()
    return counts
