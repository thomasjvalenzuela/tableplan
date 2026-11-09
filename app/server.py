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

LOCATIONS = ("fridge", "freezer", "pantry")
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
    "oven": "conventional",           # conventional | convection
    "temp_unit": "F",                 # F | C
    "ai_budget": 0,                   # monthly USD; 0 = no alert
    "pantry_check_days": 7,           # remind to review the pantry every N days (0 = off)
    "expiring_window_days": 3,
    "plan_horizon_days": 14,          # how many days the planner board shows
    "plan_reminder_days": 3,          # remind when the plan runs out within N days (0 = off)
    "polish_imports": True,           # AI rewrites imported steps clearly (never amounts); needs an OpenAI key
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
        cols = {r[1] for r in c.execute("PRAGMA table_info(pantry_items)")}
        for col, typ in (("qty", "REAL"), ("unit", "TEXT"), ("original_qty", "REAL")):
            if col not in cols:   # known amounts: qty left in `unit`, original_qty = the full package
                c.execute(f"ALTER TABLE pantry_items ADD COLUMN {col} {typ}")
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
    "oven": _v_enum("conventional", "convection"),
    "temp_unit": _v_enum("F", "C"),
    "ai_budget": _v_num(0, 100_000),
    "pantry_check_days": _v_int(0, 365),
    "expiring_window_days": _v_int(0, 60),
    "plan_horizon_days": _v_int(7, 28),
    "plan_reminder_days": _v_int(0, 7),
    "polish_imports": _v_bool,
    "categories": _v_categories,
}


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


def auth_required():
    return bool(cfg("app_password_hash")) or PUBLIC_MODE


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


def login_throttled(ip):
    now = time.time()
    with _login_lock:
        _recent_fails(now)
        total = sum(len(v) for v in _login_fails.values())
        return len(_login_fails.get(ip, [])) >= LOGIN_FAILS_PER_IP or total >= LOGIN_FAILS_GLOBAL


def login_failed(ip):
    with _login_lock:
        _login_fails.setdefault(ip, []).append(time.time())


def login_succeeded(ip):
    with _login_lock:
        _login_fails.pop(ip, None)


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
                    qty=None, unit=None):
    """Stock an item. qty/unit, when known, are the amount bought (otherwise parsed from quantity_text)."""
    if qty is None and quantity_text:
        qty, unit = parse_amount(quantity_text)
    qty = float(qty) if qty is not None and float(qty) > 0 else None
    unit = n_units.normalize(unit) if qty is not None else None
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
           expiry_source, rule_id, mealie_item_id, created_at, qty, unit, original_qty) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (name.strip(), quantity_text or "", loc, iso(t), iso(t) if loc == "freezer" else None, iso(exp), src,
         rule["id"] if rule else None, mealie_item_id, datetime.now().isoformat(timespec="seconds"), qty, unit, qty))
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
        if item["qty"] is not None and (item["original_qty"] or item["qty"]):
            updates["qty"] = round(left * (item["original_qty"] or item["qty"]), 4)   # keep the known amount in step
            updates["original_qty"] = item["original_qty"] or item["qty"]
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
        "qty": row["qty"], "unit": row["unit"] or "", "left_text": pantry_left_text(row),
        "rule": {"id": rule["id"], "name": rule["name"], "source": rule["source"],
                 **{f: rule[f] for f in RULE_FIELDS}, "tips": rule["tips"]} if rule else None,
    }


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
        "ingredients": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["section", "line"],
                                                    "properties": {"section": {"type": "string"}, "line": {"type": "string"}}}},
        "steps": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
        "categories": {"type": "array", "items": {"type": "string"}},
    },
}


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


