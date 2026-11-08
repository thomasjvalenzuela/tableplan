"""
TablePlan — a family kitchen dashboard that sits on top of Mealie.

Mealie (separate container) owns recipes, AI screenshot/link import, scaling,
meal-plan storage and shopping lists. TablePlan adds:

  * one-tap meal-plan generation for a week or month from your recipe pool
  * a pantry with expiration tracking driven by USDA FoodKeeper shelf-life data
    (mark something opened / used half → the rest gets the "after opening" date)
  * shopping list → pantry: tick an item off and it's stocked with a due date
  * email (SMTP), print, CSV, TXT and calendar (.ics) exports
  * an Apple Home–style mobile UI (static/)

Pure Python standard library + SQLite. No pip installs.
"""

import base64
import csv
import hashlib
import ipaddress
import socket
import hmac
import html
import io
import json
import mimetypes
import os
import random
import re
import smtplib
import sqlite3
import ssl
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import uuid
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/manifest+json", ".webmanifest")
STATIC_DIR = os.path.join(HERE, "static")
SEED_FILE = os.path.join(HERE, "seed", "starter_shelf_life.json")


def env(name, default=""):
    return os.environ.get(name, default)


def log(*a):
    print("[tableplan]", *a, flush=True)


DATA_DIR = env("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "tableplan.db")
LISTEN_PORT = int(env("LISTEN_PORT", "8080"))
APP_VERSION = (open(os.path.join(HERE, "VERSION")).read().strip()
               if os.path.exists(os.path.join(HERE, "VERSION")) else "dev")
UPDATE_FEED = env("TABLEPLAN_UPDATE_FEED", "https://thomasjvalenzuela.github.io/tableplan/version.json")
INSTALL_METHOD = env("TABLEPLAN_INSTALL", "zimaos")
NATIVE = env("TABLEPLAN_BACKEND", "native").lower() != "mealie"   # native = TablePlan's own storage (no Mealie)   # zimaos | cli | manual
# Set TABLEPLAN_PUBLIC=1 when TablePlan is reachable from the internet (custom domain, Railway, …):
# sign-in is then always required, and until a household password exists the one-time setup code
# printed in the server log is the only way in.
PUBLIC_MODE = env("TABLEPLAN_PUBLIC", "").lower() in ("1", "true", "yes")
SETUP_CODE = base64.b32encode(os.urandom(5)).decode()

FOODKEEPER_URL = env("FOODKEEPER_URL", "https://www.fsis.usda.gov/shared/data/EN/foodkeeper.json")

LOCATIONS = ("fridge", "freezer", "pantry")
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
    "oven": "conventional",           # conventional | convection
    "temp_unit": "F",                 # F | C
    "ai_budget": 0,                   # monthly USD; 0 = no alert
    "pantry_check_days": 7,           # remind to review the pantry every N days (0 = off)
    "expiring_window_days": 3,
}



# ============================================================ database

