"""
TablePlan — a family kitchen dashboard that sits on top of Mealie.

Mealie (separate container) owns recipes, AI screenshot/link import, scaling,
meal-plan storage and shopping lists. TablePlan adds:

  * one-tap meal-plan generation for a week or month from your recipe pool
  * an inventory with use-by dates you can trust: printed dates you enter, or a countdown once
    something is opened or frozen (USDA FoodKeeper shelf-life data); sealed items are never guessed
  * shopping list → inventory: tick an item off and it's stocked
  * email (SMTP), print, CSV, TXT and calendar (.ics) exports
  * an Apple Home–style mobile UI (static/)

Pure Python standard library + SQLite. No pip installs.
"""

import base64
import csv
import hashlib
import http.client
import ipaddress
import secrets
import shutil
import socket
import hmac
import html
import io
import json
import mimetypes
import os
import random
import statistics
import re
import smtplib
import sqlite3
import ssl
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import uuid
import urllib.request
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("font/woff2", ".woff2")
STATIC_DIR = os.path.join(HERE, "static")
SEED_FILE = os.path.join(HERE, "seed", "starter_shelf_life.json")


def env(name, default=""):
    return os.environ.get(name, default)


def log(*a):
    print("[tableplan]", *a, flush=True)


DATA_DIR = env("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "tableplan.db")
LISTEN_PORT = int(env("PORT") or env("LISTEN_PORT", "8080"))   # PORT is what Railway/Heroku-style hosts set
APP_VERSION = (open(os.path.join(HERE, "VERSION")).read().strip()
               if os.path.exists(os.path.join(HERE, "VERSION")) else "dev")
UPDATE_FEED = env("TABLEPLAN_UPDATE_FEED", "https://thomasjvalenzuela.github.io/tableplan/version.json")
INSTALL_METHOD = env("TABLEPLAN_INSTALL", "zimaos")
NATIVE = env("TABLEPLAN_BACKEND", "native").lower() != "mealie"   # native = TablePlan's own storage (no Mealie)   # zimaos | cli | manual
# Set TABLEPLAN_PUBLIC=1 when TablePlan is reachable from the internet (custom domain, Railway, …):
# sign-in is then always required, and until a household password exists the one-time setup code
# printed in the server log is the only way in.
ON_RAILWAY = bool(env("RAILWAY_ENVIRONMENT") or env("RAILWAY_ENVIRONMENT_NAME"))


def _env_flag(name, default):
    v = env(name).strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


PUBLIC_MODE = _env_flag("TABLEPLAN_PUBLIC", ON_RAILWAY)
# Only trust X-Forwarded-For / X-Forwarded-Host when a reverse proxy we control sits in front (Railway does).
TRUST_PROXY = _env_flag("TABLEPLAN_TRUST_PROXY", ON_RAILWAY)
SETUP_CODE = base64.b32encode(os.urandom(10)).decode()   # 16 chars, 80 bits
SESSION_DAYS = 180

FOODKEEPER_URL = env("FOODKEEPER_URL", "https://www.fsis.usda.gov/shared/data/EN/foodkeeper.json")

LOCATIONS = ("fridge", "freezer", "pantry")   # storage kinds: shelf life follows these
# Places: where things live in this kitchen. Each is one of the three kinds; "spices" and "baking" are pantry shelves.
DEFAULT_PLACES = [{"key": "fridge", "label": "Fridge", "kind": "fridge"}, {"key": "freezer", "label": "Freezer", "kind": "freezer"},
                  {"key": "pantry", "label": "Pantry", "kind": "pantry"},
                  {"key": "spices", "label": "Spice cabinet", "kind": "pantry"},
                  {"key": "baking", "label": "Baking supplies", "kind": "pantry"}]
DEFAULT_STORES = ("Aldi", "Costco")
DEFAULT_SETTINGS = {
    "meal_types": ["dinner"],
    "no_repeat_days": 14,
    "prefer_expiring": True,
    "include_tags": [],
    "exclude_tags": [],
    "fill_empty_only": True,
    "auto_plan_day": "",          # "" (off) or mon..sun
    "auto_plan_email": False,         # "send the plan when it's made" (all notification channels)
    "expiry_alert": False,            # daily "use soon" alert
    "expiry_alert_hour": 8,
    "recipe_style": "classic",        # classic | steps
    "stove": "electric",              # gas | electric | induction
    "oven": "conventional",           # conventional | convection | air_fryer | toaster_oven
    "eat_times": {"breakfast": "08:00", "lunch": "12:30", "dinner": "18:30"},   # when we usually eat, per meal
    "start_reminder": False,          # message me when it's time to start cooking
    "locations": DEFAULT_PLACES,      # inventory places (fridge, freezer, pantry + shelves like the spice cabinet)
    "temp_unit": "F",                 # F | C
    "ai_budget": 0,                   # monthly USD; 0 = no alert
    "pantry_check_days": 7,           # kitchen check-in: 7 weekly, 14 every 2 weeks, 0 off
    "checkin_day": "sun",             # ...on this day
    "checkin_hour": 18,               # ...from this hour (Sunday evening)
    "expiring_window_days": 3,
    "plan_horizon_days": 14,          # how many days the planner board shows
    "plan_reminder_days": 3,          # remind when the plan runs out within N days (0 = off)
    "polish_imports": True,           # AI rewrites imported steps clearly (never amounts); needs an OpenAI key
    "whatsnew_seen": [],              # ids from static/whatsnew.json already shown (on any device)
    "theme": "system",                # mode: system | light | dark (a device's own choice wins)
    "palette": "mono",                # look: mono | midnight | blossom | forest
    "staples": ["Table salt", "Kosher salt", "Black pepper", "Water", "Olive oil", "Vegetable oil", "Cooking spray",
                "Granulated sugar", "All-purpose flour", "Baking soda", "Baking powder"],   # "always have": never on the list
    "budget": {"period": "week", "amount": 0, "week_start": "mon", "stores": {}, "timezone": "", "plan_aware": True},
    "price_ai": False,
    "pans": [],
    "missing_alert_daybefore": False, # message the day before when a planned meal is missing ingredients
    "missing_alert_morning": False,   # ...and that morning
    "missing_alert_time": "08:00",                       # "Pans I have": [{kind, w, h, d, cups, quarts}] (used to suggest a pan when scaling)                # look up missing prices with AI web search (monthly per food, within the AI budget)
    "categories": ["Main dish", "Side dish", "Soup", "Salad", "Appetizer", "Dessert", "Breakfast", "Snack", "Sauce",
                   "Drink"],          # recipe categories, in display order
}



# ============================================================ database

_db_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=FULL")   # writes are rare; never lose one to a power cut
    return conn


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS shelf_rules (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  keywords TEXT DEFAULT '',
  source TEXT NOT NULL DEFAULT 'starter',      -- custom | usda | starter
  usda_id INTEGER,
  category TEXT DEFAULT '',
  default_location TEXT DEFAULT 'fridge',
  sealed_pantry INTEGER, sealed_fridge INTEGER,
  opened_pantry INTEGER, opened_fridge INTEGER,
  freezer INTEGER, thawed_fridge INTEGER,
  tips TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_rules_usda ON shelf_rules(usda_id) WHERE usda_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS food_map (
  food_key TEXT PRIMARY KEY,
  rule_id INTEGER REFERENCES shelf_rules(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS pantry_items (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  quantity_text TEXT DEFAULT '',
  location TEXT NOT NULL DEFAULT 'fridge',
  amount_left REAL NOT NULL DEFAULT 1.0,
  purchased_on TEXT NOT NULL,
  opened_on TEXT,
  frozen_on TEXT,
  expires_on TEXT,
  expiry_source TEXT DEFAULT 'none',            -- package | manual | opened | frozen | none (old: estimate)
  rule_id INTEGER REFERENCES shelf_rules(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'active',        -- active | used | tossed
  finished_on TEXT,
  mealie_item_id TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pantry_status ON pantry_items(status, expires_on);
CREATE TABLE IF NOT EXISTS pantry_events (
  id INTEGER PRIMARY KEY,
  item_id INTEGER REFERENCES pantry_items(id) ON DELETE CASCADE,
  at TEXT NOT NULL, action TEXT NOT NULL, detail TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS allocations (
  plan_entry_id INTEGER NOT NULL, pantry_item_id INTEGER NOT NULL, food_key TEXT NOT NULL, qty REAL, unit TEXT
);
CREATE INDEX IF NOT EXISTS ix_alloc_entry ON allocations(plan_entry_id);
CREATE INDEX IF NOT EXISTS ix_alloc_item ON allocations(pantry_item_id);
CREATE TABLE IF NOT EXISTS recipe_cache (
  id TEXT PRIMARY KEY, updated TEXT, foods TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS cook_times (
  id INTEGER PRIMARY KEY, recipe_id TEXT NOT NULL, actual_min REAL NOT NULL, estimate_min REAL NOT NULL, at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cook_times_recipe ON cook_times(recipe_id);
CREATE TABLE IF NOT EXISTS plan_eat_at (entry_id TEXT PRIMARY KEY, eat_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scan_log (id INTEGER PRIMARY KEY, code TEXT NOT NULL, at TEXT NOT NULL, results TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS food_pref (
  food_id INTEGER PRIMARY KEY, product TEXT, size TEXT, store_id TEXT, price REAL, upc TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS import_jobs (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, user_id INTEGER, pages INTEGER NOT NULL DEFAULT 0,
  draft TEXT, image_url TEXT, meta TEXT NOT NULL DEFAULT '{}', error TEXT, slug TEXT, dismissed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guided_cache (
  recipe_id TEXT, profile TEXT, updated TEXT, source TEXT, data TEXT, created_at TEXT,
  PRIMARY KEY (recipe_id, profile)
);
CREATE TABLE IF NOT EXISTS ai_usage (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, feature TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_ai_usage_at ON ai_usage(at);
CREATE TABLE IF NOT EXISTS upc_cache (code TEXT PRIMARY KEY, data TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS diary (
  id INTEGER PRIMARY KEY, recipe_id TEXT NOT NULL, plan_entry_id INTEGER, kind TEXT NOT NULL DEFAULT 'cooked',
  cooked_at TEXT NOT NULL, rating INTEGER, note TEXT NOT NULL DEFAULT '', photo TEXT, servings REAL, undo_token TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_diary_recipe ON diary(recipe_id, cooked_at);
CREATE TABLE IF NOT EXISTS trips (
  id INTEGER PRIMARY KEY, store_id TEXT, store_name TEXT NOT NULL DEFAULT '', date TEXT NOT NULL, method TEXT NOT NULL,
  items INTEGER NOT NULL DEFAULT 0, checked INTEGER NOT NULL DEFAULT 0, total REAL, files TEXT NOT NULL DEFAULT '[]',
  undo TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'done', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purchases (
  id INTEGER PRIMARY KEY, trip_id INTEGER REFERENCES trips(id) ON DELETE CASCADE, store_name TEXT NOT NULL DEFAULT '',
  date TEXT NOT NULL, food_id INTEGER, name TEXT NOT NULL, raw_text TEXT NOT NULL DEFAULT '', qty REAL, unit TEXT,
  price REAL, pantry_item_id INTEGER, list_item_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_purchases_food ON purchases(food_id, date);
CREATE TABLE IF NOT EXISTS upc_local (code TEXT PRIMARY KEY, food_id INTEGER, name TEXT NOT NULL, quantity TEXT DEFAULT '', at TEXT);
CREATE TABLE IF NOT EXISTS prices (
  id INTEGER PRIMARY KEY, food_id INTEGER, food_key TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', source TEXT NOT NULL,
  store TEXT NOT NULL DEFAULT '', price REAL NOT NULL, qty REAL, unit TEXT NOT NULL DEFAULT '', unit_price REAL, base TEXT,
  url TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', observed_on TEXT NOT NULL, fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_prices_key ON prices(food_key, source);
CREATE TABLE IF NOT EXISTS consumption (food_key TEXT PRIMARY KEY, days REAL, n INTEGER NOT NULL DEFAULT 0, updated TEXT);
CREATE TABLE IF NOT EXISTS ext_cache (key TEXT PRIMARY KEY, at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS idea_cache (id TEXT PRIMARY KEY, data TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS idea_dismissed (key TEXT PRIMARY KEY, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS image_picks (
  kind TEXT, key TEXT, idx INTEGER DEFAULT 0, file TEXT, credit TEXT, missing INTEGER DEFAULT 0, updated TEXT,
  PRIMARY KEY (kind, key)
);
"""


def _food_id(c, text):
    """Canonical food id for a name (created when new)."""
    t = (text or "").strip()
    return n_foods.resolve(c, t) if t and n_foods.normalize(t) else None


def _ing_food_name(line):
    p = parse_ing_text(line)
    return p["food"] if p else ""


def _annotate_foods(c, rec, classify=None):
    """Store the canonical food id on each ingredient of a recipe (in place). Returns the recipe."""
    ings = [g for g in rec.get("recipeIngredient") or [] if isinstance(g, dict)]
    names = {}
    for g in ings:
        nm = (g.get("food") or {}).get("name") if isinstance(g.get("food"), dict) else ""
        names[id(g)] = nm or _ing_food_name(_ing_line(g))
    found = n_foods.resolve_many(c, [n for n in names.values() if n], classify) if any(names.values()) else {}
    for g in ings:
        nm = names[id(g)]
        g["food_id"] = found.get(nm) if nm else None
    return rec


def _food_classifier():
    """AI mapping of unknown ingredient names onto existing canonical foods (or a new canonical name)."""
    if not cfg("openai_key"):
        return None

    def classify(unknown, existing):
        schema = {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {
            "type": "array", "items": {"type": "object", "additionalProperties": False,
                                       "required": ["text", "food_id", "new_name"],
                                       "properties": {"text": {"type": "string"}, "food_id": {"type": ["integer", "null"]},
                                                      "new_name": {"type": "string"}}}}}}
        out = openai_chat([{"role": "user", "content": (
            "Map each grocery or ingredient name to an existing canonical food id when it is the same food, or propose a "
            "short new canonical name (sentence case, singular unless the food is always plural, no brand, no size). "
            "Different foods must stay different: sea salt is not table salt, unsalted butter is not salted butter, whole "
            "milk is not 2% milk, extra-virgin olive oil is not olive oil, ground cinnamon is not cinnamon sticks.\n\n"
            + json.dumps({"names": unknown[:80], "existing": existing[:600]}, ensure_ascii=False))}],
            "food_map", schema, "food matching", f"{len(unknown)} names")
        return out.get("items") or []
    return classify


def _food_usage(c):
    """{food_id: {"recipes": n, "list": n, "pantry": n}}"""
    use = {}
    for row in c.execute("SELECT data FROM recipes"):
        seen = set()
        for g in (json.loads(row["data"]).get("recipeIngredient") or []):
            fid = g.get("food_id") if isinstance(g, dict) else None
            if fid is not None and fid not in seen:
                seen.add(fid)
                use.setdefault(fid, {"recipes": 0, "list": 0, "pantry": 0})
                use[fid]["recipes"] += 1
    for r in c.execute("SELECT food_id FROM shopping_items WHERE checked=0 AND food_id IS NOT NULL"):
        use.setdefault(r[0], {"recipes": 0, "list": 0, "pantry": 0})
        use[r[0]]["list"] += 1
    for r in c.execute("SELECT food_id FROM pantry_items WHERE status='active' AND food_id IS NOT NULL"):
        use.setdefault(r[0], {"recipes": 0, "list": 0, "pantry": 0})
        use[r[0]]["pantry"] += 1
    return use


def foods_list(q=""):
    q = " ".join((q or "").lower().split())[:60]
    with db() as c:
        use = _food_usage(c)
        rows = c.execute("SELECT * FROM foods ORDER BY name COLLATE NOCASE").fetchall()
        out = []
        for r in rows:
            als = n_foods.aliases(c, r["id"])
            if q and q not in r["name"].lower() and not any(q in a.lower() for a in als):
                continue
            store = c.execute("SELECT store_id FROM food_store WHERE food_key=?", (n_lists.food_store_key(r["id"]),)).fetchone()
            out.append({"id": r["id"], "name": r["name"], "category": r["category"] or aisle_for(r["name"]) or "",
                        "location": r["location"] or "", "store_id": (store["store_id"] if store else r["store_id"]),
                        "aliases": als[:20], "uses": use.get(r["id"], {"recipes": 0, "list": 0, "pantry": 0})})
    out.sort(key=lambda f: (-(f["uses"]["recipes"] + f["uses"]["list"] + f["uses"]["pantry"]), f["name"].lower()))
    return {"foods": out[:300], "total": len(out)}


def food_update(fid, b):
    require_native()
    with db() as c:
        if not n_foods.get(c, fid):
            raise ApiError(404, "Food not found")
        try:
            if "name" in b:
                n_foods.rename(c, fid, _s(b.get("name"), 60))
        except ValueError as e:
            raise ApiError(400, str(e))
        fields = {}
        if "category" in b:
            fields["category"] = _s(b.get("category"), 40).strip() or None
        if "location" in b:
            loc = _s(b.get("location"), 20)
            if loc and loc not in LOCATIONS:
                raise ApiError(400, "Pick fridge, freezer or pantry.")
            fields["location"] = loc or None
        if "store_id" in b:
            sid = _store_arg(b.get("store_id"))
            if sid is not None and not n_lists.get_store(c, sid):
                raise ApiError(404, "Store not found")
            fields["store_id"] = sid
            k = n_lists.food_store_key(fid)
            if sid is None:
                c.execute("DELETE FROM food_store WHERE food_key=?", (k,))
            else:
                c.execute("INSERT INTO food_store(food_key, store_id) VALUES (?,?) ON CONFLICT(food_key) DO UPDATE SET "
                          "store_id=excluded.store_id", (k, sid))
        n_foods.update(c, fid, **fields)
    return next((f for f in foods_list()["foods"] if f["id"] == fid), {"id": fid})


def _food_repoint(c, src, dst):
    """Move every reference from food src to dst; returns what moved (for Undo)."""
    refs = {"recipes": [], "list": [r[0] for r in c.execute("SELECT id FROM shopping_items WHERE food_id=?", (src,))],
            "pantry": [r[0] for r in c.execute("SELECT id FROM pantry_items WHERE food_id=?", (src,))],
            "upc": [r[0] for r in c.execute("SELECT code FROM upc_cache WHERE food_id=?", (src,))], "store": None}
    c.execute("UPDATE shopping_items SET food_id=? WHERE food_id=?", (dst, src))
    c.execute("UPDATE pantry_items SET food_id=? WHERE food_id=?", (dst, src))
    c.execute("UPDATE upc_cache SET food_id=? WHERE food_id=?", (dst, src))
    for t in ("upc_local",):
        if c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone():
            c.execute(f"UPDATE {t} SET food_id=? WHERE food_id=?", (dst, src))
    st = c.execute("SELECT store_id FROM food_store WHERE food_key=?", (n_lists.food_store_key(src),)).fetchone()
    if st:
        refs["store"] = st["store_id"]
        c.execute("DELETE FROM food_store WHERE food_key=?", (n_lists.food_store_key(src),))
        c.execute("INSERT OR IGNORE INTO food_store(food_key, store_id) VALUES (?,?)", (n_lists.food_store_key(dst), st["store_id"]))
    for row in c.execute("SELECT id, data FROM recipes").fetchall():
        rec = json.loads(row["data"])
        hit = []
        for i, g in enumerate(rec.get("recipeIngredient") or []):
            if isinstance(g, dict) and g.get("food_id") == src:
                g["food_id"] = dst
                hit.append(i)
        if hit:
            refs["recipes"].append([row["id"], hit])
            c.execute("UPDATE recipes SET data=? WHERE id=?", (json.dumps(rec, separators=(",", ":")), row["id"]))
    return refs


def _food_unpoint(c, src, dst, refs):
    for iid in refs.get("list") or []:
        c.execute("UPDATE shopping_items SET food_id=? WHERE id=?", (src, iid))
    for pid in refs.get("pantry") or []:
        c.execute("UPDATE pantry_items SET food_id=? WHERE id=?", (src, pid))
    for code in refs.get("upc") or []:
        c.execute("UPDATE upc_cache SET food_id=? WHERE code=?", (src, code))
    if refs.get("store"):
        c.execute("INSERT OR REPLACE INTO food_store(food_key, store_id) VALUES (?,?)", (n_lists.food_store_key(src), refs["store"]))
    for rid, idxs in refs.get("recipes") or []:
        rec = n_recipes.get(c, rid)
        if not rec:
            continue
        ings = rec.get("recipeIngredient") or []
        for i in idxs:
            if i < len(ings) and isinstance(ings[i], dict) and ings[i].get("food_id") == dst:
                ings[i]["food_id"] = src
        c.execute("UPDATE recipes SET data=? WHERE id=?", (json.dumps(rec, separators=(",", ":")), rid))


def foods_merge(b):
    require_native()
    ids = b.get("ids")
    into = b.get("into")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 50 or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        raise ApiError(400, "Pick the foods to merge.")
    if not isinstance(into, int) or isinstance(into, bool):
        raise ApiError(400, "Pick the food to keep.")
    with db() as c:
        try:
            token, gone = n_foods.merge(c, ids, into, _food_repoint)
        except KeyError:
            raise ApiError(404, "Food not found")
    return {"ok": True, "merged": len(gone), "undo_token": token}


def foods_unmerge(b):
    require_native()
    token = _s((b or {}).get("undo_token"), 40).strip()
    with db() as c:
        try:
            n_foods.unmerge(c, token, _food_unpoint)
        except KeyError:
            raise ApiError(404, "That merge can't be undone any more.")
    return {"ok": True}


def migrate_expiry_estimates(c):
    """One time: no guessed dates. Sealed items lose estimated dates; opened/frozen ones become countdowns."""
    n = {"cleared": 0, "opened": 0, "frozen": 0}
    for r in c.execute("SELECT * FROM pantry_items WHERE status='active' AND expiry_source='estimate'").fetchall():
        rule = c.execute("SELECT * FROM shelf_rules WHERE id=?", (r["rule_id"],)).fetchone() if r["rule_id"] else None
        if r["location"] == "freezer" and r["frozen_on"] and rule and rule["freezer"]:
            exp, src = parse_date(r["frozen_on"]) + timedelta(days=rule["freezer"]), "frozen"
            n["frozen"] += 1
        elif r["opened_on"] and opened_days(rule, r["location"]):
            exp, src = parse_date(r["opened_on"]) + timedelta(days=opened_days(rule, r["location"])), "opened"
            n["opened"] += 1
        else:
            exp, src = None, "none"
            n["cleared"] += 1
        c.execute("UPDATE pantry_items SET expires_on=?, expiry_source=? WHERE id=?", (iso(exp), src, r["id"]))
    log("use-by dates: estimates removed:", ", ".join(f"{k} {v}" for k, v in n.items()))
    return n


def migrate_foods(c):
    """One time: canonical foods for everything already stored (recipes, list, pantry, store memory, barcodes)."""
    counts = {"foods_seeded": n_foods.seed(c, c.execute("SELECT * FROM shelf_rules").fetchall()),
              "recipes": 0, "list_items": 0, "pantry_items": 0, "store_memory": 0, "barcodes": 0}
    for row in c.execute("SELECT id FROM recipes").fetchall():
        rec = n_recipes.get(c, row["id"])
        if rec and rec.get("recipeIngredient"):
            _annotate_foods(c, rec)
            c.execute("UPDATE recipes SET data=? WHERE id=?", (json.dumps(rec, separators=(",", ":")), row["id"]))
            counts["recipes"] += 1
    for r in c.execute("SELECT id, food, note, text FROM shopping_items WHERE food_id IS NULL").fetchall():
        fid = _food_id(c, r["food"]) if r["food"] else None
        if fid:
            c.execute("UPDATE shopping_items SET food_id=? WHERE id=?", (fid, r["id"]))
            counts["list_items"] += 1
    for r in c.execute("SELECT id, name FROM pantry_items WHERE food_id IS NULL").fetchall():
        fid = _food_id(c, r["name"])
        if fid:
            c.execute("UPDATE pantry_items SET food_id=? WHERE id=?", (fid, r["id"]))
            counts["pantry_items"] += 1
    for r in c.execute("SELECT food_key, store_id FROM food_store WHERE food_key NOT LIKE 'food:%'").fetchall():
        fid = _food_id(c, r["food_key"])
        if fid:
            c.execute("INSERT OR IGNORE INTO food_store(food_key, store_id) VALUES (?,?)", (n_lists.food_store_key(fid), r["store_id"]))
            counts["store_memory"] += 1
    for r in c.execute("SELECT code, data FROM upc_cache WHERE food_id IS NULL").fetchall():
        try:
            d = json.loads(r["data"] or "{}")
        except ValueError:
            continue
        nm = d.get("name") or d.get("product_name") or ""
        fid = _food_id(c, nm) if nm else None
        if fid:
            c.execute("UPDATE upc_cache SET food_id=? WHERE code=?", (fid, r["code"]))
            counts["barcodes"] += 1
    log("canonical foods:", ", ".join(f"{k} {v}" for k, v in counts.items()))
    return counts


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with db() as c:
        c.executescript(SCHEMA)
        n_recipes.init(c); n_plans.init(c); n_lists.init(c); n_foods.init(c); n_users.init(c)
        c.execute("DELETE FROM guided_cache WHERE profile NOT IN ('ai3', 'auto3')")   # older step-by-step formats
        for table, col, typ in (("pantry_items", "food_id", "INTEGER"), ("upc_cache", "food_id", "INTEGER"),
                                ("pantry_items", "product", "TEXT"), ("pantry_items", "image", "TEXT"),
                                ("pantry_items", "upc", "TEXT"), ("pantry_items", "pack_qty", "REAL"),
                                ("pantry_items", "place", "TEXT"),
                                ("pantry_items", "review", "INTEGER"), ("upc_local", "brand", "TEXT")):
            if col not in {r[1] for r in c.execute(f"PRAGMA table_info({table})")}:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        cols = {r[1] for r in c.execute("PRAGMA table_info(pantry_items)")}
        for col, typ in (("qty", "REAL"), ("unit", "TEXT"), ("original_qty", "REAL")):
            if col not in cols:   # known amounts: qty left in `unit`, original_qty = the full package
                c.execute(f"ALTER TABLE pantry_items ADD COLUMN {col} {typ}")
        _migrate_barcode_names(c)
        if not c.execute("SELECT 1 FROM settings WHERE key='stores_seeded'").fetchone():
            n_lists.seed_stores(c, DEFAULT_STORES)
            c.execute("INSERT INTO settings(key, value) VALUES ('stores_seeded', 'true')")
        if NATIVE:
            n_lists.single_list(c)   # one ongoing list; older installs with several get merged once
        if c.execute("SELECT COUNT(*) FROM shelf_rules").fetchone()[0] == 0:
            seed = json.load(open(SEED_FILE, encoding="utf-8"))
            for r in seed["rules"]:
                insert_rule(c, r, r.get("source", "starter"))
            log(f"seeded {len(seed['rules'])} starter shelf-life rules")
        if not c.execute("SELECT 1 FROM settings WHERE key='expiry_no_guess'").fetchone():
            migrate_expiry_estimates(c)
            c.execute("INSERT INTO settings(key, value) VALUES ('expiry_no_guess', 'true')")
        if not c.execute("SELECT 1 FROM settings WHERE key='foods_migrated'").fetchone():
            migrate_foods(c)
            c.execute("INSERT INTO settings(key, value) VALUES ('foods_migrated', 'true')")
        if not c.execute("SELECT 1 FROM settings WHERE key='titlecase_migrated'").fetchone():
            for row in c.execute("SELECT id, name FROM recipes").fetchall():   # one-time: names in title case
                tc = title_case(row["name"])
                if tc and tc != row["name"]:
                    rec = n_recipes.get(c, row["id"])
                    n_recipes.update(c, row["id"], dict(rec, name=tc))
            c.execute("INSERT INTO settings(key, value) VALUES ('titlecase_migrated', 'true')")


RULE_FIELDS = ("sealed_pantry", "sealed_fridge", "opened_pantry", "opened_fridge", "freezer", "thawed_fridge")


def insert_rule(c, r, source):
    c.execute(
        """INSERT INTO shelf_rules (name, keywords, source, usda_id, category, default_location,
           sealed_pantry, sealed_fridge, opened_pantry, opened_fridge, freezer, thawed_fridge, tips)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (r["name"], r.get("keywords", ""), source, r.get("usda_id"), r.get("category", ""),
         r.get("default_location") or guess_location(r),
         *[r.get(f) for f in RULE_FIELDS], r.get("tips", "")),
    )


def guess_location(r):
    if r.get("sealed_pantry"):
        return "pantry"
    if r.get("sealed_fridge") or r.get("opened_fridge"):
        return "fridge"
    if r.get("freezer"):
        return "freezer"
    return "pantry"


def get_settings():
    s = dict(DEFAULT_SETTINGS)
    with db() as c:
        for row in c.execute("SELECT key, value FROM settings"):
            if row["key"] not in DEFAULT_SETTINGS:      # never expose cfg.* secrets or internal keys
                continue
            try:
                s[row["key"]] = json.loads(row["value"])
            except ValueError:
                pass
    return s


_MEAL_TYPES = ("breakfast", "lunch", "dinner", "side", "snack", "dessert", "drink")


def _v_int(lo, hi):
    def f(v):
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ValueError("must be a number")
        n = int(float(v))
        if not lo <= n <= hi:
            raise ValueError(f"must be between {lo} and {hi}")
        return n
    return f


def _v_num(lo, hi):
    def f(v):
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ValueError("must be a number")
        n = float(v)
        if not lo <= n <= hi:   # also rejects NaN
            raise ValueError(f"must be between {lo} and {hi}")
        return n
    return f


def _v_bool(v):
    if not isinstance(v, bool):
        raise ValueError("must be true or false")
    return v


def _v_enum(*choices):
    def f(v):
        if v not in choices:
            raise ValueError("must be one of " + ", ".join(repr(c) for c in choices))
        return v
    return f


def _v_ids(max_items):
    def f(v):
        if not isinstance(v, list) or len(v) > max_items:
            raise ValueError(f"must be a list of at most {max_items} ids")
        out = []
        for x in v:
            if not isinstance(x, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", x):
                raise ValueError("ids are short lowercase words")
            if x not in out:
                out.append(x)
        return out
    return f


def _v_names(v, max_items, max_len):
    if not isinstance(v, list) or len(v) > max_items:
        raise ValueError(f"must be a list of at most {max_items} names")
    out = []
    for x in v:
        if not isinstance(x, str):
            raise ValueError("names must be text")
        x = " ".join(x.split())
        if not 1 <= len(x) <= max_len:
            raise ValueError(f"names must be 1-{max_len} characters")
        if x.lower() not in (y.lower() for y in out):
            out.append(x)
    return out


def whatsnew_ids():
    try:
        with open(os.path.join(STATIC_DIR, "whatsnew.json"), encoding="utf-8") as f:
            return [e["id"] for e in json.load(f) if isinstance(e, dict) and e.get("id")]
    except (OSError, ValueError):
        return []


def _v_places(v):
    if not isinstance(v, list) or not 3 <= len(v) <= 20:
        raise ValueError("must be a list of 3 to 20 places")
    out, seen = [], set()
    for x in v:
        if not isinstance(x, dict):
            raise ValueError("has a bad place")
        key, label, kind = str(x.get("key") or ""), " ".join(str(x.get("label") or "").split())[:30], x.get("kind")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,19}", key) or key in seen or kind not in LOCATIONS or not label:
            raise ValueError(f"has a bad place {key[:20]}")
        if key in LOCATIONS and kind != key:
            raise ValueError(f"keeps {key} as a {key}")
        seen.add(key)
        out.append({"key": key, "label": label, "kind": kind})
    if not set(LOCATIONS) <= seen:
        raise ValueError("must keep the fridge, freezer and pantry")
    return out


def places():
    return {p["key"]: p for p in (get_settings().get("locations") or DEFAULT_PLACES)}


def split_place(key):
    """A place key -> (storage kind, place key or None). Unknown keys -> (None, None)."""
    p = places().get(key) if isinstance(key, str) else None
    if not p:
        return None, None
    return p["kind"], (None if p["key"] in LOCATIONS else p["key"])


def ensure_place(key, label, kind="pantry"):
    """Add a place (e.g. the spice cabinet) if this household doesn't have it yet."""
    ps = list(places().values())
    if key not in {p["key"] for p in ps}:
        save_settings({"locations": ps + [{"key": key, "label": label, "kind": kind}]})


def _v_eat_times(v):
    if not isinstance(v, dict) or len(v) > 10:
        raise ValueError("must map meal types to times")
    out = {}
    for k, t in v.items():
        if k not in ENTRY_ORDER:
            raise ValueError(f"has an unknown meal type {str(k)[:20]}")
        if not (isinstance(t, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t)):
            raise ValueError("times look like 18:30")
        out[k] = t
    return out


def _v_categories(v):
    if not isinstance(v, list) or len(v) > MAX_CATEGORIES:
        raise ValueError(f"must be a list of at most {MAX_CATEGORIES} names")
    out = []
    for x in v:
        if not isinstance(x, str):
            raise ValueError("names must be text")
        x = " ".join(x.split())
        if not 1 <= len(x) <= 30:
            raise ValueError("names must be 1-30 characters")
        if x.lower() in (y.lower() for y in out):
            raise ValueError(f"has {x} twice")
        out.append(x)
    return out


MAX_CATEGORIES = 30


def _v_strlist(max_items, max_len, choices=None):
    def f(v):
        if not isinstance(v, list) or len(v) > max_items:
            raise ValueError(f"must be a list of at most {max_items} items")
        out = []
        for x in v:
            if not isinstance(x, str) or len(x) > max_len:
                raise ValueError("list items must be short text")
            if choices and x not in choices:
                raise ValueError("must only contain " + ", ".join(choices))
            if x not in out:
                out.append(x)
        return out
    return f


SETTINGS_VALIDATORS = {
    "meal_types": _v_strlist(len(_MEAL_TYPES), 20, _MEAL_TYPES),
    "no_repeat_days": _v_int(0, 365),
    "prefer_expiring": _v_bool,
    "include_tags": _v_strlist(200, 80),
    "exclude_tags": _v_strlist(200, 80),
    "fill_empty_only": _v_bool,
    "auto_plan_day": _v_enum("", "mon", "tue", "wed", "thu", "fri", "sat", "sun"),
    "auto_plan_email": _v_bool,
    "expiry_alert": _v_bool,
    "expiry_alert_hour": _v_int(0, 23),
    "recipe_style": _v_enum("classic", "steps"),
    "stove": _v_enum("gas", "electric", "induction"),
    "oven": _v_enum("conventional", "convection", "air_fryer", "toaster_oven"),
    "eat_times": _v_eat_times,
    "start_reminder": _v_bool,
    "locations": _v_places,
    "temp_unit": _v_enum("F", "C"),
    "ai_budget": _v_num(0, 100_000),
    "pantry_check_days": _v_int(0, 365),
    "checkin_day": _v_enum("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
    "checkin_hour": _v_int(0, 23),
    "expiring_window_days": _v_int(0, 60),
    "plan_horizon_days": _v_int(7, 28),
    "plan_reminder_days": _v_int(0, 7),
    "polish_imports": _v_bool,
    "categories": _v_categories,
    "whatsnew_seen": _v_ids(500),
    "theme": _v_enum("system", "light", "dark"),
    "palette": _v_enum("mono", "midnight", "blossom", "forest"),
    "staples": lambda v: _v_names(v, 100, 40),
    "budget": lambda v: _v_budget(v),
    "price_ai": _v_bool,
    "pans": lambda v: _v_pans(v),
    "missing_alert_daybefore": _v_bool,
    "missing_alert_morning": _v_bool,
    "missing_alert_time": lambda v: _v_hhmm(v),
}


def _v_hhmm(v):
    if not isinstance(v, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise ValueError("must be a time like 08:00")
    return v


def _v_pans(v):
    if not isinstance(v, list) or len(v) > 30:
        raise ValueError("must be a list of up to 30 pans")
    out = []
    for p in v:
        c = n_pans.clean(p)
        if not c:
            raise ValueError("has a pan that couldn't be read")
        if all(x["label"] != c["label"] for x in out):   # the same pan twice is kept once
            out.append(c)
    return out


def _v_budget(v):
    if not isinstance(v, dict):
        raise ValueError("must be an object")
    period = v.get("period", "week")
    if period not in ("week", "month"):
        raise ValueError("period must be week or month")
    amount = _v_num(0, 1_000_000)(v.get("amount", 0))
    ws = v.get("week_start", "mon")
    if ws not in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        raise ValueError("week_start must be a weekday")
    stores = v.get("stores") or {}
    if not isinstance(stores, dict) or len(stores) > 12:
        raise ValueError("stores must map up to 12 store ids to amounts")
    stores = {str(k)[:64]: _v_num(0, 1_000_000)(x) for k, x in stores.items()}
    tz = v.get("timezone") or ""
    if not isinstance(tz, str) or len(tz) > 60:
        raise ValueError("timezone must be a time zone name")
    if tz:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(tz)
        except Exception:
            raise ValueError("timezone isn't a known time zone")
    return {"period": period, "amount": amount, "week_start": ws, "stores": stores, "timezone": tz,
            "plan_aware": bool(v.get("plan_aware", True))}


def validate_setting(k, v):
    try:
        return SETTINGS_VALIDATORS[k](v)
    except (ValueError, TypeError, OverflowError) as e:
        raise ApiError(400, f"Setting {k} {e}.")


def save_settings(patch):
    clean = {k: validate_setting(k, v) for k, v in patch.items() if k in DEFAULT_SETTINGS}
    with db() as c:
        for k, v in clean.items():
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (k, json.dumps(v)))
    return get_settings()


PER_USER_SETTINGS = ("theme", "palette", "whatsnew_seen")   # each member keeps their own once accounts exist


def set_internal(key, value):
    with db() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, json.dumps(value)))


def get_internal(key, default=None):
    with db() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


# ============================================================ config (wizard-managed, .env values are defaults)

def _env_list(name):
    return [a.strip() for a in env(name).split(",") if a.strip()]


CFG_DEFAULTS = {
    "mealie_url": env("MEALIE_URL", "http://mealie:9000").rstrip("/"),
    "mealie_token": env("MEALIE_API_TOKEN"),
    "mealie_public_url": env("MEALIE_PUBLIC_URL").rstrip("/"),   # blank = same host as TablePlan
    "mealie_public_port": env("MEALIE_PUBLIC_PORT", "9925"),
    "group_slug": env("MEALIE_GROUP_SLUG", "home"),
    "household_name": "",
    "people": 2,
    "scale_to_household": True,
    "smtp_host": env("SMTP_HOST"),
    "smtp_port": int(env("SMTP_PORT", "587") or 587),
    "smtp_security": (env("SMTP_SECURITY", "starttls") or "starttls").lower(),
    "smtp_user": env("SMTP_USER"),
    "smtp_password": env("SMTP_PASSWORD"),
    "smtp_from": env("SMTP_FROM") or env("SMTP_USER"),
    "mail_to": _env_list("MAIL_TO"),
    "telegram_token": env("TELEGRAM_BOT_TOKEN"),
    "telegram_chat_id": env("TELEGRAM_CHAT_ID"),
    "telegram_chat_name": "",
    "telegram_bot": "",
    "telegram_link_code": "",
    "telegram_link_expires": 0,
    "ntfy_server": env("NTFY_SERVER", "https://ntfy.sh"),
    "ntfy_topic": env("NTFY_TOPIC"),
    "ntfy_token": env("NTFY_TOKEN"),
    "openai_key": env("OPENAI_API_KEY"),
    "openai_model": env("OPENAI_MODEL", "gpt-5-mini"),
    "openai_admin_key": env("OPENAI_ADMIN_KEY"),
    "mealie_user_id": "",
    "app_password_hash": "",
    "session_secret": "",
    "setup_complete": False,
}
SECRET_KEYS = {"mealie_token", "smtp_password", "app_password_hash", "session_secret", "telegram_token", "ntfy_token",
               "openai_key", "openai_admin_key", "kroger_client_secret", "bls_key", "unsplash_key", "pexels_key", "mealdb_key", "spoonacular_key",
               "telegram_link_code"}
_cfg = {}
_cfg_lock = threading.Lock()


def load_cfg():
    with _cfg_lock:
        _cfg.clear()
        with db() as c:
            for row in c.execute("SELECT key, value FROM settings WHERE key LIKE 'cfg.%'"):
                try:
                    _cfg[row["key"][4:]] = json.loads(row["value"])
                except ValueError:
                    pass
        if not _cfg.get("session_secret"):
            set_cfg(session_secret=base64.urlsafe_b64encode(os.urandom(32)).decode())
        # Older .env-based installs that already have a token skip the wizard.
        if "setup_complete" not in _cfg and CFG_DEFAULTS["mealie_token"]:
            _cfg["setup_complete"] = True


def cfg(key):
    v = _cfg.get(key)
    if v in (None, "") and key in CFG_DEFAULTS:
        return CFG_DEFAULTS[key]
    return v


def set_cfg(**kv):
    with db() as c:
        for k, v in kv.items():
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      ("cfg." + k, json.dumps(v)))
            _cfg[k] = v


_req = threading.local()


def mealie_public():
    """Public Mealie URL for links: explicit setting, else same host the user reached TablePlan on."""
    explicit = cfg("mealie_public_url")
    if explicit:
        return explicit.rstrip("/")
    host = getattr(_req, "host", "") or "localhost"
    scheme = getattr(_req, "scheme", "http")
    return f"{scheme}://{host}:{cfg('mealie_public_port')}"


def hash_password(pw, salt=None):
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def check_password(pw, stored):
    try:
        salt_b64, dk_b64 = stored.split("$", 1)
        return hmac.compare_digest(hash_password(pw, base64.b64decode(salt_b64)).split("$", 1)[1], dk_b64)
    except (ValueError, TypeError):
        return False


def make_session():
    ts = str(int(time.time()))
    sig = hmac.new(cfg("session_secret").encode(), ts.encode(), hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def valid_session(tok):
    try:
        ts, sig = tok.split(".", 1)
        if not ts.isdigit() or len(ts) > 12:
            return False
        good = hmac.new(cfg("session_secret").encode(), ts.encode(), hashlib.sha256).hexdigest()
        age = time.time() - int(ts)
        return hmac.compare_digest(sig.encode(), good.encode()) and -300 < age < SESSION_DAYS * 86400
    except (ValueError, AttributeError, TypeError):
        return False


def rotate_sessions():
    """Invalidate every existing sign-in (sessions are HMAC-signed with this secret)."""
    set_cfg(session_secret=base64.urlsafe_b64encode(os.urandom(32)).decode())


def users_exist():
    with db() as c:
        return n_users.count(c) > 0


# ---- onboarding checklist: per person, ticked automatically as the household gets going (or by hand)
CHECKLIST = (
    ("account", "Create your account", "settings:account"),
    ("household", "Set up your household", "settings:household"),
    ("recipe", "Add your first recipe", "#recipes"),
    ("plan", "Plan a meal", "#meals"),
    ("list", "Shop from your list", "#list"),
    ("inv_fridge", "Inventory your fridge", "stock:fridge"),
    ("inv_freezer", "Inventory your freezer", "stock:freezer"),
    ("inv_pantry", "Inventory your pantry", "stock:pantry"),
    ("inv_spices", "Inventory your spice cabinet", "stock:spices"),
    ("inv_baking", "Inventory your baking supplies", "stock:baking"),
    ("cook", "Cook a meal", "#recipes"),
    ("notify", "Turn on notifications", "settings:notify"),
    ("ai", "Turn on AI recipe import", "settings:ai"),
    ("members", "Invite your household", "settings:members"),
)
CHECKLIST_LINK = re.compile(r"(#[a-z]+(/[A-Za-z0-9_-]{1,80})?|settings:[a-z]+|stock:[a-z][a-z0-9_]{1,19})")
CHECKLIST_PLACE_MIN = 5          # "Inventory your fridge" ticks itself at 5 items there


def _count(c, sql):
    try:
        return c.execute(sql).fetchone()[0]
    except sqlite3.Error:
        return 0


def checklist_auto(user):
    done = set()
    if user:
        done.add("account")
    if cfg("household_name"):
        done.add("household")
    if any(channels_ready().values()) or (user and user.get("notify_email") and user.get("email")):
        done.add("notify")
    if cfg("openai_key"):
        done.add("ai")
    with db() as c:
        checks = {"recipe": "SELECT COUNT(*) FROM recipes", "plan": "SELECT COUNT(*) FROM meal_plans",
                  "list": "SELECT (SELECT COUNT(*) FROM shopping_items WHERE checked=1) + (SELECT COUNT(*) FROM trips)",
                  "cook": "SELECT COUNT(*) FROM diary",
                  "members": "SELECT CASE WHEN COUNT(*) >= 2 THEN 1 ELSE 0 END FROM users"}
        for k, sql in checks.items():
            if (NATIVE or k not in ("recipe", "plan", "list")) and _count(c, sql) > 0:
                done.add(k)
        try:
            for r in c.execute("SELECT COALESCE(place, location) k, COUNT(*) n FROM pantry_items WHERE status='active' GROUP BY 1"):
                if r["n"] >= CHECKLIST_PLACE_MIN:
                    done.add(f"inv_{r['k']}")
        except sqlite3.Error:
            pass
    return done


def _checklist_state(h):
    st = h.get_user_state().get("checklist")
    st = st if isinstance(st, dict) else {}
    # one "Stock your inventory" became a step per place: its tick carries over to the pantry
    for k in ("done", "hidden"):
        if isinstance(st.get(k), list) and "inventory" in st[k]:
            st[k] = [x for x in st[k] if x != "inventory"] + (["inv_pantry"] if k == "done" and "inv_pantry" not in st[k] else [])
    if isinstance(st.get("renamed"), dict):
        st["renamed"].pop("inventory", None)
    return {"done": [x for x in st.get("done", []) if isinstance(x, str)][:50],
            "hidden": [x for x in st.get("hidden", []) if isinstance(x, str)][:50],
            "renamed": {k: v for k, v in (st.get("renamed") or {}).items() if isinstance(v, str)} if isinstance(st.get("renamed"), dict) else {},
            "custom": [x for x in st.get("custom", []) if isinstance(x, dict) and isinstance(x.get("id"), str)][:30],
            "dismissed": bool(st.get("dismissed"))}


def checklist_view(h):
    st, auto = _checklist_state(h), checklist_auto(h.user)
    items = [{"id": i, "title": st["renamed"].get(i) or t, "default_title": t, "link": link, "custom": False}
             for i, t, link in CHECKLIST]
    items += [{"id": x["id"], "title": str(x.get("title") or "")[:80], "default_title": "", "link": x.get("link") or "",
               "custom": True} for x in st["custom"]]
    for it in items:
        it["auto"] = it["id"] in auto
        it["done"] = it["auto"] or it["id"] in st["done"]
        it["hidden"] = it["id"] in st["hidden"]
    shown = [it for it in items if not it["hidden"]]
    n = sum(1 for it in shown if it["done"])
    return {"items": items, "done": n, "total": len(shown), "complete": bool(shown) and n == len(shown),
            "dismissed": st["dismissed"]}


def checklist_action(h, b):
    st = _checklist_state(h)
    act, iid = b.get("action"), str(b.get("id") or "")[:40]
    known = {i for i, _, _ in CHECKLIST} | {x["id"] for x in st["custom"]}
    title = re.sub(r"\s+", " ", str(b.get("title") or "")).strip()[:80]
    if act in ("tick", "untick", "hide", "unhide", "rename", "remove") and iid not in known:
        raise ApiError(404, "That checklist item is gone.")
    if act == "tick" and iid not in st["done"]:
        st["done"].append(iid)
    elif act == "untick":
        st["done"] = [x for x in st["done"] if x != iid]
    elif act == "hide" and iid not in st["hidden"]:
        st["hidden"].append(iid)
    elif act == "unhide":
        st["hidden"] = [x for x in st["hidden"] if x != iid]
    elif act == "rename":
        custom = next((x for x in st["custom"] if x["id"] == iid), None)
        if custom is not None:
            if not title:
                raise ApiError(400, "Give it a name.")
            custom["title"] = title
        elif title:
            st["renamed"][iid] = title
        else:
            st["renamed"].pop(iid, None)   # blank: back to the default name
    elif act == "add":
        if not title:
            raise ApiError(400, "Give it a name.")
        link = str(b.get("link") or "").strip()
        if link and not CHECKLIST_LINK.fullmatch(link):
            raise ApiError(400, "Links go to a TablePlan page, like #recipes or settings:notify.")
        if len(st["custom"]) >= 30:
            raise ApiError(400, "That's a lot of checklist items. Remove some first.")
        st["custom"].append({"id": "c" + secrets.token_hex(4), "title": title, "link": link})
    elif act == "remove":
        if not any(x["id"] == iid for x in st["custom"]):
            raise ApiError(400, "Built-in items can be hidden, not removed.")
        st["custom"] = [x for x in st["custom"] if x["id"] != iid]
        st["done"] = [x for x in st["done"] if x != iid]
    elif act == "dismiss":
        if not checklist_view(h)["complete"]:
            raise ApiError(400, "Finish or hide the remaining items first.")
        st["dismissed"] = True
    elif act == "restore":
        st["dismissed"] = False
    else:
        raise ApiError(400, "Unknown checklist action.")
    h.put_user_state({"checklist": st})


def auth_required():
    return bool(cfg("app_password_hash")) or PUBLIC_MODE or users_exist()


def password_ok(pw):
    if not isinstance(pw, str) or len(pw) > 1024:
        return False
    if cfg("app_password_hash"):
        return check_password(pw, cfg("app_password_hash"))
    code = re.sub(r"[\s-]+", "", pw).upper()
    return PUBLIC_MODE and hmac.compare_digest(code.encode(), SETUP_CODE.encode())


_login_fails = {}
_login_lock = threading.Lock()
LOGIN_FAILS_PER_IP = 8          # per 10 minutes
LOGIN_FAILS_GLOBAL = 60         # per 10 minutes, across all addresses (slows distributed guessing)


def _recent_fails(now):
    for ip in list(_login_fails):
        fails = [t for t in _login_fails[ip] if now - t < 600]
        if fails:
            _login_fails[ip] = fails
        else:
            del _login_fails[ip]


LOGIN_FAILS_PER_ACCOUNT = 8     # per 10 minutes, from any address (a 6-digit PIN can't be walked through)


def login_throttled(ip, account=None):
    now = time.time()
    with _login_lock:
        _recent_fails(now)
        total = sum(len(v) for k, v in _login_fails.items() if not str(k).startswith("acct:"))
        return (len(_login_fails.get(ip, [])) >= LOGIN_FAILS_PER_IP or total >= LOGIN_FAILS_GLOBAL
                or (account is not None and len(_login_fails.get(f"acct:{account}", [])) >= LOGIN_FAILS_PER_ACCOUNT))


def login_failed(ip, account=None):
    with _login_lock:
        _login_fails.setdefault(ip, []).append(time.time())
        if account is not None:
            _login_fails.setdefault(f"acct:{account}", []).append(time.time())


def login_succeeded(ip, account=None):
    with _login_lock:
        _login_fails.pop(ip, None)
        if account is not None:
            _login_fails.pop(f"acct:{account}", None)


# ---- per-client rate limits for expensive work (imports, AI, outbound fetches) in public mode

_rate = {}
_rate_lock = threading.Lock()
RATE_LIMITS = {   # bucket: (requests, per seconds)
    "import": (20, 3600),
    "ai": (60, 3600),
    "fetch": (300, 3600),
}


def rate_ok(bucket, ip):
    if not PUBLIC_MODE:
        return True
    limit, window = RATE_LIMITS[bucket]
    now = time.time()
    with _rate_lock:
        if len(_rate) > 5000:   # bound memory
            for k in [k for k, v in _rate.items() if not v or now - v[-1] > window]:
                del _rate[k]
        hits = [t for t in _rate.get((bucket, ip), []) if now - t < window]
        if len(hits) >= limit:
            _rate[(bucket, ip)] = hits
            return False
        hits.append(now)
        _rate[(bucket, ip)] = hits
        return True


# Heavy imports (page scraping, video download + transcription, AI) run a few at a time.
_heavy = threading.BoundedSemaphore(int(env("TABLEPLAN_MAX_IMPORTS", "3") or 3))
# Background follow-up work (AI step-by-step prep, photo lookups) runs on a small fixed pool.
_bg_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tp-bg")


def background(fn, *a):
    _bg_pool.submit(_safe, fn, *a)


# ============================================================ USDA FoodKeeper

METRIC_DAYS = {"day": 1, "days": 1, "week": 7, "weeks": 7, "month": 30, "months": 30, "year": 365, "years": 365}


def fk_days(row, prefix):
    """Min value of a FoodKeeper range, in days (conservative). None if not applicable."""
    mn, mx, metric = row.get(prefix + "_Min"), row.get(prefix + "_Max"), (row.get(prefix + "_Metric") or "")
    mult = METRIC_DAYS.get(str(metric).strip().lower())
    val = mn if mn not in (None, "", 0) else mx
    if not mult or val in (None, ""):
        return None
    try:
        return max(1, int(round(float(val) * mult)))
    except (TypeError, ValueError):
        return None


def parse_foodkeeper(doc):
    """Handles the official layout: {"sheets":[{"name":"Product","data":[[{"ID":1},{"Name":..}...],...]}]}."""
    sheets = doc.get("sheets") if isinstance(doc, dict) else doc
    if not isinstance(sheets, list):
        raise ValueError("unexpected FoodKeeper format")

    def rows(sheet_name):
        for s in sheets:
            if isinstance(s, dict) and str(s.get("name", "")).lower() == sheet_name.lower():
                for raw in s.get("data", []):
                    if isinstance(raw, list):
                        merged = {}
                        for cell in raw:
                            if isinstance(cell, dict):
                                merged.update(cell)
                        yield merged
                    elif isinstance(raw, dict):
                        yield raw

    cats = {}
    for c in rows("Category"):
        name = " / ".join(x for x in (c.get("Category_Name"), c.get("Subcategory_Name")) if x)
        cats[c.get("ID")] = name

    out = []
    for p in rows("Product"):
        name = (p.get("Name") or "").strip()
        if not name:
            continue
        sub = (p.get("Name_subtitle") or "").strip()
        r = {
            "usda_id": p.get("ID"),
            "name": f"{name}, {sub}" if sub else name,
            "keywords": (p.get("Keywords") or ""),
            "category": cats.get(p.get("Category_ID"), ""),
            "sealed_pantry": fk_days(p, "Pantry") or fk_days(p, "DOP_Pantry"),
            "sealed_fridge": fk_days(p, "Refrigerate") or fk_days(p, "DOP_Refrigerate"),
            "opened_pantry": fk_days(p, "Pantry_After_Opening"),
            "opened_fridge": fk_days(p, "Refrigerate_After_Opening"),
            "freezer": fk_days(p, "Freeze") or fk_days(p, "DOP_Freeze"),
            "thawed_fridge": fk_days(p, "Refrigerate_After_Thawing"),
            "tips": " ".join(t for t in (p.get("Pantry_tips"), p.get("Refrigerate_tips"), p.get("Freeze_Tips")) if t),
        }
        if not any(r[f] for f in RULE_FIELDS):
            continue
        r["default_location"] = guess_location(r)
        out.append(r)
    return out


def sync_usda(raw_bytes=None):
    if raw_bytes is None:
        local = os.path.join(DATA_DIR, "foodkeeper.json")
        if os.path.exists(local):
            raw_bytes = open(local, "rb").read()
        else:
            with _open(FOODKEEPER_URL, headers={"User-Agent": "Mozilla/5.0 (TablePlan self-hosted; FoodKeeper sync)",
                                                "Accept": "application/json"}, timeout=60, allow_private=True) as r:
                raw_bytes = _read_capped(r, 50_000_000, 300)
    rules = parse_foodkeeper(json.loads(raw_bytes.decode("utf-8-sig")))
    if len(rules) < 50:
        raise ValueError(f"FoodKeeper data looked incomplete ({len(rules)} products)")
    with db() as c:
        for r in rules:
            existing = c.execute("SELECT id FROM shelf_rules WHERE usda_id=?", (r["usda_id"],)).fetchone()
            if existing:
                c.execute(f"""UPDATE shelf_rules SET name=?, keywords=?, category=?, default_location=?,
                    {", ".join(f + "=?" for f in RULE_FIELDS)}, tips=? WHERE id=?""",
                          (r["name"], r["keywords"], r["category"], r["default_location"],
                           *[r[f] for f in RULE_FIELDS], r["tips"], existing["id"]))
            else:
                insert_rule(c, r, "usda")
    set_internal("usda_synced_at", datetime.now().isoformat(timespec="seconds"))
    log(f"USDA FoodKeeper synced: {len(rules)} products")
    return len(rules)


# ============================================================ food matching

STOP = set("""fresh organic large small medium whole boneless skinless of and or the a an
chopped diced sliced minced grated can cans jar jars bag bags oz ounce ounces lb lbs pound
pounds package packages pkg bottle bottles box boxes carton cartons pint quart gallon dozen
cup cups tbsp tsp tablespoon teaspoon g kg ml l pack bunch head clove cloves to taste for""".split())


def singular(w):
    if len(w) > 4 and w.endswith(("oes", "ches", "shes", "xes")):
        return w[:-2]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def tokens(text):
    words = re.findall(r"[a-z]+", (text or "").lower())
    return [singular(w) for w in words if w not in STOP and len(w) > 1]


def food_key(name):
    return " ".join(tokens(name))


SOURCE_BONUS = {"custom": 12, "usda": 4, "starter": 0}


def match_rule(c, name):
    key = food_key(name)
    if not key:
        return None
    m = c.execute("SELECT r.* FROM food_map f JOIN shelf_rules r ON r.id=f.rule_id WHERE f.food_key=?", (key,)).fetchone()
    if m:
        return m
    item_t = set(key.split())
    best, best_score = None, 0.0
    for r in c.execute("SELECT * FROM shelf_rules"):
        name_t = set(tokens(r["name"]))
        kw_phrases = [food_key(k) for k in (r["keywords"] or "").split(",") if k.strip()]
        score = 0.0
        if key == food_key(r["name"]) or key in kw_phrases:
            score = 100
        else:
            for ph in kw_phrases:
                ph_t = set(ph.split())
                if ph_t and ph_t <= item_t:            # whole keyword phrase appears in item name
                    score = max(score, 55 + 8 * len(ph_t))
            overlap = item_t & name_t
            if overlap:
                score = max(score, 45 * len(overlap) / len(item_t) + 25 * len(overlap) / max(1, len(name_t)))
        if score:
            score += SOURCE_BONUS.get(r["source"], 0)
        if score > best_score:
            best, best_score = r, score
    return best if best_score >= 40 else None


# ============================================================ expiration logic

def today():
    return date.today()


def iso(d):
    return d.isoformat() if d else None


def parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


MAX_RANGE_DAYS = 400


def date_range(start_raw, end_raw):
    """Start/end dates from a request, defaulting to a week, capped so one request can't loop over centuries."""
    start = parse_date(start_raw) or today()
    end = parse_date(end_raw) or start + timedelta(days=6)
    if end < start:
        end = start
    if (end - start).days > MAX_RANGE_DAYS:
        raise ApiError(400, f"Pick a range of at most {MAX_RANGE_DAYS} days.")
    return start, end


def sealed_days(rule, loc):
    if not rule:
        return None
    if loc == "freezer":
        return rule["freezer"]
    if loc == "fridge":
        return rule["sealed_fridge"] or rule["sealed_pantry"]
    return rule["sealed_pantry"]


def opened_days(rule, loc):
    if not rule:
        return None
    if loc == "freezer":
        return rule["freezer"]
    if loc == "fridge":
        return rule["opened_fridge"]
    return rule["opened_pantry"] or rule["opened_fridge"]


def event(c, item_id, action, detail=""):
    c.execute("INSERT INTO pantry_events(item_id, at, action, detail) VALUES (?,?,?,?)",
              (item_id, datetime.now().isoformat(timespec="seconds"), action, detail))


def parse_amount(text):
    """'1 pint' -> (1.0, 'pint'); '2 avocados' -> (2.0, ''); '½ cup' -> (0.5, 'cup'); no number -> (None, None)."""
    t = (text or "").strip()
    for k, v in _UFRAC.items():
        t = re.sub(rf"(\d)\s*{k}", rf"\1 {v}", t).replace(k, v)
    m = re.match(rf"^\s*{_QTY}\s*(fl\.?\s*oz\b|[A-Za-z]+\.?)?", t)
    if not m:
        return None, None
    try:
        q = _qty_val(m.group(1))
    except (ValueError, ZeroDivisionError):
        return None, None
    if not q or q <= 0:
        return None, None
    word = (m.group(2) or "").rstrip(".")
    u = n_units.normalize(word) if word else ""
    if word and n_units.dimension(u) is None:
        u = ""   # "2 avocados": a plain count
    return float(q), u


def add_pantry_item(c, name, location=None, package_date=None, quantity_text="", mealie_item_id=None,
                    qty=None, unit=None, food_id=None):
    """Stock an item. qty/unit, when known, are the amount bought (otherwise parsed from quantity_text)."""
    if qty is None and quantity_text:
        qty, unit = parse_amount(quantity_text)
    qty = float(qty) if qty is not None and float(qty) > 0 else None
    unit = n_units.normalize(unit) if qty is not None else None
    rule = match_rule(c, name)
    kind, place = split_place(location)
    loc = kind or (rule["default_location"] if rule else "fridge")
    t = today()
    pkg = parse_date(package_date)
    # Only dates we know: a printed/package date, or (going straight into the freezer) a freezer countdown.
    if pkg:
        exp, src = pkg, "package"
    elif loc == "freezer" and rule and rule["freezer"]:
        exp, src = t + timedelta(days=rule["freezer"]), "frozen"
    else:
        exp, src = None, "none"
    cur = c.execute(
        """INSERT INTO pantry_items(name, quantity_text, location, purchased_on, frozen_on, expires_on,
           expiry_source, rule_id, mealie_item_id, created_at, qty, unit, original_qty, food_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (name.strip(), quantity_text or "", loc, iso(t), iso(t) if loc == "freezer" else None, iso(exp), src,
         rule["id"] if rule else None, mealie_item_id, datetime.now().isoformat(timespec="seconds"), qty, unit, qty,
         food_id if food_id is not None else _food_id(c, name)))
    if place:
        c.execute("UPDATE pantry_items SET place=? WHERE id=?", (place, cur.lastrowid))
    event(c, cur.lastrowid, "added", f"{place or loc}; expires {iso(exp) or 'unknown'}")
    return cur.lastrowid


def pantry_row(c, item_id):
    return c.execute("SELECT * FROM pantry_items WHERE id=?", (item_id,)).fetchone()


def rule_for(c, item):
    return c.execute("SELECT * FROM shelf_rules WHERE id=?", (item["rule_id"],)).fetchone() if item["rule_id"] else None


def apply_pantry_action(c, item_id, body):
    item = pantry_row(c, item_id)
    if not item:
        raise ApiError(404, "Item not found")
    action = body.get("action")
    rule = rule_for(c, item)
    t = today()
    exp = parse_date(item["expires_on"])

    def opened_countdown(when):
        """Opening starts a countdown (after-opening shelf life); a sooner printed or typed date still wins."""
        od = opened_days(rule, item["location"])
        cd = when + timedelta(days=od) if od else None
        if exp and item["expiry_source"] in ("package", "manual") and (cd is None or exp < cd):
            return exp, item["expiry_source"]
        return (cd, "opened") if cd else (exp if item["expiry_source"] in ("package", "manual") else None,
                                          item["expiry_source"] if item["expiry_source"] in ("package", "manual") else "none")

    if action in ("use", "fill"):
        try:
            left = float(body.get("left", 0))
        except (TypeError, ValueError):
            raise ApiError(400, "How much is left?")
        left = max(0.0, min(1.0, left))
        if left <= 0.001:
            c.execute("UPDATE pantry_items SET amount_left=0, status='used', finished_on=? WHERE id=?", (iso(t), item_id))
            event(c, item_id, "finished")
            return
        updates = {"amount_left": left}
        if item["qty"] is not None or item["original_qty"] is not None:
            full = item["original_qty"] or item["qty"]
            updates["qty"] = round(left * full, 4)   # keep the known amount in step
            updates["original_qty"] = full
        if left < 0.999 and not item["opened_on"] and item["location"] != "freezer":
            updates["opened_on"] = iso(t)
            new_exp, src = opened_countdown(t)
            updates["expires_on"], updates["expiry_source"] = iso(new_exp), src
        elif action == "fill" and left >= 0.999 and item["opened_on"] == iso(t) and item["expiry_source"] in ("opened", "none"):
            # set back to Full right after scanning: it isn't open after all
            updates.update(opened_on=None, expires_on=None, expiry_source="none")
        sets = ", ".join(f"{k}=?" for k in updates)
        c.execute(f"UPDATE pantry_items SET {sets} WHERE id=?", (*updates.values(), item_id))
        event(c, item_id, "used", f"{round(left * 100)}% left; expires {updates.get('expires_on', item['expires_on'])}")

    elif action == "open":
        if item["opened_on"]:
            return
        new_exp, src = opened_countdown(t)
        c.execute("UPDATE pantry_items SET opened_on=?, expires_on=?, expiry_source=? WHERE id=?", (iso(t), iso(new_exp), src, item_id))
        event(c, item_id, "opened", f"expires {iso(new_exp)}")

    elif action == "move":
        loc, place = split_place(body.get("location"))
        if loc is None:
            raise ApiError(400, "Bad location")
        if place != item["place"]:
            c.execute("UPDATE pantry_items SET place=? WHERE id=?", (place, item_id))
        if loc == item["location"]:
            return
        kept = exp if item["expiry_source"] in ("package", "manual") else None
        new_exp, src, frozen_on = kept, item["expiry_source"] if kept else "none", item["frozen_on"]
        if loc == "freezer":   # freezing starts a freezer countdown
            fz = rule["freezer"] if rule else None
            new_exp, src = (t + timedelta(days=fz), "frozen") if fz else (kept, src)
            frozen_on = iso(t)
        elif item["location"] == "freezer":   # thawing: the after-thawing window (falls back to after-opening)
            th = (rule["thawed_fridge"] or rule["opened_fridge"]) if rule else None
            new_exp, src = (t + timedelta(days=th), "opened") if th else (kept, src)
            frozen_on = None
        elif item["opened_on"]:   # opened, pantry <-> fridge: the countdown for the new place
            d = opened_days(rule, loc)
            if d:
                cand = parse_date(item["opened_on"]) + timedelta(days=d)
                new_exp, src = (min(kept, cand), item["expiry_source"]) if kept and kept < cand else (cand, "opened")
        c.execute("UPDATE pantry_items SET location=?, frozen_on=?, expires_on=?, expiry_source=? WHERE id=?",
                  (loc, frozen_on, iso(new_exp), src, item_id))
        event(c, item_id, "moved", f"to {loc}; expires {iso(new_exp)}")

    elif action == "rule":
        rid = body.get("rule_id")
        r = c.execute("SELECT * FROM shelf_rules WHERE id=?", (rid,)).fetchone() if rid else None
        if rid and not r:
            raise ApiError(404, "Rule not found")
        key = food_key(item["name"])
        if r:
            c.execute("INSERT INTO food_map(food_key, rule_id) VALUES (?,?) ON CONFLICT(food_key) DO UPDATE SET rule_id=excluded.rule_id",
                      (key, r["id"]))
        # Countdowns (opened / frozen) follow the new rule; printed and typed dates are kept; sealed items get no guess.
        new_exp, src = exp, item["expiry_source"]
        if src not in ("package", "manual"):
            if item["location"] == "freezer" and item["frozen_on"]:
                d = r["freezer"] if r else None
                new_exp, src = (parse_date(item["frozen_on"]) + timedelta(days=d), "frozen") if d else (None, "none")
            elif item["opened_on"]:
                d = opened_days(r, item["location"])
                new_exp, src = (parse_date(item["opened_on"]) + timedelta(days=d), "opened") if d else (None, "none")
            else:
                new_exp, src = None, "none"
        c.execute("UPDATE pantry_items SET rule_id=?, expires_on=?, expiry_source=? WHERE id=?",
                  (r["id"] if r else None, iso(new_exp), src, item_id))
        event(c, item_id, "rule", r["name"] if r else "none")

    elif action == "set_date":
        d = parse_date(body.get("expires_on"))
        kind = "package" if body.get("source") == "package" else "manual"
        c.execute("UPDATE pantry_items SET expires_on=?, expiry_source=? WHERE id=?",
                  (iso(d), kind if d else "none", item_id))
        event(c, item_id, "date set", iso(d) or "cleared")

    elif action == "rename":
        name = (body.get("name") or "").strip()
        if name:
            c.execute("UPDATE pantry_items SET name=?, quantity_text=? WHERE id=?",
                      (name, body.get("quantity_text", item["quantity_text"]), item_id))

    elif action == "amount":
        raw = body.get("qty")
        if raw in (None, ""):
            c.execute("UPDATE pantry_items SET qty=NULL, unit=NULL, original_qty=NULL WHERE id=?", (item_id,))
            event(c, item_id, "amount", "cleared")
            return
        try:
            q = float(raw)
        except (TypeError, ValueError):
            raise ApiError(400, "Type the amount as a number.")
        if not 0 <= q <= 1e6:
            raise ApiError(400, "That amount doesn't look right.")
        unit = n_units.normalize(_s(body.get("unit"), 20))
        if unit and n_units.dimension(unit) is None:
            raise ApiError(400, "Pick a unit from the list.")
        orig = item["original_qty"]
        if orig is None or n_units.normalize(item["unit"]) != unit or q > orig:
            orig = q
        left = max(0.0, min(1.0, q / orig)) if orig else 0.0
        c.execute("UPDATE pantry_items SET qty=?, unit=?, original_qty=?, amount_left=? WHERE id=?",
                  (q, unit, orig or None, left, item_id))
        event(c, item_id, "amount", n_units.fmt(q, unit))

    elif action == "toss":
        c.execute("UPDATE pantry_items SET status='tossed', finished_on=? WHERE id=?", (iso(t), item_id))
        event(c, item_id, "tossed")

    elif action == "still_good":   # "Still good": looked at it today, so it isn't stale (dates are changed with set_date)
        event(c, item_id, "still good")

    elif action == "restore":
        c.execute("UPDATE pantry_items SET status='active', finished_on=NULL, amount_left=CASE WHEN amount_left<=0 THEN 1 ELSE amount_left END WHERE id=?", (item_id,))
        event(c, item_id, "restored")

    elif action == "delete":
        c.execute("DELETE FROM pantry_items WHERE id=?", (item_id,))
    else:
        raise ApiError(400, "Unknown action")


def _span(days):
    return f"{days} day{'s' if days != 1 else ''}" if days < 14 else f"{round(days / 7)} weeks" if days < 60 else f"{round(days / 30)} months"


def expiry_label(row, exp, t):
    """How the date is known: a printed date, or a countdown from opening or freezing. None when there's no date."""
    if not exp:
        return None
    d = (exp - t).days
    when = "past due" if d < 0 else "use today" if d == 0 else f"use within {_span(d)}"
    if row["expiry_source"] == "opened":
        return f"Opened · {when}"
    if row["expiry_source"] == "frozen":
        return f"Frozen · {when}"
    return f"Use by {exp.strftime('%b')} {exp.day}"


def keeps_hint(rule, row):
    """Shelf-life knowledge as a hint, never as a date: 'Usually keeps ~2 weeks after opening'."""
    if not rule:
        return None
    d = opened_days(rule, row["location"]) if row["location"] != "freezer" else rule["freezer"]
    if not d:
        return None
    return f"Usually keeps ~{_span(d)} {'in the freezer' if row['location'] == 'freezer' else 'after opening'}"


BARE_CODE = re.compile(r"\d{8,14}")


def _migrate_barcode_names(c):
    """Older unknown scans were saved with the barcode as their name. They become review placeholders:
    "Unknown item · <code>", with the code kept in upc, so Review later can name them."""
    for r in c.execute("SELECT id, name, upc FROM pantry_items WHERE status='active' AND food_id IS NULL").fetchall():
        name = (r["name"] or "").strip()
        if BARE_CODE.fullmatch(name):
            c.execute("UPDATE pantry_items SET name=?, upc=COALESCE(NULLIF(upc,''), ?), review=1 WHERE id=?",
                      (f"Unknown item · {name}", name, r["id"]))


def pantry_display_name(name):
    """Never a bare barcode as a title."""
    n = (name or "").strip()
    return f"Unknown item · {n}" if BARE_CODE.fullmatch(n) else name


def pantry_json(c, row):
    t = today()
    exp = parse_date(row["expires_on"])
    rule = rule_for(c, row)
    return {
        "id": row["id"], "name": pantry_display_name(row["name"]), "quantity_text": row["quantity_text"],
        "location": row["location"], "amount_left": row["amount_left"],
        "review": bool(row["review"]), "place": row["place"], "place_label": (places().get(row["place"]) or {}).get("label") if row["place"] else None,
        "purchased_on": row["purchased_on"], "opened_on": row["opened_on"], "frozen_on": row["frozen_on"],
        "expires_on": row["expires_on"], "expiry_source": row["expiry_source"],
        "days_left": (exp - t).days if exp else None, "status": row["status"], "emoji": food_emoji(row["name"]),
        "expiry_label": expiry_label(row, exp, t), "keeps_hint": keeps_hint(rule, row),
        "qty": row["qty"], "unit": row["unit"] or "", "left_text": pantry_left_text(row),
        "product": row["product"] or "", "upc": row["upc"] or "", "food_id": row["food_id"],
        **_reserved(c, row),
        "image": f"/img/pantry/{row['id']}?v={urllib.parse.quote(row['image'])}" if row["image"] else None,
        "image_cut": bool(row["image"]) and _pantry_original(row["id"]) is not None,
        "full_qty": row["original_qty"] if row["original_qty"] is not None else (row["qty"] / row["amount_left"] if row["qty"] is not None and row["amount_left"] else None),
        "rule": {"id": rule["id"], "name": rule["name"], "source": rule["source"],
                 **{f: rule[f] for f in RULE_FIELDS}, "tips": rule["tips"]} if rule else None,
    }


def _reserved(c, row):
    """What planned meals have set aside from this item: reserved [{qty_text, date, recipe}] and the free amount."""
    res = []
    for a in c.execute("SELECT a.qty, a.unit, m.date, r.name FROM allocations a JOIN meal_plans m ON m.id=a.plan_entry_id "
                       "LEFT JOIN recipes r ON r.id=m.recipe_id WHERE a.pantry_item_id=? ORDER BY m.date", (row["id"],)):
        res.append({"qty_text": n_units.fmt(a["qty"], a["unit"]) if a["qty"] else "", "date": a["date"], "recipe": a["name"] or ""})
    free = None
    if row["qty"] is not None:
        used = sum(float(a["qty"] or 0) for a in c.execute("SELECT qty FROM allocations WHERE pantry_item_id=?", (row["id"],)))
        left = max(0.0, row["qty"] - used)
        free = (n_units.fmt(left, row["unit"]) if left > 1e-9 else "none") if used else None
    return {"reserved": res, "free_text": free}


def pantry_bulk(b):
    """POST /api/pantry/bulk {ids, action, location?, expires_on?}: one change for many inventory items.
    delete is soft (status 'deleted', so Undo can restore it); purge removes deleted rows for good."""
    ids = b.get("ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 1000:
        raise ApiError(400, "Pick at least one item.")
    ids = [_int_id(x, "item") for x in ids]
    action = b.get("action")
    if action not in ("delete", "restore", "purge", "move", "used", "set_date"):
        raise ApiError(400, "Unknown action.")
    n = 0
    t = iso(today())
    with db() as c:
        for pid in ids:
            r = pantry_row(c, pid)
            if not r:
                continue
            if action == "delete" and r["status"] != "deleted":
                c.execute("UPDATE pantry_items SET status='deleted', finished_on=? WHERE id=?", (t, pid))
                event(c, pid, "deleted", r["status"])
            elif action == "restore" and r["status"] == "deleted":
                prev = c.execute("SELECT detail FROM pantry_events WHERE item_id=? AND action='deleted' ORDER BY id DESC LIMIT 1",
                                 (pid,)).fetchone()
                status = prev["detail"] if prev and prev["detail"] in ("active", "used", "tossed") else "active"
                c.execute("UPDATE pantry_items SET status=?, finished_on=CASE WHEN ?='active' THEN NULL ELSE finished_on END WHERE id=?",
                          (status, status, pid))
                event(c, pid, "restored")
            elif action == "purge" and r["status"] == "deleted":
                c.execute("DELETE FROM pantry_items WHERE id=?", (pid,))
            elif action == "move" and r["status"] == "active":
                apply_pantry_action(c, pid, {"action": "move", "location": b.get("location")})
            elif action == "used" and r["status"] == "active":
                apply_pantry_action(c, pid, {"action": "use", "left": 0})
            elif action == "set_date" and r["status"] == "active":
                apply_pantry_action(c, pid, {"action": "set_date", "expires_on": b.get("expires_on"), "source": b.get("source")})
            else:
                continue
            n += 1
        # anything deleted more than a day ago (Undo is long over) is purged for good
        old = iso(today() - timedelta(days=1))
        c.execute("DELETE FROM pantry_items WHERE status='deleted' AND finished_on<?", (old,))
    return {"ok": True, "changed": n}


def pantry_left_text(row):
    """'1 cup left' when the amount is known, else '50% left'."""
    if row["qty"] is not None:
        return n_units.fmt(row["qty"], row["unit"]) + " left"
    return f"{round((row['amount_left'] or 0) * 100)}% left"


def list_pantry(c, status="active"):
    rows = c.execute(
        """SELECT * FROM pantry_items WHERE status=? ORDER BY
           CASE WHEN expires_on IS NULL THEN 1 ELSE 0 END, expires_on, name COLLATE NOCASE""", (status,)).fetchall()
    return [pantry_json(c, r) for r in rows]


EXPIRING_SOON_DAYS = 3    # "Use soon": expires within this many days
STALE_DAYS = 21           # "Stale": nobody has touched it in 3 weeks (not counting the freezer)


def expiry_segment(days_left, location, touched_days):
    """Which Expiring segment an active item belongs in: expired | soon | stale | None."""
    if days_left is not None and days_left < 0:
        return "expired"
    if days_left is not None and days_left <= EXPIRING_SOON_DAYS:
        return "soon"
    if location != "freezer" and touched_days is not None and touched_days >= STALE_DAYS:
        return "stale"
    return None


def expiring_view():
    """GET /api/pantry/expiring: {expired, soon, stale} (each a list of items, with touched_days), soonest first."""
    t = today()
    out = {"expired": [], "soon": [], "stale": []}
    with db() as c:
        touched = {r[0]: r[1] for r in c.execute("SELECT item_id, MAX(at) FROM pantry_events WHERE item_id IS NOT NULL GROUP BY item_id")}
        for r in c.execute("SELECT * FROM pantry_items WHERE status='active' ORDER BY "
                           "CASE WHEN expires_on IS NULL THEN 1 ELSE 0 END, expires_on, name COLLATE NOCASE"):
            exp = parse_date(r["expires_on"])
            last = max(filter(None, (parse_date((touched.get(r["id"]) or "")[:10]), parse_date(r["purchased_on"]),
                                     parse_date((r["created_at"] or "")[:10]))), default=None)
            td = (t - last).days if last else None
            seg = expiry_segment((exp - t).days if exp else None, r["location"], td)
            if seg:
                out[seg].append({**pantry_json(c, r), "touched_days": td})
    out["stale"].sort(key=lambda i: -(i["touched_days"] or 0))
    out["counts"] = {k: len(v) for k, v in out.items()}
    return out


def expiring_items(c, window):
    limit = iso(today() + timedelta(days=window))
    rows = c.execute("""SELECT * FROM pantry_items WHERE status='active' AND expires_on IS NOT NULL
                        AND expires_on<=? ORDER BY expires_on""", (limit,)).fetchall()
    return [pantry_json(c, r) for r in rows]


# ============================================================ Mealie client

class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def _s(v, max_len=None):
    """A request field as text: None -> "", anything that isn't a string -> 400."""
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ApiError(400, "Expected text.")
    if max_len is not None and len(v) > max_len:
        raise ApiError(400, f"That's too long ({max_len} characters max).")
    return v


def _q(s):
    """Quote one URL path segment (a slash or '..' in a slug can't reach another API path)."""
    return urllib.parse.quote(str(s or ""), safe="")


UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def mealie_raw(method, path, body=None, token=None, form=None, multipart=None, timeout=25, base=None):
    """Low-level Mealie call. body=JSON, form=urlencoded dict, multipart=(fields, files)."""
    base = (base or cfg("mealie_url")).rstrip("/")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif multipart is not None:
        boundary = "----tableplan" + base64.b16encode(os.urandom(8)).decode()
        fields, files = multipart
        parts = []
        for k, v in fields.items():
            if v is None:
                continue
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for k, fname, ctype, blob in files:
            safe = re.sub(r'[^A-Za-z0-9._-]', '_', fname or "image")
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{safe}"\r\n'
                         f'Content-Type: {ctype}\r\n\r\n'.encode() + blob + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    try:
        # Mealie is an admin-configured service, usually on the home network, so private addresses are allowed.
        with _open(base + path, data=data, method=method, headers=headers, timeout=timeout, allow_private=True) as r:
            raw = _read_capped(r, 200_000_000, max(timeout, 300))
            try:
                return json.loads(raw) if raw else None
            except ValueError:
                return raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read()[:600].decode("utf-8", "replace")
        try:
            dj = json.loads(detail)
            d = dj.get("detail", dj)
            if isinstance(d, dict):
                d = d.get("message") or d.get("error") or json.dumps(d)
            elif isinstance(d, list):
                d = "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in d)
            detail = str(d)
        except ValueError:
            pass
        raise MealieHTTPError(e.code, detail)
    except BlockedURL as e:
        raise ApiError(400, f"That Mealie address can't be used ({e}).")
    except urllib.error.URLError as e:
        raise ApiError(502, f"Can't reach Mealie at {base} ({e.reason}). Is the Mealie container running?")
    except (TimeoutError, OSError) as e:
        raise ApiError(504, f"Mealie took too long to answer ({e}).")


class MealieHTTPError(ApiError):
    def __init__(self, code, detail):
        super().__init__(502, f"Mealie error {code}: {detail}")
        self.code, self.detail = code, detail


def mealie(method, path, body=None, timeout=25, **kw):
    if NATIVE:
        return native_api(method, path, body, kw.get("multipart"))
    token = cfg("mealie_token")
    if not token:
        raise ApiError(503, "TablePlan isn't connected to Mealie yet — open Settings → Mealie to finish setup.")
    try:
        return mealie_raw(method, path, body=body, token=token, timeout=timeout, **kw)
    except MealieHTTPError as e:
        if e.code in (401, 403):
            raise ApiError(502, "Mealie rejected TablePlan's token — reconnect in Settings → Mealie.")
        raise ApiError(502, f"Mealie {method} {path.split('?')[0]} failed ({e.code}): {e.detail}")


_recipe_cache = {"at": 0, "items": []}
_recipe_lock = threading.Lock()

# ============================================================ native backend (replaces Mealie)
# Answers the subset of Mealie's REST API TablePlan uses, from TablePlan's own SQLite + image files,
# so the rest of the server is backend-agnostic. TABLEPLAN_BACKEND=mealie keeps the old behaviour.

sys.path.insert(0, HERE) if HERE not in sys.path else None  # python -I omits the script dir
from native import lists as n_lists, plans as n_plans, recipes as n_recipes, scraper as n_scraper  # noqa: E402
from native import units as n_units  # noqa: E402
from native import foods as n_foods  # noqa: E402
from native import plu as n_plu  # noqa: E402
from native import timers as n_timers  # noqa: E402
from native import eta as n_eta  # noqa: E402
from native import users as n_users  # noqa: E402
from native import dupes as n_dupes  # noqa: E402
from native import barcodes as n_barcodes
from native import whatcan as n_whatcan
from native import prices as n_prices
from native import checkin as n_checkin
from native import imgmeta as n_imgmeta
from native import ideas as n_ideas
from native import pans as n_pans
from native import alerts as n_alerts  # noqa: E402
from native import catalog as n_catalog  # noqa: E402

AISLES = [
    ("Produce", "apple banana lemon lime orange berr grape peach pear mango avocado tomato potato onion garlic shallot carrot celery "
                "pepper lettuce spinach kale cabbage broccoli cauliflower cucumber zucchini squash corn mushroom herb basil cilantro "
                "parsley thyme rosemary mint dill ginger scallion leek jalapeno salad greens arugula"),
    ("Meat & Seafood", "chicken beef pork bacon sausage ham turkey steak lamb ground salmon shrimp fish tuna cod tilapia crab scallop"),
    ("Dairy & Eggs", "milk cream butter cheese parmesan mozzarella cheddar yogurt egg sour cream half-and-half ricotta feta"),
    ("Bakery", "bread bun roll tortilla bagel pita baguette croissant"),
    ("Frozen", "frozen ice cream peas"),
    ("Spices", "salt pepper cumin paprika oregano cinnamon nutmeg chili powder spice seasoning bay leaf vanilla"),
    ("Pantry", "flour sugar rice pasta noodle spaghetti fettuccine penne oil vinegar sauce broth stock bean lentil oat cereal "
               "honey syrup peanut nut almond can tomato paste soy ketchup mustard mayo baking chocolate coffee tea"),
    ("Beverages", "juice soda water wine beer"),
    ("Household", "paper towel toilet soap detergent foil wrap bag trash sponge"),
]
_AISLE_RE = [(name, re.compile(r"\b(" + "|".join(re.escape(w) for w in words.split()) + r")", re.I)) for name, words in AISLES]


def aisle_for(text):
    t = (text or "").lower()
    if "frozen" in t:
        return "Frozen"
    for name, rx in _AISLE_RE:
        if rx.search(t):
            return name
    return None


def _lookup_summary(c, rid):
    r = n_recipes.get(c, rid)
    return {"id": r["id"], "name": r.get("name"), "slug": r.get("slug"), "has_image": bool(r.get("image")),
            "image_v": r.get("image") or ""} if r else None


def _ing_line(ing):
    return (ing.get("originalText") or ing.get("display") or ing.get("note") or "").strip()


def decode_content(raw, encoding, cap):
    """Undo gzip/deflate Content-Encoding, never inflating past `cap` bytes (decompression-bomb safe)."""
    if encoding in ("", "identity"):
        return raw
    if encoding in ("gzip", "x-gzip"):
        wbits_options = (16 + zlib.MAX_WBITS,)
    elif encoding == "deflate":
        wbits_options = (zlib.MAX_WBITS, -zlib.MAX_WBITS)   # zlib-wrapped, or raw deflate from some servers
    else:
        raise ApiError(502, f"That page uses an unsupported compression ({encoding[:20]}).")
    for wbits in wbits_options:
        try:
            d = zlib.decompressobj(wbits)
            out = d.decompress(raw, cap)   # truncated at cap, like an uncompressed page
            return out
        except zlib.error:
            continue
    raise ApiError(502, "That page's compressed content couldn't be read. Try a screenshot instead.")


def _fetch_page(url):
    if not re.match(r"^https?://", url or "") or not _public_host(url):
        raise ApiError(400, "That link can't be opened. Use a public https:// recipe page.")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate"}
    try:
        with _open(url, headers=headers, timeout=25) as r:
            final = r.geturl()
            encoding = (r.headers.get("Content-Encoding") or "").strip().lower()
            raw = _read_capped(r, 6_000_000, 60, truncate=not encoding)
            charset = r.headers.get_content_charset() or "utf-8"
        raw = decode_content(raw, encoding, 6_000_000)
    except BlockedURL:
        raise ApiError(400, "That link redirects somewhere TablePlan can't open.")
    except urllib.error.HTTPError as e:
        if e.code in (401, 402, 403, 429):
            raise ApiError(502, "That site blocked TablePlan from reading it. "
                                "Take screenshots of the recipe and use the Screenshot tab instead.")
        raise ApiError(502, f"The site returned an error ({e.code}). Try a screenshot instead.")
    except urllib.error.URLError as e:
        raise ApiError(502, f"Couldn't open that page ({e.reason}).")
    except (TimeoutError, OSError, http.client.HTTPException):
        raise ApiError(504, "That page took too long to load. Try again, or use a screenshot instead.")
    except ValueError:
        raise ApiError(502, "That page is too large to read. Try a screenshot instead.")
    try:
        return final, raw.decode(charset, errors="replace")
    except LookupError:   # unknown charset name from the server
        return final, raw.decode("utf-8", errors="replace")


AI_RECIPE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["found", "complete", "missing", "source_url", "name", "description", "servings", "prep_minutes", "cook_minutes", "total_minutes", "ingredients", "steps", "tags", "categories"],
    "properties": {
        "found": {"type": "boolean"}, "complete": {"type": "boolean"}, "missing": {"type": "string"}, "source_url": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"},
        "servings": {"type": "number"}, "prep_minutes": {"type": "integer"}, "cook_minutes": {"type": "integer"},
        "total_minutes": {"type": "integer"},
        "ingredients": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["section", "quantity_text", "name", "note"],
                                                    "properties": {"section": {"type": "string"}, "quantity_text": {"type": "string"},
                                                                   "name": {"type": "string"}, "note": {"type": "string"}}}},
        "steps": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
        "categories": {"type": "array", "items": {"type": "string"}},
    },
}


AI_DRAFT_SCHEMA = {**AI_RECIPE_SCHEMA,
    "required": AI_RECIPE_SCHEMA["required"] + ["title_found", "suggested_title", "questions"],
    "properties": {**AI_RECIPE_SCHEMA["properties"],
        "title_found": {"type": "boolean"}, "suggested_title": {"type": "string"},
        "questions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["kind", "text", "choices", "ingredient", "step", "page"],
            "properties": {"kind": {"type": "string", "enum": ["amount", "cutoff", "unreadable", "other"]}, "text": {"type": "string"},
                           "choices": {"type": "array", "items": {"type": "string"}},
                           "ingredient": {"type": "integer"}, "step": {"type": "integer"}, "page": {"type": "integer"}}}}}}
DRAFT_PROMPT = (
    " The images are pages photographed in order (page 1, page 2, …). If no recipe title is visible, set title_found=false, "
    "leave name empty and give suggested_title: a short, plain, descriptive name built from the ingredients and method "
    "(e.g. 'Garlic Butter Chicken Thighs'); never present it as the original title. Otherwise title_found=true and "
    "suggested_title empty. questions: only for real gaps a cook must fill, never invented: an ingredient with no amount "
    "where one is clearly needed (kind amount, ingredient = its 0-based index, choices = 2-4 common amounts), text cut off "
    "at a page edge or a missing part (kind cutoff, page = the page number, choices empty), a word you can't read (kind "
    "unreadable; write it as [?] in that ingredient or step and give 1-3 best guesses as choices; ingredient/step = its "
    "index). Use -1 for ingredient/step and 0 for page when they don't apply. With questions, still return everything "
    "you can read and set complete=true unless nothing usable is there.")


def _category_prompt():
    return ("categories: pick 1-2 that fit from exactly this list (copy the names exactly): "
            + "; ".join(get_settings()["categories"]) + ".")


def _pick_categories(names):
    """AI-suggested categories, keeping only (at most 2) names from the household's list."""
    known = {c.lower(): c for c in get_settings()["categories"]}
    out = []
    for n in names if isinstance(names, list) else []:
        c = known.get(" ".join(str(n).split()).lower()) if isinstance(n, str) else None
        if c and c not in out:
            out.append(c)
    return [{"name": c} for c in out[:2]]


def ing_line_from(x):
    """Rebuild one ingredient line from AI parts: {quantity_text, name, note} -> '1 ½ cups heavy cream, divided'.
    Also accepts the older {line} shape."""
    if not isinstance(x, dict):
        return ""
    if x.get("line") and not x.get("name"):
        return " ".join(str(x["line"]).split())
    qty, name, note = (" ".join(str(x.get(k) or "").split()) for k in ("quantity_text", "name", "note"))
    if not name:
        return qty
    low = qty.lower()
    if low in ("to taste", "as needed", "for serving", "for garnish", "optional"):
        line = f"{name} {qty}"
    elif low in _WORD_UNITS or low.rstrip("es") in _WORD_UNITS:
        line = f"{qty} of {name}"
    else:
        line = " ".join(v for v in (qty, name) if v)
    return line + (f", {note}" if note else "")


def ai_recipe(text, images=None, feature="recipe import", detail="", draft=False):
    """Turn free text and/or images into a recipe (Mealie-shaped dict) with OpenAI. draft=True (the scan queue) also
    returns the gaps as questions and a suggested name instead of refusing an incomplete page: (recipe, meta)."""
    if not cfg("openai_key"):
        raise ApiError(400, "This needs AI. Add your OpenAI key in Settings → AI recipe import.")
    content = [{"type": "text", "text": (
        "Extract the single recipe from the material below. Clean up typos, spacing and formatting, but never change the recipe: keep every amount, ingredient, temperature, time and step exactly. Give each ingredient as parts: "
        "quantity_text (the amount with its unit exactly as written, e.g. '1 1/2 cups', 'pinch', 'to taste', or empty), name (the clean food name, "
        "no amount, no 'of', e.g. 'heavy cream'), note (prep such as 'divided', 'minced', 'softened', or empty); put section headings in 'section' (empty if none). Steps are the instructions "
        "in order, one per item. source_url: the recipe's web address if one is visible (e.g. in a page header or footer), else empty. Use 0 for unknown numbers. If there is no recipe, set found=false. Never invent content: never add an ingredient, amount, time, temperature or step that isn't in the material. Set complete=false when part of the recipe is clearly missing: no ingredient list, no instructions, text cut off mid-list or mid-step (e.g. a second page or screenshot wasn't included), or steps that use ingredients the list doesn't include; then explain what's missing in 'missing' (one short sentence). Missing amounts in a spoken video recipe do not count as incomplete. " + _category_prompt())
        + (DRAFT_PROMPT if draft else "") + (f"\n\n{text[:30000]}" if text else "")}]
    for im in images or []:
        data = im.get("data") or ""
        if data.startswith("data:application/pdf"):
            content.append({"type": "file", "file": {"filename": im.get("name") or "recipe.pdf", "file_data": data}})
            continue
        if not data.startswith("data:image/"):
            data = "data:image/jpeg;base64," + data.split(",", 1)[-1]
        content.append({"type": "image_url", "image_url": {"url": data, "detail": "high"}})
    try:
        out = openai_chat([{"role": "user", "content": content}], "recipe", AI_DRAFT_SCHEMA if draft else AI_RECIPE_SCHEMA,
                          feature, detail)
    except AIUnreadable:
        content[0] = {"type": "text", "text": (
            "Extract the single recipe from the material below and reply in EXACTLY this plain-text format, nothing else:\n"
            "SOURCE: <web address shown in the material, or blank>\nTITLE: <name>\nDESCRIPTION: <one sentence or blank>\nSERVINGS: <number or 0>\nPREP: <minutes or 0>\n"
            "COOK: <minutes or 0>\nTOTAL: <minutes or 0>\nTAGS: <comma separated>\nINGREDIENTS:\n<one ingredient per line, amount first; "
            "a line starting with # is a section heading>\nSTEPS:\n<one step per line>\n"
            "Copy amounts exactly and never invent content: never add an ingredient or step that isn't in the material. If there is no recipe, reply only: NO RECIPE. If part of the recipe is clearly missing (no ingredients, no steps, or cut off), reply only: INCOMPLETE: <what's missing>")
            + (f"\n\n{text[:30000]}" if text else "")}
        out = parse_recipe_text(openai_text([{"role": "user", "content": content}], feature + " (text)", detail))
    meta = None
    if draft:
        qs = [q for q in out.get("questions") or [] if isinstance(q, dict) and q.get("text")][:12]
        if (out.get("complete") is False or out.get("incomplete")) and not any(q.get("kind") == "cutoff" for q in qs):
            qs.append({"kind": "cutoff", "text": out.get("missing") or out.get("incomplete") or "Part of the recipe seems to be missing.",
                       "choices": [], "ingredient": -1, "step": -1, "page": 0})
        meta = {"title_found": out.get("title_found", True) is not False and bool((out.get("name") or "").strip()),
                "suggested_title": title_case((out.get("suggested_title") or "").strip())[:80],
                "questions": [{"id": f"q{n + 1}", "kind": q.get("kind") if q.get("kind") in ("amount", "cutoff", "unreadable", "other") else "other",
                               "text": str(q.get("text"))[:240], "choices": [str(x)[:60] for x in (q.get("choices") or [])][:4],
                               "ingredient": int(q.get("ingredient", -1)) if isinstance(q.get("ingredient"), int) else -1,
                               "step": int(q.get("step", -1)) if isinstance(q.get("step"), int) else -1,
                               "page": int(q.get("page", 0)) if isinstance(q.get("page"), int) else 0} for n, q in enumerate(qs)]}
        out["complete"] = True
    if out.get("complete") is False or out.get("incomplete"):
        raise ApiError(422, "This recipe looks incomplete, so it wasn't saved: " + (out.get("missing") or out.get("incomplete") or "part of it is missing")
                       + " Add the missing part (another screenshot or the rest of the text) and try again.")
    if not out.get("found") or not (out.get("ingredients") or out.get("steps")):
        raise ApiError(422, "No recipe found there. Try a clearer screenshot that shows the ingredients and steps.")
    ings = [{"referenceId": str(uuid.uuid4()), "title": (x.get("section") or None), "note": ln, "display": ln,
             "originalText": ln, "quantity": 0, "unit": None, "food": None}
            for x in out["ingredients"] for ln in [ing_line_from(x)] if ln]
    last = None
    for g in ings:   # only the first line of a section carries its title
        g["title"], last = (g["title"] if g["title"] != last else None), g["title"] or last
    mins = lambda v: int(v) * 60 if v else None  # noqa: E731
    src = (out.get("source_url") or "").strip()
    recipe = {"name": (out["name"] or "") if draft else (out["name"] or "Untitled recipe"), "description": out.get("description") or "",
            "orgURL": src if re.match(r"^https?://", src) else "",
            "recipeServings": float(out.get("servings") or 0), "prepTimeSeconds": mins(out.get("prep_minutes")),
            "performTimeSeconds": mins(out.get("cook_minutes")),
            "totalTimeSeconds": mins(out.get("total_minutes")) or ((mins(out.get("prep_minutes")) or 0) + (mins(out.get("cook_minutes")) or 0)) or None,
            "recipeIngredient": ings,
            "recipeInstructions": [{"id": str(uuid.uuid4()), "title": "", "text": s, "ingredientReferences": []} for s in out["steps"] if s.strip()],
            "tags": [{"name": t} for t in (out.get("tags") or [])[:8]],
            "recipeCategory": _pick_categories(out.get("categories"))}
    return (recipe, meta) if draft else recipe


POLISH_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["description", "ingredients", "steps", "categories"],
    "properties": {
        "description": {"type": "string"}, "categories": {"type": "array", "items": {"type": "string"}},
        "ingredients": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["section", "quantity_text", "name", "note"],
                                                    "properties": {"section": {"type": "string"}, "quantity_text": {"type": "string"},
                                                                   "name": {"type": "string"}, "note": {"type": "string"}}}},
        "steps": {"type": "array", "items": {"type": "string"}},
    },
}
POLISH_PROMPT = (
    "You are editing a recipe for a home cook. Return the same recipe with clearer wording.\n"
    "- description: 1-2 appetizing, factual sentences about the dish.\n"
    "- ingredients: exactly the same number of items, in the same order, with the same section headings. Return each "
    "as parts: quantity_text (amount with unit, spelled out, e.g. '2 cups', '1 tablespoon', 'pinch', 'to taste'), name (clean "
    "food name, no amount and no 'of', e.g. 'all-purpose flour' for '2 c. flour'), note (prep like 'minced', 'divided').\n"
    "- steps: rewrite each step as clear, complete, descriptive sentences. Name the pan or vessel, the heat level, "
    "temperatures, times and doneness cues (e.g. 'until golden and 165°F inside') when the source gives them.\n"
    "NEVER change ingredients, amounts, temperatures, times or the order of the method. Never add or remove "
    "ingredients, and never add or remove actions in the steps. If the source lacks a detail, do not invent numbers; "
    "just write the sentence clearly. Keep section headings as they are.")
_NUM_TOKEN = re.compile(r"\d+(?:[.,/]\d+)?|[½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞]")


def _num_tokens(line):
    """Digit and fraction tokens of a line ('1 ½ cups' -> {'1', '1/2'}), to check a rewrite kept every number."""
    t = line or ""
    for k, v in _UFRAC.items():
        t = t.replace(k, " " + v)
    return set(_NUM_TOKEN.findall(t))


def _polish_on():
    return bool(cfg("openai_key")) and bool(get_settings().get("polish_imports", True))


REWORD_EXTRA = ("Reword for clarity only. Do not change the recipe. Don't make anything up, but use common sense to fill "
                "in obvious wording gaps (e.g. 'the pan', 'until done' -> a clear doneness cue) without adding new "
                "amounts, ingredients or temperatures.")


def polish_recipe(data, extra=""):
    """AI pass that rewrites a new import's steps and description clearly and tidies ingredient wording, without
    changing amounts. Keeps the originals in extras.original. Returns new data (the input when the polish is unsafe)."""
    ings = [g for g in data.get("recipeIngredient") or [] if _ing_line(g)]
    steps = [st for st in data.get("recipeInstructions") or [] if (st.get("text") or "").strip()]
    if not ings and not steps:
        return data
    orig_lines = [_ing_line(g) for g in ings]
    orig_steps = [st["text"].strip() for st in steps]
    section, sections = None, []
    for g in ings:
        section = g.get("title") or section
        sections.append(section or "")
    source = {"name": data.get("name") or "", "description": data.get("description") or "",
              "ingredients": [{"section": sec, "line": ln} for sec, ln in zip(sections, orig_lines)], "steps": orig_steps,
              }
    out = openai_chat([{"role": "system", "content": POLISH_PROMPT + "\n- " + _category_prompt()
                        + (("\n" + extra) if extra else "")},
                       {"role": "user", "content": json.dumps(source, ensure_ascii=False)}],
                      "recipe_polish", POLISH_SCHEMA, "polish", (data.get("name") or "")[:80])
    new_steps = [x.strip() for x in out.get("steps") or [] if isinstance(x, str) and x.strip()]
    if len(new_steps) < len(orig_steps) - 1 or not new_steps and orig_steps:
        log(f"polish discarded for {data.get('name')!r}: steps {len(orig_steps)} -> {len(new_steps)}")
        return data
    new_lines = [ing_line_from(x) for x in out.get("ingredients") or [] if isinstance(x, dict)]
    lines_ok = len(new_lines) == len(orig_lines) and all(
        nl and _num_tokens(ol) <= _num_tokens(nl) for ol, nl in zip(orig_lines, new_lines))
    if not lines_ok:
        log(f"polish kept the original ingredient lines for {data.get('name')!r} (count or numbers changed)")
    data = dict(data)
    if lines_ok:
        new_ings = []
        for g, line in zip(ings, new_lines):
            g = dict(g)
            g.update(note=line, display=line, originalText=line, quantity=0, unit=None, food=None)
            new_ings.append(g)
        data["recipeIngredient"] = new_ings
    data["recipeInstructions"] = [{"id": str(uuid.uuid4()), "title": "", "text": t, "ingredientReferences": []}
                                  for t in new_steps]
    if not data.get("recipeCategory"):
        cats = _pick_categories(out.get("categories"))
        if cats:
            data["recipeCategory"] = cats
    desc = (out.get("description") or "").strip()
    if desc:
        data["description"] = desc[:2000]
    extras = dict(data.get("extras") or {})
    if not isinstance(extras.get("original"), dict):   # repeated rewording keeps the true original
        extras["original"] = {"ingredients": orig_lines, "steps": orig_steps, "description": source["description"]}
    data["extras"] = extras
    return data


class DuplicateFound(ApiError):
    """A new import looks like a recipe we already have: it waits (as an import job) for Keep both / Replace / Cancel."""
    def __init__(self, job_id, data, matches):
        super().__init__(409, f"Looks like you already have “{matches[0]['name']}”.")
        self.extra = {"duplicate": True, "job": job_id, "matches": matches,
                      "new": {"name": data.get("name") or "", "url": data.get("orgURL") or "",
                              "ingredients": len(data.get("recipeIngredient") or [])}}


def recipe_index():
    """Every saved recipe as {id, slug, name, ingredients (lines), url, has_image}, for duplicate checks."""
    out = []
    with db() as c:
        for r in c.execute("SELECT id, slug, data FROM recipes"):
            try:
                d = json.loads(r["data"])
            except ValueError:
                continue
            out.append({"id": r["id"], "slug": r["slug"], "name": d.get("name") or "", "url": d.get("orgURL") or "",
                        "has_image": bool(d.get("image")),
                        "ingredients": [_ing_line(g) for g in d.get("recipeIngredient") or [] if _ing_line(g)]})
    return out


def find_dupes(data, exclude=()):
    new = {"name": data.get("name") or "", "url": data.get("orgURL") or "",
           "ingredients": [_ing_line(g) for g in data.get("recipeIngredient") or [] if _ing_line(g)]}
    return n_dupes.find(new, [r for r in recipe_index() if r["id"] not in exclude])


def _replace_recipe(slug, data, image_url=None):
    """Replace: new content into the existing recipe (same id and slug, so plans, diary, ratings and favourites stay);
    the old text goes to extras.versions so it can be restored."""
    with db() as c:
        rec = n_recipes.get(c, slug)
        if not rec:
            raise ApiError(404, "The recipe to replace is gone.")
        extras = dict(rec.get("extras") or {})
        old = _version_of(rec)
        old["label"] = "Before replacing with an import"
        extras["versions"] = (list(extras.get("versions") or []) + [old])[-20:]
        extras.pop("eta", None)
        for k, v in (data.get("extras") or {}).items():
            if k not in ("versions",):
                extras[k] = v
        new = dict(rec)
        for k in ("description", "recipeIngredient", "recipeInstructions", "recipeServings", "prepTimeSeconds", "performTimeSeconds",
                  "totalTimeSeconds", "orgURL", "tags", "recipeCategory"):
            if k in data:
                new[k] = data[k]
        new["extras"] = extras
        new = _annotate_foods(c, new)
        slug = n_recipes.update(c, rec["id"], new)
        invalidate_guided(c, rec["id"], slug)
        has_image = bool(rec.get("image"))
    if image_url and not has_image:
        try:
            blob, ctype = _fetch_image(image_url)
            with db() as c:
                n_recipes.save_image(IMG_DIR, rec["id"], blob, _ext(ctype), c=c)
        except Exception as e:
            log("recipe image skipped:", e)
    _recipe_cache["at"] = 0
    return slug


def _save_new_recipe(data, image_url=None, dup="check", replace=None):
    """Save an imported recipe. dup: "check" (pause with DuplicateFound when it looks like one we have), "keep" (save as
    another recipe, adding " (2)" only to an identical title) or "skip"; replace: slug to overwrite instead."""
    if NATIVE and dup == "check" and not replace:
        matches = find_dupes(dict(data, name=title_case(data.get("name") or "")))
        if matches:
            raise DuplicateFound(import_job_create("direct", "review", draft=data, image_url=image_url,
                                                   meta={"dups": matches}), data, matches)
    data = dict(data, name=title_case(data.get("name") or "") or "Untitled Recipe")
    if dup == "keep" and NATIVE:
        data["name"] = n_dupes.keep_both_name(data["name"], [r["name"] for r in recipe_index()])
    if replace:
        if _polish_on():
            try:
                data = polish_recipe(data)
            except Exception as e:
                log("recipe polish skipped:", getattr(e, "message", None) or e)
        return _replace_recipe(replace, data, image_url)
    if _polish_on():
        try:
            data = polish_recipe(data)
        except Exception as e:   # the import still succeeds, just unpolished
            log("recipe polish skipped:", getattr(e, "message", None) or e)
    classify = _food_classifier()
    data = _with_pan(data) if NATIVE else data
    with db() as c:
        data = _annotate_foods(c, dict(data), classify)
        slug = n_recipes.create(c, data.get("name") or "Untitled recipe", data)
        rid = n_recipes.get(c, slug)["id"]
    if image_url:
        try:
            blob, ctype = _fetch_image(image_url)
            with db() as c:
                n_recipes.save_image(IMG_DIR, rid, blob, _ext(ctype), c=c)
        except Exception as e:
            log("recipe image skipped:", e)
    _recipe_cache["at"] = 0
    return slug


# ============================================================ import queue (scan several recipes back to back)
# A job: pages (photos on disk) → AI draft → a quick look if anything needs the cook (suggested name, questions,
# possible duplicate) → saved. Jobs live in the database, so the queue survives a reload or a restart.
JOB_LABEL = {"waiting": "Waiting", "reading": "Reading", "review": "Needs a quick look", "done": "Done", "failed": "Failed",
             "cancelled": "Cancelled"}
MAX_PAGES = 8
_import_wake = threading.Event()


def _job_dir(job_id):
    return os.path.join(DATA_DIR, "import_pages", str(int(job_id)))


def _job_page_path(job_id, n):
    return os.path.join(_job_dir(job_id), f"{int(n)}.jpg")


def import_job_create(kind, status, draft=None, image_url=None, meta=None, user_id=None, pages=0):
    now = datetime.now().isoformat(timespec="seconds")
    with db() as c:
        return c.execute("INSERT INTO import_jobs(kind, status, user_id, pages, draft, image_url, meta, created_at, updated_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?)", (kind, status, user_id, pages, json.dumps(draft) if draft is not None else None,
                                                        image_url, json.dumps(meta or {}), now, now)).lastrowid


def _job_row(job_id):
    with db() as c:
        r = c.execute("SELECT * FROM import_jobs WHERE id=?", (int(job_id),)).fetchone()
    if not r:
        raise ApiError(404, "That import is gone.")
    return r


def _job_save(job_id, **f):
    f["updated_at"] = datetime.now().isoformat(timespec="seconds")
    for k in ("draft", "meta"):
        if k in f and not isinstance(f[k], (str, type(None))):
            f[k] = json.dumps(f[k])
    with db() as c:
        c.execute(f"UPDATE import_jobs SET {', '.join(f'{k}=?' for k in f)} WHERE id=?", (*f.values(), int(job_id)))


def _job_meta(r):
    try:
        m = json.loads(r["meta"] or "{}")
    except ValueError:
        m = {}
    return m if isinstance(m, dict) else {}


def _job_open_items(r, m):
    """What still needs the cook: the name, unanswered questions, a duplicate choice."""
    todo = []
    if m.get("suggested_title") and not m.get("name_ok"):
        todo.append("name")
    answers = m.get("answers") or {}
    todo += [q["id"] for q in m.get("questions") or [] if q["id"] not in answers]
    if m.get("dups") and not m.get("dup_choice"):
        todo.append("duplicate")
    return todo


def import_job_view(r):
    m = _job_meta(r)
    draft = json.loads(r["draft"]) if r["draft"] else {}
    status = r["status"]
    label = "Possible duplicate" if status == "review" and m.get("dups") and not m.get("dup_choice") and not m.get("questions") \
        and not (m.get("suggested_title") and not m.get("name_ok")) else JOB_LABEL.get(status, status)
    return {"id": r["id"], "kind": r["kind"], "status": status, "label": label, "pages": r["pages"],
            "page_urls": [f"/api/import/queue/{r['id']}/page/{n}" for n in range(1, r["pages"] + 1)],
            "name": draft.get("name") or m.get("suggested_title") or "", "suggested": bool(m.get("suggested_title")) and not draft.get("name"),
            "suggested_title": m.get("suggested_title") or "", "name_ok": bool(m.get("name_ok")),
            "questions": [{**q, "answered": q["id"] in (m.get("answers") or {})} for q in m.get("questions") or []],
            "dups": m.get("dups") or [], "dup_choice": m.get("dup_choice"),
            "ingredients": [_ing_line(g) for g in draft.get("recipeIngredient") or [] if _ing_line(g)][:40],
            "steps": [(x.get("text") or "") for x in draft.get("recipeInstructions") or []][:30],
            "url": draft.get("orgURL") or "", "todo": _job_open_items(r, m) if status == "review" else [],
            "error": r["error"], "slug": r["slug"], "created_at": r["created_at"], "updated_at": r["updated_at"]}


def import_queue_list():
    cutoff = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    with db() as c:
        rows = c.execute("SELECT * FROM import_jobs WHERE dismissed=0 AND status!='cancelled' AND (status!='done' OR updated_at>=?) "
                         "ORDER BY id DESC LIMIT 60", (cutoff,)).fetchall()
    jobs = [import_job_view(r) for r in rows]
    counts = {k: sum(1 for j in jobs if j["status"] == k) for k in ("waiting", "reading", "review", "failed", "done")}
    return {"jobs": jobs, "counts": counts}


def import_queue_add(b, user_id=None):
    """POST /api/import/queue {pages: [dataURL…]}: one recipe, its pages in order. Returns the job; reading happens later."""
    require_native()
    if not cfg("openai_key"):
        raise ApiError(400, "Scanning recipes needs AI. Add your OpenAI key in Settings → AI recipe import.")
    pages = b.get("pages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        raise ApiError(400, f"Send 1 to {MAX_PAGES} pages.")
    blobs = []
    for p in pages:
        if not isinstance(p, str) or not re.match(r"data:image/(jpeg|png|webp);base64,", p[:40]):
            raise ApiError(400, "Pages must be photos.")
        try:
            blob = base64.b64decode(p.split(",", 1)[1], validate=True)
        except (ValueError, IndexError):
            raise ApiError(400, "A page couldn't be read.")
        if not n_recipes.sniff_image(blob):
            raise ApiError(400, "A page isn't a photo.")
        blobs.append(blob)
    if sum(len(x) for x in blobs) > 25_000_000:
        raise ApiError(413, "Those pages are too large together (25 MB max).")
    jid = import_job_create("scan", "waiting", user_id=user_id, pages=len(blobs))
    os.makedirs(_job_dir(jid), exist_ok=True)
    for n, blob in enumerate(blobs, 1):
        with open(_job_page_path(jid, n), "wb") as f:
            f.write(blob)
    _import_wake.set()
    return import_job_view(_job_row(jid))


def _job_pages_data(jid, n):
    out = []
    for k in range(1, n + 1):
        with open(_job_page_path(jid, k), "rb") as f:
            out.append({"data": "data:image/jpeg;base64," + base64.b64encode(f.read()).decode(), "name": f"page{k}.jpg"})
    return out


def import_job_process(jid):
    r = _job_row(jid)
    if r["status"] != "waiting":
        return
    _job_save(jid, status="reading", error=None)
    try:
        data, meta = ai_recipe("", _job_pages_data(jid, r["pages"]), "scan import", f"{r['pages']} page(s)", draft=True)
    except ApiError as e:
        _job_save(jid, status="failed", error=e.message)
        return
    except Exception as e:   # never leave a job stuck in "reading"
        log("scan import failed:", e)
        _job_save(jid, status="failed", error="Something went wrong reading these pages. Try again.")
        return
    m = {"questions": meta["questions"], "answers": {}}
    if NATIVE and n_pans.needs_pan(_pan_texts(data)):
        m["questions"] = m["questions"] + [{"id": "pan", "kind": "pan", "text": "What size pan?", "ingredient": -1, "step": -1, "page": 0,
                                           "choices": ["9×13 in", "8×8 in", "9 in round", "9×5 in loaf", "12-cup muffin tin"]}]
    if not meta["title_found"] or not (data.get("name") or "").strip():
        data["name"] = ""
        m["suggested_title"] = meta["suggested_title"] or "Untitled Recipe"
    m["dups"] = find_dupes(dict(data, name=title_case(data.get("name") or m.get("suggested_title") or "")))
    _job_save(jid, draft=data, meta=m, status="review")
    import_job_finish(jid)


def _apply_answers(data, m):
    """Fold the cook's answers into the draft: amounts, words that couldn't be read, text that was cut off."""
    data = json.loads(json.dumps(data))
    ings, steps = data.get("recipeIngredient") or [], data.get("recipeInstructions") or []
    for q in m.get("questions") or []:
        a = (m.get("answers") or {}).get(q["id"])
        if not isinstance(a, str) or a == "" or a == "skip":
            continue
        a = " ".join(a.split())[:200]
        if q["kind"] == "amount" and 0 <= q["ingredient"] < len(ings):
            g = ings[q["ingredient"]]
            line = f"{a} {_ing_line(g)}".strip()
            g.update(note=line, display=line, originalText=line, quantity=0, unit=None, food=None)
        elif q["kind"] == "unreadable":
            if 0 <= q["ingredient"] < len(ings):
                g = ings[q["ingredient"]]
                line = _ing_line(g).replace("[?]", a, 1) if "[?]" in _ing_line(g) else _ing_line(g)
                g.update(note=line, display=line, originalText=line)
            elif 0 <= q["step"] < len(steps):
                steps[q["step"]]["text"] = steps[q["step"]]["text"].replace("[?]", a, 1)
        elif q["kind"] == "cutoff":
            steps.append({"id": str(uuid.uuid4()), "title": "", "text": a, "ingredientReferences": []})
        elif q["kind"] == "pan":
            pan = n_pans.parse(a)
            if pan:
                data["extras"] = {**(data.get("extras") or {}), "pan": pan}
    for g in ings:   # anything still unreadable stays visible to the cook, never guessed
        for k in ("note", "display", "originalText"):
            if isinstance(g.get(k), str):
                g[k] = g[k].replace("[?]", "(unreadable)")
    for st in steps:
        st["text"] = (st.get("text") or "").replace("[?]", "(unreadable)")
    data["recipeIngredient"], data["recipeInstructions"] = ings, steps
    return data


def import_job_finish(jid):
    """Save the recipe once nothing is left to ask (recipes that need nothing save silently)."""
    r = _job_row(jid)
    m = _job_meta(r)
    if r["status"] != "review" or _job_open_items(r, m):
        return import_job_view(r)
    if m.get("dup_choice") == "cancel":
        _job_save(jid, status="cancelled")
        return import_job_view(_job_row(jid))
    data = _apply_answers(json.loads(r["draft"]), m)
    if not data.get("name"):
        data["name"] = m.get("suggested_title") or "Untitled Recipe"
        data["extras"] = {**(data.get("extras") or {}), "title_source": "suggested"}
    choice = m.get("dup_choice")
    try:
        slug = _save_new_recipe(data, r["image_url"], dup="keep" if choice == "keep" else "skip",
                                replace=m.get("replace_slug") if choice == "replace" else None)
    except ApiError as e:
        _job_save(jid, status="failed", error=e.message)
        return import_job_view(_job_row(jid))
    queue_guided(slug)
    with db() as c:   # the name it was saved under (e.g. "Lemon Bars (2)")
        saved = n_recipes.get(c, slug)
    if saved:
        data["name"] = saved.get("name") or data.get("name")
    _job_save(jid, status="done", slug=slug, draft=data)
    return import_job_view(_job_row(jid))


def import_job_answer(jid, b):
    """POST /api/import/queue/{id}/answer {name?, approve_name?, answers: {qid: text|"skip"}, duplicate?: keep|replace|cancel,
    replace_slug?}. Saves the recipe as soon as everything is answered."""
    r = _job_row(jid)
    if r["status"] != "review":
        raise ApiError(409, "That recipe isn't waiting for answers.")
    m = _job_meta(r)
    draft = json.loads(r["draft"]) if r["draft"] else {}
    name = " ".join(_s(b.get("name"), 120).split())
    if name:
        draft["name"] = name
        m["name_ok"] = True
        m.pop("suggested_title", None)
    elif b.get("approve_name") and m.get("suggested_title"):
        m["name_ok"] = True
    answers = b.get("answers") or {}
    if not isinstance(answers, dict):
        raise ApiError(400, "Bad answers.")
    known = {q["id"] for q in m.get("questions") or []}
    for k, v in answers.items():
        if k in known and isinstance(v, str):
            m.setdefault("answers", {})[k] = v[:200]
    d = b.get("duplicate")
    if d is not None:
        if d not in ("keep", "replace", "cancel"):
            raise ApiError(400, "Choose Keep both, Replace or Cancel.")
        if d == "replace":
            target = _s(b.get("replace_slug"), 200) or ((m.get("dups") or [{}])[0].get("slug") or "")
            if target not in {x.get("slug") for x in m.get("dups") or []}:
                raise ApiError(400, "Pick which recipe to replace.")
            m["replace_slug"] = target
        m["dup_choice"] = d
    _job_save(jid, draft=draft, meta=m)
    return import_job_finish(jid)


def import_job_retake(jid, n, b):
    r = _job_row(jid)
    if r["kind"] != "scan" or not 1 <= n <= r["pages"]:
        raise ApiError(404, "That page isn't part of this scan.")
    p = b.get("data")
    if not isinstance(p, str) or not re.match(r"data:image/(jpeg|png|webp);base64,", p[:40]):
        raise ApiError(400, "Send a photo.")
    blob = base64.b64decode(p.split(",", 1)[1])
    if not n_recipes.sniff_image(blob) or len(blob) > 12_000_000:
        raise ApiError(400, "That isn't a usable photo.")
    with open(_job_page_path(jid, n), "wb") as f:
        f.write(blob)
    _job_save(jid, status="waiting", draft=None, meta={}, error=None)
    _import_wake.set()
    return import_job_view(_job_row(jid))


def import_job_retry(jid):
    r = _job_row(jid)
    if r["status"] != "failed" or r["kind"] != "scan":
        raise ApiError(409, "Only a failed scan can be retried.")
    _job_save(jid, status="waiting", error=None)
    _import_wake.set()
    return import_job_view(_job_row(jid))


def import_job_dismiss(jid):
    _job_row(jid)
    _job_save(jid, dismissed=1)
    shutil.rmtree(_job_dir(jid), ignore_errors=True)
    return {"ok": True}


def import_worker():
    """Reads queued scans one at a time, in the order they were taken."""
    with db() as c:
        c.execute("UPDATE import_jobs SET status='waiting' WHERE status='reading'")   # interrupted by a restart
    while True:
        _import_wake.wait(30)
        _import_wake.clear()
        while True:
            with db() as c:
                r = c.execute("SELECT id FROM import_jobs WHERE status='waiting' AND dismissed=0 ORDER BY id LIMIT 1").fetchone()
            if not r:
                break
            try:
                import_job_process(r["id"])
            except Exception as e:
                log("import worker error:", e)
                _job_save(r["id"], status="failed", error="Something went wrong. Try again.")


def _multipart_text(multipart, field):
    fields, files = multipart or ({}, [])
    return fields.get(field), files


def native_api(method, path, body=None, multipart=None):
    p = path.split("?")[0]
    with db() as c:
        # ---- recipes
        if p == "/api/recipes" and method == "GET":
            return {"items": n_recipes.list_summaries(c)}
        if p == "/api/recipes" and method == "POST":
            return n_recipes.create(c, (body or {}).get("name") or "Untitled recipe")
        mm = re.fullmatch(r"/api/recipes/([^/]+)/image", p)
        if mm and method == "PUT":
            _, files = _multipart_text(multipart, "extension")
            rec = n_recipes.get(c, urllib.parse.unquote(mm.group(1)))
            if not rec or not files:
                raise ApiError(404, "Recipe not found")
            _, fname, ctype, blob = files[0]
            try:
                return {"image": n_recipes.save_image(IMG_DIR, rec["id"], blob, _ext(ctype), c=c)}
            except ValueError as e:
                raise ApiError(400, str(e))
        mm = re.fullmatch(r"/api/recipes/([^/]+)", p)
        if mm and mm.group(1) not in ("create", "create-url"):
            key = urllib.parse.unquote(mm.group(1))
            if method == "GET":
                rec = n_recipes.get(c, key)
                if not rec:
                    raise ApiError(404, "Recipe not found")
                return rec
            if method == "PUT":
                return n_recipes.get(c, n_recipes.update(c, key, _annotate_foods(c, dict(body or {}))))
            if method == "DELETE":
                gone = n_recipes.get(c, key)
                n_recipes.delete(c, key, images_dir=IMG_DIR)
                if gone:   # its unbought list lines go too (shared lines keep the other recipes' amounts)
                    for lst in n_lists.list_lists(c):
                        n_lists.remove_recipe_items(c, lst["id"], gone["id"])
                c.execute("DELETE FROM meal_plans WHERE recipe_id NOT IN (SELECT id FROM recipes) AND recipe_id IS NOT NULL")
                sync_plan_list(c)
                return {}
        # ---- favorites / user
        if p == "/api/users/self":
            return {"id": "native", "groupSlug": cfg("group_slug") or "home", "fullName": cfg("household_name") or "Household"}
        if re.fullmatch(r"/api/users/[^/]+/favorites", p):
            return {"ratings": [{"recipeId": i, "isFavorite": True} for i in n_recipes.favorite_ids(c)]}
        mm = re.fullmatch(r"/api/users/[^/]+/favorites/([^/]+)", p)
        if mm:
            rec = n_recipes.get(c, urllib.parse.unquote(mm.group(1)))
            if not rec:
                raise ApiError(404, "Recipe not found")
            n_recipes.set_favorite(c, rec["id"], method == "POST")
            return {}
        # ---- meal plans
        if p == "/api/households/mealplans" and method == "GET":
            q = dict(urllib.parse.parse_qsl(path.partition("?")[2]))
            items = []
            for e in n_plans.get_plans(c, q.get("start_date"), q.get("end_date"), lambda rid: _lookup_summary(c, rid)):
                r = e.get("recipe")
                items.append({"id": e["id"], "date": e["date"], "entryType": e["entry_type"], "title": e["title"], "text": e["text"],
                              "recipeScale": e["scale"], "recipeId": e["recipeId"],
                              "cooked": e.get("cooked", False), "skipped": e.get("skipped", False),
                              "recipe": {"id": r["id"], "name": r["name"], "slug": r["slug"], "image": r["image_v"] or None} if r else None})
            return {"items": items}
        if p == "/api/households/mealplans" and method == "POST":
            b = body or {}
            try:
                eid = n_plans.add_entry(c, b.get("date"), b.get("entryType") or "dinner", b.get("recipeId"),
                                        b.get("title") or "", b.get("text") or "", b.get("recipeScale") or 1)
            except ValueError as e:
                raise ApiError(400, str(e))
            return {"id": eid, **b}
        mm = re.fullmatch(r"/api/households/mealplans/(\d+)", p)
        if mm and method == "DELETE":
            n_plans.delete_entry(c, int(mm.group(1)))
            return {}
        # ---- shopping lists
        if p == "/api/households/shopping/lists" and method == "GET":
            n_lists.single_list(c)
            return {"items": n_lists.list_lists(c)}
        if p == "/api/households/shopping/lists" and method == "POST":
            lid = n_lists.single_list(c)   # one ongoing list: "new list" points at it
            return {"id": lid, "name": n_lists.get_list(c, lid)["name"]}
        mm = re.fullmatch(r"/api/households/shopping/lists/([^/]+)/recipe", p)
        if mm and method == "POST":
            lid = urllib.parse.unquote(mm.group(1))
            for it in body or []:
                rec = n_recipes.get(c, it["recipeId"])
                if not rec:
                    continue
                ings = it.get("recipeIngredients") if it.get("recipeIngredients") is not None else rec.get("recipeIngredient") or []
                lines = [_ing_line(g) for g in ings if _ing_line(g)]
                n_lists.add_recipe_ingredients(c, lid, rec["id"], lines, it.get("recipeIncrementQuantity") or 1, parse_ing_text,
                                               aisle_for, food_key, resolve=_food_id)
            return n_lists.get_list(c, lid)
        mm = re.fullmatch(r"/api/households/shopping/lists/([^/]+)", p)
        if mm and method == "GET":
            sl = n_lists.get_list(c, urllib.parse.unquote(mm.group(1)))
            if not sl:
                raise ApiError(404, "Shopping list not found")
            return sl
        if p == "/api/households/shopping/items/create-bulk" and method == "POST":
            by_list = {}
            for x in body or []:
                by_list.setdefault(x["shoppingListId"], []).append(x.get("note") or x.get("display") or "")
            for lid, texts in by_list.items():
                n_lists.add_items(c, lid, texts, parse_ing_text, aisle_for, food_key, resolve=_food_id)
            return {}
        mm = re.fullmatch(r"/api/households/shopping/items/([^/]+)", p)
        if mm and method == "PUT":
            row = c.execute("SELECT list_id FROM shopping_items WHERE id=?", (mm.group(1),)).fetchone()
            if not row:
                raise ApiError(404, "Item not on this list")
            n_lists.set_checked(c, row["list_id"], mm.group(1), bool((body or {}).get("checked")))
            return {}
    # ---- imports (network/AI work happens outside the db transaction)
    if p == "/api/recipes/create/url":
        url = (body or {}).get("url") or ""
        try:
            data = n_scraper.scrape(url, _fetch_page)
        except n_scraper.NoRecipe as e:
            page_img = getattr(e, "image_url", None)
            if not cfg("openai_key") or len(e.page_text or "") < 300:
                raise ApiError(422, "Couldn't find a recipe on that page (it may be behind a login or paywall). "
                                    "Take screenshots of the recipe and use the Screenshot tab instead.")
            data = ai_recipe(f"Web page: {url}\n\n{e.page_text}", feature="link import", detail=url[:80])
            data["orgURL"], data["image_url"] = url, page_img
        return _save_new_recipe(data, data.pop("image_url", None))
    if p == "/api/recipes/create/ai":
        text, files = _multipart_text(multipart, "content")
        imgs = [{"data": f"data:{ct};base64," + base64.b64encode(blob).decode()} for _, _, ct, blob in files]
        data = ai_recipe(text or "", imgs, "screenshot import", f"{len(imgs)} image(s)" if imgs else "text")
        return _save_new_recipe(data)
    raise ApiError(501, f"Not available without Mealie: {method} {p}")



# ============================================================ how long a recipe takes (estimate, learned from real cooks)

def _eta_stated(r):
    sec = lambda k: round(int(r.get(k) or 0) / 60) or None   # noqa: E731
    return {"prep": sec("prepTimeSeconds"), "cook": sec("performTimeSeconds"), "total": sec("totalTimeSeconds")}


def eta_base(r, oven=None, c=None, store=True):
    """The estimate for a raw recipe (as stored), cached in extras.eta until the recipe or the oven setting changes."""
    oven = oven or get_settings().get("oven") or "conventional"
    extras = r.get("extras") if isinstance(r.get("extras"), dict) else {}
    cached = extras.get("eta")
    stamp = [r.get("dateUpdated") or "", oven, 1]
    if isinstance(cached, dict) and cached.get("stamp") == stamp:
        return cached
    lines = [_ing_line(g) for g in r.get("recipeIngredient") or [] if _ing_line(g)]
    steps = [(st.get("text") or "").strip() for st in r.get("recipeInstructions") or [] if (st.get("text") or "").strip()]
    if not lines and not steps:
        return None
    eta = {**n_eta.estimate(lines, steps, oven, _eta_stated(r)), "stamp": stamp}
    if store and NATIVE and r.get("id"):
        try:
            own = c is None
            cx = db() if own else None
            conn = cx.__enter__() if own else c
            row = conn.execute("SELECT data FROM recipes WHERE id=?", (r["id"],)).fetchone()
            if row:   # written in place: saving an estimate isn't an edit (dateUpdated stays)
                data = json.loads(row["data"])
                if (data.get("dateUpdated") or "") == stamp[0]:
                    ex = data.get("extras") if isinstance(data.get("extras"), dict) else {}
                    data["extras"] = {**ex, "eta": eta}
                    conn.execute("UPDATE recipes SET data=? WHERE id=?", (json.dumps(data), r["id"]))
            if own:
                cx.__exit__(None, None, None)
        except sqlite3.Error as e:
            log("estimate not stored:", e)
    return eta


_speed = {"at": 0, "f": 1.0}


def household_speed():
    if time.time() - _speed["at"] > 600:
        with db() as c:
            ratios = [r["actual_min"] / r["estimate_min"] for r in c.execute(
                "SELECT actual_min, estimate_min FROM cook_times WHERE estimate_min > 0 ORDER BY id DESC LIMIT 200")]
        _speed.update(at=time.time(), f=n_eta.speed_factor(ratios))
    return _speed["f"]


def eta_view(recipe_id, base):
    """What to show: the estimate, the recipe's own times, and what this household usually takes."""
    if not base:
        return None
    with db() as c:
        mine = [r["actual_min"] for r in c.execute("SELECT actual_min FROM cook_times WHERE recipe_id=? ORDER BY id DESC LIMIT 10",
                                                     (recipe_id,))]
    v = {k: base.get(k) for k in ("total", "active", "passive", "approx", "long", "parts", "stated", "based_on")}
    speed = household_speed()
    if len(mine) >= 2:
        usual = round(statistics.median(mine))
        v.update(usual=usual, shown=usual, basis="you")
    else:
        shown = base["total"] if base.get("based_on") == "recipe" else round(base["total"] * speed)
        v.update(shown=max(1, shown), speed=round(speed, 2) if abs(speed - 1) > 0.04 else None, basis=base.get("based_on"))
    v["active_shown"] = min(v["shown"], round(base["active"] * (speed if len(mine) < 2 and base.get("based_on") != "recipe" else 1)))
    v["label"] = n_eta.label({"shown": v["shown"], "active": v["active_shown"], "long": base.get("long")})
    return v


def record_cook_time(recipe_id, minutes, base):
    """Remember how long a cook actually took (cook mode start to Done), unless it's far off the estimate."""
    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        return False
    if not base or not n_eta.keep_session(minutes, base["total"]):
        return False
    with db() as c:
        c.execute("INSERT INTO cook_times(recipe_id, actual_min, estimate_min, at) VALUES (?,?,?,?)",
                  (recipe_id, round(minutes, 1), base["total"], datetime.now().isoformat(timespec="seconds")))
    _speed["at"] = 0
    return True


def start_by(eat_at, minutes, day):
    """The clock time to start cooking to eat at eat_at ("18:30") on day, in the server's time zone. Rounded down to 5 min."""
    try:
        h, m = (int(x) for x in eat_at.split(":"))
    except (ValueError, AttributeError):
        return None
    eat = datetime(day.year, day.month, day.day, h, m)
    st = eat - timedelta(minutes=int(minutes or 0))
    st -= timedelta(minutes=st.minute % 5)
    return st


def recipe_pool(refresh=False):
    with _recipe_lock:
        if refresh or time.time() - _recipe_cache["at"] > 120:
            data = mealie("GET", "/api/recipes?page=1&perPage=-1&orderBy=name&orderDirection=asc")
            favs = favorite_ids()
            items = []
            for r in data.get("items", []):
                items.append({
                    "id": r["id"], "slug": r.get("slug"), "name": r.get("name") or "Untitled",
                    "has_image": bool(r.get("image")),
                    "tags": [t.get("name", "") for t in (r.get("tags") or [])],
                    "categories": [t.get("name", "") for t in (r.get("recipeCategory") or [])],
                    "rating": r.get("rating") or 0,
                    "last_made": (r.get("lastMade") or "")[:10] or None,
                    "updated": r.get("dateUpdated") or r.get("updatedAt") or r.get("updateAt") or "",
                    "total_time": r.get("totalTime"),
                    "servings": float(r.get("recipeServings") or 0),
                    "minutes": recipe_minutes(r),
                    "description": (r.get("description") or "")[:240],
                    "image_v": r.get("image") or "",
                    "favorite": r["id"] in favs,
                })
            if NATIVE:
                oven = get_settings().get("oven") or "conventional"
                raw = {r["id"]: r for r in data.get("items", [])}
                with db() as c:
                    for it in items:
                        r = raw.get(it["id"]) or {}
                        ex = r.get("extras") if isinstance(r.get("extras"), dict) else {}
                        it["ai_generated"] = bool(ex.get("ai_generated"))
                        base = ex.get("eta") if isinstance(ex.get("eta"), dict) and ex["eta"].get("stamp") == [r.get("dateUpdated") or "", oven, 1] else None
                        if base is None:
                            full = n_recipes.get(c, it["id"])
                            base = eta_base(full, oven, c) if full else None
                        if base:
                            v = eta_view(it["id"], base)
                            it["eta"] = {k: v[k] for k in ("shown", "active_shown", "label", "long", "approx", "basis")}
                            it["eta_min"] = v["shown"]
                rated = diary_ratings()
                for it in items:
                    if it["id"] in rated:
                        it["rating"], it["ratings"] = rated[it["id"]]
            _recipe_cache.update(at=time.time(), items=items)
        return list(_recipe_cache["items"])


def _credit_out(cr):
    """A stored licence credit (e.g. Wikibooks Cookbook · CC BY-SA), with only https links passed on."""
    if not isinstance(cr, dict):
        return None
    ok = lambda u: u if isinstance(u, str) and u.startswith("https://") else ""
    return {"site": _s(cr.get("site"), 80), "title": _s(cr.get("title"), 160), "url": ok(cr.get("url")),
            "license": _s(cr.get("license"), 40), "license_url": ok(cr.get("license_url")), "authors": _s(cr.get("authors"), 120)}


def recipe_link(slug):
    if NATIVE:
        return f"/#recipe/{urllib.parse.quote(slug or '')}" if slug else "/#recipes"
    base = mealie_public()
    return f"{base}/g/{cfg('group_slug')}/r/{slug}" if slug else base


def recipe_foods(recipes):
    """Return {recipe_id: set(food tokens)} using a SQLite cache keyed on Mealie's updated timestamp."""
    out, todo = {}, []
    with db() as c:
        cached = {r["id"]: r for r in c.execute("SELECT * FROM recipe_cache")}
    for r in recipes:
        hit = cached.get(r["id"])
        if hit and hit["updated"] == r["updated"]:
            out[r["id"]] = set(json.loads(hit["foods"]))
        else:
            todo.append(r)

    def fetch(r):
        try:
            d = mealie("GET", f"/api/recipes/{_q(r['slug'] or r['id'])}")
            toks = set()
            for ing in d.get("recipeIngredient") or []:
                food = (ing.get("food") or {}).get("name") or ing.get("note") or ing.get("display") or ""
                toks.update(tokens(food))
            return r, toks
        except ApiError:
            return r, None

    if todo:
        with ThreadPoolExecutor(max_workers=4) as ex:
            results = list(ex.map(fetch, todo[:400]))
        with db() as c:
            for r, toks in results:
                if toks is None:
                    continue
                out[r["id"]] = toks
                c.execute("INSERT INTO recipe_cache(id, updated, foods) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated, foods=excluded.foods",
                          (r["id"], r["updated"], json.dumps(sorted(toks))))
    return out


def get_plans(start, end):
    q = urllib.parse.urlencode({"start_date": iso(start), "end_date": iso(end), "page": 1, "perPage": -1,
                                "orderBy": "date", "orderDirection": "asc"})
    data = mealie("GET", f"/api/households/mealplans?{q}")
    out = []
    for p in data.get("items", []):
        rec = p.get("recipe") or {}
        out.append({
            "id": p.get("id"), "date": p.get("date"), "entry_type": p.get("entryType"),
            "title": p.get("title") or "", "text": p.get("text") or "",
            "scale": p.get("recipeScale") or 1,
            "cooked": bool(p.get("cooked")), "skipped": bool(p.get("skipped")),
            "recipe": {"id": rec.get("id") or p.get("recipeId"), "name": rec.get("name"), "slug": rec.get("slug"),
                       "has_image": bool(rec.get("image")), "image_v": rec.get("image") or "",
                       "link": recipe_link(rec.get("slug"))} if (rec or p.get("recipeId")) else None,
        })
    return out


# ============================================================ meal plan generator

ENTRY_ORDER = {"breakfast": 0, "lunch": 1, "dinner": 2, "side": 3, "snack": 4, "dessert": 5, "drink": 6}


def _filtered_pool(opts):
    pool = recipe_pool()
    inc = {t.lower() for t in opts.get("include_tags") or [] if t}
    exc = {t.lower() for t in opts.get("exclude_tags") or [] if t}

    def labels(r):
        return {x.lower() for x in r["tags"] + r["categories"]}

    if inc:
        pool = [r for r in pool if labels(r) & inc]
    if exc:
        pool = [r for r in pool if not (labels(r) & exc)]
    return pool


def generate_plan(opts):
    settings = get_settings()
    o = {**settings, **{k: (validate_setting(k, v) if k in SETTINGS_VALIDATORS else v) for k, v in opts.items() if v is not None}}
    start = parse_date(o.get("start")) or today()
    days = max(1, min(62, int(o.get("days") or 7)))
    end = start + timedelta(days=days - 1)
    meal_types = [m for m in (o.get("meal_types") or ["dinner"]) if m] or ["dinner"]
    no_repeat = max(0, int(o.get("no_repeat_days") or 0))

    pool = _filtered_pool(o)
    warnings = []
    if not pool:
        raise ApiError(400, "No recipes match those filters. Add recipes in Mealie or loosen the tag filters.")

    # Every date each recipe is already used (lookback window + this range), plus Mealie's lastMade.
    used = {}
    lookback = get_plans(start - timedelta(days=max(1, no_repeat)), end)
    for p in lookback:
        rid = (p["recipe"] or {}).get("id")
        d = parse_date(p["date"])
        if rid and d:
            used.setdefault(rid, []).append(d)
    for r in pool:
        lm = parse_date(r["last_made"])
        if lm:
            used.setdefault(r["id"], []).append(lm)

    filled = {(p["date"], p["entry_type"]) for p in lookback if start <= (parse_date(p["date"]) or start - timedelta(1)) <= end}

    # Use-it-up boost: recipes that use pantry items expiring soon get weighted up early in the plan.
    boost = {}
    if o.get("prefer_expiring"):
        with db() as c:
            exp_items = expiring_items(c, max(3, int(o.get("expiring_window_days") or 3)) + 2)
        exp_tokens = set()
        for it in exp_items:
            exp_tokens.update(tokens(it["name"]))
        if exp_tokens:
            foods = recipe_foods(pool)
            for r in pool:
                hits = foods.get(r["id"], set()) & exp_tokens
                if hits:
                    boost[r["id"]] = len(hits)

    cost_w = _budget_weights(pool) if NATIVE else {}
    proposals = []
    used_this_plan = {}
    for i in range(days):
        d = start + timedelta(days=i)
        for mt in sorted(meal_types, key=lambda m: ENTRY_ORDER.get(m, 9)):
            if o.get("fill_empty_only", True) and (iso(d), mt) in filled:
                continue
            pick = _pick(pool, d, i, no_repeat, used, used_this_plan, boost, cost_w=cost_w)
            used.setdefault(pick["id"], []).append(d)
            used_this_plan[pick["id"]] = d
            proposals.append(_proposal(d, mt, pick, boost))
    if len(pool) < days * len(meal_types) and no_repeat:
        warnings.append(f"Only {len(pool)} recipes match — some repeat sooner than {no_repeat} days.")
    return {"start": iso(start), "end": iso(end), "proposals": proposals, "warnings": warnings,
            "pool_size": len(pool)}


def _proposal(d, mt, r, boost):
    return {"date": iso(d), "entry_type": mt,
            "recipe": {"id": r["id"], "name": r["name"], "slug": r["slug"], "has_image": r["has_image"],
                       "link": recipe_link(r["slug"]), "uses_expiring": bool(boost.get(r["id"]))}}


def _budget_weights(pool):
    """Budget-aware planning: with a grocery budget set, cheaper recipes (per serving) come up more often, and more so
    once this period's spending passes 80%. Recipes without a known cost are left neutral."""
    b = get_settings().get("budget") or {}
    if not float(b.get("amount") or 0) or not b.get("plan_aware", True):
        return {}
    try:
        costs = recipe_costs_all()
        level = budget_status()["level"]
    except Exception:
        return {}
    per = sorted(v["per_serving"] for v in costs.values() if v.get("per_serving"))
    if len(per) < 3:
        return {}
    mid = per[len(per) // 2]
    k = 1.2 if level else 0.6
    return {rid: max(0.4, min(2.5, (mid / v["per_serving"]) ** k)) for rid, v in costs.items() if v.get("per_serving")}


def _pick(pool, d, day_index, no_repeat, used, used_this_plan, boost, exclude=(), cost_w=None):
    """Weighted random pick. `used` maps recipe id -> list of dates it's planned/made."""
    window = max(1, no_repeat)

    def ok(r):
        if r["id"] in exclude:
            return False
        return all(abs((d - u).days) >= window for u in used.get(r["id"], ()))

    candidates = [r for r in pool if ok(r)]
    if not candidates:
        # Pool exhausted — fall back to the recipes used longest ago.
        rest = [r for r in pool if r["id"] not in exclude] or pool
        rest.sort(key=lambda r: min((abs((d - u).days) for u in used.get(r["id"], ())), default=10**6), reverse=True)
        candidates = rest[:max(1, len(rest) // 4)]
    weights = []
    for r in candidates:
        w = 1.0 + 1.5 * (float(r["rating"] or 0) / 5.0) ** 2   # well-loved recipes (diary ratings) come up more
        if r["id"] in boost and day_index < 4:
            w *= 1 + 2.5 * boost[r["id"]]
        if r["id"] in used_this_plan:
            w *= 0.3
        if cost_w and r["id"] in cost_w:
            w *= cost_w[r["id"]]
        mins = r.get("eta_min") or r.get("minutes")
        if mins and d.weekday() < 4:   # busy weekdays: quick meals come up more, long ones less
            w *= 1.3 if mins <= 35 else 0.6 if mins > 75 else 1.0
        weights.append(w)
    return random.choices(candidates, weights=weights, k=1)[0]


def reroll(opts):
    d = parse_date(opts.get("date")) or today()
    pool = _filtered_pool({**get_settings(), **opts})
    if not pool:
        raise ApiError(400, "No recipes match those filters.")
    exclude = set(opts.get("exclude_ids") or [])
    used = {}
    for e in opts.get("planned") or []:
        pd = parse_date(e.get("date"))
        if pd and e.get("recipe_id") and not (pd == d and e.get("entry_type") == opts.get("entry_type")):
            used.setdefault(e["recipe_id"], []).append(pd)
    no_repeat = max(0, min(365, int(opts.get("no_repeat_days") or get_settings()["no_repeat_days"])))
    r = _pick(pool, d, 99, no_repeat, used, {}, {}, exclude)
    return _proposal(d, opts.get("entry_type") or "dinner", r, {})


def household_scale(recipe_id):
    """Scale factor so a recipe feeds the household (people ÷ recipe servings)."""
    if not cfg("scale_to_household"):
        return 1.0
    people = float(cfg("people") or 0)
    r = next((x for x in recipe_pool() if x["id"] == recipe_id), None)
    if not r or not r.get("servings") or people <= 0:
        return 1.0
    return max(0.25, round(people / r["servings"], 2))


def save_plan(entries):
    created = 0
    for e in entries:
        if not (e.get("date") and e.get("recipe_id")):
            continue
        mealie("POST", "/api/households/mealplans", {
            "date": e["date"], "entryType": e.get("entry_type") or "dinner",
            "title": "", "text": "", "recipeId": e["recipe_id"],
            "recipeScale": household_scale(e["recipe_id"])})
        created += 1
    return created


# ============================================================ shopping lists

def nice_qty(q):
    if q in (None, ""):
        return ""
    try:
        q = float(q)
    except (TypeError, ValueError):
        return str(q)
    if q <= 0:
        return ""
    frac = Fraction(q).limit_denominator(16)
    if abs(float(frac) - q) > 0.005:
        return f"{q:.2f}".rstrip("0").rstrip(".")
    whole, rem = divmod(frac.numerator, frac.denominator)
    if rem == 0:
        return str(whole)
    part = f"{rem}/{frac.denominator}"
    return f"{whole} {part}" if whole else part


def item_text(it):
    disp = (it.get("display") or "").strip()
    if disp:
        return disp
    parts = []
    q = nice_qty(it.get("quantity"))
    if q and (it.get("unit") or it.get("food")) and not (q == "1" and not it.get("unit")):
        parts.append(q)
    unit = it.get("unit") or {}
    if unit.get("name"):
        parts.append(unit["abbreviation"] if unit.get("useAbbreviation") and unit.get("abbreviation") else unit["name"])
    if (it.get("food") or {}).get("name"):
        parts.append(it["food"]["name"])
    if (it.get("note") or "").strip():
        parts.append(it["note"].strip())
    return " ".join(parts) or "(unnamed item)"


def item_name(it):
    """Best short product name for the pantry."""
    food = (it.get("food") or {}).get("name")
    if food:
        return food[:1].upper() + food[1:]
    txt = it.get("note") or it.get("display") or "Item"
    txt = re.sub(r"^[\d\s/.,½¼¾⅓⅔]+", "", txt).strip()
    return (txt[:1].upper() + txt[1:]) if txt else "Item"


def get_lists():
    data = mealie("GET", "/api/households/shopping/lists?page=1&perPage=-1&orderBy=name&orderDirection=asc")
    return [{"id": l["id"], "name": l.get("name") or "Shopping list"} for l in data.get("items", [])]


def get_list(list_id):
    return mealie("GET", f"/api/households/shopping/lists/{urllib.parse.quote(str(list_id), safe='')}")


def grouped(sl, include_checked=False):
    groups = {}
    for it in sl.get("listItems") or []:
        if it.get("checked") and not include_checked:
            continue
        label = ((it.get("label") or {}).get("name") or "Other").strip()
        groups.setdefault(label, []).append(it)
    for v in groups.values():
        v.sort(key=lambda i: (i.get("position") or 0, item_text(i).lower()))
    order = sorted(groups, key=lambda l: (l == "Other", l.lower()))
    return [(l, groups[l]) for l in order]


ANY_STORE = "Any store"


def store_names():
    """[(id, name)] in the household's store order (native backend only)."""
    if not NATIVE:
        return []
    with db() as c:
        return [(s["id"], s["name"]) for s in n_lists.list_stores(c)]


def grouped_by_store(sl, include_checked=False):
    """[(store name, [(aisle, items)])]: stores in their set order, then "Any store" for unassigned items."""
    stores = store_names()
    known = {sid for sid, _ in stores}
    buckets = {}
    for it in sl.get("listItems") or []:
        sid = it.get("storeId")
        buckets.setdefault(sid if sid in known else None, []).append(it)
    out = []
    for sid, name in stores + [(None, ANY_STORE)]:
        g = grouped({"listItems": buckets.get(sid, [])}, include_checked)
        if g:
            out.append((name, g))
    return out


def _store_headers(by_store):
    """Only show store headers when at least one item is assigned to a store."""
    return not (len(by_store) <= 1 and (not by_store or by_store[0][0] == ANY_STORE))


def list_json(sl):
    return {
        "id": sl.get("id"), "name": sl.get("name") or "Shopping list",
        "groups": [{"label": l, "items": [{"id": i["id"], "text": item_text(i), "name": item_name(i),
                                            "emoji": food_emoji((i.get("food") or {}).get("name") or i.get("note") or i.get("display")),
                                            "qty": " ".join(x for x in (nice_qty(i.get("quantity")) if (i.get("food") or i.get("unit")) else "",
                                                                         ((i.get("unit") or {}).get("name") or "")) if x),
                                            "food": (i.get("food") or {}).get("name") or ""} for i in items]}
                   for l, items in grouped(sl)],
        "checked": [{"id": i["id"], "text": item_text(i)} for i in (sl.get("listItems") or []) if i.get("checked")][:30],
        "mealie_link": f"{mealie_public()}/shopping-lists/{sl.get('id')}",
    }


def set_checked(sl, item_id, checked):
    item = next((i for i in sl.get("listItems") or [] if i.get("id") == item_id), None)
    if not item:
        raise ApiError(404, "Item not on this list")
    payload = {k: v for k, v in item.items() if k not in ("createdAt", "updatedAt", "update_at", "created_at")}
    payload["checked"] = checked
    mealie("PUT", f"/api/households/shopping/items/{_q(item_id)}", payload)
    return item


# ============================================================ rendering (text / csv / html / ics)

def fmt_day(d):
    return d.strftime("%a %b ") + str(d.day)


def plan_by_day(entries, start, end):
    days = []
    d = start
    while d <= end:
        es = [e for e in entries if e["date"] == iso(d)]
        es.sort(key=lambda e: ENTRY_ORDER.get(e["entry_type"], 9))
        days.append((d, es))
        d += timedelta(days=1)
    return days


def entry_name(e):
    return (e.get("recipe") or {}).get("name") or e.get("title") or "(note)"


def render_list_text(sl):
    lines = [sl.get("name") or "Shopping list", ""]
    by_store = grouped_by_store(sl)
    if not by_store:
        lines.append("(Nothing left to buy.)")
    headers = _store_headers(by_store)
    for store, groups in by_store:
        if headers:
            lines += [f"== {store} ==", ""]
        for label, items in groups:
            lines.append(label.upper())
            lines += [f"  [ ] {item_text(i)}" for i in items]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_list_csv(sl):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Store", "Section", "Item", "Quantity", "Unit", "Food", "Note"])
    for store, groups in grouped_by_store(sl):
        for label, items in groups:
            for i in items:
                w.writerow([store, label, item_text(i), nice_qty(i.get("quantity")), (i.get("unit") or {}).get("name", ""),
                            (i.get("food") or {}).get("name", ""), i.get("note") or ""])
    return buf.getvalue()


def render_plan_text(entries, start, end):
    lines = [f"Meal plan {fmt_day(start)} – {fmt_day(end)}", ""]
    for d, es in plan_by_day(entries, start, end):
        lines.append(fmt_day(d))
        lines += [f"  {e['entry_type'].title()}: {entry_name(e)}" for e in es] or ["  —"]
    return "\n".join(lines) + "\n"


def render_plan_csv(entries):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Day", "Meal", "Recipe", "Link"])
    for e in sorted(entries, key=lambda e: (e["date"], ENTRY_ORDER.get(e["entry_type"], 9))):
        d = parse_date(e["date"])
        w.writerow([e["date"], d.strftime("%A") if d else "", e["entry_type"], entry_name(e),
                    (e.get("recipe") or {}).get("link", "")])
    return buf.getvalue()


def ics_escape(s):
    return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_fold(line):
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    out, cur = [], b""
    for ch in line:
        cb = ch.encode("utf-8")
        if len(cur) + len(cb) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += cb
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def render_plan_ics(entries):
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TablePlan//Meal Plan//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:Meal plan"]
    for e in entries:
        d = parse_date(e["date"])
        if not d:
            continue
        uid = f"{e.get('id') or (e['date'] + e['entry_type'] + entry_name(e))}@tableplan".replace(" ", "")
        lines += ["BEGIN:VEVENT", f"UID:{ics_escape(uid)}", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                  f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
                  f"SUMMARY:{ics_escape(e['entry_type'].title() + ': ' + entry_name(e))}"]
        link = (e.get("recipe") or {}).get("link")
        if link:
            lines += [f"URL:{link}", f"DESCRIPTION:{ics_escape(link)}"]
        lines += ["TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(ics_fold(l) for l in lines) + "\r\n"


def render_pantry_csv(items):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Item", "Quantity", "Location", "Amount left", "Purchased", "Opened", "Expires", "Days left", "Shelf-life source"])
    for i in items:
        w.writerow([i["name"], i["quantity_text"], i["location"], f"{round(i['amount_left'] * 100)}%",
                    i["purchased_on"], i["opened_on"] or "", i["expires_on"] or "",
                    "" if i["days_left"] is None else i["days_left"], (i["rule"] or {}).get("name", "")])
    return buf.getvalue()


PRINT_CSS = """
*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1c1c1e;margin:0;padding:28px;max-width:820px}
h1{font-size:26px;margin:0 0 2px;letter-spacing:-.02em}.sub{color:#8e8e93;font-size:13px;margin-bottom:22px}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#8e8e93;border-bottom:1px solid #e5e5ea;padding-bottom:5px;margin:20px 0 8px}
ul{list-style:none;padding:0;margin:0}li{padding:6px 0;font-size:15px;display:flex;gap:10px;border-bottom:1px dotted #eee}
.box{width:15px;height:15px;border:1.5px solid #8e8e93;border-radius:4px;flex:none;margin-top:2px}
.cols{columns:2;column-gap:36px}.section{break-inside:avoid}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:8px 6px;border-bottom:1px solid #e5e5ea;vertical-align:top}
th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#8e8e93}
.day{font-weight:600;white-space:nowrap;width:110px}.meal{color:#8e8e93;font-size:12px;text-transform:uppercase;width:80px}
.store{font-size:18px;margin:26px 0 0;letter-spacing:-.01em}
.red{color:#d70015;font-weight:600}.amber{color:#b25000;font-weight:600}
.bar{position:fixed;top:12px;right:12px;display:flex;gap:8px}
.bar button{font:inherit;font-size:14px;padding:8px 14px;border-radius:999px;border:0;background:#007aff;color:#fff}
.bar button.sec{background:#e5e5ea;color:#1c1c1e}
@media print{.bar{display:none}body{padding:0}}
"""


def print_page(title, sub, body):
    e = html.escape
    nonce = getattr(_req, "nonce", "") or ""
    # No inline event handlers: the page's only script carries the per-response CSP nonce.
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{PRINT_CSS}</style></head><body>
<div class="bar"><button class="sec" id="tp-done">Done</button><button id="tp-print">Print</button></div>
<h1>{e(title)}</h1><div class="sub">{e(sub)}</div>{body}
<script nonce="{e(nonce)}">document.getElementById('tp-done').onclick=()=>history.length>1?history.back():window.close();
document.getElementById('tp-print').onclick=()=>window.print();
if(location.search.includes('auto=1'))setTimeout(()=>window.print(),300)</script></body></html>"""


def print_list(sl):
    e = html.escape
    by_store = grouped_by_store(sl)
    headers = _store_headers(by_store)
    body = "".join(
        (f'<h3 class="store">{e(store)}</h3>' if headers else "") + '<div class="cols">' + "".join(
            f'<div class="section"><h2>{e(l)}</h2><ul>' +
            "".join(f'<li><span class="box"></span>{e(item_text(i))}</li>' for i in items) + "</ul></div>"
            for l, items in groups) + "</div>"
        for store, groups in by_store) if by_store else "<p>Nothing left to buy.</p>"
    return print_page(sl.get("name") or "Shopping list", datetime.now().strftime("Printed %a %b %d, %Y"), body)


def plan_table_html(entries, start, end, links=True):
    e = html.escape
    rows = []
    for d, es in plan_by_day(entries, start, end):
        if not es:
            rows.append(f'<tr><td class="day">{e(fmt_day(d))}</td><td class="meal"></td><td style="color:#c7c7cc">—</td></tr>')
        for j, en in enumerate(es):
            link = (en.get("recipe") or {}).get("link")
            name = e(entry_name(en))
            cell = f'<a href="{e(link)}" style="color:#1c1c1e;text-decoration:none">{name}</a>' if (links and link) else name
            rows.append(f'<tr><td class="day">{e(fmt_day(d)) if j == 0 else ""}</td>'
                        f'<td class="meal">{e(en["entry_type"])}</td><td>{cell}</td></tr>')
    return "<table>" + "".join(rows) + "</table>"


def print_plan(entries, start, end):
    return print_page("Meal plan", f"{fmt_day(start)} – {fmt_day(end)}, {end.year}", plan_table_html(entries, start, end))


def print_pantry(items):
    e = html.escape
    by_loc = {l: [i for i in items if i["location"] == l] for l in LOCATIONS}
    body = ""
    for loc, its in by_loc.items():
        if not its:
            continue
        body += f"<h2>{loc.title()}</h2><table><tr><th>Item</th><th>Left</th><th>Opened</th><th>Use by</th></tr>"
        for i in its:
            dl = i["days_left"]
            cls = "red" if dl is not None and dl <= 0 else "amber" if dl is not None and dl <= 3 else ""
            body += (f"<tr><td>{e(i['name'])}</td><td>{round(i['amount_left'] * 100)}%</td>"
                     f"<td>{e(i['opened_on'] or '')}</td><td class='{cls}'>{e(i['expires_on'] or '—')}</td></tr>")
        body += "</table>"
    return print_page("Pantry", datetime.now().strftime("As of %a %b %d, %Y"), body or "<p>Pantry is empty.</p>")


# ============================================================ email

def mail_recipients():
    """The household's mail_to list plus every member who opted in to email (deduplicated, case-insensitive)."""
    out, seen = [], set()
    try:
        with db() as c:
            extra = n_users.notify_emails(c)
    except sqlite3.Error:
        extra = []
    for a in list(cfg("mail_to") or []) + extra:
        if a and a.lower() not in seen:
            seen.add(a.lower()); out.append(a)
    return out


def email_ready():
    return bool(cfg("smtp_host") and mail_recipients())


def smtp_send(msg, conf=None):
    c = conf or {k: cfg(k) for k in ("smtp_host", "smtp_port", "smtp_security", "smtp_user", "smtp_password")}
    ctx = ssl.create_default_context()
    port = int(c["smtp_port"] or 587)
    sec = (c["smtp_security"] or "starttls").lower()
    try:
        server = (smtplib.SMTP_SSL(c["smtp_host"], port, context=ctx, timeout=30) if sec == "ssl"
                  else smtplib.SMTP(c["smtp_host"], port, timeout=30))
        with server:
            if sec == "starttls":
                server.starttls(context=ctx)
            if c.get("smtp_user") and c.get("smtp_password"):
                server.login(c["smtp_user"], c["smtp_password"])
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise ApiError(400, "The email server rejected the username or password. For Gmail/Google Workspace, use an App Password.")
    except (smtplib.SMTPException, OSError) as e:
        raise ApiError(502, f"Email failed: {e}")


def send_email(subject, text, html_body, attachments=(), to=None, conf=None):
    if not conf and not email_ready():
        raise ApiError(400, "Email isn't set up yet — open Settings → Email.")
    c = conf or {}
    msg = EmailMessage()
    sender = (c.get("smtp_from") if conf else cfg("smtp_from")) or (c.get("smtp_user") if conf else cfg("smtp_user"))
    msg["Subject"], msg["From"] = re.sub(r"[\r\n]+", " ", subject)[:250], sender
    msg["To"] = ", ".join(to or (c.get("mail_to") if conf else mail_recipients()))
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    for fname, data, mime in attachments:
        main, sub = mime.split("/", 1)
        msg.add_attachment(data, maintype=main, subtype=sub, filename=fname)
    smtp_send(msg, conf)


def email_wrap(inner):
    return f'<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1c1c1e;max-width:620px">{inner}</div>'


# ---- messages: one builder per kind, delivered to any channel (email, Telegram, ntfy)

def _print_body(page):
    return page.split("</div>", 1)[1].split("<script")[0]  # drop the button bar + script


def msg_list(list_id):
    sl = get_list(list_id)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", sl.get("name") or "list")
    return {"subject": f"🛒 {sl.get('name') or 'Shopping list'} — {datetime.now().strftime('%b %d')}",
            "text": render_list_text(sl).replace("[ ]", "☐"),
            "html": email_wrap(f"<style>{PRINT_CSS}</style>{_print_body(print_list(sl))}"),
            "files": [(f"{safe}.csv", render_list_csv(sl).encode(), "text/csv")]}


def msg_plan(start, end):
    entries = get_plans(start, end)
    return {"subject": f"🍽️ Meal plan {fmt_day(start)} – {fmt_day(end)}",
            "text": render_plan_text(entries, start, end),
            "html": email_wrap(f"<style>{PRINT_CSS}</style><h1>Meal plan</h1><div class='sub'>{html.escape(fmt_day(start))} – "
                               f"{html.escape(fmt_day(end))}</div>" + plan_table_html(entries, start, end)),
            "files": [("meal-plan.csv", render_plan_csv(entries).encode(), "text/csv"),
                      ("meal-plan.ics", render_plan_ics(entries).encode(), "text/calendar")]}


def msg_pantry():
    with db() as c:
        items = list_pantry(c)
    lines = [f"• {i['name']} ({i['location']}) — use by {i['expires_on'] or '?'}" for i in items]
    return {"subject": f"🥫 Pantry — {datetime.now().strftime('%b %d')}",
            "text": "\n".join(lines) or "Pantry is empty.",
            "html": email_wrap(f"<style>{PRINT_CSS}</style>{_print_body(print_pantry(items))}"),
            "files": [("pantry.csv", render_pantry_csv(items).encode(), "text/csv")]}


def msg_expiring(items):
    def when(i):
        d = i["days_left"]
        return "expired" if d < 0 else "today" if d == 0 else "tomorrow" if d == 1 else f"in {d} days"
    lines = [f"• {i['name']} — {when(i)}" for i in items]
    return {"subject": f"🥛 Use soon: {len(items)} item{'s' if len(items) != 1 else ''}",
            "text": "\n".join(lines) + "\n\nOpen TablePlan → Pantry to log what you used.",
            "html": email_wrap("<h2>Use soon</h2><ul>" + "".join(f"<li>{html.escape(l[2:])}</li>" for l in lines) + "</ul>"),
            "files": []}


def msg_test(channel):
    return {"subject": "✅ TablePlan notifications are working",
            "text": f"This {channel} channel will receive shopping lists, meal plans and use-soon alerts.",
            "html": email_wrap("<h2>TablePlan email is working ✓</h2><p>Shopping lists, meal plans and use-soon alerts will arrive here.</p>"),
            "files": []}


def channels_ready():
    return {"email": email_ready(),
            "telegram": bool(cfg("telegram_token") and cfg("telegram_chat_id")),
            "ntfy": bool(cfg("ntfy_topic"))}


def deliver(msg, channel="all"):
    """Send a message to one channel or every configured one. Returns the channels that got it."""
    ready = channels_ready()
    targets = [c for c, ok in ready.items() if ok] if channel == "all" else [channel]
    if not targets:
        raise ApiError(400, "No notifications set up yet. Open Settings → Notifications.")
    sent, errors = [], []
    for ch in targets:
        if not ready.get(ch):
            raise ApiError(400, f"{ch.title()} isn't set up yet. Open Settings → Notifications.")
        try:
            {"email": _send_email_msg, "telegram": telegram_send, "ntfy": ntfy_send}[ch](msg)
            sent.append(ch)
        except ApiError as e:
            errors.append(f"{ch}: {e.message}")
    if errors and not sent:
        raise ApiError(502, "; ".join(errors))
    return {"sent": sent, "errors": errors}


def _send_email_msg(msg):
    send_email(msg["subject"], msg["text"], msg["html"], msg["files"])


def build_msg(b):
    kind = b.get("kind")
    if kind == "list":
        return msg_list(b["id"])
    if kind == "plan":
        return msg_plan(*date_range(b.get("start"), b.get("end")))
    if kind == "pantry":
        return msg_pantry()
    if kind == "test":
        return msg_test(b.get("channel") or "notification")
    if kind == "recipe":
        return msg_recipe(_slug_arg(b.get("slug")), _servings_arg(b.get("servings")))
    raise ApiError(400, "Unknown message kind")


# ---- shared HTTP helpers for notification APIs

def _multipart(fields, files):
    boundary = "----tableplan" + base64.b16encode(os.urandom(8)).decode()
    parts = []
    for k, v in fields.items():
        if v is None:
            continue
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, fname, ctype, blob in files:
        safe = re.sub(r'[^A-Za-z0-9._-]', '_', fname or "file")
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{safe}"\r\n'
                     f'Content-Type: {ctype}\r\n\r\n'.encode() + blob + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _https_json(url, payload=None, headers=None, data=None, ctype=None, timeout=20, method=None, allow_private=False,
                max_bytes=10_000_000):
    h = {"User-Agent": f"TablePlan/{APP_VERSION}", "Accept": "application/json", **(headers or {})}
    if payload is not None:
        data, ctype = json.dumps(payload).encode(), "application/json"
    if ctype:
        h["Content-Type"] = ctype
    try:
        with _open(url, data=data, headers=h, method=method or ("POST" if data is not None else "GET"),
                   timeout=timeout, allow_private=allow_private) as r:   # TLS certificates are verified by default
            raw = _read_capped(r, max_bytes, max(timeout, 60))
        try:
            out = json.loads(raw) if raw else {}
        except ValueError:
            raise ApiError(502, "The service sent an unreadable reply.")
        return out if isinstance(out, dict) else {"data": out}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read(65536).decode("utf-8", "replace"))
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        err = body.get("description") or body.get("error") or body.get("message")
        if isinstance(err, dict):
            err = err.get("message")
        exc = ApiError(502, str(err)[:300] if err else f"HTTP {e.code}")
        exc.http_status = e.code
        raise exc
    except BlockedURL as e:
        raise ApiError(400, f"That server address isn't allowed ({e}).")
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
        raise ApiError(502, f"Couldn't connect ({getattr(e, 'reason', e)})")
    except ValueError as e:   # response too large
        raise ApiError(502, f"Couldn't read the reply ({e})")


# ---- Telegram (bot API, outbound only: no webhook, nothing exposed to the internet)

TELEGRAM_API = env("TELEGRAM_API_URL", "https://api.telegram.org").rstrip("/")   # override only for a self-hosted Bot API server
TELEGRAM_TOKEN_RE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,64}$")


def _tg(method, token=None, **kw):
    token = token or cfg("telegram_token")
    if not token:
        raise ApiError(400, "Telegram isn't set up.")
    # A self-hosted Bot API server (TELEGRAM_API_URL, set by the operator) may live on the home network.
    res = _https_json(f"{TELEGRAM_API}/bot{token}/{method}", allow_private=TELEGRAM_API != "https://api.telegram.org", **kw)
    if not res.get("ok", False):
        raise ApiError(502, res.get("description") or "Telegram error")
    return res.get("result")


def telegram_set_token(token):
    token = (token or "").strip()
    if not TELEGRAM_TOKEN_RE.match(token):
        raise ApiError(400, "That doesn't look like a bot token. It's the long code BotFather sends, like 123456789:AAH…")
    try:
        me = _tg("getMe", token=token)
    except ApiError:
        raise ApiError(400, "Telegram didn't accept that token. Copy it again from BotFather.")
    code = "".join(random.SystemRandom().choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    set_cfg(telegram_token=token, telegram_bot=me.get("username", ""), telegram_chat_id="", telegram_chat_name="",
            telegram_link_code=code, telegram_link_expires=int(time.time()) + 900)
    return telegram_public(with_code=True)


def telegram_verify():
    code, exp = cfg("telegram_link_code"), int(cfg("telegram_link_expires") or 0)
    if not code or time.time() > exp:
        raise ApiError(400, "The link code expired. Tap “Start over” to get a new one.")
    updates = _tg("getUpdates", payload={"timeout": 0, "allowed_updates": ["message"]}) or []
    match, last = None, 0
    for u in updates:
        last = max(last, u.get("update_id", 0))
        m = u.get("message") or {}
        if code in (m.get("text") or "").upper():
            match = m.get("chat") or {}
    if last:
        _tg("getUpdates", payload={"offset": last + 1, "timeout": 0})   # acknowledge so old messages aren't re-read
    if not match:
        raise ApiError(404, "Haven't seen the code yet. Send it to your bot in Telegram, then tap Check again.")
    name = match.get("title") or " ".join(x for x in (match.get("first_name"), match.get("last_name")) if x) or "your chat"
    set_cfg(telegram_chat_id=str(match["id"]), telegram_chat_name=name, telegram_link_code="", telegram_link_expires=0)
    telegram_send(msg_test("Telegram"))
    return telegram_public()


def telegram_send(msg):
    chat = cfg("telegram_chat_id")
    text = f"<b>{html.escape(msg['subject'])}</b>\n\n{html.escape(msg['text'])}"
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 3900:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    chunks.append(cur)
    for ch in chunks:
        if ch.strip():
            _tg("sendMessage", payload={"chat_id": chat, "text": ch.rstrip("\n"), "parse_mode": "HTML",
                                        "disable_web_page_preview": True})
    for fname, blob, ctype in msg.get("files") or []:
        if fname.endswith(".ics"):   # calendar file is the useful one on a phone; CSVs stay for email
            data, ct = _multipart({"chat_id": chat}, [("document", fname, ctype, blob)])
            _tg("sendDocument", data=data, ctype=ct)


def telegram_public(with_code=False):
    out = {"configured": channels_ready()["telegram"], "has_token": bool(cfg("telegram_token")),
           "bot": cfg("telegram_bot"), "chat": cfg("telegram_chat_name")}
    if with_code or (cfg("telegram_link_code") and time.time() < int(cfg("telegram_link_expires") or 0)):
        out["code"] = cfg("telegram_link_code")
        out["link"] = f"https://t.me/{cfg('telegram_bot')}?start={cfg('telegram_link_code')}"
    return out


# ---- ntfy (push notifications; self-hosted or ntfy.sh)

def ntfy_send(msg, conf=None):
    c = conf or {"ntfy_server": cfg("ntfy_server"), "ntfy_topic": cfg("ntfy_topic"), "ntfy_token": cfg("ntfy_token")}
    server = (c["ntfy_server"] or "https://ntfy.sh").rstrip("/")
    body = msg["text"]
    if len(body.encode()) > 3800:
        body = body.encode()[:3700].decode("utf-8", "ignore") + "\n… (open TablePlan for the rest)"
    headers = {"Authorization": f"Bearer {c['ntfy_token']}"} if c.get("ntfy_token") else {}
    # On the home network a self-hosted ntfy may be on a LAN address; on the internet only public servers are allowed.
    _https_json(server + "/", payload={"topic": c["ntfy_topic"], "title": msg["subject"], "message": body,
                                        "tags": ["fork_and_knife"]}, headers=headers, allow_private=not PUBLIC_MODE)


def ntfy_setup(b):
    server = _s(b.get("server")) or "https://ntfy.sh"
    server = server.strip().rstrip("/")
    if PUBLIC_MODE and not (re.match(r"^https://[^\s/@]+", server) and _public_host(server)):
        raise ApiError(400, "Use a public https:// ntfy server (like https://ntfy.sh).")
    if not re.match(r"^https://[^\s/@]+", server) and not re.match(r"^http://(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|[^./@]+(:\d+)?$)", server):
        raise ApiError(400, "Use an https:// ntfy server (plain http is only allowed for servers on your home network).")
    topic = _s(b.get("topic")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", topic):
        raise ApiError(400, "Topic must be 8–64 letters, numbers, - or _. Use the random one suggested.")
    token = _s(b.get("token")).strip()
    if token and not re.fullmatch(r"[\x21-\x7e]{1,200}", token):
        raise ApiError(400, "That access token doesn't look right.")
    if "ntfy.sh" in server and len(topic) < 20 and not token:
        raise ApiError(400, "On the public ntfy.sh server anyone who guesses the topic can read it. Use the long random topic, or add an access token.")
    # Keep the saved token only for the same server, so it's never sent to a different one.
    keep = cfg("ntfy_token") if (cfg("ntfy_server") or "https://ntfy.sh").rstrip("/") == server else ""
    conf = {"ntfy_server": server, "ntfy_topic": topic, "ntfy_token": token or keep or ""}
    ntfy_send(msg_test("ntfy"), conf)
    set_cfg(**conf)
    return ntfy_public()


def ntfy_public():
    return {"configured": channels_ready()["ntfy"], "server": cfg("ntfy_server"), "topic": cfg("ntfy_topic"),
            "has_token": bool(cfg("ntfy_token")),
            "suggested_topic": "tableplan-" + base64.b32encode(os.urandom(10)).decode().lower().rstrip("=")}


def notify_status():
    return {"channels": channels_ready(), "email": email_public(), "telegram": telegram_public(), "ntfy": ntfy_public()}


# ============================================================ setup: Mealie account, AI, email

def mealie_status():
    if NATIVE:
        return {"native": True, "connected": True, "reachable": True, "error": None}
    out = {"url": cfg("mealie_url"), "public_url": mealie_public(), "public_url_set": bool(cfg("mealie_public_url")),
           "reachable": False, "connected": False, "first_login": False,
           "version": None, "user": None, "group_slug": cfg("group_slug"), "error": None}
    try:
        about = mealie_raw("GET", "/api/app/about", timeout=8)
        out["reachable"] = True
        out["version"] = (about or {}).get("version")
        info = mealie_raw("GET", "/api/app/about/startup-info", timeout=8) or {}
        out["first_login"] = bool(info.get("isFirstLogin"))
    except ApiError as e:
        out["error"] = e.message
        return out
    if cfg("mealie_token"):
        try:
            me = mealie_raw("GET", "/api/users/self", token=cfg("mealie_token"), timeout=8)
            out["connected"] = True
            out["user"] = {"name": me.get("fullName") or me.get("username"), "email": me.get("email"),
                           "admin": bool(me.get("admin"))}
            if me.get("groupSlug") and me["groupSlug"] != cfg("group_slug"):
                set_cfg(group_slug=me["groupSlug"])
            out["group_slug"] = cfg("group_slug")
        except ApiError as e:
            out["error"] = "Saved Mealie token no longer works — reconnect below."
    return out


def _mealie_login(email, password):
    try:
        tok = mealie_raw("POST", "/api/auth/token", form={"username": email, "password": password, "remember_me": "false"})
    except MealieHTTPError as e:
        if e.code in (401, 423):
            raise ApiError(400, "Mealie didn't accept that email and password." if e.code == 401
                           else "Mealie has locked this account after too many tries — wait a few minutes.")
        raise
    return tok["access_token"]


def _issue_api_token(session_token):
    name = f"tableplan-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    res = mealie_raw("POST", "/api/users/api-tokens", body={"name": name}, token=session_token)
    return res["token"]


def _finish_connect(api_token):
    me = mealie_raw("GET", "/api/users/self", token=api_token)
    set_cfg(mealie_token=api_token, group_slug=me.get("groupSlug") or cfg("group_slug"))
    _recipe_cache["at"] = 0
    return me


def mealie_create_account(full_name, email, password):
    """First run: take over Mealie's default account (changeme@example.com) and make it the household's."""
    if len(password or "") < 8:
        raise ApiError(400, "Use a password with at least 8 characters.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""):
        raise ApiError(400, "Enter a valid email address.")
    st = mealie_status()
    if not st["reachable"]:
        raise ApiError(502, st["error"] or "Mealie isn't reachable yet — give it a minute after first start.")
    if not st["first_login"]:
        raise ApiError(409, "This Mealie already has an account — sign in with it instead.")
    session = _mealie_login("changeme@example.com", "MyPassword")
    api_token = _issue_api_token(session)            # get a durable token before changing credentials
    me = mealie_raw("GET", "/api/users/self", token=session)
    upd = {k: me.get(k) for k in ("id", "username", "fullName", "email", "authMethod", "admin", "group",
                                  "household", "advanced", "canInvite", "canManage", "canManageHousehold",
                                  "canOrganize", "showAnnouncements", "lastReadAnnouncement") if k in me}
    upd.update(email=email.strip().lower(), fullName=full_name.strip() or "Household",
               username=(full_name.strip() or email.split("@")[0]).lower().replace(" ", ""))
    mealie_raw("PUT", f"/api/users/{me['id']}", body=upd, token=session)
    mealie_raw("PUT", "/api/users/password", body={"currentPassword": "MyPassword", "newPassword": password}, token=session)
    _finish_connect(api_token)
    return mealie_status()


def mealie_sign_in(email, password):
    session = _mealie_login(email.strip(), password)
    _finish_connect(_issue_api_token(session))
    return mealie_status()


def mealie_use_token(token, url=None):
    if url:
        set_cfg(mealie_url=url.rstrip("/"))
    try:
        mealie_raw("GET", "/api/users/self", token=token.strip())
    except MealieHTTPError as e:
        raise ApiError(400, "That token didn't work." if e.code in (401, 403) else e.message)
    _finish_connect(token.strip())
    return mealie_status()


def ai_status():
    if NATIVE:
        on = bool(cfg("openai_key"))
        return {"available": True, "enabled": on, "images": on, "audio": False,
                "providers": ["OpenAI"] if on else [], "model": cfg("openai_model") or "gpt-5-mini"}
    if not cfg("mealie_token"):
        return {"available": False, "enabled": False}
    try:
        s = mealie("GET", "/api/groups/ai-providers/settings")
    except ApiError as e:
        return {"available": False, "enabled": False, "error": e.message}
    enabled = bool(s.get("aiEnabled", s.get("defaultProviderId")))
    return {"available": True, "enabled": enabled,
            "images": bool(s.get("imageProviderEnabled", enabled and s.get("imageProviderId"))),
            "audio": bool(s.get("audioProviderEnabled", enabled and s.get("audioProviderId"))),
            "providers": [p.get("name") for p in s.get("providers") or []]}


def ai_setup(api_key, model, audio, base_url=None):
    api_key = _s(api_key, 400).strip()
    model = _s(model, 64).strip() or "gpt-5-mini"
    if not api_key:
        raise ApiError(400, "Paste your OpenAI API key.")
    if not re.fullmatch(r"[\x21-\x7e]+", api_key):
        raise ApiError(400, "That doesn't look like an OpenAI API key.")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", model):
        raise ApiError(400, "That model name doesn't look right (for example gpt-5-mini).")
    if base_url is not None and not isinstance(base_url, str):
        raise ApiError(400, "Expected text.")
    if NATIVE:
        try:
            _https_json(f"https://api.openai.com/v1/models/{_q(model)}", headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
        except ApiError as e:
            raise ApiError(400, f"OpenAI didn't accept that key or model ({e.message}).")
        set_cfg(openai_key=api_key, openai_model=model)
        return {**ai_status(), "supports_images": True}
    provider = {"name": "OpenAI", "baseUrl": base_url or None, "apiKey": api_key, "model": model, "timeout": 300,
                "requestHeaders": {}, "requestParams": {}}
    test = mealie("POST", "/api/groups/ai-providers/providers/test", provider, timeout=90)
    if not test.get("success"):
        raise ApiError(400, f"OpenAI test failed: {test.get('message') or 'check the key and model name'}")
    current = mealie("GET", "/api/groups/ai-providers/settings")
    existing = {p["name"]: p["id"] for p in current.get("providers") or []}

    def upsert(data):
        if data["name"] in existing:
            return mealie("PUT", f"/api/groups/ai-providers/providers/{existing[data['name']]}", data)["id"]
        return mealie("POST", "/api/groups/ai-providers/providers", data)["id"]

    main_id = upsert(provider)
    set_cfg(openai_key=api_key, openai_model=model)
    audio_id = None
    if audio:
        audio_id = upsert({**provider, "name": "OpenAI Whisper", "model": "whisper-1"})
    mealie("PUT", "/api/groups/ai-providers/settings", {
        "defaultProviderId": main_id,
        "imageProviderId": main_id if (VISION_MODELS.match(model) or test.get("supportsImages") is not False) else None,
        "audioProviderId": audio_id})
    st = ai_status()
    st["supports_images"] = test.get("supportsImages")
    return st


SMTP_PRESETS = {
    "gmail": {"smtp_host": "smtp.gmail.com", "smtp_port": 587, "smtp_security": "starttls"},
    "outlook": {"smtp_host": "smtp.office365.com", "smtp_port": 587, "smtp_security": "starttls"},
    "icloud": {"smtp_host": "smtp.mail.me.com", "smtp_port": 587, "smtp_security": "starttls"},
    "yahoo": {"smtp_host": "smtp.mail.yahoo.com", "smtp_port": 465, "smtp_security": "ssl"},
}


EMAIL_RE = re.compile(r"[^@\s<>,;\"']{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,63}")


def email_setup(b):
    conf = {**SMTP_PRESETS.get(_s(b.get("preset")), {})}
    for k in ("smtp_host", "smtp_port", "smtp_security", "smtp_user", "smtp_from"):
        if b.get(k) not in (None, ""):
            conf[k] = b[k] if k == "smtp_port" else _s(b[k], 254).strip()
    conf.setdefault("smtp_port", 587)
    conf.setdefault("smtp_security", "starttls")
    try:
        conf["smtp_port"] = _v_int(1, 65535)(conf["smtp_port"])
    except (ValueError, TypeError):
        raise ApiError(400, "The SMTP port must be a number between 1 and 65535.")
    if conf["smtp_security"] not in ("starttls", "ssl", "none"):
        raise ApiError(400, "Security must be starttls, ssl or none.")
    if not conf.get("smtp_host"):
        raise ApiError(400, "Pick your email provider or enter the SMTP server.")
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}|\[[0-9A-Fa-f:.]+\]", conf["smtp_host"]):
        raise ApiError(400, "Enter the SMTP server name, like smtp.gmail.com.")
    if PUBLIC_MODE and not _public_host(f"https://{conf['smtp_host']}"):
        raise ApiError(400, "That email server isn't on the public internet.")
    if re.search(r"[\r\n]", conf.get("smtp_user") or ""):
        raise ApiError(400, "That username doesn't look right.")
    # A saved password is only reused for the same server and user, so it's never sent anywhere new.
    same = conf["smtp_host"] == cfg("smtp_host") and (conf.get("smtp_user") or "") == (cfg("smtp_user") or "")
    conf["smtp_password"] = _s(b.get("smtp_password"), 1024) or (cfg("smtp_password") if same else "")
    conf["smtp_from"] = conf.get("smtp_from") or conf.get("smtp_user")
    if conf["smtp_from"] and not EMAIL_RE.fullmatch(conf["smtp_from"]):
        raise ApiError(400, "The From address doesn't look like an email address.")
    to = b.get("mail_to")
    if isinstance(to, str):
        to = [a.strip() for a in re.split(r"[,;\s]+", to) if a.strip()]
    if to is not None and not (isinstance(to, list) and all(isinstance(a, str) for a in to)):
        raise ApiError(400, "Add the addresses to send to, separated by commas.")
    conf["mail_to"] = to or ([conf["smtp_from"]] if conf.get("smtp_from") else [])
    if len(conf["mail_to"]) > 20 or not all(EMAIL_RE.fullmatch(a) for a in conf["mail_to"]):
        raise ApiError(400, "One of those addresses doesn't look like an email address (20 max).")
    if not conf["mail_to"]:
        raise ApiError(400, "Add at least one address to send lists to.")
    if b.get("test", True):
        send_email("TablePlan email is working ✓", "TablePlan can send you shopping lists and meal plans.",
                   email_wrap("<h2>TablePlan email is working ✓</h2><p>Shopping lists, meal plans and pantry reports will arrive here.</p>"),
                   conf=conf)
    set_cfg(**conf)
    return email_public()


def email_public():
    return {"configured": email_ready(), "host": cfg("smtp_host"), "port": cfg("smtp_port"),
            "security": cfg("smtp_security"), "user": cfg("smtp_user"), "from": cfg("smtp_from"),
            "to": cfg("mail_to") or [], "has_password": bool(cfg("smtp_password"))}


def setup_status():
    return {"setup_complete": bool(cfg("setup_complete")),
            "household": {"name": cfg("household_name"), "people": cfg("people"), "scale": bool(cfg("scale_to_household"))},
            "mealie": mealie_status(), "ai": ai_status(), "email": email_public(), "notify": notify_status(),
            "password": {"set": auth_required()}, "version": APP_VERSION}


# ============================================================ recipe import (headless Mealie)

def import_url(url):
    url = (url or "").strip()
    m = re.search(r"https?://\S+", url)   # share sheets often send "Check this out! https://…"
    url = m.group(0).rstrip(").,") if m else url
    if not re.match(r"^https?://", url):
        raise ApiError(400, "Paste a full link starting with https://")
    if NATIVE and GDOC_RE.match(url):
        return import_gdoc(url)
    if NATIVE and VIDEO_HOSTS.search(urllib.parse.urlparse(url).hostname or ""):
        return import_video(url)
    slug = mealie("POST", "/api/recipes/create/url", {"url": url, "includeTags": True}, timeout=180)
    return _imported(slug)


def import_images(images, text=None):
    if not images and not text:
        raise ApiError(400, "Add at least one photo or screenshot.")
    if not ai_status().get("enabled"):
        raise ApiError(400, "Screenshot import needs AI — add your OpenAI key in Settings → AI recipe import.")
    if not isinstance(images, list) or not all(isinstance(im, dict) and isinstance(im.get("data"), str) for im in images):
        raise ApiError(400, "Expected a list of images.")
    text = _s(text, 40000) or None
    for im in images:   # only images and PDFs go to the AI
        head = im["data"][:40]
        if head.startswith("data:") and not re.match(r"data:(image/(jpeg|jpg|png|webp|gif|heic|heif)|application/pdf);base64,", head):
            raise ApiError(400, "Upload photos, screenshots or PDFs.")
        if not isinstance(im.get("name"), (str, type(None))) or not isinstance(im.get("type"), (str, type(None))):
            raise ApiError(400, "Expected a list of images.")
    files = []
    total = 0
    for i, im in enumerate(images[:8]):
        try:
            blob = base64.b64decode(im["data"].split(",", 1)[-1])
        except ValueError:
            raise ApiError(400, "One of those files couldn't be read.")
        total += len(blob)
        if total > 25_000_000:
            raise ApiError(413, "Those images are too large together (25 MB max).")
        ctype = im.get("type") if re.fullmatch(r"image/[a-z0-9.+-]{1,40}", im.get("type") or "") else "image/jpeg"
        files.append(("images", im.get("name") or f"image{i}.jpg", ctype, blob))
    if NATIVE:
        data = ai_recipe(text or "", images[:8], "screenshot import", f"{len(images[:8])} image(s)")
        slug = _save_new_recipe(data)
        if data.get("orgURL"):   # the screenshot showed the web address: fetch that page's photo in the background
            background(recipe_image_next, slug)
        return _imported(slug)
    if cfg("openai_key"):
        transcript = transcribe_images(images, text)
        slug = mealie("POST", "/api/recipes/create/ai", multipart=({"content": transcript}, []), timeout=300)
        return _imported(slug)
    ensure_image_provider()
    try:
        slug = mealie("POST", "/api/recipes/create/ai", multipart=({"content": text or None}, files), timeout=300)
    except ApiError as e:
        if re.search(r"unreadable|unable to read|image provider", str(e.message if hasattr(e, "message") else e), re.I):
            raise ApiError(400, "Couldn't read that screenshot. Open Settings → AI recipe import, paste your OpenAI key "
                                "again and tap Save, then try once more.")
        raise
    return _imported(slug)


# ============================================================ plain-text ingredient parsing (scales without Mealie's parser)

_UFRAC = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5",
          "⅙": "1/6", "⅚": "5/6", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8"}
_UNITS = {}
for _sing, _plur, _aliases in [
    ("cup", "cups", "c cup cups"), ("tbsp", "tbsp", "tbsp tbsps tbs tbl tablespoon tablespoons T"),
    ("tsp", "tsp", "tsp tsps teaspoon teaspoons t"), ("oz", "oz", "oz ounce ounces"), ("fl oz", "fl oz", "floz"),
    ("lb", "lb", "lb lbs pound pounds"), ("g", "g", "g gram grams gr"), ("kg", "kg", "kg kilogram kilograms"),
    ("ml", "ml", "ml milliliter milliliters millilitre millilitres"), ("l", "l", "l liter liters litre litres"),
    ("pinch", "pinches", "pinch pinches"), ("dash", "dashes", "dash dashes"), ("clove", "cloves", "clove cloves"),
    ("can", "cans", "can cans"), ("package", "packages", "package packages pkg pkgs"), ("stick", "sticks", "stick sticks"),
    ("slice", "slices", "slice slices"), ("quart", "quarts", "quart quarts qt qts"), ("pint", "pints", "pint pints pt"),
    ("gallon", "gallons", "gallon gallons gal"), ("bunch", "bunches", "bunch bunches"), ("sprig", "sprigs", "sprig sprigs"),
    ("head", "heads", "head heads"), ("jar", "jars", "jar jars"), ("bag", "bags", "bag bags"), ("box", "boxes", "box boxes"),
    ("handful", "handfuls", "handful handfuls"), ("piece", "pieces", "piece pieces pc pcs"), ("stalk", "stalks", "stalk stalks"),
    ("splash", "splashes", "splash splashes"), ("drizzle", "drizzles", "drizzle drizzles"),
]:
    for _a in _aliases.split():
        _UNITS[_a if _a in ("T", "t") else _a.lower()] = (_sing, _plur)
_QTY = r"(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_ING_RE = re.compile(rf"^\s*{_QTY}(?:\s*(?:-|–|to)\s*{_QTY})?\s*(?:\(([^)]*)\)\s*)?([A-Za-z]+\.?)?\s*(?:of\s+)?(.*)$")
_DESCRIPTORS = re.compile(r"\b(large|small|medium|fresh|freshly|chopped|minced|diced|sliced|grated|shredded|ground|finely|roughly|"
                          r"thinly|peeled|softened|melted|room temperature|packed|heaping|level|boneless|skinless|optional)\b", re.I)


def _qty_val(s):
    s = s.strip()
    if " " in s:
        a, b = s.split(None, 1)
        return float(a) + _qty_val(b)
    if "/" in s:
        n, d = s.split("/")
        return float(n) / float(d)  # ZeroDivisionError on "1/0" is caught by the caller
    return float(s)


# Amounts without a number: "pinch of salt", "a dash of hot sauce", "salt to taste", "a few sprigs of thyme".
_WORD_UNITS = ("pinch", "dash", "handful", "splash", "drizzle", "sprinkle")
_WORD_AMT_RE = re.compile(r"^\s*(?:an?\s+)?(pinch(?:es)?|dash(?:es)?|handful(?:s)?|splash(?:es)?|drizzle|sprinkle)\s+(?:of\s+)?(.+)$", re.I)
_VAGUE_RE = re.compile(r"^\s*(some|a few|a couple(?: of)?|a little|a bit of|several)\s+(?:of\s+)?(.+)$", re.I)
_TO_TASTE_RE = re.compile(r"^(.*?)[,\s]*\b(to taste|as needed|for serving|for garnish|optional)\s*\.?$", re.I)
_PREP_WORDS = re.compile(r"^(minced|chopped|diced|sliced|grated|shredded|softened|melted|divided|crushed|peeled|beaten|cubed|"
                         r"halved|quartered|julienned|drained|rinsed|thinly sliced|finely chopped|roughly chopped|at room temperature|"
                         r"room temperature|cut into [^,]+|plus more[^,]*|or to taste)$", re.I)


def _split_note(rest):
    """'heavy cream, divided' -> ('heavy cream', 'divided'); trailing '(optional)' style notes too."""
    food, _, note = rest.partition(",")
    return food.strip(" -"), note.strip()


def parse_ing_text(text):
    """'1 ½ cups heavy cream, divided' -> {quantity:1.5, unit:'cup', unit_plural:'cups', food:'heavy cream', note:'divided'}.
    Number-less amounts set amount_text: 'pinch of salt' -> {quantity:1, unit:'pinch', food:'salt', amount_text:'pinch'},
    'salt to taste' -> {quantity:0, unit:'', food:'salt', amount_text:'to taste'}. Scaling never touches amount_text."""
    t = (text or "").strip()
    for k, v in _UFRAC.items():
        t = re.sub(rf"(\d)\s*{k}", rf"\1 {v}", t).replace(k, v)
    m = _ING_RE.match(t)
    if not m:
        return _parse_wordy(t)
    try:
        q = _qty_val(m.group(1))
    except (ValueError, ZeroDivisionError):
        return None
    if not q or q <= 0:
        return None
    paren, word, rest = m.group(3), m.group(4) or "", (m.group(5) or "").strip()
    unit = _UNITS.get(word.rstrip(".") if word.rstrip(".") in ("T", "t") else word.rstrip(".").lower())
    if not unit:
        rest = (word + " " + rest).strip() if word else rest
    if paren and not unit:
        rest = f"({paren}) {rest}".strip()
    rest = re.sub(r"^of\s+", "", rest, flags=re.I)
    food, note = _split_note(rest)
    if not food:
        return None
    return {"quantity": q, "unit": unit[0] if unit else "", "unit_plural": unit[1] if unit else "",
            "food": food, "note": note, "size": (paren or "") if unit else "", "amount_text": ""}


def _parse_wordy(t):
    """Lines with no number: word amounts ("pinch of"), vague ones ("some"), or "to taste"."""
    if not t:
        return None
    m = _WORD_AMT_RE.match(t)
    if m:
        u = _UNITS.get(m.group(1).lower(), (m.group(1).lower(), m.group(1).lower()))
        tt = _TO_TASTE_RE.match(m.group(2))
        food, note = _split_note(tt.group(1) if tt and tt.group(1).strip() else m.group(2))
        if food:
            return {"quantity": 1.0, "unit": u[0], "unit_plural": u[1], "food": food, "note": note, "size": "",
                    "amount_text": u[0]}
    m = _VAGUE_RE.match(t)
    if m:
        rest = m.group(2)
        unit = None
        w = rest.split(None, 1)
        if len(w) == 2 and w[0].lower() in _UNITS:   # "a few sprigs of thyme"
            unit, rest = _UNITS[w[0].lower()], re.sub(r"^of\s+", "", w[1], flags=re.I)
        food, note = _split_note(rest)
        if food:
            amt = m.group(1).lower().replace(" of", "") + (f" {unit[1]}" if unit else "")
            return {"quantity": 0, "unit": "", "unit_plural": "", "food": food, "note": note, "size": "", "amount_text": amt}
    m = _TO_TASTE_RE.match(t)
    if m and m.group(1).strip():
        food, note = _split_note(m.group(1))
        if food:
            return {"quantity": 0, "unit": "", "unit_plural": "", "food": food, "note": note, "size": "",
                    "amount_text": m.group(2).lower()}
    return None


def split_foods(p):
    """'salt and pepper' (no amount) -> two parses, 'salt' and 'pepper', sharing the amount text."""
    if not p or p.get("quantity") and not p.get("amount_text"):
        return [p] if p else []
    parts = [x.strip() for x in re.split(r"\s+(?:and|&)\s+", p["food"]) if x.strip()]
    if len(parts) == 2 and all(len(x.split()) <= 2 for x in parts):
        return [dict(p, food=x) for x in parts]
    return [p]


def sentence_case(s):
    """'all-purpose flour' -> 'All-purpose flour'; keeps words with capitals inside (e.g. 'Dijon', 'BBQ')."""
    s = " ".join((s or "").split())
    return s[:1].upper() + s[1:] if s else s


_SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with", "en", "de", "e"}


def title_case(name):
    """Recipe names in title case: 'chicken tikka masala with naan' -> 'Chicken Tikka Masala with Naan'.
    Small words stay lowercase unless first or last; acronyms (BBQ) and inner capitals (McDonald's, iPhone) are kept;
    hyphenated parts ('Slow-Cooker') and apostrophes ("Grandma's") are handled."""
    words = " ".join(str(name or "").split()).split(" ")
    if words == [""]:
        return ""
    out = []
    for i, w in enumerate(words):
        first, last = i == 0, i == len(words) - 1
        parts = w.split("-")
        fixed = []
        for j, part in enumerate(parts):
            m = re.match(r"^([^A-Za-z]*)([A-Za-z][A-Za-z']*)(.*)$", part)
            if not m:
                fixed.append(part)
                continue
            pre, core, post = m.groups()
            low = core.lower()
            if (core.isupper() and len(core) > 1) or any(ch.isupper() for ch in core[1:]):
                fixed.append(part)            # BBQ, BLT, McDonald's, iPhone
            elif low in _SMALL_WORDS and not (first and j == 0) and not (last and j == len(parts) - 1) and not pre:
                fixed.append(pre + low + post)
            else:
                fixed.append(pre + low[:1].upper() + low[1:] + post)
        out.append("-".join(fixed))
    return " ".join(out)


def clean_food(name):
    n = re.sub(r"\([^)]*\)", " ", name or "")
    n = _DESCRIPTORS.sub(" ", n)
    n = re.split(r"\bor\b|,|;", n)[0]
    return re.sub(r"\s+", " ", n).strip(" -.") or (name or "").strip()


# ============================================================ in-app recipe editing (saves to Mealie)

def _category_arg(v):
    """Validated category names (from the settings list, in its spelling and order)."""
    if not isinstance(v, list) or len(v) > MAX_CATEGORIES:
        raise ApiError(400, "Send categories as a list of names.")
    known = {c.lower(): c for c in get_settings()["categories"]}
    want = set()
    for x in v:
        if not isinstance(x, str) or " ".join(x.split()).lower() not in known:
            raise ApiError(400, f"Unknown category: {str(x)[:40]}")
        want.add(" ".join(x.split()).lower())
    return [c for c in get_settings()["categories"] if c.lower() in want]


def _set_categories(c, rec, names):
    rec = dict(rec, recipeCategory=[{"name": n} for n in names])
    return n_recipes.update(c, rec["id"], rec)


def _rec_categories(rec):
    return [x.get("name") for x in rec.get("recipeCategory") or [] if isinstance(x, dict) and x.get("name")]


def recipes_bulk(b):
    """POST /api/recipes/bulk {slugs, categories}: set the categories of many recipes at once."""
    require_native()
    slugs = b.get("slugs")
    if not isinstance(slugs, list) or not 1 <= len(slugs) <= 2000 or not all(isinstance(x, str) for x in slugs):
        raise ApiError(400, "Pick at least one recipe.")
    names = _category_arg(b.get("categories"))
    n = 0
    with db() as c:
        for slug in slugs:
            rec = n_recipes.get(c, slug)
            if rec:
                _set_categories(c, rec, names)
                n += 1
    _recipe_cache["at"] = 0
    return {"ok": True, "updated": n}


def category_rename(b):
    """Rename a category in settings and in every recipe that uses it."""
    require_native()
    old, new = " ".join(_s(b.get("from"), 60).split()), " ".join(_s(b.get("to"), 60).split())
    cats = get_settings()["categories"]
    idx = next((i for i, x in enumerate(cats) if x.lower() == old.lower()), None)
    if idx is None:
        raise ApiError(404, "Category not found")
    cats = list(cats)
    cats[idx] = new
    save_settings({"categories": cats})   # validates the new name (length, duplicates)
    n = 0
    with db() as c:
        for rec in n_recipes.list_summaries(c):
            names = _rec_categories(rec)
            if any(x.lower() == old.lower() for x in names):
                full = n_recipes.get(c, rec["id"])
                _set_categories(c, full, [new if x.lower() == old.lower() else x for x in _rec_categories(full)])
                n += 1
    _recipe_cache["at"] = 0
    return {"ok": True, "categories": cats, "recipes": n}


def category_delete(b):
    """Delete a category from settings and recipes. Returns what Undo needs."""
    require_native()
    name = " ".join(_s(b.get("name"), 60).split())
    cats = list(get_settings()["categories"])
    idx = next((i for i, x in enumerate(cats) if x.lower() == name.lower()), None)
    if idx is None:
        raise ApiError(404, "Category not found")
    name = cats.pop(idx)
    save_settings({"categories": cats})
    slugs = []
    with db() as c:
        for rec in n_recipes.list_summaries(c):
            if any(x.lower() == name.lower() for x in _rec_categories(rec)):
                full = n_recipes.get(c, rec["id"])
                slugs.append(_set_categories(c, full, [x for x in _rec_categories(full) if x.lower() != name.lower()]))
    _recipe_cache["at"] = 0
    return {"ok": True, "categories": cats, "undo": {"name": name, "position": idx, "slugs": slugs}}


def category_undo_delete(b):
    require_native()
    name = " ".join(_s(b.get("name"), 60).split())
    pos = b.get("position")
    pos = pos if isinstance(pos, int) and not isinstance(pos, bool) and pos >= 0 else 10_000
    slugs = b.get("slugs") if isinstance(b.get("slugs"), list) else []
    cats = list(get_settings()["categories"])
    if name.lower() not in (x.lower() for x in cats):
        cats.insert(min(pos, len(cats)), name)
        save_settings({"categories": cats})
    with db() as c:
        for slug in slugs[:2000]:
            rec = n_recipes.get(c, slug) if isinstance(slug, str) else None
            if rec and name not in _rec_categories(rec):
                order = {x.lower(): i for i, x in enumerate(cats)}
                names = sorted(_rec_categories(rec) + [name], key=lambda x: order.get(x.lower(), 99))
                _set_categories(c, rec, names)
    _recipe_cache["at"] = 0
    return {"ok": True, "categories": cats}


def recipe_update(slug, b):
    r = mealie("GET", f"/api/recipes/{_q(slug)}")
    if "name" in b:
        name = (b.get("name") or "").strip()
        if not name:
            raise ApiError(400, "Give the recipe a name.")
        r["name"] = title_case(name[:200])
    if "description" in b:
        r["description"] = (b.get("description") or "").strip()[:2000]
    if b.get("servings") not in (None, ""):
        r["recipeServings"] = max(0.0, float(b["servings"]))
    for key, field in (("prep_minutes", "prepTime"), ("cook_minutes", "performTime"), ("total_minutes", "totalTime")):
        if key in b:
            v = int(float(b.get(key) or 0))
            r[field] = f"{v} minutes" if v else None
            r[field + "Seconds"] = v * 60 if v else None
    if "categories" in b:
        r["recipeCategory"] = [{"name": n} for n in _category_arg(b.get("categories"))]
    if isinstance(b.get("ingredients"), list):
        old = {}
        for ing in r.get("recipeIngredient") or []:
            for k in ("display", "originalText", "note"):
                if ing.get(k):
                    old.setdefault(ing[k].strip(), ing)
        new, section = [], None
        for line in b["ingredients"]:
            line = str(line).strip()
            if not line:
                continue
            if line.startswith("#"):
                section = line.lstrip("# ").strip() or None
                continue
            ing = dict(old.get(line) or {"quantity": 0, "unit": None, "food": None, "note": line, "display": line,
                                         "originalText": line, "referenceId": str(uuid.uuid4())})
            ing["title"] = section
            section = None
            new.append(ing)
        r["recipeIngredient"] = new
    if isinstance(b.get("steps"), list):
        old_steps = r.get("recipeInstructions") or []
        steps = []
        for j, text in enumerate(t for t in (str(x).strip() for x in b["steps"]) if t):
            st = dict(old_steps[j]) if j < len(old_steps) else {"id": str(uuid.uuid4()), "title": "", "summary": "", "ingredientReferences": []}
            if st.get("text", "").strip() != text:
                st["ingredientReferences"] = []
            st["text"] = text
            steps.append(st)
        r["recipeInstructions"] = steps
    if NATIVE:
        r = _with_pan(r)
    out = mealie("PUT", f"/api/recipes/{_q(slug)}", r)
    _recipe_cache["at"] = 0
    with db() as c:
        invalidate_guided(c, r.get("id"), out.get("slug") or slug)
    return {"slug": out.get("slug") or slug}


def recipe_delete(slug):
    mealie("DELETE", f"/api/recipes/{_q(slug)}")
    _recipe_cache["at"] = 0
    return {"ok": True}


# ============================================================ screenshot import: TablePlan reads the image itself

TRANSCRIBE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["contains_recipe", "transcription"],
                     "properties": {"contains_recipe": {"type": "boolean"}, "transcription": {"type": "string"}}}
VISION_MODELS = re.compile(r"^(gpt-4o|gpt-4\.1|gpt-5|o[34]|chatgpt-4o)", re.I)


def transcribe_images(images, text=None):
    content = [{"type": "text", "text": "These images show one recipe (screenshots, a recipe card or a cookbook page). "
                "Transcribe it faithfully as plain text: title, servings, times, every ingredient line with exact amounts "
                "(one per line, keep section headings), then every instruction step in order. Ignore UI chrome, comments and ads. "
                "Do not invent anything: never add an ingredient, amount or step that isn't shown." + (f"\n\nExtra notes from the user: {text}" if text else "")}]
    for im in images:
        data = im.get("data") or ""
        if not data.startswith("data:image/"):
            data = "data:image/jpeg;base64," + data.split(",", 1)[-1]
        content.append({"type": "image_url", "image_url": {"url": data, "detail": "high"}})
    out = openai_chat([{"role": "user", "content": content}], "recipe_transcription", TRANSCRIBE_SCHEMA,
                      "screenshot import", f"{len(images)} image{'s' if len(images) != 1 else ''}")
    if not out.get("contains_recipe") or not (out.get("transcription") or "").strip():
        raise ApiError(422, "No recipe found in that image. Try a clearer screenshot that shows the ingredients and steps.")
    return out["transcription"].strip()


def ensure_image_provider():
    """Older setups could leave Mealie's image-reading slot empty, which breaks screenshot import."""
    try:
        st = mealie("GET", "/api/groups/ai-providers/settings")
    except ApiError:
        return
    if st.get("defaultProviderId") and not st.get("imageProviderId"):
        try:
            mealie("PUT", "/api/groups/ai-providers/settings", {"defaultProviderId": st["defaultProviderId"],
                   "imageProviderId": st["defaultProviderId"], "audioProviderId": st.get("audioProviderId")})
        except ApiError:
            pass


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        log(f"background {getattr(fn, '__name__', fn)} failed:", e)


def import_from_mealie(b):
    """One-time copy of recipes, photos, favorites, plans and lists from an existing Mealie (safe to re-run)."""
    if not NATIVE:
        raise ApiError(400, "Already using Mealie as the backend.")
    base = (b.get("url") or "").strip().rstrip("/")
    token = (b.get("token") or "").strip()
    if not re.match(r"^https?://", base) or not token:
        raise ApiError(400, "Enter your Mealie address (http://…:9925) and an API token from Mealie → Profile → API Tokens.")

    def m(method, path, body=None):
        try:
            return mealie_raw(method, path, body=body, token=token, base=base, timeout=60)
        except MealieHTTPError as e:
            raise ApiError(502, f"Mealie said {e.code} for {path.split('?')[0]}" + (" (check the API token)" if e.code in (401, 403) else ""))

    def mb(path):
        try:
            with _open(base + path, headers={"Authorization": f"Bearer {token}"}, timeout=30, allow_private=True) as r:
                return _read_capped(r, MAX_IMG, 120)
        except Exception:
            return None
    m("GET", "/api/users/self")
    os.makedirs(IMG_DIR, exist_ok=True)
    with db() as c:
        rec = n_recipes.migrate_from_mealie(c, m, mb, IMG_DIR)
    with db() as c:
        pl = n_plans.migrate_from_mealie(c, m)
    with db() as c:
        ls = n_lists.migrate_from_mealie(c, m)
    _recipe_cache["at"] = 0
    return {"recipes": rec, "plans": pl, "lists": ls}


# ============================================================ more import sources: videos, Google Docs, pasted text

VIDEO_HOSTS = re.compile(r"(^|\.)(instagram\.com|tiktok\.com|youtube\.com|youtu\.be|facebook\.com|fb\.watch|pinterest\.com|pin\.it|threads\.net|threads\.com)$", re.I)
GDOC_RE = re.compile(r"^https://docs\.google\.com/document/d/([A-Za-z0-9_-]{20,})")


def _looks_like_recipe(text):
    lines = [l for l in (text or "").splitlines() if l.strip()]
    amounts = sum(1 for l in lines if re.search(r"(^|\s)(\d+([./]\d+)?|[½⅓⅔¼¾⅛])\s*(cups?|tbsp|tsp|tablespoons?|teaspoons?|oz|ounces?|lbs?|pounds?|g|grams?|ml|cloves?|large|medium|small)\b", l, re.I))
    return amounts >= 3


def local_recipe_from_text(text, title=""):
    """No-AI reader for plain recipes with 'Ingredients' and 'Instructions/Directions/Method' headings."""
    lines = [l.strip() for l in (text or "").splitlines()]
    name, mode, ings, steps, cur = title.strip(), None, [], [], []
    for l in lines:
        if not l:
            continue
        low = l.lower().rstrip(":").strip("*# ")
        if re.match(r"^ingredients?\b", low):
            mode = "i"; continue
        if re.match(r"^(instructions?|directions?|method|preparation|steps?)\b", low):
            mode = "s"; continue
        if mode is None:
            if not name:
                name = l.strip("*# ")
            continue
        item = re.sub(r"^([-•*●▪◦]|\d+[.)])\s*", "", l)
        if mode == "i":
            ings.append(item)
        elif re.match(r"^(\d+[.)]|step\s*\d+)", l, re.I):
            if cur:
                steps.append(" ".join(cur))
            cur = [item + ":"] if len(item) <= 40 and not re.search(r"[.!]$", item) else [item]
        else:
            cur.append(item)
    if cur:
        steps.append(" ".join(cur))
    if len(ings) < 2 or not steps:
        if ings and not steps or steps and not ings:
            raise ApiError(422, "This recipe looks incomplete, so it wasn't saved: it has " + ("ingredients but no instructions." if ings else "instructions but no ingredient list.")
                           + " Add the missing part and try again.")
        return None
    return {"name": name or "Untitled recipe", "description": "",
            "recipeIngredient": [{"referenceId": str(uuid.uuid4()), "title": None, "note": x, "display": x, "originalText": x,
                                  "quantity": 0, "unit": None, "food": None} for x in ings],
            "recipeInstructions": [{"id": str(uuid.uuid4()), "title": "", "text": x, "ingredientReferences": []} for x in steps]}


def recipe_from_text(text, title="", source="", feature="text import"):
    data = local_recipe_from_text(text, title)
    if cfg("openai_key"):   # AI reads messy text better; the local reader is the no-key fallback
        try:
            data = ai_recipe((f"Title: {title}\n" if title else "") + text, feature=feature, detail=(source or title)[:80])
        except ApiError:
            if not data:
                raise
    if not data:
        raise ApiError(422, "Couldn't find ingredients and steps in that text. Add an 'Ingredients' and an 'Instructions' heading, "
                            "or add your OpenAI key so AI can read it.")
    if source:
        data["orgURL"] = source
    return data


def import_text(text, title=""):
    text = (text or "").strip()
    if len(text) < 20:
        raise ApiError(400, "Paste the recipe text (ingredients and steps).")
    return _imported(_save_new_recipe(recipe_from_text(text[:40000], title)))


def import_gdoc(url):
    doc = GDOC_RE.match(url).group(1)
    try:
        with _open(f"https://docs.google.com/document/d/{doc}/export?format=txt", headers={"User-Agent": "Mozilla/5.0"},
                   timeout=25) as r:
            final = r.geturl()
            body = _read_capped(r, 3_000_000, 60, truncate=True).decode("utf-8-sig", errors="replace")
    except (urllib.error.HTTPError, BlockedURL):
        body, final = "", ""
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
        raise ApiError(502, f"Couldn't open that Google Doc ({getattr(e, 'reason', e)}).")
    if "accounts.google.com" in final or "<html" in body[:500].lower() or not body.strip():
        raise ApiError(403, "That Google Doc is private. In Google Docs tap Share → General access → 'Anyone with the link', "
                            "then try again. (Or copy the text and use the Paste tab.)")
    title = body.strip().splitlines()[0].strip()[:120]
    return _imported(_save_new_recipe(recipe_from_text(body, title, url, "google doc import")))


def _transcribe(path):
    """Speech-to-text for a short video/audio file with OpenAI (≤25 MB)."""
    key = cfg("openai_key")
    boundary = "----tp" + uuid.uuid4().hex
    with open(path, "rb") as f:
        blob = f.read()
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\ngpt-4o-mini-transcribe\r\n'.encode(),
             f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="clip{os.path.splitext(path)[1] or ".mp4"}"\r\n'
             f'Content-Type: application/octet-stream\r\n\r\n'.encode() + blob + b"\r\n", f"--{boundary}--\r\n".encode()]
    res = _https_json("https://api.openai.com/v1/audio/transcriptions", data=b"".join(parts),
                      ctype=f"multipart/form-data; boundary={boundary}", headers={"Authorization": f"Bearer {key}"}, timeout=180)
    log_ai("video transcription", "gpt-4o-mini-transcribe", res.get("usage", {}).get("input_tokens"), res.get("usage", {}).get("output_tokens"), os.path.basename(path))
    return (res.get("text") or "").strip()


class _YtdlpQuiet:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): log("yt-dlp:", msg[:200])


# yt-dlp will fetch anything it is handed, so it only ever gets URLs on these hosts, and only the dedicated
# extractors for them are loaded (never the "generic" extractor, which follows arbitrary links and redirects).
VIDEO_EXTRACTORS = [r"(?:youtube|instagram|tiktok|vm\.tiktok|facebook|pinterest)(?::.*)?"]
SHORT_LINK_HOSTS = re.compile(r"(^|\.)(pin\.it|fb\.watch)$", re.I)
CAPTION_ONLY_HOSTS = re.compile(r"(^|\.)(threads\.net|threads\.com)$", re.I)
VIDEO_MAX_BYTES = 24_000_000
VIDEO_MAX_SECONDS = 240


def _video_url_ok(url):
    try:
        p = urllib.parse.urlparse(url)
        host = p.hostname or ""
    except ValueError:
        return False
    return p.scheme in ("http", "https") and not p.username and not p.password and bool(VIDEO_HOSTS.search(host))


def _resolve_short_link(url):
    """Follow a pin.it / fb.watch short link with the guarded opener and return where it lands."""
    try:
        with _open(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15) as r:
            return r.geturl()
    except urllib.error.HTTPError as e:
        return e.geturl() or url
    except (BlockedURL, urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise ApiError(400, "That short link couldn't be opened. Paste the full link to the post instead.")


def _meta_content(page, *names):
    for name in names:
        for m in re.finditer(r"<meta\b[^>]*>", page[:400_000], re.I):
            tag = m.group(0)
            if re.search(r"""(?:property|name)\s*=\s*["']""" + re.escape(name) + r"""["']""", tag, re.I):
                c = re.search(r"""content\s*=\s*("([^"]*)"|'([^']*)')""", tag, re.I | re.S)
                if c:
                    return html.unescape(c.group(2) if c.group(2) is not None else c.group(3) or "").strip()
    return ""


def import_video(url):
    if not _video_url_ok(url):
        raise ApiError(400, "Video import works with Instagram, TikTok, YouTube, Facebook, Pinterest and Threads links.")
    if SHORT_LINK_HOSTS.search(urllib.parse.urlparse(url).hostname or ""):
        url = _resolve_short_link(url)
        if not _video_url_ok(url) or SHORT_LINK_HOSTS.search(urllib.parse.urlparse(url).hostname or ""):
            raise ApiError(400, "That short link doesn't lead to a video post TablePlan can read.")
    if CAPTION_ONLY_HOSTS.search(urllib.parse.urlparse(url).hostname or ""):
        # No dedicated extractor: read the post's caption from the page itself (guarded fetch).
        final, page = _fetch_page(url)
        title = _meta_content(page, "og:title", "twitter:title")
        caption = _meta_content(page, "og:description", "description", "twitter:description")
        if not caption.strip():
            raise ApiError(422, "Couldn't read that post's caption. Take screenshots of the post and use the Screenshot tab.")
        data = recipe_from_text(caption, title, url, "video import")
        if not data.get("name") or data["name"] == "Untitled recipe":
            data["name"] = title or "Video recipe"
        return _imported(_save_new_recipe(data, _meta_content(page, "og:image") or None))
    try:
        import yt_dlp
    except ImportError:
        raise ApiError(501, "Video import isn't available in this install. Update TablePlan, or use screenshots of the post.")
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "logger": _YtdlpQuiet(), "noplaylist": True,
            "skip_download": True, "socket_timeout": 20, "allowed_extractors": VIDEO_EXTRACTORS,
            "extract_flat": "in_playlist", "cachedir": False, "playlist_items": "1"}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
    except Exception as e:
        msg = str(e)
        if re.search(r"login|log in|private|rate|cookies", msg, re.I):
            raise ApiError(502, "That post can't be opened without logging in (private account or the site is blocking). "
                                "Take screenshots of the caption and use the Screenshot tab.")
        reason = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)?[^:]*:\s*", "", msg.splitlines()[0] if msg else "").split(";")[0][:90]
        raise ApiError(502, f"Couldn't open that video ({reason}). Try again in a minute, or use screenshots of the post.")
    if not isinstance(info, dict) or info.get("_type") in ("playlist", "multi_video", "url", "url_transparent"):
        raise ApiError(400, "Paste a link to a single video or post, not a channel or playlist.")
    title = (info.get("title") or "").strip()
    caption = (info.get("description") or "").strip()
    thumb = info.get("thumbnail")
    text = caption
    if not _looks_like_recipe(caption):
        if not cfg("openai_key"):
            if not caption:
                raise ApiError(400, "This video's recipe is spoken, not written. Add your OpenAI key in Settings → AI recipe import so TablePlan can listen to it.")
        else:   # recipe is spoken: grab the smallest version and transcribe it
            import tempfile
            started = time.monotonic()

            def guard(d):   # abort oversized or slow downloads even when the size isn't known up front
                if (d.get("downloaded_bytes") or 0) > VIDEO_MAX_BYTES or time.monotonic() - started > VIDEO_MAX_SECONDS:
                    raise yt_dlp.utils.DownloadError("download too large or too slow")

            with tempfile.TemporaryDirectory(prefix="tableplan-video-") as tmp:
                dl = {**opts, "skip_download": False, "outtmpl": os.path.join(tmp, "clip.%(ext)s"), "paths": {"home": tmp},
                      "format": "worstaudio[filesize<24M]/worst[filesize<24M]/worstaudio/worst",
                      "max_filesize": VIDEO_MAX_BYTES, "progress_hooks": [guard], "restrictfilenames": True}
                try:
                    with yt_dlp.YoutubeDL(dl) as y:
                        y.download([url])
                    files = [os.path.join(tmp, f) for f in os.listdir(tmp) if not f.endswith((".part", ".ytdl"))]
                    files = [f for f in files if os.path.isfile(f) and not os.path.islink(f)]
                    if files and os.path.getsize(files[0]) < 25_000_000:
                        spoken = _transcribe(files[0])
                        text = f"Caption:\n{caption}\n\nWhat the cook says in the video:\n{spoken}"
                except ApiError:
                    raise
                except Exception as e:
                    log("video download/transcribe failed:", str(e)[:200])
    if not text.strip():
        raise ApiError(422, "Couldn't find a recipe in that video's caption or audio. Try screenshots instead.")
    data = recipe_from_text(text, title, url, "video import")
    if not data.get("name") or data["name"] == "Untitled recipe":
        data["name"] = title or "Video recipe"
    return _imported(_save_new_recipe(data, thumb if isinstance(thumb, str) else None))


def _imported(slug):
    slug = slug.strip('"') if isinstance(slug, str) else slug
    queue_guided(slug)   # the recipe is saved (polished first): prepare its AI step-by-step in the background
    _recipe_cache["at"] = 0
    try:
        r = mealie("GET", f"/api/recipes/{_q(slug)}")
        ings = r.get("recipeIngredient") or []
        unparsed = sum(1 for i in ings if not (i.get("food") or i.get("unit")) and (i.get("note") or i.get("display")))
        return {"slug": slug, "name": r.get("name"), "id": r.get("id"), "has_image": bool(r.get("image")),
                "servings": r.get("recipeServings"), "ingredients": len(ings), "unparsed": unparsed,
                "link": recipe_link(slug)}
    except ApiError:
        return {"slug": slug, "name": slug.replace("-", " ").title(), "link": recipe_link(slug)}


# ============================================================ recipes (detail, favorites, scaling data)

def recipe_minutes(r):
    for k in ("totalTimeSeconds",):
        if r.get(k):
            return round(int(r[k]) / 60)
    sec = sum(int(r.get(k) or 0) for k in ("prepTimeSeconds", "performTimeSeconds"))
    if sec:
        return round(sec / 60)
    m = re.search(r"(\d+)\s*(h|hour)", str(r.get("totalTime") or ""), re.I)
    mins = int(m.group(1)) * 60 if m else 0
    m = re.search(r"(\d+)\s*(m|min)", str(r.get("totalTime") or ""), re.I)
    return mins + (int(m.group(1)) if m else 0) or None


def mealie_user_id():
    uid = cfg("mealie_user_id")
    if not uid:
        uid = mealie("GET", "/api/users/self")["id"]
        set_cfg(mealie_user_id=uid)
    return uid


def favorite_ids():
    try:
        res = mealie("GET", f"/api/users/{mealie_user_id()}/favorites")
        return {r.get("recipeId") for r in res.get("ratings") or [] if r.get("isFavorite")}
    except ApiError:
        return set()


def set_favorite(slug, on):
    mealie("POST" if on else "DELETE", f"/api/users/{mealie_user_id()}/favorites/{_q(slug)}")
    _recipe_cache["at"] = 0
    return {"favorite": bool(on)}


FOOD_EMOJI = [
    ("paper towel", "🧻"), ("toilet paper", "🧻"), ("napkin", "🧻"), ("tissue", "🧻"), ("soap", "🧼"), ("detergent", "🧴"), ("dish", "🧽"), ("sponge", "🧽"),
    ("trash bag", "🗑️"), ("foil", "🧻"), ("plastic wrap", "🧻"),
    ("egg", "🥚"), ("milk", "🥛"), ("cream", "🥛"), ("butter", "🧈"), ("cheese", "🧀"), ("parmesan", "🧀"), ("yogurt", "🥛"),
    ("chicken", "🍗"), ("turkey", "🦃"), ("beef", "🥩"), ("steak", "🥩"), ("pork", "🥓"), ("bacon", "🥓"), ("sausage", "🌭"),
    ("ham", "🍖"), ("salmon", "🐟"), ("fish", "🐟"), ("tuna", "🐟"), ("shrimp", "🦐"), ("crab", "🦀"),
    ("tomato", "🍅"), ("potato", "🥔"), ("onion", "🧅"), ("garlic", "🧄"), ("carrot", "🥕"), ("pepper", "🫑"), ("chili", "🌶️"),
    ("jalapeno", "🌶️"), ("broccoli", "🥦"), ("lettuce", "🥬"), ("spinach", "🥬"), ("kale", "🥬"), ("cabbage", "🥬"),
    ("cucumber", "🥒"), ("zucchini", "🥒"), ("corn", "🌽"), ("mushroom", "🍄"), ("avocado", "🥑"), ("eggplant", "🍆"),
    ("bean", "🫘"), ("pea", "🫛"), ("lemon", "🍋"), ("lime", "🍋"), ("orange", "🍊"), ("apple", "🍎"), ("banana", "🍌"),
    ("berry", "🫐"), ("blueberr", "🫐"), ("strawberr", "🍓"), ("cherry", "🍒"), ("grape", "🍇"), ("peach", "🍑"), ("mango", "🥭"),
    ("pineapple", "🍍"), ("coconut", "🥥"), ("rice", "🍚"), ("pasta", "🍝"), ("spaghetti", "🍝"), ("noodle", "🍜"),
    ("fettuccine", "🍝"), ("penne", "🍝"), ("linguine", "🍝"), ("macaroni", "🍝"), ("bread", "🍞"), ("tortilla", "🫓"), ("flour", "🌾"), ("oat", "🌾"), ("sugar", "🍬"), ("honey", "🍯"), ("syrup", "🍯"),
    ("chocolate", "🍫"), ("cocoa", "🍫"), ("oil", "🫒"), ("olive", "🫒"), ("vinegar", "🍶"), ("salt", "🧂"), ("broth", "🍲"),
    ("stock", "🍲"), ("wine", "🍷"), ("beer", "🍺"), ("water", "💧"), ("ice", "🧊"), ("herb", "🌿"), ("basil", "🌿"),
    ("parsley", "🌿"), ("cilantro", "🌿"), ("oregano", "🌿"), ("thyme", "🌿"), ("rosemary", "🌿"), ("mint", "🌿"),
    ("ginger", "🫚"), ("cinnamon", "🟤"), ("nut", "🥜"), ("peanut", "🥜"), ("almond", "🥜"), ("tofu", "🧊"), ("sauce", "🥫"),
    ("paste", "🥫"), ("can", "🥫"),
    ("clementine", "🍊"), ("mandarin", "🍊"), ("tangerine", "🍊"), ("raspberr", "🫐"), ("blackberr", "🫐"), ("kiwi", "🥝"),
    ("shallot", "🧅"), ("leek", "🧅"), ("celery", "🥬"), ("cauliflower", "🥦"), ("asparagus", "🥬"), ("brussels", "🥬"),
    ("squash", "🎃"), ("pumpkin", "🎃"), ("jalapeño", "🌶️"), ("spring mix", "🥬"), ("arugula", "🥬"), ("coleslaw", "🥬"),
    ("dill", "🌿"), ("radish", "🥕"), ("beet", "🥕"), ("half and half", "🥛"), ("margarine", "🧈"), ("cheddar", "🧀"),
    ("mozzarella", "🧀"), ("monterey", "🧀"), ("provolone", "🧀"), ("feta", "🧀"), ("ricotta", "🧀"), ("roast", "🥩"),
    ("hot dog", "🌭"), ("cod", "🐟"), ("tilapia", "🐟"), ("lamb", "🍖"), ("bun", "🍞"), ("roll", "🍞"), ("bagel", "🥯"),
    ("muffin", "🧁"), ("naan", "🫓"), ("croissant", "🥐"), ("baking soda", "🧂"), ("baking powder", "🧂"), ("yeast", "🌾"),
    ("vanilla", "🍶"), ("cooking spray", "🫒"), ("quinoa", "🌾"), ("panko", "🍞"), ("chickpea", "🫘"), ("lentil", "🫘"),
    ("jelly", "🍇"), ("jam", "🍓"), ("pancake", "🥞"), ("ketchup", "🥫"), ("mustard", "🥫"), ("mayo", "🥫"), ("sriracha", "🌶️"),
    ("salsa", "🍅"), ("dressing", "🥗"), ("pickle", "🥒"), ("cereal", "🥣"), ("granola", "🥣"), ("cracker", "🍘"),
    ("pretzel", "🥨"), ("popcorn", "🍿"), ("walnut", "🥜"), ("pecan", "🥜"), ("raisin", "🍇"), ("coffee", "☕"), ("tea", "🍵"),
    ("paprika", "🌶️"), ("cumin", "🟤"), ("seasoning", "🧂"), ("bay lea", "🌿"), ("curry", "🍛"), ("frozen", "🧊"),
    ("cherri", "🍒"), ("soda", "🥤"), ("seltzer", "🥤"), ("juice", "🧃"), ("zip-top", "🛍️"), ("bags", "🛍️"), ("parchment", "🧻"),
]


# Checked before FOOD_EMOJI: seasonings and names that a plain keyword would mis-match (black pepper -> bell pepper,
# eggplant -> egg, peach/peanut -> pea, nutmeg -> nut).
_EMOJI_FIRST = [
    (r"\bsalt\b", "🧂"), (r"\b(black|white|ground|cracked)\s+pepper|peppercorn|\bpepper\b.*\bto taste\b", "🧂"),
    (r"\b(red pepper flakes|crushed red pepper|cayenne|chipotle|chile|chili)", "🌶️"), (r"\beggplant", "🍆"),
    (r"\bpeanut", "🥜"), (r"\bpeach", "🍑"), (r"\bpear\b|\bpears\b", "🍐"), (r"\bnutmeg", "🟤"),
    (r"\bcream cheese", "🧀"), (r"\bcornstarch|\bcorn starch", "🌾"), (r"\b(broth|stock)\b", "🍲"),
]


def food_emoji(name):
    n = (name or "").lower()
    for pat, e in _EMOJI_FIRST:
        if re.search(pat, n):
            return e
    for k, e in FOOD_EMOJI:
        # match at a word start so "juice"/"spice" don't hit "ice" and "pecan" doesn't hit "can"
        if re.search(r"\b" + re.escape(k), n):
            return e
    return "🥄"


def _num(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def recipe_detail(slug):
    r = mealie("GET", f"/api/recipes/{_q(slug)}")
    with db() as c:
        pantry = {}   # soonest-expiring first, so an ingredient shows the item to use up
        for it in sorted(list_pantry(c), key=lambda x: (x["days_left"] is None, x["days_left"] if x["days_left"] is not None else 0)):
            if it.get("review"):
                continue
            pantry.setdefault(food_key(it["name"]), it)
            if it.get("food_id") is not None:
                pantry.setdefault(f"f:{it['food_id']}", it)
        fid_of = {}
        if NATIVE:
            for ing in r.get("recipeIngredient") or []:
                nm = (ing.get("food") or {}).get("name") or _ing_food_name(ing.get("note") or ing.get("display") or ing.get("originalText") or "")
                if nm and n_foods.normalize(nm):
                    fid_of[nm] = n_foods.lookup(c, nm)
    ings, ref_index = [], {}
    for i, ing in enumerate(r.get("recipeIngredient") or []):
        food = ing.get("food") or {}
        unit = ing.get("unit") or {}
        fname = food.get("name") or ""
        parsed = bool(food or unit) and _num(ing.get("quantity")) is not None
        local = None
        if not parsed:
            local = parse_ing_text(ing.get("note") or ing.get("display") or ing.get("originalText") or "")
            if local:
                fname = local["food"]
        pantry_hit = (pantry.get(f"f:{fid_of.get(fname)}") if fid_of.get(fname) is not None else None) if fname else None
        pantry_hit = pantry_hit or ((pantry.get(food_key(fname)) or pantry.get(food_key(clean_food(fname)))) if fname else None)
        if ing.get("referenceId"):
            ref_index[ing["referenceId"]] = i
        if local:
            ings.append({"i": i, "section": ing.get("title") or "", "quantity": local["quantity"] or None, "parsed": True, "local": True,
                         "unit": local["unit"], "unit_plural": local["unit_plural"], "food": local["food"], "food_plural": "",
                         "name": sentence_case(local["food"]), "amount_text": local.get("amount_text") or "",
                         "note": local["note"], "size": local["size"],
                         "display": (ing.get("display") or ing.get("note") or "").strip(),
                         "raw": (ing.get("originalText") or ing.get("display") or ing.get("note") or "").strip(),
                         "emoji": food_emoji(local["food"]), "img": f"/img/ing?name={urllib.parse.quote(clean_food(local['food']))}",
                         "pantry": {"days_left": pantry_hit["days_left"], "location": pantry_hit["location"]} if pantry_hit else None})
            continue
        ings.append({
            "i": i, "section": ing.get("title") or "",
            "quantity": _num(ing.get("quantity")), "parsed": parsed,
            "unit": unit.get("abbreviation") if unit.get("useAbbreviation") and unit.get("abbreviation") else unit.get("name") or "",
            "unit_plural": unit.get("pluralAbbreviation") if unit.get("useAbbreviation") and unit.get("pluralAbbreviation")
            else unit.get("pluralName") or "",
            "food": fname, "food_plural": food.get("pluralName") or "", "name": sentence_case(fname), "amount_text": "",
            "note": ing.get("note") or "", "display": (ing.get("display") or ing.get("originalText") or ing.get("note") or "").strip(),
            "emoji": food_emoji(fname or ing.get("note") or ing.get("display")),
            "img": f"/img/ing?name={urllib.parse.quote(clean_food(fname))}" if fname else None,
            "raw": (ing.get("originalText") or ing.get("display") or ing.get("note") or "").strip(),
            "pantry": {"days_left": pantry_hit["days_left"], "location": pantry_hit["location"]} if pantry_hit else None,
        })
    steps = []
    for j, st in enumerate(r.get("recipeInstructions") or []):
        refs = [ref_index[x["referenceId"]] for x in st.get("ingredientReferences") or [] if x.get("referenceId") in ref_index]
        steps.append({"i": j, "title": st.get("title") or "", "text": (st.get("text") or "").strip(),
                      "refs": refs, "duration_sec": st.get("durationSeconds")})
    minutes = recipe_minutes(r)
    n = len(ings)
    difficulty = "Easy" if (minutes or 30) <= 30 and n <= 8 else "Hard" if (minutes or 0) > 90 or n > 15 else "Medium"
    return {
        "id": r["id"], "slug": r.get("slug"), "name": r.get("name"), "description": r.get("description") or "",
        "has_image": bool(r.get("image")), "image_v": r.get("image") or "",
        "photo": recipe_photo_info(r) if NATIVE and r.get("id") else None,
        "ai_generated": bool((r.get("extras") or {}).get("ai_generated")) if isinstance(r.get("extras"), dict) else False,
        "source_credit": _credit_out((r.get("extras") or {}).get("source_credit")) if isinstance(r.get("extras"), dict) else None,
        "pan": recipe_pan(r) if NATIVE else None,
        "servings": _num(r.get("recipeServings")) or _num(r.get("recipeYieldQuantity")) or 0,
        "yield": r.get("recipeYield") or "", "minutes": minutes,
        "prep_minutes": round(int(r.get("prepTimeSeconds") or 0) / 60) or None,
        "cook_minutes": round(int(r.get("performTimeSeconds") or 0) / 60) or None,
        "difficulty": difficulty, "rating": (diary_ratings().get(r["id"]) or (r.get("rating") or 0,))[0] if NATIVE else r.get("rating") or 0,
        "favorite": r["id"] in favorite_ids(), "diary": diary_list(recipe_id=r["id"], limit=20) if NATIVE else [],
        "versions": len(((r.get("extras") or {}).get("versions") or [])) if isinstance(r.get("extras"), dict) else 0,
        "tags": [t.get("name") for t in r.get("tags") or []],
        "categories": [t.get("name") for t in r.get("recipeCategory") or []],
        "ingredients": ings, "steps": steps, "source_url": r.get("orgURL") or "",
        "link": recipe_link(r.get("slug")), "updated": r.get("dateUpdated") or r.get("updatedAt") or "",
        "unparsed": 0, "total_minutes": round(int(r.get("totalTimeSeconds") or 0) / 60) or None,
        "missing": recipe_missing(r["id"]), "cook_entry": cook_entry_for(r["id"]),
        "eta": eta_view(r["id"], eta_base(r)),
        "cooked_today": cooked_today(r["id"]),
        "original": _original(r),
        "name_suggested": ((r.get("extras") or {}).get("title_source") == "suggested") if isinstance(r.get("extras"), dict) else False,
    }


def recipe_polish(slug):
    """"Reword with AI" on an existing recipe: same safety checks as the import polish; the original text survives."""
    require_native()
    if not cfg("openai_key"):
        raise ApiError(400, "Add your OpenAI key in Settings → AI recipe import to reword recipes.")
    with db() as c:
        rec = n_recipes.get(c, slug)
    if not rec:
        raise ApiError(404, "Recipe not found")
    new = polish_recipe(rec, REWORD_EXTRA)
    if new is rec:
        raise ApiError(422, "The AI's rewrite dropped part of the method, so nothing was changed. Try again.")
    with db() as c:
        slug = n_recipes.update(c, rec["id"], _annotate_foods(c, new))
        invalidate_guided(c, rec["id"], slug)
    _recipe_cache["at"] = 0
    return recipe_detail(slug)


def recipe_restore_original(slug):
    """Put an imported/reworded recipe's original ingredient, step and description text back."""
    require_native()
    with db() as c:
        rec = n_recipes.get(c, slug)
        if not rec:
            raise ApiError(404, "Recipe not found")
        o = _original(rec)
        if not o:
            raise ApiError(404, "There's no original text for this recipe.")
        ings, section = [], None
        old = [g for g in rec.get("recipeIngredient") or [] if _ing_line(g)]
        for i, line in enumerate(o["ingredients"]):
            title = old[i].get("title") if i < len(old) and len(old) == len(o["ingredients"]) else None
            ings.append({"referenceId": str(uuid.uuid4()), "title": title, "note": line, "display": line,
                         "originalText": line, "quantity": 0, "unit": None, "food": None})
        rec = dict(rec, recipeIngredient=ings, description=o["description"] or rec.get("description") or "",
                   recipeInstructions=[{"id": str(uuid.uuid4()), "title": "", "text": t, "ingredientReferences": []}
                                       for t in o["steps"]])
        slug = n_recipes.update(c, rec["id"], _annotate_foods(c, rec))
        invalidate_guided(c, rec["id"], slug)
    _recipe_cache["at"] = 0
    return recipe_detail(slug)


def _original(r):
    """The pre-polish text of an imported recipe, or None."""
    o = (r.get("extras") or {}).get("original") if isinstance(r.get("extras"), dict) else None
    if not isinstance(o, dict):
        return None
    strs = lambda v: [str(x) for x in v if isinstance(x, (str, int, float))] if isinstance(v, list) else []  # noqa: E731
    return {"ingredients": strs(o.get("ingredients")), "steps": strs(o.get("steps")),
            "description": str(o.get("description") or "")}


def add_items_to_list(texts, list_id=None):
    list_id = ensure_list(list_id)
    mealie("POST", "/api/households/shopping/items/create-bulk",
           [{"shoppingListId": list_id, "note": t, "quantity": 1, "isFood": False} for t in texts if t])
    return {"list_id": list_id, "added": len([t for t in texts if t])}


# ============================================================ guided "step-by-step" recipes

DUR_RE = re.compile(r"(\d+(?:\.\d+)?)(?:\s*(?:-|–|to)\s*(\d+(?:\.\d+)?))?\s*(hours?|hrs?|h\b|minutes?|mins?|m\b|seconds?|secs?)", re.I)
TEMP_RE = re.compile(r"(\d{3})\s*°?\s*(F|C)?\b", re.I)
HEAT_RE = re.compile(r"\b((?:medium[- ])?(?:low|medium|high)(?:[- ]high|[- ]low)?)\s+heat\b", re.I)
STOVE_TIPS = {
    "gas": "Gas responds instantly. Adjust the flame and you'll see the change right away.",
    "electric": "Electric coils are slow. Give the burner 2–3 minutes to heat, and slide the pan off the burner to cool it quickly.",
    "induction": "Induction heats fast. Start one notch lower than the recipe says, and use a magnetic (cast iron or steel) pan.",
}


GUIDED_AI, GUIDED_AUTO = "ai3", "auto3"   # cache "profile" tags; the kitchen (stove, oven, units) is applied when shown


def _guided_key(rec):
    """Fingerprint of what the step-by-step is built from. Photos, categories, ratings or notes don't change it."""
    src = [rec.get("name"), rec.get("servings"),
           [(x.get("i"), x.get("display"), x.get("food"), x.get("section")) for x in rec.get("ingredients") or []],
           [(s0.get("title"), s0.get("text")) for s0 in rec.get("steps") or []]]
    return hashlib.sha256(json.dumps(src, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _temp_raw(text):
    tm = TEMP_RE.search(text or "")
    if tm and re.search(r"oven|bake|roast|preheat|°", text, re.I):
        return {"v": int(tm.group(1)), "u": (tm.group(2) or "F").upper()}
    return None


def _timing(text):
    t = n_timers.step_timing(text)
    return {"timers": t["timers"], "cue": t["cue"]}


def guided_auto(rec):
    """Built-in step-by-step (no AI): ingredients placed in the step that uses them, stated times as timers."""
    used, steps = set(), []
    tokens_of = {x["i"]: set(tokens(x["food"])) for x in rec["ingredients"] if x["food"]}
    for s0 in rec["steps"]:
        text = s0["text"]
        refs = [i for i in s0["refs"] if i not in used]
        if not s0["refs"]:
            ttoks = set(tokens(text))
            refs = [i for i, tk in tokens_of.items() if tk and tk <= ttoks and i not in used]
        used.update(refs)
        tmg = _timing(text)
        if not tmg["timers"] and s0.get("duration_sec"):
            d = int(s0["duration_sec"])
            tmg["timers"] = [{"sec": d, "high_sec": None, "label": n_timers.fmt(d), "kind": "countdown", "source": ""}]
        heat = HEAT_RE.search(text)
        steps.append({"title": s0["title"] or "", "text": text, "ingredients": [{"i": i, "portion": 1} for i in refs],
                      **tmg, "heat": heat.group(1).lower() if heat else None, "temp_raw": _temp_raw(text)})
    leftovers = [x["i"] for x in rec["ingredients"] if x["i"] not in used and (x["food"] or x["display"])]
    out = []
    oven = next((st["temp_raw"] for st in steps if st["temp_raw"]), None)
    if oven and not re.search(r"preheat", steps[0]["text"] if steps else "", re.I):
        out.append({"title": "Preheat", "kind": "preheat", "text": "", "ingredients": [], "timers": [], "cue": None,
                    "heat": None, "temp_raw": oven})
    names = [rec["ingredients"][i]["food"] or rec["ingredients"][i]["display"] for i in leftovers]
    tips = [f"Also have ready: {', '.join(n for n in names if n)}."] if leftovers and any(names) else []
    return {"source": "auto", "steps": out + steps, "tips": tips}


def _local_temp(raw, unit, oven):
    if not raw:
        return None, False
    t, u = int(raw["v"]), raw.get("u") or "F"
    if u != unit:
        t = round((t - 32) * 5 / 9 / 5) * 5 if unit == "C" else round((t * 9 / 5 + 32) / 5) * 5
    conv = oven == "convection"
    if conv:
        t -= 25 if unit == "F" else 15
    return f"{t}°{unit}", conv


def guided_localize(data, settings=None):
    """Apply this kitchen (stove, oven, °F/°C) to a cached step-by-step. Changing those settings never needs the AI."""
    st = settings or get_settings()
    stove, oven, unit = st.get("stove"), st.get("oven"), st.get("temp_unit") or "F"
    steps = []
    for s0 in data.get("steps") or []:
        s1 = dict(s0)
        temp, conv = _local_temp(s1.get("temp_raw"), unit, oven)
        s1["temperature"] = temp
        if s1.get("kind") == "preheat":
            s1["text"] = (f"Preheat the oven to {temp}" + (f" (convection, already lowered {'25°F' if unit == 'F' else '15°C'})" if conv else "")
                          + ". It takes about 10–15 minutes, so keep going with the next steps while it heats.")
            s1["timers"] = [{"sec": 600, "high_sec": 900, "label": "Oven preheating", "kind": "countdown", "source": "preheat"}]
        ts = s1.get("timers") or []
        first = next((x for x in ts if x.get("kind") != "long"), None)
        s1["timer_sec"] = first["sec"] if first else None
        s1["timer_label"] = first["label"] if first else (ts[0]["label"] if ts else None)
        s1["tip"] = STOVE_TIPS.get(stove) if s1.get("heat") else None
        steps.append(s1)
    return {**data, "steps": steps}


GUIDE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["steps", "tips"],
    "properties": {
        "tips": {"type": "array", "items": {"type": "string"}},
        "steps": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["title", "text", "ingredients", "timer_minutes", "timer_label", "heat", "temperature"],
            "properties": {
                "title": {"type": "string"}, "text": {"type": "string"},
                "ingredients": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                "required": ["index", "portion"],
                                "properties": {"index": {"type": "integer"}, "portion": {"type": "number"}}}},
                "timer_minutes": {"type": ["number", "null"]}, "timer_label": {"type": ["string", "null"]},
                "heat": {"type": ["string", "null"]}, "temperature": {"type": ["string", "null"]}}}}}}


AI_PRICES = {   # USD per 1M tokens (input, output). Published OpenAI list prices, Nov 2026; edit if they change.
    "gpt-5": (1.25, 10.00), "gpt-5-mini": (0.25, 2.00), "gpt-5-nano": (0.05, 0.40),
    "gpt-image-1": (10.00, 40.00),   # image input / image output tokens
    "gpt-4.1": (2.00, 8.00), "gpt-4.1-mini": (0.40, 1.60), "gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00),
}


def ai_cost(model, tin, tout):
    key = next((k for k in sorted(AI_PRICES, key=len, reverse=True) if (model or "").startswith(k)), None)
    if not key:
        return None
    pin, pout = AI_PRICES[key]
    return round((tin or 0) / 1e6 * pin + (tout or 0) / 1e6 * pout, 6)


def log_ai(feature, model, tin=None, tout=None, detail=""):
    cost = ai_cost(model, tin, tout) if tin is not None else None
    with db() as c:
        c.execute("INSERT INTO ai_usage(at, feature, model, input_tokens, output_tokens, cost_usd, detail) VALUES (?,?,?,?,?,?,?)",
                  (datetime.now().isoformat(timespec="seconds"), feature, model, tin, tout, cost, detail[:120]))
    return cost


def openai_chat(messages, schema_name, schema, feature, detail=""):
    key, model = cfg("openai_key"), cfg("openai_model") or "gpt-5-mini"
    if not key:
        raise ApiError(400, "Add your OpenAI key in Settings → AI recipe import to use AI step-by-step.")
    payload = {"model": model, "messages": messages, "max_completion_tokens": 8000,
               "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}}
    if re.match(r"^(gpt-5|o[134])", model):
        payload["reasoning_effort"] = "low"
    content, finish = _openai_call(key, payload, feature, detail, model)
    try:
        return json.loads(content or "{}")
    except ValueError:
        log(f"AI JSON unreadable (finish_reason={finish}, {len(content or '')} chars): {(content or '')[:200]!r}")
        raise AIUnreadable(finish)


class AIUnreadable(ApiError):
    def __init__(self, finish=None):
        super().__init__(502, f"The AI's answer couldn't be read ({finish or 'unknown'}). Please try again.")


def _openai_call(key, payload, feature, detail, model):
    res = _https_json("https://api.openai.com/v1/chat/completions", payload=payload,
                      headers={"Authorization": f"Bearer {key}"}, timeout=180)
    u = res.get("usage") or {}
    log_ai(feature, res.get("model") or model, u.get("prompt_tokens"), u.get("completion_tokens"), detail)
    choice = (res.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    if msg.get("refusal"):
        raise ApiError(422, "The AI declined to read that. Try a different screenshot.")
    return msg.get("content") or "", choice.get("finish_reason")


def openai_text(messages, feature, detail=""):
    key, model = cfg("openai_key"), cfg("openai_model") or "gpt-5-mini"
    payload = {"model": model, "messages": messages, "max_completion_tokens": 8000}
    if re.match(r"^(gpt-5|o[134])", model):
        payload["reasoning_effort"] = "minimal" if model.startswith("gpt-5") else "low"
    content, finish = _openai_call(key, payload, feature, detail, model)
    log(f"AI text reply: finish_reason={finish}, {len(content)} chars")
    return content


def parse_recipe_text(t):
    """Parse the plain-text recipe format requested by ai_recipe's fallback."""
    out = {"found": True, "name": "", "description": "", "servings": 0, "prep_minutes": 0, "cook_minutes": 0,
           "total_minutes": 0, "ingredients": [], "steps": [], "tags": []}
    mode, section = None, ""
    for raw in (t or "").splitlines():
        line = raw.strip().strip("*").strip()
        if not line:
            continue
        inc = re.match(r"^INCOMPLETE\s*:?\s*(.*)$", line, re.I)
        if inc:
            out["incomplete"] = inc.group(1) or "part of it is missing"
            continue
        m = re.match(r"^(SOURCE|TITLE|DESCRIPTION|SERVINGS|PREP|COOK|TOTAL|TAGS|INGREDIENTS|STEPS|NO RECIPE)\s*:?\s*(.*)$", line, re.I)
        if m:
            k, v = m.group(1).upper(), m.group(2).strip()
            if k == "NO RECIPE":
                out["found"] = False
            elif k in ("INGREDIENTS", "STEPS"):
                mode = k
            elif k == "TITLE":
                out["name"] = v
            elif k == "SOURCE":
                out["source_url"] = v
            elif k == "DESCRIPTION":
                out["description"] = v
            elif k == "TAGS":
                out["tags"] = [x.strip() for x in v.split(",") if x.strip()]
            else:
                n = re.search(r"\d+(?:\.\d+)?", v)
                key = {"SERVINGS": "servings", "PREP": "prep_minutes", "COOK": "cook_minutes", "TOTAL": "total_minutes"}[k]
                if n:
                    out[key] = float(n.group()) if k == "SERVINGS" else int(float(n.group()))
            continue
        if mode == "INGREDIENTS":
            if line.startswith("#"):
                section = line.lstrip("# ").strip()
                continue
            out["ingredients"].append({"section": section, "line": re.sub(r"^[-•*]\s*", "", line)})
            section = ""
        elif mode == "STEPS":
            out["steps"].append(re.sub(r"^(step\s*)?\d+[.):]\s*", "", line, flags=re.I))
    return out


def guided_ai(rec):
    """AI order of operations. Kitchen-independent (stove, oven and units are applied when shown), and any timer the
    AI gives must be a time the recipe itself states."""
    ing_lines = "\n".join(f"[{x['i']}] {x['display'] or x['food']}" + (f"  (section: {x['section']})" if x["section"] else "")
                          for x in rec["ingredients"])
    step_lines = "\n".join(f"{n + 1}. {s0['text']}" for n, s0 in enumerate(rec["steps"]))
    source_texts = [s0["text"] for s0 in rec["steps"]]
    stated = n_timers.stated_seconds(source_texts)
    hint = n_timers.hints(source_texts)
    sys_prompt = (
        "You rewrite home recipes into a perfect order of operations a nervous home cook can follow without reading ahead. "
        "Rules: keep every original ingredient and amount, never invent ingredients. Each step lists exactly which ingredients it uses "
        "by their [index]; if an ingredient is split across steps, give the fraction used as portion (e.g. 0.5), otherwise 1. "
        "Put preheating (oven, pans, water to boil) at the moment it must start so it's ready in time. "
        "Keep oven temperatures exactly as the recipe gives them (same number and °F/°C). Describe stovetop heat as low, "
        "medium-low, medium, medium-high or high in the heat field. "
        "TIMES: only use times that appear in the recipe. Never invent a time. When a step waits for a stated time "
        "(simmer, bake, rest, marinate, boil, chill, rise), put that exact time in the step text and set timer_minutes to "
        "the low end of it with a short timer_label such as 'Simmer sauce'. When the recipe gives no time, leave "
        "timer_minutes null and keep the recipe's doneness cue (e.g. 'until golden'). If something useful can be done "
        "while waiting, say so in the text. Steps are short and imperative, one action each. tips: up to 3 short tips "
        "specific to this recipe. "
        "INGREDIENT PLACEMENT (most important): each step's ingredients list holds ONLY the ingredients physically added or used "
        "in that exact step, with the amount used there. Example: 'Whisk the wet ingredients' lists only buttermilk, eggs and melted "
        "butter; the next step 'Add the dry ingredients' lists only flour, sugar, baking powder and salt. If an original step adds "
        "two groups at different moments, split it into separate steps. Never make a 'gather' or 'prep everything' step that lists "
        "ingredients. Don't re-list a mixture made earlier (e.g. 'the batter'). Every ingredient index appears at least once; an "
        "ingredient split across steps gets a portion in each (portions add up to 1).")
    data = openai_chat([
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"Recipe: {rec['name']} (serves {rec['servings'] or '?'})\n\nIngredients:\n{ing_lines}\n\n"
                                    f"Original steps:\n{step_lines}\n\nTimes stated in this recipe: "
                                    f"{', '.join(hint) if hint else 'none'}"},
    ], "guided_recipe", GUIDE_SCHEMA, "step-by-step", rec["name"])
    valid = {x["i"] for x in rec["ingredients"]}
    steps = []
    for s0 in data.get("steps") or []:
        text = s0.get("text") or ""
        tmg = _timing(text)
        tmg["timers"] = [t for t in tmg["timers"] if t["sec"] in stated]           # only times the recipe states
        tm = s0.get("timer_minutes")
        if not tmg["timers"] and tm and int(round(float(tm) * 60)) in stated:
            sec = int(round(float(tm) * 60))
            tmg["timers"] = [{"sec": sec, "high_sec": None, "label": n_timers.fmt(sec), "kind": "countdown", "source": ""}]
        if tmg["timers"] and s0.get("timer_label") and len(tmg["timers"]) == 1 and tmg["timers"][0]["kind"] == "countdown":
            tmg["timers"][0]["name"] = str(s0["timer_label"])[:40]
        steps.append({"title": s0.get("title") or "", "text": text,
                      "ingredients": [{"i": x["index"], "portion": max(0.05, min(1.0, float(x.get("portion") or 1)))}
                                      for x in s0.get("ingredients") or [] if x.get("index") in valid],
                      **tmg, "heat": s0.get("heat"), "temp_raw": _temp_raw(s0.get("temperature") or "") or _temp_raw(text)})
    if not steps:
        raise ApiError(502, "The AI didn't return any steps. Try again.")
    used = {x["i"] for st in steps for x in st["ingredients"]}
    for x in rec["ingredients"]:   # safety net: attach anything the AI skipped to the first step that mentions it
        if x["i"] in used or not x["food"]:
            continue
        key = clean_food(x["food"]).lower().split()[-1] if clean_food(x["food"]) else ""
        st = next((st for st in steps if key and key in st["text"].lower()), None)
        if st:
            st["ingredients"].append({"i": x["i"], "portion": 1})
    return {"source": "ai", "steps": steps, "tips": (data.get("tips") or [])[:3]}


def _guided_cached(c, rec_id, tag, key):
    row = c.execute("SELECT data FROM guided_cache WHERE recipe_id=? AND profile=? AND updated=?", (rec_id, tag, key)).fetchone()
    return json.loads(row["data"]) if row else None


def _guided_store(rec, tag, key, data):
    with db() as c:
        c.execute("INSERT INTO guided_cache(recipe_id, profile, updated, source, data, created_at) VALUES (?,?,?,?,?,?) "
                  "ON CONFLICT(recipe_id, profile) DO UPDATE SET updated=excluded.updated, source=excluded.source, "
                  "data=excluded.data, created_at=excluded.created_at",
                  (rec["id"], tag, key, data["source"], json.dumps(data), datetime.now().isoformat(timespec="seconds")))


def guided(slug, use_ai=None, refresh=False):
    """Step-by-step version of a recipe.
    use_ai=None (cook mode): the AI version when it's ready, otherwise the instant built-in one right away while the
    AI version is prepared in the background (ai_pending). use_ai=True: the AI version now (an explicit request).
    use_ai=False: the built-in arranger."""
    rec = recipe_detail(slug)
    key = _guided_key(rec)
    with db() as c:
        ai = None if refresh else _guided_cached(c, rec["id"], GUIDED_AI, key)
    if ai is not None and use_ai is not False:
        return {**guided_localize(ai), "cached": True, "ai_available": True}
    if use_ai is True:
        data = guided_ai(rec)
        _guided_store(rec, GUIDED_AI, key, data)
        return {**guided_localize(data), "cached": False, "ai_available": True}
    with db() as c:
        auto = _guided_cached(c, rec["id"], GUIDED_AUTO, key)
    if auto is None:
        auto = guided_auto(rec)
        _guided_store(rec, GUIDED_AUTO, key, auto)
    pending = use_ai is None and bool(cfg("openai_key"))
    if pending:
        queue_guided(rec["slug"] if rec.get("slug") else slug, delay=0)
    return {**guided_localize(auto), "cached": True, "ai_available": False, "ai_pending": pending}


# Rebuilding the AI step-by-step after an edit: debounced (several quick edits make one AI call) and one per recipe.
GUIDED_DEBOUNCE = 4.0
_gq_lock = threading.Lock()
_gq_timers, _gq_running = {}, set()


def queue_guided(slug, delay=None):
    if not cfg("openai_key") or not slug:
        return
    with _gq_lock:
        t = _gq_timers.pop(slug, None)
        if t:
            t.cancel()
        if slug in _gq_running and delay == 0:
            return
        t = threading.Timer(GUIDED_DEBOUNCE if delay is None else delay, background, (_guided_build, slug))
        t.daemon = True
        _gq_timers[slug] = t
        t.start()


def _guided_build(slug):
    with _gq_lock:
        _gq_timers.pop(slug, None)
        if slug in _gq_running:
            return
        _gq_running.add(slug)
    try:
        guided(slug, True)
    except ApiError as e:
        log(f"step-by-step for {slug} not prepared:", e.message)
        _gw_failed[slug] = time.time()
    finally:
        with _gq_lock:
            _gq_running.discard(slug)


def invalidate_guided(c, rec_id, slug):
    """The recipe's text changed: drop its step-by-step and prepare a fresh one in the background."""
    c.execute("DELETE FROM guided_cache WHERE recipe_id=?", (rec_id,))
    queue_guided(slug)


# Warming: recipes on the plan for the next 14 days first, then the rest, one at a time with a pause between.
_gw_failed = {}


def guided_warm_candidates(limit=400):
    with db() as c:
        planned = [r["recipe_id"] for r in c.execute(
            "SELECT recipe_id, MIN(date) d FROM meal_plans WHERE recipe_id IS NOT NULL AND date>=? AND date<=? "
            "GROUP BY recipe_id ORDER BY d", (iso(today()), iso(today() + timedelta(days=14))))]
        rest = [r["id"] for r in c.execute("SELECT id FROM recipes ORDER BY updated_at DESC LIMIT ?", (limit,))]
        slugs = {r["id"]: r["slug"] for r in c.execute("SELECT id, slug FROM recipes")}
    seen, out = set(), []
    for rid in planned + rest:
        if rid in slugs and rid not in seen:
            seen.add(rid); out.append(slugs[rid])
    return out


def _ai_over_budget():
    budget = float(get_settings().get("ai_budget") or 0)
    if budget <= 0:
        return False
    try:
        sp = ai_spending()
        return float(sp.get("estimate_usd") or 0) >= budget
    except Exception:
        return False


def guided_warm_next():
    """Prepare one missing AI step-by-step. Returns the slug it prepared, or None when there's nothing to do."""
    if not (NATIVE and cfg("openai_key")) or _ai_over_budget():
        return None
    for slug in guided_warm_candidates():
        if time.time() - _gw_failed.get(slug, 0) < 86400 or slug in _gq_running:
            continue
        try:
            rec = recipe_detail(slug)
        except ApiError:
            continue
        if not rec.get("steps"):
            continue
        with db() as c:
            if _guided_cached(c, rec["id"], GUIDED_AI, _guided_key(rec)) is not None:
                continue
        _guided_build(slug)
        return slug
    return None


def guided_warmer():
    time.sleep(120)   # let start-up finish
    while True:
        try:
            did = guided_warm_next()
        except Exception as e:
            log("step-by-step warm-up error:", e)
            did = None
        time.sleep(90 if did else 900)


# ============================================================ AI spending

_costs_cache = {"at": 0, "data": None}


def openai_costs(force=False):
    """Exact spend from OpenAI's Costs API (needs an Admin key)."""
    key = cfg("openai_admin_key")
    if not key:
        return None
    if not force and time.time() - _costs_cache["at"] < 1800 and _costs_cache["data"]:
        return _costs_cache["data"]
    start = datetime(today().year, today().month, 1)
    res = _https_json("https://api.openai.com/v1/organization/costs?" + urllib.parse.urlencode(
        {"start_time": int(start.timestamp()), "bucket_width": "1d", "limit": 31}), headers={"Authorization": f"Bearer {key}"})
    days = []
    for b in res.get("data") or []:
        amt = sum(float((x.get("amount") or {}).get("value") or 0) for x in b.get("results") or [])
        days.append({"date": datetime.fromtimestamp(b["start_time"]).date().isoformat(), "usd": round(amt, 4)})
    data = {"total": round(sum(d["usd"] for d in days), 4), "days": days, "currency": "usd"}
    _costs_cache.update(at=time.time(), data=data)
    return data


def ai_spending():
    month = today().strftime("%Y-%m")
    with db() as c:
        rows = c.execute("SELECT feature, COUNT(*) n, SUM(COALESCE(cost_usd,0)) usd, SUM(COALESCE(input_tokens,0)) tin, "
                         "SUM(COALESCE(output_tokens,0)) tout FROM ai_usage WHERE substr(at,1,7)=? GROUP BY feature", (month,)).fetchall()
        recent = [dict(r) for r in c.execute("SELECT at, feature, model, input_tokens, output_tokens, cost_usd, detail FROM ai_usage "
                                              "ORDER BY id DESC LIMIT 25")]
        daily = [dict(r) for r in c.execute("SELECT substr(at,1,10) date, SUM(COALESCE(cost_usd,0)) usd FROM ai_usage "
                                             "WHERE substr(at,1,7)=? GROUP BY date ORDER BY date", (month,))]
    exact, exact_error = None, None
    try:
        exact = openai_costs()
    except ApiError as e:
        exact_error = e.message
    est = round(sum(r["usd"] for r in rows), 4)
    return {"month": month, "estimate_usd": est, "by_feature": [dict(r) for r in rows], "daily": daily, "recent": recent,
            "exact": exact, "exact_error": exact_error, "has_admin_key": bool(cfg("openai_admin_key")),
            "has_key": bool(cfg("openai_key")), "model": cfg("openai_model"), "budget": float(get_settings().get("ai_budget") or 0),
            "prices": {k: {"input": v[0], "output": v[1]} for k, v in AI_PRICES.items()}}


# ============================================================ barcode lookup & pantry check-ins

_PACK_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:x|×|\*)\s*(\d+(?:[.,]\d+)?)\s*(fl\.?\s*oz|[a-zA-Z]+)")
_SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(fl\.?\s*oz|[a-zA-Z]+)")


def parse_pack(text):
    """Package size text -> {qty, unit, count, each_qty, each_unit}.
    '26 oz' -> qty 26 oz; '1 L' -> 1 l; '12 × 355 ml' -> count 12 of 355 ml; '1 dozen' -> 12 count; '6 ct' -> 6."""
    t = (text or "").strip().lower().replace(",", ".")
    if not t:
        return None
    m = _PACK_RE.search(t)
    if m:
        n, each, u = float(m.group(1)), float(m.group(2)), n_units.normalize(m.group(3))
        if n_units.dimension(u) in ("volume", "weight"):
            return {"qty": n, "unit": "", "count": n, "each_qty": each, "each_unit": u}
    m = re.search(r"(\d+(?:\.\d+)?)\s*dozen|\bdozen\b", t)
    if m:
        n = float(m.group(1)) if m.group(1) else 1.0
        return {"qty": n * 12, "unit": "", "count": n * 12, "each_qty": None, "each_unit": None}
    m = re.search(r"(\d+)\s*(?:ct|count|pk|pack|pcs|pieces|eggs)\b", t)
    if m:
        return {"qty": float(m.group(1)), "unit": "", "count": float(m.group(1)), "each_qty": None, "each_unit": None}
    for m in _SIZE_RE.finditer(t):
        u = n_units.normalize(m.group(2))
        if n_units.dimension(u) in ("volume", "weight"):
            return {"qty": float(m.group(1)), "unit": u, "count": 1, "each_qty": None, "each_unit": None}
    return None


def _product_food(c, name, generic, cats, brand):
    """Canonical food for a product: its name, generic name or categories (most specific last), else a new food."""
    for cand in [generic, name] + list(reversed(cats or [])):
        if cand and n_foods.normalize(cand, brand):
            fid = n_foods.lookup(c, cand, brand)
            if fid is not None:
                return fid
    return n_foods.resolve(c, name or generic, brand)


NEG_CACHE_DAYS = 7   # "not found" is asked again after a week (products get added to the databases)


def _upc_local(c, codes):
    for k in codes:
        r = c.execute("SELECT * FROM upc_local WHERE code=?", (k,)).fetchone()
        if r:
            return r
    return None


def upc_lookup(code, fresh=False):
    """Barcode → product. Saved-by-you first, then the cache, then Open Food Facts → Open Products Facts → UPCitemdb,
    trying the UPC-A and EAN-13 spellings. Every provider's answer is written to the scan log."""
    n = n_barcodes.normalize(code)
    if n["misread"]:
        raise ApiError(422, "That barcode didn't read cleanly. Scan it again.")
    codes = list(dict.fromkeys([n["code"]] + n["try"] + [code]))
    with db() as c:
        local = _upc_local(c, codes)
        if local:
            f = n_foods.get(c, local["food_id"]) if local["food_id"] else None
            return {"code": n["code"], "found": True, "name": local["name"], "brand": local["brand"] or "",
                    "quantity": local["quantity"] or "", "categories": [], "source": "Saved by you", "food_id": local["food_id"],
                    "food_name": f["name"] if f else local["name"], "pack": parse_pack(local["quantity"]), "image_url": "", "rule": None}
        row = None if fresh else next((r for r in (c.execute("SELECT data, at FROM upc_cache WHERE code=?", (k,)).fetchone() for k in codes) if r), None)
    if row:
        data = json.loads(row["data"])
        stale = not data.get("found") and (parse_date(row["at"]) or today()) <= today() - timedelta(days=NEG_CACHE_DAYS)
        if not stale:
            return data
    data, answered, errors, log_rows = None, None, [], []
    for source in UPC_SOURCES:   # Open Food Facts, then Open Products Facts, then UPCitemdb's free trial
        name = getattr(source, "label", getattr(source, "__name__", "source"))
        for t in n["try"]:
            t0 = time.time()
            try:
                data = source(t)
                if data is not None:
                    answered = data
                log_rows.append({"source": name, "code": t, "status": "found" if data and data.get("found") else "not found",
                                 "ms": int((time.time() - t0) * 1000)})
            except ApiError as e:
                errors.append(e.message)
                log_rows.append({"source": name, "code": t, "status": f"error {e.status}: {(e.message or '')[:80]}",
                                 "ms": int((time.time() - t0) * 1000)})
                data = None
                break   # this provider is down or resting: next provider
            if data and data.get("found"):
                break
        if data and data.get("found"):
            break
    with db() as c:
        c.execute("INSERT INTO scan_log(code, at, results) VALUES (?,?,?)", (n["code"], datetime.now().isoformat(timespec="seconds"), json.dumps(log_rows)))
        c.execute("DELETE FROM scan_log WHERE id NOT IN (SELECT id FROM scan_log ORDER BY id DESC LIMIT 500)")
    if data is None or not data.get("found"):
        data = answered   # a provider that said "not found" still counts as an answer
    if data is None:
        raise ApiError(502, f"Couldn't look up that barcode ({errors[0] if errors else 'no answer'}).")
    data["code"] = n["code"]
    fid = None
    if data.get("found"):
        name, cats, brand = data["name"], data.get("categories") or [], data.get("brand") or ""
        with db() as c:
            rule = match_rule(c, name) or next((match_rule(c, cat) for cat in reversed(cats) if match_rule(c, cat)), None)
            fid = _product_food(c, name, data.pop("generic", ""), cats[-4:], brand)
            f = n_foods.get(c, fid) if fid else None
        data["rule"] = {"id": rule["id"], "name": rule["name"], "location": rule["default_location"]} if rule else None
        data["food_id"], data["food_name"] = fid, (f["name"] if f else name)
    data.pop("generic", None)
    if not data.get("found") and errors:
        return data   # someone didn't answer: don't remember "not found" yet
    with db() as c:
        c.execute("INSERT OR REPLACE INTO upc_cache(code, data, at, food_id) VALUES (?,?,?,?)",
                  (n["code"], json.dumps(data), iso(today()), fid))
    return data


def upc_diagnose(code):
    """Settings → Test barcode lookup: each provider's answer for a code, no cache."""
    n = n_barcodes.normalize(code)
    if n["misread"]:
        return {"code": code, "misread": True, "results": []}
    out = []
    for source in UPC_SOURCES:
        name = getattr(source, "label", getattr(source, "__name__", "source"))
        for t in n["try"][:2]:
            t0 = time.time()
            try:
                d = source(t)
                out.append({"source": name, "code": t, "status": "found" if d.get("found") else "not found",
                            "name": d.get("name") or "", "ms": int((time.time() - t0) * 1000)})
            except ApiError as e:
                out.append({"source": name, "code": t, "status": f"error {e.status}", "name": e.message[:120],
                            "ms": int((time.time() - t0) * 1000)})
    with db() as c:
        local = _upc_local(c, [n["code"]] + n["try"])
    return {"code": n["code"], "misread": False, "saved_by_you": local["name"] if local else None, "results": out}


def _off_like(host, source):
    def lookup(code):
        res = _https_json(f"https://{host}/api/v2/product/{code}.json?" + urllib.parse.urlencode(
            {"fields": "product_name,product_name_en,generic_name,generic_name_en,brands,quantity,categories_tags,"
                       "image_front_small_url,image_front_url,expiration_date"}), timeout=12)
        p = res.get("product") or {}
        name = (p.get("product_name_en") or p.get("product_name") or p.get("generic_name") or "").strip()
        cats = [c.split(":", 1)[-1].replace("-", " ") for c in (p.get("categories_tags") or []) if c.startswith("en:")]
        return {"code": code, "found": bool(res.get("status") == 1 and name), "name": name,
                "generic": (p.get("generic_name_en") or p.get("generic_name") or "").strip(),
                "brand": (p.get("brands") or "").split(",")[0].strip(), "quantity": p.get("quantity") or "",
                "categories": cats[-4:], "source": source, "pack": parse_pack(p.get("quantity") or ""),
                "image_url": p.get("image_front_small_url") or p.get("image_front_url") or "", "food_id": None, "food_name": "",
                "expiration_date": p.get("expiration_date") or ""}
    lookup.label = source
    return lookup


_UPCITEMDB = {"until": 0.0}


def _upcitemdb(code):
    """UPCitemdb free trial (no key, rate-limited): backs off for an hour after a 429."""
    if time.time() < _UPCITEMDB["until"]:
        raise ApiError(429, "UPCitemdb is resting")
    try:
        res = _https_json("https://api.upcitemdb.com/prod/trial/lookup?" + urllib.parse.urlencode({"upc": code}), timeout=12)
    except ApiError as e:
        if "429" in (e.message or "") or e.status == 429:
            _UPCITEMDB["until"] = time.time() + 3600
        raise
    item = (res.get("items") or [{}])[0] if isinstance(res, dict) else {}
    title = (item.get("title") or "").strip()
    size = (item.get("size") or "").strip()
    if not size:
        m = re.search(r"(\d+(?:\.\d+)?\s*(?:fl\.?\s*oz|oz|lb|lbs|g|kg|ml|l|ct|count)\b)", title, re.I)
        size = m.group(1) if m else ""
    images = item.get("images") or []
    return {"code": code, "found": bool(title), "name": title, "generic": "", "brand": (item.get("brand") or "").strip(),
            "quantity": size, "categories": [x.strip() for x in (item.get("category") or "").split(">") if x.strip()][-3:],
            "source": "UPCitemdb", "pack": parse_pack(size), "image_url": images[0] if images else "", "food_id": None,
            "food_name": ""}


_upcitemdb.label = "UPCitemdb"
UPC_SOURCES = [_off_like("world.openfoodfacts.org", "Open Food Facts"),
               _off_like("world.openproductsfacts.org", "Open Products Facts"), _upcitemdb]


def plu_lookup(code):
    """Produce sticker codes (4011 bananas, 94011 organic bananas)."""
    hit = n_plu.lookup(code)
    if not hit:
        return None
    with db() as c:
        fid = n_foods.resolve(c, hit["food"])
        f = n_foods.get(c, fid)
        rule = match_rule(c, hit["food"])
    label = ", ".join(x for x in ("Organic" if hit["organic"] else "", hit["variety"]) if x)
    return {"code": code, "found": True, "name": hit["food"], "brand": "", "quantity": "", "categories": [],
            "source": "Produce code", "pack": None, "image_url": "", "food_id": fid, "food_name": f["name"],
            "variety": label, "rule": {"id": rule["id"], "name": rule["name"], "location": rule["default_location"]} if rule else None}


# ============================================================ grocery trips (receipt or scanner) and purchases

RECEIPT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["store_name", "date", "items", "total"],
    "properties": {
        "store_name": {"type": "string"}, "date": {"type": "string"}, "total": {"type": ["number", "null"]},
        "items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "required": ["raw_text", "name", "quantity", "unit", "price", "is_food"],
                                             "properties": {"raw_text": {"type": "string"}, "name": {"type": "string"},
                                                            "quantity": {"type": ["number", "null"]}, "unit": {"type": "string"},
                                                            "price": {"type": ["number", "null"]}, "is_food": {"type": "boolean"}}}},
    },
}
RECEIPT_PROMPT = (
    "Read this grocery receipt. List ONLY the purchased items actually printed on it, in order; never invent items. "
    "Skip subtotals, taxes, bag fees, coupons, discounts, savings, deposits, payment and loyalty lines (a discount just "
    "lowers the item above it; use the final price you can see for the item if it's clear, else the printed price).\n"
    "For each item: raw_text = the line exactly as printed; name = a plain, normalised grocery name without brand or size "
    "(expand abbreviations: 'GRND BF 80/20' -> 'ground beef 80/20', 'ORG BNNA' -> 'organic bananas', 'HVY WHP CRM' -> "
    "'heavy whipping cream', 'BNLS SKNLS CHKN BRST' -> 'boneless skinless chicken breast', 'GV' / 'KS' / 'TJ' / '365' / 'S. TRUTH' "
    "are store brands); quantity and unit from the line or the pack size (weighted produce like 'BANANAS 2.31 lb @ 0.59/lb' "
    "-> quantity 2.31, unit 'lb'; '2 @ 3.49' -> quantity 2, unit ''; '12 CT' -> 12); price = the line total in dollars; "
    "is_food = false for non-food (paper towels, soap, batteries, pet supplies, cleaning, medicine, gift cards).\n"
    "Grocer conventions: Costco prints item numbers before names and 'E' tax flags; Walmart prints UPCs and 'X/N/O' "
    "flags; Aldi uses short names and 'A/B' tax codes; Kroger, Safeway/Albertsons, Publix, H-E-B, Meijer and Target show "
    "'SC' or 'You saved' discount lines under items; Trader Joe's and Whole Foods use readable names. store_name = the store "
    "as printed; date = YYYY-MM-DD if printed, else empty; total = the receipt total or null.")
_WEIGHTED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(lb|lbs|kg|oz)\b\s*@\s*\$?\s*(\d+(?:\.\d+)?)", re.I)
_COUNT_AT_RE = re.compile(r"\b(\d+)\s*@\s*\$?\s*(\d+(?:\.\d+)?)")


def _receipt_line_fix(it):
    """Fill quantity/unit/price from the printed line when the reader missed them (weighted produce, 'N @ price')."""
    raw = it.get("raw_text") or ""
    m = _WEIGHTED_RE.search(raw)
    if m and not it.get("quantity"):
        it["quantity"], it["unit"] = float(m.group(1)), n_units.normalize(m.group(2))
        if it.get("price") is None:
            it["price"] = round(float(m.group(1)) * float(m.group(3)), 2)
    m = _COUNT_AT_RE.search(raw)
    if m and not it.get("quantity") and not _WEIGHTED_RE.search(raw):
        it["quantity"], it["unit"] = float(m.group(1)), ""
        if it.get("price") is None:
            it["price"] = round(float(m.group(1)) * float(m.group(2)), 2)
    if it.get("unit"):
        it["unit"] = n_units.normalize(it["unit"])
    return it


def _receipt_content(images):
    content = [{"type": "text", "text": RECEIPT_PROMPT}]
    for im in images[:6]:
        data = im.get("data") if isinstance(im, dict) else None
        if not isinstance(data, str):
            raise ApiError(400, "Expected photos or PDFs of the receipt.")
        if data.startswith("data:application/pdf"):
            content.append({"type": "file", "file": {"filename": "receipt.pdf", "file_data": data}})
        elif re.match(r"data:image/(jpeg|jpg|png|webp|gif|heic|heif);base64,", data[:40]):
            content.append({"type": "image_url", "image_url": {"url": data, "detail": "high"}})
        else:
            raise ApiError(400, "Upload a photo or PDF of the receipt.")
    return content


def trip_rows(c, items, lid=None):
    """Match receipt/scan items to canonical foods, unchecked list items and inventory; pick a default action."""
    lid = lid or n_lists.single_list(c)
    rows, used_list = [], set()
    for it in items:
        name = " ".join(str(it.get("name") or it.get("raw_text") or "").split())[:80]
        if not name:
            continue
        fid = n_foods.resolve(c, name) if n_foods.normalize(name) else None
        f = n_foods.get(c, fid) if fid else None
        li = None
        if fid is not None:
            li = c.execute("SELECT * FROM shopping_items WHERE list_id=? AND checked=0 AND food_id=? ORDER BY position",
                           (lid, fid)).fetchall()
            li = next((r for r in li if r["id"] not in used_list), None)
        if li:
            used_list.add(li["id"])
        unit = n_units.normalize(it.get("unit") or "")
        qty = it.get("quantity") if isinstance(it.get("quantity"), (int, float)) and it.get("quantity") > 0 else None
        pi = None
        if fid is not None:
            for r in c.execute("SELECT * FROM pantry_items WHERE status='active' AND food_id=? ORDER BY id DESC", (fid,)):
                if r["qty"] is not None and qty is not None and n_units.convert(1, unit, r["unit"]) is not None:
                    pi = r
                    break
        rule = match_rule(c, f["name"] if f else name)
        loc = (f or {}).get("location") or (rule["default_location"] if rule else "pantry")
        food = it.get("is_food", True) is not False
        rows.append({"raw_text": (it.get("raw_text") or "")[:120], "name": f["name"] if f else name, "food_id": fid,
                     "quantity": qty, "unit": unit, "price": it.get("price") if isinstance(it.get("price"), (int, float)) else None,
                     "location": loc if loc in LOCATIONS else "pantry",
                     "list_item": {"id": li["id"], "text": n_lists._display(li)} if li else None,
                     "pantry_item": {"id": pi["id"], "name": pi["name"], "left_text": pantry_left_text(pi)} if pi else None,
                     "action": "ignore" if not food else "check_off" if li else "add"})
    return rows


def receipt_read(b):
    """POST /api/receipt {images}: read a receipt with AI and return the review rows (nothing is changed yet)."""
    require_native()
    if not cfg("openai_key"):
        raise ApiError(400, "Reading receipts needs AI. Add your OpenAI key in Settings → AI recipe import, or scan the items instead.")
    images = b.get("images")
    if not isinstance(images, list) or not images:
        raise ApiError(400, "Add a photo or PDF of the receipt.")
    out = openai_chat([{"role": "user", "content": _receipt_content(images)}], "receipt", RECEIPT_SCHEMA, "receipt",
                      f"{len(images)} file(s)")
    items = [_receipt_line_fix(dict(x)) for x in out.get("items") or [] if isinstance(x, dict)]
    with db() as c:
        rows = trip_rows(c, items)
    d = parse_date(out.get("date"))
    return {"store_name": (out.get("store_name") or "").strip()[:60], "date": iso(d) if d else iso(today()),
            "total": out.get("total"), "rows": rows}


def _save_trip_files(trip_id, images):
    out = []
    d = os.path.join(IMG_DIR, "trips", str(int(trip_id)))
    for i, im in enumerate((images or [])[:6], 1):
        data = im.get("data") if isinstance(im, dict) else ""
        head, _, b64 = (data or "").partition(",")
        if not b64:
            continue
        try:
            blob = base64.b64decode(b64)
        except ValueError:
            continue
        if head.startswith("data:application/pdf") and blob[:5] == b"%PDF-":
            ext = "pdf"
        else:
            kind = n_recipes.sniff_image(blob[:64])
            if not kind:
                continue
            ext = "jpg" if kind == "jpg" else kind
        if len(blob) > 15_000_000:
            continue
        os.makedirs(d, exist_ok=True)
        name = f"receipt-{i}.{ext}"
        with open(os.path.join(d, name), "wb") as f:
            f.write(blob)
        out.append(name)
    return out


def trip_apply(b):
    """POST /api/trip/apply: tick off list items, add or top up inventory, record purchases; one Undo for all of it."""
    require_native()
    rows = b.get("rows")
    if not isinstance(rows, list) or not rows or len(rows) > 300:
        raise ApiError(400, "Nothing to apply.")
    store_id = _store_arg(b.get("store_id"))
    store_name = " ".join(_s(b.get("store_name"), 60).split())
    d = parse_date(b.get("date")) or today()
    method = b.get("method") if b.get("method") in ("receipt", "scanner") else "receipt"
    undo = {"created": [], "increased": [], "checked": []}
    checked = items = 0
    total = 0.0
    now = datetime.now().isoformat(timespec="seconds")
    with db() as c:
        if store_id is not None:
            st = n_lists.get_store(c, store_id)
            if not st:
                raise ApiError(404, "Store not found")
            store_name = store_name or st["name"]
        lid = n_lists.single_list(c)
        cur = c.execute("INSERT INTO trips(store_id, store_name, date, method, created_at) VALUES (?,?,?,?,?)",
                        (store_id, store_name, iso(d), method, now))
        trip_id = cur.lastrowid
        for r in rows:
            if not isinstance(r, dict):
                raise ApiError(400, "Bad row.")
            action = r.get("action")
            if action not in ("check_off", "add", "increase", "ignore"):
                raise ApiError(400, "Unknown action.")
            name = " ".join(_s(r.get("name"), 80).split())
            if not name:
                continue
            price = r.get("price") if isinstance(r.get("price"), (int, float)) and not isinstance(r.get("price"), bool) and 0 <= r["price"] < 100000 else None
            qty = r.get("quantity") if isinstance(r.get("quantity"), (int, float)) and not isinstance(r.get("quantity"), bool) and 0 < r["quantity"] < 1e6 else None
            unit = n_units.normalize(_s(r.get("unit"), 20)) if qty is not None else None
            if unit and n_units.dimension(unit) is None:
                unit = ""
            loc = r.get("location") if split_place(r.get("location"))[0] else None
            fid = _food_id(c, name)
            pid = li_id = None
            if action == "check_off":
                li = c.execute("SELECT id FROM shopping_items WHERE id=? AND list_id=? AND checked=0",
                               (_s(r.get("list_item_id"), 64), lid)).fetchone() if r.get("list_item_id") else None
                if li:
                    fulfill_line(c, lid, li["id"], None, " ".join(_s(r.get("raw_text"), 120).split()) or name,
                                 n_units.fmt(qty, unit) if qty is not None else "", price, store_id, _s(r.get("upc"), 20))
                    undo["checked"].append(li["id"])
                    li_id = li["id"]
                    checked += 1
                action = "add"
            if action == "increase" and r.get("pantry_item_id") is not None:
                p = pantry_row(c, _int_id(r.get("pantry_item_id"), "item"))
                add = n_units.convert(qty, unit, p["unit"]) if p and p["qty"] is not None and qty is not None else None
                if add is not None:
                    undo["increased"].append({"id": p["id"], "qty": p["qty"], "original_qty": p["original_qty"], "amount_left": p["amount_left"]})
                    nq = p["qty"] + add
                    orig = max(nq, (p["original_qty"] or p["qty"]) + add)
                    c.execute("UPDATE pantry_items SET qty=?, original_qty=?, amount_left=? WHERE id=?", (nq, orig, min(1.0, nq / orig), p["id"]))
                    event(c, p["id"], "restocked", f"+{n_units.fmt(add, p['unit'])} ({store_name or 'trip'})")
                    pid = p["id"]
                else:
                    action = "add"
            if action == "add":
                printed = parse_date(r.get("expires_on")) if isinstance(r.get("expires_on"), str) else None
                pid = add_pantry_item(c, name, loc, iso(printed) if printed else None, n_units.fmt(qty, unit) if qty is not None else "",
                                      li_id, qty, unit, fid)
                undo["created"].append(pid)
                left = r.get("left")
                if isinstance(left, (int, float)) and not isinstance(left, bool) and 0 < left < 0.999:
                    apply_pantry_action(c, pid, {"action": "fill", "left": left})
            if action != "ignore":
                items += 1
            if price is not None:
                total += price
            c.execute("INSERT INTO purchases(trip_id, store_name, date, food_id, name, raw_text, qty, unit, price, pantry_item_id, "
                      "list_item_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (trip_id, store_name, iso(d), fid if action != "ignore" else None, name, _s(r.get("raw_text"), 120), qty, unit,
                       price, pid, li_id))
        total = round(total, 2) if any(isinstance(r.get("price"), (int, float)) for r in rows if isinstance(r, dict)) else None
        c.execute("UPDATE trips SET items=?, checked=?, total=?, undo=? WHERE id=?", (items, checked, total, json.dumps(undo), trip_id))
    files = _save_trip_files(trip_id, b.get("files"))
    if files:
        with db() as c:
            c.execute("UPDATE trips SET files=? WHERE id=?", (json.dumps(files), trip_id))
    summary = " · ".join(x for x in (store_name or "Grocery trip", plural_s(items, "item"),
                                       f"${total:,.2f}" if total is not None else "",
                                       f"{checked} checked off your list" if checked else "") if x)
    return {"ok": True, "trip_id": trip_id, "items": items, "checked": checked, "total": total, "summary": summary}


def plural_s(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def trip_undo(trip_id):
    require_native()
    with db() as c:
        t = c.execute("SELECT * FROM trips WHERE id=?", (trip_id,)).fetchone()
        if not t or t["status"] != "done":
            raise ApiError(404, "That trip can't be undone any more.")
        u = json.loads(t["undo"] or "{}")
        for pid in u.get("created") or []:
            c.execute("DELETE FROM pantry_items WHERE id=?", (pid,))
        for x in u.get("increased") or []:
            c.execute("UPDATE pantry_items SET qty=?, original_qty=?, amount_left=? WHERE id=?",
                      (x["qty"], x["original_qty"], x["amount_left"], x["id"]))
        for iid in u.get("checked") or []:
            c.execute("UPDATE shopping_items SET checked=0, checked_at=NULL, checked_how=NULL WHERE id=?", (iid,))
        c.execute("DELETE FROM purchases WHERE trip_id=?", (trip_id,))
        c.execute("UPDATE trips SET status='undone' WHERE id=?", (trip_id,))
    shutil.rmtree(os.path.join(IMG_DIR, "trips", str(int(trip_id))), ignore_errors=True)
    return {"ok": True}


def trip_record_scans(b):
    """A scanner trip: the scans are already in the inventory; record the trip and its purchases for later budgeting."""
    require_native()
    ids = b.get("pantry_item_ids")
    if not isinstance(ids, list) or not ids or len(ids) > 500:
        raise ApiError(400, "Nothing was scanned.")
    store_id = _store_arg(b.get("store_id"))
    store_name = " ".join(_s(b.get("store_name"), 60).split())
    with db() as c:
        if store_id is not None and not store_name:
            st = n_lists.get_store(c, store_id)
            store_name = st["name"] if st else ""
        cur = c.execute("INSERT INTO trips(store_id, store_name, date, method, created_at, undo) VALUES (?,?,?,?,?,?)",
                        (store_id, store_name, iso(today()), "scanner", datetime.now().isoformat(timespec="seconds"),
                         json.dumps({"created": []})))
        tid, n, checked = cur.lastrowid, 0, 0
        for pid in ids:
            p = pantry_row(c, _int_id(pid, "item"))
            if not p:
                continue
            n += 1
            checked += 1 if p["mealie_item_id"] else 0
            c.execute("INSERT INTO purchases(trip_id, store_name, date, food_id, name, qty, unit, pantry_item_id, list_item_id) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", (tid, store_name, iso(today()), p["food_id"], p["name"], p["qty"], p["unit"],
                                                     p["id"], p["mealie_item_id"]))
        c.execute("UPDATE trips SET items=?, checked=? WHERE id=?", (n, checked, tid))
    return {"ok": True, "trip_id": tid, "summary": " · ".join(x for x in (store_name or "Grocery trip", plural_s(n, "item"),
                                                                          f"{checked} checked off your list" if checked else "") if x)}


def _pantry_image(pid, url):
    """Save a product photo for a pantry item (public HTTPS only, real image bytes only)."""
    try:
        blob, ctype = _fetch_image(url)
    except Exception as e:
        log("product photo skipped:", e)
        return None
    return _pantry_image_blob(pid, blob, ctype)


def scan_add(b):
    """POST /api/scan {code, location?, name?, quantity?}: one barcode scan -> a pantry item (and the list ticked).
    Unknown codes need a name; that name is remembered for next time (upc_local)."""
    code = re.sub(r"\D", "", _s(b.get("code"), 20))
    is_plu = len(code) in (4, 5) and n_plu.lookup(code) is not None
    if not (6 <= len(code) <= 14 or is_plu):
        raise ApiError(400, "That isn't a barcode or a produce code we know.")
    if not is_plu:
        nb = n_barcodes.normalize(code)
        if nb["misread"]:   # a bad check digit: the scanner misread it
            return {"ok": False, "code": code, "misread": True, "error": "That barcode didn't read cleanly. Scan it again."}
        code = nb["code"]
    loc = b.get("location") if split_place(b.get("location"))[0] else None
    name = " ".join(_s(b.get("name"), 80).split())
    size = " ".join(_s(b.get("quantity"), 40).split())
    if name:
        with db() as c:
            fid = _food_id(c, name)
            c.execute("INSERT OR REPLACE INTO upc_local(code, food_id, name, quantity, at) VALUES (?,?,?,?,?)",
                      (code, fid, name, size, iso(today())))
    lookup_error = None
    try:
        p = plu_lookup(code) if is_plu else upc_lookup(code)
    except ApiError as e:   # offline or every lookup failed
        p, lookup_error = {"found": False}, e.message
    if not p.get("found"):
        if b.get("placeholder") is False:
            out = {"ok": False, "code": code, "needs_name": True}
            if lookup_error:
                out["error"] = lookup_error
            return out
        # never a dead end: add it now as an unknown item to review later (no typing during a scan session).
        # The same unknown code in the same place again counts up the placeholder that's already waiting.
        kind, place = split_place(loc or "pantry")
        with db() as c:
            same = c.execute("SELECT id FROM pantry_items WHERE status='active' AND review=1 AND upc=? AND location=? "
                             "AND COALESCE(place,'')=? ORDER BY id LIMIT 1", (code, kind or "pantry", place or "")).fetchone()
        if same:
            out = scan_more(same["id"], 1)
            return {"ok": True, "unknown": True, "again": True, "code": code, "item": out["item"], "list_checked": None,
                    "list_ask": None, "error": lookup_error}
        with db() as c:
            pid = add_pantry_item(c, f"Unknown item · {code}", loc or "pantry", None, "")
            c.execute("UPDATE pantry_items SET upc=?, review=1, food_id=NULL, qty=1, unit=NULL, original_qty=1, pack_qty=1 "
                      "WHERE id=?", (code, pid))   # counted in packages until its size is known
            row = pantry_json(c, pantry_row(c, pid))
        return {"ok": True, "unknown": True, "code": code, "item": row, "list_checked": None, "list_ask": None,
                "error": lookup_error}
    pack = p.get("pack") or {}
    with db() as c:
        f = n_foods.get(c, p["food_id"]) if p.get("food_id") else None
        canon = f["name"] if f else p["name"]
        product = " · ".join(x for x in (p.get("brand"), p.get("name") if p.get("name") and p.get("name") != canon else "",
                                         p.get("variety")) if x)
        qty = pack.get("qty") if pack else None
        unit = pack.get("unit") if pack else None
        loc = loc or (f["location"] if f and f.get("location") else None) or (p.get("rule") or {}).get("location")
        printed = parse_date(p.get("expiration_date")) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(p.get("expiration_date") or "")) else None
        pid = add_pantry_item(c, canon, loc, iso(printed) if printed and printed >= today() else None, p.get("quantity") or "",
                              None, qty, unit, p.get("food_id"))
        c.execute("UPDATE pantry_items SET product=?, upc=?, pack_qty=? WHERE id=?", (product or None, code, qty, pid))
        # on the shopping list? one clear match is ticked off; several, or a generic line, are asked about
        checked = ask = None
        if NATIVE:
            lid = n_lists.single_list(c)
            exact, related = list_matches(c, lid, p.get("food_id"), canon)
            size = p.get("quantity") or (n_units.fmt(qty, unit) if qty is not None else "")
            store = _store_arg(b.get("store_id"))
            if len(exact) == 1:
                checked = fulfill_line(c, lid, exact[0]["id"], pid, product or canon, size, None, store, code)
            elif exact or related:
                ask = {"pantry_item_id": pid, "product": product or canon, "size": size, "store_id": store,
                       "candidates": [{"id": r["id"], "text": n_lists._display(r)} for r in (exact or related)][:6]}
            elif p.get("food_id"):
                remember_purchase(c, p["food_id"], product or canon, size, store, None, code)
        row = pantry_json(c, pantry_row(c, pid))
    if p.get("image_url"):
        if _pantry_image(pid, p["image_url"]):
            with db() as c:
                row = pantry_json(c, pantry_row(c, pid))
    return {"ok": True, "code": code, "item": row, "list_checked": checked, "list_ask": ask, "pack": pack or None,
            "product": {"name": p.get("name"), "brand": p.get("brand"), "quantity": p.get("quantity")}}


IDENTIFY_SCHEMA = {"type": "object", "additionalProperties": False,
                   "required": ["name", "brand", "size_text", "category", "food", "confident"],
                   "properties": {"name": {"type": "string"}, "brand": {"type": "string"}, "size_text": {"type": "string"},
                                  "category": {"type": "string"}, "food": {"type": "string"},
                                  "confident": {"type": "object", "additionalProperties": False,
                                                "required": ["name", "brand", "size_text", "category", "food"],
                                                "properties": {k: {"type": "boolean"} for k in ("name", "brand", "size_text", "category", "food")}}}}


def scan_identify(b):
    """POST /api/scan/identify {images: [front, label]}: read a package with AI. Fields it can't read clearly come back
    empty (nothing is guessed); the cook confirms before anything is saved."""
    if not cfg("openai_key"):
        raise ApiError(400, "Reading a package photo needs AI. Add your OpenAI key in Settings → AI recipe import.")
    imgs = [x for x in (b.get("images") or []) if isinstance(x, str) and x.startswith("data:image/")][:2]
    if not imgs:
        raise ApiError(400, "Take a photo of the package.")
    content = [{"type": "text", "text": (
        "These are photos of one grocery package (front, and maybe the label). Read only what is printed: name = what the "
        "product is (e.g. 'Plain Greek yogurt'), brand, size_text = the net size exactly as printed (e.g. '32 oz'), "
        "category = a grocery aisle (Produce, Dairy & Eggs, Meat & Seafood, Bakery, Pantry, Spices, Frozen, Beverages, "
        "Household, Snacks), food = the plain generic food (e.g. 'greek yogurt'). For each field set confident=false and "
        "leave it empty if you can't read it clearly. Never guess.")}]
    content += [{"type": "image_url", "image_url": {"url": x, "detail": "high"}} for x in imgs]
    out = openai_chat([{"role": "user", "content": content}], "package", IDENTIFY_SCHEMA, "package photo", "identify")
    conf = out.get("confident") or {}
    return {k: (" ".join(str(out.get(k) or "").split())[:80] if conf.get(k) else "")
            for k in ("name", "brand", "size_text", "category", "food")}


def pantry_details(pid, b):
    """POST /api/pantry/{id}/details {name, brand?, size?, category?, food?, image?}: finish an unknown scanned item.
    The barcode is remembered (only in this household), so the next scan of it is instant."""
    name = " ".join(_s(b.get("name"), 80).split())
    if not name:
        raise ApiError(400, "Give it a name.")
    brand = " ".join(_s(b.get("brand"), 60).split())
    size = " ".join(_s(b.get("size"), 40).split())
    food = " ".join(_s(b.get("food"), 80).split()) or name
    with db() as c:
        r = pantry_row(c, pid)
        if not r:
            raise ApiError(404, "Item not found")
        fid = n_foods.resolve(c, food, brand)
        canon = (n_foods.get(c, fid) or {}).get("name") or name
        qty, unit = parse_amount(size) if size else (None, None)
        product = " · ".join(x for x in (brand, name if name.lower() != canon.lower() else "") if x) or None
        targets = [r]
        if r["review"] and r["upc"]:   # every placeholder of this code, from any session, learns the same details
            targets += [x for x in c.execute("SELECT * FROM pantry_items WHERE status='active' AND review=1 AND upc=? AND id<>? "
                                             "ORDER BY id", (r["upc"], pid))]
        for t in targets:
            c.execute("UPDATE pantry_items SET name=?, food_id=?, product=?, quantity_text=?, review=0 WHERE id=?",
                      (canon, fid, product, size, t["id"]))
            if qty is not None:
                n = _pack_count(t)
                c.execute("UPDATE pantry_items SET qty=?, unit=?, original_qty=?, pack_qty=? WHERE id=?",
                          (qty * n * (t["amount_left"] or 1), n_units.normalize(unit), qty * n, qty, t["id"]))
        others = [t["id"] for t in targets[1:]]
        if r["upc"]:
            c.execute("INSERT OR REPLACE INTO upc_local(code, food_id, name, quantity, at, brand) VALUES (?,?,?,?,?,?)",
                      (r["upc"], fid, canon, size, iso(today()), brand))
            c.execute("DELETE FROM upc_cache WHERE code=?", (r["upc"],))
        rule = match_rule(c, canon)
        if rule:
            c.execute("UPDATE pantry_items SET rule_id=? WHERE id=?", (rule["id"], pid))
    if b.get("image"):
        blob, ctype = decode_upload(b["image"])
        _pantry_image_blob(pid, blob, ctype)
    with db() as c:
        out = pantry_json(c, pantry_row(c, pid))
        out["same_code"] = [pantry_json(c, x) for x in (pantry_row(c, i) for i in others) if x]
    return out


def _pack_count(r):
    """Packages in a row counted by the package (no unit yet): qty / pack_qty, at least 1."""
    if r["unit"] or not r["pack_qty"] or r["qty"] is None:
        return 1
    return max(1, round(float(r["qty"]) / float(r["pack_qty"])))


def pantry_merge(pid, b):
    """POST /api/pantry/{id}/merge {ids}: fold same-barcode items into this one (package counts add up)."""
    ids = [_int_id(x, "item") for x in (b.get("ids") or [])][:50]
    with db() as c:
        r = pantry_row(c, pid)
        if not r:
            raise ApiError(404, "Item not found")
        rows = [x for x in (pantry_row(c, i) for i in ids if i != pid) if x and x["status"] == "active"]
        if any(x["upc"] != r["upc"] or not r["upc"] or (x["unit"] or "") != (r["unit"] or "") for x in rows):
            raise ApiError(400, "Only items with the same barcode and size can be merged.")
        if r["qty"] is not None:
            q = r["qty"] + sum(x["qty"] or 0 for x in rows)
            o = (r["original_qty"] or r["qty"]) + sum((x["original_qty"] or x["qty"] or 0) for x in rows)
            c.execute("UPDATE pantry_items SET qty=?, original_qty=?, amount_left=? WHERE id=?", (q, o, min(1.0, q / o) if o else 1, pid))
        for x in rows:
            c.execute("DELETE FROM pantry_items WHERE id=?", (x["id"],))
        event(c, pid, "merged", f"{len(rows)} merged in")
        return pantry_json(c, pantry_row(c, pid))


def _pantry_image_blob(pid, blob, ctype):
    """Store an inventory item's photo (metadata stripped). The file name carries a content hash, so a new photo is
    never served from a stale cache; older versions of this item's photo are removed (the kept original stays)."""
    d = os.path.join(IMG_DIR, "pantry")
    os.makedirs(d, exist_ok=True)
    blob = n_imgmeta.strip_metadata(blob)
    fname = f"{int(pid)}-{hashlib.sha1(blob).hexdigest()[:6]}.{_ext(ctype)}"
    for old in os.listdir(d):
        if re.fullmatch(rf"{int(pid)}(-[0-9a-f]{{6}})?\.(jpg|png|webp|gif)", old) and old != fname:
            os.remove(os.path.join(d, old))
    with open(os.path.join(d, fname), "wb") as f:
        f.write(blob)
    with db() as c:
        c.execute("UPDATE pantry_items SET image=? WHERE id=?", (fname, pid))
    return fname


def _pantry_original(pid):
    d = os.path.join(IMG_DIR, "pantry")
    return next((p for p in (os.path.join(d, f"{int(pid)}-orig.{e}") for e in ("jpg", "png", "webp", "gif")) if os.path.exists(p)), None)


def pantry_photo(pid, b):
    """POST /api/pantry/{id}/photo {image, cutout?}: a product photo for an inventory item. A background cut-out keeps
    the photo it was made from, so "Use original photo" can bring it back."""
    require_native()
    blob, ctype = decode_upload(b.get("image"))
    dims = n_imgmeta.size(blob)
    if not dims or max(dims) > 2048:
        raise ApiError(400, "Send a photo up to 2048 pixels.")
    with db() as c:
        r = pantry_row(c, pid)
    if not r:
        raise ApiError(404, "Item not found")
    d = os.path.join(IMG_DIR, "pantry")
    if b.get("cutout") is True:
        if r["image"] and not _pantry_original(pid):
            cur = os.path.join(d, r["image"])
            if os.path.exists(cur):
                shutil.copyfile(cur, os.path.join(d, f"{int(pid)}-orig.{r['image'].rsplit('.', 1)[1]}"))
    else:
        old = _pantry_original(pid)
        if old:
            os.remove(old)
    _pantry_image_blob(pid, blob, ctype)
    with db() as c:
        return pantry_json(c, pantry_row(c, pid))


def pantry_photo_restore(pid):
    """POST /api/pantry/{id}/photo/restore: back to the photo before the cut-out."""
    require_native()
    old = _pantry_original(pid)
    if not old:
        raise ApiError(404, "There's no original photo to go back to.")
    with open(old, "rb") as f:
        blob = f.read()
    kind = n_recipes.sniff_image(blob[:64]) or "jpg"
    _pantry_image_blob(pid, blob, "image/" + ("jpeg" if kind == "jpg" else kind))
    os.remove(old)
    with db() as c:
        return pantry_json(c, pantry_row(c, pid))


def pantry_relookup(pid):
    """"Retry lookup" on an unknown item: ask the barcode databases again (ignoring the 7-day "not found" cache)."""
    with db() as c:
        r = pantry_row(c, pid)
    if not r or not r["upc"]:
        raise ApiError(404, "That item has no barcode.")
    p = upc_lookup(r["upc"], fresh=True)
    if not p.get("found"):
        return {"found": False}
    out = pantry_details(pid, {"name": p.get("food_name") or p["name"], "brand": p.get("brand") or "", "size": p.get("quantity") or "",
                               "food": p.get("food_name") or p["name"]})
    if p.get("image_url"):
        _pantry_image(pid, p["image_url"])
    return {"found": True, "item": out}


SNAP_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["name", "brand", "size_text"],
               "properties": {"name": {"type": "string"}, "brand": {"type": "string"}, "size_text": {"type": "string"}}}


def scan_photo(b):
    """POST /api/scan/photo {code, image, location?}: a barcode nobody knows; read the package photo with AI,
    remember the answer for that code, and add it."""
    if not cfg("openai_key"):
        raise ApiError(400, "Reading a package photo needs AI. Add your OpenAI key in Settings → AI recipe import.")
    code = re.sub(r"\D", "", _s(b.get("code"), 20))
    if not 6 <= len(code) <= 14:
        raise ApiError(400, "That doesn't look like a barcode.")
    img = _s(b.get("image"), 12_000_000)
    if not img.startswith("data:image/"):
        raise ApiError(400, "Send a photo of the package.")
    out = openai_chat([{"role": "user", "content": [
        {"type": "text", "text": "This is a grocery package. Read what is printed on it: name = what the product is (e.g. "
                                 "'Iodized table salt'), brand = the brand, size_text = the net size exactly as printed (e.g. "
                                 "'26 oz', '12 x 355 ml'), or empty. Do not guess anything that isn't visible."},
        {"type": "image_url", "image_url": {"url": img, "detail": "low"}}]}], "package", SNAP_SCHEMA, "package photo", code)
    name = " ".join((out.get("name") or "").split())[:80]
    if not name:
        raise ApiError(422, "Couldn't read the package. Type the name instead.")
    brand = " ".join((out.get("brand") or "").split())[:60]
    with db() as c:
        fid = n_foods.resolve(c, name, brand)
        c.execute("INSERT OR REPLACE INTO upc_local(code, food_id, name, quantity, at) VALUES (?,?,?,?,?)",
                  (code, fid, n_foods.get(c, fid)["name"] if fid else name, (out.get("size_text") or "")[:40], iso(today())))
    res = scan_add({"code": code, "location": b.get("location")})
    if res.get("item") and brand:
        with db() as c:
            c.execute("UPDATE pantry_items SET product=? WHERE id=?", (" · ".join(x for x in (brand, name) if x), res["item"]["id"]))
            res["item"] = pantry_json(c, pantry_row(c, res["item"]["id"]))
    return res


def scan_more(pid, delta):
    """+1 / -1 on a scanned pantry item: known sizes add or remove one package's amount."""
    with db() as c:
        r = pantry_row(c, pid)
        if not r:
            raise ApiError(404, "Item not found")
        if r["qty"] is not None and r["pack_qty"]:
            q = max(0.0, r["qty"] + delta * r["pack_qty"])
            orig = max(q, (r["original_qty"] or 0) + delta * r["pack_qty"])
            c.execute("UPDATE pantry_items SET qty=?, original_qty=?, amount_left=? WHERE id=?",
                      (q, orig or None, min(1.0, q / orig) if orig else 0, pid))
            event(c, pid, "scanned", f"{'+' if delta > 0 else '-'}1 package")
            return {"ok": True, "item": pantry_json(c, pantry_row(c, pid)), "added_id": None}
        if delta > 0:   # amount unknown: another one of the same item
            nid = add_pantry_item(c, r["name"], r["location"], None, r["quantity_text"], None, None, None, r["food_id"])
            c.execute("UPDATE pantry_items SET product=?, upc=?, image=? WHERE id=?", (r["product"], r["upc"], None, nid))
            return {"ok": True, "item": pantry_json(c, pantry_row(c, pid)), "added_id": nid}
        twin = c.execute("SELECT id FROM pantry_items WHERE upc=? AND id<>? AND status='active' ORDER BY id DESC LIMIT 1",
                         (r["upc"], pid)).fetchone() if r["upc"] else None
        if twin:
            c.execute("DELETE FROM pantry_items WHERE id=?", (twin["id"],))
        return {"ok": True, "item": pantry_json(c, pantry_row(c, pid)), "added_id": None}


def scan_undo(b):
    pid = _int_id(b.get("pantry_item_id"), "item")
    with db() as c:
        r = pantry_row(c, pid)
        if not r:
            raise ApiError(404, "Item not found")
        if r["mealie_item_id"]:
            c.execute("UPDATE shopping_items SET checked=0, checked_at=NULL, checked_how=NULL WHERE id=?", (r["mealie_item_id"],))
        c.execute("DELETE FROM pantry_items WHERE id=?", (pid,))
    for f in ([os.path.join(IMG_DIR, "pantry", os.path.basename(r["image"]))] if r["image"] else []) + [_pantry_original(pid)]:
        try:
            if f:
                os.remove(f)
        except OSError:
            pass
    return {"ok": True}


def pantry_checkin_status(now=None):
    """Due once this week's check-in time (Sunday 6 pm by default) has passed; every 2 weeks waits a week longer."""
    s = get_settings()
    days = int(s.get("pantry_check_days") or 0)
    now = now or datetime.now()
    last_dt = _checkin_last()
    if not last_dt:
        with db() as c:
            first = c.execute("SELECT MIN(created_at) FROM pantry_items WHERE status='active'").fetchone()[0]
        if not first:
            return {"interval_days": days, "last": None, "due": False, "days_since": None,
                    "day": s.get("checkin_day") or "sun", "hour": s.get("checkin_hour", 18)}
        last_dt = datetime.combine(parse_date(first), datetime.min.time())
        never = True
    else:
        never = False
    due = n_checkin.is_due(now, last_dt, days, s.get("checkin_day") or "sun", int(s.get("checkin_hour", 18)))
    last = last_dt.date()
    return {"interval_days": days, "last": None if never else iso(last), "due": due, "days_since": (now.date() - last).days,
            "day": s.get("checkin_day") or "sun", "hour": int(s.get("checkin_hour", 18))}


# ============================================================ kitchen check-in (weekly, swipe through ~10 items)

CHECKIN_SNAP = ("status", "amount_left", "finished_on", "qty", "original_qty", "opened_on", "expires_on", "expiry_source")


def _checkin_last():
    """When the last check-in was done (older installs stored just a date: that counts as the end of the day)."""
    raw = get_internal("pantry_checked_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return dt if "T" in str(raw) else dt.replace(hour=23, minute=59)


def _pantry_key(r):
    return f"f:{r['food_id']}" if r["food_id"] is not None else food_key(clean_food(r["name"]))


def checkin_cards(limit=n_checkin.MAX_CARDS):
    """GET /api/checkin: the few items worth asking about, each with a plain reason."""
    t = today()
    with db() as c:
        rows = c.execute("SELECT * FROM pantry_items WHERE status='active'").fetchall()
        last_event, last_asked = {}, {}
        for e in c.execute("SELECT item_id, action, MAX(at) AS at FROM pantry_events GROUP BY item_id, action='checkin'"):
            (last_asked if e["action"] == "checkin" else last_event)[e["item_id"]] = e["at"]
        buys = {}
        for p in c.execute("SELECT food_id, name, date FROM purchases WHERE date>=?", (iso(t - timedelta(days=180)),)).fetchall():
            fid = p["food_id"] if p["food_id"] is not None else (n_foods.lookup(c, p["name"]) if n_foods.normalize(p["name"] or "") else None)
            buys.setdefault(f"f:{fid}" if fid is not None else food_key(clean_food(p["name"])), []).append(p["date"])
        for p in c.execute("SELECT food_id, name, purchased_on FROM pantry_items WHERE purchased_on>=?", (iso(t - timedelta(days=180)),)):
            buys.setdefault(_pantry_key(p), []).append(p["purchased_on"])
        cad = {k: v for k, v in ((k, n_checkin.cadence(ds)) for k, ds in buys.items()) if v}
        rates = {r["food_key"]: r["days"] for r in c.execute("SELECT * FROM consumption WHERE days IS NOT NULL")}
        items = [{**dict(r), "key": _pantry_key(r)} for r in rows]
        picks = n_checkin.candidates(items, t, last_event, last_asked, cad, rates, limit)
        by_id = {r["id"]: r for r in rows}
        cards = [{**pantry_json(c, by_id[p["id"]]), "reason": p["reason"]} for p in picks]
    return {"cards": cards, "status": pantry_checkin_status()}


def _learn(c, r, answer):
    key = _pantry_key(r)
    prev = c.execute("SELECT days, n FROM consumption WHERE food_key=?", (key,)).fetchone()
    before = (prev["days"], prev["n"]) if prev else None
    age = (today() - (parse_date(r["purchased_on"]) or today())).days
    days, n = n_checkin.learn(prev["days"] if prev else None, prev["n"] if prev else 0, age, answer)
    if days is not None:
        c.execute("INSERT INTO consumption(food_key, days, n, updated) VALUES (?,?,?,?) ON CONFLICT(food_key) DO UPDATE SET "
                  "days=excluded.days, n=excluded.n, updated=excluded.updated", (key, days, n, iso(today())))
    return {"key": key, "before": before}


def checkin_answer(b):
    """POST /api/checkin/answer {id, answer: have|low|gone}: returns an undo token."""
    require_native()
    pid = _int_id(b.get("id"), "item")
    ans = b.get("answer")
    if ans not in ("have", "low", "gone"):
        raise ApiError(400, "Answer have, low or gone.")
    with db() as c:
        r = pantry_row(c, pid)
        if not r or r["status"] != "active":
            raise ApiError(404, "Item not found")
        snap = {k: r[k] for k in CHECKIN_SNAP}
        learned = _learn(c, r, ans)
        if ans == "gone":
            apply_pantry_action(c, pid, {"action": "use", "left": 0})
        elif ans == "low" and (r["amount_left"] or 1) > 0.25:
            apply_pantry_action(c, pid, {"action": "use", "left": 0.25})
        event(c, pid, "checkin", ans)
        out = pantry_json(c, pantry_row(c, pid))
    return {"ok": True, "item": out, "undo": {"id": pid, "before": snap, "learned": learned}}


def checkin_undo(b):
    """POST /api/checkin/undo {undo}: put the item (and what was learned) back exactly."""
    require_native()
    u = b.get("undo") if isinstance(b.get("undo"), dict) else {}
    pid = _int_id(u.get("id"), "item")
    before = u.get("before") if isinstance(u.get("before"), dict) else None
    if not before or set(before) - set(CHECKIN_SNAP):
        raise ApiError(400, "Nothing to undo.")
    if before.get("status") not in ("active", "used", "tossed"):
        raise ApiError(400, "Nothing to undo.")
    for k in ("amount_left", "qty", "original_qty"):
        if before.get(k) is not None and not isinstance(before[k], (int, float)):
            raise ApiError(400, "Nothing to undo.")
    for k in ("finished_on", "opened_on", "expires_on", "expiry_source"):
        if before.get(k) is not None and not isinstance(before[k], str):
            raise ApiError(400, "Nothing to undo.")
    with db() as c:
        if not pantry_row(c, pid):
            raise ApiError(404, "Item not found")
        c.execute(f"UPDATE pantry_items SET {', '.join(f'{k}=?' for k in CHECKIN_SNAP)} WHERE id=?",
                  (*[before.get(k) for k in CHECKIN_SNAP], pid))
        last = c.execute("SELECT id FROM pantry_events WHERE item_id=? AND action='checkin' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
        if last:
            c.execute("DELETE FROM pantry_events WHERE id=?", (last["id"],))
        c.execute("DELETE FROM pantry_events WHERE item_id=? AND action='finished' AND at>=?", (pid, iso(today())))
        lk = u.get("learned") if isinstance(u.get("learned"), dict) else {}
        key = _s(lk.get("key"), 200) if isinstance(lk.get("key"), str) else ""
        if key:
            prev = lk.get("before")
            if isinstance(prev, list) and len(prev) == 2 and all(isinstance(x, (int, float)) or x is None for x in prev):
                c.execute("UPDATE consumption SET days=?, n=? WHERE food_key=?", (prev[0], prev[1], key))
            elif prev is None:
                c.execute("DELETE FROM consumption WHERE food_key=?", (key,))
        return {"ok": True, "item": pantry_json(c, pantry_row(c, pid))}


def checkin_finish(b):
    """POST /api/checkin/done {have: [ids]}: "All good" marks the rest as still here; the check-in is done."""
    require_native()
    ids = [_int_id(x, "item") for x in (b.get("have") or [])][:50]
    with db() as c:
        for pid in ids:
            r = pantry_row(c, pid)
            if r and r["status"] == "active":
                _learn(c, r, "have")
                event(c, pid, "checkin", "have")
    set_internal("pantry_checked_at", datetime.now().isoformat(timespec="seconds"))
    return {"ok": True, "status": pantry_checkin_status()}





# ============================================================ images (ingredients & recipes)

IMG_DIR = os.path.join(DATA_DIR, "images")
MAX_IMG = 8_000_000


# ---- outbound HTTP with SSRF protection
#
# Anything fetched on behalf of a user (recipe pages, images, Google Docs, video short links, ntfy in public mode)
# goes through _open(): only http(s), every redirect hop re-checked, and the address actually connected to is
# checked too (so a DNS answer that changes between the check and the connect can't reach an internal host).

class BlockedURL(ValueError):
    pass


def _ip_public(addr):
    try:
        ip = ipaddress.ip_address(str(addr).split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        for embedded in (ip.ipv4_mapped, ip.sixtofour, (ip.teredo or (None, None))[1]):
            if embedded is not None and not _ip_public(embedded):
                return False
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def _public_host(url):
    """True when the URL is http(s) and every address its host resolves to is a public internet address."""
    try:
        p = urllib.parse.urlparse(url)
        host, port = p.hostname or "", p.port
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not host:
        return False
    try:
        infos = socket.getaddrinfo(host, port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return False
    return bool(infos) and all(_ip_public(info[4][0]) for info in infos)


def _proxy_hosts():
    hosts = set()
    for u in urllib.request.getproxies().values():
        try:
            h = urllib.parse.urlparse(u if "://" in u else "http://" + u).hostname
        except ValueError:
            h = None
        if h:
            hosts.add(h.lower())
    return hosts


def _guarded_connection(conn):
    """Replace http.client's connect so only public addresses are dialled (pinned to the checked address)."""
    def create(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *a, **kw):
        host, port = address
        if conn._tunnel_host or str(host).lower() in _proxy_hosts():
            # Talking to a configured outbound proxy; the target was checked by URL before the request.
            return socket.create_connection(address, timeout, source_address)
        infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
        if not infos or not all(_ip_public(i[4][0]) for i in infos):
            raise BlockedURL(f"refusing to connect to a private address for {host}")
        err = None
        for family, stype, proto, _, sa in infos:
            sock = socket.socket(family, stype, proto)
            try:
                if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(timeout)
                if source_address:
                    sock.bind(source_address)
                sock.connect(sa)
                return sock
            except OSError as e:
                err = e
                sock.close()
        raise err or OSError("connection failed")
    conn._create_connection = create
    return conn


class _GuardedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _guarded_connection(self)


class _GuardedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _guarded_connection(self)


class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_GuardedHTTPConnection, req)


class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self):
        super().__init__(context=ssl.create_default_context())

    def https_open(self, req):
        return self.do_open(_GuardedHTTPSConnection, req, context=self._context)


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def __init__(self, allow_private):
        super().__init__()
        self.allow_private = allow_private

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = urllib.parse.urljoin(req.full_url, newurl)
        scheme = urllib.parse.urlparse(newurl).scheme.lower()
        if scheme not in ("http", "https") or (not self.allow_private and not _public_host(newurl)):
            raise BlockedURL("redirect to a non-public address blocked")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.remove_header("Authorization")   # never forward credentials to a redirect target
        return new


def _opener(allow_private=False):
    """An opener that only speaks http/https (no file://, ftp:// or data:) and re-checks every redirect."""
    op = urllib.request.OpenerDirector()
    for h in (urllib.request.ProxyHandler(), urllib.request.UnknownHandler(), urllib.request.HTTPDefaultErrorHandler(),
              urllib.request.HTTPErrorProcessor(), _CheckedRedirects(allow_private),
              urllib.request.HTTPHandler() if allow_private else _GuardedHTTPHandler(),
              urllib.request.HTTPSHandler(context=ssl.create_default_context()) if allow_private else _GuardedHTTPSHandler()):
        op.add_handler(h)
    return op


def _open(url, data=None, headers=None, method=None, timeout=20, allow_private=False):
    """urlopen() with scheme, redirect and private-address checks. Raises BlockedURL for refused targets."""
    if urllib.parse.urlparse(url).scheme.lower() not in ("http", "https"):
        raise BlockedURL("only http(s) links are supported")
    if not allow_private and not _public_host(url):
        raise BlockedURL("that address isn't on the public internet")
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        return _opener(allow_private).open(req, timeout=timeout)
    except urllib.error.URLError as e:
        if isinstance(e.reason, BlockedURL):
            raise e.reason
        raise


def _read_capped(resp, cap, total_timeout=120, truncate=False):
    """Read at most `cap` bytes within `total_timeout` seconds (truncate=True keeps the first `cap` bytes)."""
    deadline = time.monotonic() + total_timeout
    chunks, n = [], 0
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("download took too long")
        chunk = resp.read(min(65536, cap + 1 - n))
        if not chunk:
            break
        chunks.append(chunk)
        n += len(chunk)
        if n > cap:
            if truncate:
                return b"".join(chunks)[:cap]
            raise ValueError("response too large")
    return b"".join(chunks)


def _fetch_image(url):
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://"):
        url = "https://" + url[7:]
    if not url.startswith("https://") or not _public_host(url):
        raise ValueError("refusing non-public or non-https image URL")
    with _open(url, headers={"User-Agent": f"TablePlan/{APP_VERSION} (+https://github.com/thomasjvalenzuela/tableplan)"},
               timeout=20) as r:
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].lower()
        data = _read_capped(r, MAX_IMG, 60)
    kind = n_recipes.sniff_image(data[:64])
    if not kind:   # only real JPEG/PNG/WebP/GIF bytes are stored (no SVG or HTML posing as an image)
        raise ValueError("not an image")
    ctype = "image/" + ("jpeg" if kind == "jpg" else kind)
    return data, ctype


def _ext(ctype):
    return {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(ctype, "jpg")


def openverse_candidates(q, n=20):
    res = _https_json("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": q, "page_size": n, "mature": "false", "category": "photograph"}), timeout=15)
    out = []
    for x in res.get("results") or []:
        url = x.get("url") or x.get("thumbnail")
        if url:
            lic = " ".join(x for x in ((x.get('license') or '').upper(), str(x.get('license_version') or '')) if x)
            credit = f"“{x.get('title') or 'Photo'}” by {x.get('creator') or 'unknown'}" + (f" ({'CC ' if lic and not lic.startswith(('CC', 'PDM')) else ''}{lic})" if lic else "")
            out.append((url, credit))
    return out


def ingredient_candidates(name):
    words = [w for w in re.findall(r"[A-Za-z]+", name)]
    variants = []
    for v in (" ".join(words), " ".join(singular(w.lower()) for w in words), words[-1] if words else "", singular(words[-1].lower()) if words else ""):
        v = v.strip().title()
        if v and v not in variants:
            variants.append(v)
    cands = [(f"https://www.themealdb.com/images/ingredients/{_q(v)}-Small.png", "TheMealDB") for v in variants]
    return cands


def _pick_row(kind, key):
    with db() as c:
        return c.execute("SELECT * FROM image_picks WHERE kind=? AND key=?", (kind, key)).fetchone()


def _save_pick(kind, key, idx, blob=None, ctype="image/jpeg", credit="", missing=0):
    os.makedirs(IMG_DIR, exist_ok=True)
    fname = None
    if blob:
        fname = f"{kind}-{hashlib.sha1(key.encode()).hexdigest()[:16]}.{_ext(ctype)}"
        for old in os.listdir(IMG_DIR):
            if old.startswith(fname.rsplit(".", 1)[0] + "."):
                os.remove(os.path.join(IMG_DIR, old))
        with open(os.path.join(IMG_DIR, fname), "wb") as f:
            f.write(blob)
    with db() as c:
        c.execute("INSERT INTO image_picks(kind, key, idx, file, credit, missing, updated) VALUES (?,?,?,?,?,?,?) "
                  "ON CONFLICT(kind, key) DO UPDATE SET idx=excluded.idx, file=excluded.file, credit=excluded.credit, "
                  "missing=excluded.missing, updated=excluded.updated",
                  (kind, key, idx, fname, credit, missing, datetime.now().isoformat(timespec="seconds")))
    return fname


def ingredient_image(name, advance=False):
    """Return (path, credit) for an ingredient photo, fetching and caching it on first use."""
    key = food_key(name) or name.lower().strip()
    row = _pick_row("ing", key)
    if row and not advance:
        if row["file"] and os.path.exists(os.path.join(IMG_DIR, row["file"])):
            return os.path.join(IMG_DIR, row["file"]), row["credit"]
        if row["missing"]:
            return None, None
    start = (row["idx"] + 1) if (row and advance) else 0
    cands = ingredient_candidates(name)
    if advance or start >= len(cands):
        try:
            cands += openverse_candidates(f"{name} food ingredient", 12)
        except ApiError:
            pass
    for idx in range(start, len(cands)):
        url, credit = cands[idx]
        try:
            blob, ctype = _fetch_image(url)
        except Exception:
            continue
        f = _save_pick("ing", key, idx, blob, ctype, credit)
        return os.path.join(IMG_DIR, f), credit
    if advance:
        raise ApiError(404, "No more photos found for this ingredient. Upload your own instead.")
    _save_pick("ing", key, 0, missing=1)
    return None, None


def recipe_image_next(slug):
    rec = mealie("GET", f"/api/recipes/{_q(slug)}")
    row = _pick_row("recipe", rec["id"])
    if not row and rec.get("orgURL"):   # first try: the photo from the recipe's own web page
        try:
            final, page = _fetch_page(rec["orgURL"])
            img = n_scraper.page_image(page, final)
            try:
                img = n_scraper.parse_html(page, final).get("image_url") or img
            except n_scraper.NoRecipe:
                pass
            if img:
                blob, ctype = _fetch_image(img)
                _upload_recipe_image(slug, blob, ctype)
                _save_pick("recipe", rec["id"], -1, None, ctype, urllib.parse.urlparse(rec["orgURL"]).hostname)
                return {"ok": True, "credit": urllib.parse.urlparse(rec["orgURL"]).hostname}
        except Exception as e:
            log("original page photo unavailable:", e)
    idx = (row["idx"] + 1) if row else 0
    cands = openverse_candidates(f"{rec.get('name')} dish", 20)
    for i in range(idx, len(cands)):
        url, credit = cands[i]
        try:
            blob, ctype = _fetch_image(url)
        except Exception:
            continue
        _upload_recipe_image(slug, blob, ctype)
        _save_pick("recipe", rec["id"], i, None, ctype, credit)
        return {"ok": True, "credit": credit}
    _save_pick("recipe", rec["id"], -1)
    raise ApiError(404, "No more photos found. Upload your own instead, or tap Try again to start over.")


def _upload_recipe_image(slug, blob, ctype):
    mealie("PUT", f"/api/recipes/{_q(slug)}/image",
           multipart=({"extension": _ext(ctype)}, [("image", f"image.{_ext(ctype)}", ctype, blob)]), timeout=60)
    _recipe_cache["at"] = 0


def decode_upload(data_url):
    head, _, b64 = _s(data_url).partition(",")
    m = re.match(r"data:(image/[a-z+.-]+);base64$", head)
    if not m:
        raise ApiError(400, "Upload a JPG, PNG or WebP image.")
    if len(b64) > MAX_IMG * 4 // 3 + 16:
        raise ApiError(413, "That image is too large (8 MB max).")
    try:
        blob = base64.b64decode(b64, validate=False)
    except ValueError:
        raise ApiError(400, "That image couldn't be read.")
    if len(blob) > MAX_IMG:
        raise ApiError(413, "That image is too large (8 MB max).")
    kind = n_recipes.sniff_image(blob[:64])   # the bytes decide the type (no SVG/HTML stored as an "image")
    if not kind:
        raise ApiError(400, "Upload a JPG, PNG, WebP or GIF image.")
    return blob, "image/" + ("jpeg" if kind == "jpg" else kind)


# ============================================================ pan sizes (found in the recipe, asked when scaling)

def _pan_texts(rec):
    return ([_ing_line(g) for g in rec.get("recipeIngredient") or [] if isinstance(g, dict)] +
            [(x.get("text") or "") for x in rec.get("recipeInstructions") or [] if isinstance(x, dict)] +
            [rec.get("description") or ""] + [str(n.get("text") or "") for n in rec.get("notes") or [] if isinstance(n, dict)])


def _with_pan(rec):
    """Store the pan found in the recipe's text (parsed) in extras.pan_detected; a pan the cook set stays in extras.pan."""
    ex = dict(rec.get("extras") or {}) if isinstance(rec.get("extras"), dict) else {}
    found = n_pans.detect(_pan_texts(rec))
    if found:
        ex["pan_detected"] = found
    else:
        ex.pop("pan_detected", None)
    return {**rec, "extras": ex}


def recipe_pan(rec):
    """{pan, source: set|recipe|None, pref, needs}: the pan for this recipe and the cook's scaling choice."""
    ex = rec.get("extras") if isinstance(rec.get("extras"), dict) else {}
    pan = n_pans.clean(ex.get("pan")) if ex.get("pan") else None
    src = "set" if pan else None
    if not pan:
        pan = n_pans.clean(ex.get("pan_detected")) if ex.get("pan_detected") else None
        if pan is None:
            pan = n_pans.detect(_pan_texts(rec))   # older recipes saved before pans were stored
        src = "recipe" if pan else None
    pref = ex.get("pan_pref") if isinstance(ex.get("pan_pref"), dict) else None
    return {"pan": pan, "source": src, "pref": pref, "needs": pan is None and n_pans.needs_pan(_pan_texts(rec))}


def owned_pans():
    return [p for p in (n_pans.clean(x) for x in get_settings().get("pans") or []) if p]


def recipe_pan_api(slug, m, q, b):
    """GET /api/recipe/{slug}/pan?factor=1.5: the pan and what scaling does to it.
    POST {pan?: {...}|null, pref?: keep|different|any, pref_pan?: {...}}: set the pan or remember the scaling choice."""
    require_native()
    with db() as c:
        rec = n_recipes.get(c, slug)
        if not rec:
            raise ApiError(404, "Recipe not found")
        if m == "POST":
            ex = dict(rec.get("extras") or {}) if isinstance(rec.get("extras"), dict) else {}
            if "pan" in b:
                if b["pan"] is None:
                    ex.pop("pan", None)
                else:
                    pan = n_pans.clean(b["pan"]) if isinstance(b["pan"], dict) else n_pans.parse(_s(b["pan"], 60))
                    if not pan:
                        raise ApiError(400, "That pan size couldn't be read. Try “9x13” or “9 inch round”.")
                    ex["pan"] = pan
            if "pref" in b:
                if b["pref"] not in ("keep", "different", "any", None):
                    raise ApiError(400, "Choose keep, different or any.")
                if b["pref"] is None:
                    ex.pop("pan_pref", None)
                else:
                    pp = n_pans.clean(b.get("pref_pan")) if b["pref"] == "different" else None
                    if b["pref"] == "different" and not pp:
                        raise ApiError(400, "Which pan will you use?")
                    ex["pan_pref"] = {"choice": b["pref"], **({"pan": pp} if pp else {})}
            n_recipes.update(c, rec["slug"], {**rec, "extras": ex})
            rec = n_recipes.get(c, slug)
    out = recipe_pan(rec)
    factor = _num(q.get("factor")) if q else None
    out["advice"] = n_pans.advice(out["pan"], factor, owned_pans()) if out["pan"] and factor else None
    if out["pref"] and out["pref"].get("choice") == "different" and out["pan"] and factor:
        alt = out["pref"]["pan"]
        out["advice_alt"] = {"label": alt["label"], "depth": round(n_pans.area(out["pan"]) * factor / max(1e-6, n_pans.area(alt)), 2)} \
            if n_pans.family(alt) == n_pans.family(out["pan"]) else None
    out["owned"] = owned_pans()
    out["common"] = n_pans.COMMON
    return out


# ============================================================ recipe photos: crop sizes, sources, AI images

PHOTO_MAX = 2048          # master: longest side
PHOTO_CARD, PHOTO_THUMB = 800, 320
IMAGE_MODEL = "gpt-image-1"
_cand_cache = {}          # recipe id -> (time, [candidate dicts])
_cand_blob = {}           # (recipe id, i) -> (time, blob, ctype)


def _recipe_dir(rid):
    return os.path.dirname(n_recipes.image_path(IMG_DIR, rid) or os.path.join(n_recipes._image_dir(IMG_DIR, rid), "x"))


def _recipe_extras(c, rec, **kv):
    """Set extras on a recipe without touching anything else."""
    ex = rec.get("extras") if isinstance(rec.get("extras"), dict) else {}
    ex = {**ex, **kv}
    for k in [k for k, v in ex.items() if v is None]:
        ex.pop(k)
    n_recipes.update(c, rec["slug"], {**rec, "extras": ex})


def _photo_blob(data_url, label):
    blob, ctype = decode_upload(data_url)
    dims = n_imgmeta.size(blob)
    if not dims:
        raise ApiError(400, f"The {label} image couldn't be read.")
    return n_imgmeta.strip_metadata(blob), ctype, dims


def save_recipe_photo(slug, b):
    """POST /api/recipe/{slug}/image/upload {data, card?, thumb?, credit?, ai?, keep?}: the cropped photo in its sizes
    (master ≤2048 px, card 800, thumb 320, made in the browser). Metadata is stripped from every file. keep=true saves
    the current photo first (when trying an AI image) so it can come back."""
    require_native()
    master, ctype, dims = _photo_blob(b.get("data"), "photo")
    if max(dims) > PHOTO_MAX * 2:
        raise ApiError(400, f"That photo is too big ({dims[0]}×{dims[1]}). Crop it first.")
    sizes = {}
    for key, cap_px in (("card", PHOTO_CARD), ("thumb", PHOTO_THUMB)):
        if b.get(key):
            blob, ct, d = _photo_blob(b[key], key)
            if max(d) > cap_px * 1.5:
                raise ApiError(400, f"The {key} image is larger than expected.")
            sizes[key] = (blob, ct)
    with db() as c:
        rec = n_recipes.get(c, slug)
        if not rec:
            raise ApiError(404, "Recipe not found")
        d = n_recipes._image_dir(IMG_DIR, rec["id"])
        os.makedirs(d, exist_ok=True)
        cur = n_recipes.image_path(IMG_DIR, rec["id"])
        ex = rec.get("extras") if isinstance(rec.get("extras"), dict) else {}
        if b.get("keep") and cur and not ex.get("photo_ai"):
            for old in os.listdir(d):
                if old.startswith("keep."):
                    os.remove(os.path.join(d, old))
            shutil.copyfile(cur, os.path.join(d, "keep." + cur.rsplit(".", 1)[1]))
            kept_credit = ex.get("photo_credit") or ""
        else:
            kept_credit = ex.get("photo_kept_credit")
        try:
            token = n_recipes.save_image(IMG_DIR, rec["id"], master, _ext(ctype), c=c)
        except ValueError as e:
            raise ApiError(400, str(e))
        for key in ("card", "thumb"):
            for old in os.listdir(d):
                if old.startswith(key + "."):
                    os.remove(os.path.join(d, old))
            if key in sizes:
                with open(os.path.join(d, f"{key}.{_ext(sizes[key][1])}"), "wb") as f:
                    f.write(sizes[key][0])
        for old in os.listdir(d):   # an AI suggestion is used (or passed over) once a photo is saved
            if old.startswith("ai-pending."):
                os.remove(os.path.join(d, old))
        if b.get("ai") is not True and not b.get("keep"):
            for old in os.listdir(d):
                if old.startswith("keep."):
                    os.remove(os.path.join(d, old))
            kept_credit = None
        rec = n_recipes.get(c, slug)
        _recipe_extras(c, rec, photo_credit=_s(b.get("credit"), 300).strip() or ("AI image" if b.get("ai") is True else "Your photo"),
                       photo_ai=True if b.get("ai") is True else None, photo_kept_credit=kept_credit)
    _recipe_cache["at"] = 0
    return {"ok": True, "image": token}


def recipe_photo_restore(slug):
    """POST /api/recipe/{slug}/image/restore: back to the photo kept before an AI image."""
    require_native()
    with db() as c:
        rec = n_recipes.get(c, slug)
        if not rec:
            raise ApiError(404, "Recipe not found")
        d = n_recipes._image_dir(IMG_DIR, rec["id"])
        kept = next((os.path.join(d, f) for f in (os.listdir(d) if os.path.isdir(d) else []) if f.startswith("keep.")), None)
        if not kept:
            raise ApiError(404, "There's no earlier photo to go back to.")
        with open(kept, "rb") as f:
            blob = f.read()
        n_recipes.save_image(IMG_DIR, rec["id"], blob, kept.rsplit(".", 1)[1], c=c)
        os.remove(kept)
        for old in os.listdir(d):
            if old.startswith(("card.", "thumb.", "ai-pending.")):
                os.remove(os.path.join(d, old))
        ex = rec.get("extras") or {}
        rec = n_recipes.get(c, slug)
        _recipe_extras(c, rec, photo_ai=None, photo_credit=ex.get("photo_kept_credit") or "Your photo", photo_kept_credit=None)
    _recipe_cache["at"] = 0
    return {"ok": True}


def recipe_photo_info(rec):
    ex = rec.get("extras") if isinstance(rec.get("extras"), dict) else {}
    d = n_recipes._image_dir(IMG_DIR, rec["id"]) if NATIVE else ""
    kept = NATIVE and os.path.isdir(d) and any(f.startswith("keep.") for f in os.listdir(d))
    return {"credit": ex.get("photo_credit") or "", "ai": bool(ex.get("photo_ai")), "kept": bool(kept)}


def _strip_html(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(s or ""))).split())


def wikimedia_candidates(q, n=8):
    res = _https_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {q}", "gsrnamespace": 6, "gsrlimit": n,
         "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1600, "format": "json", "origin": "*"}), timeout=15)
    out = []
    for p in sorted(((res.get("query") or {}).get("pages") or {}).values(), key=lambda x: x.get("index", 0)):
        ii = (p.get("imageinfo") or [{}])[0]
        url = ii.get("thumburl") or ii.get("url")
        meta = ii.get("extmetadata") or {}
        if url:
            title = re.sub(r"^File:|\.\w+$", "", p.get("title") or "Photo")
            artist = _strip_html((meta.get("Artist") or {}).get("value")) or "unknown"
            lic = _strip_html((meta.get("LicenseShortName") or {}).get("value"))
            out.append({"url": url, "credit": f"“{title}” by {artist}{f' ({lic})' if lic else ''}, Wikimedia Commons", "source": "Wikimedia Commons"})
    return out


def unsplash_candidates(q, n=6):
    key = cfg("unsplash_key")
    if not key:
        return []
    res = _https_json("https://api.unsplash.com/search/photos?" + urllib.parse.urlencode({"query": q, "per_page": n}),
                      headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"}, timeout=15)
    return [{"url": (x.get("urls") or {}).get("regular"), "credit": f"Photo by {(x.get('user') or {}).get('name') or 'unknown'} on Unsplash",
             "source": "Unsplash"} for x in res.get("results") or [] if (x.get("urls") or {}).get("regular")]


def pexels_candidates(q, n=6):
    key = cfg("pexels_key")
    if not key:
        return []
    res = _https_json("https://api.pexels.com/v1/search?" + urllib.parse.urlencode({"query": q, "per_page": n}),
                      headers={"Authorization": key}, timeout=15)
    return [{"url": (x.get("src") or {}).get("large"), "credit": f"Photo by {x.get('photographer') or 'unknown'} on Pexels",
             "source": "Pexels"} for x in res.get("photos") or [] if (x.get("src") or {}).get("large")]


def recipe_photo_candidates(slug, more=False):
    """GET /api/recipe/{slug}/image/candidates: up to 6 photos to choose from. The recipe's own page photo comes first,
    then openly licensed photos (Openverse, Wikimedia Commons), then Unsplash and Pexels when keys are set.
    Nothing is assigned here: the cook picks and crops."""
    require_native()
    with db() as c:
        rec = n_recipes.get(c, slug)
    if not rec:
        raise ApiError(404, "Recipe not found")
    hit = _cand_cache.get(rec["id"])
    if hit and time.time() - hit[0] < 1800 and not more:
        cands = hit[1]
    else:
        cands = []
        if rec.get("orgURL"):
            try:
                final, page = _fetch_page(rec["orgURL"])
                img = n_scraper.page_image(page, final)
                try:
                    img = n_scraper.parse_html(page, final).get("image_url") or img
                except n_scraper.NoRecipe:
                    pass
                if img:
                    cands.append({"url": img, "credit": urllib.parse.urlparse(rec["orgURL"]).hostname or "Recipe page", "source": "Recipe page"})
            except Exception as e:
                log("recipe page photo unavailable:", e)
        q = f"{rec.get('name')} food"
        for fn in (unsplash_candidates, pexels_candidates, lambda x: openverse_candidates(x.replace(" food", " dish"), 10), wikimedia_candidates):
            try:
                got = fn(q)
            except Exception as e:
                log("photo source failed:", e)
                continue
            for g in got:
                if isinstance(g, tuple):
                    g = {"url": g[0], "credit": g[1], "source": "Openverse"}
                cands.append(g)
        seen, uniq = set(), []
        for x in cands:
            if x["url"] and x["url"] not in seen:
                seen.add(x["url"])
                uniq.append(x)
        # round-robin by source so six picks aren't all from one place (the recipe's own page stays first)
        first = [x for x in uniq if x["source"] == "Recipe page"]
        by = {}
        for x in uniq:
            if x["source"] != "Recipe page":
                by.setdefault(x["source"], []).append(x)
        mixed = []
        while any(by.values()):
            for k in list(by):
                if by[k]:
                    mixed.append(by[k].pop(0))
        start = (hit[2] if hit and more and len(hit) > 2 else 0)
        cands = first + mixed
        if more:
            cands = cands[start + 6:] + cands[:start + 6]
        _cand_cache[rec["id"]] = (time.time(), cands, start + 6 if more else 0)
    return {"candidates": [{"i": i, "credit": x["credit"], "source": x["source"], "src": f"/api/recipe/{_q(slug)}/image/candidate/{i}"}
                           for i, x in enumerate(cands[:6])]}


def recipe_photo_candidate(slug, i):
    """The candidate photo itself, fetched through TablePlan (so the browser can crop it)."""
    require_native()
    with db() as c:
        rec = n_recipes.get(c, slug)
    hit = _cand_cache.get(rec["id"]) if rec else None
    if not hit or not 0 <= i < min(6, len(hit[1])):
        raise ApiError(404, "That photo isn't available any more.")
    key = (rec["id"], i)
    got = _cand_blob.get(key)
    if got and time.time() - got[0] < 1800 and got[3] == hit[1][i]["url"]:
        return got[1], got[2]
    try:
        blob, ctype = _fetch_image(hit[1][i]["url"])
    except Exception:
        raise ApiError(404, "That photo couldn't be loaded.")
    if len(_cand_blob) > 60:
        _cand_blob.clear()
    _cand_blob[key] = (time.time(), blob, ctype, hit[1][i]["url"])
    return blob, ctype


def _multipart(fields, files):
    boundary = "tp" + secrets.token_hex(12)
    body = bytearray()
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    for name, fname, ctype, blob in files:
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{fname}\"\r\nContent-Type: {ctype}\r\n\r\n".encode()
        body += blob + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def recipe_photo_ai(slug, b):
    """POST /api/recipe/{slug}/image/ai {mode: new|enhance}: an AI photo to compare side by side. It's only a
    suggestion until the cook chooses it (the current photo is kept). Respects the monthly AI budget."""
    require_native()
    key = cfg("openai_key")
    if not key:
        raise ApiError(400, "AI photos need your OpenAI key (Settings → AI recipe import).")
    if _ai_over_budget():
        raise ApiError(402, "This month's AI budget is used up. Raise it in Settings → AI spending.")
    mode = "enhance" if b.get("mode") == "enhance" else "new"
    with db() as c:
        rec = n_recipes.get(c, slug)
    if not rec:
        raise ApiError(404, "Recipe not found")
    cur = n_recipes.image_path(IMG_DIR, rec["id"])
    model = cfg("openai_image_model") or IMAGE_MODEL
    if mode == "enhance":
        if not cur:
            raise ApiError(400, "Add a photo first, then enhance it.")
        with open(cur, "rb") as f:
            blob = f.read()
        prompt = ("Improve this home-cooked food photo: better light and exposure, natural colour, crisp focus, a tidier "
                  "background. Keep exactly the same dish, plate, portion and composition. Add nothing, no text.")
        data, ctype = _multipart({"model": model, "prompt": prompt, "size": "1536x1024", "quality": "medium", "n": "1"},
                                 [("image", "photo." + cur.rsplit(".", 1)[1], mimetypes.guess_type(cur)[0] or "image/jpeg", blob)])
        res = _https_json("https://api.openai.com/v1/images/edits", data=data, ctype=ctype,
                          headers={"Authorization": f"Bearer {key}"}, timeout=240, method="POST")
    else:
        ings = ", ".join(x for x in (ing_food(i) for i in (rec.get("recipeIngredient") or [])[:8]) if x)
        prompt = (f"A realistic, appetizing photo of home-cooked {rec.get('name')} ({ings}), served and ready to eat, "
                  "natural window light, on a simple table, shot from a 45-degree angle. No text, no people, no hands.")
        res = _https_json("https://api.openai.com/v1/images/generations", payload={"model": model, "prompt": prompt,
                          "size": "1536x1024", "quality": "medium", "n": 1}, headers={"Authorization": f"Bearer {key}"}, timeout=240)
    u = res.get("usage") or {}
    log_ai("recipe photo", model, u.get("input_tokens"), u.get("output_tokens"), f"{mode}: {rec.get('name')}"[:80])
    b64 = ((res.get("data") or [{}])[0]).get("b64_json")
    if not b64:
        raise ApiError(502, "The AI didn't return a photo. Try again.")
    out = base64.b64decode(b64)
    if not n_recipes.sniff_image(out[:64]):
        raise ApiError(502, "The AI's photo couldn't be read.")
    d = n_recipes._image_dir(IMG_DIR, rec["id"])
    os.makedirs(d, exist_ok=True)
    for old in os.listdir(d):
        if old.startswith("ai-pending."):
            os.remove(os.path.join(d, old))
    kind = n_recipes.sniff_image(out[:64])
    with open(os.path.join(d, f"ai-pending.{kind}"), "wb") as f:
        f.write(n_imgmeta.strip_metadata(out))
    return {"ok": True, "src": f"/api/recipe/{_q(slug)}/image/ai-pending?t={int(time.time())}", "mode": mode}


def recipe_photo_pending(slug):
    with db() as c:
        rec = n_recipes.get(c, slug)
    d = n_recipes._image_dir(IMG_DIR, rec["id"]) if rec else None
    f = next((os.path.join(d, x) for x in (os.listdir(d) if d and os.path.isdir(d) else []) if x.startswith("ai-pending.")), None)
    if not f:
        raise ApiError(404, "No AI photo waiting.")
    with open(f, "rb") as fh:
        return fh.read(), mimetypes.guess_type(f)[0] or "image/png"


def photos_config(b):
    """PUT /api/photos/config {unsplash_key?, pexels_key?}"""
    require_native()
    up = {k: _s(b.get(k), 200).strip() for k in ("unsplash_key", "pexels_key") if k in b}
    if up:
        set_cfg(**up)
    _cand_cache.clear()
    return {"unsplash": bool(cfg("unsplash_key")), "pexels": bool(cfg("pexels_key")), "ai": bool(cfg("openai_key"))}


# ============================================================ recipe ideas from the kitchen: real recipes only
# (TheMealDB, Spoonacular, the Wikibooks Cookbook, and web pages found by AI search). Nothing here writes a recipe.
# Third-party calls go only to fixed hosts through the SSRF-safe fetcher, with timeouts and size caps; keys stay on the
# server; everything that comes back is treated as untrusted text (see native/ideas.py).

IDEA_HOSTS = {"www.themealdb.com", "api.spoonacular.com", "api.openai.com", "en.wikibooks.org"}
IDEA_IMG_HOSTS = {"www.themealdb.com", "img.spoonacular.com", "spoonacular.com"}
IDEAS_AI_LIMIT = (10, 3600)       # AI web searches for recipes per member (or device) per hour
SPOON_DAILY_CALLS = 40            # stay well inside Spoonacular's free daily points
_ideas_rate = {}
_idea_img = {}


def _idea_api(url, timeout=20, max_bytes=2_000_000, **kw):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "") not in IDEA_HOSTS:
        raise ApiError(400, "That service isn't allowed.")
    return _https_json(url, timeout=timeout, max_bytes=max_bytes, **kw)


def _cached(key, days, fn):
    """A JSON answer from cache when younger than `days`, else fetched and stored."""
    with db() as c:
        r = c.execute("SELECT at, data FROM ext_cache WHERE key=?", (key,)).fetchone()
    if r and (datetime.now() - datetime.fromisoformat(r["at"])).total_seconds() < days * 86400:
        return json.loads(r["data"])
    data = fn()
    with db() as c:
        c.execute("INSERT INTO ext_cache(key, at, data) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET at=excluded.at, data=excluded.data",
                  (key, datetime.now().isoformat(timespec="seconds"), json.dumps(data)))
    return data


def _ideas_rate_ok(who):
    limit, window = IDEAS_AI_LIMIT
    now = time.time()
    with _rate_lock:
        hits = [x for x in _ideas_rate.get(who, []) if now - x < window]
        if len(hits) >= limit:
            _ideas_rate[who] = hits
            return False
        _ideas_rate[who] = hits + [now]
        return True


def _mealdb(path, params):
    key = cfg("mealdb_key") or "1"
    url = f"https://www.themealdb.com/api/json/v1/{_q(key)}/{path}?" + urllib.parse.urlencode(params)
    return _cached(f"mealdb:{path}?{urllib.parse.urlencode(sorted(params.items()))}", 7, lambda: _idea_api(url))


def mealdb_ideas(foods, limit=10):
    """Real recipes from TheMealDB that use the kitchen's foods (ingredient filter, then full lookups)."""
    ids = []
    for food in foods:
        for variant in dict.fromkeys([food, singular(food), food.split()[-1]]):
            meals = (_mealdb("filter.php", {"i": variant.lower().replace(" ", "_")}).get("meals") or [])
            if isinstance(meals, list) and meals:
                ids += [m.get("idMeal") for m in meals[:6] if isinstance(m, dict) and str(m.get("idMeal") or "").isdigit()]
                break
    out = []
    for mid in list(dict.fromkeys(ids))[:limit]:
        meals = _mealdb("lookup.php", {"i": mid}).get("meals") or []
        idea = n_ideas.mealdb_idea(meals[0]) if isinstance(meals, list) and meals else None
        if idea:
            out.append(idea)
    return out


def _spoon(path, params):
    key = cfg("spoonacular_key")
    until = float(get_internal("spoon_backoff_until") or 0)
    if not key or time.time() < until:
        return None
    day = datetime.now(timezone.utc).date().isoformat()
    used = int(get_internal(f"spoon_calls_{day}") or 0)
    if used >= SPOON_DAILY_CALLS:
        return None
    set_internal(f"spoon_calls_{day}", used + 1)
    try:
        return _idea_api(f"https://api.spoonacular.com/{path}?" + urllib.parse.urlencode({**params, "apiKey": key}))
    except ApiError as e:
        code = getattr(e, "http_status", None)
        if code == 402:   # daily quota used up: wait for tomorrow (UTC)
            tomorrow = datetime.combine(datetime.now(timezone.utc).date() + timedelta(days=1), datetime.min.time(), timezone.utc)
            set_internal("spoon_backoff_until", tomorrow.timestamp())
        elif code == 429:
            set_internal("spoon_backoff_until", time.time() + 3600)
        log("Spoonacular:", e.message)
        return None


def spoon_ideas(foods, limit=6):
    """Spoonacular's findByIngredients (fewest missing first), then the full recipes in one bulk call."""
    if not cfg("spoonacular_key") or not foods:
        return []
    params = {"ingredients": ",".join(foods), "number": limit, "ranking": 2, "ignorePantry": "true"}
    ck = "spoon:find:" + ",".join(sorted(f.lower() for f in foods))
    with db() as c:
        r = c.execute("SELECT at, data FROM ext_cache WHERE key=?", (ck,)).fetchone()
    found = json.loads(r["data"]) if r and (datetime.now() - datetime.fromisoformat(r["at"])).total_seconds() < 86400 else None
    if found is None:
        got = _spoon("recipes/findByIngredients", params)
        if got is None:
            return []
        found = got.get("data") if isinstance(got.get("data"), list) else []
        with db() as c:
            c.execute("INSERT INTO ext_cache(key, at, data) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET at=excluded.at, data=excluded.data",
                      (ck, datetime.now().isoformat(timespec="seconds"), json.dumps(found)))
    ids = [x["id"] for x in found if isinstance(x, dict) and isinstance(x.get("id"), int)][:limit]
    infos, todo = {}, []
    with db() as c:
        for i in ids:
            r = c.execute("SELECT at, data FROM ext_cache WHERE key=?", (f"spoon:info:{i}",)).fetchone()
            if r and (datetime.now() - datetime.fromisoformat(r["at"])).total_seconds() < 7 * 86400:
                infos[i] = json.loads(r["data"])
            else:
                todo.append(i)
    if todo:
        got = _spoon("recipes/informationBulk", {"ids": ",".join(map(str, todo))})
        rows = (got or {}).get("data") if isinstance((got or {}).get("data"), list) else []
        with db() as c:
            for x in rows:
                if isinstance(x, dict) and isinstance(x.get("id"), int):
                    infos[x["id"]] = x
                    c.execute("INSERT INTO ext_cache(key, at, data) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET at=excluded.at, data=excluded.data",
                              (f"spoon:info:{x['id']}", datetime.now().isoformat(timespec="seconds"), json.dumps(x)))
    return [x for x in (n_ideas.spoon_idea(infos[i]) for i in ids if i in infos) if x]


def _idea_score(c, idea, stock, skeys, t, book):
    """How well an outside recipe fits the kitchen: the same coverage math as What can I make?."""
    rec = {"recipeIngredient": [{"note": ln} for ln in idea["ingredients"]], "recipeServings": idea.get("servings") or 0}
    chk = recipe_check(c, rec, stock, skeys, t)
    idea.update(missing=[m["text"] for m in chk["missing"]][:12], missing_n=len(chk["missing"]), need_n=chk["need_n"],
                have_n=max(0, chk["need_n"] - len(chk["missing"])), expiring=chk["expiring"],
                to_buy=missing_cost(c, chk["missing"], book, t) if chk["missing"] else None)
    return idea


def _dismissed(c):
    cut = iso(today() - timedelta(days=30))
    return {r[0] for r in c.execute("SELECT key FROM idea_dismissed WHERE at>=?", (cut,))}


def _idea_key(idea):
    return idea["id"]


def _store_ideas(c, ideas):
    c.execute("DELETE FROM idea_cache WHERE at<?", (iso(today() - timedelta(days=2)),))
    for i in ideas:
        c.execute("INSERT INTO idea_cache(id, data, at) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data, at=excluded.at",
                  (i["id"], json.dumps(i), iso(today())))


def _public_idea(i):
    out = {k: i.get(k) for k in ("id", "source", "label", "site", "title", "url", "minutes", "servings", "ingredients", "steps",
                                 "why", "credit", "rating", "missing", "missing_n", "need_n", "have_n", "expiring", "to_buy")}
    out["image"] = f"/api/ideas/image/{_q(i['id'])}" if i.get("image") else None
    return out


IDEA_WEB_MAX = 8                  # web pages opened and checked per search
IDEAS_FIND_TTL = 86400            # merged results per inventory snapshot are reused for a day
WIKI_UA = "TablePlan/1.0 (self-hosted household recipe app)"


def idea_denylist():
    raw = get_internal("idea_denylist")
    if raw in (None, ""):
        return list(n_ideas.DEFAULT_DENYLIST)
    try:
        v = json.loads(raw)
    except ValueError:
        return list(n_ideas.DEFAULT_DENYLIST)
    return n_ideas.clean_denylist(v)


def _wiki(params):
    url = "https://en.wikibooks.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    key = "wb:" + urllib.parse.urlencode(sorted(params.items()))
    return _cached(key, 7, lambda: _idea_api(url, headers={"User-Agent": WIKI_UA}))


def wikibooks_ideas(foods, limit=6):
    """Open-source recipes from the Wikibooks Cookbook (CC BY-SA) that use the kitchen's foods; cached for 7 days."""
    titles = []
    for food in foods[:3]:
        got = _wiki({"action": "query", "list": "search", "srsearch": f"{food} incategory:Recipes", "srnamespace": 102, "srlimit": 5})
        for hit in ((got.get("query") or {}).get("search") or []) if isinstance(got, dict) else []:
            t = hit.get("title") if isinstance(hit, dict) else None
            if isinstance(t, str) and t.startswith("Cookbook:") and t not in titles:
                titles.append(t)
    out = []
    for t in titles[:limit * 2]:
        page = _wiki({"action": "parse", "page": t, "prop": "wikitext", "redirects": 1})
        wt = ((page.get("parse") or {}).get("wikitext") or "") if isinstance(page, dict) else ""
        idea = n_ideas.wikibooks_idea((page.get("parse") or {}).get("title") or t if isinstance(page, dict) else t, wt)
        if idea:
            out.append(idea)
        if len(out) >= limit:
            break
    return out


def _verify_web(url, cited, known, deny):
    """One search result, checked on our side: cited by the search, https, not denylisted, opens through the
    SSRF-safe fetcher, and publishes schema.org Recipe data (name, ingredients, instructions). (url, recipe) or None."""
    n = _url_norm(url)
    if not re.match(r"^https://", url or "") or not n or n not in cited or n in known or n_ideas.denied(url, deny):
        return None
    try:
        final, page = _fetch_page(url)
        if not re.match(r"^https://", final or url) or n_ideas.denied(final or url, deny):
            return None
        return (final or url), n_scraper.parse_structured(page, final or url)
    except Exception:
        return None


IDEAS_FIND_PROMPT = (
    "Search the web for real, published home-cooking recipes. Search each of these angles: {angles}. "
    "The kitchen has (expiring first): {foods}. Only give recipe pages you actually found in the search (each url must "
    "be one of your sources): a single recipe per page with its ingredient list and method, no videos, no roundups or "
    "list articles, no social media. Do not write, change or summarize any recipe. title = the name as written on the page.")


def web_recipe_ideas(foods, meal, max_min, mood, known):
    """AI finds and matches, never writes: web search with 2-4 angles from the whole inventory, then every page is
    verified and read from its own structured data. Returns ideas (unscored) and how many links were checked."""
    angles = n_ideas.search_angles(foods, meal, max_min, mood)
    if not angles:
        return [], 0
    prompt = IDEAS_FIND_PROMPT.format(angles="; ".join(f"“{a}”" for a in angles),
                                      foods=", ".join(n_ideas.safe_name(f["name"], 40) for f in foods[:40]))
    data, cited = _responses_web_search(prompt, "recipe search", "; ".join(angles)[:80])
    deny = idea_denylist()
    picks = []
    for x in data.get("recipes") or []:
        u = (x.get("url") or "").strip() if isinstance(x, dict) else ""
        if u and _url_norm(u) not in {_url_norm(p) for p in picks}:
            picks.append(u)
    with ThreadPoolExecutor(max_workers=4) as ex:
        found = [r for r in ex.map(lambda u: _verify_web(u, cited, known, deny), picks[:IDEA_WEB_MAX]) if r]
    return [i for i in (n_ideas.web_idea(rec, u) for u, rec in found) if i], len(picks)


def _idea_foods_all(c, stock, t):
    """The whole usable inventory as canonical names, expiring first: [{name, expiring}] (staples left out)."""
    soon = iso(t + timedelta(days=MAKE_EXPIRING_DAYS))
    seen, out = set(), []
    rows = sorted({id(e["row"]): e["row"] for ents in stock.values() for e in ents}.values(),
                  key=lambda r: (r["expires_on"] is None, r["expires_on"] or "", -(r["amount_left"] or 0)))
    for r in rows:
        f = n_foods.get(c, r["food_id"]) if r["food_id"] is not None else None
        name = (f or {}).get("name") or clean_food(r["name"])
        k = food_key(name)
        if k and k not in seen and not is_staple(name, None, c):
            seen.add(k)
            out.append({"name": name, "expiring": bool(r["expires_on"] and r["expires_on"] <= soon)})
    return out


def _ideas_snapshot(c, params):
    rows = c.execute("SELECT id, name, amount_left, qty, expires_on, food_id FROM pantry_items WHERE status='active' "
                     "AND COALESCE(review,0)=0 ORDER BY id").fetchall()
    spoon = bool(cfg("spoonacular_key")) and time.time() >= float(get_internal("spoon_backoff_until") or 0)
    blob = json.dumps([[tuple(r) for r in rows], params, spoon, idea_denylist()], default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:20]


def find_ideas(b, who=None):
    """Find recipes for what I have: real recipes only, from TheMealDB, Spoonacular (with a key), the Wikibooks
    Cookbook, and (with an OpenAI key and web=true) recipe pages found by AI web search and verified here. One list,
    scored by each recipe's own ingredients against the inventory. Cached per inventory snapshot for a day."""
    require_native()
    t = today()
    meal = b.get("meal") if b.get("meal") in ("breakfast", "lunch", "dinner", "snack", "dessert") else None
    max_min = int(_num(b.get("max_minutes")) or 0) or None
    max_min = max_min if max_min and 0 < max_min <= 1440 else None
    mood = n_ideas.text(b.get("mood")[:1000] if isinstance(b.get("mood"), str) else "", 60)
    web = bool(b.get("web")) and bool(cfg("openai_key"))
    with db() as c:
        stock = _make_stock(c, t)
        foods = _idea_foods_all(c, stock, t)
        snap = _ideas_snapshot(c, [meal, max_min, mood, web])
        known = {_url_norm(r["data"] and json.loads(r["data"]).get("orgURL") or "") for r in c.execute("SELECT data FROM recipes")}
        hit = c.execute("SELECT at, data FROM ext_cache WHERE key=?", ("ideas:find:" + snap,)).fetchone()
    sources = {"mealdb": True, "spoonacular": bool(cfg("spoonacular_key")), "wikibooks": True, "web": web,
               "web_available": bool(cfg("openai_key"))}
    if not foods:
        return {"ideas": [], "foods": [], "sources": sources, "errors": []}
    if hit and (datetime.now() - datetime.fromisoformat(hit["at"])).total_seconds() < IDEAS_FIND_TTL:
        out = json.loads(hit["data"])
        out["cached"] = True
    else:
        if web and not _ideas_rate_ok(who or "anon"):
            raise ApiError(429, "That's a lot of searching for one hour. Try again a bit later.")
        names = [f["name"] for f in foods]
        ideas, errors, checked = [], [], 0
        for label, fn in (("TheMealDB", lambda: mealdb_ideas(names[:4])), ("Spoonacular", lambda: spoon_ideas(names[:4])),
                          ("Wikibooks", lambda: wikibooks_ideas(names[:3]))):
            try:
                ideas += fn()
            except ApiError as e:
                errors.append(f"{label}: {e.message}")
            except Exception as e:   # one source being down never hides the others
                errors.append(f"{label}: {e}")
        if web:
            try:
                found, checked = web_recipe_ideas(foods, meal, max_min, mood, known)
                ideas += found
            except ApiError as e:
                errors.append(f"Web search: {e.message}")
        seen, merged = set(), []
        for i in ideas:
            k = _url_norm(i.get("url") or "") or i["id"]
            if k in seen or k in known:
                continue
            seen.add(k)
            merged.append(i)
        with db() as c:
            skeys, book = staple_keys(c), PriceBook(c)
            merged = [_idea_score(c, i, stock, skeys, t, book) for i in merged]
            if max_min:
                merged = [i for i in merged if not i.get("minutes") or i["minutes"] <= max_min]
            merged.sort(key=n_ideas.rank_key)
            _store_ideas(c, merged)
        out = {"ideas": merged[:40], "errors": errors, "checked": checked}
        with db() as c:   # a source that failed this time shouldn't stay missing for a whole day
            if not errors:
                c.execute("INSERT INTO ext_cache(key, at, data) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET at=excluded.at, data=excluded.data",
                          ("ideas:find:" + snap, datetime.now().isoformat(timespec="seconds"), json.dumps(out)))
        out["cached"] = False
    with db() as c:
        gone = _dismissed(c)
        _store_ideas(c, [i for i in out["ideas"] if _idea_key(i) not in gone])
    return {"ideas": [_public_idea(i) for i in out["ideas"] if _idea_key(i) not in gone][:24], "foods": [f["name"] for f in foods],
            "sources": sources, "errors": out.get("errors") or [], "checked": out.get("checked") or 0, "cached": out["cached"]}


def recipe_ideas(q):
    """GET /api/ideas: the free sources only (TheMealDB, Spoonacular with a key, Wikibooks), ranked by the kitchen."""
    return find_ideas({"meal": q.get("meal"), "max_minutes": q.get("max_minutes"), "mood": q.get("mood"), "web": False})


def _idea_get(iid):
    with db() as c:
        r = c.execute("SELECT data FROM idea_cache WHERE id=?", (_s(iid, 80),)).fetchone()
    if not r:
        raise ApiError(404, "That idea has expired. Refresh the ideas and try again.")
    return json.loads(r["data"])


def idea_save(b):
    """POST /api/ideas/save {id, dup?}: save an idea as a recipe through the normal path (duplicate check, polish)."""
    require_native()
    i = _idea_get(b.get("id"))
    if i.get("source") not in ("mealdb", "spoonacular", "wikibooks", "web"):
        raise ApiError(400, "Only published recipes can be saved from ideas.")
    tag = {"mealdb": "TheMealDB", "spoonacular": "Spoonacular", "wikibooks": "Wikibooks Cookbook"}.get(i["source"]) or (i.get("site") or "Web")
    data = {"name": i["title"], "description": i.get("why") or "", "orgURL": i.get("url") or "",
            "recipeServings": float(i.get("servings") or cfg("people") or 2),
            "totalTimeSeconds": i["minutes"] * 60 if i.get("minutes") else None,
            "recipeIngredient": [{"referenceId": str(uuid.uuid4()), "title": None, "note": ln, "display": ln, "originalText": ln,
                                  "quantity": 0, "unit": None, "food": None} for ln in i["ingredients"]],
            "recipeInstructions": [{"id": str(uuid.uuid4()), "title": "", "text": s, "ingredientReferences": []} for s in i["steps"]],
            "tags": [{"name": tag}], "recipeCategory": [],
            "extras": {"idea_source": i["source"], **({"source_credit": i["credit"]} if isinstance(i.get("credit"), dict) else {})}}
    img = i.get("image") or ""
    img = img if _idea_img_ok(i, img) else None
    dup = b.get("dup") if b.get("dup") in ("check", "keep", "skip") else "check"
    slug = _save_new_recipe(data, img, dup=dup)
    with db() as c:
        rec = n_recipes.get(c, slug)
        ex = rec.get("extras") if isinstance(rec.get("extras"), dict) else {}
        if isinstance(i.get("credit"), dict) and not ex.get("source_credit"):   # keep the licence even if a polish pass rewrote extras
            _recipe_extras(c, rec, source_credit=i["credit"], idea_source=i["source"])
    return {"ok": True, "slug": slug, "name": rec["name"]}


def idea_dismiss(b):
    require_native()
    i = _idea_get(b.get("id"))
    with db() as c:
        c.execute("INSERT INTO idea_dismissed(key, at) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET at=excluded.at", (_idea_key(i), iso(today())))
    return {"ok": True}


def _idea_img_ok(i, u):
    """Photos come from the known recipe APIs' image hosts, or (for a web page) from that site's own domain."""
    if not isinstance(u, str) or not u.startswith("https://"):
        return False
    h = (urllib.parse.urlsplit(u).hostname or "").lower()
    if h in IDEA_IMG_HOSTS:
        return True
    if i.get("source") == "web":
        base = ".".join(n_ideas.host_of(i.get("url")).split(".")[-2:])
        return bool(base) and (h == base or h.endswith("." + base))
    return False


def idea_image(iid):
    """An idea's photo, fetched through TablePlan from the recipe site's own image host (never hotlinked)."""
    i = _idea_get(iid)
    u = i.get("image") or ""
    if not _idea_img_ok(i, u):
        raise ApiError(404, "No photo")
    hit = _idea_img.get(u)
    if hit:
        return hit
    try:
        blob, ctype = _fetch_image(u)
    except Exception:
        raise ApiError(404, "No photo")
    if len(_idea_img) > 80:
        _idea_img.clear()
    _idea_img[u] = (blob, ctype)
    return blob, ctype


def ideas_config(b):
    """PUT /api/ideas/config {mealdb_key?, spoonacular_key?, denylist?} (keys are stored as secrets; never sent back)."""
    require_native()
    up = {k: _s(b.get(k), 120).strip() for k in ("mealdb_key", "spoonacular_key") if k in b}
    if up:
        set_cfg(**up)
        set_internal("spoon_backoff_until", 0)
    if "denylist" in b:
        dl = n_ideas.clean_denylist(b.get("denylist") if isinstance(b.get("denylist"), list) else _s(b.get("denylist"), 8000))
        set_internal("idea_denylist", json.dumps(dl))
    return ideas_status()


def ai_created_count():
    """Recipes saved earlier from the retired AI-created ideas (they stay the user's data, badge and all)."""
    try:
        return sum(1 for r in recipe_pool() if r.get("ai_generated"))
    except Exception:
        return 0


def ideas_status():
    return {"mealdb_supporter": bool(cfg("mealdb_key") and cfg("mealdb_key") != "1"), "spoonacular": bool(cfg("spoonacular_key")),
            "web_search": bool(cfg("openai_key")), "spoon_paused": time.time() < float(get_internal("spoon_backoff_until") or 0),
            "denylist": idea_denylist(), "default_denylist": list(n_ideas.DEFAULT_DENYLIST), "ai_created": ai_created_count()}


# ---- inventory export (CSV download or clipboard)

CSV_HEADERS = ["Name", "Brand", "Place", "Storage", "Amount", "Unit", "Fill", "Use by", "Opened/Frozen date", "Barcode",
               "Category", "Price", "Added"]


def csv_safe(v):
    """Spreadsheet formula guard: text starting with = + - @ tab or CR gets a leading apostrophe."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def pantry_export_rows(q):
    """Inventory rows for export: all, one place (?loc=), chosen ids (?ids=1,2), finished items only with ?finished=1."""
    ids = [int(x) for x in re.findall(r"\d{1,12}", _s(q.get("ids"), 4000))][:2000]
    loc = _s(q.get("loc"), 40)
    finished = q.get("finished") == "1"
    t = today()
    with db() as c:
        sql, args = "SELECT * FROM pantry_items WHERE 1=1", []
        if not finished:
            sql += " AND status='active'"
        if ids:
            sql += f" AND id IN ({','.join('?' * len(ids))})"
            args += ids
        rows = c.execute(sql + " ORDER BY location, place, name COLLATE NOCASE", args).fetchall()
        book = PriceBook(c)
        paid = {r[0]: r[1] for r in c.execute("SELECT pantry_item_id, price FROM purchases WHERE pantry_item_id IS NOT NULL AND price>0")}
        out = []
        for r in rows:
            j = pantry_json(c, r)
            if loc and loc != "all" and j["location"] != loc and (j.get("place") or "") != loc:
                continue
            f = n_foods.get(c, r["food_id"]) if r["food_id"] is not None else None
            price = paid.get(r["id"])
            if price is None:
                bst = n_prices.best(book.records(_pantry_key(r), r["name"]), t)
                price = n_prices.money(bst["price"]) if bst else None
            brand = (r["product"] or "").split(" · ")[0] if r["product"] and " · " in (r["product"] or "") else ""
            out.append({"Name": r["name"], "Brand": brand, "Place": j.get("place_label") or (r["location"] or "").capitalize(), "Storage": r["location"],
                        "Amount": (int(r["qty"]) if float(r["qty"]).is_integer() else round(r["qty"], 3)) if r["qty"] is not None else "", "Unit": r["unit"] or "",
                        "Fill": f"{round((r['amount_left'] or 0) * 100)}%", "Use by": r["expires_on"] or "",
                        "Opened/Frozen date": r["frozen_on"] or r["opened_on"] or "", "Barcode": r["upc"] or "",
                        "Category": (f or {}).get("category") or aisle_for(r["name"]) or "", "Price": price if price is not None else "",
                        "Added": r["purchased_on"] or "", "_status": r["status"]})
    return out


def pantry_export_csv(q):
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(CSV_HEADERS)
    for r in pantry_export_rows(q):
        w.writerow([csv_safe(r[h]) for h in CSV_HEADERS])
    return "﻿" + buf.getvalue()


# ============================================================ meal plan → shopping list

def ensure_list(list_id=None):
    lists = get_lists()
    if list_id and any(l["id"] == list_id for l in lists):
        return list_id
    if lists:
        return lists[0]["id"]
    return mealie("POST", "/api/households/shopping/lists", {"name": "Groceries"})["id"]


def ing_food(ing):
    """Food name for a Mealie ingredient, using the local parser when Mealie hasn't parsed it."""
    fname = (ing.get("food") or {}).get("name") or ""
    if fname:
        return fname, None
    p = parse_ing_text(ing.get("note") or ing.get("display") or ing.get("originalText") or "")
    return (clean_food(p["food"]), p) if p else ("", None)


def local_line(p, scale):
    q = p["quantity"] * scale
    unit = (p["unit_plural"] if q > 1 else p["unit"]) if p["unit"] else ""
    size = f"({p['size']}) " if p.get("size") else ""
    return " ".join(x for x in (nice_qty(q), size + unit if unit else size.strip(), p["food"]) if x) + (f", {p['note']}" if p["note"] else "")


def plan_preview(start, end):
    """Ingredients a plan needs, flagged with what the pantry says, so the user can confirm what they already have."""
    entries = [e for e in get_plans(start, end) if (e.get("recipe") or {}).get("id")]
    with db() as c:
        pantry = {food_key(it["name"]): it for it in list_pantry(c)}
    foods = {}
    for e in entries:
        slug = e["recipe"].get("slug")
        if not slug:
            continue
        try:
            rec = mealie("GET", f"/api/recipes/{_q(slug)}")
        except ApiError:
            continue
        for ing in rec.get("recipeIngredient") or []:
            fname, _ = ing_food(ing)
            if not fname:
                continue
            k = food_key(fname)
            f = foods.setdefault(k, {"key": k, "name": fname, "emoji": food_emoji(fname), "recipes": [], "pantry": None, "staple": False})
            if e["recipe"].get("name") not in f["recipes"]:
                f["recipes"].append(e["recipe"].get("name"))
            p = pantry.get(k)
            if p:
                f["pantry"] = {"amount_left": p["amount_left"], "days_left": p["days_left"], "location": p["location"]}
            f["staple"] = is_staple(fname)
    items = sorted(foods.values(), key=lambda f: (not f["pantry"], not f["staple"], f["name"].lower()))
    for f in items:   # suggest "have it" when the pantry has a decent amount that won't expire first, or it's a staple
        pf = f["pantry"]
        f["have"] = bool(pf and pf["amount_left"] >= 0.25 and (pf["days_left"] is None or pf["days_left"] >= 0)) or f["staple"]
        f["ask"] = bool(pf) or f["staple"]
        f["need"] = "For " + ", ".join(x for x in f["recipes"][:3] if x)
        if pf:
            f["pantry"] = f"{pf['location'].title()} · {round(pf['amount_left'] * 100)}% left" + (
                f" · {'expired' if pf['days_left'] < 0 else 'use within ' + str(pf['days_left']) + 'd'}" if pf["days_left"] is not None and pf["days_left"] <= 3 else "")
    return {"recipes": len({e["recipe"]["id"] for e in entries}), "items": items}


def plan_to_list(start, end, list_id=None, skip_pantry=True, skip_keys=None):
    entries = [e for e in get_plans(start, end) if (e.get("recipe") or {}).get("id")]
    if not entries:
        raise ApiError(400, "No recipes planned in that range yet.")
    list_id = ensure_list(list_id)
    totals = {}
    for e in entries:
        rid = e["recipe"]["id"]
        totals.setdefault(rid, {"scale": 0.0, "slug": e["recipe"].get("slug"), "name": e["recipe"].get("name")})
        totals[rid]["scale"] += float(e.get("scale") or 1)
    have = set(skip_keys or [])
    if skip_pantry and skip_keys is None:
        with db() as c:
            for it in list_pantry(c):
                if it["amount_left"] >= 0.25 and (it["days_left"] is None or it["days_left"] >= 0):
                    have.add(food_key(it["name"]))
    payload, skipped, extra = [], [], []
    for rid, t in totals.items():
        item = {"recipeId": rid, "recipeIncrementQuantity": round(t["scale"], 2)}
        if t["slug"]:
            try:
                rec = mealie("GET", f"/api/recipes/{_q(t['slug'])}")
                ings = rec.get("recipeIngredient") or []
                keep = []
                for ing in ings:
                    fname, local = ing_food(ing)
                    if fname and food_key(fname) in have:
                        skipped.append(fname)
                    elif local:
                        extra.append(local_line(local, t["scale"]))   # plain-text line: scale it here
                    else:
                        keep.append(ing)
                if len(keep) != len(ings):
                    if not keep:
                        continue
                    item["recipeIngredients"] = keep
            except ApiError:
                pass
        payload.append(item)
    if extra:
        add_items_to_list(extra, list_id)
    if not payload:
        return {"list_id": list_id, "recipes": len(totals), "skipped": sorted(set(skipped))}
    try:
        mealie("POST", f"/api/households/shopping/lists/{list_id}/recipe", payload, timeout=60)
    except ApiError:
        # Fall back to whole recipes if Mealie rejects the filtered ingredient lists.
        mealie("POST", f"/api/households/shopping/lists/{list_id}/recipe",
               [{"recipeId": p["recipeId"], "recipeIncrementQuantity": p["recipeIncrementQuantity"]} for p in payload], timeout=60)
        skipped = []
    return {"list_id": list_id, "recipes": len(totals), "skipped": sorted(set(skipped))}


# ============================================================ planner board (assign / move / delete keep the list in sync)

PLAN_LOOKAHEAD_DAYS = 30   # a recipe planned again within this many days keeps its list items when one entry goes
SLUG_RE = re.compile(r"[A-Za-z0-9_.~%-]{1,200}")


def require_native():
    if not NATIVE:
        raise ApiError(501, "This needs TablePlan's built-in storage (TABLEPLAN_BACKEND=native).")


def _strict_date(v, field="date"):
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise ApiError(400, f"Pick a valid {field} (YYYY-MM-DD).")
    d = parse_date(v)
    if not d:
        raise ApiError(400, f"Pick a valid {field} (YYYY-MM-DD).")
    if abs((d - today()).days) > 3660:
        raise ApiError(400, "That date is too far away.")
    return d


def _entry_type_arg(v):
    t = "dinner" if v in (None, "") else v
    if t not in n_plans.ENTRY_TYPES:
        raise ApiError(400, "Unknown meal type.")
    return t


def _int_id(v, what="entry"):
    if isinstance(v, bool) or not isinstance(v, (int, str)) or not re.fullmatch(r"\d{1,15}", str(v)):
        raise ApiError(400, f"Bad {what} id.")
    return int(v)


# ============================================================ allocation-aware shopping list
# The planned part of the list is derived: for every upcoming, uncooked, unskipped meal (in date order) each ingredient
# is first covered from pantry stock nobody else has claimed (soonest-expiring first); only the shortfall goes on the
# list, keyed by plan entry. Typed-in items, ad-hoc recipe adds and checked items are never touched.

DEFAULT_STAPLES = ["salt", "kosher salt", "black pepper", "pepper", "water", "olive oil", "vegetable oil", "cooking spray",
                   "sugar", "all-purpose flour", "baking soda", "baking powder"]
STAPLES = set(DEFAULT_STAPLES)   # the defaults; the household's own list is the `staples` setting


def _pantry_have_keys():
    """Food keys the pantry covers: at least 25% left and not expired."""
    have = set()
    with db() as c:
        for it in list_pantry(c):
            if it["amount_left"] >= 0.25 and (it["days_left"] is None or it["days_left"] >= 0):
                have.add(food_key(it["name"]))
    return have


def _drop_entry_items(c, list_id, entry):
    """An entry was removed: drop its recipe's unchecked list items, unless that recipe is planned again soon."""
    rid = entry.get("recipe_id")
    if not rid:
        return 0
    t = today()
    if n_plans.recipe_planned(c, rid, iso(t), iso(t + timedelta(days=PLAN_LOOKAHEAD_DAYS)), entry.get("id")):
        return 0
    return n_lists.remove_recipe_items(c, list_id, rid)


def staple_names():
    try:
        return get_settings().get("staples") or list(DEFAULT_STAPLES)
    except Exception:
        return list(DEFAULT_STAPLES)


def staple_keys(c=None):
    """Keys for "always have" foods: canonical food ids ("f:12") plus plain word keys as a fallback."""
    names = staple_names()
    keys = {food_key(clean_food(n)) for n in names} | {food_key(n) for n in names}
    if c is not None:
        for n in names:
            fid = n_foods.lookup(c, n)
            if fid is not None:
                keys.add(f"f:{fid}")
    return keys


def is_staple(food, keys=None, c=None):
    keys = staple_keys(c) if keys is None else keys
    if not food:
        return False
    if c is not None:
        fid = n_foods.lookup(c, food)
        if fid is not None and f"f:{fid}" in keys:
            return True
    return food_key(clean_food(food)) in keys or food_key(food) in keys


def _ing_key(food, c=None, create=True):
    if c is not None:
        fid = _food_id(c, food) if create else (n_foods.lookup(c, food) if (food or "").strip() and n_foods.normalize(food) else None)
        if fid is not None:
            return f"f:{fid}"
    return food_key(clean_food(food)) or food_key(food)


def _recipe_needs(rec, scale, skeys, c=None, create=True):
    """[{key, food, qty|None, unit, amount_text, note, line}] for one planned meal (staples left out)."""
    out = []
    for ing in rec.get("recipeIngredient") or []:
        line = _ing_line(ing)
        if not line:
            continue
        p = parse_ing_text(line)
        if not p:
            key = food_key(line)
            fid = n_foods.lookup(c, line) if c is not None else None
            key = f"f:{fid}" if fid is not None else key
            if key and key not in skeys:
                out.append({"key": key, "food": None, "qty": None, "unit": "", "amount_text": "", "note": line, "line": line})
            continue
        for q in split_foods(p):
            food = q["food"].strip()
            if is_staple(food, skeys, c):
                continue
            amt = q.get("amount_text") or ""
            out.append({"key": _ing_key(food, c, create), "food": food, "qty": None if amt else float(q["quantity"]) * float(scale or 1),
                        "unit": "" if amt else n_units.normalize(q["unit"]), "amount_text": amt, "note": q.get("note") or "",
                        "line": line})
    return out


def _group_of(n):
    """Lines that add up share a group: same food and a unit dimension that converts."""
    if n["qty"] is None:
        return (n["key"], "text")
    dim = n_units.dimension(n["unit"])
    if dim in ("volume", "weight"):
        return (n["key"], dim)
    u = n_units.normalize(n["unit"])
    return (n["key"], "count:" + ("" if u in n_units.GENERIC_COUNT else u))


_NICE = {"cup": 0.25, "tbsp": 0.5, "tsp": 0.125, "lb": 0.25, "oz": 0.5, "gallon": 0.25, "quart": 0.25}


def _readable(total, unit, units_seen):
    """Show a total in the most readable unit: keep a single shared unit; mixed volumes go to cups/tbsp/tsp, mixed
    weights to lb/oz (metric stays metric)."""
    seen = {n_units.normalize(u) for u in units_seen}
    if len(seen) == 1:
        return total, unit
    dim = n_units.dimension(unit)
    metric = bool(seen & {"ml", "l", "g", "kg"}) and not (seen - {"ml", "l", "g", "kg"})
    if dim == "volume":
        cands = ["l", "ml"] if metric else ["gallon", "cup", "tbsp", "tsp"]
    elif dim == "weight":
        cands = ["kg", "g"] if metric else ["lb", "oz"]
    else:
        return total, unit
    for cu in cands:
        v = n_units.convert(total, unit, cu)
        if v is None or v < (1 if cu not in ("cup",) else 0.25):
            continue
        step = _NICE.get(cu)
        if step is None or abs(v / step - round(v / step)) < 0.02 or cu == cands[-1]:
            return v, cu
    return total, unit


def _contrib_map(row):
    try:
        d = json.loads(row["contrib"] or "{}")
    except (ValueError, TypeError):
        d = {}
    return d if isinstance(d, dict) else {}


def _entry_part(contrib):
    """The plan-entry contributions (dict values) of an item; numeric values are ad-hoc recipe adds and stay."""
    return {k: v for k, v in contrib.items() if isinstance(v, dict)}


def _row_key(r):
    fid = r["food_id"] if "food_id" in r.keys() else None
    if fid is not None:
        return f"f:{fid}"
    return _ing_key(r["food"]) if r["food"] else food_key(r["note"] or r["text"])


def _alloc_migrate(c, start, end, lid):
    """One time: list lines that older versions added per recipe become per-meal contributions (the sync rebuilds them)."""
    if c.execute("SELECT 1 FROM settings WHERE key='alloc_migrated'").fetchone():
        return
    planned = {r[0] for r in c.execute("SELECT DISTINCT recipe_id FROM meal_plans WHERE date BETWEEN ? AND ? AND recipe_id IS NOT NULL",
                                        (start, end))}
    for r in c.execute("SELECT * FROM shopping_items WHERE list_id=? AND checked=0", (lid,)).fetchall():
        cm = _contrib_map(r)
        legacy = {k: v for k, v in cm.items() if not isinstance(v, dict) and k in planned}
        rids = json.loads(r["recipe_ids"] or "[]")
        if not legacy and not (not cm and set(rids) & planned and not r["manual"]):
            continue
        rest = {k: v for k, v in cm.items() if k not in legacy}
        q = r["quantity"]
        if q is not None and legacy:
            q = q - sum(float(v or 0) for v in legacy.values())
        if not r["manual"] and not rest:
            c.execute("DELETE FROM shopping_items WHERE id=?", (r["id"],))
        else:
            c.execute("UPDATE shopping_items SET contrib=?, quantity=?, recipe_ids=? WHERE id=?",
                      (json.dumps(rest), q if (q or 0) > 0 else None, json.dumps([x for x in rids if x not in planned]), r["id"]))
    c.execute("INSERT INTO settings(key, value) VALUES ('alloc_migrated', 'true')")


def sync_plan_list(c, now=None):
    """Recompute allocations and the planned part of the shopping list. Returns {"removed": n, "entries": {...}}."""
    t = (now or today())
    start, end = iso(t), iso(t + timedelta(days=PLAN_LOOKAHEAD_DAYS))
    lid = n_lists.single_list(c)
    skeys = staple_keys(c)
    _alloc_migrate(c, start, end, lid)
    entries = [e for e in c.execute(
        "SELECT * FROM meal_plans WHERE date BETWEEN ? AND ? AND recipe_id IS NOT NULL AND cooked_at IS NULL "
        "AND skipped_at IS NULL ORDER BY date, " + n_plans._ORDER_SQL + ", id", (start, end)).fetchall()]
    eids = {str(e["id"]) for e in entries}
    # ---- pantry stock (active, not expired), soonest-expiring first
    stock, free = {}, {}
    for r in c.execute("SELECT * FROM pantry_items WHERE status='active' AND COALESCE(review,0)=0 AND (expires_on IS NULL OR expires_on>=?) "
                       "ORDER BY CASE WHEN expires_on IS NULL THEN 1 ELSE 0 END, expires_on, id", (start,)):
        if r["qty"] is not None and r["qty"] <= 0:
            continue
        keys = {f"f:{r['food_id']}"} if r["food_id"] is not None else {food_key(clean_food(r["name"])), food_key(r["name"])}
        for k in keys:
            if k:
                stock.setdefault(k, []).append(r)
        free[r["id"]] = r["qty"]
    # ---- what checked (bought / "have") items already satisfied: {(entry_id, key): (qty, unit)} + legacy recipe links
    rows = c.execute("SELECT * FROM shopping_items WHERE list_id=?", (lid,)).fetchall()
    sat, legacy = {}, set()
    linked_pantry = {}
    for r in rows:
        if not r["checked"]:
            continue
        cm = _contrib_map(r)
        for k, v in _entry_part(cm).items():
            if k in eids:
                sat[(k, _row_key(r))] = (v.get("qty"), r["unit"] or "")
                linked_pantry.setdefault((k, _row_key(r)), r["id"])
        if not _entry_part(cm):
            for rid in json.loads(r["recipe_ids"] or "[]"):
                legacy.add((str(rid), _row_key(r)))
    pantry_by_item = {}
    for r in c.execute("SELECT id, mealie_item_id FROM pantry_items WHERE mealie_item_id IS NOT NULL AND status='active'"):
        pantry_by_item[r["mealie_item_id"]] = r["id"]
    # ---- allocate, entry by entry
    c.execute("DELETE FROM allocations")
    want = {}   # group -> {"needs": [(entry, need, short_qty)], ...}
    names = {}
    for e in entries:
        rec = n_recipes.get(c, e["recipe_id"])
        if not rec:
            continue
        names[str(e["id"])] = rec.get("name") or ""
        for n in _recipe_needs(rec, e["scale"], skeys, c):
            k, eid = n["key"], str(e["id"])
            need = n["qty"]
            if (e["recipe_id"], k) in legacy:
                continue
            got = sat.get((eid, k))
            if got is not None:
                pid = pantry_by_item.get(linked_pantry.get((eid, k)))
                if pid is not None and free.get(pid) is not None and got[0]:
                    free[pid] = max(0.0, free[pid] - (n_units.convert(got[0], got[1], next(
                        (x["unit"] for x in stock.get(k, []) if x["id"] == pid), got[1])) or 0))
                if need is None or got[0] is None:
                    continue
                conv = n_units.convert(got[0], got[1], n["unit"])
                if conv is None:
                    continue
                need -= conv
                if need <= 1e-6:
                    continue
            for p in stock.get(k, []):
                if need is not None and need <= 1e-6:
                    break
                if p["qty"] is None:   # amount unknown: it covers every planned use until it's used up or tossed
                    c.execute("INSERT INTO allocations(plan_entry_id, pantry_item_id, food_key, qty, unit) VALUES (?,?,?,?,?)",
                              (e["id"], p["id"], k, None, None))
                    need = 0.0
                    break
                if need is None:       # "pinch", "to taste": any stock covers it
                    c.execute("INSERT INTO allocations(plan_entry_id, pantry_item_id, food_key, qty, unit) VALUES (?,?,?,?,?)",
                              (e["id"], p["id"], k, None, None))
                    need = 0.0
                    break
                if free[p["id"]] <= 1e-9:
                    continue
                conv = n_units.convert(need, n["unit"], p["unit"])
                if conv is None:
                    continue
                take = min(conv, free[p["id"]])
                free[p["id"]] -= take
                c.execute("INSERT INTO allocations(plan_entry_id, pantry_item_id, food_key, qty, unit) VALUES (?,?,?,?,?)",
                          (e["id"], p["id"], k, take, p["unit"]))
                need -= n_units.convert(take, p["unit"], n["unit"]) or 0
            if need is not None and need <= 1e-6:
                continue
            g = want.setdefault(_group_of(n), [])
            g.append((e, n, need))
    # ---- reconcile unchecked items
    removed, touched = 0, set()
    unchecked = [r for r in rows if not r["checked"]]
    state = {}
    for r in unchecked:
        cm = _contrib_map(r)
        ent = _entry_part(cm)
        planned = sum(float(v.get("qty") or 0) for v in ent.values())
        base = (r["quantity"] or 0) - planned if r["quantity"] is not None else None
        keep_rest = {k: v for k, v in cm.items() if not isinstance(v, dict)}
        state[r["id"]] = {"row": r, "base": base if (r["manual"] or keep_rest) else None, "rest": keep_rest, "new": {},
                          "total": None, "unit": r["unit"] or ""}
    def fits(st, grp):
        r = st["row"]
        if _row_key(r) != grp[0]:
            return False
        if grp[1] == "text":
            return r["quantity"] is None or not r["food"]
        if r["quantity"] is None or not r["food"]:
            return False
        return _group_of({"key": grp[0], "qty": 1, "unit": r["unit"] or ""}) == grp
    for grp, needs in want.items():
        st = next((x for x in state.values() if x["row"]["id"] not in touched and fits(x, grp)), None)
        first = needs[0][1]
        if grp[1] == "text":
            texts = list(dict.fromkeys(n["amount_text"] or n["note"] or "" for _, n, _ in needs if (n["amount_text"] or n["note"])))
            contrib = {str(e["id"]): {"qty": None, "unit": "", "text": n["amount_text"]} for e, n, _ in needs}
            if st:
                touched.add(st["row"]["id"]); st["new"] = contrib
                st["note"] = "; ".join(texts) if first["food"] and st["row"]["food"] and not st["row"]["manual"] else None
            else:
                iid = _new_list_item(c, lid, first["food"], "", "" if first["food"] else first["line"], grp[0])
                row = c.execute("SELECT * FROM shopping_items WHERE id=?", (iid,)).fetchone()
                state[iid] = st = {"row": row, "base": None, "rest": {}, "new": contrib, "total": None, "unit": "",
                                   "note": "; ".join(texts) if first["food"] else None, "created": True}
                touched.add(iid)
            continue
        unit = first["unit"]
        total = sum(n_units.convert(q, n["unit"], unit) or 0 for _, n, q in needs)
        if st and st["base"]:
            item_unit = st["row"]["unit"] or ""
        else:
            total, item_unit = _readable(total, unit, [n["unit"] for _, n, _ in needs])
        contrib = {}
        for e, n, q in needs:
            v = n_units.convert(q, n["unit"], item_unit) or 0
            prev = contrib.get(str(e["id"]), {}).get("qty") or 0
            contrib[str(e["id"])] = {"qty": prev + v, "unit": item_unit}
        notes = list(dict.fromkeys(n["note"] for _, n, _ in needs if n["note"]))
        if st:
            touched.add(st["row"]["id"]); st["new"] = contrib; st["unit"] = item_unit
            st["note"] = None if (st["base"] or st["row"]["manual"]) else ", ".join(notes)
        else:
            iid = _new_list_item(c, lid, first["food"], item_unit, ", ".join(notes), grp[0])
            row = c.execute("SELECT * FROM shopping_items WHERE id=?", (iid,)).fetchone()
            state[iid] = {"row": row, "base": None, "rest": {}, "new": contrib, "unit": item_unit, "note": None, "created": True}
            touched.add(iid)
    for iid, st in state.items():
        r, ent_new = st["row"], st["new"]
        if not ent_new and st["base"] is None and not r["manual"] and not st["rest"]:
            c.execute("DELETE FROM shopping_items WHERE id=?", (iid,))
            removed += 0 if st.get("created") else 1
            continue
        cm = dict(st["rest"])
        cm.update(ent_new)
        rids = sorted({str(e["recipe_id"]) for e in entries if str(e["id"]) in ent_new} |
                      {str(k) for k in st["rest"]} | (set(json.loads(r["recipe_ids"] or "[]")) if r["manual"] and not ent_new else set()))
        if r["food"] and any(v.get("qty") is not None for v in ent_new.values()):
            planned = sum(float(v.get("qty") or 0) for v in ent_new.values())
            q = (st["base"] or 0) + planned
            unit = st["unit"] or None
            c.execute("UPDATE shopping_items SET quantity=?, unit=?, unit_plural=?, contrib=?, recipe_ids=?, note=coalesce(?, note) "
                      "WHERE id=?", (q or None, unit, n_units._PLURAL.get(unit or "", unit) if unit else None, json.dumps(cm),
                                     json.dumps(rids), st.get("note"), iid))
        else:
            sets, vals = ["contrib=?", "recipe_ids=?"], [json.dumps(cm), json.dumps(rids)]
            if st.get("note") is not None:
                sets.append("note=?"); vals.append(st["note"])
            if r["food"] and not r["manual"] and not st["rest"] and ent_new:
                sets.append("quantity=?"); vals.append(None)
            elif st["base"] is not None and _entry_part(_contrib_map(r)) and not ent_new:   # meals gone: back to what was typed
                sets.append("quantity=?"); vals.append(st["base"] if st["base"] > 1e-9 else None)
            c.execute(f"UPDATE shopping_items SET {', '.join(sets)} WHERE id=?", (*vals, iid))
    return {"removed": removed, "names": names}


def _new_list_item(c, lid, food, unit, note, key=None):
    """Insert a planned line (quantity is filled in by the sync)."""
    iid = str(uuid.uuid4())
    pos = c.execute("SELECT coalesce(max(position), -1) + 1 FROM shopping_items WHERE list_id=?", (lid,)).fetchone()[0]
    text = food or note
    fid = int(key[2:]) if key and key.startswith("f:") else None
    store = (n_lists.store_for(c, n_lists.food_store_key(fid)) if fid is not None else None) or n_lists.store_for(c, food_key(text))
    c.execute("INSERT INTO shopping_items (id, list_id, text, food, quantity, unit, unit_plural, note, label, checked, position, "
              "recipe_ids, created_at, store_id, contrib, manual, food_id) VALUES (?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,0,?)",
              (iid, lid, text, food or None, None, unit or None, n_units._PLURAL.get(unit, unit) if unit else None, note or "",
               aisle_for(text) or None, pos, "[]", n_lists._now(), store, "{}", fid))
    return iid


def sync_list():
    """Run the allocation sync in its own transaction (native backend only)."""
    if not NATIVE:
        return {"removed": 0}
    with db() as c:
        return sync_plan_list(c)


def entry_missing_counts(c, lid):
    out = {}
    for r in c.execute("SELECT contrib FROM shopping_items WHERE list_id=? AND checked=0", (lid,)):
        for k, v in _entry_part(_contrib_map(r)).items():
            out[k] = out.get(k, 0) + 1
    return out


def missing_counts():
    if not NATIVE:
        return {}
    with db() as c:
        return entry_missing_counts(c, n_lists.single_list(c))


def enrich_plan(entries):
    """Add recipe minutes and the "missing N" readiness count to plan entries."""
    try:
        pool = {r["id"]: r for r in recipe_pool()}
    except ApiError:
        pool = {}
    miss = {}
    if NATIVE:
        ds = [parse_date(e.get("date")) for e in entries if parse_date(e.get("date"))]
        if ds:
            try:
                miss = planned_missing(min(ds), max(ds))
            except Exception as ex:   # readiness is a hint; never break the plan view over it
                log("missing check skipped:", ex)
    counts = {} if NATIVE else missing_counts()
    eat_times = get_settings().get("eat_times") or {}
    with db() as c:
        own = {r["entry_id"]: r["eat_at"] for r in c.execute("SELECT * FROM plan_eat_at")}
    for e in entries:
        r = e.get("recipe")
        if r:
            p = pool.get(r.get("id")) or {}
            r["minutes"] = p.get("minutes")
            r["eta"] = p.get("eta")
            r.setdefault("image_v", "")
        if NATIVE:
            m = miss.get(str(e.get("id"))) or []
            e["missing"] = len(m) if r else 0
            e["missing_items"] = [x["text"] for x in m][:8] if r else []
        else:
            e["missing"] = counts.get(str(e.get("id")), 0) if r else 0
        e["eat_at"] = own.get(str(e.get("id"))) or eat_times.get(e.get("entry_type"))
        e["eat_at_custom"] = str(e.get("id")) in own
        mins = ((r or {}).get("eta") or {}).get("shown") or (r or {}).get("minutes")
        st = start_by(e["eat_at"], mins, parse_date(e.get("date"))) if e["eat_at"] and mins and parse_date(e.get("date")) else None
        e["start_by"] = st.strftime("%H:%M") if st else None
    return entries


def plan_eat_at(entry_id, b):
    """PUT /api/plan/{id}/eat-at {eat_at: "19:00" | null}: this meal's own eat time (null: back to the usual)."""
    t = (b or {}).get("eat_at")
    with db() as c:
        if t in (None, ""):
            c.execute("DELETE FROM plan_eat_at WHERE entry_id=?", (str(entry_id),))
        else:
            if not (isinstance(t, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t)):
                raise ApiError(400, "Times look like 18:30.")
            c.execute("INSERT INTO plan_eat_at(entry_id, eat_at) VALUES (?,?) ON CONFLICT(entry_id) DO UPDATE SET eat_at=excluded.eat_at",
                      (str(entry_id), t))
    return {"ok": True}


def plan_entry(entry_id, day):
    return next((e for e in enrich_plan(get_plans(day, day)) if str(e["id"]) == str(entry_id)), None)


def plan_assign(b):
    """Put a recipe on a day (alongside what's there, or in place of replace_id). The list is re-synced: pantry stock
    nobody else has claimed covers what it can, and only the shortfall goes on the list."""
    require_native()
    d = _strict_date(b.get("date"))
    et = _entry_type_arg(b.get("entry_type"))
    key = _s(b.get("recipe_id"), 200).strip()
    if not key:
        raise ApiError(400, "Pick a recipe.")
    with db() as c:
        rec = n_recipes.get(c, key)
    if not rec:
        raise ApiError(404, "Recipe not found")
    rid = rec["id"]
    scale = household_scale(rid)
    replace_id = _int_id(b["replace_id"]) if b.get("replace_id") not in (None, "") else None
    with db() as c:
        existing = n_plans.entries_on(c, iso(d), et)
        same = next((x for x in existing if x["recipe_id"] == rid and x["id"] != replace_id), None)
        if same:   # the same recipe in the same slot already: nothing to do
            return {"entry": plan_entry(same["id"], d), "added": 0, "skipped": [], "replaced_removed": 0}
        if replace_id is not None:   # an explicit swap replaces that one entry; otherwise entries add up
            if not n_plans.get_entry(c, replace_id):
                raise ApiError(404, "Plan entry not found")
            n_plans.delete_entry(c, replace_id)
        eid = n_plans.add_entry(c, iso(d), et, rid, scale=scale)
        res = sync_plan_list(c)
        lid = n_lists.single_list(c)
        added = sum(1 for r in c.execute("SELECT contrib FROM shopping_items WHERE list_id=? AND checked=0", (lid,))
                    if str(eid) in _entry_part(_contrib_map(r)))
        skipped = sorted({r["name"] for r in c.execute(
            "SELECT p.name FROM allocations a JOIN pantry_items p ON p.id=a.pantry_item_id WHERE a.plan_entry_id=?", (eid,))},
            key=str.lower)
    return {"entry": plan_entry(eid, d), "added": added, "skipped": skipped, "replaced_removed": res["removed"]}


def plan_move(b):
    """Move an entry to another day (it joins that day's meals); with swap_with, the two entries trade days."""
    require_native()
    eid = _int_id(b.get("id"))
    d = _strict_date(b.get("date"))
    with db() as c:
        e = n_plans.get_entry(c, eid)
        if not e:
            raise ApiError(404, "Plan entry not found")
        if e["date"] == iso(d):
            return {"ok": True, "swapped_with": None}
        swapped = None
        sw = _int_id(b["swap_with"]) if b.get("swap_with") not in (None, "") else None
        if sw is not None:   # dropped onto a specific meal of the same type: the two trade days
            other = n_plans.get_entry(c, sw)
            if not other or other["date"] != iso(d) or other["entry_type"] != e["entry_type"]:
                raise ApiError(400, "Pick a meal of the same type on that day to swap with.")
            n_plans.update_entry(c, sw, date=e["date"])
            swapped = sw
        n_plans.update_entry(c, eid, date=iso(d))
        sync_plan_list(c)   # earlier meals get first claim on the pantry
    return {"ok": True, "swapped_with": swapped}


def plan_delete(eid):
    if not NATIVE:
        mealie("DELETE", f"/api/households/mealplans/{eid}")
        return {"ok": True, "removed": 0, "undo": None}
    with db() as c:
        e = n_plans.get_entry(c, eid)
        if not e:
            raise ApiError(404, "Plan entry not found")
        n_plans.delete_entry(c, eid)
        removed = sync_plan_list(c)["removed"]
    undo = {"date": e["date"], "recipe_id": e["recipe_id"], "entry_type": e["entry_type"]} if e["recipe_id"] else None
    return {"ok": True, "removed": removed, "undo": undo}


ARRANGE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["assignments"],
    "properties": {"assignments": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["date", "recipe_id"],
        "properties": {"date": {"type": "string"}, "recipe_id": {"type": "string"}}}}},
}


def _arrange_fallback(recs, dates):
    """Deterministic spread: the longest recipes go to weekends, the quickest to weekdays, in the given order."""
    weekend = [d for d in dates if d.weekday() >= 5]
    by_len = sorted(range(len(recs)), key=lambda i: (-(recs[i].get("minutes") or 0), i))
    pick_weekend = set(by_len[:len(weekend)]) if any(r.get("minutes") for r in recs) else set()
    long_q = [recs[i] for i in range(len(recs)) if i in pick_weekend]
    rest = [recs[i] for i in range(len(recs)) if i not in pick_weekend]
    out = []
    for d in dates:
        src = long_q if (d.weekday() >= 5 and long_q) else rest if rest else long_q
        out.append({"date": iso(d), "recipe_id": src.pop(0)["id"]})
    return out


def plan_arrange(b):
    """POST /api/plan/arrange {recipe_ids, start, end, entry_type?}: spread chosen recipes over the empty days.
    Uses AI for variety (falls back to a deterministic spread). Only proposes; the client applies with /plan/assign."""
    require_native()
    ids = b.get("recipe_ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 60 or not all(isinstance(x, str) and 0 < len(x) <= 200 for x in ids):
        raise ApiError(400, "Pick between 1 and 60 recipes.")
    start, end = _strict_date(b.get("start"), "start"), _strict_date(b.get("end"), "end")
    if end < start or (end - start).days > 60:
        raise ApiError(400, "Pick a range of at most 60 days.")
    et = _entry_type_arg(b.get("entry_type"))
    with db() as c:
        taken = {e["date"] for e in n_plans.get_plans(c, iso(start), iso(end), lambda rid: None) if e["entry_type"] == et}
        recs = []
        for x in dict.fromkeys(ids):
            r = n_recipes.get(c, x)
            if not r:
                raise ApiError(404, "Recipe not found")
            if r["id"] not in (y["id"] for y in recs):
                recs.append(r)
        expiring = sorted({clean_food(i["name"]) for i in expiring_items(c, 4)})
    dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    dates = [d for d in dates if iso(d) not in taken]
    if not dates:
        return {"assignments": [], "ai": False, "dropped": len(recs), "empty_days": 0}
    pool = {r["id"]: r for r in recipe_pool()}
    info = [{"id": r["id"], "name": r.get("name") or "",
             "minutes": (pool.get(r["id"]) or {}).get("eta_min") or (pool.get(r["id"]) or {}).get("minutes") or 0,
             "rating": (pool.get(r["id"]) or {}).get("rating") or 0,
             "ingredients": [_ing_line(g) for g in r.get("recipeIngredient") or []][:25]} for r in recs]
    n_empty = len(dates)
    dropped = max(0, len(info) - len(dates))
    info = info[:len(dates)]
    dates = dates[:len(info)]
    out, used_ai = None, False
    if cfg("openai_key"):
        try:
            res = openai_chat([{"role": "user", "content": (
                "Assign each recipe to exactly one of the dates (one recipe per date, use every recipe once). Aim for "
                "variety: don't put similar proteins or cuisines on back-to-back days. Put quicker recipes on weekdays "
                "and longer ones on weekends. Give the best-rated recipes (rating out of 5) the best slots, like weekends. Recipes that use these soon-to-expire pantry foods should come first: "
                + (", ".join(expiring) or "none") + ".\n\n" + json.dumps({
                    "dates": [{"date": iso(d), "weekday": d.strftime("%A")} for d in dates], "recipes": info},
                    ensure_ascii=False))}], "plan_arrange", ARRANGE_SCHEMA, "arrange", f"{len(info)} recipes")
            seen_d, seen_r, cand = set(), set(), []
            ok_dates, ok_ids = {iso(d) for d in dates}, {r["id"] for r in info}
            for a in res.get("assignments") or []:
                d, rid = a.get("date"), a.get("recipe_id")
                if d in ok_dates and rid in ok_ids and d not in seen_d and rid not in seen_r:
                    seen_d.add(d); seen_r.add(rid); cand.append({"date": d, "recipe_id": rid})
            if cand:   # anything the AI left out goes to the remaining days, in order
                left_r = [r for r in info if r["id"] not in seen_r]
                for d in dates:
                    if iso(d) not in seen_d and left_r:
                        cand.append({"date": iso(d), "recipe_id": left_r.pop(0)["id"]})
                out, used_ai = sorted(cand, key=lambda a: a["date"]), True
        except Exception as e:
            log("arrange: AI unavailable, using the simple spread:", getattr(e, "message", None) or e)
    if out is None:
        out = _arrange_fallback(info, dates)
    return {"assignments": out, "ai": used_ai, "dropped": dropped, "empty_days": n_empty}


def plan_skip(eid, skipped=True):
    """A past day that wasn't cooked: stop asking about it."""
    require_native()
    with db() as c:
        if not n_plans.set_skipped(c, eid, skipped):
            raise ApiError(404, "Plan entry not found")
        sync_plan_list(c)
    return {"ok": True}


COOK_SNAPSHOT = ("qty", "unit", "original_qty", "amount_left", "status", "finished_on", "opened_on", "expires_on",
                 "expiry_source")


def _pantry_by_key(c):
    """Active pantry rows by food key (plain and cleaned names), soonest-expiring first."""
    out = {}
    rows = c.execute("SELECT * FROM pantry_items WHERE status='active' ORDER BY "
                     "CASE WHEN expires_on IS NULL THEN 1 ELSE 0 END, expires_on, id").fetchall()
    for r in rows:
        keys = {food_key(r["name"]), food_key(clean_food(r["name"]))}
        if r["food_id"] is not None:
            keys.add(f"f:{r['food_id']}")
        for k in keys:
            if k:
                out.setdefault(k, []).append(r["id"])
    return out


def _cook_needs(rec, factor, skeys=None, c=None):
    """[(food name, quantity or None, unit)] for a recipe's non-staple ingredients, scaled by factor."""
    out = []
    for ing in rec.get("recipeIngredient") or []:
        line = _ing_line(ing)
        if not line:
            continue
        parsed = split_foods(parse_ing_text(line)) or [None]
        for p in parsed:
            if p and not p.get("amount_text"):
                name, q, unit = clean_food(p["food"]), p["quantity"] * factor, p["unit"] or ""
            elif p:
                name, q, unit = clean_food(p["food"]), None, ""   # "to taste", "pinch": amount unknown
            else:
                name, q, unit = clean_food(line), None, ""
            key = food_key(name)
            if not key or is_staple(name, skeys, c):
                continue
            out.append((name, q, unit))
    return out


_STAPLE_KEYS = {food_key(x) for x in STAPLES}


def recipe_cooked(slug, b):
    """Mark a recipe cooked: take what it used out of the pantry (undoable) and tick off its plan entry."""
    require_native()
    b = b if isinstance(b, dict) else {}
    plan_id = _int_id(b["plan_id"]) if b.get("plan_id") not in (None, "") else None
    servings = b.get("servings")
    if servings not in (None, ""):
        if isinstance(servings, bool) or not isinstance(servings, (int, float, str)):
            raise ApiError(400, "Servings must be a number.")
        try:
            servings = float(servings)
        except ValueError:
            raise ApiError(400, "Servings must be a number.")
        if not 0 < servings <= 1000:
            raise ApiError(400, "Servings must be between 0 and 1000.")
    else:
        servings = None
    token = secrets.token_urlsafe(12)
    deducted, unknown, finished = [], [], []
    now = datetime.now().isoformat(timespec="seconds")
    with db() as c:
        rec = n_recipes.get(c, slug)
        if not rec:
            raise ApiError(404, "Recipe not found")
        entry = n_plans.get_entry(c, plan_id) if plan_id is not None else None
        if plan_id is not None and not entry:
            raise ApiError(404, "Plan entry not found")
        base = _num(rec.get("recipeServings")) or _num(rec.get("recipeYieldQuantity"))
        if servings is not None:
            factor = servings / base if base else 1.0
        else:
            factor = float(entry["scale"]) if entry else 1.0
        pantry = _pantry_by_key(c)
        snap = {}
        for name, need, unit in _cook_needs(rec, factor, staple_keys(c), c):
            fid = n_foods.lookup(c, name)
            ids = (pantry.get(f"f:{fid}") if fid is not None else None) or pantry.get(food_key(name)) or []
            if plan_id is not None and fid is not None:   # what was set aside for this meal goes first
                mine = [r[0] for r in c.execute("SELECT pantry_item_id FROM allocations WHERE plan_entry_id=? AND food_key=?",
                                                (plan_id, f"f:{fid}"))]
                ids = mine + [i for i in ids if i not in mine]
            row = next((r for r in (pantry_row(c, i) for i in ids) if r and r["status"] == "active"), None)
            if not row:
                continue
            if row["id"] not in snap:
                snap[row["id"]] = {k: row[k] for k in COOK_SNAPSHOT}
            used_txt = n_units.fmt(need, unit, name) if need is not None else name
            amt = n_units.convert(need, unit, row["unit"]) if (need is not None and row["qty"] is not None) else None
            if amt is not None:
                orig = row["original_qty"] or row["qty"]
                left = row["qty"] - amt
                if left <= 1e-6:
                    c.execute("UPDATE pantry_items SET qty=0, original_qty=?, amount_left=0, status='used', finished_on=? "
                              "WHERE id=?", (orig, iso(today()), row["id"]))
                    finished.append(row["name"])
                    deducted.append({"name": row["name"], "used": used_txt, "left_text": "finished"})
                    continue
                c.execute("UPDATE pantry_items SET qty=?, original_qty=?, amount_left=? WHERE id=?",
                          (left, orig, max(0.0, min(1.0, left / orig)) if orig else 0.0, row["id"]))
                if not row["opened_on"] and row["location"] != "freezer":
                    apply_pantry_action(c, row["id"], {"action": "open"})
                deducted.append({"name": row["name"], "used": used_txt, "left_text": pantry_left_text(pantry_row(c, row["id"]))})
                continue
            # amount unknown (or units that don't convert): it's open now, and about half of it is gone
            if not row["opened_on"] and row["location"] != "freezer":
                apply_pantry_action(c, row["id"], {"action": "open"})
            left = max(0.0, (row["amount_left"] or 0) - 0.5)
            if left <= 1e-6:
                c.execute("UPDATE pantry_items SET amount_left=0, status='used', finished_on=? WHERE id=?",
                          (iso(today()), row["id"]))
                finished.append(row["name"])
            else:
                c.execute("UPDATE pantry_items SET amount_left=? WHERE id=?", (left, row["id"]))
            unknown.append(row["name"])
        for iid, before in snap.items():   # the ledger: each item before and after, so undo and edits are exact
            after = pantry_row(c, iid)
            event(c, iid, "cooked", json.dumps({"token": token, "before": before, "after": {k: after[k] for k in COOK_SNAPSHOT},
                                                "recipe": rec.get("name") or ""}))
        if entry:
            prev = n_plans.set_cooked(c, plan_id, now)
            c.execute("INSERT INTO pantry_events(item_id, at, action, detail) VALUES (NULL,?,?,?)",
                      (now, "cooked-plan", json.dumps({"token": token, "plan_id": plan_id, "before": prev})))
        c.execute("INSERT INTO pantry_events(item_id, at, action, detail) VALUES (NULL,?,?,?)",
                  (now, "cooked-recipe", json.dumps({"token": token, "recipe_id": rec["id"]})))
        did = c.execute("INSERT INTO diary(recipe_id, plan_entry_id, kind, cooked_at, servings, undo_token, created_at) "
                        "VALUES (?,?,?,?,?,?,?)", (rec["id"], plan_id, "cooked", now, servings or (base * factor if base else None),
                                                   token, now)).lastrowid
        if NATIVE:
            sync_plan_list(c)   # the meal's allocations are spent; the rest of the plan re-claims what's left
    timed = record_cook_time(rec["id"], b.get("cook_minutes"), eta_base(rec, store=False)) if b.get("cook_minutes") is not None else False
    return {"ok": True, "deducted": deducted, "unknown": sorted(set(unknown), key=str.lower),
            "finished": sorted(set(finished), key=str.lower), "undo_token": token, "plan_id": plan_id, "diary_id": did,
            "timed": timed}


# ============================================================ cooking diary (cooked meals, ratings, notes, photos)

def _diary_photo_remove(name):
    if name and re.fullmatch(r"\d{1,12}\.(jpg|png|webp|gif)", name):
        try:
            os.remove(os.path.join(IMG_DIR, "diary", name))
        except OSError:
            pass


def diary_json(r):
    return {"id": r["id"], "recipe_id": r["recipe_id"], "plan_entry_id": r["plan_entry_id"], "kind": r["kind"],
            "cooked_at": r["cooked_at"], "date": r["cooked_at"][:10], "rating": r["rating"], "note": r["note"] or "",
            "servings": r["servings"], "photo": f"/img/diary/{r['id']}?v={urllib.parse.quote(r['photo'])}" if r["photo"] else None,
            "recipe_name": r["name"] if "name" in r.keys() else None, "slug": r["slug"] if "slug" in r.keys() else None}


def diary_list(flt="all", limit=60, recipe_id=None):
    where, args = ["1=1"], []
    if flt == "top":
        where.append("d.rating >= 4")
    elif flt == "notes":
        where.append("d.note <> ''")
    if recipe_id:
        where.append("d.recipe_id = ?"); args.append(recipe_id)
    with db() as c:
        rows = c.execute(f"SELECT d.*, r.name, r.slug, r.data AS rdata FROM diary d LEFT JOIN recipes r ON r.id=d.recipe_id "
                         f"WHERE {' AND '.join(where)} ORDER BY d.cooked_at DESC, d.id DESC LIMIT ?", (*args, int(limit))).fetchall()
    out = []
    for r in rows:
        j = diary_json(r)
        try:
            img = (json.loads(r["rdata"] or "{}") or {}).get("image")
        except ValueError:
            img = None
        j["recipe_image"] = f"/img/{r['recipe_id']}?size=min&v={urllib.parse.quote(str(img))}" if img and UUID_RE.fullmatch(r["recipe_id"] or "") else None
        out.append(j)
    return out


def diary_ratings():
    """{recipe_id: (average rating, count)} from the diary."""
    with db() as c:
        return {r[0]: (round(r[1], 1), r[2]) for r in c.execute(
            "SELECT recipe_id, AVG(rating), COUNT(rating) FROM diary WHERE rating IS NOT NULL GROUP BY recipe_id")}


def diary_add(b):
    """A note at any time, without cooking: POST /api/diary {slug, note, rating?}."""
    require_native()
    with db() as c:
        rec = n_recipes.get(c, _s(b.get("slug"), 200))
        if not rec:
            raise ApiError(404, "Recipe not found")
        note = _s(b.get("note"), 2000).strip()
        rating = _rating_arg(b.get("rating"))
        if not note and rating is None:
            raise ApiError(400, "Write a note or pick a rating.")
        now = datetime.now().isoformat(timespec="seconds")
        did = c.execute("INSERT INTO diary(recipe_id, kind, cooked_at, rating, note, created_at) VALUES (?,?,?,?,?,?)",
                        (rec["id"], _s(b.get("kind"), 20) if b.get("kind") in ("note", "adjusted") else "note", now, rating, note, now)).lastrowid
    _recipe_cache["at"] = 0
    return next(x for x in diary_list(recipe_id=rec["id"]) if x["id"] == did)


def _rating_arg(v):
    if v in (None, "", 0):
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 1 <= v <= 5:
        raise ApiError(400, "Ratings are 1 to 5 stars.")
    return int(round(v))


def diary_update(did, b):
    require_native()
    with db() as c:
        r = c.execute("SELECT * FROM diary WHERE id=?", (did,)).fetchone()
        if not r:
            raise ApiError(404, "Diary entry not found")
        rating = _rating_arg(b["rating"]) if "rating" in b else r["rating"]
        note = _s(b.get("note"), 2000).strip() if "note" in b else r["note"]
        cooked_at = r["cooked_at"]
        if b.get("date"):
            d = _strict_date(b.get("date"), "date")
            if d > today():
                raise ApiError(400, "That date is in the future.")
            cooked_at = iso(d) + (r["cooked_at"][10:] if len(r["cooked_at"] or "") > 10 else "T19:00:00")
        servings = r["servings"]
        if "servings" in b and b["servings"] not in (None, ""):
            try:
                new = float(b["servings"])
            except (TypeError, ValueError):
                raise ApiError(400, "Servings must be a number.")
            if not 0 < new <= 1000:
                raise ApiError(400, "Servings must be between 0 and 1000.")
            if r["undo_token"] and servings and abs(new - servings) > 1e-9:
                # cooked a different amount: give back (or take) the difference from the inventory
                k = 1 - new / servings
                for ev, d in _cook_events(c, r["undo_token"]):
                    if ev["action"] == "cooked" and ev["item_id"] is not None:
                        _cook_give_back(c, ev["item_id"], d.get("before") or {}, d.get("after") or {}, k)
                        now_row = pantry_row(c, ev["item_id"])
                        d["after"] = {x: now_row[x] for x in COOK_SNAPSHOT}
                        c.execute("UPDATE pantry_events SET detail=? WHERE id=?", (json.dumps(d), ev["id"]))
                sync_plan_list(c)
            servings = new
        c.execute("UPDATE diary SET rating=?, note=?, cooked_at=?, servings=? WHERE id=?", (rating, note, cooked_at, servings, did))
    _recipe_cache["at"] = 0
    return next((x for x in diary_list(limit=500) if x["id"] == did), {"id": did})


def diary_photo(did, b):
    blob, ctype = decode_upload(b.get("data"))
    with db() as c:
        r = c.execute("SELECT * FROM diary WHERE id=?", (did,)).fetchone()
        if not r:
            raise ApiError(404, "Diary entry not found")
    d = os.path.join(IMG_DIR, "diary")
    os.makedirs(d, exist_ok=True)
    name = f"{int(did)}.{_ext(ctype)}"
    _diary_photo_remove(r["photo"])
    with open(os.path.join(d, name), "wb") as f:
        f.write(blob)
    with db() as c:
        c.execute("UPDATE diary SET photo=? WHERE id=?", (name, did))
    return next((x for x in diary_list(limit=500) if x["id"] == did), {"id": did})


def diary_delete(did, restore=False):
    """Delete a diary entry. restore=True also puts the ingredients back (a full undo of that cook)."""
    with db() as c:
        r = c.execute("SELECT * FROM diary WHERE id=?", (did,)).fetchone()
        if not r:
            raise ApiError(404, "Diary entry not found")
        token, plan_id = r["undo_token"], r["plan_entry_id"]
    if restore and token:
        cooked_undo({"undo_token": token})
        return {"ok": True, "restored": True}
    with db() as c:
        c.execute("DELETE FROM diary WHERE id=?", (did,))
        if plan_id is not None and r["kind"] == "cooked":   # it wasn't cooked after all: the plan entry goes back too
            try:
                n_plans.set_cooked(c, plan_id, None)
            except KeyError:
                pass
    _diary_photo_remove(r["photo"])
    _recipe_cache["at"] = 0
    return {"ok": True}


# ============================================================ "Make it my way": AI adjustments with a diff, and versions

ADJUST_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summary", "ingredients", "steps"],
    "properties": {
        "summary": {"type": "string"},
        "ingredients": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                   "required": ["status", "was", "line", "reason"],
                                                   "properties": {"status": {"type": "string", "enum": ["same", "changed", "added", "removed"]},
                                                                  "was": {"type": "string"}, "line": {"type": "string"},
                                                                  "reason": {"type": "string"}}}},
        "steps": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "required": ["status", "was", "text", "reason"],
                                             "properties": {"status": {"type": "string", "enum": ["same", "changed", "added", "removed"]},
                                                            "was": {"type": "string"}, "text": {"type": "string"},
                                                            "reason": {"type": "string"}}}},
    },
}


def recipe_adjust(slug, b):
    """POST /api/recipe/{slug}/adjust {request}: propose a version of the recipe changed only as the cook asked."""
    require_native()
    if not cfg("openai_key"):
        raise ApiError(400, "Adjusting a recipe needs AI. Add your OpenAI key in Settings → AI recipe import, or edit the recipe yourself.")
    req = " ".join(_s(b.get("request"), 300).split())
    if not req:
        raise ApiError(400, "Say how you'd like it changed.")
    with db() as c:
        rec = n_recipes.get(c, slug)
    if not rec:
        raise ApiError(404, "Recipe not found")
    lines = [_ing_line(g) for g in rec.get("recipeIngredient") or [] if _ing_line(g)]
    steps = [(st.get("text") or "").strip() for st in rec.get("recipeInstructions") or [] if (st.get("text") or "").strip()]
    out = openai_chat([{"role": "user", "content": (
        "Adjust this recipe the way the cook asks. Make only the changes needed for the request, with sensible real-world "
        "amounts; adding, removing or changing ingredients and steps is allowed here because the cook asked for it. Never "
        "change anything unrelated to the request. Return EVERY original ingredient and step in order: status 'same' (copy "
        "it exactly), 'changed' (new text in line/text, the original in 'was'), or 'removed' (original in 'was'); insert "
        "'added' items where they belong (empty 'was'). Give each change a one-line reason; 'same' items get an empty reason. "
        "summary: one short phrase naming the main changes (e.g. 'spicier: +1 tsp chili flakes').\n\n"
        + json.dumps({"request": req, "name": rec.get("name"), "servings": rec.get("recipeServings"), "ingredients": lines,
                      "steps": steps}, ensure_ascii=False))}], "recipe_adjust", ADJUST_SCHEMA, "adjust", req[:60])
    ings = [x for x in out.get("ingredients") or [] if isinstance(x, dict)]
    sts = [x for x in out.get("steps") or [] if isinstance(x, dict)]
    if not ings or not sts:
        raise ApiError(502, "The adjustment came back empty. Try again.")
    return {"request": req, "summary": (out.get("summary") or req)[:120], "ingredients": ings, "steps": sts}


def _version_of(rec):
    return {"at": datetime.now().isoformat(timespec="seconds"), "name": rec.get("name"),
            "description": rec.get("description") or "",
            "ingredients": [{"title": g.get("title"), "line": _ing_line(g)} for g in rec.get("recipeIngredient") or [] if _ing_line(g)],
            "steps": [(st.get("text") or "").strip() for st in rec.get("recipeInstructions") or [] if (st.get("text") or "").strip()]}


def _apply_version(rec, ingredients, steps):
    ings = []
    for x in ingredients:
        line = " ".join(str(x.get("line") if isinstance(x, dict) else x).split())[:300]
        if line:
            ings.append({"referenceId": str(uuid.uuid4()), "title": (x.get("title") if isinstance(x, dict) else None) or None,
                         "note": line, "display": line, "originalText": line, "quantity": 0, "unit": None, "food": None})
    return dict(rec, recipeIngredient=ings, recipeInstructions=[
        {"id": str(uuid.uuid4()), "title": "", "text": " ".join(str(t).split())[:3000], "ingredientReferences": []}
        for t in steps if str(t).strip()])


def recipe_adjust_save(slug, b):
    """Save an adjustment as the main recipe; the text before it goes to extras.versions and a diary note is added."""
    require_native()
    ings = [x for x in (b.get("ingredients") or []) if isinstance(x, dict) and x.get("status") != "removed"]
    steps = [x.get("text") for x in (b.get("steps") or []) if isinstance(x, dict) and x.get("status") != "removed"]
    if not ings or not steps or len(ings) > 200 or len(steps) > 100:
        raise ApiError(400, "Nothing to save.")
    summary = " ".join(_s(b.get("summary"), 160).split()) or " ".join(_s(b.get("request"), 160).split())
    with db() as c:
        rec = n_recipes.get(c, slug)
        if not rec:
            raise ApiError(404, "Recipe not found")
        extras = dict(rec.get("extras") or {})
        versions = list(extras.get("versions") or [])
        v = _version_of(rec)
        v["label"] = "Before: " + (summary or "adjustment")
        versions.append(v)
        extras["versions"] = versions[-20:]
        new = _apply_version(rec, [{"line": x.get("line")} for x in ings], steps)
        new["extras"] = extras
        slug = n_recipes.update(c, rec["id"], _annotate_foods(c, new))
        invalidate_guided(c, rec["id"], slug)
        now = datetime.now().isoformat(timespec="seconds")
        changes = [x.get("line") or x.get("text") for x in (b.get("ingredients") or []) + (b.get("steps") or [])
                   if isinstance(x, dict) and x.get("status") in ("changed", "added")]
        note = f"Adjusted: {summary}" + (f" ({'; '.join(str(x) for x in changes[:2])}…)" if changes else "")
        c.execute("INSERT INTO diary(recipe_id, kind, cooked_at, note, created_at) VALUES (?,?,?,?,?)",
                  (rec["id"], "adjusted", now, note[:500], now))
    _recipe_cache["at"] = 0
    return recipe_detail(slug)


def recipe_versions(slug):
    with db() as c:
        rec = n_recipes.get(c, slug)
    if not rec:
        raise ApiError(404, "Recipe not found")
    vs = (rec.get("extras") or {}).get("versions") or []
    return {"versions": [{"n": i, "at": v.get("at"), "label": v.get("label") or "Earlier version",
                          "ingredients": len(v.get("ingredients") or []), "steps": len(v.get("steps") or [])}
                         for i, v in enumerate(vs)][::-1]}


def recipe_version_restore(slug, n):
    """Go back to an earlier version; the current text is kept as a version too, so this can be undone the same way."""
    require_native()
    with db() as c:
        rec = n_recipes.get(c, slug)
        if not rec:
            raise ApiError(404, "Recipe not found")
        extras = dict(rec.get("extras") or {})
        vs = list(extras.get("versions") or [])
        if not 0 <= n < len(vs):
            raise ApiError(404, "Version not found")
        v = vs.pop(n)
        cur = _version_of(rec)
        cur["label"] = "Before going back to: " + (v.get("label") or "an earlier version")
        vs.append(cur)
        extras["versions"] = vs[-20:]
        new = _apply_version(rec, v.get("ingredients") or [], v.get("steps") or [])
        new["description"] = v.get("description") or rec.get("description") or ""
        new["extras"] = extras
        slug = n_recipes.update(c, rec["id"], _annotate_foods(c, new))
        invalidate_guided(c, rec["id"], slug)
    _recipe_cache["at"] = 0
    return recipe_detail(slug)


def _cook_events(c, token, include_undone=False):
    rows = c.execute("SELECT * FROM pantry_events WHERE (action IN ('cooked', 'cooked-plan', 'cooked-recipe') OR action LIKE '% (undone)') "
                     "AND detail LIKE ? ORDER BY id DESC", (f'%"token": "{token}"%',)).fetchall()
    out = []
    for r in rows:
        try:
            d = json.loads(r["detail"])
        except (TypeError, ValueError):
            continue
        if d.get("token") == token and (include_undone or not r["action"].endswith("(undone)")):
            out.append((r, d))
    return out


def _cook_give_back(c, iid, before, after, k):
    """Return k × what one cook took from an item (k < 0 takes more). Exact when nothing else touched the item since."""
    cur = pantry_row(c, iid)
    if not cur or not after:
        return False
    if k == 1 and all(cur[x] == after.get(x) for x in COOK_SNAPSHOT):
        c.execute(f"UPDATE pantry_items SET {', '.join(f'{x}=?' for x in COOK_SNAPSHOT)} WHERE id=?",
                  (*(before.get(x) for x in COOK_SNAPSHOT), iid))
        return True
    f = {}
    if cur["qty"] is not None and before.get("qty") is not None and after.get("qty") is not None:
        q = max(0.0, cur["qty"] + k * (before["qty"] - after["qty"]))
        orig = max(q, cur["original_qty"] or 0) or None
        f.update(qty=q, original_qty=orig, amount_left=max(0.0, min(1.0, q / orig)) if orig else 0.0)
    elif before.get("amount_left") is not None and after.get("amount_left") is not None:
        f["amount_left"] = max(0.0, min(1.0, (cur["amount_left"] or 0) + k * (before["amount_left"] - after["amount_left"])))
    left = f.get("amount_left", cur["amount_left"] or 0)
    if left > 1e-6 and cur["status"] == "used" and before.get("status") == "active":
        f.update(status="active", finished_on=None)
    elif left <= 1e-6 and cur["status"] == "active":
        f.update(status="used", finished_on=iso(today()))
    if f:
        c.execute(f"UPDATE pantry_items SET {', '.join(f'{x}=?' for x in f)} WHERE id=?", (*f.values(), iid))
    return bool(f)


def cooked_undo(b):
    """Put the pantry back the way it was before a "cooked", remove its diary entry and un-cook the plan entry.
    Doing it twice is harmless."""
    require_native()
    token = _s((b or {}).get("undo_token"), 64).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", token):
        raise ApiError(400, "Nothing to undo.")
    restored = 0
    with db() as c:
        rows = _cook_events(c, token)
        if not rows:
            if _cook_events(c, token, include_undone=True):
                return {"ok": True, "restored": 0, "already": True}
            raise ApiError(404, "That can't be undone any more.")
        for r, d in rows:
            if r["action"] == "cooked" and r["item_id"] is not None:
                if _cook_give_back(c, r["item_id"], d.get("before") or {}, d.get("after") or d.get("before") or {}, 1):
                    restored += 1
                elif not d.get("after"):   # an older ledger entry (no "after"): put the snapshot back
                    c.execute(f"UPDATE pantry_items SET {', '.join(f'{k}=?' for k in COOK_SNAPSHOT)} WHERE id=?",
                              (*(d["before"].get(k) for k in COOK_SNAPSHOT), r["item_id"]))
                    restored += 1
                event(c, r["item_id"], "cook undone")
            elif r["action"] == "cooked-plan":
                try:
                    n_plans.set_cooked(c, d["plan_id"], d.get("before"))
                except KeyError:
                    pass
            c.execute("UPDATE pantry_events SET action=action || ' (undone)' WHERE id=?", (r["id"],))
        for d in c.execute("SELECT id, photo FROM diary WHERE undo_token=?", (token,)).fetchall():
            _diary_photo_remove(d["photo"])
            c.execute("DELETE FROM diary WHERE id=?", (d["id"],))
        sync_plan_list(c)
    _recipe_cache["at"] = 0
    return {"ok": True, "restored": restored}


def cooked_today(recipe_id):
    """The latest undoable cook of this recipe today: {diary_id, undo_token} or None."""
    if not NATIVE:
        return None
    with db() as c:
        r = c.execute("SELECT id, undo_token FROM diary WHERE recipe_id=? AND kind='cooked' AND undo_token IS NOT NULL AND "
                      "substr(cooked_at, 1, 10)=? ORDER BY id DESC LIMIT 1", (recipe_id, iso(today()))).fetchone()
    return {"diary_id": r["id"], "undo_token": r["undo_token"]} if r else None


def plan_uncook(entry_id):
    """"Not cooked yet": undo the cook that ticked this plan entry (or just clear the tick if there's no record)."""
    require_native()
    with db() as c:
        e = n_plans.get_entry(c, entry_id)
        if not e:
            raise ApiError(404, "Plan entry not found")
        token = None
        for r in c.execute("SELECT detail FROM pantry_events WHERE action='cooked-plan' ORDER BY id DESC LIMIT 200"):
            try:
                d = json.loads(r["detail"])
            except ValueError:
                continue
            if d.get("plan_id") == entry_id:
                token = d.get("token")
                break
        if not token:
            n_plans.set_cooked(c, entry_id, None)
            return {"ok": True, "restored": 0}
    return cooked_undo({"undo_token": token})


def cook_entry_for(recipe_id):
    """The plan entry to tick off when this recipe is cooked: planned today or in the last 2 days, not cooked or
    skipped yet. {id, date, today} or None."""
    if not NATIVE or not recipe_id:
        return None
    t = today()
    with db() as c:
        for e in n_plans.recent_for_recipe(c, recipe_id, iso(t - timedelta(days=2)), iso(t)):
            if not e.get("cooked_at") and not e.get("skipped_at"):
                return {"id": e["id"], "date": e["date"], "today": e["date"] == iso(t)}
    return None


def plan_status():
    s = get_settings()
    t = today()
    types = [m for m in s.get("meal_types") or [] if m in n_plans.ENTRY_TYPES] or ["dinner"]
    end = t + timedelta(days=MAX_RANGE_DAYS)
    if NATIVE:
        with db() as c:
            dates = n_plans.planned_dates(c, iso(t), iso(end), types)
    else:
        dates = sorted({e["date"] for e in get_plans(t, t + timedelta(days=120)) if e["entry_type"] in types})
    through = parse_date(dates[-1]) if dates else None
    return {"planned_through": iso(through), "days_left": (through - t).days + 1 if through else 0,
            "planned_days": len(dates), "horizon_days": int(s.get("plan_horizon_days") or 14),
            "reminder_days": int(s.get("plan_reminder_days") or 0)}


_app_url = {"url": ""}   # how the household reaches TablePlan, captured from recent signed-in requests


def unchecked_count():
    try:
        lists = get_lists()
        if not lists:
            return 0
        return sum(1 for i in (get_list(lists[0]["id"]).get("listItems") or []) if not i.get("checked"))
    except ApiError:
        return 0


def notify_plan_runout(now=None):
    """Once per run-out: tell the household the plan is about to end."""
    now = now or datetime.now()
    s = get_settings()
    remind = int(s.get("plan_reminder_days") or 0)
    if remind <= 0 or not any(channels_ready().values()) or now.hour < int(s.get("expiry_alert_hour") or 8):
        return None
    st = plan_status()
    through = st["planned_through"]
    if not through or st["days_left"] > remind or get_internal("plan_runout_notified") == through:
        return None
    day = parse_date(through).strftime("%A")
    n, items = st["planned_days"], unchecked_count()
    url = _app_url["url"]
    text = (f"{n} planned day{'s' if n != 1 else ''} left. {items} item{'s' if items != 1 else ''} on your shopping list."
            + (f"\n\nPlan the next days: {url}" if url else ""))
    msg = {"subject": f"🗓️ Your meal plan runs out {day}", "text": text,
           "html": email_wrap(f"<p>{html.escape(text.split(chr(10))[0])}</p>"
                              + (f'<p><a href="{html.escape(url)}">Open TablePlan</a></p>' if url else "")),
           "files": []}
    deliver(msg)
    set_internal("plan_runout_notified", through)
    return msg


# ============================================================ the ongoing shopping list and stores

def _qty_text(i):
    u = i.get("unit") or {}
    unit = (u.get("pluralName") or u.get("name")) if (i.get("quantity") or 0) > 1 else u.get("name")
    return " ".join(x for x in (nice_qty(i.get("quantity")) if (i.get("food") or i.get("unit")) else "", unit or "") if x)


def _uses(i, entries):
    """Per-meal breakdown of a list item: [{entry_id, date, recipe_name, qty_text}], soonest first."""
    out = []
    for k, v in (i.get("contrib") or {}).items():
        e = entries.get(str(k)) if isinstance(v, dict) else None
        if not e:
            continue
        q = v.get("qty")
        out.append({"entry_id": e["id"], "date": e["date"], "recipe_name": e["name"],
                    "qty_text": n_units.fmt(q, v.get("unit") or "") if q else (v.get("text") or "")})
    return sorted(out, key=lambda u: (u["date"], u["entry_id"]))


def _plan_names(c):
    return {str(r["id"]): {"id": r["id"], "date": r["date"], "name": r["name"] or ""} for r in c.execute(
        "SELECT m.id, m.date, r.name FROM meal_plans m LEFT JOIN recipes r ON r.id=m.recipe_id WHERE m.date>=?", (iso(today()),))}


def list_item_json(i, names, entries=None):
    food = (i.get("food") or {}).get("name") or ""
    return {"id": i["id"], "text": item_text(i), "name": item_name(i), "food": food, "qty": _qty_text(i),
            "emoji": food_emoji(food or i.get("note") or i.get("display")), "checked": bool(i.get("checked")),
            "checked_at": i.get("checkedAt"), "have": i.get("checkedHow") == "have",
            "store_id": i.get("storeId"), "aisle": ((i.get("label") or {}).get("name") or "Other"),
            "recipes": [names[r] for r in i.get("recipeIds") or [] if r in names],
            "uses": _uses(i, entries) if entries else [], "manual": bool(i.get("manual")),
            "food_id": i.get("foodId"), "bought": _bought_text(i), "last": _last_hint(i.get("foodId")) if not i.get("checked") else None}


def _bought_text(i):
    b = i.get("bought")
    if not b:
        return None
    parts = [b.get("product") or "", b.get("size") or "", f"${b['price']:.2f}" if isinstance(b.get("price"), (int, float)) else ""]
    return f"{item_name(i)} → " + ", ".join(x for x in parts if x)


_prefs = {"at": 0, "rows": {}, "stores": {}}


def _last_hint(food_id):
    """'Last time: Kemps · 1 gal at Aldi' for a food bought before (cached a few seconds per request burst)."""
    if not food_id:
        return None
    if time.time() - _prefs["at"] > 5:
        with db() as c:
            _prefs["rows"] = {r["food_id"]: dict(r) for r in c.execute("SELECT * FROM food_pref")}
            _prefs["stores"] = {s["id"]: s["name"] for s in n_lists.list_stores(c)}
        _prefs["at"] = time.time()
    p = _prefs["rows"].get(food_id)
    if not p or not (p.get("product") or p.get("size")):
        return None
    where = _prefs["stores"].get(p.get("store_id"))
    return "Last time: " + " ".join(x for x in (p.get("product") or "", p.get("size") or "") if x) + (f" at {where}" if where else "")


def remember_purchase(c, food_id, product="", size="", store_id=None, price=None, upc=""):
    if not food_id:
        return
    old = c.execute("SELECT * FROM food_pref WHERE food_id=?", (food_id,)).fetchone()
    c.execute("INSERT INTO food_pref(food_id, product, size, store_id, price, upc, at) VALUES (?,?,?,?,?,?,?) "
              "ON CONFLICT(food_id) DO UPDATE SET product=excluded.product, size=excluded.size, store_id=excluded.store_id, "
              "price=excluded.price, upc=excluded.upc, at=excluded.at",
              (food_id, product or (old["product"] if old else ""), size or (old["size"] if old else ""),
               store_id or (old["store_id"] if old else None), price if price is not None else None, upc or "", iso(today())))
    _prefs["at"] = 0


def fulfill_line(c, list_id, li_id, pantry_item_id=None, product="", size="", price=None, store_id=None, upc=""):
    """Tick a list line off with what was actually bought, link the inventory item, and remember the choice."""
    li = c.execute("SELECT * FROM shopping_items WHERE id=? AND list_id=?", (li_id, list_id)).fetchone()
    if not li:
        return None
    n_lists.set_checked(c, list_id, li["id"], True)
    bought = {k: v for k, v in (("product", product), ("size", size), ("price", price), ("store_id", store_id), ("upc", upc)) if v not in ("", None)}
    c.execute("UPDATE shopping_items SET bought=? WHERE id=?", (json.dumps(bought) if bought else None, li["id"]))
    if pantry_item_id:
        c.execute("UPDATE pantry_items SET mealie_item_id=? WHERE id=?", (li["id"], pantry_item_id))
    remember_purchase(c, li["food_id"], product, size, store_id, price, upc)
    return {"id": li["id"], "text": n_lists._display(li)}


def list_matches(c, list_id, food_id, food_name):
    """Open list lines a bought product fills. exact: same canonical food; related: a generic line ("Milk") the
    specific product ("Whole milk") could fill. Variants (2% vs whole) never match."""
    rows = c.execute("SELECT s.*, f.name AS food_name FROM shopping_items s LEFT JOIN foods f ON f.id=s.food_id "
                     "WHERE s.list_id=? AND s.checked=0", (list_id,)).fetchall()
    exact = [r for r in rows if food_id is not None and r["food_id"] == food_id]
    related = [] if exact else [r for r in rows if n_catalog.related(r["food"] or r["food_name"] or r["text"], food_name)]
    return exact, related


def _recipe_names(c):
    return {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM recipes")}


CHECKED_VISIBLE_HOURS = 4   # a ticked item stays on the list, struck through, this long


def ongoing_list(now=None):
    """The list: unchecked items plus items checked in the last few hours (shown in place, struck through).
    Older checked items only appear in recently_checked. `count` is the number still to buy."""
    require_native()
    cut = ((now or datetime.now(timezone.utc)) - timedelta(hours=CHECKED_VISIBLE_HOURS)).isoformat(timespec="seconds")
    with db() as c:
        lid = n_lists.single_list(c)
        sl = n_lists.get_list(c, lid)
        fresh = n_lists.checked_since(c, lid, cut)
        recent = n_lists.recently_checked(c, lid, 20, before=cut)
        stores = n_lists.list_stores(c)
        names = _recipe_names(c)
        plans = _plan_names(c)
    order = {s["id"]: i for i, s in enumerate(stores)}
    unchecked = [list_item_json(i, names, plans) for i in sl["listItems"] if not i["checked"]]
    items = unchecked + [list_item_json(i, names, plans) for i in fresh]
    items.sort(key=lambda x: (order.get(x["store_id"], len(order)), x["aisle"] == "Other", x["aisle"].lower()))
    return {"id": lid, "name": sl["name"], "items": items, "count": len(unchecked),
            "recently_checked": [list_item_json(i, names) for i in recent],
            "stores": [{"id": s["id"], "name": s["name"]} for s in stores]}


def _store_arg(v):
    if v in (None, ""):
        return None
    return _s(v, 64).strip() or None


def _item_key(it):
    if it.get("foodId"):
        return n_lists.food_store_key(it["foodId"])
    return food_key((it.get("food") or {}).get("name") or it.get("note") or it.get("display") or "")


def list_add(b):
    require_native()
    raw = b.get("items")
    if not isinstance(raw, list):
        raise ApiError(400, "Send items as a list.")
    items = [_s(t, 200).strip() for t in raw[:100] if isinstance(t, str)]
    items = [t for t in items if t]
    if not items:
        raise ApiError(400, "Type at least one item.")
    sid = _store_arg(b.get("store_id"))
    with db() as c:
        lid = n_lists.single_list(c)
        try:
            ids = n_lists.add_items(c, lid, items, list_parse, lambda t: n_catalog.aisle_of(t) or aisle_for(t), food_key, sid,
                                    resolve=_food_id)
        except KeyError:
            raise ApiError(404, "Store not found")
        for i in dict.fromkeys(ids):   # bought it before at a particular store: suggest that store
            r = c.execute("SELECT s.food_id, s.store_id, p.store_id ps FROM shopping_items s LEFT JOIN food_pref p ON p.food_id=s.food_id "
                          "WHERE s.id=?", (i,)).fetchone()
            if r and not r["store_id"] and r["ps"] and n_lists.get_store(c, r["ps"]):
                n_lists.set_item_store(c, i, r["ps"])
        names = _recipe_names(c)
        out = [list_item_json(n_lists.get_item(c, i), names) for i in dict.fromkeys(ids)]
    return {"ok": True, "added": len(out), "items": out}


def list_parse(text):
    """Like parse_ing_text, but "2% milk" and "1% milk" are names, so "2 2% milk" is two of them."""
    m = re.match(r"^\s*(?:(\d+(?:\.\d+)?)\s*(?:x\s+)?)?(\d+(?:\.\d+)?%\s+\S.*)$", text or "", re.I)
    if m:
        return {"food": m.group(2).strip(), "quantity": float(m.group(1)) if m.group(1) else 0, "unit": "", "unit_plural": "",
                "note": "", "amount_text": ""}
    return parse_ing_text(text)


def grocery_suggest(q):
    """Autocomplete for "Add an item…": the household's own past items first, then its foods, then common groceries."""
    require_native()
    q = re.sub(r"^\s*\d+(?:[./]\d+)?\s*(?:x\s*)?", "", _s(q, 80)).strip()   # "2 whole milk" → "whole milk"
    if not q:
        return {"items": []}
    out, seen = [], set()

    def add(name, source, aisle=None, size="", food_id=None, sc=0):
        k = " ".join(n_catalog.words(name))
        if not k or k in seen:
            return
        seen.add(k)
        out.append({"name": name, "source": source, "aisle": aisle or n_catalog.aisle_of(name) or aisle_for(name) or "Other",
                    "size": size, "last": _last_hint(food_id), "score": sc})
    with db() as c:
        hist = c.execute("SELECT text, food, food_id, COUNT(*) n, MAX(created_at) at FROM shopping_items WHERE manual=1 "
                         "GROUP BY lower(coalesce(food, text)) ORDER BY n DESC, at DESC LIMIT 300").fetchall()
        foods = c.execute("SELECT id, name FROM foods ORDER BY name LIMIT 3000").fetchall()
    for r in sorted(hist, key=lambda r: -r["n"]):
        name = sentence_case(r["food"] or r["text"])
        sc = n_catalog.score(q, name)
        if sc:
            add(name, "history", food_id=r["food_id"], sc=2000 + sc + min(r["n"], 10))
    for f in foods:
        sc = n_catalog.score(q, f["name"])
        if sc:
            add(sentence_case(f["name"]), "food", food_id=f["id"], sc=1000 + sc)
    for it in n_catalog.search(q, 12):
        add(it["name"], "catalog", it["aisle"], it["size"], sc=it["score"])
    out.sort(key=lambda x: -x["score"])
    for x in out:
        x.pop("score", None)
    return {"items": out[:8]}


def grocery_catalog_view():
    """GET /api/grocery/catalog: the common-items grid, by aisle, with what's already at home.
    Each item: emoji, a cached photo when there is one (never fetched just for this), and how many are at home;
    each aisle: how many inventory items are in it."""
    aisles = n_catalog.by_aisle()
    with db() as c:
        home, by_aisle = {}, {}
        for r in c.execute("SELECT * FROM pantry_items WHERE status='active' AND COALESCE(review,0)=0").fetchall():
            keys = {food_key(clean_food(r["name"])), food_key(r["name"])}
            if r["food_id"] is not None:
                keys.add(f"f:{r['food_id']}")
            for k in keys:
                if k:
                    home.setdefault(k, []).append(r)
        cached = {r["key"] for r in c.execute("SELECT key FROM image_picks WHERE kind='ing' AND file IS NOT NULL AND missing=0")}
        out = []
        for a in aisles:
            items, n_aisle = [], set()
            for it in a["items"]:
                fid = n_foods.lookup(c, it["food"]) if n_foods.normalize(it["food"]) else None
                rows = (home.get(f"f:{fid}") if fid is not None else None) or home.get(food_key(clean_food(it["food"]))) \
                    or home.get(food_key(clean_food(it["name"]))) or []
                rows = list({r["id"]: r for r in rows}.values())
                n_aisle.update(r["id"] for r in rows)
                left = ""
                if len(rows) == 1 and (rows[0]["amount_left"] or 1) < 0.999:
                    left = n_whatcan_left(rows[0]["amount_left"])
                items.append({**it, "emoji": food_emoji(it["name"]), "home": len(rows), "left": left,
                              "photo": (food_key(it["name"]) or it["name"].lower()) in cached})
            out.append({"aisle": a["aisle"], "items": items, "home": len(n_aisle)})
    return {"aisles": out}


def n_whatcan_left(v):
    return {1.0: "", 0.75: "¾ left", 0.5: "½ left", 0.25: "¼ left"}.get(round(float(v) * 4) / 4, f"{round(float(v) * 100)}% left") if v else ""


def grocery_usual():
    """The household's most-added extras (not from recipes), topped up with popular common groceries."""
    require_native()
    with db() as c:
        lid = n_lists.single_list(c)
        open_keys = {(r["food"] or r["text"] or "").lower() for r in c.execute("SELECT food, text FROM shopping_items WHERE list_id=? AND checked=0", (lid,))}
        rows = c.execute("SELECT text, food, COUNT(*) n FROM shopping_items WHERE manual=1 GROUP BY lower(coalesce(food, text)) "
                         "HAVING n >= 2 ORDER BY n DESC LIMIT 20").fetchall()
    staples = {x.lower() for x in staple_names()}
    out = [sentence_case(r["food"] or r["text"]) for r in rows]
    out = [x for x in out if x.lower() not in open_keys and x.lower() not in staples][:12]
    for it in n_catalog.popular():
        if len(out) >= 12:
            break
        if it["name"].lower() not in {x.lower() for x in out} and it["name"].lower() not in open_keys and it["food"].lower() not in staples:
            out.append(it["name"])
    return {"items": out, "from_history": len(rows)}


def list_fulfill(b):
    """POST /api/list/fulfill {item_id, pantry_item_id}: the answer to "Is this for 'Milk'?" after a scan."""
    require_native()
    with db() as c:
        lid = n_lists.single_list(c)
        p = pantry_row(c, _int_id(b.get("pantry_item_id"), "item"))
        if not p:
            raise ApiError(404, "Item not found")
        res = fulfill_line(c, lid, _s(b.get("item_id"), 64), p["id"], p["product"] or p["name"], p["quantity_text"] or "",
                           None, _store_arg(b.get("store_id")), p["upc"] or "")
        if not res:
            raise ApiError(404, "That list item is gone.")
    return {"ok": True, "list_checked": res}


def stores_replace(b):
    require_native()
    stores = b.get("stores") if isinstance(b, dict) else b
    try:
        with db() as c:
            return n_lists.replace_stores(c, stores)
    except ValueError as e:
        raise ApiError(400, str(e))


# ============================================================ cook readiness

def recipe_missing(recipe_id):
    if not NATIVE or not recipe_id:
        return []
    with db() as c:
        return n_lists.unchecked_for_recipe(c, n_lists.single_list(c), recipe_id)


def staples_add(b):
    """"Always have": the food never goes on the list again; matching unchecked items are removed everywhere."""
    require_native()
    raw = " ".join(_s(b.get("name"), 60).split())
    if not raw:
        raise ApiError(400, "Which food?")
    with db() as c:
        fid = _food_id(c, raw)
        f = n_foods.get(c, fid) if fid else None
        name = f["name"] if f else raw
        lid = n_lists.single_list(c)
        removed = []
        for r in c.execute("SELECT * FROM shopping_items WHERE list_id=? AND checked=0", (lid,)).fetchall():
            if (fid is not None and r["food_id"] == fid) or (r["food"] and food_key(clean_food(r["food"])) == food_key(clean_food(raw))):
                if r["manual"]:
                    removed.append(r["text"] or n_lists._display(r))
                c.execute("DELETE FROM shopping_items WHERE id=?", (r["id"],))
    names = staple_names()
    if name.lower() not in (x.lower() for x in names):
        save_settings({"staples": names + [name]})
    return {"ok": True, "name": name, "restore": removed, "staples": staple_names()}


def staples_remove(b):
    require_native()
    name = " ".join(_s(b.get("name"), 60).split())
    save_settings({"staples": [x for x in staple_names() if x.lower() != name.lower()]})
    restore = [t for t in (b.get("restore") or []) if isinstance(t, str) and t.strip()][:50]
    if restore:
        list_add({"items": restore})
    return {"ok": True, "staples": staple_names()}


def _have_to_pantry(c, item_ids):
    """"I have this": the food is at home, so it goes in the inventory (amount unknown) and covers every planned meal
    that needs it until it's used up or tossed. Nothing is added when the inventory already has that food."""
    for iid in item_ids:
        r = c.execute("SELECT * FROM shopping_items WHERE id=?", (iid,)).fetchone()
        if not r or not r["food"]:
            continue
        fid = r["food_id"] if r["food_id"] is not None else _food_id(c, r["food"])
        if fid is None or c.execute("SELECT 1 FROM pantry_items WHERE food_id=? AND status='active'", (fid,)).fetchone():
            continue
        f = n_foods.get(c, fid)
        add_pantry_item(c, f["name"] if f else r["food"], None, None, "", iid, None, None, fid)


def recipe_have_all(slug):
    require_native()
    with db() as c:
        rec = n_recipes.get(c, slug)
        if not rec:
            raise ApiError(404, "Recipe not found")
        lid = n_lists.single_list(c)
        ids = [x["id"] for x in n_lists.unchecked_for_recipe(c, lid, rec["id"])]
        n = n_lists.mark_have(c, ids)
        _have_to_pantry(c, ids)
    return {"ok": True, "count": n}


# ============================================================ prices, costs and budget

KROGER_API = "https://api.kroger.com/v1"
BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
# BLS average retail prices (U.S. city average, series AP...). A series that returns nothing is simply skipped.
BLS_SERIES = {
    "APU0000708111": ("Eggs", 12, "each"),          # grade A large, per dozen
    "APU0000709112": ("Whole milk", 1, "gallon"),   # per gallon
    "APU0000702111": ("White bread", 1, "lb"),
    "APU0000703112": ("Ground beef", 1, "lb"),
    "APU0000706111": ("Whole chicken", 1, "lb"),
    "APU0000FF1101": ("Chicken breast", 1, "lb"),   # boneless
    "APU0000710212": ("Cheddar cheese", 1, "lb"),
    "APU0000FS1101": ("Butter", 1, "lb"),
    "APU0000704111": ("Bacon", 1, "lb"),
    "APU0000711211": ("Bananas", 1, "lb"),
    "APU0000711111": ("Apples", 1, "lb"),
    "APU0000711311": ("Oranges", 1, "lb"),
    "APU0000712112": ("Potatoes", 1, "lb"),
    "APU0000712211": ("Iceberg lettuce", 1, "lb"),
    "APU0000712311": ("Tomatoes", 1, "lb"),
    "APU0000701111": ("All-purpose flour", 1, "lb"),
    "APU0000701312": ("White rice", 1, "lb"),
    "APU0000715211": ("Granulated sugar", 1, "lb"),
    "APU0000717311": ("Ground coffee", 1, "lb"),
}
PRICE_REFRESH = {"running": False, "last": None, "done": {}, "errors": []}
_price_lock = threading.Lock()
_kroger_token = {"token": "", "until": 0.0}


def _pack_of(text):
    """'1 gal' -> (1, 'gallon'); '12 × 355 ml' -> (4260, 'ml'); '18 ct' -> (18, '')."""
    p = parse_pack(text or "")
    if not p:
        return None, None
    if p.get("each_qty") and p.get("each_unit") and p.get("count"):
        return p["count"] * p["each_qty"], p["each_unit"]
    return p["qty"], p["unit"] or ""


def _price_rec(source, price, qty, unit, observed_on, store="", url="", rid=None, note="", name=""):
    up, base = n_prices.unit_price(price, qty, unit, n_units.convert, n_units.dimension)
    return {"id": rid, "source": source, "price": price, "qty": qty, "unit": unit or "", "unit_price": up, "base": base,
            "observed_on": str(observed_on or "")[:10], "store": store or "", "url": url or "", "note": note or "", "name": name}


class PriceBook:
    """Every known price, loaded once per request: keyed by food id ("f:12") and by name key."""

    def __init__(self, c):
        self.by = {}
        for r in c.execute("SELECT * FROM prices"):
            self._add(r["food_id"], r["food_key"], _price_rec(r["source"], r["price"], r["qty"], r["unit"], r["observed_on"],
                                                             r["store"], r["url"], r["id"], r["note"], r["name"]))
        for r in c.execute("SELECT p.*, pi.original_qty AS pq, pi.unit AS pu, pi.quantity_text AS pqt FROM purchases p "
                           "LEFT JOIN pantry_items pi ON pi.id=p.pantry_item_id WHERE p.price>0 ORDER BY p.date DESC, p.id DESC"):
            qty, unit = r["qty"], r["unit"]
            if not qty:
                qty, unit = (r["pq"], r["pu"]) if r["pq"] else _pack_of(r["pqt"])
            self._add(r["food_id"], food_key(clean_food(r["name"])),
                      _price_rec("receipt", r["price"], qty, unit, r["date"], r["store_name"], name=r["name"]))

    def _add(self, fid, key, rec):
        if fid is not None:
            self.by.setdefault(f"f:{fid}", []).append(rec)
        if key and not (fid is not None and key == f"f:{fid}"):
            self.by.setdefault(key, []).append(rec)

    def records(self, key, name=""):
        out = list(self.by.get(key) or [])
        k = food_key(clean_food(name)) if name else ""
        if k and k != key:
            out += [r for r in self.by.get(k) or [] if not any(r is x for x in out)]
        return out


def _cost_line(book, key, food, qty, unit, t, to_buy=False):
    recs = book.records(key, food or "")
    fn = n_prices.cost_to_buy if to_buy else n_prices.cost_used
    return fn(qty, unit or "", recs, t, n_units.convert, n_units.dimension) if recs else None


def recipe_cost(c, rec, scale=1.0, book=None, stock=None, t=None):
    """What a recipe costs at `scale`: the amounts it uses (partial packages count only the part used), plus what you'd
    need to buy (whole packages, for what's not in the kitchen). Prices are never made up: unpriced foods are listed."""
    t = t or today()
    book = book or PriceBook(c)
    lines, unpriced, total, approx = [], [], 0.0, False
    for n in _recipe_needs(rec, scale, set(), c, create=False):
        if n["qty"] is None or not n["food"]:   # "to taste", "a pinch": too small to price
            continue
        r = _cost_line(book, n["key"], n["food"], n["qty"], n["unit"], t)
        if r is None:
            unpriced.append(n["food"])
            continue
        total += r["cost"]
        approx = approx or r["approx"]
        lines.append({"food": n["food"], "cost": n_prices.money(r["cost"]), "approx": r["approx"], "source": r["source"]})
    servings = float(rec.get("recipeServings") or 0) * float(scale or 1) or None
    out = {"total": n_prices.money(total), "per_serving": n_prices.money(total / servings) if servings and total else None,
           "servings": servings, "approx": approx or bool(unpriced), "unpriced": list(dict.fromkeys(unpriced)), "lines": lines}
    if stock is not None:
        chk = recipe_check(c, rec, stock, staple_keys(c), t, scale)
        out["to_buy"] = missing_cost(c, chk["missing"], book, t)
    return out


def missing_cost(c, missing, book, t):
    """Whole-package cost of the missing items (Almost there's "+$4.20", "Need to buy")."""
    total, approx, unpriced, lines = 0.0, False, [], []
    for m in missing:
        key = _ing_key(m.get("food") or "", c, create=False) if m.get("food") else ""
        r = _cost_line(book, key, m.get("food") or "", m.get("qty"), m.get("unit"), t, to_buy=True) if key else None
        if r is None:
            unpriced.append(m.get("food") or m.get("text"))
            continue
        total += r["cost"]
        approx = approx or r["approx"]
        lines.append({"food": m.get("food"), "cost": n_prices.money(r["cost"]), "packages": r["packages"], "approx": r["approx"]})
    return {"total": n_prices.money(total), "approx": approx or bool(unpriced), "unpriced": unpriced, "lines": lines}


def recipe_cost_api(slug, q):
    require_native()
    with db() as c:
        rec = n_recipes.get(c, slug)
        if not rec:
            raise ApiError(404, "Recipe not found")
        base = float(rec.get("recipeServings") or 0) or None
        want = _num(q.get("servings"))
        scale = (want / base) if (want and base) else 1.0
        return recipe_cost(c, rec, scale, stock=_make_stock(c, today()))


_cost_cache = {"at": 0.0, "key": None, "data": {}}


def recipe_costs_all():
    """{recipe id: {per_serving, total, approx}} for every recipe (cached briefly; used by the planner and picker)."""
    with db() as c:
        key = (c.execute("SELECT COUNT(*), MAX(id), MAX(observed_on) FROM prices").fetchone()[:],
               c.execute("SELECT COUNT(*), MAX(id) FROM purchases").fetchone()[:],
               c.execute("SELECT COUNT(*), MAX(updated_at) FROM recipes").fetchone()[:])
        if _cost_cache["key"] == key and time.time() - _cost_cache["at"] < 600:
            return _cost_cache["data"]
        book, out = PriceBook(c), {}
        for row in c.execute("SELECT id, data FROM recipes").fetchall():
            rc = recipe_cost(c, json.loads(row["data"]), 1.0, book)
            if rc["total"]:
                out[row["id"]] = {"per_serving": rc["per_serving"], "total": rc["total"], "approx": rc["approx"]}
    _cost_cache.update(at=time.time(), key=key, data=out)
    return out


def plan_cost(start, end):
    """GET /api/costs/plan: what the planned meals cost (amounts used) and per meal."""
    require_native()
    t = today()
    with db() as c:
        book = PriceBook(c)
        rows = c.execute("SELECT * FROM meal_plans WHERE date BETWEEN ? AND ? AND recipe_id IS NOT NULL AND skipped_at IS NULL "
                         "ORDER BY date", (iso(start), iso(end))).fetchall()
        per, total, approx, unpriced = [], 0.0, False, set()
        for e in rows:
            rec = n_recipes.get(c, e["recipe_id"])
            if not rec:
                continue
            rc = recipe_cost(c, rec, e["scale"] or 1, book, t=t)
            total += rc["total"]
            approx = approx or rc["approx"]
            unpriced.update(rc["unpriced"])
            per.append({"id": e["id"], "date": e["date"], "cost": rc["total"], "per_serving": rc["per_serving"], "approx": rc["approx"]})
    return {"total": n_prices.money(total), "approx": approx, "entries": per, "unpriced": sorted(unpriced),
            "start": iso(start), "end": iso(end)}


def _list_item_food(c, r):
    """The food on a list row: its parsed food, else its canonical food, else (for "milk") the text itself."""
    if r["food"]:
        return r["food"]
    if r["food_id"] is not None:
        f = n_foods.get(c, r["food_id"])
        if f:
            return f["name"]
    return (r["text"] or "").strip() if r["food_id"] is not None else ""


def list_costs():
    """GET /api/costs/list: each unchecked item at whole-package prices, totals per store, and how many have no price."""
    require_native()
    t = today()
    with db() as c:
        book = PriceBook(c)
        lid = n_lists.single_list(c)
        stores = {s["id"]: s["name"] for s in n_lists.list_stores(c)}
        items, per_store, total, approx, unpriced = {}, {}, 0.0, False, 0
        for r in c.execute("SELECT * FROM shopping_items WHERE list_id=? AND checked=0", (lid,)).fetchall():
            food = _list_item_food(c, r)
            if not food:
                unpriced += 1
                continue
            key = f"f:{r['food_id']}" if r["food_id"] is not None else food_key(clean_food(food))
            res = _cost_line(book, key, food, r["quantity"], r["unit"] or "", t, to_buy=True)
            if res is None:
                unpriced += 1
                items[r["id"]] = None
                continue
            cost = n_prices.money(res["cost"])
            items[r["id"]] = {"cost": cost, "approx": res["approx"], "packages": res["packages"], "source": res["source"]}
            sid = r["store_id"] if r["store_id"] in stores else None
            st = per_store.setdefault(sid, {"id": sid, "name": stores.get(sid) or ANY_STORE, "total": 0.0, "approx": False})
            st["total"] = n_prices.money(st["total"] + cost)
            st["approx"] = st["approx"] or res["approx"]
            total += cost
            approx = approx or res["approx"]
    order = list(stores) + [None]
    return {"items": items, "stores": sorted(per_store.values(), key=lambda s: order.index(s["id"]) if s["id"] in order else 99),
            "total": n_prices.money(total), "approx": approx, "unpriced": unpriced}


# ---- the budget

def _household_tz():
    name = (get_settings().get("budget") or {}).get("timezone") or os.environ.get("TZ") or ""
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


def budget_today():
    return n_prices.local_today(datetime.now(timezone.utc), _household_tz())


def spent_between(c, start, end, store_id=None):
    """Money spent on grocery trips in [start, end]: the trip total when known, else the priced items on it."""
    q = "SELECT t.id, t.total, t.store_id, (SELECT SUM(price) FROM purchases p WHERE p.trip_id=t.id) AS items " \
        "FROM trips t WHERE t.date BETWEEN ? AND ? AND t.status='done'"
    args = [iso(start), iso(end)]
    if store_id is not None:
        q += " AND t.store_id=?"
        args.append(store_id)
    return n_prices.money(sum((r["total"] if r["total"] else (r["items"] or 0)) for r in c.execute(q, args)))


def budget_status(day=None):
    """GET /api/budget: this period's goal, what's spent, and the warning level (80% / 100%)."""
    b = get_settings().get("budget") or {}
    amount = float(b.get("amount") or 0)
    kind = b.get("period") or "week"
    day = day or budget_today()
    start, end = n_prices.period_bounds(kind, day, b.get("week_start") or "mon")
    out = {"period": kind, "start": iso(start), "end": iso(end), "amount": amount, "on": amount > 0}
    with db() as c:
        spent = spent_between(c, start, end)
        stores = {s["id"]: s["name"] for s in n_lists.list_stores(c)} if NATIVE else {}
        per = []
        for sid, amt in (b.get("stores") or {}).items():
            if sid in stores and float(amt or 0) > 0:
                s_spent = spent_between(c, start, end, sid)
                per.append({"id": sid, "name": stores[sid], "amount": float(amt), "spent": s_spent,
                            "level": n_prices.budget_level(s_spent, float(amt))})
    out.update(spent=spent, left=n_prices.money(amount - spent) if amount else None, level=n_prices.budget_level(spent, amount),
               stores=per, days_left=(end - day).days + 1)
    if NATIVE and amount:
        try:
            pc = plan_cost(max(day, start), end)
            out["planned"] = pc["total"]
            out["planned_approx"] = pc["approx"]
        except ApiError:
            pass
    return out


def notify_budget():
    """Once per period and level: "80% of this week's grocery budget"."""
    st = budget_status()
    if not st["on"] or not st["level"] or not any(channels_ready().values()):
        return
    flag = f"budget_{st['start']}_{st['level']}"
    if get_internal(flag):
        return
    set_internal(flag, True)
    pct = 100 if st["level"] == "over" else 80
    word = "week" if st["period"] == "week" else "month"
    deliver({"subject": f"🛒 Groceries at {pct}% of this {word}'s budget",
             "text": f"${st['spent']:.2f} of your ${st['amount']:.2f} {word}ly grocery budget spent.",
             "html": email_wrap(f"<p>${st['spent']:.2f} of your ${st['amount']:.2f} {word}ly grocery budget spent.</p>"), "files": []})


# ---- the spending page

def _food_category(c, food_id, name):
    if food_id is not None:
        f = n_foods.get(c, food_id)
        if f and f.get("category"):
            return f["category"]
    return aisle_for(name) or "Other"


def spending(q):
    """GET /api/spending?by=week|month&n=8: totals per period, by store and category, waste, cost per meal."""
    require_native()
    by = "month" if q.get("by") == "month" else "week"
    n = max(1, min(24, int(_num(q.get("n")) or 8)))
    b = get_settings().get("budget") or {}
    periods = n_prices.previous_periods(by, budget_today(), n, b.get("week_start") or "mon")
    start, end = periods[0][0], periods[-1][1]
    t = today()
    with db() as c:
        book = PriceBook(c)
        rows = []
        for s, e in periods:
            spent = spent_between(c, s, e)
            meals = c.execute("SELECT COUNT(*) FROM diary WHERE kind='cooked' AND substr(cooked_at,1,10) BETWEEN ? AND ?",
                              (iso(s), iso(e))).fetchone()[0]
            rows.append({"start": iso(s), "end": iso(e), "spent": spent, "meals": meals,
                         "per_meal": n_prices.money(spent / meals) if meals and spent else None})
        stores = {}
        for r in c.execute("SELECT t.store_name, t.total, (SELECT SUM(price) FROM purchases p WHERE p.trip_id=t.id) AS items "
                           "FROM trips t WHERE t.date BETWEEN ? AND ? AND t.status='done'", (iso(start), iso(end))):
            nm = r["store_name"] or "Other"
            stores[nm] = n_prices.money(stores.get(nm, 0) + (r["total"] or r["items"] or 0))
        cats = {}
        for r in c.execute("SELECT food_id, name, price FROM purchases WHERE price>0 AND date BETWEEN ? AND ?", (iso(start), iso(end))):
            k = _food_category(c, r["food_id"], r["name"])
            cats[k] = n_prices.money(cats.get(k, 0) + r["price"])
        waste, waste_items, waste_approx = 0.0, [], False
        for r in c.execute("SELECT pi.*, (SELECT price FROM purchases p WHERE p.pantry_item_id=pi.id AND p.price>0 LIMIT 1) AS paid "
                           "FROM pantry_items pi WHERE pi.status='tossed' AND pi.finished_on BETWEEN ? AND ?", (iso(start), iso(end))):
            key = f"f:{r['food_id']}" if r["food_id"] is not None else food_key(clean_food(r["name"]))
            v, ap = n_prices.waste_value(r["amount_left"], r["paid"], book.records(key, r["name"]), r["original_qty"] or r["qty"],
                                         r["unit"] or "", t, n_units.convert, n_units.dimension)
            if v:
                waste += v
                waste_approx = waste_approx or ap
                waste_items.append({"name": r["name"], "value": n_prices.money(v), "approx": ap, "date": r["finished_on"]})
    total = n_prices.money(sum(r["spent"] for r in rows))
    meals = sum(r["meals"] for r in rows)
    return {"by": by, "periods": rows, "total": total, "meals": meals, "per_meal": n_prices.money(total / meals) if meals and total else None,
            "stores": sorted(({"name": k, "total": v} for k, v in stores.items()), key=lambda x: -x["total"]),
            "categories": sorted(({"name": k, "total": v} for k, v in cats.items()), key=lambda x: -x["total"]),
            "waste": {"total": n_prices.money(waste), "approx": waste_approx, "items": sorted(waste_items, key=lambda x: -x["value"])[:20]},
            "budget": budget_status()}


# ---- price sources

def _save_price(c, source, food, price, qty, unit, store="", url="", note="", observed=None, replace=True):
    """Store one price for a food (one per source and store unless replace=False)."""
    fid = n_foods.lookup(c, food) if food and n_foods.normalize(food) else None
    key = f"f:{fid}" if fid is not None else food_key(clean_food(food))
    if not key:
        raise ApiError(400, "Which food?")
    if replace:
        c.execute("DELETE FROM prices WHERE source=? AND food_key=? AND store=?", (source, key, store or ""))
    up, base = n_prices.unit_price(price, qty, unit, n_units.convert, n_units.dimension)
    if not up:
        raise ApiError(400, "That price or size couldn't be read.")
    cur = c.execute("INSERT INTO prices(food_id, food_key, name, source, store, price, qty, unit, unit_price, base, url, note, "
                    "observed_on, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (fid, key, food, source, store or "", float(price), qty, unit or "", up, base, url or "", note or "",
                     iso(observed or today()), datetime.now().isoformat(timespec="seconds")))
    return cur.lastrowid


def price_set(b):
    """POST /api/prices {food, price, size?, store?}: a price you know (beats everything but your receipts)."""
    require_native()
    food = " ".join(_s(b.get("food"), 80).split())
    price = n_prices.parse_money(_s(b.get("price"), 30)) if isinstance(b.get("price"), str) else _num(b.get("price"))
    if not food or not price:
        raise ApiError(400, "Give the food and its price.")
    if price > 10_000:
        raise ApiError(400, "That price looks too high.")
    qty, unit = _pack_of(_s(b.get("size"), 40)) if b.get("size") else (1, "")
    with db() as c:
        pid = _save_price(c, "manual", food, price, qty or 1, unit or "", _s(b.get("store"), 40))
    _cost_cache["at"] = 0
    return {"ok": True, "id": pid}


def price_delete(pid):
    require_native()
    with db() as c:
        c.execute("DELETE FROM prices WHERE id=?", (pid,))
    _cost_cache["at"] = 0
    return {"ok": True}


def _kroger_auth():
    cid, sec = cfg("kroger_client_id"), cfg("kroger_client_secret")
    if not (cid and sec):
        raise ApiError(400, "Add your Kroger API client ID and secret first.")
    if _kroger_token["token"] and time.time() < _kroger_token["until"] - 60:
        return _kroger_token["token"]
    basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    res = _https_json(f"{KROGER_API}/connect/oauth2/token", data=b"grant_type=client_credentials&scope=product.compact",
                      ctype="application/x-www-form-urlencoded", headers={"Authorization": f"Basic {basic}"}, method="POST")
    tok = res.get("access_token")
    if not tok:
        raise ApiError(502, "Kroger didn't accept those credentials.")
    _kroger_token.update(token=tok, until=time.time() + float(res.get("expires_in") or 1800))
    return tok


def kroger_locations(zip_code):
    """Stores near a ZIP code, for the store picker."""
    z = re.sub(r"\D", "", zip_code or "")[:5]
    if len(z) != 5:
        raise ApiError(400, "Enter a 5-digit ZIP code.")
    tok = _kroger_auth()
    res = _https_json(f"{KROGER_API}/locations?" + urllib.parse.urlencode({"filter.zipCode.near": z, "filter.limit": 10}),
                      headers={"Authorization": f"Bearer {tok}"})
    out = []
    for l in res.get("data") or []:
        a = l.get("address") or {}
        out.append({"id": l.get("locationId"), "name": f"{l.get('chain') or ''} {l.get('name') or ''}".strip(),
                    "address": ", ".join(x for x in (a.get("addressLine1"), a.get("city")) if x)})
    return {"locations": out}


def kroger_price(food):
    """The first matching product with a price at the chosen store -> (price, qty, unit, url, product name) or None."""
    loc = cfg("kroger_location_id")
    if not loc:
        return None
    tok = _kroger_auth()
    res = _https_json(f"{KROGER_API}/products?" + urllib.parse.urlencode(
        {"filter.term": food[:60], "filter.locationId": loc, "filter.limit": 8}), headers={"Authorization": f"Bearer {tok}"})
    for p in res.get("data") or []:
        for it in p.get("items") or []:
            pr = it.get("price") or {}
            price = pr.get("promo") or pr.get("regular")
            qty, unit = _pack_of(it.get("size") or "")
            if price and float(price) > 0 and qty:
                return (float(price), qty, unit, f"https://www.kroger.com/p/-/{p.get('productId')}" if p.get("productId") else "",
                        p.get("description") or "")
    return None


AI_PRICE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["price", "size", "url", "store"],
                   "properties": {"price": {"type": "string"}, "size": {"type": "string"}, "url": {"type": "string"},
                                  "store": {"type": "string"}}}


def ai_price(food, store=""):
    """A web-search estimate. Kept only when the page was really cited and both price and size can be read."""
    where = f" at {store}" if store else " at a large US supermarket chain"
    prompt = (f"Find the current shelf price of one typical package of {food}{where}, from a store's own product page. "
              "price = the price as shown (e.g. '$3.49'); size = the package size as shown (e.g. '1 gal', '16 oz'); "
              "url = that product page (one of your sources); store = the store's name. If you can't find a real listing, "
              "leave every field empty. Never estimate.")
    key, model = cfg("openai_key"), cfg("openai_model") or "gpt-5-mini"
    if not key or _ai_over_budget():
        return None
    payload = {"model": model, "input": prompt, "tools": [{"type": "web_search"}],
               "text": {"format": {"type": "json_schema", "name": "price", "strict": True, "schema": AI_PRICE_SCHEMA}}}
    if re.match(r"^(gpt-5|o[134])", model):
        payload["reasoning"] = {"effort": "low"}
    res = _https_json("https://api.openai.com/v1/responses", payload=payload, headers={"Authorization": f"Bearer {key}"}, timeout=180)
    u = res.get("usage") or {}
    log_ai("price estimate", res.get("model") or model, u.get("input_tokens"), u.get("output_tokens"), food[:60])
    return _ai_price_result(res)


def _ai_price_result(res):
    text, cited = "", set()
    for item in res.get("output") or []:
        for part in (item.get("content") or []) if item.get("type") == "message" else []:
            if part.get("type") == "output_text":
                text += part.get("text") or ""
                cited |= {_url_norm(a.get("url")) for a in part.get("annotations") or [] if a.get("type") == "url_citation"}
    try:
        d = json.loads(text or "{}")
    except ValueError:
        return None
    url = (d.get("url") or "").strip()
    price = n_prices.parse_money(d.get("price"))
    qty, unit = _pack_of(d.get("size") or "")
    if not (url.startswith("https://") and _url_norm(url) in cited and price and qty):
        return None   # no cited page, or no price/size we can read: nothing is kept
    return price, qty, unit, url, " ".join(str(d.get("store") or "").split())[:40]


def bls_refresh():
    """Monthly US average prices from the Bureau of Labor Statistics (fallback estimates)."""
    body = {"seriesid": list(BLS_SERIES), "latest": True}
    if cfg("bls_key"):
        body["registrationkey"] = cfg("bls_key")
    res = _https_json(BLS_API, payload=body, timeout=40)
    n = 0
    with db() as c:
        for s in (res.get("Results") or {}).get("series") or []:
            meta = BLS_SERIES.get(s.get("seriesID"))
            data = s.get("data") or []
            if not meta or not data:
                continue
            row = data[0]
            try:
                price = float(row.get("value"))
            except (TypeError, ValueError):
                continue
            month = re.sub(r"\D", "", row.get("period") or "")
            observed = date(int(row.get("year")), int(month or 1), 1) if (row.get("year") or "").isdigit() else today()
            food, qty, unit = meta
            _save_price(c, "bls", food, price, qty, unit, url=f"https://data.bls.gov/timeseries/{s['seriesID']}",
                        note=f"US city average, {row.get('periodName') or ''} {row.get('year') or ''}".strip(), observed=observed)
            n += 1
    if n:
        set_internal("prices_bls_at", datetime.now().isoformat(timespec="seconds"))
    return n


def _price_targets(c):
    """Foods worth pricing, most useful first: the list, the next week's plan, then what's bought often."""
    t = today()
    out = []
    lid = n_lists.single_list(c)
    for r in c.execute("SELECT * FROM shopping_items WHERE list_id=? AND checked=0", (lid,)).fetchall():
        nm = _list_item_food(c, r)
        if nm:
            out.append(nm)
    skeys = staple_keys(c)
    for e in c.execute("SELECT recipe_id FROM meal_plans WHERE date BETWEEN ? AND ? AND recipe_id IS NOT NULL AND cooked_at IS NULL",
                       (iso(t), iso(t + timedelta(days=7)))).fetchall():
        rec = n_recipes.get(c, e["recipe_id"])
        if rec:
            out += [n["food"] for n in _recipe_needs(rec, 1, skeys, c, create=False) if n["food"]]
    for r in c.execute("SELECT name, COUNT(*) n FROM purchases WHERE date>=? GROUP BY food_id, name HAVING n>=2 ORDER BY n DESC LIMIT 40",
                       (iso(t - timedelta(days=90)),)):
        out.append(r["name"])
    seen, uniq = set(), []
    for f in out:
        k = food_key(clean_food(f))
        if k and k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


def prices_refresh(force=False, ai_limit=5, kroger_limit=25):
    """Bring prices up to date: BLS monthly, Kroger weekly per food, AI estimates at most monthly per food."""
    if not NATIVE or not _price_lock.acquire(blocking=False):
        return PRICE_REFRESH
    PRICE_REFRESH.update(running=True, errors=[], done={})
    try:
        t = today()
        last_bls = parse_date((get_internal("prices_bls_at") or "")[:10])
        if force or not last_bls or (t - last_bls).days >= 30:
            try:
                PRICE_REFRESH["done"]["bls"] = bls_refresh()
            except ApiError as e:
                PRICE_REFRESH["errors"].append(f"US averages: {e.message}")
        with db() as c:
            targets = _price_targets(c)
            book = PriceBook(c)
        kn = an = 0
        for food in targets:
            key = food_key(clean_food(food))
            recs = book.records(key, food)
            have = {r["source"]: r for r in recs}
            if cfg("kroger_location_id") and kn < kroger_limit:
                k = have.get("kroger")
                if force or not k or n_prices.is_stale(k, t) or (t - date.fromisoformat(k["observed_on"])).days >= 7:
                    kn += 1
                    try:
                        got = kroger_price(food)
                        if got:
                            with db() as c:
                                _save_price(c, "kroger", food, got[0], got[1], got[2], cfg("kroger_location_name") or "Kroger", got[3], got[4])
                    except ApiError as e:
                        PRICE_REFRESH["errors"].append(f"Kroger: {e.message}")
                        kn = kroger_limit
            if get_settings().get("price_ai") and cfg("openai_key") and an < ai_limit:
                fresh = [r for r in recs if r["source"] in ("receipt", "manual", "kroger") and not n_prices.is_stale(r, t)]
                a = have.get("ai")
                if not fresh and (not a or (t - date.fromisoformat(a["observed_on"])).days >= 30):
                    an += 1
                    try:
                        got = ai_price(food)
                        if got:
                            with db() as c:
                                _save_price(c, "ai", food, got[0], got[1], got[2], got[4], got[3])
                    except ApiError as e:
                        PRICE_REFRESH["errors"].append(f"Web estimate: {e.message}")
                        an = ai_limit
        PRICE_REFRESH["done"].update(kroger=kn, ai=an, foods=len(targets))
        PRICE_REFRESH["last"] = datetime.now().isoformat(timespec="seconds")
        set_internal("prices_refresh_at", PRICE_REFRESH["last"])
        _cost_cache["at"] = 0
    finally:
        PRICE_REFRESH["running"] = False
        _price_lock.release()
    return PRICE_REFRESH


def prices_overview():
    """GET /api/prices: the sources, when they were refreshed, and every food's best price."""
    require_native()
    t = today()
    with db() as c:
        book = PriceBook(c)
        counts = {s: 0 for s in n_prices.SOURCES}
        foods = {}
        seen = set()
        for key, recs in book.by.items():
            for r in recs:
                if id(r) in seen:
                    continue
                seen.add(id(r))
                counts[r["source"]] += 1
            label = next((r.get("name") for r in recs if r.get("name")), "")
            if key.startswith("f:"):
                f = n_foods.get(c, int(key[2:]))
                label = (f or {}).get("name") or label
            if not label:
                continue
            b = n_prices.best(recs, t)
            if b:
                foods.setdefault(label.lower(), {"food": label, "best": {**b, "approx": n_prices.approx(b, t), "label": n_prices.LABEL[b["source"]],
                                                                         "stale": n_prices.is_stale(b, t)},
                                                 "sources": sorted({r["source"] for r in recs}, key=n_prices.RANK.get)})
    s = get_settings()
    return {"sources": [{"key": k, "label": n_prices.LABEL[k], "count": counts[k], "estimate": k in n_prices.ESTIMATE_SOURCES} for k in n_prices.SOURCES],
            "foods": sorted(foods.values(), key=lambda x: x["food"].lower()),
            "kroger": {"connected": bool(cfg("kroger_client_id") and cfg("kroger_client_secret")), "location": cfg("kroger_location_name") or "",
                       "location_id": cfg("kroger_location_id") or ""},
            "ai": {"on": bool(s.get("price_ai")), "key": bool(cfg("openai_key"))},
            "bls": {"at": get_internal("prices_bls_at"), "key": bool(cfg("bls_key"))},
            "refresh": {k: PRICE_REFRESH[k] for k in ("running", "done", "errors")} | {"last": get_internal("prices_refresh_at")}}


def prices_config(b):
    """PUT /api/prices/config: Kroger credentials and store, BLS key."""
    require_native()
    up = {}
    for k in ("kroger_client_id", "kroger_client_secret", "bls_key"):
        if k in b:
            up[k] = _s(b.get(k), 200).strip()
    if "location_id" in b:
        up["kroger_location_id"] = _s(b.get("location_id"), 40).strip()
        up["kroger_location_name"] = _s(b.get("location_name"), 80).strip()
    if up:
        set_cfg(**up)
        _kroger_token.update(token="", until=0)
    return prices_overview()


# ============================================================ what can I make?

MAKE_EXPIRING_DAYS = 3   # "Use it up": expiring within this many days
MAKE_PLANNED_DAYS = 3    # recipes planned this soon are left out


def _make_stock(c, t, include_id=None):
    """{key: [{row, free}]}: active, unexpired inventory, soonest-expiring first; free = amount not reserved for a plan.
    include_id: one item to count even if it's past its date or waiting for review (Find recipes for that food)."""
    reserved = {r[0]: r[1] for r in c.execute(
        "SELECT pantry_item_id, SUM(qty) FROM allocations WHERE qty IS NOT NULL GROUP BY pantry_item_id")}
    stock = {}
    for r in c.execute("SELECT * FROM pantry_items WHERE status='active' AND (id=? OR (COALESCE(review,0)=0 "
                       "AND (expires_on IS NULL OR expires_on>=?))) "
                       "ORDER BY CASE WHEN expires_on IS NULL THEN 1 ELSE 0 END, expires_on, id", (include_id or -1, iso(t))):
        if r["qty"] is not None and r["qty"] <= 0:
            continue
        free = None if r["qty"] is None else max(0.0, r["qty"] - (reserved.get(r["id"]) or 0))
        keys = {food_key(clean_food(r["name"])), food_key(r["name"])}
        if r["food_id"] is not None:
            keys.add(f"f:{r['food_id']}")
        ent = {"row": r, "free": free}
        for k in keys:
            if k:
                stock.setdefault(k, []).append(ent)
    return stock


def _make_need_text(n):
    if n["food"] and n["qty"]:
        return n_units.fmt(n["qty"], n["unit"] or "", n["food"])
    if n["food"]:
        return n["food"]
    return n["line"]


def recipe_check(c, rec, stock, skeys, t, scale=1):
    """One recipe against the inventory: what's missing (or short) and which expiring foods it would use."""
    needs = _recipe_needs(rec, scale, skeys, c, create=False)
    groups = {}
    for n in needs:
        groups.setdefault(n["key"], []).append(n)
    soon = iso(t + timedelta(days=MAKE_EXPIRING_DAYS))
    missing, expiring, seen, uses = [], [], set(), set()
    for k, ns in groups.items():
        ents = stock.get(k) or []
        if not ents and (ns[0]["food"] or "").strip():
            alt = food_key(clean_food(ns[0]["food"]))
            ents = stock.get(alt) or []
        if not ents:
            missing.append({"food": ns[0]["food"] or ns[0]["line"], "text": _make_need_text(ns[0]), "short": False,
                            "qty": ns[0]["qty"], "unit": ns[0]["unit"]})
            continue
        uses.update(e["row"]["id"] for e in ents)
        first = ns[0]
        qty = None
        if all(n["qty"] is not None for n in ns):
            conv = [n_units.convert(n["qty"], n["unit"], first["unit"]) for n in ns]
            qty = sum(conv) if all(v is not None for v in conv) else None
        if not n_whatcan.enough(qty, first["unit"], [(e["free"], e["row"]["unit"] or "") for e in ents], n_units.convert):
            missing.append({"food": first["food"], "text": _make_need_text({**first, "qty": qty}), "short": True,
                            "have": pantry_left_text(ents[0]["row"]), "qty": qty, "unit": first["unit"]})
        for e in ents:
            r = e["row"]
            if r["expires_on"] and r["expires_on"] <= soon and r["id"] not in seen:
                seen.add(r["id"])
                d = (parse_date(r["expires_on"]) - t).days
                expiring.append({"id": r["id"], "name": r["name"], "days_left": d})
                break
    expiring.sort(key=lambda x: x["days_left"])
    return {"missing": missing, "expiring": expiring, "need_n": len(groups), "uses": sorted(uses)}


def what_can_i_make(food=None):
    """GET /api/make[?food=<inventory id>]: Make right now / Almost there / Use it up.
    With food, Use it up is the recipes that use that one item (at most 3 other things missing), and focus is the item."""
    require_native()
    t = today()
    pool = {r["id"]: r for r in recipe_pool()}
    focus = None
    with db() as c:
        if food is not None:
            row = pantry_row(c, _int_id(food, "item"))
            if not row or row["status"] != "active":
                raise ApiError(404, "That item isn't in your inventory any more.")
            focus = pantry_json(c, row)
        skeys = staple_keys(c)
        stock = _make_stock(c, t, focus["id"] if focus else None)
        planned = {r[0] for r in c.execute(
            "SELECT DISTINCT recipe_id FROM meal_plans WHERE recipe_id IS NOT NULL AND cooked_at IS NULL AND skipped_at IS NULL "
            "AND date BETWEEN ? AND ?", (iso(t), iso(t + timedelta(days=MAKE_PLANNED_DAYS))))}
        cands = []
        for rid, p in pool.items():
            rec = n_recipes.get(c, rid)
            if not rec:
                continue
            chk = recipe_check(c, rec, stock, skeys, t)
            cands.append({"id": rid, "slug": p["slug"], "name": p["name"], "has_image": p["has_image"], "image_v": p["image_v"],
                          "rating": p.get("rating") or 0, "minutes": p.get("eta_min") or p.get("minutes"),
                          "planned_soon": rid in planned, **chk})
        soon = iso(t + timedelta(days=MAKE_EXPIRING_DAYS))
        exp = [pantry_json(c, r) for r in c.execute(
            "SELECT * FROM pantry_items WHERE status='active' AND expires_on IS NOT NULL AND expires_on>=? AND expires_on<=? "
            "ORDER BY expires_on", (iso(t), soon))]
    out = n_whatcan.buckets(cands)
    if focus:
        out["use_up"] = sorted((r for r in cands if focus["id"] in r["uses"] and len(r["missing"]) <= n_whatcan.ALMOST_MAX),
                               key=lambda r: (len(r["missing"]), r.get("planned_soon", False)) + n_whatcan.rank_key(r)[1:])[:60]
        out["focus"] = focus
    with db() as c:
        book = PriceBook(c)
        for r in out["almost"] + [x for x in out["use_up"] if x["missing"]]:
            if "to_buy" not in r:
                r["to_buy"] = missing_cost(c, r["missing"], book, t)
    out["expiring"] = exp
    out["planned_skipped"] = sum(1 for x in cands if x["planned_soon"])
    out["recipes"] = len(cands)
    return out


# ---- web suggestions: AI web search, then every link is opened and must be a real recipe page
WEB_SUGGEST_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["recipes"],
                      "properties": {"recipes": {"type": "array", "items": {
                          "type": "object", "additionalProperties": False, "required": ["title", "url"],
                          "properties": {"title": {"type": "string"}, "url": {"type": "string"}}}}}}


def _responses_web_search(prompt, feature, detail=""):
    """OpenAI Responses API with web search. Returns (parsed JSON, set of cited URLs)."""
    key, model = cfg("openai_key"), cfg("openai_model") or "gpt-5-mini"
    if not key:
        raise ApiError(400, "Web suggestions need AI. Add your OpenAI key in Settings → AI recipe import.")
    if _ai_over_budget():
        raise ApiError(402, "This month's AI budget is used up. Raise it in Settings → AI spending.")
    payload = {"model": model, "input": prompt, "tools": [{"type": "web_search"}],
               "text": {"format": {"type": "json_schema", "name": "suggestions", "strict": True, "schema": WEB_SUGGEST_SCHEMA}}}
    if re.match(r"^(gpt-5|o[134])", model):
        payload["reasoning"] = {"effort": "low"}
    res = _https_json("https://api.openai.com/v1/responses", payload=payload, headers={"Authorization": f"Bearer {key}"}, timeout=180)
    u = res.get("usage") or {}
    log_ai(feature, res.get("model") or model, u.get("input_tokens"), u.get("output_tokens"), detail)
    text, cited = "", set()
    for item in res.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text":
                text += part.get("text") or ""
                for a in part.get("annotations") or []:
                    if a.get("type") == "url_citation" and a.get("url"):
                        cited.add(_url_norm(a["url"]))
    try:
        return json.loads(text or "{}"), cited
    except ValueError:
        raise AIUnreadable("web search")


def _url_norm(u):
    """Compare links without tracking junk: scheme-less, no fragment, no utm_* parameters, no trailing slash."""
    try:
        p = urllib.parse.urlsplit((u or "").strip())
    except ValueError:
        return ""
    q = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not k.lower().startswith("utm_")])
    return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}" + (f"?{q}" if q else "")


def make_web_suggestions(b):
    """POST /api/make/web {foods?}: recipes on the web that use what's expiring. Only links the search actually cited,
    that open, and that hold a real recipe are shown; what each one uses is read from its own ingredient list."""
    require_native()
    t = today()
    with db() as c:
        skeys = staple_keys(c)
        stock = _make_stock(c, t)
        soon = iso(t + timedelta(days=MAKE_EXPIRING_DAYS))
        foods = [" ".join(_s(x, 60).split()) for x in (b.get("foods") or []) if isinstance(x, str)][:6]
        if not foods:
            foods = [r["name"] for r in c.execute(
                "SELECT name FROM pantry_items WHERE status='active' AND expires_on BETWEEN ? AND ? ORDER BY expires_on LIMIT 5",
                (iso(t), soon))]
        have = [r["name"] for r in c.execute("SELECT DISTINCT name FROM pantry_items WHERE status='active' LIMIT 40")]
        known = {_url_norm(r["data"] and json.loads(r["data"]).get("orgURL") or "") for r in c.execute("SELECT data FROM recipes")}
    if not foods:
        raise ApiError(400, "Nothing is expiring soon. Pick a food to use up.")
    prompt = ("Find up to 6 well-reviewed home-cooking recipes on the web that use these foods, which need using up soon: "
              + ", ".join(foods) + ". The kitchen also has: " + ", ".join(have[:30]) + ". Prefer recipes that need few other "
              "ingredients. Only give recipe pages you actually found in the search (each url must be one of your sources); "
              "no videos, no roundups or list articles. title = the recipe's name as written on the page.")
    data, cited = _responses_web_search(prompt, "make suggestions", ", ".join(foods)[:80])
    picks, seen = [], set()
    for x in data.get("recipes") or []:
        url = (x.get("url") or "").strip() if isinstance(x, dict) else ""
        n = _url_norm(url)
        if n and n not in seen:
            seen.add(n)
            picks.append(url)
    deny = idea_denylist()
    out = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        found = [r for r in ex.map(lambda u: _verify_web(u, cited, known, deny), picks[:8]) if r]
    with db() as c:
        for url, rec in found:
            rec = {**rec, "recipeIngredient": [{"note": x} if isinstance(x, str) else x for x in rec.get("recipeIngredient") or []]}
            chk = recipe_check(c, rec, stock, skeys, t)
            out.append({"title": rec.get("name") or "", "url": url, "site": urllib.parse.urlsplit(url).netloc.removeprefix("www."),
                        "image_url": rec.get("image_url") or "", "minutes": recipe_minutes(rec),
                        "uses": [e["name"] for e in chk["expiring"]], "missing": [m["text"] for m in chk["missing"]][:8],
                        "missing_n": len(chk["missing"]), "need_n": chk["need_n"]})
    out.sort(key=lambda r: (-len(r["uses"]), r["missing_n"]))
    return {"foods": foods, "suggestions": out[:6], "checked": len(picks)}


# ============================================================ recipe export, print and share

PRINT_SIZES = {   # page size, sheet inches, margin, base font pt, minimum font pt, two columns, title pt
    # Cut-out cards: printed on US Letter with dashed cut lines; w x h is the card, `per` cards per page.
    "card35": {"card": True, "w": 5.0, "h": 3.0, "per": 3, "font": 8.5, "min": 8, "title": 11},
    "card46": {"card": True, "w": 6.0, "h": 4.0, "per": 2, "font": 9.5, "min": 8, "title": 13},
    "card57": {"card": True, "w": 7.0, "h": 5.0, "per": 2, "font": 10, "min": 8, "title": 15},
    "half": {"card": True, "w": 8.0, "h": 5.25, "per": 2, "font": 10, "min": 8, "title": 16},   # Letter halves inside 0.25in margins
    # Whole pages
    "letter": {"page": "letter", "w": 8.5, "h": 11.0, "m": 0.6, "font": 11.5, "min": 9, "cols": True, "title": 24},
    "a4": {"page": "A4", "w": 8.27, "h": 11.69, "m": 0.6, "font": 11.5, "min": 9, "cols": True, "title": 24},
}
CARD_PAGE_MARGIN = 0.25   # inches, on Letter
CARD_PAD = 0.15


def _servings_arg(v):
    if v in (None, ""):
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise ApiError(400, "Servings must be a number.")
    if not 0 < n <= 500:
        raise ApiError(400, "Servings must be between 0 and 500.")
    return n


def _slug_arg(v):
    v = _s(v, 200)
    if not SLUG_RE.fullmatch(v or ""):
        raise ApiError(400, "Bad recipe.")
    return urllib.parse.unquote(v)


def _scaled_line(g, f):
    if f != 1 and g.get("parsed") and g.get("quantity"):
        q = g["quantity"] * f
        unit = (g.get("unit_plural") if q > 1 and g.get("unit_plural") else g.get("unit")) or ""
        size = f"({g['size']}) " if g.get("size") else ""
        food = (g.get("food_plural") if q > 1 and g.get("food_plural") else "") or g.get("food") or ""
        out = " ".join(x for x in (nice_qty(q), (size + unit).strip(), food) if x)
        return out + (f", {g['note']}" if g.get("note") else "")
    return g.get("raw") or g.get("display") or g.get("food") or ""


def recipe_export(slug, servings=None):
    """Recipe detail plus ingredient lines scaled to `servings` (local parsed quantities, like the recipe page)."""
    rec = recipe_detail(slug)
    base = rec["servings"] or 0
    f = (servings / base) if (servings and base) else 1.0
    lines = [{"section": g["section"], "text": _scaled_line(g, f), "i": g["i"]} for g in rec["ingredients"]]
    return rec, lines, f, (servings or base or None)


def _meta_line(rec, servings):
    bits = []
    if servings:
        bits.append(f"Serves {nice_qty(servings)}")
    if rec.get("minutes"):
        bits.append(f"{rec['minutes']} min")
    return " · ".join(bits)


def render_recipe_text(slug, servings=None):
    rec, lines, _, sv = recipe_export(slug, servings)
    out = [rec["name"] or "Recipe"]
    meta = _meta_line(rec, sv)
    if meta:
        out.append(meta)
    if rec.get("description"):
        out += ["", rec["description"]]
    out += ["", "INGREDIENTS"]
    for ln in lines:
        if ln["section"]:
            out.append(f"{ln['section']}:")
        out.append(f"- {ln['text']}")
    out += ["", "STEPS"]
    out += [f"{j}. " + (f"{st['title']}: " if st["title"] else "") + st["text"] for j, st in enumerate(rec["steps"], 1)]
    if rec.get("source_url"):
        out += ["", f"Source: {rec['source_url']}"]
    out += ["", "Made with TablePlan"]
    return "\n".join(out) + "\n"


def render_recipe_md(slug, servings=None):
    rec, lines, _, sv = recipe_export(slug, servings)
    md = lambda t: re.sub(r"([\\`*_\[\]<>#|])", r"\\\1", str(t or ""))  # noqa: E731
    out = [f"# {md(rec['name'] or 'Recipe')}", ""]
    meta = _meta_line(rec, sv)
    if meta:
        out += [f"*{md(meta)}*", ""]
    if rec.get("description"):
        out += [md(rec["description"]), ""]
    out += ["## Ingredients", ""]
    for ln in lines:
        if ln["section"]:
            out += ([""] if out[-1] else []) + [f"### {md(ln['section'])}", ""]
        out.append(f"- {md(ln['text'])}")
    out += ["", "## Steps", ""]
    out += [f"{j}. " + (f"**{md(st['title'])}** " if st["title"] else "") + md(st["text"]) for j, st in enumerate(rec["steps"], 1)]
    if rec.get("source_url"):
        out += ["", f"Source: <{rec['source_url']}>" if re.match(r"^https?://\S+$", rec["source_url"]) else f"Source: {md(rec['source_url'])}"]
    out += ["", "*Made with TablePlan*"]
    return "\n".join(out) + "\n"


def render_recipe_json(slug, servings=None):
    """The stored (Mealie-shaped) recipe; with servings, quantities and lines are scaled to match."""
    raw = mealie("GET", f"/api/recipes/{_q(slug)}")
    rec, lines, f, sv = recipe_export(slug, servings)
    out = json.loads(json.dumps(raw))
    if f != 1:
        out["recipeServings"] = sv
        by_i = {ln["i"]: ln["text"] for ln in lines}
        for i, ing in enumerate(out.get("recipeIngredient") or []):
            if _num(ing.get("quantity")):
                ing["quantity"] = round(float(ing["quantity"]) * f, 4)
            if i in by_i:
                for k in ("display", "originalText", "note") if not (ing.get("food") or ing.get("unit")) else ("display",):
                    ing[k] = by_i[i]
    return json.dumps(out, indent=2, ensure_ascii=False) + "\n"


def _print_steps(slug, rec, style):
    """Classic steps, or the step-by-step version when one is cached (built-in arranger otherwise; never a new AI call)."""
    if style == "steps":
        try:
            with db() as c:
                cached = _guided_cached(c, rec["id"], GUIDED_AI, _guided_key(recipe_detail(slug)))
            data = guided_localize(cached) if cached is not None else guided(slug, False)
            steps = [{"title": s.get("title") or "", "text": s.get("text") or "",
                      "extra": " · ".join(x for x in (s.get("temperature"), s.get("timer_label")) if x)}
                     for s in data.get("steps") or [] if s.get("text")]
            if steps:
                return steps
        except Exception as e:   # any problem: print the classic steps
            log("print: step-by-step unavailable:", str(e)[:200])
    return [{"title": st["title"], "text": st["text"], "extra": ""} for st in rec["steps"]]


def print_recipe(slug, size="letter", servings=None, style="classic", photo=True):
    sz = PRINT_SIZES[size]
    rec, lines, _, sv = recipe_export(slug, servings)
    steps = _print_steps(slug, rec, style)
    e = html.escape
    nonce = getattr(_req, "nonce", "") or ""
    if sz.get("card"):
        return _print_cards(rec, lines, steps, sv, sz, photo, nonce)
    inner_w, inner_h = sz["w"] - 2 * sz["m"], sz["h"] - 2 * sz["m"]
    ing_html = ""
    for ln in lines:
        if ln["section"]:
            ing_html += f'</ul><h3>{e(ln["section"])}</h3><ul>'
        ing_html += f"<li>{e(ln['text'])}</li>"
    ing_html = f"<ul>{ing_html}</ul>".replace("<ul></ul>", "")
    steps_html = "".join(
        "<li>" + (f"<b>{e(s['title'])}.</b> " if s["title"] else "") + e(s["text"])
        + (f' <span class="x">{e(s["extra"])}</span>' if s["extra"] else "") + "</li>" for s in steps)
    img = (f'<img class="photo" alt="" src="/img/{e(rec["id"])}?size=full">'
           if photo and rec.get("has_image") and UUID_RE.fullmatch(str(rec.get("id") or "")) else "")
    meta = _meta_line(rec, sv)
    src = rec.get("source_url") or ""
    cols = "grid-template-columns:minmax(0,2fr) minmax(0,3fr);" if sz["cols"] else "grid-template-columns:1fr;"
    css = f"""@page{{size:{sz['page']};margin:{sz['m']}in}}
*{{box-sizing:border-box}}html,body{{margin:0;padding:0;background:#f2f2f7}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1c1c1e}}
.sheet{{width:{inner_w:.2f}in;min-height:{inner_h:.2f}in;margin:56px auto 24px;background:#fff;font-size:{sz['font']}pt;line-height:1.3;
box-shadow:0 0 0 {sz['m']}in #fff,0 2px 12px {sz['m']}in rgba(0,0,0,.08)}}
h1{{font-size:{sz['title'] / sz['font']:.2f}em;margin:0 0 .15em;letter-spacing:-.01em;line-height:1.15}}
.meta{{color:#6e6e73;font-size:.85em;margin-bottom:.5em}}.desc{{margin:0 0 .6em}}
h2{{font-size:.75em;text-transform:uppercase;letter-spacing:.08em;color:#6e6e73;margin:.4em 0 .3em;border-bottom:1px solid #e5e5ea}}
h3{{font-size:.85em;margin:.5em 0 .15em}}
.cols{{display:grid;{cols}gap:0 1.4em}}ul,ol{{margin:0;padding-left:1.2em}}li{{margin:0 0 .25em}}
.x{{color:#6e6e73;font-size:.85em;white-space:nowrap}}
.photo{{float:right;width:{'34%' if sz['h'] < 6 else '38%'};max-height:{min(3.2, inner_h * 0.42):.2f}in;object-fit:cover;border-radius:4px;margin:0 0 .5em .8em}}
.foot{{clear:both;margin-top:.8em;padding-top:.3em;border-top:1px solid #e5e5ea;color:#8e8e93;font-size:.75em;display:flex;justify-content:space-between;gap:1em}}
.foot span:first-child{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.bar{{position:fixed;top:10px;right:12px;display:flex;gap:8px;align-items:center}}
.bar button{{font:inherit;font-size:14px;padding:8px 14px;border-radius:999px;border:0;background:#007aff;color:#fff}}
.bar button.sec{{background:#e5e5ea;color:#1c1c1e}}.bar small{{color:#6e6e73;font-size:12px}}
@media print{{html,body{{background:#fff}}.bar{{display:none}}.sheet{{margin:0;box-shadow:none;min-height:0}}}}"""
    js = (f"(function(){{var s=document.getElementById('tp-sheet'),max={inner_h * 96:.1f},min={sz['min']},f={sz['font']};"
          "function fit(){f=" + f"{sz['font']}" + ";s.style.fontSize=f+'pt';"
          "while(s.scrollHeight>max&&f>min){f=Math.max(min,Math.round((f-0.25)*100)/100);s.style.fontSize=f+'pt';}}"
          "document.getElementById('tp-done').onclick=function(){history.length>1?history.back():window.close();};"
          "document.getElementById('tp-print').onclick=function(){window.print();};"
          "window.addEventListener('load',function(){fit();"
          "if(location.search.indexOf('auto=1')>=0)setTimeout(function(){window.print();},300);});"
          "if(document.readyState==='complete')fit();})();")
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(rec['name'] or 'Recipe')}</title><style>{css}</style></head><body>
<div class="bar"><small>Choose "Save as PDF" in the print dialog</small><button class="sec" id="tp-done">Done</button><button id="tp-print">Print</button></div>
<div class="sheet" id="tp-sheet">{img}<h1>{e(rec['name'] or 'Recipe')}</h1>{f'<div class="meta">{e(meta)}</div>' if meta else ''}
{f'<p class="desc">{e(rec["description"][:400])}</p>' if rec.get("description") and not sz['h'] < 6 else ''}
<div class="cols"><section><h2>Ingredients</h2>{ing_html}</section><section><h2>Steps</h2><ol>{steps_html}</ol></section></div>
<div class="foot"><span>{e(src)}</span><span>TablePlan</span></div></div>
<script nonce="{e(nonce)}">{js}</script></body></html>"""


def _print_cards(rec, lines, steps, sv, sz, photo, nonce):
    """Cut-out cards on US Letter: each card is a dashed box of the exact size. Content fills card 1 and flows onto
    more cards ("Name · 2 of 3", "continued"); a small script measures and moves blocks, adding Letter pages as needed."""
    e = html.escape
    name = rec["name"] or "Recipe"
    meta = _meta_line(rec, sv)
    blocks = [f'<h1 class="b">{e(name)}</h1>']
    if photo and rec.get("has_image") and UUID_RE.fullmatch(str(rec.get("id") or "")):
        blocks.insert(0, f'<img class="photo" alt="" src="/img/{e(rec["id"])}?size=full">')
    if meta:
        blocks.append(f'<div class="meta b">{e(meta)}</div>')
    blocks.append('<h2 class="b">Ingredients</h2>')
    for ln in lines:
        if ln["section"]:
            blocks.append(f'<h3 class="b">{e(ln["section"])}</h3>')
        blocks.append(f'<div class="b ing">{e(ln["text"])}</div>')
    blocks.append('<h2 class="b">Steps</h2>')
    for i, st in enumerate(steps, 1):
        blocks.append(f'<div class="b step"><span class="n">{i}.</span><span>'
                      + (f"<b>{e(st['title'])}.</b> " if st["title"] else "") + e(st["text"])
                      + (f' <span class="x">{e(st["extra"])}</span>' if st["extra"] else "") + "</span></div>")
    src = rec.get("source_url") or ""
    blocks.append(f'<div class="b foot"><span>{e(src)}</span><span>TablePlan</span></div>')
    w, h, pad, m = sz["w"], sz["h"], CARD_PAD, CARD_PAGE_MARGIN
    page_w, page_h = 8.5 - 2 * m, 11 - 2 * m
    css = f"""@page{{size:letter;margin:{m}in}}
*{{box-sizing:border-box}}html,body{{margin:0;padding:0;background:#f2f2f7}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1c1c1e;
-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.page{{width:{page_w}in;height:{page_h}in;margin:56px auto 24px;background:#fff;display:flex;flex-direction:column;
align-items:center;box-shadow:0 0 0 {m}in #fff,0 2px 12px {m}in rgba(0,0,0,.08)}}
.card{{position:relative;width:{w}in;height:{h}in;border:1px dashed #999;break-inside:avoid;page-break-inside:avoid;
font-size:{max(sz['font'], sz['min'])}pt;line-height:1.28}}
.card+.card{{margin-top:-1px}}
.cut{{position:absolute;top:-.62em;left:-.5em;font-size:9pt;line-height:1;color:#999;background:#fff;padding:0 1px}}
.cin{{position:absolute;inset:{pad}in;overflow:hidden}}
.more{{position:absolute;right:{pad}in;bottom:.02in;font-size:6.5pt;color:#8e8e93;font-style:italic}}
.cont{{font-size:.8em;color:#6e6e73;border-bottom:1px solid #e5e5ea;margin-bottom:.3em;padding-bottom:.1em}}
h1{{font-size:{sz['title']}pt;margin:0 0 .1em;line-height:1.15;letter-spacing:-.01em}}
.meta{{color:#6e6e73;font-size:.85em;margin-bottom:.3em}}
h2{{font-size:.72em;text-transform:uppercase;letter-spacing:.08em;color:#6e6e73;margin:.35em 0 .2em;border-bottom:1px solid #e5e5ea}}
h3{{font-size:.85em;margin:.35em 0 .1em}}
.ing{{padding-left:.9em;text-indent:-.7em;margin:0 0 .12em}}.ing::before{{content:"•";display:inline-block;width:.7em;text-indent:0}}
.step{{display:flex;gap:.35em;margin:0 0 .25em}}.step .n{{font-weight:600;min-width:1.1em}}
.x{{color:#6e6e73;font-size:.85em;white-space:nowrap}}
.photo{{float:right;width:35%;max-height:{h * 0.5:.2f}in;object-fit:cover;border-radius:3px;margin:0 0 .3em .6em}}
.foot{{clear:both;margin-top:.4em;color:#8e8e93;font-size:.72em;display:flex;justify-content:space-between;gap:1em}}
.foot span:first-child{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
#tp-src{{display:none}}
.bar{{position:fixed;top:10px;right:12px;display:flex;gap:8px;align-items:center}}
.bar button{{font:inherit;font-size:14px;padding:8px 14px;border-radius:999px;border:0;background:#007aff;color:#fff}}
.bar button.sec{{background:#e5e5ea;color:#1c1c1e}}.bar small{{color:#6e6e73;font-size:12px}}
@media print{{html,body{{background:#fff}}.bar{{display:none}}.page{{margin:0;box-shadow:none;break-after:page;page-break-after:always}}
.page:last-child{{break-after:auto;page-break-after:auto}}.card{{border:1px dashed #999}}}}"""
    js = ("(function(){var name=" + json.dumps(name).replace("<", "\\u003c") + ",per=" + str(sz["per"]) + ";"
          "var src=document.getElementById('tp-src'),out=document.getElementById('tp-pages'),cards=[],page=null;"
          "function card(){if(!page||page.childElementCount>=per){page=document.createElement('div');page.className='page';out.appendChild(page);}"
          "var c=document.createElement('div');c.className='card';var cut=document.createElement('span');cut.className='cut';"
          "cut.textContent='\u2702';c.appendChild(cut);var i=document.createElement('div');i.className='cin';c.appendChild(i);"
          "page.appendChild(c);cards.push(i);if(cards.length>1){var h=document.createElement('div');h.className='cont';h.textContent=name+' \u00b7 99 of 99';i.appendChild(h);}return i;}"
          "function over(i){var l=i.lastElementChild;return !!l&&l.getBoundingClientRect().bottom>i.getBoundingClientRect().bottom+0.5;}"
          "function lay(){out.textContent='';cards=[];page=null;var blocks=[].slice.call(src.children).map(function(b){return b.cloneNode(true);});"
          "var cur=card();blocks.forEach(function(b){cur.appendChild(b);if(over(cur)&&cur.querySelectorAll('.b').length>1){"
          "cur.removeChild(b);var prev=cur.lastElementChild,hd=prev&&/^H[23]$/.test(prev.tagName)&&cur.querySelectorAll('.b').length>1?prev:null;"
          "cur=card();if(hd)cur.appendChild(hd);cur.appendChild(b);}});"
          "var n=cards.length;cards.forEach(function(i,k){var h=i.querySelector('.cont');if(h)h.textContent=name+' \u00b7 '+(k+1)+' of '+n;"
          "if(k<n-1){var m=document.createElement('div');m.className='more';m.textContent='continued \u2192';i.parentNode.appendChild(m);}});}"
          "document.getElementById('tp-done').onclick=function(){history.length>1?history.back():window.close();};"
          "document.getElementById('tp-print').onclick=function(){window.print();};"
          "lay();window.addEventListener('load',function(){lay();"
          "if(location.search.indexOf('auto=1')>=0)setTimeout(function(){window.print();},300);});})();")
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(name)}</title><style>{css}</style></head><body>
<div class="bar"><small>Prints on Letter paper with dashed lines to cut out</small><button class="sec" id="tp-done">Done</button><button id="tp-print">Print</button></div>
<div id="tp-src">{''.join(blocks)}</div><div id="tp-pages"></div>
<script nonce="{e(nonce)}">{js}</script></body></html>"""


def msg_recipe(slug, servings=None):
    rec, lines, _, sv = recipe_export(slug, servings)
    e = html.escape
    meta = _meta_line(rec, sv)
    body = (f"<h1>{e(rec['name'] or 'Recipe')}</h1>" + (f"<div class='sub'>{e(meta)}</div>" if meta else "")
            + "<h2>Ingredients</h2><ul>" + "".join(f"<li>{e(ln['text'])}</li>" for ln in lines) + "</ul>"
            + "<h2>Steps</h2><ol>" + "".join(f"<li>{e(st['text'])}</li>" for st in rec["steps"]) + "</ol>"
            + (f"<p class='sub'>Source: {e(rec['source_url'])}</p>" if rec.get("source_url") else ""))
    return {"subject": f"🍳 {rec['name'] or 'Recipe'}", "text": render_recipe_text(slug, servings),
            "html": email_wrap(body), "files": []}


# ============================================================ backups and storage safety

BACKUP_DIR = os.path.join(DATA_DIR, "backups")
BACKUP_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.db")
DAILY_BACKUP_RE = re.compile(r"tableplan-\d{4}-\d{2}-\d{2}\.db")
PRE_BACKUP_RE = re.compile(r"pre-[A-Za-z0-9._-]+-to-[A-Za-z0-9._-]+\.db")
KEEP_DAILY, KEEP_PRE = 14, 5
ZIP_CAP = 1 << 30   # 1 GB
_backup_lock = threading.Lock()
_zip_lock = threading.Lock()
_storage = {"integrity": None}


def _snapshot(dest):
    """Consistent copy of the live database via SQLite's online backup API; written 0600 and swapped in atomically."""
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    tmp = dest + ".tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    os.close(fd)
    try:
        src = sqlite3.connect(DB_PATH, timeout=30)
        try:
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return dest


def rotate_backups():
    try:
        names = os.listdir(BACKUP_DIR)
    except FileNotFoundError:
        return
    daily = sorted(n for n in names if DAILY_BACKUP_RE.fullmatch(n))
    pre = sorted((n for n in names if PRE_BACKUP_RE.fullmatch(n)),
                 key=lambda n: os.path.getmtime(os.path.join(BACKUP_DIR, n)))
    for n in daily[:-KEEP_DAILY] + pre[:-KEEP_PRE]:
        try:
            os.remove(os.path.join(BACKUP_DIR, n))
        except OSError as e:
            log("backup rotation:", e)


def _backup_info(name):
    st = os.stat(os.path.join(BACKUP_DIR, name))
    return {"name": name, "size": st.st_size, "created": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")}


def list_backups():
    try:
        names = os.listdir(BACKUP_DIR)
    except FileNotFoundError:
        return []
    out = []
    for n in names:
        p = os.path.join(BACKUP_DIR, n)
        if BACKUP_NAME_RE.fullmatch(n) and os.path.isfile(p) and not os.path.islink(p):
            out.append(_backup_info(n))
    return sorted(out, key=lambda b: b["created"], reverse=True)


def make_backup():
    with _backup_lock:
        name = f"tableplan-{iso(today())}.db"
        _snapshot(os.path.join(BACKUP_DIR, name))
        rotate_backups()
    set_internal("backup_last", iso(today()))
    return _backup_info(name)


# ============================================================ Settings → Danger zone (resets, each after a backup)

RESET_SECTIONS = {   # key: label the user must type
    "inventory": "Inventory", "recipes": "Recipes", "plan": "Meal plan", "list": "Shopping list",
    "trips": "Grocery trips", "diary": "Cooking diary", "demo": "Demo data", "everything": "Everything",
}


def _reset_backup(section):
    """A backup taken right before a reset, kept apart from the daily ones (the last 5 are kept)."""
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    name = f"pre-reset-{section}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    with _backup_lock:
        _snapshot(os.path.join(BACKUP_DIR, name))
        old = sorted(n for n in os.listdir(BACKUP_DIR) if n.startswith("pre-reset-") and n.endswith(".db"))
        for n in old[:-5]:
            try:
                os.remove(os.path.join(BACKUP_DIR, n))
            except OSError:
                pass
    return name


def _reset_rows(c, section):
    """Delete one section's rows (and what depends on them) inside the caller's transaction. Returns counts and
    folders to remove once the transaction has committed."""
    n, dirs = {}, []
    dele = lambda table, where="1=1", args=(): n.__setitem__(table, n.get(table, 0) + c.execute(f"DELETE FROM {table} WHERE {where}", args).rowcount)  # noqa: E731
    if section in ("inventory", "everything"):
        dele("allocations"); dele("pantry_events"); dele("pantry_items")
        dirs.append(os.path.join(IMG_DIR, "pantry"))
    if section in ("plan", "everything"):
        dele("allocations"); dele("meal_plans")
    if section in ("list", "everything"):
        dele("shopping_items")
    if section in ("trips", "everything"):
        dele("purchases"); dele("trips")
        dirs.append(os.path.join(IMG_DIR, "trips"))
    if section in ("diary", "everything"):
        dele("diary")
        dirs.append(os.path.join(IMG_DIR, "diary"))
    if section in ("recipes", "demo", "everything"):
        if section == "demo":
            ids = [r["id"] for r in c.execute("SELECT id, data FROM recipes")
                   if (json.loads(r["data"] or "{}").get("extras") or {}).get("demo")]
        else:
            ids = [r["id"] for r in c.execute("SELECT id FROM recipes")]
        for rid in ids:
            for table, col in (("diary", "recipe_id"), ("guided_cache", "recipe_id"), ("recipe_cache", "id"),
                               ("favorites", "recipe_id"), ("aliases", "recipe_id"), ("recipes", "id")):
                dele(table, f"{col}=?", (rid,))
            for e in c.execute("SELECT id FROM meal_plans WHERE recipe_id=?", (rid,)).fetchall():
                dele("allocations", "plan_entry_id=?", (e["id"],))
            dele("meal_plans", "recipe_id=?", (rid,))
            for lst in n_lists.list_lists(c):   # list lines added from this recipe outside the plan
                n_lists.remove_recipe_items(c, lst["id"], rid)
            if UUID_RE.fullmatch(rid):
                dirs.append(os.path.join(IMG_DIR, rid))
        n["recipes_removed"] = len(ids)
        if section == "demo":
            dele("pantry_items", "product='Demo'")
    return n, dirs


def danger_reset(section, b):
    """POST /api/reset/{section} {confirm}: back up, then clear one part of TablePlan in one transaction."""
    require_native()
    if section not in RESET_SECTIONS:
        raise ApiError(404, "Unknown section")
    label = RESET_SECTIONS[section]
    if " ".join(_s(b.get("confirm"), 40).split()).lower() != label.lower():
        raise ApiError(400, f"Type {label} to confirm.")
    backup = _reset_backup(section)
    with db() as c:
        counts, dirs = _reset_rows(c, section)
        sync_plan_list(c)
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)
    _recipe_cache["at"] = 0
    log(f"reset {section}: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + f"; backup {backup}")
    return {"ok": True, "section": section, "backup": backup, "backup_path": os.path.join(BACKUP_DIR, backup), "removed": counts}


def backup_path(name):
    """Path of an existing backup, or 404. Only plain names inside the backups folder are accepted."""
    if not isinstance(name, str) or not BACKUP_NAME_RE.fullmatch(name):
        raise ApiError(404, "Not found")
    base = os.path.realpath(BACKUP_DIR)
    p = os.path.join(base, name)
    if os.path.dirname(os.path.realpath(p)) != base or os.path.islink(p) or not os.path.isfile(p):
        raise ApiError(404, "Not found")
    return p


def _stored_version():
    """The version that last ran against this database (read before migrations touch it)."""
    if not os.path.exists(DB_PATH):
        return None, False
    try:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        try:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'").fetchone():
                return None, False
            row = conn.execute("SELECT value FROM settings WHERE key='last_run_version'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        log("couldn't read the stored version:", e)
        return None, False
    try:
        return (json.loads(row[0]) if row else None), True
    except ValueError:
        return None, True


def pre_upgrade_snapshot():
    """Snapshot the database before a different TablePlan version migrates it."""
    old, existing = _stored_version()
    if not existing or old == APP_VERSION:
        return None
    name = f"pre-{safe_filename(old or 'unknown', 'unknown')}-to-{safe_filename(APP_VERSION, 'new')}.db"
    with _backup_lock:
        _snapshot(os.path.join(BACKUP_DIR, name))
        rotate_backups()
    log(f"saved {name} before upgrading")
    return name


def integrity_check():
    try:
        with db() as c:
            rows = [r[0] for r in c.execute("PRAGMA integrity_check").fetchall()]
        res = "ok" if rows == ["ok"] else "; ".join(str(r) for r in rows)[:500]
    except sqlite3.Error as e:
        res = f"check failed: {e}"[:500]
    _storage["integrity"] = res
    (log("database integrity: ok") if res == "ok" else log("DATABASE INTEGRITY PROBLEM:", res))
    return res


def storage_persistent():
    """In a container, DATA_DIR must be a mounted volume (its own device or a mount point) to survive a rebuild."""
    if not (os.path.exists("/.dockerenv") or ON_RAILWAY):
        return True
    try:
        if os.stat(DATA_DIR).st_dev != os.stat("/").st_dev:
            return True
    except OSError:
        return False
    real = os.path.realpath(DATA_DIR)
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
            mounts = {ln.split()[1].replace("\\040", " ") for ln in f if len(ln.split()) > 1}
    except OSError:
        return False
    return real in mounts


def storage_info():
    b = list_backups()
    return {"persistent": storage_persistent(), "last_backup": b[0]["created"] if b else None, "backups": len(b),
            "integrity": _storage["integrity"] or "not checked", "data_dir": DATA_DIR}


def startup_storage():
    integrity_check()
    set_internal("last_run_version", APP_VERSION)
    try:
        make_backup()
    except Exception as e:
        log("startup backup failed:", e)
    if not storage_persistent():
        log(f"WARNING: {DATA_DIR} isn't on a persistent volume; data will be lost when this container is rebuilt.")


def build_backup_zip():
    """A temp file holding a zip of a fresh DB snapshot plus the images folder (capped at 1 GB)."""
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    fd, snap = tempfile.mkstemp(prefix=".snap-", suffix=".tmp", dir=BACKUP_DIR)
    os.close(fd)
    out = tempfile.TemporaryFile(dir=BACKUP_DIR)
    try:
        _snapshot(snap)
        total = os.path.getsize(snap)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snap, "tableplan.db")
            for root, dirs, files in os.walk(IMG_DIR, followlinks=False):
                dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
                for fn in files:
                    p = os.path.join(root, fn)
                    if os.path.islink(p) or not os.path.isfile(p) or fn.endswith(".tmp"):
                        continue
                    total += os.path.getsize(p)
                    if total > ZIP_CAP:
                        raise ApiError(413, "Your data is over 1 GB. Copy the data folder directly instead.")
                    zf.write(p, "images/" + os.path.relpath(p, IMG_DIR).replace(os.sep, "/"), zipfile.ZIP_STORED)
        out.seek(0, os.SEEK_END)
        size = out.tell()
        out.seek(0)
        return out, size
    except BaseException:
        out.close()
        raise
    finally:
        try:
            os.remove(snap)
        except OSError:
            pass


# ============================================================ update check

_update_cache = {"at": 0, "data": None}


def update_info(force=False):
    ttl = 600   # every 10 minutes (a tiny file on GitHub Pages)   # hourly; retry sooner after a failed check
    if force or time.time() - _update_cache["at"] > ttl:
        data = None
        try:
            with _open(UPDATE_FEED, headers={"User-Agent": f"TablePlan/{APP_VERSION}"}, timeout=8, allow_private=True) as r:
                data = json.loads(_read_capped(r, 1_000_000, 30).decode())
            if not isinstance(data, dict):
                data = None
        except Exception:
            data = None
        _update_cache.update(at=time.time(), data=data)
    feed = _update_cache["data"] or {}
    latest = feed.get("version")

    def vt(v):
        return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)

    available = bool(latest and APP_VERSION != "dev" and vt(latest) > vt(APP_VERSION))
    how = {"zimaos": "Open ZimaOS → App Store → My Apps → TablePlan → Update.",
           "cli": "On the server run:  sudo tableplan update"}.get(
        INSTALL_METHOD, "In your TablePlan folder run:  docker compose pull && docker compose up -d")
    return {"version": APP_VERSION, "latest": latest, "update_available": available,
            "notes": feed.get("notes"), "released": feed.get("released"), "how": how, "install": INSTALL_METHOD}


# ============================================================ scheduler (optional weekly auto-plan)

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def notify_update():
    """Send a one-time phone/email notice when a newer TablePlan is published."""
    u = update_info()
    if not u["update_available"] or get_internal("update_notified") == u["latest"] or not any(channels_ready().values()):
        return
    notes = (u.get("notes") or "").strip()
    text = f"TablePlan {u['latest']} is available (you have {u['version']}).\n{notes[:300]}\n\nTo update: {u['how']}"
    try:
        deliver({"subject": f"⬆️ TablePlan {u['latest']} is available", "text": text,
                 "html": email_wrap(f"<h2>TablePlan {html.escape(u['latest'])} is available</h2><p>{html.escape(notes[:300])}</p>"
                                    f"<p><b>To update:</b> {html.escape(u['how'])}</p>"), "files": []})
        set_internal("update_notified", u["latest"])
    except ApiError as e:
        log("update notice not sent:", e.message)


# ============================================================ onboarding tour + sample data

TOUR_STEPS = 7
TOUR_SNOOZE_MS = 7 * 86400 * 1000


def clean_tour(t):
    """Tour state: {done, skipped, snoozed_until (ms), step}. Anything else is refused."""
    if t is None:
        return None
    if not isinstance(t, dict) or set(t) - {"done", "skipped", "snoozed_until", "step"}:
        raise ApiError(400, "Bad tour state.")
    out = {}
    for k in ("done", "skipped"):
        if k in t:
            if not isinstance(t[k], bool):
                raise ApiError(400, "Bad tour state.")
            out[k] = t[k]
    if "snoozed_until" in t:
        v = t["snoozed_until"]
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 10 ** 14):
            raise ApiError(400, "Bad tour state.")
        out["snoozed_until"] = v
    if "step" in t:
        v = t["step"]
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < TOUR_STEPS:
            raise ApiError(400, "Bad tour state.")
        out["step"] = v
    return out


def tour_due(t, now_ms):
    """Show the tour automatically? Never once finished or skipped; not while snoozed."""
    t = t if isinstance(t, dict) else {}
    if t.get("done"):
        return False
    return not (t.get("snoozed_until") and now_ms < t["snoozed_until"])


DEMO_RECIPES = [
    {"name": "Sheet-Pan Lemon Chicken", "servings": 4, "minutes": 45,
     "ingredients": ["2 lb chicken thighs", "1 lb baby potatoes", "1 lemon", "3 cloves garlic", "2 tbsp olive oil", "1 tsp salt"],
     "steps": ["Heat the oven to 425°F.", "Halve the potatoes and toss everything on a sheet pan with the oil, salt, garlic and lemon slices.",
               "Roast 35 minutes, until the chicken is golden and the potatoes are tender."]},
    {"name": "Weeknight Veggie Fried Rice", "servings": 2, "minutes": 20,
     "ingredients": ["2 cups cooked rice", "2 eggs", "1 cup frozen peas", "2 green onions", "2 tbsp soy sauce", "1 tbsp vegetable oil"],
     "steps": ["Heat the oil in a large skillet over high heat.", "Scramble the eggs 1 minute, then push them aside.",
               "Add the rice and peas and stir-fry 5 minutes.", "Stir in the soy sauce and green onions and serve."]},
    {"name": "Banana Oat Pancakes", "servings": 2, "minutes": 15,
     "ingredients": ["2 bananas", "2 eggs", "1 cup rolled oats", "1/2 cup milk", "1 tsp baking powder"],
     "steps": ["Blend everything until smooth.", "Cook 1/4 cup at a time in a buttered pan, 2 minutes per side."]},
]
DEMO_ITEMS = [("eggs", "12", "fridge"), ("spinach", "1 bag", "fridge"), ("rice", "2 lb", "pantry"), ("bananas", "3", "pantry"),
              ("chicken thighs", "2 lb", "fridge"), ("milk", "1 gallon", "fridge")]


def demo_add():
    """POST /api/demo: three sample recipes and a few inventory items, all marked Demo (Settings → Danger zone →
    Wipe demo data removes them). Adding twice doesn't duplicate anything."""
    require_native()
    with db() as c:
        have = any((json.loads(r["data"] or "{}").get("extras") or {}).get("demo") for r in c.execute("SELECT data FROM recipes"))
        if have:
            return {"ok": True, "added": 0, "already": True}
        for d in DEMO_RECIPES:
            data = {"recipeServings": float(d["servings"]), "totalTimeSeconds": d["minutes"] * 60,
                    "recipeIngredient": [{"referenceId": str(uuid.uuid4()), "note": x, "display": x, "originalText": x,
                                          "quantity": 0, "unit": None, "food": None} for x in d["ingredients"]],
                    "recipeInstructions": [{"id": str(uuid.uuid4()), "title": "", "text": s, "ingredientReferences": []} for s in d["steps"]],
                    "tags": [{"name": "Demo"}], "extras": {"demo": True}, "description": "A sample recipe to explore TablePlan."}
            n_recipes.create(c, d["name"], _with_pan(data))
        for name, q, loc in DEMO_ITEMS:
            pid = add_pantry_item(c, name, loc, None, q)
            c.execute("UPDATE pantry_items SET product='Demo' WHERE id=?", (pid,))
    _recipe_cache["at"] = 0
    return {"ok": True, "added": len(DEMO_RECIPES), "items": len(DEMO_ITEMS)}


# ============================================================ missing-ingredient alerts (day before, same morning)

def _checked_for_entries(c, lid):
    """What bought / "have" list lines already covered, per planned meal: {entry id: {food key: [(qty, unit)]}}."""
    out = {}
    for r in c.execute("SELECT * FROM shopping_items WHERE list_id=? AND checked=1", (lid,)).fetchall():
        for eid, v in _entry_part(_contrib_map(r)).items():
            out.setdefault(str(eid), {}).setdefault(_row_key(r), []).append(((v or {}).get("qty"), r["unit"] or ""))
    return out


def meal_missing(c, e, skeys, checked=None, rec=None):
    """What a planned meal still lacks, from the allocation ledger: inventory set aside for it (other meals' reservations
    are theirs; expired items and unreviewed scans are never allocated) plus what was bought or marked "have" for it.
    "Always have" foods count as present. -> [{food, text, key}]"""
    rec = rec or n_recipes.get(c, e["recipe_id"])
    if not rec:
        return []
    got = {}
    for a in c.execute("SELECT food_key, qty, unit FROM allocations WHERE plan_entry_id=?", (e["id"],)):
        got.setdefault(a["food_key"], []).append((a["qty"], a["unit"] or ""))
    if checked is None:
        checked = _checked_for_entries(c, n_lists.single_list(c))
    for k, v in (checked.get(str(e["id"])) or {}).items():
        got.setdefault(k, []).extend(v)
    groups = {}
    for n in _recipe_needs(rec, e["scale"] or 1, skeys, c, create=False):
        groups.setdefault(n["key"], []).append(n)
    out = []
    for k, ns in groups.items():
        have = got.get(k) or []
        first = ns[0]
        if not have:
            out.append({"food": first["food"] or first["line"], "text": _make_need_text(first), "key": k})
            continue
        if any(n["qty"] is None for n in ns) or any(q is None for q, _ in have):
            continue
        need = sum(n_units.convert(n["qty"], n["unit"], first["unit"]) or 0 for n in ns)
        hv = sum(n_units.convert(q, u, first["unit"]) or 0 for q, u in have)
        if hv + 1e-6 < need:
            out.append({"food": first["food"], "text": _make_need_text({**first, "qty": need - hv}), "key": k, "short": True})
    return out


def planned_missing(start, end, c=None):
    """{entry id: [missing]} for planned, uncooked meals with a recipe between start and end."""
    def run(c):
        skeys = staple_keys(c)
        checked = _checked_for_entries(c, n_lists.single_list(c))
        rows = c.execute("SELECT * FROM meal_plans WHERE date BETWEEN ? AND ? AND recipe_id IS NOT NULL AND cooked_at IS NULL "
                         "AND skipped_at IS NULL", (iso(start), iso(end))).fetchall()
        return {str(e["id"]): meal_missing(c, e, skeys, checked) for e in rows}
    if c is not None:
        return run(c)
    with db() as c2:
        return run(c2)


def _local_now():
    """The household's wall-clock time (Settings → Budget time zone, else the server's TZ)."""
    tz = _household_tz()
    return datetime.now(timezone.utc).astimezone(tz).replace(tzinfo=None) if tz else datetime.now()


def notify_missing(now=None):
    """Day-before heads-up and morning check for planned meals still missing something; once per meal per window."""
    if not NATIVE:
        return []
    s = get_settings()
    day_before, morning = bool(s.get("missing_alert_daybefore")), bool(s.get("missing_alert_morning"))
    if not (day_before or morning) or not any(channels_ready().values()):
        return []
    now = now or _local_now()
    eat_times = s.get("eat_times") or {}
    sent = []
    last = get_internal("missing_sync_at") or ""
    if not last or (datetime.now() - datetime.fromisoformat(last)).total_seconds() > 3600:
        with db() as c:
            sync_plan_list(c)   # the ledger follows what expired or was used since the last change
        set_internal("missing_sync_at", datetime.now().isoformat(timespec="seconds"))
    with db() as c:
        rows = c.execute("SELECT * FROM meal_plans WHERE date BETWEEN ? AND ? AND recipe_id IS NOT NULL AND cooked_at IS NULL "
                         "AND skipped_at IS NULL", (iso(now.date()), iso(now.date() + timedelta(days=2)))).fetchall()
        own = {r["entry_id"]: r["eat_at"] for r in c.execute("SELECT * FROM plan_eat_at")}
        pool = {}
        try:
            pool = {r["id"]: r for r in recipe_pool()}
        except ApiError:
            pass
        skeys = staple_keys(c)
        checked = _checked_for_entries(c, n_lists.single_list(c))
        due = []
        for e in rows:
            day = parse_date(e["date"])
            p = pool.get(e["recipe_id"]) or {}
            eat = own.get(str(e["id"])) or eat_times.get(e["entry_type"])
            mins = ((p.get("eta") or {}).get("shown")) or p.get("minutes")
            st = start_by(eat, mins, day) if eat and day else None
            for w in n_alerts.due_windows(now, day, st, s.get("missing_alert_time") or "08:00", day_before, morning):
                flag = f"missing_{w}_{e['id']}_{e['date']}"
                if get_internal(flag):
                    continue
                miss = meal_missing(c, e, skeys, checked)
                if miss:
                    due.append((w, e, p.get("name") or "", miss, flag))
    for w, e, name, miss, flag in due:
        set_internal(flag, True)
        when = "Tomorrow's" if w == "day_before" else ("Tonight's" if e["entry_type"] == "dinner" else "Today's")
        items = ", ".join(m["text"] for m in miss[:6]) + ("…" if len(miss) > 6 else "")
        n = len(miss)
        deliver({"subject": f"🛒 {when} {name} is missing {n} item{'s' if n != 1 else ''}",
                 "text": f"{when} {name} is missing {items}. They're on your shopping list; open TablePlan to add or tick them off.",
                 "html": email_wrap(f"<p>{html.escape(when)} <b>{html.escape(name)}</b> is missing {html.escape(items)}.</p>"
                                    "<p>They're on your shopping list. Open TablePlan to add anything else or tick them off.</p>"),
                 "files": []})
        sent.append((w, e["id"]))
    return sent


def notify_start_cooking(now):
    for e in enrich_plan(get_plans(now.date(), now.date())):
        if e.get("cooked") or e.get("skipped") or not e.get("start_by") or not e.get("recipe"):
            continue
        st = start_by(e["eat_at"], ((e["recipe"].get("eta") or {}).get("shown") or e["recipe"].get("minutes")), now.date())
        if not st or not (st <= now < st + timedelta(minutes=20)):
            continue
        flag = f"start_nudge_{e['id']}_{iso(now.date())}"
        if get_internal(flag):
            continue
        set_internal(flag, True)
        name = e["recipe"].get("name") or "dinner"
        deliver({"subject": f"🍳 Time to start {name}",
                 "text": f"Start {name} now to eat at {e['eat_at']}. It takes about {e['recipe']['eta']['label'].lstrip('≈ ') if e['recipe'].get('eta') else str(e['recipe'].get('minutes')) + ' min'}.",
                 "html": email_wrap(f"<p>Start <b>{html.escape(name)}</b> now to eat at {html.escape(e['eat_at'])}.</p>"), "files": []})


def scheduler():
    while True:
        try:
            notify_update()
        except Exception as e:
            log("update check failed:", e)
        try:
            s = get_settings()
            day = (s.get("auto_plan_day") or "").lower()[:3]
            now = datetime.now()
            if day in WEEKDAYS and now.weekday() == WEEKDAYS.index(day) and now.hour >= 8:
                if get_internal("auto_plan_last") != iso(now.date()):
                    start = now.date() + timedelta(days=1)
                    res = generate_plan({"start": iso(start), "days": 7, "fill_empty_only": True})
                    n = save_plan([{"date": p["date"], "entry_type": p["entry_type"], "recipe_id": p["recipe"]["id"]}
                                   for p in res["proposals"]])
                    set_internal("auto_plan_last", iso(now.date()))
                    log(f"auto-plan: added {n} meals for week of {start}")
                    if s.get("auto_plan_email") and any(channels_ready().values()):
                        deliver(msg_plan(start, start + timedelta(days=6)))
            # Daily "use soon" alert
            if s.get("expiry_alert") and any(channels_ready().values()) and now.hour >= int(s.get("expiry_alert_hour") or 8):
                if get_internal("expiry_alert_last") != iso(now.date()):
                    set_internal("expiry_alert_last", iso(now.date()))
                    with db() as c:
                        items = expiring_items(c, 1)
                    if items:
                        deliver(msg_expiring(items))
                        log(f"use-soon alert sent ({len(items)} items)")
            # Nightly database backup (~3:00; one is also taken at start-up)
            if now.hour >= 3 and get_internal("backup_last") != iso(now.date()):
                try:
                    make_backup()
                    log("nightly backup saved")
                except Exception as e:
                    log("nightly backup failed:", e)
            # "Time to start cooking" (opt-in): today's planned meals, at their start-by time
            if s.get("start_reminder") and any(channels_ready().values()):
                try:
                    notify_start_cooking(now)
                except ApiError as e:
                    log("start-cooking reminder not sent:", e.message)
            # Missing ingredients: the day-before heads-up and the morning check
            try:
                notify_missing()
            except ApiError as e:
                log("missing-ingredient alert not sent:", e.message)
            # "Your meal plan runs out" reminder (once per run-out)
            try:
                notify_plan_runout(now)
            except ApiError as e:
                log("plan reminder not sent:", e.message)
            # Pantry check-in reminder (once per due period, at the alert hour)
            ck = pantry_checkin_status()
            if ck["due"] and any(channels_ready().values()):
                flag = f"checkin_nudge_{ck['last']}_{iso(now.date() - timedelta(days=now.weekday()))}"
                if not get_internal(flag):
                    set_internal(flag, True)
                    deliver({"subject": "🧺 Kitchen check-in",
                             "text": "A few items might be gone or running low. Open TablePlan to swipe through them: it takes about a minute.",
                             "html": email_wrap("<p>A few items might be gone or running low. Open TablePlan and tap <b>Kitchen check-in</b>: it takes about a minute.</p>"), "files": []})
            # Prices: refreshed in the background (each source keeps its own pace), and the grocery budget alert
            if NATIVE and now.hour >= 4:
                last = get_internal("prices_refresh_at") or ""
                if not last or (now - datetime.fromisoformat(last)).total_seconds() > 6 * 3600:
                    prices_refresh()
                try:
                    notify_budget()
                except ApiError as e:
                    log("budget alert not sent:", e.message)
            # Monthly AI budget alert (80% and 100%)
            budget = float(s.get("ai_budget") or 0)
            if budget > 0 and any(channels_ready().values()):
                sp = ai_spending()
                spent = (sp["exact"] or {}).get("total", sp["estimate_usd"]) if sp["exact"] else sp["estimate_usd"]
                for level in (1.0, 0.8):
                    flag = f"ai_budget_{sp['month']}_{int(level * 100)}"
                    if spent >= budget * level and not get_internal(flag):
                        set_internal(flag, True)
                        deliver({"subject": f"💸 AI spending at {int(level * 100)}% of budget",
                                 "text": f"${spent:.2f} of your ${budget:.2f} monthly OpenAI budget used in {sp['month']}.",
                                 "html": email_wrap(f"<p>${spent:.2f} of your ${budget:.2f} monthly OpenAI budget used.</p>"), "files": []})
                        break
        except Exception as e:  # never let the scheduler die
            log("scheduler error:", e)
        time.sleep(300)


# ============================================================ HTTP

# Request body limits: screenshots/PDFs and photo uploads are big, everything else is small JSON.
BODY_LIMITS = [
    (re.compile(r"/api/import/images|/api/import/queue|/api/receipt|/api/trip/apply"), 36_000_000),
    (re.compile(r"/api/import/queue/\d+/page/\d+"), 16_000_000),   # ~25 MB of files once base64-encoded
    (re.compile(r"/api/recipe/[^/]+/image/upload"), 20_000_000),   # master + card + thumb
    (re.compile(r"/api/pantry/\d+/photo"), 12_000_000),
    (re.compile(r"/api/recipe/[^/]+/image/upload-legacy|/api/ingredient-image/upload|/api/scan/photo|/api/diary/\d+/photo|/api/pantry/\d+/details"), 12_000_000),
    (re.compile(r"/api/scan/identify"), 24_000_000),   # 8 MB image
]
BODY_LIMIT_DEFAULT = 1_000_000

# Expensive endpoints: rate-limited per client in public mode, and imports run a few at a time.
EXPENSIVE = [
    (re.compile(r"/api/import/(url|text|images)"), "import"),
    (re.compile(r"/api/setup/import-mealie"), "import"),
    (re.compile(r"/api/recipe/[^/]+/(guided|image/next|polish|adjust)"), "ai"),
    (re.compile(r"/api/plan/arrange"), "ai"),
    (re.compile(r"/api/(setup/ai|setup/openai-admin|ingredient-image/next)"), "ai"),
    (re.compile(r"/api/scan/photo|/api/scan/identify|/api/receipt|/api/make/web|/api/prices/refresh|/api/recipe/[^/]+/image/ai$"), "ai"),
    (re.compile(r"/api/recipe/[^/]+/image/candidates"), "fetch"),
    (re.compile(r"/api/ideas"), "fetch"),
    (re.compile(r"/api/(upc/\d+|scan|send|email|rules/sync-usda|setup/email|setup/ntfy|setup/telegram.*)"), "fetch"),
    (re.compile(r"/api/backups|/export/backup\.zip"), "fetch"),
]
PUBLIC_PATHS = ("/", "/manifest.webmanifest", "/sw.js", "/api/session", "/api/login")


def body_limit(path):
    for rx, n in BODY_LIMITS:
        if rx.fullmatch(path):
            return n
    return BODY_LIMIT_DEFAULT


def safe_filename(name, default="download"):
    """A Content-Disposition-safe file name (no quotes, CR/LF, slashes or non-ASCII)."""
    out = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "")).strip(".-")[:100]
    return out or default


class Handler(BaseHTTPRequestHandler):
    server_version = "TablePlan/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 60   # seconds a client may stall while sending a request (slow-loris protection)

    def log_message(self, fmt, *args):
        if "/health" not in str(args[0] if args else ""):
            sys.stdout.write("[tableplan] %s %s\n" % (self.client_ip(), (fmt % args).replace("\n", " ")[:500]))

    # ---- helpers
    def session_token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "tp_session" and v:
                return v
        return ""

    def authorized(self):
        """True when this request may use the app; sets self.user to the signed-in member (None without accounts)."""
        if getattr(self, "_authed", None) is not None:
            return self._authed
        self.user = None
        tok, ok = self.session_token(), False
        if tok.startswith("u."):
            with db() as c:
                row = n_users.session_user(c, tok, time.time(), SESSION_DAYS * 86400)
            if row is not None:
                self.user, ok = n_users.public_user(row), True
        elif tok and valid_session(tok) and not users_exist():
            ok = True   # household-password session: only until the first account exists
        if not ok and not auth_required():
            ok = True
        self._authed = ok
        return ok

    def client_ip(self):
        peer = self.client_address[0] if self.client_address else ""
        headers = getattr(self, "headers", None)
        if TRUST_PROXY and headers is not None:
            # The trusted proxy appends the address it saw, so the right-most entry is the one we can believe.
            hops = [h.strip() for h in (headers.get("X-Forwarded-For") or "").split(",") if h.strip()]
            if hops:
                return hops[-1][:64]
        return peer

    def cookie(self, value, max_age=SESSION_DAYS * 86400):
        secure = "; Secure" if getattr(_req, "scheme", "http") == "https" else ""
        return f"tp_session={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict{secure}"

    def send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if getattr(self, "_sync_after", False) and code < 300:
            self._sync_after = False
            try:
                sync_list()   # inventory or recipes changed: re-allocate and refresh the planned part of the list
            except Exception as e:
                log("list sync failed:", e)
        if isinstance(body, (dict, list)):
            body = json.dumps(body, default=str)
        data = body.encode("utf-8") if isinstance(body, str) else body
        if not self._start(code, ctype, len(data), headers):
            return
        try:
            if self.command != "HEAD":
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True   # the browser went away mid-response; nothing to do

    def send_file(self, fileobj, length, ctype, fname):
        """Stream an open binary file as a download (backups can be large)."""
        if not self._start(200, ctype, length, {"Content-Disposition": f'attachment; filename="{safe_filename(fname)}"'}):
            return
        if self.command == "HEAD":
            return
        try:
            remaining = length
            while remaining > 0:
                chunk = fileobj.read(min(1 << 20, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _start(self, code, ctype, length, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        if getattr(self, "_body", None) is None and getattr(self, "_req_len", 0) > 0:
            # request body was never read (early 401/403/413/error): close so its bytes aren't parsed as the next request
            self.send_header("Connection", "close")
            self.close_connection = True
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        if ctype.startswith("text/html"):
            nonce = getattr(_req, "nonce", "")
            extra = f"'nonce-{nonce}' " if nonce and self.path.startswith("/print/") else ""
            self.send_header("Content-Security-Policy",
                             f"default-src 'self'; script-src 'self' 'wasm-unsafe-eval' {extra}; style-src 'self' 'unsafe-inline'; "
                             "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
                             "base-uri 'self'; form-action 'self'")
        else:
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; sandbox")
        if getattr(_req, "scheme", "http") == "https":
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        if not (headers or {}).get("Cache-Control"):
            self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        try:
            self.end_headers()
            return True
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True   # the browser went away mid-response; nothing to do
            return False

    def download(self, text, fname, ctype):
        self.send(200, text, ctype, {"Content-Disposition": f'attachment; filename="{safe_filename(fname)}"'})

    def body(self):
        if getattr(self, "_body", None) is None:
            self._read_body()
        try:
            out = json.loads(self._body) if self._body else {}
        except (ValueError, RecursionError):
            raise ApiError(400, "Expected a JSON object.")
        if not isinstance(out, dict):
            raise ApiError(400, "Expected a JSON object.")
        return out

    def json_any(self):
        """Request JSON that may be an object or a list."""
        if getattr(self, "_body", None) is None:
            self._read_body()
        try:
            out = json.loads(self._body) if self._body else {}
        except (ValueError, RecursionError):
            raise ApiError(400, "Expected JSON.")
        if not isinstance(out, (dict, list)):
            raise ApiError(400, "Expected JSON.")
        return out

    def _read_body(self):
        n = self._req_len
        if n > self._max_body:
            raise ApiError(413, "Request too large")
        self._body = self.rfile.read(n) if n else b""
        if len(self._body) < n:
            self.close_connection = True
            raise ApiError(400, "Incomplete request body")

    def _reject(self, code, msg):
        self.close_connection = True
        return self.send(code, {"error": msg})

    def handle_any(self, method):
        self._authed = None
        self.user = None
        self._body = None
        self._req_len = 0
        self._max_body = BODY_LIMIT_DEFAULT
        _req.nonce = ""
        if self.headers.get("Transfer-Encoding"):
            # Chunked bodies aren't supported; refusing them avoids request-smuggling ambiguity.
            return self._reject(411, "Send a Content-Length")
        cl = (self.headers.get("Content-Length") or "0").strip()
        if not cl.isdigit() or len(self.headers.get_all("Content-Length") or []) > 1:
            return self._reject(400, "Bad Content-Length")
        self._req_len = int(cl)
        try:
            url = urllib.parse.urlparse(self.path)
        except ValueError:
            return self._reject(400, "Bad request")
        path, q = url.path, {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if path == "/health":
            return self.send(200, "ok", "text/plain")
        host = ((self.headers.get("X-Forwarded-Host") if TRUST_PROXY else None) or self.headers.get("Host") or "localhost")
        host = host.split(",")[0].strip()
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}(:\d{1,5})?|\[[0-9A-Fa-f:.]+\](:\d{1,5})?", host):
            host = "localhost"
        _req.host = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        # X-Forwarded-Proto can only make the response stricter (Secure cookie, HSTS), so it's honoured even
        # without TABLEPLAN_TRUST_PROXY: a home reverse proxy that terminates HTTPS keeps working.
        _req.scheme = "https" if (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower() == "https" else "http"
        _req.nonce = secrets.token_urlsafe(16) if path.startswith("/print/") else ""
        public = path in PUBLIC_PATHS or path.startswith("/static/")
        state_changing = method in ("POST", "PUT", "PATCH", "DELETE")
        # CSRF: state-changing requests must carry a custom header, which other sites can't send without CORS (we allow none).
        if state_changing and self.headers.get("X-TablePlan") != "1":
            return self.send(403, {"error": "Missing X-TablePlan header"})
        # Browsers label cross-site requests; the API is only ever called by TablePlan's own pages.
        if (path.startswith("/api/") or state_changing) and self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self.send(403, {"error": "Cross-site request refused"})
        if not public and not self.authorized():
            if path.startswith("/api/"):
                return self.send(401, {"error": "Sign in required", "auth": True})
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            if self._req_len:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            return
        if not public and self.authorized():
            _app_url["url"] = f"{_req.scheme}://{host}"
        self._max_body = body_limit(path)
        if self._req_len > self._max_body:
            return self._reject(413, "Request too large")
        heavy = None
        for rx, bucket in EXPENSIVE:
            if rx.fullmatch(path):
                if path.endswith("/guided") and "1" not in (q.get("ai"), q.get("refresh")):
                    break   # cached / built-in step-by-step views are cheap
                if not rate_ok(bucket, self.client_ip()):
                    return self.send(429, {"error": "Too many requests. Wait a while and try again."},
                                     headers={"Retry-After": "600"})
                if bucket == "import":
                    heavy = _heavy
                break
        if heavy is not None and not heavy.acquire(timeout=30):
            return self.send(503, {"error": "TablePlan is busy with other imports. Try again in a minute."},
                             headers={"Retry-After": "30"})
        try:
            return self.route(method, path, q)
        except ApiError as e:
            return self.send(e.status, {"error": e.message, **(getattr(e, "extra", None) or {})})
        except (ValueError, KeyError, TypeError, AttributeError, IndexError, OverflowError) as e:
            log(f"bad request {method} {path}: {type(e).__name__}: {str(e)[:200]}")
            return self.send(400, {"error": "Bad request: " + (f"missing {e}" if isinstance(e, KeyError) else str(e)[:200])})
        except Exception:
            traceback.print_exc()
            return self.send(500, {"error": "Server error. Details are in the TablePlan log."})
        finally:
            if heavy is not None:
                heavy.release()

    def do_GET(self):
        self.handle_any("GET")

    def do_HEAD(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")

    def do_PATCH(self):
        self.handle_any("PATCH")

    def do_PUT(self):
        self.handle_any("PUT")

    def do_DELETE(self):
        self.handle_any("DELETE")

    # ---- routes
    def route(self, method, path, q):
        m = method
        self._sync_after = NATIVE and m != "GET" and bool(SYNC_PATHS.fullmatch(path))

        # static
        if m == "GET" and (path == "/" or path.startswith("/static/") or path in ("/manifest.webmanifest", "/sw.js")):
            return self.static(path, q)

        # ---- session / auth
        if m == "GET" and path == "/api/session":
            authed = self.authorized()
            with db() as c:
                people = n_users.chooser(c)
            return self.send(200, {"auth_required": auth_required(), "authed": authed, "public": PUBLIC_MODE,
                                   "needs_setup_code": PUBLIC_MODE and not cfg("app_password_hash") and not people,
                                   "backend": "native" if NATIVE else "mealie",
                                   "accounts": bool(people), "profiles": people if auth_required() else [],
                                   "household_password": bool(cfg("app_password_hash")) and not people,
                                   "me": self.user if authed else None,
                                   "needs_account": authed and not people and bool(cfg("setup_complete")),
                                   "pin_allowed": not PUBLIC_MODE,
                                   "setup_complete": bool(cfg("setup_complete")), "version": APP_VERSION})
        if m == "POST" and path == "/api/login":
            ip, b = self.client_ip(), self.body()
            uid = b.get("user_id")
            acct = int(uid) if isinstance(uid, int) or (isinstance(uid, str) and uid.isdigit() and len(uid) < 12) else None
            if login_throttled(ip, acct):
                raise ApiError(429, "Too many tries. Wait 10 minutes and try again.")
            if users_exist():
                if acct is None:
                    raise ApiError(400, "Choose who's signing in.")
                with db() as c:
                    row = n_users.verify(c, acct, b.get("secret") if isinstance(b.get("secret"), str) else "", PUBLIC_MODE)
                    tok = n_users.new_session(c, row["id"], time.time()) if row is not None else None
                if tok:
                    login_succeeded(ip, acct)
                    return self.send(200, {"ok": True, "me": n_users.public_user(row)},
                                     headers={"Set-Cookie": self.cookie(tok)})
                login_failed(ip, acct)
                log(f"failed sign-in for member {acct} from {ip}")
                time.sleep(1.0)
                with db() as c:
                    pin = (n_users.get(c, acct) or {"kind": ""})["kind"] == "pin"
                if pin and PUBLIC_MODE:
                    raise ApiError(401, "PIN sign-in is off because this TablePlan is on the internet. Ask your admin to set a password for you.")
                raise ApiError(401, "Wrong PIN" if pin else "Wrong password")
            pw = b.get("password") or ""
            if not auth_required() or password_ok(pw):
                login_succeeded(ip)
                return self.send(200, {"ok": True}, headers={"Set-Cookie": self.cookie(make_session())})
            login_failed(ip)
            log(f"failed sign-in from {ip}")
            time.sleep(1.0)
            raise ApiError(401, "Wrong password" if cfg("app_password_hash") else "Wrong setup code. Find it in the TablePlan server log.")
        if m == "POST" and path == "/api/logout":
            with db() as c:
                n_users.end_session(c, self.session_token())
            return self.send(200, {"ok": True}, headers={"Set-Cookie": self.cookie("", 0)})

        if m == "POST" and path == "/api/places/ensure":
            key = self.body().get("key")
            known = {"spices": "Spice cabinet", "baking": "Baking supplies"}
            if key not in known and key not in places():
                raise ApiError(404, "Unknown place.")
            if key in known:
                ensure_place(key, known[key])
            return self.send(200, {"locations": list(places().values())})
        # ---- accounts (everyone shares the household's data; accounts decide who's signed in)
        if path.startswith("/api/me") or path.startswith("/api/users") or path.startswith("/api/account") or path == "/api/checklist":
            return self.accounts_route(m, path)

        if m == "GET" and path == "/api/config":
            s = get_settings()
            base, slug = mealie_public(), cfg("group_slug")
            return self.send(200, {"mealie_url": base, "group_slug": slug,
                                   "email_ready": email_ready(), "mail_to": cfg("mail_to") or [], "settings": self.user_settings(s), "me": self.user,
                                   "channels": channels_ready(), "telegram_chat": cfg("telegram_chat_name"),
                                   "usda_synced_at": get_internal("usda_synced_at"),
                                   "setup_complete": bool(cfg("setup_complete")), "connected": NATIVE or bool(cfg("mealie_token")), "backend": "native" if NATIVE else "mealie",
                                   "household": {"name": cfg("household_name"), "people": cfg("people"),
                                                 "scale": bool(cfg("scale_to_household"))},
                                   "auth_required": auth_required(), "version": APP_VERSION,
                                   "repo_url": "https://github.com/thomasjvalenzuela/tableplan",
                                   "ai_key": bool(cfg("openai_key")),
                                   "storage": storage_info(),
                                   "import_url": f"{base}/g/{slug}/r/create/url",
                                   "import_image": f"{base}/g/{slug}/r/create",
                                   "planner_url": f"{base}/household/mealplan/planner/view"})

        # ---- setup wizard & settings
        if m == "GET" and path == "/api/setup/status":
            return self.send(200, setup_status())
        if m == "POST" and path == "/api/setup/household":
            b = self.body()
            people = max(1, min(30, _v_int(-10**6, 10**6)(b.get("people") or 2)))
            set_cfg(household_name=_s(b.get("name")).strip()[:60], people=people,
                    scale_to_household=bool(b.get("scale", True)))
            return self.send(200, setup_status()["household"])
        if m == "GET" and path == "/api/setup/mealie":
            return self.send(200, mealie_status())
        if m == "POST" and path == "/api/setup/mealie/create-account":
            b = self.body()
            return self.send(200, mealie_create_account(b.get("name", ""), b.get("email", ""), b.get("password", "")))
        if m == "POST" and path == "/api/setup/mealie/sign-in":
            b = self.body()
            return self.send(200, mealie_sign_in(b.get("email", ""), b.get("password", "")))
        if m == "POST" and path == "/api/setup/mealie/public":
            u = (self.body().get("url") or "").strip().rstrip("/")
            if u and not re.match(r"^https?://[^\s/]+", u):
                raise ApiError(400, "Enter a full address like https://recipes.example.com")
            set_cfg(mealie_public_url=u)
            return self.send(200, {"public_url": mealie_public(), "public_url_set": bool(u)})
        if m == "POST" and path == "/api/setup/mealie/token":
            b = self.body()
            return self.send(200, mealie_use_token(b.get("token", ""), b.get("url")))
        if m == "GET" and path == "/api/setup/ai":
            return self.send(200, ai_status())
        if m == "POST" and path == "/api/setup/ai":
            b = self.body()
            return self.send(200, ai_setup(b.get("api_key"), b.get("model"), bool(b.get("audio", True)),
                                           b.get("base_url") if not PUBLIC_MODE else None))
        if m == "GET" and path == "/api/setup/email":
            return self.send(200, email_public())
        if m == "POST" and path == "/api/setup/email":
            return self.send(200, email_setup(self.body()))
        if m == "GET" and path == "/api/setup/notify":
            return self.send(200, notify_status())
        if m == "POST" and path == "/api/setup/telegram":
            return self.send(200, telegram_set_token(self.body().get("token")))
        if m == "POST" and path == "/api/setup/telegram/verify":
            return self.send(200, telegram_verify())
        if m == "POST" and path == "/api/setup/ntfy":
            return self.send(200, ntfy_setup(self.body()))
        if m == "DELETE" and path in ("/api/setup/telegram", "/api/setup/ntfy", "/api/setup/email"):
            which = path.rsplit("/", 1)[1]
            set_cfg(**{"telegram": dict(telegram_token="", telegram_chat_id="", telegram_chat_name="", telegram_bot="",
                                        telegram_link_code=""),
                       "ntfy": dict(ntfy_topic="", ntfy_token=""),
                       "email": dict(smtp_host="", smtp_user="", smtp_password="", smtp_from="", mail_to=[])}[which])
            return self.send(200, notify_status())
        if m == "POST" and path == "/api/setup/password":
            if users_exist():
                raise ApiError(409, "Everyone signs in with their own account now. Change yours in Settings → Account.")
            pw = _s(self.body().get("password"), 1024)
            min_len = 8 if PUBLIC_MODE else 4
            if pw and len(pw) < min_len:
                raise ApiError(400, f"Use at least {min_len} characters.")
            if not pw and PUBLIC_MODE:
                raise ApiError(400, "A password is required because this TablePlan is reachable from the internet.")
            set_cfg(app_password_hash=hash_password(pw) if pw else "")
            rotate_sessions()   # every other device (and any setup-code sign-in) must sign in again
            log("household password " + ("changed" if pw else "removed") + f" from {self.client_ip()}; other sessions signed out")
            hdr = {"Set-Cookie": self.cookie(make_session())} if pw else None
            return self.send(200, {"set": bool(pw)}, headers=hdr)
        if m == "POST" and path == "/api/setup/import-mealie":
            return self.send(200, import_from_mealie(self.body()))
        if m == "POST" and path == "/api/setup/complete":
            set_cfg(setup_complete=True)
            seen = get_settings().get("whatsnew_seen") or []
            save_settings({"whatsnew_seen": (seen + [i for i in whatsnew_ids() if i not in seen])[-500:]})   # new install: nothing is "new"
            if self.user:
                self.put_user_state({"whatsnew_seen": whatsnew_ids()[-500:]})
            return self.send(200, {"ok": True})

        # ---- import & updates
        if m == "POST" and path == "/api/import/url":
            return self.send(200, import_url(_s(self.body().get("url"), 4000).strip()))
        if m == "POST" and path == "/api/import/text":
            b = self.body()
            return self.send(200, import_text(_s(b.get("text"), 200_000), _s(b.get("title"), 300)))
        if path == "/api/import/queue":
            if m == "POST":
                return self.send(200, import_queue_add(self.body(), (self.user or {}).get("id")))
            return self.send(200, import_queue_list())
        mm = re.fullmatch(r"/api/import/queue/(\d{1,12})(?:/(answer|retry|page/(\d{1,2})))?", path)
        if mm:
            jid, act = int(mm.group(1)), mm.group(2)
            if m == "GET" and act and act.startswith("page/"):
                n = int(mm.group(3))
                r = _job_row(jid)
                if not 1 <= n <= r["pages"] or not os.path.exists(_job_page_path(jid, n)):
                    raise ApiError(404, "Page not found")
                with open(_job_page_path(jid, n), "rb") as f:
                    return self.send(200, f.read(), "image/jpeg", {"Cache-Control": "private, max-age=3600"})
            if m == "POST" and act and act.startswith("page/"):
                return self.send(200, import_job_retake(jid, int(mm.group(3)), self.body()))
            if m == "POST" and act == "answer":
                return self.send(200, import_job_answer(jid, self.body()))
            if m == "POST" and act == "retry":
                return self.send(200, import_job_retry(jid))
            if m == "GET" and not act:
                return self.send(200, import_job_view(_job_row(jid)))
            if m == "DELETE" and not act:
                return self.send(200, import_job_dismiss(jid))
        if m == "POST" and path == "/api/import/images":
            b = self.body()
            return self.send(200, import_images(b.get("images") or [], b.get("text")))
        if m == "POST" and path == "/api/plan/to-list":
            b = self.body()
            return self.send(200, plan_to_list(*date_range(b.get("start"), b.get("end")),
                                               b.get("list_id"), bool(b.get("skip_pantry", True)), b.get("skip_keys")))
        if m == "POST" and path == "/api/plan/preview":
            b = self.body()
            return self.send(200, plan_preview(*date_range(b.get("start"), b.get("end"))))
        # ---- barcode lookup (Open Food Facts) & pantry check-ins
        if m == "POST" and path == "/api/scan":
            require_native()
            return self.send(200, scan_add(self.body()))
        if path == "/api/prices" and m in ("GET", "POST"):
            require_native()
            return self.send(200, prices_overview() if m == "GET" else price_set(self.body()))
        mm = re.fullmatch(r"/api/prices/(\d{1,12})", path)
        if m == "DELETE" and mm:
            return self.send(200, price_delete(int(mm.group(1))))
        if m == "PUT" and path == "/api/prices/config":
            return self.send(200, prices_config(self.body()))
        if m == "GET" and path == "/api/prices/kroger/locations":
            require_native()
            return self.send(200, kroger_locations(_s(q.get("zip"), 10)))
        if m == "POST" and path == "/api/prices/refresh":
            require_native()
            if not PRICE_REFRESH["running"]:
                threading.Thread(target=prices_refresh, kwargs={"force": True}, daemon=True, name="tp-prices").start()
            return self.send(200, {"ok": True, "running": True})
        mm = re.fullmatch(r"/api/costs/recipe/([^/]{1,200})", path)
        if m == "GET" and mm:
            return self.send(200, recipe_cost_api(urllib.parse.unquote(mm.group(1)), q))
        if m == "GET" and path == "/api/costs/plan":
            start, end = date_range(q.get("start"), q.get("end"))
            return self.send(200, plan_cost(start, end))
        if m == "GET" and path == "/api/costs/list":
            return self.send(200, list_costs())
        if m == "GET" and path == "/api/costs/recipes":
            require_native()
            return self.send(200, {"costs": recipe_costs_all()})
        if m == "GET" and path == "/api/budget":
            return self.send(200, budget_status())
        if m == "GET" and path == "/api/spending":
            return self.send(200, spending(q))
        if m == "GET" and path == "/api/ideas":
            return self.send(200, recipe_ideas(q))
        if m == "POST" and path == "/api/ideas/find":
            who = f"u{self.user['id']}" if getattr(self, "user", None) else self.client_ip()
            return self.send(200, find_ideas(self.body(), who))
        if m == "POST" and path in ("/api/ideas/save", "/api/ideas/dismiss"):
            return self.send(200, (idea_save if path.endswith("save") else idea_dismiss)(self.body()))
        mm = re.fullmatch(r"/api/ideas/image/([A-Za-z0-9:_%-]{1,80})", path)
        if m == "GET" and mm:
            blob, ctype = idea_image(urllib.parse.unquote(mm.group(1)))
            return self.send(200, blob, ctype, {"Cache-Control": "private, max-age=86400"})
        if path == "/api/ideas/config" and m in ("GET", "PUT"):
            require_native()
            return self.send(200, ideas_status() if m == "GET" else ideas_config(self.body()))
        if m == "GET" and path == "/api/pantry/export.csv":
            require_native()
            return self.download(pantry_export_csv(q), f"tableplan-inventory-{iso(today())}.csv", "text/csv; charset=utf-8")
        if m == "GET" and path == "/api/pantry/export":
            require_native()
            return self.send(200, {"rows": pantry_export_rows(q), "headers": CSV_HEADERS})
        if m == "POST" and path == "/api/demo":
            return self.send(200, demo_add())
        if m == "GET" and path == "/api/make":
            return self.send(200, what_can_i_make(q.get("food")))
        if m == "POST" and path == "/api/make/web":
            return self.send(200, make_web_suggestions(self.body()))
        if m == "POST" and path == "/api/scan/identify":
            require_native()
            return self.send(200, scan_identify(self.body()))
        if m == "GET" and path == "/api/scan/test":
            require_native()
            return self.send(200, upc_diagnose(_s(q.get("code"), 20)))
        mm = re.fullmatch(r"/api/pantry/(\d{1,12})/photo(/restore)?", path)
        if m == "POST" and mm:
            pid = int(mm.group(1))
            return self.send(200, pantry_photo_restore(pid) if mm.group(2) else pantry_photo(pid, self.body()))
        mm = re.fullmatch(r"/api/pantry/(\d{1,12})/(details|relookup|merge)", path)
        if m == "POST" and mm:
            require_native()
            pid = int(mm.group(1))
            act = mm.group(2)
            out = pantry_details(pid, self.body()) if act == "details" else pantry_merge(pid, self.body()) if act == "merge" else pantry_relookup(pid)
            self._sync_after = NATIVE
            return self.send(200, out)
        if m == "POST" and path == "/api/scan/photo":
            require_native()
            return self.send(200, scan_photo(self.body()))
        if m == "POST" and path == "/api/receipt":
            return self.send(200, receipt_read(self.body()))
        if m == "POST" and path == "/api/trip/apply":
            return self.send(200, trip_apply(self.body()))
        if m == "POST" and path == "/api/trip/scans":
            return self.send(200, trip_record_scans(self.body()))
        mm = re.fullmatch(r"/api/trip/(\d{1,12})/undo", path)
        if m == "POST" and mm:
            return self.send(200, trip_undo(int(mm.group(1))))
        if m == "POST" and path == "/api/scan/undo":
            return self.send(200, scan_undo(self.body()))
        mm = re.fullmatch(r"/api/scan/(\d{1,12})/(more|less)", path)
        if m == "POST" and mm:
            return self.send(200, scan_more(int(mm.group(1)), 1 if mm.group(2) == "more" else -1))
        mm = re.fullmatch(r"/img/pantry/(\d{1,12})", path)
        if m == "GET" and mm:
            with db() as c:
                r = c.execute("SELECT image FROM pantry_items WHERE id=?", (int(mm.group(1)),)).fetchone()
            fn = r["image"] if r else None
            if not fn or not re.fullmatch(r"\d{1,12}(-[0-9a-f]{6})?\.(jpg|png|webp|gif)", fn):
                return self.send(404, b"", "image/jpeg", {"Cache-Control": "no-cache"})
            with open(os.path.join(IMG_DIR, "pantry", fn), "rb") as f:
                return self.send(200, f.read(), mimetypes.guess_type(fn)[0] or "image/jpeg", {"Cache-Control": "private, max-age=86400"})
        mm = re.fullmatch(r"/api/upc/(\d{6,14})", path)
        if m == "GET" and mm:
            return self.send(200, upc_lookup(mm.group(1)))
        if m == "POST" and path == "/api/pantry/checked":
            set_internal("pantry_checked_at", datetime.now().isoformat(timespec="seconds"))
            return self.send(200, pantry_checkin_status())
        if m == "GET" and path == "/api/checkin":
            require_native()
            return self.send(200, checkin_cards())
        if m == "POST" and path in ("/api/checkin/answer", "/api/checkin/undo", "/api/checkin/done"):
            fn = {"answer": checkin_answer, "undo": checkin_undo, "done": checkin_finish}[path.rsplit("/", 1)[1]]
            out = fn(self.body())
            self._sync_after = NATIVE
            return self.send(200, out)
        if m == "GET" and path == "/api/pantry/expiring":
            return self.send(200, expiring_view())
        if m == "GET" and path == "/api/pantry/checkin":
            return self.send(200, pantry_checkin_status())
        # ---- recipes
        mm = re.fullmatch(r"/api/recipe/([A-Za-z0-9_.~%-]{1,200})", path)
        if m == "GET" and mm:
            return self.send(200, recipe_detail(urllib.parse.unquote(mm.group(1))))
        if m == "PUT" and mm:
            return self.send(200, recipe_update(urllib.parse.unquote(mm.group(1)), self.body()))
        if m == "DELETE" and mm:
            return self.send(200, recipe_delete(urllib.parse.unquote(mm.group(1))))
        mm = re.fullmatch(r"/api/recipe/([A-Za-z0-9_.~%-]{1,200})/image/(candidates|candidate/\d|ai|ai-pending|restore)", path)
        if mm:
            slug, act = urllib.parse.unquote(mm.group(1)), mm.group(2)
            if act == "candidates" and m == "GET":
                return self.send(200, recipe_photo_candidates(slug, q.get("more") == "1"))
            if act.startswith("candidate/") and m == "GET":
                blob, ctype = recipe_photo_candidate(slug, int(act.split("/")[1]))
                return self.send(200, blob, ctype, {"Cache-Control": "private, max-age=600"})
            if act == "ai" and m == "POST":
                return self.send(200, recipe_photo_ai(slug, self.body()))
            if act == "ai-pending" and m == "GET":
                blob, ctype = recipe_photo_pending(slug)
                return self.send(200, blob, ctype, {"Cache-Control": "no-store"})
            if act == "restore" and m == "POST":
                return self.send(200, recipe_photo_restore(slug))
        if m == "GET" and path == "/api/pans":
            return self.send(200, {"common": n_pans.COMMON, "owned": owned_pans()})
        mm = re.fullmatch(r"/api/recipe/([A-Za-z0-9_.~%-]{1,200})/pan", path)
        if mm and m in ("GET", "POST"):
            return self.send(200, recipe_pan_api(urllib.parse.unquote(mm.group(1)), m, q, self.body() if m == "POST" else {}))
        if m == "PUT" and path == "/api/photos/config":
            return self.send(200, photos_config(self.body()))
        mm = re.fullmatch(r"/api/recipe/([A-Za-z0-9_.~%-]{1,200})/(favorite|guided|image/next|image/upload|to-list|have-all|cooked|polish|restore-original|adjust|adjust/save|versions|versions/\d{1,3}/restore)", path)
        if mm:
            slug, act = urllib.parse.unquote(mm.group(1)), mm.group(2)
            if act == "adjust" and m == "POST":
                return self.send(200, recipe_adjust(slug, self.body()))
            if act == "adjust/save" and m == "POST":
                return self.send(200, recipe_adjust_save(slug, self.body()))
            if act == "versions" and m == "GET":
                return self.send(200, recipe_versions(slug))
            if act.startswith("versions/") and m == "POST":
                return self.send(200, recipe_version_restore(slug, int(act.split("/")[1])))
            if act == "polish" and m == "POST":
                return self.send(200, recipe_polish(slug))
            if act == "restore-original" and m == "POST":
                return self.send(200, recipe_restore_original(slug))
            if act == "cooked" and m == "POST":
                return self.send(200, recipe_cooked(slug, self.body()))
            if act == "have-all" and m == "POST":
                return self.send(200, recipe_have_all(slug))
            if act == "favorite" and m == "POST":
                return self.send(200, set_favorite(slug, bool(self.body().get("favorite", True))))
            if act == "guided" and m == "GET":
                ai = {"1": True, "0": False}.get(q.get("ai"))
                return self.send(200, guided(slug, ai, q.get("refresh") == "1"))
            if act == "image/next" and m == "POST":
                return self.send(200, recipe_image_next(slug))
            if act == "image/upload" and m == "POST":
                b = self.body()
                if NATIVE:
                    return self.send(200, save_recipe_photo(slug, b))
                blob, ctype = decode_upload(b.get("data"))
                _upload_recipe_image(slug, blob, ctype)
                return self.send(200, {"ok": True})
            if act == "to-list" and m == "POST":
                b = self.body()
                return self.send(200, add_items_to_list(b.get("items") or [], b.get("list_id")))
        if m == "GET" and path == "/img/ing":
            name = (q.get("name") or "").strip()[:80]
            if name and not _pick_row("ing", food_key(name) or name.lower()) and not rate_ok("fetch", self.client_ip()):
                return self.send(429, b"", "image/png", {"Retry-After": "600"})
            fpath, _ = ingredient_image(name) if name else (None, None)
            if not fpath:
                return self.send(404, b"", "image/png", {"Cache-Control": "public, max-age=3600"})
            with open(fpath, "rb") as f:
                blob = f.read()
            return self.send(200, blob, mimetypes.guess_type(fpath)[0] or "image/jpeg", {"Cache-Control": "public, max-age=600"})
        if m == "POST" and path == "/api/ingredient-image/next":
            name = (self.body().get("name") or "").strip()[:80]
            _, credit = ingredient_image(name, advance=True)
            return self.send(200, {"ok": True, "credit": credit})
        if m == "POST" and path == "/api/ingredient-image/upload":
            b = self.body()
            name = (b.get("name") or "").strip()[:80]
            blob, ctype = decode_upload(b.get("data"))
            _save_pick("ing", food_key(name) or name.lower(), 999, blob, ctype, "Your photo")
            return self.send(200, {"ok": True})
        # ---- AI spending
        if m == "GET" and path == "/api/ai/spending":
            if q.get("refresh") == "1":
                _costs_cache["at"] = 0
            return self.send(200, ai_spending())
        if m == "POST" and path == "/api/setup/openai-admin":
            k = (self.body().get("key") or "").strip()
            if k and not k.startswith("sk-admin-"):
                raise ApiError(400, "That isn't an Admin key. Admin keys start with sk-admin- (OpenAI → Settings → Organization → Admin keys).")
            prev = cfg("openai_admin_key")
            set_cfg(openai_admin_key=k)
            if k:
                try:
                    openai_costs(force=True)
                except ApiError as e:
                    set_cfg(openai_admin_key=prev or "")
                    raise ApiError(400, f"OpenAI rejected that key: {e.message}")
            return self.send(200, ai_spending())

        if m == "GET" and path == "/api/version":
            return self.send(200, update_info(force=q.get("refresh") == "1"))

        if m == "GET" and path == "/api/summary":
            return self.send(200, self.summary())

        if path == "/api/settings":
            if m == "PUT":
                b = self.body()
                mine = {k: validate_setting(k, b.pop(k)) for k in PER_USER_SETTINGS if isinstance(b, dict) and k in b}
                if mine and self.user:
                    self.put_user_state(mine)
                elif mine:
                    b.update(mine)   # no accounts: these stay household settings
                out = save_settings(b) if b else get_settings()
                return self.send(200, self.user_settings(out))
            return self.send(200, self.user_settings(get_settings()))

        # --- recipes & images
        if m == "GET" and path == "/api/foods":
            require_native()
            return self.send(200, foods_list(q.get("q", "")))
        mm = re.fullmatch(r"/api/foods/(\d{1,12})", path)
        if m == "PATCH" and mm:
            return self.send(200, food_update(int(mm.group(1)), self.body()))
        if m == "POST" and path == "/api/foods/merge":
            return self.send(200, foods_merge(self.body()))
        if m == "POST" and path == "/api/foods/unmerge":
            return self.send(200, foods_unmerge(self.body()))
        if path == "/api/diary":
            require_native()
            if m == "GET":
                f = q.get("filter", "all")
                return self.send(200, {"entries": diary_list(f if f in ("all", "top", "notes") else "all", min(500, int(q.get("limit") or 60) if str(q.get("limit") or "60").isdigit() else 60))})
            if m == "POST":
                return self.send(200, diary_add(self.body()))
        mm = re.fullmatch(r"/api/diary/(\d{1,12})(/photo)?", path)
        if mm:
            require_native()
            did = int(mm.group(1))
            if mm.group(2) and m == "POST":
                return self.send(200, diary_photo(did, self.body()))
            if m == "PATCH" and not mm.group(2):
                return self.send(200, diary_update(did, self.body()))
            if m == "DELETE" and not mm.group(2):
                return self.send(200, diary_delete(did, q.get("restore") == "1"))
        mm = re.fullmatch(r"/img/diary/(\d{1,12})", path)
        if m == "GET" and mm:
            with db() as c:
                r = c.execute("SELECT photo FROM diary WHERE id=?", (int(mm.group(1)),)).fetchone()
            fn = r["photo"] if r else None
            if not fn or not re.fullmatch(r"\d{1,12}\.(jpg|png|webp|gif)", fn):
                return self.send(404, b"", "image/jpeg", {"Cache-Control": "no-cache"})
            with open(os.path.join(IMG_DIR, "diary", fn), "rb") as f:
                return self.send(200, f.read(), mimetypes.guess_type(fn)[0] or "image/jpeg", {"Cache-Control": "private, max-age=86400"})
        mm = re.fullmatch(r"/api/reset/([a-z]{2,12})", path)
        if m == "POST" and mm:
            self.require_admin()
            return self.send(200, danger_reset(mm.group(1), self.body()))
        if m == "POST" and path == "/api/staples/add":
            return self.send(200, staples_add(self.body()))
        if m == "POST" and path == "/api/staples/remove":
            return self.send(200, staples_remove(self.body()))
        if m == "POST" and path == "/api/recipes/bulk":
            return self.send(200, recipes_bulk(self.body()))
        if m == "POST" and path == "/api/categories/rename":
            return self.send(200, category_rename(self.body()))
        if m == "POST" and path == "/api/categories/delete":
            return self.send(200, category_delete(self.body()))
        if m == "POST" and path == "/api/categories/undo-delete":
            return self.send(200, category_undo_delete(self.body()))
        if m == "GET" and path == "/api/recipes":
            pool = recipe_pool(refresh=q.get("refresh") == "1")
            tags = sorted({t for r in pool for t in r["tags"] + r["categories"] if t}, key=str.lower)
            costs = {}
            if NATIVE:
                try:
                    costs = recipe_costs_all()
                except Exception:
                    costs = {}
            return self.send(200, {"recipes": [{**r, "link": recipe_link(r["slug"]), **({"cost": costs[r["id"]]} if r["id"] in costs else {})}
                                               for r in pool], "tags": tags})

        mm = re.fullmatch(r"/img/([A-Za-z0-9-]{1,64})", path)
        if m == "GET" and mm:
            if not UUID_RE.fullmatch(mm.group(1)):   # recipe ids are UUIDs; they're used in file paths
                raise ApiError(404, "Not found")
            return self.image(mm.group(1), q.get("size", "min"))

        # --- meal plan
        if m == "GET" and path == "/api/plan":
            start, end = date_range(q.get("start"), q.get("end"))
            entries = enrich_plan(get_plans(start, end))
            return self.send(200, {"start": iso(start), "end": iso(end), "entries": entries})
        if m == "GET" and path == "/api/plan/status":
            return self.send(200, plan_status())
        if m == "POST" and path == "/api/plan/assign":
            return self.send(200, plan_assign(self.body()))
        if m == "POST" and path == "/api/plan/arrange":
            return self.send(200, plan_arrange(self.body()))
        if m == "POST" and path == "/api/plan/move":
            return self.send(200, plan_move(self.body()))
        if m == "POST" and path == "/api/plan/generate":
            return self.send(200, generate_plan(self.body()))
        if m == "POST" and path == "/api/plan/reroll":
            return self.send(200, reroll(self.body()))
        if m == "POST" and path == "/api/plan/save":
            b = self.body()
            entries = b.get("entries") or []
            if b.get("replace"):   # "Only fill empty days" off: new picks replace what's in those slots
                slots = {(e.get("date"), e.get("entry_type") or "dinner") for e in entries}
                dates = sorted(d for d, _ in slots if d)
                if dates:
                    for e in get_plans(parse_date(dates[0]), parse_date(dates[-1])):
                        if (e["date"], e["entry_type"]) in slots:
                            mealie("DELETE", f"/api/households/mealplans/{e['id']}")
            n = save_plan(entries)
            return self.send(200, {"created": n})
        mm = re.fullmatch(r"/api/plan/(\d{1,15})", path)
        if m == "DELETE" and mm:
            return self.send(200, plan_delete(int(mm.group(1))))
        mm = re.fullmatch(r"/api/plan/(\d{1,15})/uncook", path)
        if m == "POST" and mm:
            return self.send(200, plan_uncook(int(mm.group(1))))
        mm = re.fullmatch(r"/api/plan/(\d{1,15})/eat-at", path)
        if m == "PUT" and mm:
            return self.send(200, plan_eat_at(int(mm.group(1)), self.body()))
        mm = re.fullmatch(r"/api/plan/(\d{1,15})/skip", path)
        if m == "POST" and mm:
            return self.send(200, plan_skip(int(mm.group(1)), self.body().get("skipped", True) is not False))
        if m == "POST" and path == "/api/cooked/undo":
            return self.send(200, cooked_undo(self.body()))

        # --- the ongoing list and stores
        if m == "GET" and path == "/api/list":
            return self.send(200, ongoing_list())
        if m == "GET" and path == "/api/grocery/suggest":
            return self.send(200, grocery_suggest(q.get("q", "")))
        if m == "GET" and path == "/api/grocery/usual":
            return self.send(200, grocery_usual())
        if m == "GET" and path == "/api/grocery/catalog":
            return self.send(200, grocery_catalog_view())
        if m == "POST" and path == "/api/list/fulfill":
            return self.send(200, list_fulfill(self.body()))
        if m == "POST" and path == "/api/list/items":
            return self.send(200, list_add(self.body()))
        mm = re.fullmatch(r"/api/list/items/([A-Za-z0-9-]{1,64})(/have)?", path)
        if mm and ((m == "PATCH" and not mm.group(2)) or (m == "POST" and mm.group(2))):
            require_native()
            item_id = mm.group(1)
            with db() as c:
                it = n_lists.get_item(c, item_id)
            if not it:
                raise ApiError(404, "Item not on the list")
            if mm.group(2):
                with db() as c:
                    n_lists.mark_have(c, [item_id])
                    _have_to_pantry(c, [item_id])
                return self.send(200, {"ok": True})
            return self.send(200, self.patch_item(it, self.body()))
        if path == "/api/stores":
            if m == "GET":
                require_native()
                with db() as c:
                    return self.send(200, n_lists.list_stores(c))
            if m == "PUT":
                return self.send(200, stores_replace(self.json_any()))

        # --- backups
        if path == "/api/backups":
            if m == "GET":
                return self.send(200, list_backups())
            if m == "POST":
                return self.send(200, {"ok": True, "backup": make_backup(), "backups": list_backups()})
        mm = re.fullmatch(r"/backups/([^/]{1,160})", path)
        if m == "GET" and mm:
            p = backup_path(mm.group(1))
            with open(p, "rb") as f:
                return self.send_file(f, os.fstat(f.fileno()).st_size, "application/octet-stream", mm.group(1))
        if m == "GET" and path == "/export/backup.zip":
            if not _zip_lock.acquire(blocking=False):
                raise ApiError(503, "A backup download is already being prepared. Try again in a minute.")
            try:
                f, size = build_backup_zip()
            finally:
                _zip_lock.release()
            with f:
                return self.send_file(f, size, "application/zip", f"tableplan-backup-{iso(today())}.zip")

        # --- shopping lists
        if m == "GET" and path == "/api/lists":
            return self.send(200, {"lists": get_lists()})
        mm = re.fullmatch(r"/api/lists/([A-Za-z0-9-]{1,64})", path)
        if m == "GET" and mm:
            return self.send(200, list_json(get_list(mm.group(1))))
        if m == "POST" and path == "/api/recipes/new":
            name = (self.body().get("name") or "").strip()[:200]
            if not name:
                raise ApiError(400, "Give the recipe a name.")
            slug = mealie("POST", "/api/recipes", {"name": title_case(name)})
            _recipe_cache["at"] = 0
            return self.send(200, {"slug": slug.strip('"') if isinstance(slug, str) else slug})
        if m == "POST" and path == "/api/lists":
            name = (self.body().get("name") or "Groceries").strip()[:80]
            return self.send(200, {"id": mealie("POST", "/api/households/shopping/lists", {"name": name})["id"]})
        mm = re.fullmatch(r"/api/lists/([A-Za-z0-9-]{1,64})/items", path)
        if m == "POST" and mm:
            items = [str(t).strip()[:200] for t in (self.body().get("items") or []) if str(t).strip()][:100]
            if not items:
                raise ApiError(400, "Type at least one item.")
            return self.send(200, add_items_to_list(items, mm.group(1)))
        mm = re.fullmatch(r"/api/lists/([A-Za-z0-9-]{1,64})/items/([A-Za-z0-9-]{1,64})/(bought|undo)", path)
        if m == "POST" and mm:
            return self.send(200, self.bought(mm.group(1), mm.group(2), mm.group(3), self.body()))

        # --- pantry
        if path == "/api/pantry":   # (responses are sent after the transaction closes: the list sync needs the db)
            with db() as c:
                if m == "POST":
                    b = self.body()
                    if not (b.get("name") or "").strip():
                        raise ApiError(400, "Name is required")
                    iid = add_pantry_item(c, b["name"], b.get("location"), b.get("package_date"), b.get("quantity_text", ""))
                    out = pantry_json(c, pantry_row(c, iid))
                else:
                    out = {"items": list_pantry(c, q.get("status", "active"))}
            if m == "POST":
                self._sync_after = False
                sync_list()
                with db() as c:   # what the item has reserved after the sync
                    out = pantry_json(c, pantry_row(c, out["id"]))
            return self.send(200, out)
        if m == "POST" and path == "/api/pantry/bulk":
            out = pantry_bulk(self.body())
            self._sync_after = False
            sync_list()
            return self.send(200, out)
        mm = re.fullmatch(r"/api/pantry/(\d+)", path)
        if mm and m in ("PATCH", "POST"):
            with db() as c:
                apply_pantry_action(c, int(mm.group(1)), self.body())
            self._sync_after = False
            sync_list()
            with db() as c:
                row = pantry_row(c, int(mm.group(1)))
                out = pantry_json(c, row) if row else {"deleted": True}
            return self.send(200, out)
        if m == "GET" and path == "/api/pantry/match":
            with db() as c:
                r = match_rule(c, q.get("name", ""))
                return self.send(200, {"rule": dict(r) if r else None})

        # --- shelf-life rules
        if m == "GET" and path == "/api/rules":
            term = f"%{q.get('q', '').strip()}%"
            with db() as c:
                rows = c.execute("""SELECT * FROM shelf_rules WHERE name LIKE ? OR keywords LIKE ?
                                    ORDER BY CASE source WHEN 'custom' THEN 0 WHEN 'usda' THEN 1 ELSE 2 END, name LIMIT 60""",
                                 (term, term)).fetchall()
                counts = dict(c.execute("SELECT source, COUNT(*) FROM shelf_rules GROUP BY source").fetchall())
            return self.send(200, {"rules": [dict(r) for r in rows], "counts": counts})
        if m == "POST" and path == "/api/rules":
            b = self.body()
            if not (b.get("name") or "").strip():
                raise ApiError(400, "Name is required")
            with db() as c:
                insert_rule(c, {**b, **{f: _int_or_none(b.get(f)) for f in RULE_FIELDS}}, "custom")
                rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
                return self.send(200, dict(c.execute("SELECT * FROM shelf_rules WHERE id=?", (rid,)).fetchone()))
        mm = re.fullmatch(r"/api/rules/(\d+)", path)
        if m == "PUT" and mm:
            b = self.body()
            with db() as c:
                # Editing a USDA/starter rule turns it into a house rule so a re-sync never overwrites it.
                c.execute(f"""UPDATE shelf_rules SET name=COALESCE(?,name), keywords=COALESCE(?,keywords),
                              default_location=COALESCE(?,default_location), source='custom', usda_id=NULL,
                              {", ".join(f + "=?" for f in RULE_FIELDS)} WHERE id=?""",
                          (b.get("name"), b.get("keywords"), b.get("default_location"),
                           *[_int_or_none(b.get(f)) for f in RULE_FIELDS], int(mm.group(1))))
                return self.send(200, dict(c.execute("SELECT * FROM shelf_rules WHERE id=?", (int(mm.group(1)),)).fetchone()))
        if m == "POST" and path == "/api/rules/sync-usda":
            try:
                n = sync_usda()
            except Exception as e:
                raise ApiError(502, f"Couldn't sync USDA FoodKeeper: {e}. You can download foodkeeper.json manually "
                                    f"and drop it in the TablePlan data folder, then sync again.")
            return self.send(200, {"products": n, "synced_at": get_internal("usda_synced_at")})

        # --- send (email / Telegram / ntfy)
        if m == "POST" and path in ("/api/send", "/api/email"):
            b = self.body()
            channel = b.get("channel") or ("email" if path == "/api/email" else "all")
            res = deliver(build_msg(b), channel)
            return self.send(200, {"ok": True, **res, "to": cfg("mail_to")})

        # --- exports & print
        mm = re.fullmatch(r"/export/list/([A-Za-z0-9-]{1,64})\.(txt|csv)", path)
        if m == "GET" and mm:
            sl = get_list(mm.group(1))
            safe = re.sub(r"[^A-Za-z0-9_-]+", "-", sl.get("name") or "list")
            if mm.group(2) == "txt":
                return self.download(render_list_text(sl), f"{safe}.txt", "text/plain; charset=utf-8")
            return self.download(render_list_csv(sl), f"{safe}.csv", "text/csv; charset=utf-8")
        mm = re.fullmatch(r"/export/plan\.(csv|ics|txt)", path)
        if m == "GET" and mm:
            start, end = date_range(q.get("start"), q.get("end"))
            entries = get_plans(start, end)
            ext = mm.group(1)
            if ext == "ics":
                return self.download(render_plan_ics(entries), f"meal-plan-{iso(start)}.ics", "text/calendar; charset=utf-8")
            if ext == "txt":
                return self.download(render_plan_text(entries, start, end), f"meal-plan-{iso(start)}.txt", "text/plain; charset=utf-8")
            return self.download(render_plan_csv(entries), f"meal-plan-{iso(start)}.csv", "text/csv; charset=utf-8")
        mm = re.fullmatch(r"/export/recipe/([A-Za-z0-9_.~%-]{1,200})\.(txt|md|json)", path)
        if m == "GET" and mm:
            slug, ext = urllib.parse.unquote(mm.group(1)), mm.group(2)
            sv = _servings_arg(q.get("servings"))
            fname = f"{safe_filename(slug, 'recipe')}.{ext}"
            if ext == "txt":
                return self.download(render_recipe_text(slug, sv), fname, "text/plain; charset=utf-8")
            if ext == "md":
                return self.download(render_recipe_md(slug, sv), fname, "text/markdown; charset=utf-8")
            return self.download(render_recipe_json(slug, sv), fname, "application/json; charset=utf-8")
        mm = re.fullmatch(r"/print/recipe/([A-Za-z0-9_.~%-]{1,200})", path)
        if m == "GET" and mm:
            size = q.get("size") or "letter"
            style = q.get("style") or "classic"
            if size not in PRINT_SIZES or style not in ("classic", "steps") or q.get("photo", "1") not in ("0", "1"):
                raise ApiError(400, "Bad print options.")
            return self.send(200, print_recipe(urllib.parse.unquote(mm.group(1)), size, _servings_arg(q.get("servings")),
                                               style, q.get("photo", "1") == "1"), "text/html; charset=utf-8")
        if m == "GET" and path == "/export/pantry.csv":
            with db() as c:
                return self.download(render_pantry_csv(list_pantry(c)), "pantry.csv", "text/csv; charset=utf-8")
        mm = re.fullmatch(r"/print/list/([A-Za-z0-9-]{1,64})", path)
        if m == "GET" and mm:
            return self.send(200, print_list(get_list(mm.group(1))), "text/html; charset=utf-8")
        if m == "GET" and path == "/print/plan":
            start, end = date_range(q.get("start"), q.get("end"))
            return self.send(200, print_plan(get_plans(start, end), start, end), "text/html; charset=utf-8")
        if m == "GET" and path == "/print/pantry":
            with db() as c:
                return self.send(200, print_pantry(list_pantry(c)), "text/html; charset=utf-8")

        raise ApiError(404, "Not found")

    # ---- route helpers
    def summary(self):
        s = get_settings()
        out = {"today": iso(today()), "mealie_ok": True, "error": None}
        with db() as c:
            out["expiring"] = expiring_items(c, int(s.get("expiring_window_days") or 3))
            out["pantry_count"] = c.execute("SELECT COUNT(*) FROM pantry_items WHERE status='active'").fetchone()[0]
            out["review_items"] = c.execute("SELECT COUNT(*) FROM pantry_items WHERE status='active' AND review=1").fetchone()[0]
        out["pantry_checkin"] = pantry_checkin_status()
        try:
            start = today()
            out["week"] = enrich_plan(get_plans(start, start + timedelta(days=6)))
            out["plan_status"] = plan_status()
            lists = get_lists()
            out["lists"] = lists
            if lists:
                sl = get_list(lists[0]["id"])
                out["list_count"] = sum(1 for i in (sl.get("listItems") or []) if not i.get("checked"))
            else:
                out["list_count"] = 0
            out["recipe_count"] = len(recipe_pool())
            if NATIVE:
                with db() as c:
                    out["review_count"] = c.execute("SELECT COUNT(*) FROM import_jobs WHERE status='review' AND dismissed=0").fetchone()[0]
        except ApiError as e:
            out.update(mealie_ok=False, error=e.message, week=[], lists=[], list_count=0, recipe_count=0)
        return out

    def require_admin(self):
        """Resets and member management are for a household admin once accounts exist (always allowed before)."""
        if users_exist() and not (getattr(self, "user", None) or {}).get("admin"):
            raise ApiError(403, "Only a household admin can do that.")

    # ---- per-user state (falls back to one household-wide record before accounts exist)
    def get_user_state(self):
        if self.user:
            with db() as c:
                return n_users.get_state(c, self.user["id"])
        st = get_internal("anon_state", {})
        return st if isinstance(st, dict) else {}

    def put_user_state(self, patch):
        if self.user:
            with db() as c:
                return n_users.put_state(c, self.user["id"], patch)
        st = self.get_user_state()
        st.update({k: v for k, v in patch.items() if k in n_users.STATE_KEYS})
        set_internal("anon_state", st)
        return st

    def user_settings(self, s):
        if not self.user:
            return s
        st = self.get_user_state()
        return {**s, **{k: st[k] for k in PER_USER_SETTINGS if k in st}}

    def accounts_route(self, m, path):
        try:
            return self._accounts_route(m, path)
        except n_users.UserError as e:
            raise ApiError(400, str(e))

    def _signed_in_member(self):
        if not self.user:
            raise ApiError(400, "Create your account first (Settings → Account).")
        return self.user

    def _accounts_route(self, m, path):
        b = self.body() if m in ("POST", "PUT", "PATCH") else {}
        if not isinstance(b, dict):
            raise ApiError(400, "Expected a JSON object.")
        kind = b.get("kind") if b.get("kind") in ("password", "pin") else "password"
        secret = b.get("secret") if isinstance(b.get("secret"), str) else ""
        if m == "POST" and path == "/api/account/first":
            with db() as c:
                if n_users.count(c):
                    raise ApiError(409, "Accounts are already set up. Sign in, or ask an admin to add you.")
                row = n_users.create(c, b.get("name"), b.get("email"), kind, secret, PUBLIC_MODE, admin=True)
                hs = get_settings()
                n_users.put_state(c, row["id"], {"theme": hs.get("theme") or "system",
                                                 "whatsnew_seen": hs.get("whatsnew_seen") or [],
                                                 **{k: v for k, v in (get_internal("anon_state", {}) or {}).items()
                                                    if k in ("tour", "checklist")}})
                tok = n_users.new_session(c, row["id"], time.time())
            rotate_sessions()                     # household-password and setup-code sessions end now
            set_cfg(app_password_hash="")         # everyone signs in with their own account from here on
            log(f"first account created ({row['name']}) from {self.client_ip()}; household password retired")
            return self.send(200, {"me": n_users.public_user(row)}, headers={"Set-Cookie": self.cookie(tok)})
        if path == "/api/me":
            if m == "GET":
                st = self.get_user_state()
                return self.send(200, {"me": self.user, "state": st, "accounts": users_exist(),
                                       "tour_due": bool(cfg("setup_complete")) and tour_due(st.get("tour"), int(time.time() * 1000))})
            if m == "PATCH":
                me = self._signed_in_member()
                with db() as c:
                    row = n_users.update(c, me["id"], {k: b[k] for k in ("name", "email", "notify_email") if k in b}, False)
                return self.send(200, {"me": n_users.public_user(row)})
        if m == "POST" and path == "/api/me/secret":
            me, ip = self._signed_in_member(), self.client_ip()
            if login_throttled(ip, me["id"]):
                raise ApiError(429, "Too many tries. Wait 10 minutes and try again.")
            with db() as c:
                if n_users.verify(c, me["id"], b.get("current") if isinstance(b.get("current"), str) else "", False) is None:
                    login_failed(ip, me["id"])
                    raise ApiError(400, "Your current password or PIN isn't right.")
                n_users.set_secret(c, me["id"], kind, secret, PUBLIC_MODE)
                tok = n_users.new_session(c, me["id"], time.time())
            log(f"member {me['id']} changed their {kind}; their other devices were signed out")
            return self.send(200, {"ok": True, "kind": kind}, headers={"Set-Cookie": self.cookie(tok)})
        if m == "PUT" and path == "/api/me/state":
            patch = {}
            if "tour" in b:
                patch["tour"] = clean_tour(b["tour"])
            if "account_prompt" in b:
                patch["account_prompt"] = _v_int(0, 10**14)(b["account_prompt"] or 0)
            return self.send(200, {"state": self.put_user_state(patch)})
        if path == "/api/checklist":
            if m == "POST":
                checklist_action(self, b)
            return self.send(200, checklist_view(self))
        if path == "/api/users":
            if m == "GET":
                with db() as c:
                    return self.send(200, {"users": n_users.list_users(c) if (self.user or not n_users.count(c)) else [],
                                           "me": self.user, "pin_allowed": not PUBLIC_MODE})
            if m == "POST":
                self.require_admin()
                if not users_exist():
                    raise ApiError(400, "Create your own account first.")
                with db() as c:
                    row = n_users.create(c, b.get("name"), b.get("email"), kind, secret, PUBLIC_MODE, admin=bool(b.get("admin")))
                    n_users.put_state(c, row["id"], {"whatsnew_seen": whatsnew_ids()[-500:]})   # nothing is "new" to them
                log(f"member {row['name']} added by {self.user['name']}")
                return self.send(200, {"user": n_users.public_user(row)})
        mm = re.fullmatch(r"/api/users/(\d{1,9})(/secret)?", path)
        if mm:
            self.require_admin()
            uid, out = int(mm.group(1)), None
            with db() as c:   # commit before answering, so the next request sees the change
                if mm.group(2) and m == "POST":
                    n_users.set_secret(c, uid, kind, secret, PUBLIC_MODE)
                    log(f"{kind} reset for member {uid} by {self.user['name']}")
                    out = {"ok": True}
                elif m == "PATCH" and not mm.group(2):
                    out = {"user": n_users.public_user(n_users.update(c, uid, b, True))}
                elif m == "DELETE" and not mm.group(2):
                    if uid == self.user["id"]:
                        raise ApiError(400, "You can't remove yourself. Ask another admin.")
                    n_users.remove(c, uid)
                    log(f"member {uid} removed by {self.user['name']}")
                    out = {"ok": True}
            if out is not None:
                return self.send(200, out)
        raise ApiError(404, "Not found")

    def patch_item(self, it, b):
        """PATCH /api/list/items/{id}: store_id (remembered per food), text, checked (the bought / undo flow)."""
        item_id = it["id"]
        out = {"ok": True}
        if "text" in b:
            text = _s(b.get("text"), 200).strip()
            if not text:
                raise ApiError(400, "Type the item.")
            with db() as c:
                n_lists.set_item_text(c, item_id, text, parse_ing_text, aisle_for, resolve=_food_id)
        if "store_id" in b:
            with db() as c:
                try:
                    n_lists.set_item_store(c, item_id, _store_arg(b.get("store_id")), _item_key(it))
                except KeyError:
                    raise ApiError(404, "Store not found")
        if "checked" in b:
            if not isinstance(b["checked"], bool):
                raise ApiError(400, "checked must be true or false")
            if b["checked"] and not it["checked"]:
                out.update(self.bought(it["list_id"], item_id, "bought", b))
            elif not b["checked"] and it["checked"]:
                out.update(self.bought(it["list_id"], item_id, "undo", b))
        with db() as c:
            out["item"] = list_item_json(n_lists.get_item(c, item_id), _recipe_names(c))
        return out

    def bought(self, list_id, item_id, action, b):
        sl = get_list(list_id)
        with db() as c:
            if action == "bought":
                item = set_checked(sl, item_id, True)
                pid = None
                mode = b.get("to_pantry", "auto")
                name = b.get("name") or item_name(item)
                # "auto": only stock things we have shelf-life data for (skips paper towels, soap, etc.)
                if mode is True or (mode == "auto" and match_rule(c, name)):
                    q = _num(item.get("quantity"))
                    u = (item.get("unit") or {}).get("name") or ""
                    known = q is not None and q > 0 and (item.get("food") or u)
                    pid = add_pantry_item(c, name, b.get("location"), b.get("package_date"), item_text(item), item_id,
                                          q if known else None, u if known else None)
                return {"ok": True, "pantry_item": pantry_json(c, pantry_row(c, pid)) if pid else None}
            set_checked(sl, item_id, False)
            if b.get("pantry_item_id"):
                c.execute("DELETE FROM pantry_items WHERE id=? AND mealie_item_id=?", (b["pantry_item_id"], item_id))
            else:   # unticked later (e.g. after a reload): drop the pantry item that tick created, if it's untouched
                cut = (datetime.now() - timedelta(hours=CHECKED_VISIBLE_HOURS)).isoformat(timespec="seconds")
                c.execute("DELETE FROM pantry_items WHERE mealie_item_id=? AND status='active' AND created_at>=? "
                          "AND opened_on IS NULL AND amount_left>=1", (item_id, cut))
            return {"ok": True}

    def image(self, recipe_id, size):
        if NATIVE:
            fp = n_recipes.image_path(IMG_DIR, recipe_id)
            if not fp:
                return self.send(404, b"", "image/webp", {"Cache-Control": "public, max-age=600"})
            # card (800) and thumb (320) made when the photo was cropped; ignored if the photo changed since
            want = {"min": ("card",), "tiny": ("thumb", "card")}.get(size, ())
            d, t0 = os.path.dirname(fp), os.path.getmtime(fp)
            for w in want:
                alt = next((os.path.join(d, x) for x in os.listdir(d) if x.startswith(w + ".")), None)
                if alt and os.path.getmtime(alt) >= t0 - 1:
                    fp = alt
                    break
            with open(fp, "rb") as f:
                return self.send(200, f.read(), mimetypes.guess_type(fp)[0] or "image/jpeg", {"Cache-Control": "public, max-age=86400"})
        fname = {"min": "min-original.webp", "tiny": "tiny-original.webp", "full": "original.webp"}.get(size, "min-original.webp")
        try:
            with _open(f"{cfg('mealie_url')}/api/media/recipes/{recipe_id}/images/{fname}", timeout=15,
                       allow_private=True) as r:
                data = _read_capped(r, 20_000_000, 60)
            return self.send(200, data, "image/webp", {"Cache-Control": "public, max-age=86400"})
        except Exception:
            return self.send(404, b"", "image/webp", {"Cache-Control": "public, max-age=600"})

    def static(self, path, q=None):
        rel = {"/": "index.html", "/manifest.webmanifest": "manifest.webmanifest", "/sw.js": "sw.js"}.get(path) \
            or path[len("/static/"):]
        full = os.path.realpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(os.path.realpath(STATIC_DIR) + os.sep) or not os.path.isfile(full):
            raise ApiError(404, "Not found")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".webmanifest"):
            ctype = "application/manifest+json"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/manifest+json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            data = f.read()
        if rel == "index.html":
            data = look_index(data, self.headers.get("Cookie") or "")
            # Versioned asset URLs: a Home Screen app picks up new code as soon as the server is updated.
            v = urllib.parse.quote(APP_VERSION, safe="")
            for a in VERSIONED_ASSETS:
                data = data.replace(f'"/static/{a}"'.encode(), f'"/static/{a}?v={v}"'.encode())
            return self.send(200, data, ctype, {"Cache-Control": "no-store"})
        if rel in VERSIONED_ASSETS and (q or {}).get("v") == APP_VERSION:
            return self.send(200, data, ctype, {"Cache-Control": "public, max-age=31536000, immutable"})
        return self.send(200, data, ctype, {"Cache-Control": "no-cache"})


# Changes to inventory or recipes that can change what the planned meals still need from the store.
SYNC_PATHS = re.compile(r"/api/pantry(/\d+)?|/api/list/items/[A-Za-z0-9-]{1,64}(/have)?|/api/lists/[^/]+/items/[^/]+/(bought|undo)"
                        r"|/api/scan(/.*)?|/api/trip/.*|/api/recipe/[^/]+(/have-all|/polish|/restore-original)?|/api/plan/(save|generate)"
                        r"|/api/recipes/bulk|/api/staples/.*|/api/recipe/[^/]+/(adjust/save|versions/\d+/restore)")
# The look (theme + light/dark) is applied before the first paint: the browser sends its choice as a cookie and the
# page arrives with the attributes already set (no inline script needed under the strict CSP).
LOOK_COLORS = {"mono": ("#FFFFFF", "#000000"), "midnight": ("#FFFFFF", "#050B1A"), "blossom": ("#FFF5F7", "#0D070B"),
               "forest": ("#F3FAF6", "#07120E")}


def look_index(data, cookie_header):
    m = re.search(r"(?:^|;\s*)tp_look=([a-z]+)\.([a-z]+)(?:;|$)", cookie_header)
    if not m or m.group(1) not in LOOK_COLORS or m.group(2) not in ("system", "light", "dark"):
        return data
    theme, mode = m.group(1), m.group(2)
    attrs = f' data-theme="{theme}"' + (f' data-mode="{mode}"' if mode != "system" else "")
    data = data.replace(b'<html lang="en">', f'<html lang="en"{attrs}>'.encode(), 1)
    light, dark = LOOK_COLORS[theme]
    if mode != "system":
        light = dark = (dark if mode == "dark" else light)
    data = data.replace(b'content="#FFFFFF" media="(prefers-color-scheme: light)"', f'content="{light}" media="(prefers-color-scheme: light)"'.encode(), 1)
    data = data.replace(b'content="#000000" media="(prefers-color-scheme: dark)"', f'content="{dark}" media="(prefers-color-scheme: dark)"'.encode(), 1)
    return data


VERSIONED_ASSETS = ("app.css", "app.js", "recipes.js", "setup.js", "accounts.js", "scan.js")


def _int_or_none(v):
    if v in (None, ""):
        return None
    try:
        return max(0, int(float(v)))
    except (TypeError, ValueError):
        return None


class Server(ThreadingHTTPServer):
    """ThreadingHTTPServer with a cap on simultaneous connections (each one is a thread)."""
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, *a, max_conns=None, **kw):
        self._slots = threading.BoundedSemaphore(max_conns or int(env("TABLEPLAN_MAX_CONNECTIONS", "64") or 64))
        super().__init__(*a, **kw)

    def process_request(self, request, client_address):
        if not self._slots.acquire(timeout=10):   # all busy: drop rather than pile up threads
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def secure_data_dir():
    """Keep the database, secrets and photos readable by this process only (0700 dirs / 0600 files)."""
    os.umask(0o077)
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    for f in (DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm"):
        try:
            if os.path.exists(f):
                os.chmod(f, 0o600)
        except OSError:
            pass
    try:
        if os.path.isdir(IMG_DIR):
            os.chmod(IMG_DIR, 0o700)
    except OSError:
        pass


def main():
    secure_data_dir()
    try:
        pre_upgrade_snapshot()
    except Exception as e:
        log("pre-upgrade snapshot failed:", e)
    init_db()
    secure_data_dir()
    load_cfg()
    startup_storage()
    if not get_internal("usda_synced_at"):
        def first_sync():
            try:
                sync_usda()
            except Exception as e:
                log(f"USDA FoodKeeper sync skipped ({e}); using starter shelf-life table. Retry from Settings.")
        threading.Thread(target=first_sync, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    threading.Thread(target=guided_warmer, daemon=True, name="tp-guided-warm").start()
    if NATIVE:
        threading.Thread(target=import_worker, daemon=True, name="tp-import").start()
    if PUBLIC_MODE and not cfg("app_password_hash"):
        log(f"PUBLIC MODE · one-time setup code: {SETUP_CODE}  (enter it on the sign-in screen, then set a household password)")
    log(f"TablePlan {APP_VERSION} listening on :{LISTEN_PORT} · {'public' if PUBLIC_MODE else 'home network'} mode"
        f"{' · trusting proxy headers' if TRUST_PROXY else ''} · backend {'native' if NATIVE else 'Mealie'} · data {DB_PATH} · "
        f"setup {'done' if cfg('setup_complete') else 'pending — open the app to run the wizard'}")
    Server(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