def ai_recipe(text, images=None, feature="recipe import", detail=""):
    """Turn free text and/or images into a recipe (Mealie-shaped dict) with OpenAI."""
    if not cfg("openai_key"):
        raise ApiError(400, "This needs AI. Add your OpenAI key in Settings → AI recipe import.")
    content = [{"type": "text", "text": (
        "Extract the single recipe from the material below. Clean up typos, spacing and formatting, but never change the recipe: keep every amount, ingredient, temperature, time and step exactly. Copy ingredient lines with amounts, amount first "
        "(e.g. '1 1/2 cups heavy cream'); put section headings in 'section' (empty if none). Steps are the instructions "
        "in order, one per item. source_url: the recipe's web address if one is visible (e.g. in a page header or footer), else empty. Use 0 for unknown numbers. If there is no recipe, set found=false. Never invent content. Set complete=false when part of the recipe is clearly missing: no ingredient list, no instructions, text cut off mid-list or mid-step (e.g. a second page or screenshot wasn't included), or steps that use ingredients the list doesn't include; then explain what's missing in 'missing' (one short sentence). Missing amounts in a spoken video recipe do not count as incomplete. " + _category_prompt())
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
            "tags": [{"name": t} for t in (out.get("tags") or [])[:8]],
            "recipeCategory": _pick_categories(out.get("categories"))}


POLISH_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["description", "ingredients", "steps", "categories"],
    "properties": {
        "description": {"type": "string"}, "categories": {"type": "array", "items": {"type": "string"}},
        "ingredients": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                    "required": ["section", "line"],
                                                    "properties": {"section": {"type": "string"}, "line": {"type": "string"}}}},
        "steps": {"type": "array", "items": {"type": "string"}},
    },
}
POLISH_PROMPT = (
    "You are editing a recipe for a home cook. Return the same recipe with clearer wording.\n"
    "- description: 1-2 appetizing, factual sentences about the dish.\n"
    "- ingredients: exactly the same number of lines, in the same order, with the same section headings. Tidy the "
    "wording and spell out units (e.g. '2 c. flour' -> '2 cups all-purpose flour', 'tbs' -> 'tablespoons').\n"
    "- steps: rewrite each step as clear, complete, descriptive sentences. Name the pan or vessel, the heat level, "
    "temperatures, times and doneness cues (e.g. 'until golden and 165°F inside') when the source gives them.\n"
    "NEVER change ingredients, amounts, temperatures, times or the order of the method. Never add or remove "
    "ingredients, and never add or remove actions in the steps. If the source lacks a detail, do not invent numbers; "
    "just write the sentence clearly. Keep section headings as they are.")
_NUM_TOKEN = re.compile(r"\d+(?:[.,/]\d+)?|[½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞]")


def _num_tokens(line):
    """Digit and fraction tokens of a line ('1 ½ cups' -> {'1', '½'}), to check a rewrite kept every number."""
    return set(_NUM_TOKEN.findall(line or ""))


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
              "ingredients": [{"section": sec, "line": ln} for sec, ln in zip(sections, orig_lines)], "steps": orig_steps}
    out = openai_chat([{"role": "system", "content": POLISH_PROMPT + "\n- " + _category_prompt()
                        + (("\n" + extra) if extra else "")},
                       {"role": "user", "content": json.dumps(source, ensure_ascii=False)}],
                      "recipe_polish", POLISH_SCHEMA, "polish", (data.get("name") or "")[:80])
    new_steps = [x.strip() for x in out.get("steps") or [] if isinstance(x, str) and x.strip()]
    if len(new_steps) < len(orig_steps) - 1 or not new_steps and orig_steps:
        log(f"polish discarded for {data.get('name')!r}: steps {len(orig_steps)} -> {len(new_steps)}")
        return data
    new_lines = [(x.get("line") or "").strip() for x in out.get("ingredients") or [] if isinstance(x, dict)]
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