_db_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
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
  expiry_source TEXT DEFAULT 'estimate',        -- estimate | package | manual | none
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
CREATE TABLE IF NOT EXISTS recipe_cache (
  id TEXT PRIMARY KEY, updated TEXT, foods TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
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
CREATE TABLE IF NOT EXISTS image_picks (
  kind TEXT, key TEXT, idx INTEGER DEFAULT 0, file TEXT, credit TEXT, missing INTEGER DEFAULT 0, updated TEXT,
  PRIMARY KEY (kind, key)
);
"""


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with db() as c:
        c.executescript(SCHEMA)
        n_recipes.init(c); n_plans.init(c); n_lists.init(c)
        if c.execute("SELECT COUNT(*) FROM shelf_rules").fetchone()[0] == 0:
            seed = json.load(open(SEED_FILE, encoding="utf-8"))
            for r in seed["rules"]:
                insert_rule(c, r, r.get("source", "starter"))
            log(f"seeded {len(seed['rules'])} starter shelf-life rules")


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


def save_settings(patch):
    allowed = set(DEFAULT_SETTINGS)
    with db() as c:
        for k, v in patch.items():
            if k in allowed:
                c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (k, json.dumps(v)))
    return get_settings()


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
               "openai_key", "openai_admin_key",
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
        good = hmac.new(cfg("session_secret").encode(), ts.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, good) and time.time() - int(ts) < 180 * 86400
    except (ValueError, AttributeError):
        return False


def auth_required():
    return bool(cfg("app_password_hash")) or PUBLIC_MODE


def password_ok(pw):
    if cfg("app_password_hash"):
        return check_password(pw, cfg("app_password_hash"))
    return PUBLIC_MODE and hmac.compare_digest(pw.strip().upper(), SETUP_CODE)


_login_fails = {}


def login_throttled(ip):
    now = time.time()
    fails = [t for t in _login_fails.get(ip, []) if now - t < 600]
    _login_fails[ip] = fails
    return len(fails) >= 8


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
            req = urllib.request.Request(FOODKEEPER_URL, headers={
                "User-Agent": "Mozilla/5.0 (TablePlan self-hosted; FoodKeeper sync)",
                "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw_bytes = r.read()
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


def add_pantry_item(c, name, location=None, package_date=None, quantity_text="", mealie_item_id=None):
    rule = match_rule(c, name)
    loc = location if location in LOCATIONS else (rule["default_location"] if rule else "fridge")
    t = today()
    pkg = parse_date(package_date)
    if pkg:
        exp, src = pkg, "package"
    else:
        d = sealed_days(rule, loc)
        exp, src = (t + timedelta(days=d), "estimate") if d else (None, "none")
    cur = c.execute(
        """INSERT INTO pantry_items(name, quantity_text, location, purchased_on, frozen_on, expires_on,
           expiry_source, rule_id, mealie_item_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (name.strip(), quantity_text or "", loc, iso(t), iso(t) if loc == "freezer" else None, iso(exp), src,
         rule["id"] if rule else None, mealie_item_id, datetime.now().isoformat(timespec="seconds")))
    event(c, cur.lastrowid, "added", f"{loc}; expires {iso(exp) or 'unknown'}")
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

    if action == "use":
        left = float(body.get("left", 0))
        left = max(0.0, min(1.0, left))
        if left <= 0.001:
            c.execute("UPDATE pantry_items SET amount_left=0, status='used', finished_on=? WHERE id=?", (iso(t), item_id))
            event(c, item_id, "finished")
            return
        updates = {"amount_left": left}
        if not item["opened_on"] and item["location"] != "freezer":
            updates["opened_on"] = iso(t)
            od = opened_days(rule, item["location"])
            if od:
                new_exp = t + timedelta(days=od)
                # Opening can only shorten shelf life, never extend a sooner package date.
                if not exp or new_exp < exp:
                    updates["expires_on"] = iso(new_exp)
                    updates["expiry_source"] = "estimate"
        sets = ", ".join(f"{k}=?" for k in updates)
        c.execute(f"UPDATE pantry_items SET {sets} WHERE id=?", (*updates.values(), item_id))
        event(c, item_id, "used", f"{round(left * 100)}% left; expires {updates.get('expires_on', item['expires_on'])}")

    elif action == "open":
        if item["opened_on"]:
            return
        od = opened_days(rule, item["location"])
        new_exp = t + timedelta(days=od) if od else exp
        if exp and new_exp and exp < new_exp:
            new_exp = exp
        c.execute("UPDATE pantry_items SET opened_on=?, expires_on=? WHERE id=?", (iso(t), iso(new_exp), item_id))
        event(c, item_id, "opened", f"expires {iso(new_exp)}")

    elif action == "move":
        loc = body.get("location")
        if loc not in LOCATIONS:
            raise ApiError(400, "Bad location")
        if loc == item["location"]:
            return
        new_exp = exp
        frozen_on = item["frozen_on"]
        if loc == "freezer":
            fz = rule["freezer"] if rule else None
            new_exp = t + timedelta(days=fz) if fz else exp
            frozen_on = iso(t)
        elif item["location"] == "freezer":
            # Thawing: use the after-thawing window, falling back to the opened window.
            th = (rule["thawed_fridge"] or rule["opened_fridge"]) if rule else None
            new_exp = t + timedelta(days=th) if th else None
            frozen_on = None
        else:
            # Pantry <-> fridge: recompute from the right column, keep the sooner date.
            d = (opened_days if item["opened_on"] else sealed_days)(rule, loc)
            if d:
                cand = t + timedelta(days=d)
                new_exp = cand if (not exp or item["expiry_source"] != "package") else min(exp, cand)
        c.execute("UPDATE pantry_items SET location=?, frozen_on=?, expires_on=?, expiry_source=? WHERE id=?",
                  (loc, frozen_on, iso(new_exp), "estimate" if new_exp else "none", item_id))
        event(c, item_id, "moved", f"to {loc}; expires {iso(new_exp)}")

    elif action == "set_date":
        d = parse_date(body.get("expires_on"))
        c.execute("UPDATE pantry_items SET expires_on=?, expiry_source=? WHERE id=?",
                  (iso(d), "manual" if d else "none", item_id))
        event(c, item_id, "date set", iso(d) or "cleared")

    elif action == "rule":
        rid = body.get("rule_id")
        r = c.execute("SELECT * FROM shelf_rules WHERE id=?", (rid,)).fetchone() if rid else None
        if rid and not r:
            raise ApiError(404, "Rule not found")
        key = food_key(item["name"])
        if r:
            c.execute("INSERT INTO food_map(food_key, rule_id) VALUES (?,?) ON CONFLICT(food_key) DO UPDATE SET rule_id=excluded.rule_id",
                      (key, r["id"]))
        # Recompute expiry from purchase/open dates with the new rule (package/manual dates are kept).
        new_exp, src = exp, item["expiry_source"]
        if src not in ("package", "manual"):
            base_open = parse_date(item["opened_on"])
            if item["location"] == "freezer":
                d, start = (r["freezer"] if r else None), parse_date(item["frozen_on"]) or t
            elif base_open:
                d, start = opened_days(r, item["location"]), base_open
            else:
                d, start = sealed_days(r, item["location"]), parse_date(item["purchased_on"]) or t
            new_exp, src = (start + timedelta(days=d), "estimate") if d else (None, "none")
        c.execute("UPDATE pantry_items SET rule_id=?, expires_on=?, expiry_source=? WHERE id=?",
                  (r["id"] if r else None, iso(new_exp), src, item_id))
        event(c, item_id, "rule", r["name"] if r else "none")

    elif action == "rename":
        name = (body.get("name") or "").strip()
        if name:
            c.execute("UPDATE pantry_items SET name=?, quantity_text=? WHERE id=?",
                      (name, body.get("quantity_text", item["quantity_text"]), item_id))

    elif action == "toss":
        c.execute("UPDATE pantry_items SET status='tossed', finished_on=? WHERE id=?", (iso(t), item_id))
        event(c, item_id, "tossed")

    elif action == "restore":
        c.execute("UPDATE pantry_items SET status='active', finished_on=NULL, amount_left=CASE WHEN amount_left<=0 THEN 1 ELSE amount_left END WHERE id=?", (item_id,))
        event(c, item_id, "restored")

    elif action == "delete":
        c.execute("DELETE FROM pantry_items WHERE id=?", (item_id,))
    else:
        raise ApiError(400, "Unknown action")


def pantry_json(c, row):
    t = today()
    exp = parse_date(row["expires_on"])
    rule = rule_for(c, row)
    return {
        "id": row["id"], "name": row["name"], "quantity_text": row["quantity_text"],
        "location": row["location"], "amount_left": row["amount_left"],
        "purchased_on": row["purchased_on"], "opened_on": row["opened_on"], "frozen_on": row["frozen_on"],
        "expires_on": row["expires_on"], "expiry_source": row["expiry_source"],
        "days_left": (exp - t).days if exp else None, "status": row["status"], "emoji": food_emoji(row["name"]),
        "rule": {"id": rule["id"], "name": rule["name"], "source": rule["source"],
                 **{f: rule[f] for f in RULE_FIELDS}, "tips": rule["tips"]} if rule else None,
    }


def list_pantry(c, status="active"):
    rows = c.execute(
        """SELECT * FROM pantry_items WHERE status=? ORDER BY
           CASE WHEN expires_on IS NULL THEN 1 ELSE 0 END, expires_on, name COLLATE NOCASE""", (status,)).fetchall()
    return [pantry_json(c, r) for r in rows]


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
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
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


def _fetch_page(url):
    if not re.match(r"^https?://", url or "") or not _public_host(url):
        raise ApiError(400, "That link can't be opened. Use a public https:// recipe page.")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            final = r.geturl()
            if not _public_host(final):
                raise ApiError(400, "That link redirects somewhere TablePlan can't open.")
            raw = r.read(6_000_000)
            charset = r.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as e:
        if e.code in (401, 402, 403, 429):
            raise ApiError(502, "That site blocks apps from reading its recipes (it may need a subscription). "
                                "Take screenshots of the recipe and use the Screenshot tab instead.")
        raise ApiError(502, f"The site returned an error ({e.code}). Try a screenshot instead.")
    except urllib.error.URLError as e:
        raise ApiError(502, f"Couldn't open that page ({e.reason}).")
    return final, raw.decode(charset, errors="replace")


AI_RECIPE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["found", "complete", "missing", "source_url", "name", "description", "servings", "prep_minutes", "cook_minutes", "total_minutes", "ingredients", "steps", "tags"],
    "properties": {
        "found": {"type": "boolean"}, "complete": {"type": "boolean"}, "missing": {"type": "string"}, "source_url": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"},
        "servings": {"type": "number"}, "prep_minutes": {"type": "integer"}, "cook_minutes": {"type": "integer"},
        "total_minutes": {"type": "integer"},
        "ingredients": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["section", "line"],
                                                    "properties": {"section": {"type": "string"}, "line": {"type": "string"}}}},
        "steps": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}


def ai_recipe(text, images=None, feature="recipe import", detail=""):
    """Turn free text and/or images into a recipe (Mealie-shaped dict) with OpenAI."""
    if not cfg("openai_key"):
        raise ApiError(400, "This needs AI. Add your OpenAI key in Settings → AI recipe import.")
    content = [{"type": "text", "text": (
        "Extract the single recipe from the material below. Clean up typos, spacing and formatting, but never change the recipe: keep every amount, ingredient, temperature, time and step exactly. Copy ingredient lines with amounts, amount first "
        "(e.g. '1 1/2 cups heavy cream'); put section headings in 'section' (empty if none). Steps are the instructions "
        "in order, one per item. source_url: the recipe's web address if one is visible (e.g. in a page header or footer), else empty. Use 0 for unknown numbers. If there is no recipe, set found=false. Never invent content. Set complete=false when part of the recipe is clearly missing: no ingredient list, no instructions, text cut off mid-list or mid-step (e.g. a second page or screenshot wasn't included), or steps that use ingredients the list doesn't include; then explain what's missing in 'missing' (one short sentence). Missing amounts in a spoken video recipe do not count as incomplete.")
        + (f"\n\n{text[:30000]}" if text else "")}]
    for im in images or []:
        data = im.get("data") or ""
        if data.startswith("data:application/pdf"):
            content.append({"type": "file", "file": {"filename": im.get("name") or "recipe.pdf", "file_data": data}})
            continue
        if not data.startswith("data:image/"):
            data = "data:image/jpeg;base64," + data.split(",", 1)[-1]
        content.append({"type": "image_url", "image_url": {"url": data, "detail": "high"}})
    try:
        out = openai_chat([{"role": "user", "content": content}], "recipe", AI_RECIPE_SCHEMA, feature, detail)
    except AIUnreadable:
        content[0] = {"type": "text", "text": (
            "Extract the single recipe from the material below and reply in EXACTLY this plain-text format, nothing else:\n"
            "SOURCE: <web address shown in the material, or blank>\nTITLE: <name>\nDESCRIPTION: <one sentence or blank>\nSERVINGS: <number or 0>\nPREP: <minutes or 0>\n"
            "COOK: <minutes or 0>\nTOTAL: <minutes or 0>\nTAGS: <comma separated>\nINGREDIENTS:\n<one ingredient per line, amount first; "
            "a line starting with # is a section heading>\nSTEPS:\n<one step per line>\n"
            "Copy amounts exactly and never invent content. If there is no recipe, reply only: NO RECIPE. If part of the recipe is clearly missing (no ingredients, no steps, or cut off), reply only: INCOMPLETE: <what's missing>")
            + (f"\n\n{text[:30000]}" if text else "")}
        out = parse_recipe_text(openai_text([{"role": "user", "content": content}], feature + " (text)", detail))
    if out.get("complete") is False or out.get("incomplete"):
        raise ApiError(422, "This recipe looks incomplete, so it wasn't saved: " + (out.get("missing") or out.get("incomplete") or "part of it is missing")
                       + " Add the missing part (another screenshot or the rest of the text) and try again.")
    if not out.get("found") or not (out.get("ingredients") or out.get("steps")):
        raise ApiError(422, "No recipe found there. Try a clearer screenshot that shows the ingredients and steps.")
    ings = [{"referenceId": str(uuid.uuid4()), "title": (x.get("section") or None), "note": x["line"], "display": x["line"],
             "originalText": x["line"], "quantity": 0, "unit": None, "food": None} for x in out["ingredients"] if x.get("line")]
    last = None
    for g in ings:   # only the first line of a section carries its title
        g["title"], last = (g["title"] if g["title"] != last else None), g["title"] or last
    mins = lambda v: int(v) * 60 if v else None  # noqa: E731
    src = (out.get("source_url") or "").strip()
    return {"name": out["name"] or "Untitled recipe", "description": out.get("description") or "",
            "orgURL": src if re.match(r"^https?://", src) else "",
            "recipeServings": float(out.get("servings") or 0), "prepTimeSeconds": mins(out.get("prep_minutes")),
            "performTimeSeconds": mins(out.get("cook_minutes")),
            "totalTimeSeconds": mins(out.get("total_minutes")) or ((mins(out.get("prep_minutes")) or 0) + (mins(out.get("cook_minutes")) or 0)) or None,
            "recipeIngredient": ings,
            "recipeInstructions": [{"id": str(uuid.uuid4()), "title": "", "text": s, "ingredientReferences": []} for s in out["steps"] if s.strip()],
            "tags": [{"name": t} for t in (out.get("tags") or [])[:8]]}


