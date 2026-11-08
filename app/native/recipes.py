"""Native recipe storage: SQLite rows holding Mealie-shaped recipe JSON, images on disk.

Each recipe is stored as the same dict Mealie's ``GET /api/recipes/{slug}`` returns, so
code written against Mealie keeps working when it reads from here instead. Functions take
an open ``sqlite3`` connection (row_factory=sqlite3.Row); callers own the transaction
(``with db() as c: ...``) except ``migrate_from_mealie``, which commits its batch.
Stdlib only; never imports server.py.
"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone

MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_EXTS = ("jpg", "png", "webp", "gif")
_EXT_ALIASES = {"jpeg": "jpg", "jpe": "jpg"}
_DETAIL_ONLY = ("recipeIngredient", "recipeInstructions")

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
  id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  data TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_recipes_name ON recipes(name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS favorites (
  recipe_id TEXT PRIMARY KEY REFERENCES recipes(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS aliases (
  slug TEXT PRIMARY KEY,
  recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE
);
"""


def init(c):
    c.executescript(SCHEMA)


# ------------------------------------------------------------------ helpers

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(name):
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:80].rstrip("-") or "recipe"


def _unique_slug(c, name, own_id=None):
    base = slugify(name)
    slug, n = base, 1
    while True:
        row = c.execute("SELECT id FROM recipes WHERE slug=?", (slug,)).fetchone()
        if row is None or row["id"] == own_id:
            return slug
        n += 1
        slug = f"{base}-{n}"


def _default(rid, slug, name, now):
    return {
        "id": rid, "slug": slug, "name": name, "description": "", "image": None,
        "recipeServings": None, "recipeYield": "",
        "totalTimeSeconds": None, "prepTimeSeconds": None, "performTimeSeconds": None,
        "totalTime": None, "prepTime": None, "performTime": None,
        "rating": None, "orgURL": None, "tags": [], "recipeCategory": [],
        "recipeIngredient": [], "recipeInstructions": [],
        "dateAdded": now[:10], "createdAt": now, "dateUpdated": now, "lastMade": None,
    }


def _normalize(rec):
    """Fill ids Mealie consumers rely on (ingredient referenceId, instruction id)."""
    for ing in rec.get("recipeIngredient") or []:
        if isinstance(ing, dict) and not ing.get("referenceId"):
            ing["referenceId"] = str(uuid.uuid4())
    for step in rec.get("recipeInstructions") or []:
        if isinstance(step, dict):
            step.setdefault("id", str(uuid.uuid4()))
            step.setdefault("ingredientReferences", [])
    return rec


def _row(c, slug_or_id):
    q = "SELECT * FROM recipes WHERE slug=? OR id=?"
    row = c.execute(q, (slug_or_id, slug_or_id)).fetchone()
    if row is None:
        row = c.execute("SELECT r.* FROM aliases a JOIN recipes r ON r.id=a.recipe_id WHERE a.slug=?",
                        (slug_or_id,)).fetchone()
    return row


def _write(c, rec, created_at):
    c.execute("DELETE FROM aliases WHERE slug=?", (rec["slug"],))
    c.execute("INSERT INTO recipes(id, slug, name, data, updated_at, created_at) VALUES (?,?,?,?,?,?) "
              "ON CONFLICT(id) DO UPDATE SET slug=excluded.slug, name=excluded.name, "
              "data=excluded.data, updated_at=excluded.updated_at",
              (rec["id"], rec["slug"], rec["name"], json.dumps(rec, separators=(",", ":")),
               rec["dateUpdated"], created_at))


# ------------------------------------------------------------------ CRUD

def list_summaries(c):
    out = []
    for row in c.execute("SELECT data FROM recipes ORDER BY name COLLATE NOCASE, slug"):
        rec = json.loads(row["data"])
        for k in _DETAIL_ONLY:
            rec.pop(k, None)
        out.append(rec)
    return out


