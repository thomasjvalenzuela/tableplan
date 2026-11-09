"""Household members: accounts (password or PIN), per-user sign-in sessions and per-user state.

Everyone shares one household's data; accounts only decide who is signed in, who may manage members, and keep
small per-person preferences (theme, What's new, onboarding checklist, tour). Stdlib only; callers own the
transaction (row_factory=sqlite3.Row).
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'password',
    secret TEXT NOT NULL,
    admin INTEGER NOT NULL DEFAULT 0,
    notify_email INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    last_seen REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_user_sessions_user ON user_sessions(user_id);
"""

EMAIL_RE = re.compile(r"[^@\s]{1,64}@[^@\s]{1,253}\.[A-Za-z]{2,}")
PIN_MIN = 6
PASSWORD_MIN_PUBLIC = 10
PASSWORD_MIN_LOCAL = 8
STATE_KEYS = ("theme", "whatsnew_seen", "tour", "checklist", "account_prompt")


class UserError(ValueError):
    """A message that's safe to show to the person filling in the form."""


def init(c):
    c.executescript(SCHEMA)


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ------------------------------------------------------------------ secrets

def hash_secret(secret, salt=None):
    """scrypt (memory-hard) with a random salt; falls back to PBKDF2 where OpenSSL lacks scrypt."""
    salt = salt or os.urandom(16)
    try:
        dk = hashlib.scrypt(secret.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
        algo = "scrypt"
    except (AttributeError, ValueError):
        dk = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, 300_000)
        algo = "pbkdf2"
    return f"{algo}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def check_secret(secret, stored):
    if not isinstance(secret, str) or len(secret) > 1024:
        return False
    try:
        algo, salt_b64, dk_b64 = stored.split("$", 2)
        salt = base64.b64decode(salt_b64)
        if algo == "scrypt":
            dk = hashlib.scrypt(secret.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
        elif algo == "pbkdf2":
            dk = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, 300_000)
        else:
            return False
        return hmac.compare_digest(base64.b64encode(dk).decode().encode(), dk_b64.encode())
    except (ValueError, TypeError, AttributeError):
        return False


def validate_secret(kind, secret, public):
    """Raise UserError unless this password/PIN is allowed (PINs only on a home network)."""
    secret = secret if isinstance(secret, str) else ""
    if kind == "pin":
        if public:
            raise UserError(f"This TablePlan is reachable from the internet, so use a password of at least "
                            f"{PASSWORD_MIN_PUBLIC} characters instead of a PIN.")
        if not re.fullmatch(r"\d{%d,12}" % PIN_MIN, secret):
            raise UserError(f"A PIN is {PIN_MIN} to 12 digits.")
        if len(set(secret)) == 1 or secret in "01234567890123" or secret in "98765432109876":
            raise UserError("That PIN is too easy to guess. Avoid repeated or sequential digits.")
        return
    if kind != "password":
        raise UserError("Choose a password or a PIN.")
    need = PASSWORD_MIN_PUBLIC if public else PASSWORD_MIN_LOCAL
    if len(secret) < need:
        raise UserError(f"Use a password of at least {need} characters.")
    if len(secret) > 256:
        raise UserError("That password is too long.")


def _clean_name(name):
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:40]
    if not name:
        raise UserError("Enter a name.")
    return name


def _clean_email(email):
    email = str(email or "").strip()[:254]
    if email and not EMAIL_RE.fullmatch(email):
        raise UserError("That email address doesn't look right.")
    return email


# ------------------------------------------------------------------ members

def public_user(row):
    if row is None:
        return None
    return {"id": row["id"], "name": row["name"], "email": row["email"], "kind": row["kind"],
            "admin": bool(row["admin"]), "notify_email": bool(row["notify_email"]), "created_at": row["created_at"]}


def count(c):
    return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def get(c, user_id):
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def list_users(c):
    return [public_user(r) for r in c.execute("SELECT * FROM users ORDER BY admin DESC, name COLLATE NOCASE, id")]


def chooser(c):
    """What the sign-in screen may show before anyone is signed in: names only (plus how they sign in)."""
    return [{"id": r["id"], "name": r["name"], "kind": r["kind"]}
            for r in c.execute("SELECT id, name, kind FROM users ORDER BY name COLLATE NOCASE, id")]


def create(c, name, email, kind, secret, public, admin=None):
    name, email = _clean_name(name), _clean_email(email)
    validate_secret(kind, secret, public)
    if c.execute("SELECT 1 FROM users WHERE lower(name)=lower(?)", (name,)).fetchone():
        raise UserError(f"Someone called {name} already has an account. Use a different name.")
    first = count(c) == 0
    cur = c.execute("INSERT INTO users(name, email, kind, secret, admin, notify_email, state, created_at) "
                    "VALUES(?,?,?,?,?,0,'{}',?)",
                    (name, email, kind, hash_secret(secret), 1 if (first or admin) else 0, now_iso()))
    return get(c, cur.lastrowid)