def _save_new_recipe(data, image_url=None):
    with db() as c:
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
                return n_recipes.get(c, n_recipes.update(c, key, body or {}))
            if method == "DELETE":
                n_recipes.delete(c, key, images_dir=IMG_DIR)
                c.execute("DELETE FROM meal_plans WHERE recipe_id NOT IN (SELECT id FROM recipes) AND recipe_id IS NOT NULL")
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
            return {"items": n_lists.list_lists(c)}
        if p == "/api/households/shopping/lists" and method == "POST":
            lid = n_lists.create_list(c, (body or {}).get("name") or "Groceries")
            return {"id": lid, "name": (body or {}).get("name") or "Groceries"}
        mm = re.fullmatch(r"/api/households/shopping/lists/([^/]+)/recipe", p)
        if mm and method == "POST":
            lid = urllib.parse.unquote(mm.group(1))
            for it in body or []:
                rec = n_recipes.get(c, it["recipeId"])
                if not rec:
                    continue
                ings = it.get("recipeIngredients") if it.get("recipeIngredients") is not None else rec.get("recipeIngredient") or []
                lines = [_ing_line(g) for g in ings if _ing_line(g)]
                n_lists.add_recipe_ingredients(c, lid, rec["id"], lines, it.get("recipeIncrementQuantity") or 1, parse_ing_text, aisle_for)
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
                n_lists.add_items(c, lid, texts, parse_ing_text, aisle_for)
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
            _recipe_cache.update(at=time.time(), items=items)
        return list(_recipe_cache["items"])


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
            d = mealie("GET", f"/api/recipes/{urllib.parse.quote(r['slug'] or r['id'])}")
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
            "recipe": {"id": rec.get("id") or p.get("recipeId"), "name": rec.get("name"), "slug": rec.get("slug"),
                       "has_image": bool(rec.get("image")), "link": recipe_link(rec.get("slug"))} if (rec or p.get("recipeId")) else None,
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
    o = {**settings, **{k: v for k, v in opts.items() if v is not None}}
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

    proposals = []
    used_this_plan = {}
    for i in range(days):
        d = start + timedelta(days=i)
        for mt in sorted(meal_types, key=lambda m: ENTRY_ORDER.get(m, 9)):
            if o.get("fill_empty_only", True) and (iso(d), mt) in filled:
                continue
            pick = _pick(pool, d, i, no_repeat, used, used_this_plan, boost)
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


