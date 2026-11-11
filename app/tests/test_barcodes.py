"""Barcodes: UPC-E/EAN normalization, check digits, unknown → placeholder → details → learned, vision fields."""

import base64
import os
import shutil
import tempfile
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-bc-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import barcodes as B  # noqa: E402

_PATCHES = []
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()


def setUpModule():
    for name, value in (("DATA_DIR", _TMP), ("DB_PATH", os.path.join(_TMP, "tableplan.db")),
                        ("IMG_DIR", os.path.join(_TMP, "images")), ("BACKUP_DIR", os.path.join(_TMP, "backups")),
                        ("NATIVE", True), ("PUBLIC_MODE", False)):
        p = mock.patch.object(S, name, value)
        p.start()
        _PATCHES.append(p)
    S.init_db()
    S.load_cfg()
    S.set_cfg(people=2, setup_complete=True, openai_key="sk-test")


def tearDownModule():
    S.set_cfg(openai_key="")
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


class Normalize(unittest.TestCase):
    def test_upc_e_expands(self):
        self.assertEqual(B.upce_to_upca("04252614"), "042100005264")
        self.assertEqual(B.upce_to_upca("01234565"), "012345000065")
        self.assertEqual(B.normalize("425261")["code"], "0042100005264")

    def test_upc_a_and_ean_spellings(self):
        n = B.normalize("041383090400")
        self.assertEqual((n["code"], n["try"]), ("0041383090400", ["0041383090400", "041383090400"]))
        self.assertEqual(B.normalize("0041383090400")["code"], "0041383090400")
        self.assertEqual(B.normalize("5012345678900")["try"], ["5012345678900"])

    def test_check_digit_rejects_misreads(self):
        for bad in ("041383090401", "5012345678901", "04138309040"):
            self.assertTrue(B.normalize(bad)["misread"], bad)
        self.assertTrue(B.normalize("4011")["plu"])


