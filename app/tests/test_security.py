"""Security regression tests for the HTTP server: SSRF guards, auth in public mode, path validation, limits."""

import gzip
import http.client
import http.server
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import zlib
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-sec-")
os.environ["DATA_DIR"] = _TMP

from app import server as S  # noqa: E402
from app.native import recipes as n_recipes  # noqa: E402

_NO_PROXY_ENV = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
RID = "11111111-2222-3333-4444-555555555555"


def setUpModule():
    S.init_db()
    S.load_cfg()


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


class _Redirector(http.server.BaseHTTPRequestHandler):
    """Local test server: /start redirects to /secret (an "internal" resource); /file redirects to file://."""

    def do_GET(self):
        if self.path == "/start":
            self.send_response(302)
            self.send_header("Location", "/secret")
        elif self.path == "/file":
            self.send_response(302)
            self.send_header("Location", "file:///etc/passwd")
        else:
            self.send_response(200)
        self.send_header("Content-Length", "6")
        self.end_headers()
        self.wfile.write(b"secret")

    def log_message(self, *a):
        pass


def _serve(handler):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


class AddressChecks(unittest.TestCase):
    def test_private_and_special_addresses_rejected(self):
        for ip in ("127.0.0.1", "10.1.2.3", "192.168.1.1", "172.16.0.1", "169.254.169.254", "100.64.0.1",
                   "0.0.0.0", "::1", "fe80::1", "fd00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "224.0.0.1",
                   "2002:7f00:1::1", "not-an-ip"):
            self.assertFalse(S._ip_public(ip), ip)
        for ip in ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"):
            self.assertTrue(S._ip_public(ip), ip)

    def test_public_host_rejects_internal_urls(self):
        for url in ("http://127.0.0.1/", "http://localhost:9000/", "http://[::1]/", "http://169.254.169.254/latest",
                    "file:///etc/passwd", "ftp://example.com/", "gopher://127.0.0.1/", "http:///nohost", "http://0/"):
            self.assertFalse(S._public_host(url), url)

    def test_fetch_page_refuses_private_address(self):
        with self.assertRaises(S.ApiError) as cm:
            S._fetch_page("http://127.0.0.1:1/recipe")
        self.assertEqual(cm.exception.status, 400)

    def test_fetch_image_refuses_private_address(self):
        with self.assertRaises(ValueError):
            S._fetch_image("https://127.0.0.1/x.png")

    def test_video_links_only_for_known_hosts(self):
        self.assertTrue(S._video_url_ok("https://www.youtube.com/watch?v=abc"))
        self.assertTrue(S._video_url_ok("https://www.instagram.com/reel/abc/"))
        for url in ("http://169.254.169.254/", "https://evil.example/youtube.com", "https://youtube.com.evil.example/",
                    "file:///etc/passwd", "https://user:pw@www.youtube.com/watch?v=1"):
            self.assertFalse(S._video_url_ok(url), url)
        with self.assertRaises(S.ApiError):
            S.import_video("http://127.0.0.1/video.mp4")