def _pick(pool, d, day_index, no_repeat, used, used_this_plan, boost, exclude=()):
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
        w = 1.0 + (float(r["rating"] or 0) / 5.0)
        if r["id"] in boost and day_index < 4:
            w *= 1 + 2.5 * boost[r["id"]]
        if r["id"] in used_this_plan:
            w *= 0.3
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
    no_repeat = int(opts.get("no_repeat_days") or get_settings()["no_repeat_days"])
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
    mealie("PUT", f"/api/households/shopping/items/{urllib.parse.quote(item_id)}", payload)
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
    g = grouped(sl)
    if not g:
        lines.append("(Nothing left to buy.)")
    for label, items in g:
        lines.append(label.upper())
        lines += [f"  [ ] {item_text(i)}" for i in items]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_list_csv(sl):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Section", "Item", "Quantity", "Unit", "Food", "Note"])
    for label, items in grouped(sl):
        for i in items:
            w.writerow([label, item_text(i), nice_qty(i.get("quantity")), (i.get("unit") or {}).get("name", ""),
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
.red{color:#d70015;font-weight:600}.amber{color:#b25000;font-weight:600}
.bar{position:fixed;top:12px;right:12px;display:flex;gap:8px}
.bar button{font:inherit;font-size:14px;padding:8px 14px;border-radius:999px;border:0;background:#007aff;color:#fff}
.bar button.sec{background:#e5e5ea;color:#1c1c1e}
@media print{.bar{display:none}body{padding:0}}
"""


def print_page(title, sub, body):
    e = html.escape
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{PRINT_CSS}</style></head><body>
<div class="bar"><button class="sec" onclick="history.length>1?history.back():window.close()">Done</button><button onclick="window.print()">Print</button></div>
<h1>{e(title)}</h1><div class="sub">{e(sub)}</div>{body}
<script>if(location.search.includes('auto=1'))setTimeout(()=>window.print(),300)</script></body></html>"""


def print_list(sl):
    e = html.escape
    g = grouped(sl)
    body = '<div class="cols">' + "".join(
        f'<div class="section"><h2>{e(l)}</h2><ul>' +
        "".join(f'<li><span class="box"></span>{e(item_text(i))}</li>' for i in items) + "</ul></div>"
        for l, items in g) + "</div>" if g else "<p>Nothing left to buy.</p>"
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

def email_ready():
    return bool(cfg("smtp_host") and cfg("mail_to"))


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
    msg["Subject"], msg["From"] = subject, sender
    msg["To"] = ", ".join(to or (c.get("mail_to") if conf else cfg("mail_to")))
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
    return page.split("</div>", 1)[1].split("<script>")[0]  # drop the button bar + script


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
        s0 = parse_date(b.get("start")) or today()
        return msg_plan(s0, parse_date(b.get("end")) or s0 + timedelta(days=6))
    if kind == "pantry":
        return msg_pantry()
    if kind == "test":
        return msg_test(b.get("channel") or "notification")
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


def _https_json(url, payload=None, headers=None, data=None, ctype=None, timeout=20, method=None):
    h = {"User-Agent": f"TablePlan/{APP_VERSION}", "Accept": "application/json", **(headers or {})}
    if payload is not None:
        data, ctype = json.dumps(payload).encode(), "application/json"
    if ctype:
        h["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, headers=h, method=method or ("POST" if data is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:   # TLS certificates are verified by default
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
        except ValueError:
            body = {}
        raise ApiError(502, body.get("description") or body.get("error") or f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ApiError(502, f"Couldn't connect ({getattr(e, 'reason', e)})")


# ---- Telegram (bot API, outbound only: no webhook, nothing exposed to the internet)

TELEGRAM_API = env("TELEGRAM_API_URL", "https://api.telegram.org").rstrip("/")   # override only for a self-hosted Bot API server
TELEGRAM_TOKEN_RE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,64}$")


def _tg(method, token=None, **kw):
    token = token or cfg("telegram_token")
    if not token:
        raise ApiError(400, "Telegram isn't set up.")
    res = _https_json(f"{TELEGRAM_API}/bot{token}/{method}", **kw)
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
    _https_json(server + "/", payload={"topic": c["ntfy_topic"], "title": msg["subject"], "message": body,
                                        "tags": ["fork_and_knife"]}, headers=headers)


def ntfy_setup(b):
    server = (b.get("server") or "https://ntfy.sh").strip().rstrip("/")
    if not re.match(r"^https://[^\s/]+", server) and not re.match(r"^http://(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|[^./]+(:\d+)?$)", server):
        raise ApiError(400, "Use an https:// ntfy server (plain http is only allowed for servers on your home network).")
    topic = (b.get("topic") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", topic):
        raise ApiError(400, "Topic must be 8–64 letters, numbers, - or _. Use the random one suggested.")
    if "ntfy.sh" in server and len(topic) < 20 and not b.get("token"):
        raise ApiError(400, "On the public ntfy.sh server anyone who guesses the topic can read it. Use the long random topic, or add an access token.")
    conf = {"ntfy_server": server, "ntfy_topic": topic, "ntfy_token": (b.get("token") or "").strip() or cfg("ntfy_token") or ""}
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
    api_key = (api_key or "").strip()
    model = (model or "gpt-5-mini").strip()
    if not api_key:
        raise ApiError(400, "Paste your OpenAI API key.")
    if NATIVE:
        try:
            _https_json(f"https://api.openai.com/v1/models/{urllib.parse.quote(model)}", headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
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


def email_setup(b):
    conf = {**SMTP_PRESETS.get(b.get("preset") or "", {})}
    for k in ("smtp_host", "smtp_port", "smtp_security", "smtp_user", "smtp_from"):
        if b.get(k) not in (None, ""):
            conf[k] = b[k]
    conf.setdefault("smtp_port", 587)
    conf.setdefault("smtp_security", "starttls")
    conf["smtp_port"] = int(conf["smtp_port"])
    if conf["smtp_security"] not in ("starttls", "ssl", "none"):
        raise ApiError(400, "Security must be starttls, ssl or none.")
    conf["smtp_password"] = b.get("smtp_password") or cfg("smtp_password")
    conf["smtp_from"] = conf.get("smtp_from") or conf.get("smtp_user")
    to = b.get("mail_to")
    if isinstance(to, str):
        to = [a.strip() for a in re.split(r"[,;\s]+", to) if a.strip()]
    conf["mail_to"] = to or ([conf["smtp_from"]] if conf.get("smtp_from") else [])
    if not conf.get("smtp_host"):
        raise ApiError(400, "Pick your email provider or enter the SMTP server.")
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
    files = []
    total = 0
    for i, im in enumerate(images[:8]):
        blob = base64.b64decode(im["data"].split(",", 1)[-1])
        total += len(blob)
        if total > 25_000_000:
            raise ApiError(413, "Those images are too large together (25 MB max).")
        files.append(("images", im.get("name") or f"image{i}.jpg", im.get("type") or "image/jpeg", blob))
    if NATIVE:
        data = ai_recipe(text or "", images[:8], "screenshot import", f"{len(images[:8])} image(s)")
        slug = _save_new_recipe(data)
        if data.get("orgURL"):   # the screenshot showed the web address: fetch that page's photo in the background
            threading.Thread(target=lambda: _safe(recipe_image_next, slug), daemon=True).start()
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


def parse_ing_text(text):
    """'1 ½ cups heavy cream, divided' -> {quantity:1.5, unit:'cup', unit_plural:'cups', food:'heavy cream', note:'divided'}."""
    t = (text or "").strip()
    for k, v in _UFRAC.items():
        t = re.sub(rf"(\d)\s*{k}", rf"\1 {v}", t).replace(k, v)
    m = _ING_RE.match(t)
    if not m:
        return None
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
    food, _, note = rest.partition(",")
    food = food.strip(" -")
    if not food:
        return None
    return {"quantity": q, "unit": unit[0] if unit else "", "unit_plural": unit[1] if unit else "",
            "food": food, "note": note.strip(), "size": (paren or "") if unit else ""}


def clean_food(name):
    n = re.sub(r"\([^)]*\)", " ", name or "")
    n = _DESCRIPTORS.sub(" ", n)
    n = re.split(r"\bor\b|,|;", n)[0]
    return re.sub(r"\s+", " ", n).strip(" -.") or (name or "").strip()


# ============================================================ in-app recipe editing (saves to Mealie)

def recipe_update(slug, b):
    r = mealie("GET", f"/api/recipes/{urllib.parse.quote(slug)}")
    if "name" in b:
        name = (b.get("name") or "").strip()
        if not name:
            raise ApiError(400, "Give the recipe a name.")
        r["name"] = name[:200]
    if "description" in b:
        r["description"] = (b.get("description") or "").strip()[:2000]
    if b.get("servings") not in (None, ""):
        r["recipeServings"] = max(0.0, float(b["servings"]))
    for key, field in (("prep_minutes", "prepTime"), ("cook_minutes", "performTime"), ("total_minutes", "totalTime")):
        if key in b:
            v = int(float(b.get(key) or 0))
            r[field] = f"{v} minutes" if v else None
            r[field + "Seconds"] = v * 60 if v else None
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
    out = mealie("PUT", f"/api/recipes/{urllib.parse.quote(slug)}", r)
    _recipe_cache["at"] = 0
    with db() as c:
        c.execute("DELETE FROM guided_cache WHERE recipe_id=?", (r.get("id"),))
    return {"slug": out.get("slug") or slug}


def recipe_delete(slug):
    mealie("DELETE", f"/api/recipes/{urllib.parse.quote(slug)}")
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
                "Do not invent anything." + (f"\n\nExtra notes from the user: {text}" if text else "")}]
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
            req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read(MAX_IMG + 1)
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

VIDEO_HOSTS = re.compile(r"(^|\.)(instagram\.com|tiktok\.com|youtube\.com|youtu\.be|facebook\.com|fb\.watch|pinterest\.com|pin\.it|threads\.net)$", re.I)
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
    req = urllib.request.Request(f"https://docs.google.com/document/d/{doc}/export?format=txt", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            final = r.geturl()
            body = r.read(3_000_000).decode("utf-8-sig", errors="replace")
    except urllib.error.HTTPError:
        body, final = "", ""
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


def import_video(url):
    try:
        import yt_dlp
    except ImportError:
        raise ApiError(501, "Video import isn't available in this install. Update TablePlan, or use screenshots of the post.")
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "logger": _YtdlpQuiet(), "noplaylist": True, "skip_download": True, "socket_timeout": 20}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
    except Exception as e:
        msg = str(e)
        if re.search(r"login|log in|private|rate|cookies", msg, re.I):
            raise ApiError(502, "That post can't be opened without logging in (private account or the site is blocking). "
                                "Take screenshots of the caption and use the Screenshot tab.")
        reason = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)?[^:]*:\s*", "", msg.splitlines()[0]).split(";")[0][:90]
        raise ApiError(502, f"Couldn't open that video ({reason}). Try again in a minute, or use screenshots of the post.")
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
            with tempfile.TemporaryDirectory() as tmp:
                dl = {**opts, "skip_download": False, "outtmpl": os.path.join(tmp, "clip.%(ext)s"),
                      "format": "worstaudio[filesize<24M]/worst[filesize<24M]/worstaudio/worst", "max_filesize": 24_000_000}
                try:
                    with yt_dlp.YoutubeDL(dl) as y:
                        y.download([url])
                    files = [os.path.join(tmp, f) for f in os.listdir(tmp)]
                    if files and os.path.getsize(files[0]) < 25_000_000:
                        spoken = _transcribe(files[0])
                        text = f"Caption:\n{caption}\n\nWhat the cook says in the video:\n{spoken}"
                except ApiError:
                    raise
                except Exception as e:
                    log("video download/transcribe failed:", e)
    if not text.strip():
        raise ApiError(422, "Couldn't find a recipe in that video's caption or audio. Try screenshots instead.")
    data = recipe_from_text(text, title, url, "video import")
    if not data.get("name") or data["name"] == "Untitled recipe":
        data["name"] = title or "Video recipe"
    return _imported(_save_new_recipe(data, thumb))


def _imported(slug):
    slug = slug.strip('"') if isinstance(slug, str) else slug
    if cfg("openai_key"):   # prepare the AI step-by-step version in the background so it's instant later
        threading.Thread(target=lambda: _safe(guided, slug, True), daemon=True).start()
    _recipe_cache["at"] = 0
    try:
        r = mealie("GET", f"/api/recipes/{urllib.parse.quote(slug)}")
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
    mealie("POST" if on else "DELETE", f"/api/users/{mealie_user_id()}/favorites/{urllib.parse.quote(slug)}")
    _recipe_cache["at"] = 0
    return {"favorite": bool(on)}


FOOD_EMOJI = [
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
    r = mealie("GET", f"/api/recipes/{urllib.parse.quote(slug)}")
    with db() as c:
        pantry = {}
        for it in list_pantry(c):
            pantry.setdefault(food_key(it["name"]), it)
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
        pantry_hit = (pantry.get(food_key(fname)) or pantry.get(food_key(clean_food(fname)))) if fname else None
        if ing.get("referenceId"):
            ref_index[ing["referenceId"]] = i
        if local:
            ings.append({"i": i, "section": ing.get("title") or "", "quantity": local["quantity"], "parsed": True, "local": True,
                         "unit": local["unit"], "unit_plural": local["unit_plural"], "food": local["food"], "food_plural": "",
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
            "food": fname, "food_plural": food.get("pluralName") or "",
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
        "servings": _num(r.get("recipeServings")) or _num(r.get("recipeYieldQuantity")) or 0,
        "yield": r.get("recipeYield") or "", "minutes": minutes,
        "prep_minutes": round(int(r.get("prepTimeSeconds") or 0) / 60) or None,
        "cook_minutes": round(int(r.get("performTimeSeconds") or 0) / 60) or None,
        "difficulty": difficulty, "rating": r.get("rating") or 0, "favorite": r["id"] in favorite_ids(),
        "tags": [t.get("name") for t in r.get("tags") or []],
        "categories": [t.get("name") for t in r.get("recipeCategory") or []],
        "ingredients": ings, "steps": steps, "source_url": r.get("orgURL") or "",
        "link": recipe_link(r.get("slug")), "updated": r.get("dateUpdated") or r.get("updatedAt") or "",
        "unparsed": 0, "total_minutes": round(int(r.get("totalTimeSeconds") or 0) / 60) or None,
    }


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


def _guided_profile():
    st = get_settings()
    return f"{st.get('stove')}|{st.get('oven')}|{st.get('temp_unit')}"


def guided_auto(rec):
    st = get_settings()
    stove, oven, unit = st.get("stove"), st.get("oven"), st.get("temp_unit") or "F"
    used, steps = set(), []
    tokens_of = {x["i"]: set(tokens(x["food"])) for x in rec["ingredients"] if x["food"]}
    for s0 in rec["steps"]:
        text = s0["text"]
        refs = [i for i in s0["refs"] if i not in used]
        if not s0["refs"]:
            ttoks = set(tokens(text))
            refs = [i for i, tk in tokens_of.items() if tk and tk <= ttoks and i not in used]
        used.update(refs)
        timer, label = s0.get("duration_sec"), None
        if not timer:
            m = None
            for m in DUR_RE.finditer(text):
                pass
            if m:
                lo, hi, u = float(m.group(1)), m.group(2), m.group(3).lower()
                mult = 3600 if u.startswith("h") else 1 if u.startswith("s") else 60
                timer = int(lo * mult)
                label = f"Check at {m.group(1)}" + (f"–{hi}" if hi else "") + (" h" if mult == 3600 else " sec" if mult == 1 else " min")
        heat = HEAT_RE.search(text)
        temp = None
        tm = TEMP_RE.search(text)
        if tm and re.search(r"oven|bake|roast|preheat|°", text, re.I):
            t, u = int(tm.group(1)), (tm.group(2) or "F").upper()
            if u != unit:
                t = round((t - 32) * 5 / 9 / 5) * 5 if unit == "C" else round((t * 9 / 5 + 32) / 5) * 5
            if oven == "convection" and re.search(r"bake|roast|oven", text, re.I):
                t -= 25 if unit == "F" else 15
            temp = f"{t}°{unit}"
        steps.append({"title": s0["title"] or "", "text": text, "ingredients": [{"i": i, "portion": 1} for i in refs],
                      "timer_sec": timer, "timer_label": label or (f"{round(timer / 60)} min" if timer else None),
                      "heat": heat.group(1).lower() if heat else None, "temperature": temp,
                      "tip": STOVE_TIPS.get(stove) if heat else None})
    leftovers = [x["i"] for x in rec["ingredients"] if x["i"] not in used and (x["food"] or x["display"])]
    out = []
    oven_steps = [s for s in steps if s["temperature"]]
    if oven_steps and not re.search(r"preheat", steps[0]["text"] if steps else "", re.I):
        t = oven_steps[0]["temperature"]
        out.append({"title": "Preheat", "text": f"Preheat the oven to {t}" + (" (convection, already lowered 25°F)" if oven == "convection" and unit == "F" else "")
                    + ". It takes about 10–15 minutes, so keep going with the next steps while it heats.",
                    "ingredients": [], "timer_sec": 600, "timer_label": "Oven preheating", "heat": None, "temperature": t, "tip": None})
    names = [rec["ingredients"][i]["food"] or rec["ingredients"][i]["display"] for i in leftovers]
    tips = [f"Also have ready: {', '.join(n for n in names if n)}."] if leftovers and any(names) else []
    return {"source": "auto", "steps": out + steps, "tips": tips}


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
    st = get_settings()
    ing_lines = "\n".join(f"[{x['i']}] {x['display'] or x['food']}" + (f"  (section: {x['section']})" if x["section"] else "")
                          for x in rec["ingredients"])
    step_lines = "\n".join(f"{n + 1}. {s0['text']}" for n, s0 in enumerate(rec["steps"]))
    sys_prompt = (
        "You rewrite home recipes into a perfect order of operations a nervous home cook can follow without reading ahead. "
        "Rules: keep every original ingredient and amount, never invent ingredients. Each step lists exactly which ingredients it uses "
        "by their [index]; if an ingredient is split across steps, give the fraction used as portion (e.g. 0.5), otherwise 1. "
        "Put preheating (oven, pans, water to boil) at the moment it must start so it's ready in time. "
        f"The cook has a {st.get('stove')} stovetop and a {st.get('oven')} oven"
        + (" (lower convection temperatures by 25°F / 15°C and say so)" if st.get("oven") == "convection" else "")
        + f". Give temperatures in °{st.get('temp_unit') or 'F'}. Translate heat levels to that stove, with a short practical cue "
        "(e.g. 'gas: flame just touching the pan'). For every step that involves waiting (simmer, bake, rest, marinate, boil), "
        "set timer_minutes and a short timer_label such as 'Simmer sauce'. If something useful can be done while waiting, say so in the text. "
        "Steps are short and imperative, one action each. tips: up to 3 short tips specific to this recipe. "
        "INGREDIENT PLACEMENT (most important): each step's ingredients list holds ONLY the ingredients physically added or used "
        "in that exact step, with the amount used there. Example: 'Whisk the wet ingredients' lists only buttermilk, eggs and melted "
        "butter; the next step 'Add the dry ingredients' lists only flour, sugar, baking powder and salt. If an original step adds "
        "two groups at different moments, split it into separate steps. Never make a 'gather' or 'prep everything' step that lists "
        "ingredients. Don't re-list a mixture made earlier (e.g. 'the batter'). Every ingredient index appears at least once; an "
        "ingredient split across steps gets a portion in each (portions add up to 1).")
    data = openai_chat([
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"Recipe: {rec['name']} (serves {rec['servings'] or '?'})\n\nIngredients:\n{ing_lines}\n\nOriginal steps:\n{step_lines}"},
    ], "guided_recipe", GUIDE_SCHEMA, "step-by-step", rec["name"])
    valid = {x["i"] for x in rec["ingredients"]}
    steps = []
    for s0 in data.get("steps") or []:
        tm = s0.get("timer_minutes")
        steps.append({"title": s0.get("title") or "", "text": s0.get("text") or "",
                      "ingredients": [{"i": x["index"], "portion": max(0.05, min(1.0, float(x.get("portion") or 1)))}
                                      for x in s0.get("ingredients") or [] if x.get("index") in valid],
                      "timer_sec": int(tm * 60) if tm else None, "timer_label": s0.get("timer_label"),
                      "heat": s0.get("heat"), "temperature": s0.get("temperature"), "tip": None})
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


def guided(slug, use_ai=None, refresh=False):
    """Step-by-step version of a recipe. Uses AI automatically when an OpenAI key is set (cached), else the built-in arranger."""
    if use_ai is None:
        use_ai = bool(cfg("openai_key"))
        if use_ai:
            try:
                return guided(slug, True, refresh)
            except ApiError as e:
                log("AI step-by-step failed, using built-in:", e.message)
                use_ai = False
    rec = recipe_detail(slug)
    profile = _guided_profile() + ("|ai2" if use_ai else "|auto2")
    if not refresh:
        with db() as c:
            row = c.execute("SELECT * FROM guided_cache WHERE recipe_id=? AND profile=?", (rec["id"], profile)).fetchone()
        if row and row["updated"] == rec["updated"]:
            return {**json.loads(row["data"]), "cached": True}
    data = guided_ai(rec) if use_ai else guided_auto(rec)
    with db() as c:
        c.execute("INSERT INTO guided_cache(recipe_id, profile, updated, source, data, created_at) VALUES (?,?,?,?,?,?) "
                  "ON CONFLICT(recipe_id, profile) DO UPDATE SET updated=excluded.updated, source=excluded.source, data=excluded.data, created_at=excluded.created_at",
                  (rec["id"], profile, rec["updated"], data["source"], json.dumps(data), datetime.now().isoformat(timespec="seconds")))
    has_ai = False
    if not use_ai:
        with db() as c:
            has_ai = bool(c.execute("SELECT 1 FROM guided_cache WHERE recipe_id=? AND profile=?", (rec["id"], _guided_profile() + "|ai2")).fetchone())
    return {**data, "cached": False, "ai_available": has_ai}


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

def upc_lookup(code):
    with db() as c:
        row = c.execute("SELECT data FROM upc_cache WHERE code=?", (code,)).fetchone()
    if row:
        return json.loads(row["data"])
    try:
        res = _https_json(f"https://world.openfoodfacts.org/api/v2/product/{code}.json?" + urllib.parse.urlencode(
            {"fields": "product_name,product_name_en,generic_name,brands,quantity,categories_tags"}), timeout=12)
    except ApiError as e:
        raise ApiError(502, f"Couldn't look up that barcode ({e.message}). You can type the item instead.")
    p = res.get("product") or {}
    name = (p.get("product_name_en") or p.get("product_name") or p.get("generic_name") or "").strip()
    found = bool(res.get("status") == 1 and name)
    cats = [c.split(":", 1)[-1].replace("-", " ") for c in (p.get("categories_tags") or []) if c.startswith("en:")]
    data = {"code": code, "found": found, "name": name, "brand": (p.get("brands") or "").split(",")[0].strip(),
            "quantity": p.get("quantity") or "", "categories": cats[-4:], "source": "Open Food Facts"}
    if found:
        with db() as c:
            rule = match_rule(c, name) or next((match_rule(c, cat) for cat in reversed(cats) if match_rule(c, cat)), None)
        data["rule"] = {"id": rule["id"], "name": rule["name"], "location": rule["default_location"]} if rule else None
    with db() as c:
        c.execute("INSERT OR REPLACE INTO upc_cache(code, data, at) VALUES (?,?,?)", (code, json.dumps(data), iso(today())))
    return data


def pantry_checkin_status():
    days = int(get_settings().get("pantry_check_days") or 0)
    last = parse_date(get_internal("pantry_checked_at"))
    if not last:
        with db() as c:
            first = c.execute("SELECT MIN(created_at) FROM pantry_items").fetchone()[0]
        last = parse_date(first) if first else None
    due = bool(days and last and (today() - last).days >= days)
    return {"interval_days": days, "last": iso(last) if last else None, "due": due,
            "days_since": (today() - last).days if last else None}


# ============================================================ images (ingredients & recipes)

IMG_DIR = os.path.join(DATA_DIR, "images")
MAX_IMG = 8_000_000


def _public_host(url):
    host = urllib.parse.urlparse(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _fetch_image(url):
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://"):
        url = "https://" + url[7:]
    if not url.startswith("https://") or not _public_host(url):
        raise ValueError("refusing non-public or non-https image URL")
    req = urllib.request.Request(url, headers={"User-Agent": f"TablePlan/{APP_VERSION} (+https://github.com/thomasjvalenzuela/tableplan)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].lower()
        data = r.read(MAX_IMG + 1)
        if not ctype.startswith("image/"):
            kind = n_recipes.sniff_image(data[:64])
            if not kind:
                raise ValueError("not an image")
            ctype = "image/" + ("jpeg" if kind == "jpg" else kind)
    if len(data) > MAX_IMG:
        raise ValueError("image too large")
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
            credit = f"“{x.get('title') or 'Photo'}” by {x.get('creator') or 'unknown'} ({(x.get('license') or '').upper()} {x.get('license_version') or ''})".strip()
            out.append((url, credit))
    return out


def ingredient_candidates(name):
    words = [w for w in re.findall(r"[A-Za-z]+", name)]
    variants = []
    for v in (" ".join(words), " ".join(singular(w.lower()) for w in words), words[-1] if words else "", singular(words[-1].lower()) if words else ""):
        v = v.strip().title()
        if v and v not in variants:
            variants.append(v)
    cands = [(f"https://www.themealdb.com/images/ingredients/{urllib.parse.quote(v)}-Small.png", "TheMealDB") for v in variants]
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
    rec = mealie("GET", f"/api/recipes/{urllib.parse.quote(slug)}")
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
    mealie("PUT", f"/api/recipes/{urllib.parse.quote(slug)}/image",
           multipart=({"extension": _ext(ctype)}, [("image", f"image.{_ext(ctype)}", ctype, blob)]), timeout=60)
    _recipe_cache["at"] = 0


def decode_upload(data_url):
    head, _, b64 = (data_url or "").partition(",")
    m = re.match(r"data:(image/[a-z+.-]+);base64", head)
    if not m:
        raise ApiError(400, "Upload a JPG, PNG or WebP image.")
    blob = base64.b64decode(b64)
    if len(blob) > MAX_IMG:
        raise ApiError(413, "That image is too large (8 MB max).")
    return blob, m.group(1)


# ============================================================ meal plan → shopping list

def ensure_list(list_id=None):
    lists = get_lists()
    if list_id and any(l["id"] == list_id for l in lists):
        return list_id
    if lists:
        return lists[0]["id"]
    return mealie("POST", "/api/households/shopping/lists", {"name": "Groceries"})["id"]


STAPLES = {"salt", "pepper", "black pepper", "water", "oil", "olive oil", "vegetable oil", "butter", "sugar", "flour",
           "garlic", "baking soda", "baking powder", "vanilla", "vanilla extract", "soy sauce", "vinegar"}


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
            rec = mealie("GET", f"/api/recipes/{urllib.parse.quote(slug)}")
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
            f["staple"] = fname.lower() in STAPLES
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
                rec = mealie("GET", f"/api/recipes/{urllib.parse.quote(t['slug'])}")
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


# ============================================================ update check

_update_cache = {"at": 0, "data": None}


def update_info(force=False):
    ttl = 600   # every 10 minutes (a tiny file on GitHub Pages)   # hourly; retry sooner after a failed check
    if force or time.time() - _update_cache["at"] > ttl:
        data = None
        try:
            req = urllib.request.Request(UPDATE_FEED, headers={"User-Agent": f"TablePlan/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode())
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
            # Pantry check-in reminder (once per due period, at the alert hour)
            ck = pantry_checkin_status()
            if ck["due"] and any(channels_ready().values()) and now.hour >= int(s.get("expiry_alert_hour") or 8):
                flag = f"checkin_nudge_{ck['last']}"
                if not get_internal(flag):
                    set_internal(flag, True)
                    deliver({"subject": "🧺 Time for a quick pantry check",
                             "text": f"It's been {ck['days_since']} days. Open TablePlan → Pantry → Check-in to confirm what's left. It takes about a minute.",
                             "html": email_wrap("<p>Time for a quick pantry check. Open TablePlan → Pantry → <b>Check-in</b>.</p>"), "files": []})
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

class Handler(BaseHTTPRequestHandler):
    server_version = "TablePlan/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if "/health" not in str(args[0] if args else ""):
            sys.stdout.write("[tableplan] %s %s\n" % (self.address_string(), fmt % args))

    # ---- helpers
    def authorized(self):
        if not auth_required():
            return True
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "tp_session" and valid_session(v):
                return True
        return False

    def client_ip(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def cookie(self, value, max_age=180 * 86400):
        secure = "; Secure" if getattr(_req, "scheme", "http") == "https" else ""
        return f"tp_session={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}"

    def send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, default=str)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if getattr(self, "_body", None) is None and int(self.headers.get("Content-Length") or 0) > 0:
            # request body was never read (early 401/403/413/error): close so its bytes aren't parsed as the next request
            self.send_header("Connection", "close")
            self.close_connection = True
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        if ctype.startswith("text/html"):
            inline = "'unsafe-inline' " if self.path.startswith("/print/") else ""
            self.send_header("Content-Security-Policy",
                             f"default-src 'self'; script-src 'self' 'wasm-unsafe-eval' {inline}; style-src 'self' 'unsafe-inline'; "
                             "img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if getattr(_req, "scheme", "http") == "https":
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        if not (headers or {}).get("Cache-Control"):
            self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def download(self, text, fname, ctype):
        self.send(200, text, ctype, {"Content-Disposition": f'attachment; filename="{fname}"'})

    def body(self):
        if getattr(self, "_body", None) is None:
            self._read_body()
        out = json.loads(self._body) if self._body else {}
        if not isinstance(out, dict):
            raise ApiError(400, "Expected a JSON object.")
        return out

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 40_000_000:
            raise ApiError(413, "Request too large")
        self._body = self.rfile.read(n) if n else b""

    def handle_any(self, method):
        self._body = None
        url = urllib.parse.urlparse(self.path)
        path, q = url.path, {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if path == "/health":
            return self.send(200, "ok", "text/plain")
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "localhost").split(",")[0].strip()
        _req.host = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        _req.scheme = (self.headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip()
        public = (path == "/" or path.startswith("/static/") or path in ("/manifest.webmanifest", "/api/session", "/api/login"))
        # CSRF: state-changing requests must carry a custom header, which other sites can't send without CORS (we allow none).
        if method in ("POST", "PUT", "PATCH", "DELETE") and self.headers.get("X-TablePlan") != "1":
            return self.send(403, {"error": "Missing X-TablePlan header"})
        if not public and not self.authorized():
            if path.startswith("/api/"):
                return self.send(401, {"error": "Sign in required", "auth": True})
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            return self.route(method, path, q)
        except ApiError as e:
            return self.send(e.status, {"error": e.message})
        except (ValueError, KeyError, TypeError) as e:
            traceback.print_exc()
            return self.send(400, {"error": f"Bad request: {e}"})
        except Exception as e:
            traceback.print_exc()
            return self.send(500, {"error": f"Server error: {e}"})

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

        # static
        if m == "GET" and (path == "/" or path.startswith("/static/") or path in ("/manifest.webmanifest", "/sw.js")):
            return self.static(path)

        # ---- session / auth
        if m == "GET" and path == "/api/session":
            return self.send(200, {"auth_required": auth_required(), "authed": self.authorized(), "public": PUBLIC_MODE,
                                   "needs_setup_code": PUBLIC_MODE and not cfg("app_password_hash"), "backend": "native" if NATIVE else "mealie",
                                   "setup_complete": bool(cfg("setup_complete")), "version": APP_VERSION})
        if m == "POST" and path == "/api/login":
            ip = self.client_ip()
            if login_throttled(ip):
                raise ApiError(429, "Too many tries. Wait 10 minutes and try again.")
            pw = self.body().get("password") or ""
            if not auth_required() or password_ok(pw):
                _login_fails.pop(ip, None)
                return self.send(200, {"ok": True}, headers={"Set-Cookie": self.cookie(make_session())})
            _login_fails.setdefault(ip, []).append(time.time())
            time.sleep(1.0)
            raise ApiError(401, "Wrong password" if cfg("app_password_hash") else "Wrong setup code. Find it in the TablePlan server log.")
        if m == "POST" and path == "/api/logout":
            return self.send(200, {"ok": True}, headers={"Set-Cookie": self.cookie("", 0)})

        if m == "GET" and path == "/api/config":
            s = get_settings()
            base, slug = mealie_public(), cfg("group_slug")
            return self.send(200, {"mealie_url": base, "group_slug": slug,
                                   "email_ready": email_ready(), "mail_to": cfg("mail_to") or [], "settings": s,
                                   "channels": channels_ready(), "telegram_chat": cfg("telegram_chat_name"),
                                   "usda_synced_at": get_internal("usda_synced_at"),
                                   "setup_complete": bool(cfg("setup_complete")), "connected": NATIVE or bool(cfg("mealie_token")), "backend": "native" if NATIVE else "mealie",
                                   "household": {"name": cfg("household_name"), "people": cfg("people"),
                                                 "scale": bool(cfg("scale_to_household"))},
                                   "auth_required": auth_required(), "version": APP_VERSION,
                                   "repo_url": "https://github.com/thomasjvalenzuela/tableplan",
                                   "ai_key": bool(cfg("openai_key")),
                                   "import_url": f"{base}/g/{slug}/r/create/url",
                                   "import_image": f"{base}/g/{slug}/r/create",
                                   "planner_url": f"{base}/household/mealplan/planner/view"})

        # ---- setup wizard & settings
        if m == "GET" and path == "/api/setup/status":
            return self.send(200, setup_status())
        if m == "POST" and path == "/api/setup/household":
            b = self.body()
            people = max(1, min(30, int(b.get("people") or 2)))
            set_cfg(household_name=(b.get("name") or "").strip()[:60], people=people,
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
            return self.send(200, ai_setup(b.get("api_key"), b.get("model"), bool(b.get("audio", True)), b.get("base_url")))
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
            pw = self.body().get("password") or ""
            if pw and len(pw) < 4:
                raise ApiError(400, "Use at least 4 characters.")
            if not pw and PUBLIC_MODE:
                raise ApiError(400, "A password is required because this TablePlan is reachable from the internet.")
            set_cfg(app_password_hash=hash_password(pw) if pw else "")
            hdr = {"Set-Cookie": self.cookie(make_session())} if pw else None
            return self.send(200, {"set": bool(pw)}, headers=hdr)
        if m == "POST" and path == "/api/setup/import-mealie":
            return self.send(200, import_from_mealie(self.body()))
        if m == "POST" and path == "/api/setup/complete":
            set_cfg(setup_complete=True)
            return self.send(200, {"ok": True})

        # ---- import & updates
        if m == "POST" and path == "/api/import/url":
            return self.send(200, import_url(self.body().get("url", "").strip()))
        if m == "POST" and path == "/api/import/text":
            b = self.body()
            return self.send(200, import_text(b.get("text"), b.get("title") or ""))
        if m == "POST" and path == "/api/import/images":
            b = self.body()
            return self.send(200, import_images(b.get("images") or [], b.get("text")))
        if m == "POST" and path == "/api/plan/to-list":
            b = self.body()
            s0 = parse_date(b.get("start")) or today()
            return self.send(200, plan_to_list(s0, parse_date(b.get("end")) or s0 + timedelta(days=6),
                                               b.get("list_id"), bool(b.get("skip_pantry", True)), b.get("skip_keys")))
        if m == "POST" and path == "/api/plan/preview":
            b = self.body()
            s0 = parse_date(b.get("start")) or today()
            return self.send(200, plan_preview(s0, parse_date(b.get("end")) or s0 + timedelta(days=6)))
        # ---- barcode lookup (Open Food Facts) & pantry check-ins
        mm = re.fullmatch(r"/api/upc/(\d{6,14})", path)
        if m == "GET" and mm:
            return self.send(200, upc_lookup(mm.group(1)))
        if m == "POST" and path == "/api/pantry/checked":
            set_internal("pantry_checked_at", iso(today()))
            return self.send(200, pantry_checkin_status())
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
        mm = re.fullmatch(r"/api/recipe/([A-Za-z0-9_.~%-]{1,200})/(favorite|guided|image/next|image/upload|to-list)", path)
        if mm:
            slug, act = urllib.parse.unquote(mm.group(1)), mm.group(2)
            if act == "favorite" and m == "POST":
                return self.send(200, set_favorite(slug, bool(self.body().get("favorite", True))))
            if act == "guided" and m == "GET":
                ai = {"1": True, "0": False}.get(q.get("ai"))
                return self.send(200, guided(slug, ai, q.get("refresh") == "1"))
            if act == "image/next" and m == "POST":
                return self.send(200, recipe_image_next(slug))
            if act == "image/upload" and m == "POST":
                blob, ctype = decode_upload(self.body().get("data"))
                _upload_recipe_image(slug, blob, ctype)
                return self.send(200, {"ok": True})
            if act == "to-list" and m == "POST":
                b = self.body()
                return self.send(200, add_items_to_list(b.get("items") or [], b.get("list_id")))
        if m == "GET" and path == "/img/ing":
            name = (q.get("name") or "").strip()[:80]
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
                return self.send(200, save_settings(self.body()))
            return self.send(200, get_settings())

        # --- recipes & images
        if m == "GET" and path == "/api/recipes":
            pool = recipe_pool(refresh=q.get("refresh") == "1")
            tags = sorted({t for r in pool for t in r["tags"] + r["categories"] if t}, key=str.lower)
            return self.send(200, {"recipes": [{**r, "link": recipe_link(r["slug"])} for r in pool], "tags": tags})

        mm = re.fullmatch(r"/img/([A-Za-z0-9-]{1,64})", path)
        if m == "GET" and mm:
            return self.image(mm.group(1), q.get("size", "min"))

        # --- meal plan
        if m == "GET" and path == "/api/plan":
            start = parse_date(q.get("start")) or today()
            end = parse_date(q.get("end")) or start + timedelta(days=6)
            entries = get_plans(start, end)
            return self.send(200, {"start": iso(start), "end": iso(end), "entries": entries})
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
        mm = re.fullmatch(r"/api/plan/(\d+)", path)
        if m == "DELETE" and mm:
            mealie("DELETE", f"/api/households/mealplans/{mm.group(1)}")
            return self.send(200, {"ok": True})

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
            slug = mealie("POST", "/api/recipes", {"name": name})
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
        if path == "/api/pantry":
            with db() as c:
                if m == "POST":
                    b = self.body()
                    if not (b.get("name") or "").strip():
                        raise ApiError(400, "Name is required")
                    iid = add_pantry_item(c, b["name"], b.get("location"), b.get("package_date"), b.get("quantity_text", ""))
                    return self.send(200, pantry_json(c, pantry_row(c, iid)))
                return self.send(200, {"items": list_pantry(c, q.get("status", "active"))})
        mm = re.fullmatch(r"/api/pantry/(\d+)", path)
        if mm and m in ("PATCH", "POST"):
            with db() as c:
                apply_pantry_action(c, int(mm.group(1)), self.body())
                row = pantry_row(c, int(mm.group(1)))
                return self.send(200, pantry_json(c, row) if row else {"deleted": True})
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
            start = parse_date(q.get("start")) or today()
            end = parse_date(q.get("end")) or start + timedelta(days=6)
            entries = get_plans(start, end)
            ext = mm.group(1)
            if ext == "ics":
                return self.download(render_plan_ics(entries), f"meal-plan-{iso(start)}.ics", "text/calendar; charset=utf-8")
            if ext == "txt":
                return self.download(render_plan_text(entries, start, end), f"meal-plan-{iso(start)}.txt", "text/plain; charset=utf-8")
            return self.download(render_plan_csv(entries), f"meal-plan-{iso(start)}.csv", "text/csv; charset=utf-8")
        if m == "GET" and path == "/export/pantry.csv":
            with db() as c:
                return self.download(render_pantry_csv(list_pantry(c)), "pantry.csv", "text/csv; charset=utf-8")
        mm = re.fullmatch(r"/print/list/([A-Za-z0-9-]{1,64})", path)
        if m == "GET" and mm:
            return self.send(200, print_list(get_list(mm.group(1))), "text/html; charset=utf-8")
        if m == "GET" and path == "/print/plan":
            start = parse_date(q.get("start")) or today()
            end = parse_date(q.get("end")) or start + timedelta(days=6)
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
        out["pantry_checkin"] = pantry_checkin_status()
        try:
            start = today()
            out["week"] = get_plans(start, start + timedelta(days=6))
            lists = get_lists()
            out["lists"] = lists
            if lists:
                sl = get_list(lists[0]["id"])
                out["list_count"] = sum(1 for i in (sl.get("listItems") or []) if not i.get("checked"))
            else:
                out["list_count"] = 0
            out["recipe_count"] = len(recipe_pool())
        except ApiError as e:
            out.update(mealie_ok=False, error=e.message, week=[], lists=[], list_count=0, recipe_count=0)
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
                    pid = add_pantry_item(c, name, b.get("location"), b.get("package_date"), item_text(item), item_id)
                return {"ok": True, "pantry_item": pantry_json(c, pantry_row(c, pid)) if pid else None}
            set_checked(sl, item_id, False)
            if b.get("pantry_item_id"):
                c.execute("DELETE FROM pantry_items WHERE id=? AND mealie_item_id=?", (b["pantry_item_id"], item_id))
            return {"ok": True}

    def image(self, recipe_id, size):
        if NATIVE:
            fp = n_recipes.image_path(IMG_DIR, recipe_id)
            if not fp:
                return self.send(404, b"", "image/webp", {"Cache-Control": "public, max-age=600"})
            with open(fp, "rb") as f:
                return self.send(200, f.read(), mimetypes.guess_type(fp)[0] or "image/jpeg", {"Cache-Control": "public, max-age=86400"})
        fname = {"min": "min-original.webp", "tiny": "tiny-original.webp", "full": "original.webp"}.get(size, "min-original.webp")
        try:
            req = urllib.request.Request(f"{cfg('mealie_url')}/api/media/recipes/{recipe_id}/images/{fname}")
            with urllib.request.urlopen(req, timeout=15) as r:
                data = r.read()
            return self.send(200, data, "image/webp", {"Cache-Control": "public, max-age=86400"})
        except Exception:
            return self.send(404, b"", "image/webp", {"Cache-Control": "public, max-age=600"})

    def static(self, path):
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
        return self.send(200, data, ctype, {"Cache-Control": "no-cache"})


def _int_or_none(v):
    if v in (None, ""):
        return None
    try:
        return max(0, int(float(v)))
    except (TypeError, ValueError):
        return None


def main():
    init_db()
    load_cfg()
    if not get_internal("usda_synced_at"):
        def first_sync():
            try:
                sync_usda()
            except Exception as e:
                log(f"USDA FoodKeeper sync skipped ({e}); using starter shelf-life table. Retry from Settings.")
        threading.Thread(target=first_sync, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    if PUBLIC_MODE and not cfg("app_password_hash"):
        log(f"PUBLIC MODE · one-time setup code: {SETUP_CODE}  (enter it on the sign-in screen, then set a household password)")
    log(f"TablePlan {APP_VERSION} listening on :{LISTEN_PORT} · Mealie {cfg('mealie_url')} · data {DB_PATH} · "
        f"setup {'done' if cfg('setup_complete') else 'pending — open the app to run the wizard'}")
    ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
