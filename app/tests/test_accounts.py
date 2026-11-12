"""Accounts: hashing, PIN/password rules, per-user sessions, first-admin migration, member management, checklist."""

import http.client
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-acct-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import users as U  # noqa: E402

_NO_PROXY_ENV = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
_PATCHES = []


def setUpModule():
    for name, value in (("DATA_DIR", _TMP), ("DB_PATH", os.path.join(_TMP, "tableplan.db")),
                        ("IMG_DIR", os.path.join(_TMP, "images")), ("BACKUP_DIR", os.path.join(_TMP, "backups")),
                        ("NATIVE", True), ("PUBLIC_MODE", False)):
        p = mock.patch.object(S, name, value)
        p.start()
        _PATCHES.append(p)
    S.init_db()
    S.load_cfg()
    S.set_cfg(people=2, setup_complete=True, app_password_hash="")


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


def wipe():
    with S.db() as c:
        c.execute("DELETE FROM user_sessions")
        c.execute("DELETE FROM users")
    S.set_cfg(app_password_hash="")
    S.set_internal("anon_state", {})
    S._login_fails.clear()


class Secrets(unittest.TestCase):
    def test_hash_is_salted_and_verifies(self):
        a, b = U.hash_secret("correct horse"), U.hash_secret("correct horse")
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith(("scrypt$", "pbkdf2$")))
        self.assertTrue(U.check_secret("correct horse", a))
        self.assertFalse(U.check_secret("correct horsf", a))
        self.assertFalse(U.check_secret("x", "garbage"))

    def test_pin_and_password_rules(self):
        U.validate_secret("pin", "480913", public=False)
        for bad in ("12345", "abcdef", "111111", "123456", "654321"):
            with self.assertRaises(U.UserError):
                U.validate_secret("pin", bad, public=False)
        with self.assertRaises(U.UserError):
            U.validate_secret("pin", "480913", public=True)       # no PINs on the internet
        with self.assertRaises(U.UserError):
            U.validate_secret("password", "ninechars", public=True)
        U.validate_secret("password", "tenchars!!", public=True)
        U.validate_secret("password", "eightchr", public=False)