def update(c, user_id, b, allow_admin_change):
    row = get(c, user_id)
    if row is None:
        raise UserError("That member no longer exists.")
    sets, args = [], []
    if "name" in b:
        name = _clean_name(b.get("name"))
        if c.execute("SELECT 1 FROM users WHERE lower(name)=lower(?) AND id<>?", (name, row["id"])).fetchone():
            raise UserError(f"Someone called {name} already has an account.")
        sets.append("name=?"); args.append(name)
    if "email" in b:
        sets.append("email=?"); args.append(_clean_email(b.get("email")))
    if "notify_email" in b:
        sets.append("notify_email=?"); args.append(1 if b.get("notify_email") else 0)
    if "admin" in b and allow_admin_change:
        make = bool(b.get("admin"))
        if not make and row["admin"] and c.execute("SELECT COUNT(*) FROM users WHERE admin=1").fetchone()[0] <= 1:
            raise UserError("The household needs at least one admin.")
        sets.append("admin=?"); args.append(1 if make else 0)
    if sets:
        c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", (*args, row["id"]))
    return get(c, row["id"])


def set_secret(c, user_id, kind, secret, public):
    row = get(c, user_id)
    if row is None:
        raise UserError("That member no longer exists.")
    validate_secret(kind, secret, public)
    c.execute("UPDATE users SET kind=?, secret=? WHERE id=?", (kind, hash_secret(secret), row["id"]))
    c.execute("DELETE FROM user_sessions WHERE user_id=?", (row["id"],))   # every device signs in again


def remove(c, user_id):
    row = get(c, user_id)
    if row is None:
        raise UserError("That member no longer exists.")
    if row["admin"] and c.execute("SELECT COUNT(*) FROM users WHERE admin=1").fetchone()[0] <= 1:
        raise UserError("You can't remove the only admin. Make someone else an admin first.")
    c.execute("DELETE FROM user_sessions WHERE user_id=?", (row["id"],))
    c.execute("DELETE FROM users WHERE id=?", (row["id"],))


def verify(c, user_id, secret, public):
    """The user row when the secret matches (PIN sign-in is refused on a public server)."""
    row = get(c, user_id)
    if row is None:
        check_secret(secret or "", hash_secret("timing-equaliser"))   # same work whether or not the account exists
        return None
    if row["kind"] == "pin" and public:
        return None
    return row if check_secret(secret or "", row["secret"]) else None


def notify_emails(c):
    return [r["email"] for r in c.execute("SELECT email FROM users WHERE notify_email=1 AND email<>''")]


# ------------------------------------------------------------------ sessions

def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(c, user_id, now):
    token = "u." + secrets.token_urlsafe(32)
    c.execute("INSERT INTO user_sessions(token_hash, user_id, created_at, last_seen) VALUES(?,?,?,?)",
              (_token_hash(token), int(user_id), now, now))
    # keep at most 20 devices per person
    c.execute("DELETE FROM user_sessions WHERE user_id=? AND token_hash NOT IN (SELECT token_hash FROM user_sessions "
              "WHERE user_id=? ORDER BY last_seen DESC LIMIT 20)", (int(user_id), int(user_id)))
    return token


def session_user(c, token, now, max_age):
    if not isinstance(token, str) or not token.startswith("u.") or len(token) > 100:
        return None
    row = c.execute("SELECT s.token_hash, s.created_at, s.last_seen, u.* FROM user_sessions s JOIN users u "
                    "ON u.id=s.user_id WHERE s.token_hash=?", (_token_hash(token),)).fetchone()
    if row is None:
        return None
    if now - row["created_at"] > max_age:
        c.execute("DELETE FROM user_sessions WHERE token_hash=?", (row["token_hash"],))
        return None
    if now - row["last_seen"] > 3600:
        c.execute("UPDATE user_sessions SET last_seen=? WHERE token_hash=?", (now, row["token_hash"]))
    return row


def end_session(c, token):
    if isinstance(token, str) and token.startswith("u."):
        c.execute("DELETE FROM user_sessions WHERE token_hash=?", (_token_hash(token),))


# ------------------------------------------------------------------ per-user state

def get_state(c, user_id):
    row = c.execute("SELECT state FROM users WHERE id=?", (int(user_id),)).fetchone()
    try:
        st = json.loads(row["state"]) if row else {}
    except (ValueError, TypeError):
        st = {}
    return st if isinstance(st, dict) else {}


def put_state(c, user_id, patch):
    st = get_state(c, user_id)
    for k, v in patch.items():
        if k in STATE_KEYS:
            if v is None:
                st.pop(k, None)
            else:
                st[k] = v
    data = json.dumps(st)
    if len(data) > 64_000:
        raise UserError("Too much saved state for this person.")
    c.execute("UPDATE users SET state=? WHERE id=?", (data, int(user_id)))
    return st
