"""Canonical foods: normalisation, resolution, merge with Undo, and the migration."""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from app.native import foods as F

_TMP = tempfile.mkdtemp(prefix="tableplan-foods-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402

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
    S.set_cfg(setup_complete=True, app_password_hash="", openai_key="")


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


class Normalize(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        self.c.row_factory = sqlite3.Row
        F.init(self.c)
        F.seed(self.c)

    def test_table_salt_variants_are_one_food(self):
        ids = {F.resolve(self.c, t) for t in ("Morton iodized table salt 26 oz", "table salt", "Salt, table", "salt")}
        self.assertEqual(len(ids), 1)
        self.assertEqual(F.get(self.c, ids.pop())["name"], "Table salt")
        self.assertNotEqual(F.resolve(self.c, "sea salt"), F.resolve(self.c, "table salt"))
        self.assertEqual(F.resolve(self.c, "Sea Salt, Fine"), F.resolve(self.c, "sea salt"))
        self.assertNotEqual(F.resolve(self.c, "kosher salt"), F.resolve(self.c, "sea salt"))

    def test_modifiers_keep_foods_apart(self):
        pairs = [("unsalted butter", "salted butter"), ("whole milk", "2% milk"), ("whole milk", "skim milk"),
                 ("light brown sugar", "dark brown sugar"), ("extra-virgin olive oil", "olive oil"),
                 ("ground cinnamon", "cinnamon sticks"), ("chicken breast", "chicken thighs")]
        for a, b in pairs:
            self.assertNotEqual(F.resolve(self.c, a), F.resolve(self.c, b), (a, b))

    def test_plurals_order_brands_and_noise(self):
        self.assertEqual(F.resolve(self.c, "tomatoes"), F.resolve(self.c, "Tomato"))
        self.assertEqual(F.resolve(self.c, "Roma tomatoes (2 lb)"), F.resolve(self.c, "roma tomato"))
        self.assertEqual(F.resolve(self.c, "large eggs"), F.resolve(self.c, "Eggs"))
        self.assertEqual(F.resolve(self.c, "chicken breasts, boneless skinless"), F.resolve(self.c, "chicken breast"))
        self.assertEqual(F.resolve(self.c, "Kirkland Organic Extra-Virgin Olive Oil 2 L"), F.resolve(self.c, "EVOO"))
        self.assertEqual(F.normalize("oats"), "oats")
        self.assertEqual(F.normalize("collard greens"), "collard greens")
        self.assertEqual(F.normalize("whipping cream"), "heavy cream")

    def test_ai_classification_is_cached_and_checked(self):
        cream = F.resolve(self.c, "heavy cream")
        seen = []

        def classify(unknown, existing):
            seen.append(list(unknown))
            return [{"text": "double cream", "food_id": cream, "new_name": ""},
                    {"text": "gochujang paste", "food_id": None, "new_name": "Gochujang"},
                    {"text": "mystery", "food_id": 999999, "new_name": ""}]
        out = F.resolve_many(self.c, ["double cream", "gochujang paste", "mystery", "heavy cream"], classify)
        self.assertEqual(out["double cream"], cream)
        self.assertEqual(F.get(self.c, out["gochujang paste"])["name"], "Gochujang")
        self.assertNotEqual(out["mystery"], 999999)
        self.assertEqual(seen, [["double cream", "gochujang paste", "mystery"]])
        self.assertEqual(F.lookup(self.c, "double cream"), cream)   # cached as an alias


class ServerFoods(unittest.TestCase):
    def test_merge_repoints_and_undo(self):
        with S.db() as c:
            a, b = S._food_id(c, "scallions"), S._food_id(c, "green onion tops")
            pid = S.add_pantry_item(c, "green onion tops")
        S.list_add({"items": ["2 green onion tops"]})
        slug = S.mealie("POST", "/api/recipes", {"name": "Merge Test"})
        S.recipe_update(slug, {"ingredients": ["3 green onion tops", "1 cup rice"], "steps": ["x"]})
        res = S.foods_merge({"ids": [b], "into": a})
        self.assertEqual(res["merged"], 1)
        with S.db() as c:
            self.assertIsNone(S.n_foods.get(c, b))
            self.assertEqual(S.pantry_row(c, pid)["food_id"], a)
            self.assertEqual(S.n_recipes.get(c, slug)["recipeIngredient"][0]["food_id"], a)
            self.assertEqual(S.n_foods.lookup(c, "green onion tops"), a)
        self.assertTrue(any(i["text"] for i in S.ongoing_list()["items"]))
        foods = {f["id"]: f for f in S.foods_list("green")["foods"]}
        self.assertIn(a, foods)
        self.assertGreaterEqual(foods[a]["uses"]["recipes"], 1)
        S.foods_unmerge({"undo_token": res["undo_token"]})
        with S.db() as c:
            self.assertEqual(S.n_foods.get(c, b)["key"], "green onion top")
            self.assertEqual(S.pantry_row(c, pid)["food_id"], b)
            self.assertEqual(S.n_recipes.get(c, slug)["recipeIngredient"][0]["food_id"], b)
        with self.assertRaises(S.ApiError):
            S.foods_unmerge({"undo_token": res["undo_token"]})

    def test_rename_and_settings(self):
        with S.db() as c:
            fid = S._food_id(c, "gruyere")
        S.food_update(fid, {"name": "Gruyère cheese", "location": "fridge"})
        with S.db() as c:
            self.assertEqual(S.n_foods.lookup(c, "gruyere"), fid)   # the old name stays an alias
            self.assertEqual(S.n_foods.get(c, fid)["location"], "fridge")
        with self.assertRaises(S.ApiError):
            S.food_update(fid, {"location": "garage"})

    def test_list_merges_by_canonical_food(self):
        S.list_add({"items": ["1 tsp table salt", "2 tsp Morton salt"]})
        salt = [i for i in S.ongoing_list()["items"] if "salt" in i["text"].lower()]
        self.assertEqual(len(salt), 1)

    def test_migration_backfills(self):
        with S.db() as c:
            c.execute("UPDATE pantry_items SET food_id=NULL")
            c.execute("UPDATE shopping_items SET food_id=NULL")
            S.add_pantry_item(c, "Unsalted Butter")
            c.execute("UPDATE pantry_items SET food_id=NULL")
            counts = S.migrate_foods(c)
            self.assertGreaterEqual(counts["pantry_items"], 1)
            self.assertEqual(c.execute("SELECT count(*) FROM pantry_items WHERE food_id IS NULL").fetchone()[0], 0)
            self.assertIsNotNone(S.n_foods.lookup(c, "unsalted butter"))


if __name__ == "__main__":
    unittest.main()


OFF = {
    "0001234567890": {"status": 1, "product": {"product_name": "Morton Iodized Table Salt", "brands": "Morton",
                                               "quantity": "26 oz", "categories_tags": ["en:salts", "en:table-salts"]}},
    "0009999999999": {"status": 1, "product": {"product_name": "Cola", "brands": "Fizz", "quantity": "12 × 355 ml",
                                               "categories_tags": ["en:sodas"]}},
    "0005555555555": {"status": 0},
}


def fake_https(url, **kw):
    if "openfoodfacts" not in url:
        return {"status": 0, "items": []}
    code = url.split("/product/")[1].split(".json")[0]
    return OFF[code]


class Barcodes(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("pantry_items", "upc_cache", "upc_local", "shopping_items"):
                c.execute(f"DELETE FROM {t}")

    def test_parse_pack(self):
        cases = {"26 oz": (26, "oz", 1), "1 L": (1, "l", 1), "500 g": (500, "g", 1), "2 lb": (2, "lb", 1),
                 "1.5 kg": (1.5, "kg", 1), "750 ml": (750, "ml", 1), "16 fl oz": (16, "fl oz", 1),
                 "12 × 355 ml": (12, "", 12), "6 x 12 fl oz": (6, "", 6), "1 dozen": (12, "", 12), "18 ct": (18, "", 18)}
        for text, (q, u, n) in cases.items():
            p = S.parse_pack(text)
            self.assertEqual((p["qty"], p["unit"], p["count"]), (q, u, n), text)
        self.assertEqual(S.parse_pack("12 × 355 ml")["each_unit"], "ml")
        self.assertIsNone(S.parse_pack("big bag"))

    def test_scan_resolves_food_and_ticks_the_list(self):
        S.list_add({"items": ["1 tsp table salt"]})
        with mock.patch.object(S, "_https_json", side_effect=fake_https), mock.patch.object(S, "_pantry_image", return_value=None):
            out = S.scan_add({"code": "0001234567890", "location": "pantry"})
        it = out["item"]
        self.assertEqual((it["name"], it["qty"], it["unit"], it["product"]), ("Table salt", 26.0, "oz", "Morton · Morton Iodized Table Salt"))
        self.assertIsNotNone(out["list_checked"])
        self.assertTrue(all(i["checked"] for i in S.ongoing_list()["items"] if "salt" in i["text"].lower()))
        # +1 package adds 26 oz; -1 takes it back
        self.assertEqual(S.scan_more(it["id"], 1)["item"]["qty"], 52.0)
        self.assertEqual(S.scan_more(it["id"], -1)["item"]["qty"], 26.0)
        S.scan_undo({"pantry_item_id": it["id"]})
        self.assertFalse(any(i["checked"] for i in S.ongoing_list()["items"] if "salt" in i["text"].lower()))
        with S.db() as c:
            self.assertIsNone(S.pantry_row(c, it["id"]))

    def test_multipack_and_unknown_amount_increment(self):
        with mock.patch.object(S, "_https_json", side_effect=fake_https), mock.patch.object(S, "_pantry_image", return_value=None):
            out = S.scan_add({"code": "0009999999999"})
        self.assertEqual((out["item"]["qty"], out["pack"]["each_qty"]), (12.0, 355.0))
        with S.db() as c:
            pid = S.add_pantry_item(c, "Mystery jam")
            c.execute("UPDATE pantry_items SET upc='123456' WHERE id=?", (pid,))
        r = S.scan_more(pid, 1)
        self.assertIsNotNone(r["added_id"])
        S.scan_more(pid, -1)
        with S.db() as c:
            self.assertIsNone(S.pantry_row(c, r["added_id"]))

    def test_unknown_code_is_learned(self):
        with mock.patch.object(S, "_https_json", side_effect=fake_https) as h:
            self.assertEqual(S.scan_add({"code": "0005555555555"}), {"ok": False, "code": "0005555555555", "needs_name": True})
            out = S.scan_add({"code": "0005555555555", "name": "Sea salt", "quantity": "17.6 oz"})
            calls = h.call_count
            again = S.scan_add({"code": "0005555555555"})
            self.assertEqual(h.call_count, calls)   # answered from upc_local, no lookup
        self.assertEqual((out["item"]["name"], out["item"]["qty"], out["item"]["unit"]), ("Sea salt", 17.6, "oz"))
        self.assertEqual(again["item"]["name"], "Sea salt")
        with self.assertRaises(S.ApiError):
            S.scan_add({"code": "12"})


class LookupChain(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("pantry_items", "upc_cache", "upc_local", "shopping_items"):
                c.execute(f"DELETE FROM {t}")
        S._UPCITEMDB["until"] = 0

    def test_plu_codes(self):
        with mock.patch.object(S, "_https_json") as h:
            out = S.scan_add({"code": "94011", "location": "pantry"})
            h.assert_not_called()
        self.assertEqual(out["item"]["name"], "Banana")
        self.assertIn("Organic", out["item"]["product"])
        self.assertEqual(S.n_plu.lookup("4011")["organic"], False)
        self.assertIsNone(S.n_plu.lookup("1234"))
        with self.assertRaises(S.ApiError):
            S.scan_add({"code": "1234"})

    def test_store_brands_are_stripped(self):
        for raw, want in (("Kirkland Signature Organic Extra Virgin Olive Oil", "extra virgin olive oil"),
                          ("Great Value Whole Milk 1 gal", "whole milk"), ("Simply Nature Organic Spinach", "spinach"),
                          ("Trader Joe's Unsalted Butter", "unsalted butter"), ("Member's Mark Kosher Salt", "kosher salt"),
                          ("Good & Gather Large Eggs 12 ct", "egg"), ("Market Pantry Granulated Sugar", "granulated sugar")):
            self.assertEqual(F.normalize(raw), want, raw)

    def test_chain_order_cache_and_backoff(self):
        calls = []

        def fake(url, **kw):
            calls.append(url.split("/")[2])
            if "openfoodfacts" in url or "openproductsfacts" in url:
                return {"status": 0}
            return {"items": [{"title": "Great Value Iodized Salt 26 oz", "brand": "Great Value", "images": []}]}
        with mock.patch.object(S, "_https_json", side_effect=fake):
            p = S.upc_lookup("0007874200001")
            S.upc_lookup("0007874200001")
        self.assertEqual(calls, ["world.openfoodfacts.org", "world.openproductsfacts.org", "api.upcitemdb.com"])
        self.assertEqual((p["source"], p["food_name"], p["pack"]["qty"], p["pack"]["unit"]), ("UPCitemdb", "Table salt", 26.0, "oz"))

        def busy(url, **kw):
            if "upcitemdb" in url:
                raise S.ApiError(429, "HTTP 429")
            return {"status": 0}
        with mock.patch.object(S, "_https_json", side_effect=busy) as h:
            S.upc_lookup("0007874200002")
            n = h.call_count
            S.upc_lookup("0007874200003")   # UPCitemdb is resting: not called again
            self.assertEqual(h.call_count - n, 2)

    def test_snap_the_product(self):
        S.set_cfg(openai_key="sk-test")
        try:
            with mock.patch.object(S, "_https_json", return_value={"status": 0}), \
                    mock.patch.object(S, "openai_chat", return_value={"name": "Iodized table salt", "brand": "Morton", "size_text": "26 oz"}):
                out = S.scan_photo({"code": "0001112223334", "image": "data:image/jpeg;base64,AAAA"})
            self.assertEqual((out["item"]["name"], out["item"]["qty"], out["item"]["product"]), ("Table salt", 26.0, "Morton · Iodized table salt"))
            with S.db() as c:
                self.assertEqual(c.execute("SELECT name FROM upc_local WHERE code='0001112223334'").fetchone()[0], "Table salt")
        finally:
            S.set_cfg(openai_key="")


class GroceryTrip(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("pantry_items", "shopping_items", "purchases", "trips"):
                c.execute(f"DELETE FROM {t}")
        S.set_cfg(openai_key="sk-test")

    def tearDown(self):
        S.set_cfg(openai_key="")

    READ = {"store_name": "ALDI", "date": "2026-11-08", "total": 12.53, "items": [
        {"raw_text": "BANANAS 2.31 lb @ 0.59/lb", "name": "bananas", "quantity": None, "unit": "", "price": None, "is_food": True},
        {"raw_text": "GRND BF 80/20 1.0 LB 5.49", "name": "ground beef 80/20", "quantity": 1, "unit": "lb", "price": 5.49, "is_food": True},
        {"raw_text": "HVY WHP CRM 16OZ 3.29", "name": "heavy whipping cream", "quantity": 16, "unit": "fl oz", "price": 3.29, "is_food": True},
        {"raw_text": "PAPER TOWELS 2.39", "name": "paper towels", "quantity": None, "unit": "", "price": 2.39, "is_food": False},
        {"raw_text": "2 @ 0.89 LIMES", "name": "limes", "quantity": None, "unit": "", "price": None, "is_food": True}]}

    def test_receipt_rows_and_weighted_produce(self):
        S.list_add({"items": ["1 lb ground beef", "2 cups heavy cream"]})
        with mock.patch.object(S, "openai_chat", return_value=json_copy(self.READ)) as oc:
            out = S.receipt_read({"images": [{"data": "data:image/jpeg;base64,AAAA"}]})
        self.assertIn("GRND BF", oc.call_args.args[0][0]["content"][0]["text"])
        rows = {r["name"]: r for r in out["rows"]}
        self.assertEqual((out["store_name"], out["date"]), ("ALDI", "2026-11-08"))
        self.assertEqual((rows["Banana"]["quantity"], rows["Banana"]["unit"], rows["Banana"]["price"]), (2.31, "lb", 1.36))
        self.assertEqual((rows["Lime"]["quantity"], rows["Lime"]["price"]), (2.0, 1.78))
        self.assertEqual(rows["Ground beef"]["action"], "check_off")
        self.assertEqual(rows["Heavy cream"]["action"], "check_off")
        self.assertEqual(rows["Paper towel"]["action"], "ignore")
        self.assertEqual(rows["Banana"]["action"], "add")

    def test_apply_and_undo(self):
        S.list_add({"items": ["1 lb ground beef"]})
        with S.db() as c:
            cream = S.add_pantry_item(c, "Heavy cream", "fridge", None, "", None, 1, "cup")
        with mock.patch.object(S, "openai_chat", return_value=json_copy(self.READ)):
            out = S.receipt_read({"images": [{"data": "data:image/jpeg;base64,AAAA"}]})
        rows = out["rows"]
        for r in rows:
            r["list_item_id"] = (r.get("list_item") or {}).get("id")
            if r["name"] == "Heavy cream":
                r["action"], r["pantry_item_id"] = "increase", cream
        res = S.trip_apply({"store_name": "Aldi", "date": out["date"], "rows": rows, "method": "receipt",
                            "files": [{"data": "data:image/png;base64," + __import__("base64").b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 40).decode()}]})
        self.assertEqual((res["items"], res["checked"]), (4, 1))
        self.assertEqual(res["total"], 14.31)
        self.assertIn("Aldi · 4 items · $14.31 · 1 checked off your list", res["summary"])
        with S.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM purchases WHERE trip_id=?", (res["trip_id"],)).fetchone()[0], 5)
            self.assertAlmostEqual(S.pantry_row(c, cream)["qty"], 3.0, places=2)   # 1 cup + 16 fl oz
            files = json.loads(c.execute("SELECT files FROM trips WHERE id=?", (res["trip_id"],)).fetchone()[0])
        self.assertEqual(files, ["receipt-1.png"])
        self.assertTrue(all(i["checked"] for i in S.ongoing_list()["items"] if "beef" in i["text"]))
        S.trip_undo(res["trip_id"])
        with S.db() as c:
            self.assertEqual(S.pantry_row(c, cream)["qty"], 1)
            self.assertEqual(c.execute("SELECT count(*) FROM pantry_items").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT count(*) FROM purchases").fetchone()[0], 0)
        self.assertFalse(any(i["checked"] for i in S.ongoing_list()["items"]))
        with self.assertRaises(S.ApiError):
            S.trip_undo(res["trip_id"])

    def test_scanner_trip_is_recorded(self):
        with S.db() as c:
            a = S.add_pantry_item(c, "Milk")
        out = S.trip_record_scans({"pantry_item_ids": [a], "store_name": "Costco"})
        self.assertEqual(out["summary"], "Costco · 1 item")


def json_copy(d):
    return json.loads(json.dumps(d))