def get(c, slug_or_id):
    row = _row(c, slug_or_id)
    return json.loads(row["data"]) if row else None


def create(c, name, data=None):
    name = (str(name or "").strip() or (data or {}).get("name") or "").strip()
    if not name:
        raise ValueError("Recipe name is required.")
    now = _now()
    rid = str(uuid.uuid4())
    rec = _default(rid, _unique_slug(c, name), name, now)
    for k, v in (data or {}).items():
        if k not in ("id", "slug", "name", "dateAdded", "createdAt", "dateUpdated"):
            rec[k] = v
    _write(c, _normalize(rec), now)
    return rec["slug"]


def update(c, slug, data):
    """Replace a recipe's data wholesale. Returns the (possibly new) slug."""
    row = _row(c, slug)
    if row is None:
        raise KeyError(slug)
    old = json.loads(row["data"])
    name = str(data.get("name") or old["name"]).strip()
    rec = _default(old["id"], old["slug"], name, old.get("createdAt") or row["created_at"])
    rec.update({k: v for k, v in data.items() if k not in ("id", "slug")})
    rec.update(id=old["id"], name=name, dateAdded=old.get("dateAdded", rec["dateAdded"]),
               createdAt=old.get("createdAt", row["created_at"]), dateUpdated=_now())
    if "image" not in data:
        rec["image"] = old.get("image")
    if name != old["name"]:
        rec["slug"] = _unique_slug(c, name, own_id=old["id"])
        if rec["slug"] != old["slug"]:
            c.execute("INSERT OR REPLACE INTO aliases(slug, recipe_id) VALUES (?,?)", (old["slug"], old["id"]))
    _write(c, _normalize(rec), row["created_at"])
    return rec["slug"]


def delete(c, slug, images_dir=None):
    row = _row(c, slug)
    if row is None:
        return False
    rid = row["id"]
    for table, col in (("favorites", "recipe_id"), ("aliases", "recipe_id"), ("recipes", "id")):
        c.execute(f"DELETE FROM {table} WHERE {col}=?", (rid,))
    if images_dir:
        shutil.rmtree(_image_dir(images_dir, rid), ignore_errors=True)
    return True


def set_favorite(c, recipe_id, on):
    if on:
        c.execute("INSERT OR IGNORE INTO favorites(recipe_id) SELECT id FROM recipes WHERE id=?", (recipe_id,))
    else:
        c.execute("DELETE FROM favorites WHERE recipe_id=?", (recipe_id,))


def favorite_ids(c):
    return [r["recipe_id"] for r in c.execute("SELECT recipe_id FROM favorites ORDER BY recipe_id")]


# ------------------------------------------------------------------ images

def _image_dir(images_dir, recipe_id):
    rid = str(recipe_id)
    if not re.fullmatch(r"[A-Za-z0-9-]+", rid):
        raise ValueError("Invalid recipe id.")
    return os.path.join(images_dir, "recipes", rid)


def sniff_image(blob):
    """Return the canonical extension for image bytes, or None."""
    if blob[:3] == b"\xff\xd8\xff":
        return "jpg"
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp"
    if blob[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def save_image(images_dir, recipe_id, blob, ext, c=None):
    """Write {images_dir}/recipes/{id}/original.{ext}; returns the new image version token.

    If ``c`` is given, the recipe's ``image`` field is set to the token.
    """
    if not blob:
        raise ValueError("Image is empty.")
    if len(blob) > MAX_IMAGE_BYTES:
        raise ValueError("Image is too large (8 MB max).")
    ext = str(ext or "").lower().lstrip(".")
    ext = _EXT_ALIASES.get(ext, ext)
    kind = sniff_image(blob)
    if kind is None:
        raise ValueError("Unsupported image type (use JPEG, PNG, WebP or GIF).")
    if ext and ext != kind:
        raise ValueError(f"Image content is {kind.upper()}, not {ext.upper()}.")
    d = _image_dir(images_dir, recipe_id)
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, f"original.{kind}")
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, dest)
    for e in IMAGE_EXTS:
        if e != kind:
            try:
                os.remove(os.path.join(d, f"original.{e}"))
            except FileNotFoundError:
                pass
    token = hashlib.sha256(blob).hexdigest()[:8]
    if c is not None:
        row = c.execute("SELECT data, created_at FROM recipes WHERE id=?", (str(recipe_id),)).fetchone()
        if row is not None:
            rec = json.loads(row["data"])
            rec["image"], rec["dateUpdated"] = token, _now()
            _write(c, rec, row["created_at"])
    return token