def _save_new_recipe(data, image_url=None):
    if _polish_on():
        try:
            data = polish_recipe(data)
        except Exception as e:   # the import still succeeds, just unpolished
            log("recipe polish skipped:", getattr(e, "message", None) or e)
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
                gone = n_recipes.get(c, key)
                n_recipes.delete(c, key, images_dir=IMG_DIR)
                if gone:   # its unbought list lines go too (shared lines keep the other recipes' amounts)
                    for lst in n_lists.list_lists(c):
                        n_lists.remove_recipe_items(c, lst["id"], gone["id"])
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
                                               aisle_for, food_key)
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
                n_lists.add_items(c, lid, texts, parse_ing_text, aisle_for, food_key)
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
    msg["Subject"], msg["From"] = re.sub(r"[\r\n]+", " ", subject)[:250], sender
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
        raise ApiError(502, str(err)[:300] if err else f"HTTP {e.code}")
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
    out = mealie("PUT", f"/api/recipes/{_q(slug)}", r)
    _recipe_cache["at"] = 0
    with db() as c:
        c.execute("DELETE FROM guided_cache WHERE recipe_id=?", (r.get("id"),))
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
    if cfg("openai_key"):   # prepare the AI step-by-step version in the background so it's instant later
        background(guided, slug, True)
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
        "missing": recipe_missing(r["id"]), "cook_entry": cook_entry_for(r["id"]),
        "original": _original(r),
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
        slug = n_recipes.update(c, rec["id"], new)
        c.execute("DELETE FROM guided_cache WHERE recipe_id=?", (rec["id"],))
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
        slug = n_recipes.update(c, rec["id"], rec)
        c.execute("DELETE FROM guided_cache WHERE recipe_id=?", (rec["id"],))
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


def missing_counts():
    if not NATIVE:
        return {}
    with db() as c:
        return n_lists.missing_counts(c, n_lists.single_list(c))


def enrich_plan(entries):
    """Add recipe minutes and the "missing N" readiness count to plan entries."""
    try:
        pool = {r["id"]: r for r in recipe_pool()}
    except ApiError:
        pool = {}
    counts = missing_counts()
    for e in entries:
        r = e.get("recipe")
        if r:
            r["minutes"] = (pool.get(r.get("id")) or {}).get("minutes")
            r.setdefault("image_v", "")
        e["missing"] = counts.get((r or {}).get("id"), 0) if r else 0
    return entries


def plan_entry(entry_id, day):
    return next((e for e in enrich_plan(get_plans(day, day)) if str(e["id"]) == str(entry_id)), None)


def plan_assign(b):
    """Put a recipe on a day (replacing that day's entry of the same type) and add its ingredients to the list."""
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
    # Everything that reads through other connections happens before the write transaction.
    scale = household_scale(rid)
    have = _pantry_have_keys()
    lines, skipped = [], []
    for ing in rec.get("recipeIngredient") or []:
        line = _ing_line(ing)
        if not line:
            continue
        fname, _ = ing_food(ing)
        if fname and food_key(fname) in have:
            skipped.append(fname)
            continue
        lines.append(line)
    added, replaced = [], 0
    with db() as c:
        lid = n_lists.single_list(c)
        existing = n_plans.entries_on(c, iso(d), et)
        same = next((x for x in existing if x["recipe_id"] == rid), None)
        if same:
            eid, skipped = same["id"], []
        else:
            for old in existing:
                n_plans.delete_entry(c, old["id"])
                replaced += _drop_entry_items(c, lid, old)
            eid = n_plans.add_entry(c, iso(d), et, rid, scale=scale)
            added = n_lists.add_recipe_ingredients(c, lid, rid, lines, scale, parse_ing_text, aisle_for, food_key)
    return {"entry": plan_entry(eid, d), "added": len(set(added)),
            "skipped": sorted(set(skipped), key=str.lower), "replaced_removed": replaced}