@mock.patch.dict(os.environ, _NO_PROXY_ENV, clear=True)
class RedirectSSRF(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = _serve(_Redirector)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_redirect_to_internal_host_is_blocked(self):
        # Pretend the first hop is public and the redirect target is internal: the redirect must be re-checked.
        with mock.patch.object(S, "_public_host", lambda u: "/secret" not in u), \
                mock.patch.object(S, "_ip_public", lambda a: True):
            with self.assertRaises(S.BlockedURL):
                S._open(self.base + "/start")
            with self.assertRaises(S.ApiError) as cm:
                S._fetch_page(self.base + "/start")
            self.assertEqual(cm.exception.status, 400)

    def test_redirect_to_file_scheme_is_blocked(self):
        with mock.patch.object(S, "_public_host", lambda u: True), mock.patch.object(S, "_ip_public", lambda a: True):
            with self.assertRaises((S.BlockedURL, urllib.error.URLError)):
                S._open(self.base + "/file")

    def test_dns_rebinding_guard_checks_connected_address(self):
        # The URL check passes (e.g. DNS answered with a public IP), but the address actually dialled is loopback.
        with mock.patch.object(S, "_public_host", lambda u: True):
            with self.assertRaises(S.BlockedURL):
                S._open(self.base + "/secret")

    def test_allow_private_for_admin_configured_services(self):
        with S._open(self.base + "/secret", allow_private=True) as r:
            self.assertEqual(r.read(), b"secret")

    def test_https_json_reports_blocked_target(self):
        with self.assertRaises(S.ApiError):
            S._https_json(self.base + "/secret")


class SizeLimits(unittest.TestCase):
    def test_read_capped(self):
        import io
        self.assertEqual(S._read_capped(io.BytesIO(b"x" * 10), 10), b"x" * 10)
        with self.assertRaises(ValueError):
            S._read_capped(io.BytesIO(b"x" * 11), 10)
        self.assertEqual(S._read_capped(io.BytesIO(b"x" * 50), 10, truncate=True), b"x" * 10)

    def test_gzip_and_deflate_decoding_is_capped(self):
        page = b"<html>" + b"a" * 1000 + b"</html>"
        self.assertEqual(S.decode_content(gzip.compress(page), "gzip", 10_000), page)
        self.assertEqual(S.decode_content(zlib.compress(page), "deflate", 10_000), page)
        raw = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        self.assertEqual(S.decode_content(raw.compress(page) + raw.flush(), "deflate", 10_000), page)
        bomb = gzip.compress(b"\0" * 5_000_000)
        self.assertEqual(len(S.decode_content(bomb, "gzip", 1000)), 1000)
        with self.assertRaises(S.ApiError):
            S.decode_content(b"junk", "br", 1000)

    def test_body_limits_per_route(self):
        self.assertEqual(S.body_limit("/api/import/text"), 1_000_000)
        self.assertEqual(S.body_limit("/api/settings"), 1_000_000)
        self.assertGreaterEqual(S.body_limit("/api/import/images"), 33_000_000)
        self.assertGreaterEqual(S.body_limit("/api/recipe/tacos/image/upload"), 11_000_000)


class Validation(unittest.TestCase):
    def test_recipe_image_paths_require_uuid(self):
        for bad in ("../evil", "..", "abc", "abc-def", RID + "/..", RID[:-1], "", "a" * 36):
            with self.assertRaises(ValueError):
                n_recipes.image_path(_TMP, bad)
        self.assertIsNone(n_recipes.image_path(_TMP, RID))

    def test_settings_are_type_checked(self):
        for k, v in (("stove", "rocket"), ("expiry_alert_hour", 99), ("expiry_alert_hour", "x"), ("meal_types", ["brunch"]),
                     ("prefer_expiring", "yes"), ("include_tags", "a"), ("ai_budget", float("nan")), ("temp_unit", "K")):
            with self.assertRaises(S.ApiError, msg=(k, v)):
                S.save_settings({k: v})
        out = S.save_settings({"stove": "gas", "expiry_alert_hour": 7, "meal_types": ["dinner", "lunch"]})
        self.assertEqual((out["stove"], out["expiry_alert_hour"]), ("gas", 7))

    def test_date_range_is_capped(self):
        with self.assertRaises(S.ApiError):
            S.date_range("1900-01-01", "9999-12-31")
        start, end = S.date_range("2026-01-10", "2026-01-01")
        self.assertEqual(start, end)

    def test_download_filenames_are_sanitised(self):
        self.assertEqual(S.safe_filename('a"b\r\nSet-Cookie: x.csv'), "a-b-Set-Cookie-x.csv")
        self.assertEqual(S.safe_filename("../../etc"), "etc")

    def test_upload_must_be_a_real_image(self):
        import base64
        svg = "data:image/svg+xml;base64," + base64.b64encode(b"<svg onload=alert(1)>").decode()
        with self.assertRaises(S.ApiError):
            S.decode_upload(svg)
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 20
        blob, ctype = S.decode_upload("data:image/jpeg;base64," + base64.b64encode(png).decode())
        self.assertEqual(ctype, "image/png")

    def test_session_expiry_and_rotation(self):
        good = S.make_session()
        self.assertTrue(S.valid_session(good))
        old_ts = str(int(time.time()) - (S.SESSION_DAYS + 1) * 86400)
        import hashlib
        import hmac
        sig = hmac.new(S.cfg("session_secret").encode(), old_ts.encode(), hashlib.sha256).hexdigest()
        self.assertFalse(S.valid_session(f"{old_ts}.{sig}"))
        self.assertFalse(S.valid_session("garbage"))
        S.rotate_sessions()
        self.assertFalse(S.valid_session(good))

    def test_client_ip_only_trusts_forwarded_for_behind_proxy(self):
        h = S.Handler.__new__(S.Handler)
        h.client_address = ("10.0.0.5", 1234)
        h.headers = http.client.HTTPMessage()
        h.headers["X-Forwarded-For"] = "6.6.6.6, 203.0.113.9"
        with mock.patch.object(S, "TRUST_PROXY", False):
            self.assertEqual(h.client_ip(), "10.0.0.5")
        with mock.patch.object(S, "TRUST_PROXY", True):
            self.assertEqual(h.client_ip(), "203.0.113.9")   # the hop the proxy added, not the client's claim


@mock.patch.dict(os.environ, _NO_PROXY_ENV, clear=True)
class PublicModeAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = mock.patch.object(S, "PUBLIC_MODE", True)
        cls.patch.start()
        S.set_cfg(app_password_hash="")
        cls.httpd = S.Server(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.patch.stop()
        S.set_cfg(app_password_hash="")

    def setUp(self):
        S._login_fails.clear()

    def req(self, method, path, body=None, cookie=None, headers=None, raw_length=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"X-TablePlan": "1"} if method != "GET" else {}
        if cookie:
            h["Cookie"] = cookie
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        if raw_length is not None:
            c.putrequest(method, path)
            for k, v in {**h, "Content-Length": str(raw_length)}.items():
                c.putheader(k, v)
            c.endheaders()
        else:
            c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = (r.status, dict(r.getheaders()), r.read())
        c.close()
        return out

    def login(self, pw):
        st, hdrs, _ = self.req("POST", "/api/login", {"password": pw})
        self.assertEqual(st, 200)
        return hdrs["Set-Cookie"].split(";")[0]

    def test_private_routes_require_sign_in(self):
        for path in (f"/img/{RID}", "/img/ing?name=egg", "/export/pantry.csv", "/export/plan.csv", "/print/pantry",
                     "/print/plan", "/export/list/abc.txt"):
            st, hdrs, _ = self.req("GET", path)
            self.assertEqual(st, 302, path)
            self.assertEqual(hdrs.get("Location"), "/")
        for path in ("/api/config", "/api/setup/status", "/api/settings", "/api/recipes", "/api/setup/ai"):
            self.assertEqual(self.req("GET", path)[0], 401, path)
        for path in ("/api/setup/password", "/api/setup/complete", "/api/setup/ai", "/api/import/url"):
            self.assertEqual(self.req("POST", path, {"password": "hijacked!", "url": "x"})[0], 401, path)
        self.assertEqual(self.req("GET", "/api/session")[0], 200)

    def test_setup_code_then_password_and_old_sessions_revoked(self):
        self.assertEqual(self.req("POST", "/api/login", {"password": "WRONGCODE"})[0], 401)
        code_cookie = self.login(S.SETUP_CODE.lower())
        self.assertEqual(self.req("GET", "/export/pantry.csv", cookie=code_cookie)[0], 200)
        self.assertEqual(self.req("POST", "/api/setup/password", {"password": "short"}, cookie=code_cookie)[0], 400)
        st, hdrs, _ = self.req("POST", "/api/setup/password", {"password": "correct horse"}, cookie=code_cookie)
        self.assertEqual(st, 200)
        new_cookie = hdrs["Set-Cookie"].split(";")[0]
        self.assertIn("HttpOnly", hdrs["Set-Cookie"])
        self.assertIn("SameSite=Strict", hdrs["Set-Cookie"])
        # the setup code no longer works, and the session it created was revoked
        self.assertEqual(self.req("POST", "/api/login", {"password": S.SETUP_CODE})[0], 401)
        self.assertEqual(self.req("GET", "/api/config", cookie=code_cookie)[0], 401)
        self.assertEqual(self.req("GET", "/api/config", cookie=new_cookie)[0], 200)
        # anonymous users can't change the password of a set-up instance
        self.assertEqual(self.req("POST", "/api/setup/password", {"password": "attacker-pw"})[0], 401)
        S._login_fails.clear()
        self.assertEqual(self.req("POST", "/api/login", {"password": "correct horse"})[0], 200)

    def test_csrf_header_cross_site_and_headers(self):
        cookie = self.login(S.SETUP_CODE) if not S.cfg("app_password_hash") else None
        if cookie is None:
            S._login_fails.clear()
            cookie = self.login("correct horse")
        st, _, _ = self.req("PUT", "/api/settings", {"stove": "gas"}, cookie=cookie, headers={"X-TablePlan": "0"})
        self.assertEqual(st, 403)
        st, _, _ = self.req("GET", "/api/config", cookie=cookie, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(st, 403)
        st, hdrs, _ = self.req("GET", "/api/config", cookie=cookie)
        self.assertEqual(st, 200)
        self.assertEqual(hdrs["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", hdrs["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", hdrs)
        self.assertNotIn("Strict-Transport-Security", hdrs)
        st, hdrs, _ = self.req("GET", "/api/config", cookie=cookie, headers={"X-Forwarded-Proto": "https"})
        self.assertIn("Strict-Transport-Security", hdrs)
        # non-UUID recipe image ids are refused
        self.assertEqual(self.req("GET", "/img/not-a-uuid", cookie=cookie)[0], 404)
        self.assertEqual(self.req("GET", f"/img/{RID}", cookie=cookie)[0], 404)
        # oversized bodies are refused before they're read
        st, _, _ = self.req("POST", "/api/import/text", cookie=cookie, raw_length=5_000_000)
        self.assertEqual(st, 413)
        st, _, _ = self.req("PUT", "/api/settings", {"expiry_alert_hour": "noon"}, cookie=cookie)
        self.assertEqual(st, 400)
        st, hdrs, body = self.req("GET", "/print/pantry", cookie=cookie)
        self.assertEqual(st, 200)
        self.assertNotIn("unsafe-inline' ;", hdrs["Content-Security-Policy"])
        self.assertIn("'nonce-", hdrs["Content-Security-Policy"])
        self.assertNotIn(b" onclick=\"", body)   # no inline event-handler attributes

    def test_chunked_bodies_refused(self):
        st, _, _ = self.req("POST", "/api/login", headers={"Transfer-Encoding": "chunked"}, body=None)
        self.assertEqual(st, 411)

    def test_login_throttle(self):
        for _ in range(S.LOGIN_FAILS_PER_IP):
            S.login_failed("127.0.0.1")
        self.assertEqual(self.req("POST", "/api/login", {"password": "x"})[0], 429)


if __name__ == "__main__":
    unittest.main()