@mock.patch.dict(os.environ, _NO_PROXY_ENV, clear=True)
class AccountsHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = S.Server(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        wipe()

    def setUp(self):
        wipe()

    def req(self, method, path, body=None, cookie=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        h = {"X-TablePlan": "1", "Content-Type": "application/json"} if method != "GET" else {}
        if cookie:
            h["Cookie"] = cookie
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
        r = c.getresponse()
        raw = r.read()
        out = (r.status, dict(r.getheaders()), json.loads(raw) if raw[:1] in (b"{", b"[") else raw)
        c.close()
        return out

    def first(self, **kw):
        body = {"name": "Thomas", "email": "t@example.com", "kind": "password", "secret": "kitchen-table", **kw}
        st, hdrs, data = self.req("POST", "/api/account/first", body)
        self.assertEqual(st, 200, data)
        return hdrs["Set-Cookie"].split(";")[0], data["me"]

    def login(self, uid, secret, expect=200):
        st, hdrs, data = self.req("POST", "/api/login", {"user_id": uid, "secret": secret})
        self.assertEqual(st, expect, data)
        return hdrs.get("Set-Cookie", "").split(";")[0]

    def test_open_install_then_first_admin_locks_it(self):
        st, _, sess = self.req("GET", "/api/session")
        self.assertFalse(sess["auth_required"])
        self.assertTrue(sess["needs_account"])
        cookie, me = self.first()
        self.assertTrue(me["admin"])
        st, hdrs, sess = self.req("GET", "/api/session")
        self.assertTrue(sess["auth_required"])
        self.assertFalse(sess["authed"])
        self.assertEqual(sess["profiles"], [{"id": me["id"], "name": "Thomas", "kind": "password"}])   # names only
        self.assertNotIn("email", json.dumps(sess["profiles"]))
        self.assertEqual(self.req("GET", "/api/config")[0], 401)
        self.assertEqual(self.req("GET", "/api/config", cookie=cookie)[0], 200)
        self.assertEqual(self.req("POST", "/api/account/first", {"name": "Eve", "secret": "whatever123"}, cookie=cookie)[0], 409)

    def test_existing_password_install_migrates(self):
        S.set_cfg(app_password_hash=S.hash_password("oldpass"))
        st, hdrs, _ = self.req("POST", "/api/login", {"password": "oldpass"})
        self.assertEqual(st, 200)
        legacy = hdrs["Set-Cookie"].split(";")[0]
        st, _, sess = self.req("GET", "/api/session", cookie=legacy)
        self.assertTrue(sess["authed"] and sess["needs_account"] and sess["household_password"])
        st, hdrs, data = self.req("POST", "/api/account/first", {"name": "Thomas", "kind": "pin", "secret": "480913"}, cookie=legacy)
        self.assertEqual(st, 200, data)
        self.assertIn("SameSite=Strict", hdrs["Set-Cookie"])
        self.assertIn("HttpOnly", hdrs["Set-Cookie"])
        mine = hdrs["Set-Cookie"].split(";")[0]
        self.assertEqual(self.req("GET", "/api/config", cookie=legacy)[0], 401)      # old household sessions end
        self.assertEqual(self.req("GET", "/api/config", cookie=mine)[0], 200)
        self.assertEqual(self.req("POST", "/api/login", {"password": "oldpass"})[0], 400)   # must choose a profile

    def test_login_logout_throttle_and_wrong_secret(self):
        cookie, me = self.first(kind="pin", secret="480913")
        self.login(me["id"], "999999", expect=401)
        c2 = self.login(me["id"], "480913")
        self.assertEqual(self.req("GET", "/api/me", cookie=c2)[2]["me"]["name"], "Thomas")
        self.req("POST", "/api/logout", {}, cookie=c2)
        self.assertEqual(self.req("GET", "/api/config", cookie=c2)[0], 401)
        for _ in range(S.LOGIN_FAILS_PER_ACCOUNT):
            S.login_failed("203.0.113.%d" % _, me["id"])        # spread across addresses
        self.assertEqual(self.req("POST", "/api/login", {"user_id": me["id"], "secret": "480913"})[0], 429)
        S._login_fails.clear()
        with mock.patch.object(S, "PUBLIC_MODE", True):          # PINs stop working on a public server
            st, _, data = self.req("POST", "/api/login", {"user_id": me["id"], "secret": "480913"})
            self.assertEqual(st, 401)
            self.assertIn("password", data["error"])

    def test_members_admin_only_and_reset(self):
        admin, me = self.first()
        st, _, data = self.req("POST", "/api/users", {"name": "Sam", "email": "", "kind": "pin", "secret": "271828"}, cookie=admin)
        self.assertEqual(st, 200, data)
        sam_id = data["user"]["id"]
        self.assertFalse(data["user"]["admin"])
        sam = self.login(sam_id, "271828")
        # Sam can't manage members or reset sections
        self.assertEqual(self.req("POST", "/api/users", {"name": "Eve", "kind": "pin", "secret": "314159"}, cookie=sam)[0], 403)
        self.assertEqual(self.req("DELETE", f"/api/users/{me['id']}", cookie=sam)[0], 403)
        self.assertEqual(self.req("POST", "/api/reset/diary", {"confirm": "RESET"}, cookie=sam)[0], 403)
        # admin resets Sam's PIN: Sam's sessions end and the new PIN works
        self.assertEqual(self.req("POST", f"/api/users/{sam_id}/secret", {"kind": "pin", "secret": "161803"}, cookie=admin)[0], 200)
        self.assertEqual(self.req("GET", "/api/config", cookie=sam)[0], 401)
        self.login(sam_id, "271828", expect=401)
        sam = self.login(sam_id, "161803")
        # Sam changes their own name, can't make themself admin
        st, _, data = self.req("PATCH", "/api/me", {"name": "Samantha", "admin": True}, cookie=sam)
        self.assertEqual(data["me"]["name"], "Samantha")
        self.assertFalse(data["me"]["admin"])
        # the only admin can't be demoted or removed; admins can't remove themselves
        self.assertEqual(self.req("PATCH", f"/api/users/{me['id']}", {"admin": False}, cookie=admin)[0], 400)
        self.assertEqual(self.req("DELETE", f"/api/users/{me['id']}", cookie=admin)[0], 400)
        self.assertEqual(self.req("DELETE", f"/api/users/{sam_id}", cookie=admin)[0], 200)
        self.assertEqual(self.req("GET", "/api/config", cookie=sam)[0], 401)

    def test_change_own_secret_needs_current(self):
        cookie, me = self.first()
        self.assertEqual(self.req("POST", "/api/me/secret", {"current": "nope", "kind": "pin", "secret": "480913"}, cookie=cookie)[0], 400)
        st, hdrs, _ = self.req("POST", "/api/me/secret", {"current": "kitchen-table", "kind": "pin", "secret": "480913"}, cookie=cookie)
        self.assertEqual(st, 200)
        self.assertEqual(self.req("GET", "/api/config", cookie=cookie)[0], 401)     # old device signed out
        self.assertEqual(self.req("GET", "/api/config", cookie=hdrs["Set-Cookie"].split(";")[0])[0], 200)

    def test_per_user_theme_and_whatsnew(self):
        admin, me = self.first()
        self.req("POST", "/api/users", {"name": "Sam", "kind": "pin", "secret": "271828"}, cookie=admin)
        sam_id = [u for u in self.req("GET", "/api/users", cookie=admin)[2]["users"] if u["name"] == "Sam"][0]["id"]
        sam = self.login(sam_id, "271828")
        self.req("PUT", "/api/settings", {"theme": "dark", "whatsnew_seen": ["a"]}, cookie=admin)
        self.assertEqual(self.req("GET", "/api/settings", cookie=admin)[2]["theme"], "dark")
        self.assertEqual(self.req("GET", "/api/settings", cookie=sam)[2]["theme"], "system")
        self.assertEqual(self.req("GET", "/api/config", cookie=admin)[2]["settings"]["whatsnew_seen"], ["a"])
        self.assertEqual(self.req("PUT", "/api/settings", {"theme": "neon"}, cookie=sam)[0], 400)

    def test_checklist_auto_manual_custom_dismiss(self):
        st, _, cl = self.req("GET", "/api/checklist")
        self.assertEqual(cl["total"], 14)   # includes "Turn on AI recipe import"
        self.assertFalse({i["id"]: i for i in cl["items"]}["account"]["done"])
        cookie, me = self.first()
        cl = self.req("GET", "/api/checklist", cookie=cookie)[2]
        items = {i["id"]: i for i in cl["items"]}
        self.assertTrue(items["account"]["done"] and items["account"]["auto"])
        self.req("POST", "/api/checklist", {"action": "tick", "id": "cook"}, cookie=cookie)
        self.req("POST", "/api/checklist", {"action": "rename", "id": "plan", "title": "Plan Monday"}, cookie=cookie)
        self.req("POST", "/api/checklist", {"action": "hide", "id": "members"}, cookie=cookie)
        st, _, cl = self.req("POST", "/api/checklist", {"action": "add", "title": "Try the scanner", "link": "#pantry"}, cookie=cookie)
        items = {i["id"]: i for i in cl["items"]}
        self.assertTrue(items["cook"]["done"])
        self.assertEqual(items["plan"]["title"], "Plan Monday")
        self.assertEqual(cl["total"], 14)         # 14 built-in - 1 hidden + 1 custom
        self.assertEqual(self.req("POST", "/api/checklist", {"action": "add", "title": "x", "link": "javascript:alert(1)"}, cookie=cookie)[0], 400)
        self.assertEqual(self.req("POST", "/api/checklist", {"action": "dismiss"}, cookie=cookie)[0], 400)
        for it in cl["items"]:
            if not it["hidden"]:
                self.req("POST", "/api/checklist", {"action": "tick", "id": it["id"]}, cookie=cookie)
        st, _, cl = self.req("POST", "/api/checklist", {"action": "dismiss"}, cookie=cookie)
        self.assertTrue(cl["complete"] and cl["dismissed"])
        # another member has their own checklist
        self.req("POST", "/api/users", {"name": "Sam", "kind": "pin", "secret": "271828"}, cookie=cookie)
        sam_id = [u for u in self.req("GET", "/api/users", cookie=cookie)[2]["users"] if u["name"] == "Sam"][0]["id"]
        cl = self.req("GET", "/api/checklist", cookie=self.login(sam_id, "271828"))[2]
        self.assertFalse(cl["dismissed"])
        self.assertTrue({i["id"]: i for i in cl["items"]}["members"]["done"])   # two members now

    def test_not_now_snooze_takes_a_millisecond_timestamp(self):
        import time as _t
        st, _, data = self.req("PUT", "/api/me/state", {"account_prompt": int(_t.time() * 1000) + 3 * 86400000})
        self.assertEqual(st, 200, data)
        self.assertGreater(data["state"]["account_prompt"], 10 ** 12)

    def test_checklist_inventory_by_place(self):
        st, _, cl = self.req("GET", "/api/checklist")
        ids = [i["id"] for i in cl["items"]]
        for k in ("inv_fridge", "inv_freezer", "inv_pantry", "inv_spices", "inv_baking"):
            self.assertIn(k, ids)
        self.assertNotIn("inventory", ids)
        links = {i["id"]: i["link"] for i in cl["items"]}
        self.assertEqual(links["inv_spices"], "stock:spices")
        with S.db() as c:
            c.execute("DELETE FROM pantry_items")
            for n in ("Cumin", "Paprika", "Oregano", "Cinnamon"):
                S.add_pantry_item(c, n, "spices")
        items = {i["id"]: i for i in self.req("GET", "/api/checklist")[2]["items"]}
        self.assertFalse(items["inv_spices"]["done"])                   # 4 isn't enough
        with S.db() as c:
            S.add_pantry_item(c, "Nutmeg", "spices")
            row = c.execute("SELECT location, place FROM pantry_items WHERE name='Nutmeg'").fetchone()
        self.assertEqual((row["location"], row["place"]), ("pantry", "spices"))   # a pantry shelf
        items = {i["id"]: i for i in self.req("GET", "/api/checklist")[2]["items"]}
        self.assertTrue(items["inv_spices"]["done"] and items["inv_spices"]["auto"])
        self.assertFalse(items["inv_pantry"]["done"])                   # the spice cabinet isn't the pantry
        # an old checklist's manual "Stock your inventory" tick moves to the pantry
        S.set_internal("anon_state", {"checklist": {"done": ["inventory", "cook"], "hidden": [], "renamed": {"inventory": "x"}, "custom": []}})
        items = {i["id"]: i for i in self.req("GET", "/api/checklist")[2]["items"]}
        self.assertTrue(items["inv_pantry"]["done"] and not items["inv_pantry"]["auto"])
        self.assertTrue(items["cook"]["done"])
        # a removed place comes back when its checklist step is used
        S.save_settings({"locations": [p for p in S.DEFAULT_PLACES if p["key"] != "baking"]})
        self.assertNotIn("baking", S.places())
        self.assertEqual(self.req("POST", "/api/places/ensure", {"key": "baking"})[0], 200)
        self.assertEqual(S.places()["baking"]["label"], "Baking supplies")
        self.assertEqual(self.req("POST", "/api/places/ensure", {"key": "garage"})[0], 404)
        with S.db() as c:
            c.execute("DELETE FROM pantry_items")

    def test_notify_emails_join_recipients(self):
        cookie, me = self.first()
        S.set_cfg(mail_to=["house@example.com"])
        self.req("PATCH", "/api/me", {"notify_email": True, "email": "T@example.com"}, cookie=cookie)
        self.assertEqual(S.mail_recipients(), ["house@example.com", "T@example.com"])
        S.set_cfg(mail_to=[])


if __name__ == "__main__":
    unittest.main()