def plan_move(b):
    """Move an entry to another day; if that day already has one of the same type, the two swap."""
    require_native()
    eid = _int_id(b.get("id"))
    d = _strict_date(b.get("date"))
    with db() as c:
        e = n_plans.get_entry(c, eid)
        if not e:
            raise ApiError(404, "Plan entry not found")
        if e["date"] == iso(d):
            return {"ok": True, "swapped_with": None}
        other = n_plans.entries_on(c, iso(d), e["entry_type"], exclude_id=eid)
        swapped = None
        if other:
            n_plans.update_entry(c, other[0]["id"], date=e["date"])
            swapped = other[0]["id"]
        n_plans.update_entry(c, eid, date=iso(d))
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
        removed = _drop_entry_items(c, n_lists.single_list(c), e)
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
    info = [{"id": r["id"], "name": r.get("name") or "", "minutes": (pool.get(r["id"]) or {}).get("minutes") or 0,
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
                "and longer ones on weekends. Recipes that use these soon-to-expire pantry foods should come first: "
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
    return {"ok": True}


COOK_SNAPSHOT = ("qty", "unit", "original_qty", "amount_left", "status", "finished_on", "opened_on", "expires_on",
                 "expiry_source")


def _pantry_by_key(c):
    """Active pantry rows by food key (plain and cleaned names), soonest-expiring first."""
    out = {}
    rows = c.execute("SELECT * FROM pantry_items WHERE status='active' ORDER BY "
                     "CASE WHEN expires_on IS NULL THEN 1 ELSE 0 END, expires_on, id").fetchall()
    for r in rows:
        for k in {food_key(r["name"]), food_key(clean_food(r["name"]))}:
            if k:
                out.setdefault(k, []).append(r["id"])
    return out


def _cook_needs(rec, factor):
    """[(food name, quantity or None, unit)] for a recipe's non-staple ingredients, scaled by factor."""
    out = []
    for ing in rec.get("recipeIngredient") or []:
        line = _ing_line(ing)
        if not line:
            continue
        p = parse_ing_text(line)
        if p:
            name, q, unit = clean_food(p["food"]), p["quantity"] * factor, p["unit"] or ""
        else:
            name, q, unit = clean_food(line), None, ""
        key = food_key(name)
        if not key or name.lower() in STAPLES or key in _STAPLE_KEYS:
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
        for name, need, unit in _cook_needs(rec, factor):
            ids = pantry.get(food_key(name)) or []
            row = next((r for r in (pantry_row(c, i) for i in ids) if r and r["status"] == "active"), None)
            if not row:
                continue
            if row["id"] not in snap:
                snap[row["id"]] = {k: row[k] for k in COOK_SNAPSHOT}
                event(c, row["id"], "cooked", json.dumps({"token": token, "before": snap[row["id"]],
                                                          "recipe": rec.get("name") or ""}))
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
        if entry:
            prev = n_plans.set_cooked(c, plan_id, now)
            c.execute("INSERT INTO pantry_events(item_id, at, action, detail) VALUES (NULL,?,?,?)",
                      (now, "cooked-plan", json.dumps({"token": token, "plan_id": plan_id, "before": prev})))
        c.execute("INSERT INTO pantry_events(item_id, at, action, detail) VALUES (NULL,?,?,?)",
                  (now, "cooked-recipe", json.dumps({"token": token, "recipe_id": rec["id"]})))
    return {"ok": True, "deducted": deducted, "unknown": sorted(set(unknown), key=str.lower),
            "finished": sorted(set(finished), key=str.lower), "undo_token": token, "plan_id": plan_id}


def cooked_undo(b):
    """Put the pantry back the way it was before a "cooked", and un-cook the plan entry."""
    require_native()
    token = _s((b or {}).get("undo_token"), 64).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", token):
        raise ApiError(400, "Nothing to undo.")
    restored = 0
    with db() as c:
        rows = c.execute("SELECT * FROM pantry_events WHERE action IN ('cooked', 'cooked-plan', 'cooked-recipe') "
                         "AND detail LIKE ? ORDER BY id DESC", (f'%"token": "{token}"%',)).fetchall()
        rows = [(r, json.loads(r["detail"])) for r in rows]
        rows = [(r, d) for r, d in rows if d.get("token") == token]
        if not rows:
            raise ApiError(404, "That can't be undone any more.")
        for r, d in rows:
            if r["action"] == "cooked" and r["item_id"] is not None:
                before = {k: d["before"].get(k) for k in COOK_SNAPSHOT}
                c.execute(f"UPDATE pantry_items SET {', '.join(f'{k}=?' for k in COOK_SNAPSHOT)} WHERE id=?",
                          (*before.values(), r["item_id"]))
                event(c, r["item_id"], "cook undone")
                restored += 1
            elif r["action"] == "cooked-plan":
                try:
                    n_plans.set_cooked(c, d["plan_id"], d.get("before"))
                except KeyError:
                    pass
            c.execute("UPDATE pantry_events SET action=action || ' (undone)' WHERE id=?", (r["id"],))
    return {"ok": True, "restored": restored}


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
    return " ".join(x for x in (nice_qty(i.get("quantity")) if (i.get("food") or i.get("unit")) else "",
                                ((i.get("unit") or {}).get("name") or "")) if x)


def list_item_json(i, names):
    food = (i.get("food") or {}).get("name") or ""
    return {"id": i["id"], "text": item_text(i), "name": item_name(i), "food": food, "qty": _qty_text(i),
            "emoji": food_emoji(food or i.get("note") or i.get("display")), "checked": bool(i.get("checked")),
            "checked_at": i.get("checkedAt"), "have": i.get("checkedHow") == "have",
            "store_id": i.get("storeId"), "aisle": ((i.get("label") or {}).get("name") or "Other"),
            "recipes": [names[r] for r in i.get("recipeIds") or [] if r in names]}


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
    order = {s["id"]: i for i, s in enumerate(stores)}
    unchecked = [list_item_json(i, names) for i in sl["listItems"] if not i["checked"]]
    items = unchecked + [list_item_json(i, names) for i in fresh]
    items.sort(key=lambda x: (order.get(x["store_id"], len(order)), x["aisle"] == "Other", x["aisle"].lower()))
    return {"id": lid, "name": sl["name"], "items": items, "count": len(unchecked),
            "recently_checked": [list_item_json(i, names) for i in recent],
            "stores": [{"id": s["id"], "name": s["name"]} for s in stores]}


def _store_arg(v):
    if v in (None, ""):
        return None
    return _s(v, 64).strip() or None


def _item_key(it):
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
            ids = n_lists.add_items(c, lid, items, parse_ing_text, aisle_for, food_key, sid)
        except KeyError:
            raise ApiError(404, "Store not found")
        names = _recipe_names(c)
        out = [list_item_json(n_lists.get_item(c, i), names) for i in dict.fromkeys(ids)]
    return {"ok": True, "added": len(out), "items": out}


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


def recipe_have_all(slug):
    require_native()
    with db() as c:
        rec = n_recipes.get(c, slug)
        if not rec:
            raise ApiError(404, "Recipe not found")
        lid = n_lists.single_list(c)
        n = n_lists.mark_have(c, [x["id"] for x in n_lists.unchecked_for_recipe(c, lid, rec["id"])])
    return {"ok": True, "count": n}


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
                row = c.execute("SELECT data, updated FROM guided_cache WHERE recipe_id=? AND profile=?",
                                (rec["id"], _guided_profile() + "|ai2")).fetchone()
            data = json.loads(row["data"]) if row and row["updated"] == rec["updated"] else guided(slug, False)
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
            # "Your meal plan runs out" reminder (once per run-out)
            try:
                notify_plan_runout(now)
            except ApiError as e:
                log("plan reminder not sent:", e.message)
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

# Request body limits: screenshots/PDFs and photo uploads are big, everything else is small JSON.
BODY_LIMITS = [
    (re.compile(r"/api/import/images"), 36_000_000),            # ~25 MB of files once base64-encoded
    (re.compile(r"/api/recipe/[^/]+/image/upload|/api/ingredient-image/upload"), 12_000_000),   # 8 MB image
]
BODY_LIMIT_DEFAULT = 1_000_000

# Expensive endpoints: rate-limited per client in public mode, and imports run a few at a time.
EXPENSIVE = [
    (re.compile(r"/api/import/(url|text|images)"), "import"),
    (re.compile(r"/api/setup/import-mealie"), "import"),
    (re.compile(r"/api/recipe/[^/]+/(guided|image/next|polish)"), "ai"),
    (re.compile(r"/api/plan/arrange"), "ai"),
    (re.compile(r"/api/(setup/ai|setup/openai-admin|ingredient-image/next)"), "ai"),
    (re.compile(r"/api/(upc/\d+|send|email|rules/sync-usda|setup/email|setup/ntfy|setup/telegram.*)"), "fetch"),
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
    def authorized(self):
        if not auth_required():
            return True
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "tp_session" and valid_session(v):
                return True
        return False

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
        return f"tp_session={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}"

    def send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
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
            return self.send(e.status, {"error": e.message})
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

        # static
        if m == "GET" and (path == "/" or path.startswith("/static/") or path in ("/manifest.webmanifest", "/sw.js")):
            return self.static(path, q)

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
                login_succeeded(ip)
                return self.send(200, {"ok": True}, headers={"Set-Cookie": self.cookie(make_session())})
            login_failed(ip)
            log(f"failed sign-in from {ip}")
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
            return self.send(200, {"ok": True})

        # ---- import & updates
        if m == "POST" and path == "/api/import/url":
            return self.send(200, import_url(_s(self.body().get("url"), 4000).strip()))
        if m == "POST" and path == "/api/import/text":
            b = self.body()
            return self.send(200, import_text(_s(b.get("text"), 200_000), _s(b.get("title"), 300)))
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
        mm = re.fullmatch(r"/api/recipe/([A-Za-z0-9_.~%-]{1,200})/(favorite|guided|image/next|image/upload|to-list|have-all|cooked|polish|restore-original)", path)
        if mm:
            slug, act = urllib.parse.unquote(mm.group(1)), mm.group(2)
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
                blob, ctype = decode_upload(self.body().get("data"))
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
                return self.send(200, save_settings(self.body()))
            return self.send(200, get_settings())

        # --- recipes & images
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
            return self.send(200, {"recipes": [{**r, "link": recipe_link(r["slug"])} for r in pool], "tags": tags})

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
        mm = re.fullmatch(r"/api/plan/(\d{1,15})/skip", path)
        if m == "POST" and mm:
            return self.send(200, plan_skip(int(mm.group(1)), self.body().get("skipped", True) is not False))
        if m == "POST" and path == "/api/cooked/undo":
            return self.send(200, cooked_undo(self.body()))

        # --- the ongoing list and stores
        if m == "GET" and path == "/api/list":
            return self.send(200, ongoing_list())
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

    def patch_item(self, it, b):
        """PATCH /api/list/items/{id}: store_id (remembered per food), text, checked (the bought / undo flow)."""
        item_id = it["id"]
        out = {"ok": True}
        if "text" in b:
            text = _s(b.get("text"), 200).strip()
            if not text:
                raise ApiError(400, "Type the item.")
            with db() as c:
                n_lists.set_item_text(c, item_id, text, parse_ing_text, aisle_for)
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
            # Versioned asset URLs: a Home Screen app picks up new code as soon as the server is updated.
            v = urllib.parse.quote(APP_VERSION, safe="")
            for a in VERSIONED_ASSETS:
                data = data.replace(f'"/static/{a}"'.encode(), f'"/static/{a}?v={v}"'.encode())
            return self.send(200, data, ctype, {"Cache-Control": "no-store"})
        if rel in VERSIONED_ASSETS and (q or {}).get("v") == APP_VERSION:
            return self.send(200, data, ctype, {"Cache-Control": "public, max-age=31536000, immutable"})
        return self.send(200, data, ctype, {"Cache-Control": "no-cache"})


VERSIONED_ASSETS = ("app.css", "app.js", "recipes.js", "setup.js")


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
    if PUBLIC_MODE and not cfg("app_password_hash"):
        log(f"PUBLIC MODE · one-time setup code: {SETUP_CODE}  (enter it on the sign-in screen, then set a household password)")
    log(f"TablePlan {APP_VERSION} listening on :{LISTEN_PORT} · {'public' if PUBLIC_MODE else 'home network'} mode"
        f"{' · trusting proxy headers' if TRUST_PROXY else ''} · backend {'native' if NATIVE else 'Mealie'} · data {DB_PATH} · "
        f"setup {'done' if cfg('setup_complete') else 'pending — open the app to run the wizard'}")
    Server(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