class Unknowns(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("pantry_items", "upc_local", "upc_cache", "scan_log"):
                c.execute(f"DELETE FROM {t}")

    def test_not_found_becomes_a_placeholder_then_details_teach_the_code(self):
        nothing = lambda code: {"code": code, "found": False}   # noqa: E731
        nothing.label = "Test DB"
        with mock.patch.object(S, "UPC_SOURCES", [nothing]):
            r = S.scan_add({"code": "041383090400", "location": "fridge"})
        self.assertTrue(r["ok"] and r["unknown"])
        it = r["item"]
        self.assertEqual(it["name"], "Unknown item · 0041383090400")
        self.assertTrue(it["review"])
        self.assertEqual((it["location"], it["amount_left"], it["expires_on"]), ("fridge", 1, None))
        with S.db() as c:
            log = c.execute("SELECT results FROM scan_log").fetchall()
        self.assertIn("Test DB", log[-1]["results"])                     # every provider's answer is logged
        done = S.pantry_details(it["id"], {"name": "Plain Greek yogurt", "brand": "Fage", "size": "32 oz", "food": "greek yogurt", "image": PNG})
        self.assertFalse(done["review"])
        self.assertEqual(done["upc"], "0041383090400")
        self.assertTrue(done["image"])
        # the next scan of that code is instant and needs no lookup at all
        boom = mock.Mock(side_effect=AssertionError("should not look up"))
        with mock.patch.object(S, "UPC_SOURCES", [boom]):
            again = S.scan_add({"code": "0041383090400"})
        self.assertTrue(again["ok"])
        self.assertFalse(again.get("unknown"))
        self.assertIn("Fage", again["item"]["product"])

    def test_misread_and_offline(self):
        r = S.scan_add({"code": "041383090401"})
        self.assertTrue(r["misread"])
        def down(code):
            raise S.ApiError(503, "Service unavailable")
        down.label = "Down"
        with mock.patch.object(S, "UPC_SOURCES", [down]):
            r = S.scan_add({"code": "5012345678900"})
        self.assertTrue(r["unknown"])                                    # offline: still added, to review later

    def test_negative_cache_expires_and_retry(self):
        calls = []
        def nothing(code):
            calls.append(code)
            return {"code": code, "found": False}
        nothing.label = "T"
        with mock.patch.object(S, "UPC_SOURCES", [nothing]):
            S.upc_lookup("5012345678900")
            S.upc_lookup("5012345678900")
            self.assertEqual(len(calls), 1)                              # cached "not found"
            with S.db() as c:
                c.execute("UPDATE upc_cache SET at=?", (S.iso(S.today() - S.timedelta(days=8)),))
            S.upc_lookup("5012345678900")
            self.assertEqual(len(calls), 2)                              # a week later it asks again
        found = lambda code: {"code": code, "found": True, "name": "Whole milk", "brand": "Kemps", "quantity": "1 gal",  # noqa: E731
                              "categories": [], "source": "T", "pack": {}, "image_url": ""}
        found.label = "T"
        with mock.patch.object(S, "UPC_SOURCES", [nothing]):
            r = S.scan_add({"code": "5012345678900"})
        with mock.patch.object(S, "UPC_SOURCES", [found]):
            out = S.pantry_relookup(r["item"]["id"])
        self.assertTrue(out["found"])
        self.assertFalse(out["item"]["review"])

    def test_one_provider_down_is_still_an_answer_but_not_remembered(self):
        def fake(url, **kw):
            if "upcitemdb" in url:
                raise S.ApiError(503, "HTTP 503")
            return {"status": 0}
        S._UPCITEMDB["until"] = 0
        with mock.patch.object(S, "_https_json", side_effect=fake):
            p = S.upc_lookup("0852390000449")
        self.assertFalse(p["found"])
        with S.db() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM upc_cache WHERE code='0852390000449'").fetchone())
            log = c.execute("SELECT results FROM scan_log ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertIn("error 503", log)
        S._UPCITEMDB["until"] = 0

    def test_repeat_unknowns_count_up_then_learn_and_merge(self):
        code = "0852390000111"
        with mock.patch.object(S, "_https_json", return_value={"status": 0, "items": []}):
            a = S.scan_add({"code": code, "location": "pantry"})
            b = S.scan_add({"code": code, "location": "pantry"})
            f = S.scan_add({"code": code, "location": "fridge"})
        self.assertEqual(a["item"]["id"], b["item"]["id"])
        self.assertTrue(b["again"])
        self.assertEqual(b["item"]["qty"], 2)
        self.assertNotEqual(f["item"]["id"], a["item"]["id"])
        out = S.pantry_details(a["item"]["id"], {"name": "Oat milk", "size": "64 oz"})
        self.assertEqual((out["qty"], out["unit"], out["review"]), (128, "oz", False))
        self.assertEqual([x["id"] for x in out["same_code"]], [f["item"]["id"]])
        self.assertEqual((out["same_code"][0]["name"], out["same_code"][0]["qty"], out["same_code"][0]["review"]), ("Oat milk", 64, False))
        merged = S.pantry_merge(a["item"]["id"], {"ids": [f["item"]["id"]]})
        self.assertEqual(merged["qty"], 192)
        with S.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM pantry_items WHERE upc=? AND status='active'", (code,)).fetchone()[0], 1)

    def test_identify_keeps_only_confident_fields(self):
        reply = {"name": "Greek yogurt", "brand": "Fage", "size_text": "32 oz", "category": "Dairy & Eggs", "food": "greek yogurt",
                 "confident": {"name": True, "brand": False, "size_text": True, "category": True, "food": True}}
        with mock.patch.object(S, "openai_chat", return_value=reply):
            out = S.scan_identify({"images": [PNG]})
        self.assertEqual(out["brand"], "")                               # not sure: left for the cook
        self.assertEqual((out["name"], out["size_text"]), ("Greek yogurt", "32 oz"))


if __name__ == "__main__":
    unittest.main()