def image_path(images_dir, recipe_id):
    d = _image_dir(images_dir, recipe_id)
    for e in IMAGE_EXTS:
        p = os.path.join(d, f"original.{e}")
        if os.path.isfile(p):
            return p
    return None


# ------------------------------------------------------------------ Mealie migration

def migrate_from_mealie(c, mealie, mealie_bytes, images_dir):
    """Copy recipes, images and favorites from Mealie. Safe to re-run; returns counts.

    ``mealie(method, path)`` returns decoded JSON; ``mealie_bytes(path)`` returns bytes or None.
    Recipes keep their Mealie id and slug, so existing references stay valid.
    """
    counts = {"recipes": 0, "created": 0, "updated": 0, "images": 0, "favorites": 0, "errors": []}
    listing = mealie("GET", "/api/recipes?page=1&perPage=-1") or {}
    items = listing.get("items", []) if isinstance(listing, dict) else listing
    for item in items:
        slug = item.get("slug")
        try:
            rec = mealie("GET", f"/api/recipes/{slug}")
            rid = str(rec.get("id") or item.get("id") or "")
            if not rid or not rec.get("name"):
                raise ValueError("missing id or name")
            existing = c.execute("SELECT data, created_at FROM recipes WHERE id=?", (rid,)).fetchone()
            now = _now()
            full = _default(rid, rec.get("slug") or slug, rec["name"], now)
            full.update(rec)
            full["id"] = rid
            full["dateUpdated"] = rec.get("dateUpdated") or now
            other = c.execute("SELECT id FROM recipes WHERE slug=?", (full["slug"],)).fetchone()
            if other is not None and other["id"] != rid:
                full["slug"] = _unique_slug(c, full["name"], own_id=rid)

            if image_path(images_dir, rid) is None:
                full["image"] = None  # Mealie's token is meaningless without the file
                for name in ("original.webp", "min-original.webp"):
                    blob = mealie_bytes(f"/api/media/recipes/{rid}/images/{name}")
                    if blob and sniff_image(blob):
                        full["image"] = save_image(images_dir, rid, blob, "")
                        counts["images"] += 1
                        break
            else:
                prev = json.loads(existing["data"]).get("image") if existing else None
                if not prev:
                    with open(image_path(images_dir, rid), "rb") as f:
                        prev = hashlib.sha256(f.read()).hexdigest()[:8]
                full["image"] = prev

            _write(c, _normalize(full), existing["created_at"] if existing else now)
            counts["recipes"] += 1
            counts["updated" if existing else "created"] += 1
        except Exception as e:  # one bad recipe must not abort the whole migration
            counts["errors"].append(f"{slug}: {e}")

    try:
        user = mealie("GET", "/api/users/self") or {}
        favs = mealie("GET", f"/api/users/{user['id']}/favorites") or {}
        ratings = favs.get("ratings", []) if isinstance(favs, dict) else favs
        for r in ratings:
            rid = str(r.get("recipeId") or "")
            if r.get("isFavorite") and rid:
                set_favorite(c, rid, True)
                if c.execute("SELECT 1 FROM favorites WHERE recipe_id=?", (rid,)).fetchone():
                    counts["favorites"] += 1
    except Exception as e:
        counts["errors"].append(f"favorites: {e}")
    c.commit()
    return counts
