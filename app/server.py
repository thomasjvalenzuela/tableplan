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
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
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
INSTALL_METHOD = env("TABLEPLAN_INSTALL", "zimaos")   # zimaos | cli | manual

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
    "auto_plan_email": False,
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
"""


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with db() as c:
        c.executescript(SCHEMA)
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
    "app_password_hash": "",
    "session_secret": "",
    "setup_complete": False,
}
SECRET_KEYS = {"mealie_token", "smtp_password", "app_password_hash", "session_secret"}
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
    return bool(cfg("app_password_hash"))


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
        "days_left": (exp - t).days if exp else None, "status": row["status"],
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


def recipe_pool(refresh=False):
    with _recipe_lock:
        if refresh or time.time() - _recipe_cache["at"] > 120:
            data = mealie("GET", "/api/recipes?page=1&perPage=-1&orderBy=name&orderDirection=asc")
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
                })
            _recipe_cache.update(at=time.time(), items=items)
        return list(_recipe_cache["items"])


def recipe_link(slug):
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
        "groups": [{"label": l, "items": [{"id": i["id"], "text": item_text(i), "name": item_name(i)} for i in items]}
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


def email_list(list_id):
    sl = get_list(list_id)
    page = print_list(sl)
    body = page.split("</div>", 1)[1].split("<script>")[0]  # drop the button bar + script
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", sl.get("name") or "list")
    send_email(f"🛒 {sl.get('name') or 'Shopping list'} — {datetime.now().strftime('%b %d')}",
               render_list_text(sl), email_wrap(f"<style>{PRINT_CSS}</style>{body}"),
               [(f"{safe}.csv", render_list_csv(sl).encode(), "text/csv")])


def email_plan(start, end):
    entries = get_plans(start, end)
    send_email(f"🍽️ Meal plan {fmt_day(start)} – {fmt_day(end)}", render_plan_text(entries, start, end),
               email_wrap(f"<style>{PRINT_CSS}</style><h1>Meal plan</h1><div class='sub'>{html.escape(fmt_day(start))} – {html.escape(fmt_day(end))}</div>"
                          + plan_table_html(entries, start, end)),
               [("meal-plan.csv", render_plan_csv(entries).encode(), "text/csv"),
                ("meal-plan.ics", render_plan_ics(entries).encode(), "text/calendar")])


def email_pantry():
    with db() as c:
        items = list_pantry(c)
    page = print_pantry(items)
    body = page.split("</div>", 1)[1].split("<script>")[0]
    lines = [f"{i['name']} — {i['location']} — use by {i['expires_on'] or '?'}" for i in items]
    send_email(f"🥫 Pantry — {datetime.now().strftime('%b %d')}", "\n".join(lines) or "Pantry is empty.",
               email_wrap(f"<style>{PRINT_CSS}</style>{body}"),
               [("pantry.csv", render_pantry_csv(items).encode(), "text/csv")])


# ============================================================ setup: Mealie account, AI, email

def mealie_status():
    out = {"url": cfg("mealie_url"), "reachable": False, "connected": False, "first_login": False,
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
    audio_id = None
    if audio:
        audio_id = upsert({**provider, "name": "OpenAI Whisper", "model": "whisper-1"})
    mealie("PUT", "/api/groups/ai-providers/settings", {
        "defaultProviderId": main_id,
        "imageProviderId": main_id if test.get("supportsImages") is not False else None,
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
            "mealie": mealie_status(), "ai": ai_status(), "email": email_public(),
            "password": {"set": auth_required()}, "version": APP_VERSION}


# ============================================================ recipe import (headless Mealie)

def import_url(url):
    if not re.match(r"^https?://", url or ""):
        raise ApiError(400, "Paste a full link starting with https://")
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
    slug = mealie("POST", "/api/recipes/create/ai", multipart=({"content": text or None}, files), timeout=300)
    return _imported(slug)


def _imported(slug):
    slug = slug.strip('"') if isinstance(slug, str) else slug
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


# ============================================================ meal plan → shopping list

def ensure_list(list_id=None):
    lists = get_lists()
    if list_id and any(l["id"] == list_id for l in lists):
        return list_id
    if lists:
        return lists[0]["id"]
    return mealie("POST", "/api/households/shopping/lists", {"name": "Groceries"})["id"]


def plan_to_list(start, end, list_id=None, skip_pantry=True):
    entries = [e for e in get_plans(start, end) if (e.get("recipe") or {}).get("id")]
    if not entries:
        raise ApiError(400, "No recipes planned in that range yet.")
    list_id = ensure_list(list_id)
    totals = {}
    for e in entries:
        rid = e["recipe"]["id"]
        totals.setdefault(rid, {"scale": 0.0, "slug": e["recipe"].get("slug"), "name": e["recipe"].get("name")})
        totals[rid]["scale"] += float(e.get("scale") or 1)
    have = set()
    if skip_pantry:
        with db() as c:
            for it in list_pantry(c):
                if it["amount_left"] >= 0.25 and (it["days_left"] is None or it["days_left"] >= 0):
                    have.add(food_key(it["name"]))
    payload, skipped = [], []
    for rid, t in totals.items():
        item = {"recipeId": rid, "recipeIncrementQuantity": round(t["scale"], 2)}
        if have and t["slug"]:
            try:
                rec = mealie("GET", f"/api/recipes/{urllib.parse.quote(t['slug'])}")
                keep = []
                for ing in rec.get("recipeIngredient") or []:
                    fname = (ing.get("food") or {}).get("name") or ""
                    if fname and food_key(fname) in have:
                        skipped.append(fname)
                    else:
                        keep.append(ing)
                if len(keep) != len(rec.get("recipeIngredient") or []):
                    item["recipeIngredients"] = keep
            except ApiError:
                pass
        payload.append(item)
    try:
        mealie("POST", f"/api/households/shopping/lists/{list_id}/recipe", payload, timeout=60)
    except ApiError:
        # Fall back to whole recipes if Mealie rejects the filtered ingredient lists.
        mealie("POST", f"/api/households/shopping/lists/{list_id}/recipe",
               [{"recipeId": p["recipeId"], "recipeIncrementQuantity": p["recipeIncrementQuantity"]} for p in payload], timeout=60)
        skipped = []
    return {"list_id": list_id, "recipes": len(payload), "skipped": sorted(set(skipped))}


# ============================================================ update check

_update_cache = {"at": 0, "data": None}


def update_info(force=False):
    if force or time.time() - _update_cache["at"] > 6 * 3600:
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
           "cli": "On the server run:  sudo tableplan update"}.get(INSTALL_METHOD, "Pull the new image and restart the container.")
    return {"version": APP_VERSION, "latest": latest, "update_available": available,
            "notes": feed.get("notes"), "released": feed.get("released"), "how": how, "install": INSTALL_METHOD}


# ============================================================ scheduler (optional weekly auto-plan)

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def scheduler():
    while True:
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
                    if s.get("auto_plan_email") and email_ready():
                        email_plan(start, start + timedelta(days=6))
        except Exception as e:  # never let the scheduler die
            log("scheduler error:", e)
        time.sleep(600)


# ============================================================ HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "TablePlan/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if "/health" not in (args[0] if args else ""):
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

    def send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, default=str)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
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
        n = int(self.headers.get("Content-Length") or 0)
        if n > 40_000_000:
            raise ApiError(413, "Request too large")
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw) if raw else {}

    def handle_any(self, method):
        url = urllib.parse.urlparse(self.path)
        path, q = url.path, {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if path == "/health":
            return self.send(200, "ok", "text/plain")
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "localhost").split(",")[0].strip()
        _req.host = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        _req.scheme = (self.headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip()
        public = (path == "/" or path.startswith("/static/") or path in ("/manifest.webmanifest", "/api/session", "/api/login"))
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
            return self.send(200, {"auth_required": auth_required(), "authed": self.authorized(),
                                   "setup_complete": bool(cfg("setup_complete")), "version": APP_VERSION})
        if m == "POST" and path == "/api/login":
            pw = self.body().get("password") or ""
            if not auth_required() or check_password(pw, cfg("app_password_hash")):
                return self.send(200, {"ok": True}, headers={
                    "Set-Cookie": f"tp_session={make_session()}; Path=/; Max-Age={180 * 86400}; HttpOnly; SameSite=Lax"})
            time.sleep(1.0)
            raise ApiError(401, "Wrong password")
        if m == "POST" and path == "/api/logout":
            return self.send(200, {"ok": True}, headers={"Set-Cookie": "tp_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})

        if m == "GET" and path == "/api/config":
            s = get_settings()
            base, slug = mealie_public(), cfg("group_slug")
            return self.send(200, {"mealie_url": base, "group_slug": slug,
                                   "email_ready": email_ready(), "mail_to": cfg("mail_to") or [], "settings": s,
                                   "usda_synced_at": get_internal("usda_synced_at"),
                                   "setup_complete": bool(cfg("setup_complete")), "connected": bool(cfg("mealie_token")),
                                   "household": {"name": cfg("household_name"), "people": cfg("people"),
                                                 "scale": bool(cfg("scale_to_household"))},
                                   "auth_required": auth_required(), "version": APP_VERSION,
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
        if m == "POST" and path == "/api/setup/password":
            pw = self.body().get("password") or ""
            if pw and len(pw) < 4:
                raise ApiError(400, "Use at least 4 characters.")
            set_cfg(app_password_hash=hash_password(pw) if pw else "")
            hdr = {"Set-Cookie": f"tp_session={make_session()}; Path=/; Max-Age={180 * 86400}; HttpOnly; SameSite=Lax"} if pw else None
            return self.send(200, {"set": bool(pw)}, headers=hdr)
        if m == "POST" and path == "/api/setup/complete":
            set_cfg(setup_complete=True)
            return self.send(200, {"ok": True})

        # ---- import & updates
        if m == "POST" and path == "/api/import/url":
            return self.send(200, import_url(self.body().get("url", "").strip()))
        if m == "POST" and path == "/api/import/images":
            b = self.body()
            return self.send(200, import_images(b.get("images") or [], b.get("text")))
        if m == "POST" and path == "/api/plan/to-list":
            b = self.body()
            s0 = parse_date(b.get("start")) or today()
            return self.send(200, plan_to_list(s0, parse_date(b.get("end")) or s0 + timedelta(days=6),
                                               b.get("list_id"), bool(b.get("skip_pantry", True))))
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
            n = save_plan(self.body().get("entries") or [])
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

        # --- email
        if m == "POST" and path == "/api/email":
            b = self.body()
            kind = b.get("kind")
            if kind == "list":
                email_list(b["id"])
            elif kind == "plan":
                s = parse_date(b.get("start")) or today()
                email_plan(s, parse_date(b.get("end")) or s + timedelta(days=6))
            elif kind == "pantry":
                email_pantry()
            elif kind == "test":
                send_email("TablePlan test email", "Email is working.", email_wrap("<p>Email is working ✓</p>"))
            else:
                raise ApiError(400, "Unknown email kind")
            return self.send(200, {"ok": True, "to": cfg("mail_to")})

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
    log(f"TablePlan {APP_VERSION} listening on :{LISTEN_PORT} · Mealie {cfg('mealie_url')} · data {DB_PATH} · "
        f"setup {'done' if cfg('setup_complete') else 'pending — open the app to run the wizard'}")
    ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
