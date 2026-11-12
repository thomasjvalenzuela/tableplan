"""Common groceries: autocomplete ranking, usual items, quantity prefixes, and generic list lines filled by a
specific scanned product (without cross-matching variants)."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-grocery-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import catalog as C  # noqa: E402

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
    S.set_cfg(people=2, setup_complete=True)


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


def clear():
    with S.db() as c:
        for t in ("shopping_items", "pantry_items", "food_pref"):
            c.execute(f"DELETE FROM {t}")
    S._prefs["at"] = 0


def open_lines():
    return {i["name"]: i for i in S.ongoing_list()["items"] if not i["checked"]}


class Catalog(unittest.TestCase):
    def test_seed_is_generic_and_complete(self):
        items = C.items()
        self.assertGreaterEqual(len(items), 300)
        for it in items:
            self.assertTrue(it["name"] and it["food"] and it["aisle"] and it["size"], it)
        self.assertEqual(C.find("whole milk")["size"], "1 gal")

    def test_fuzzy_and_alias_matches(self):
        names = [x["name"] for x in C.search("milk", 8)]
        for n in ("Whole milk", "2% milk", "Skim milk"):
            self.assertIn(n, names)
        self.assertEqual(C.search("yogrt", 1)[0]["name"], "Greek yogurt")   # typo
        self.assertEqual(C.search("salt", 1)[0]["name"], "Table salt")       # whole words before "salted"

    def test_variants_never_relate(self):
        self.assertTrue(C.related("milk", "whole milk"))
        self.assertFalse(C.related("2% milk", "whole milk"))
        self.assertFalse(C.related("table salt", "sea salt"))


class Adding(unittest.TestCase):
    def setUp(self):
        clear()

    def test_history_ranks_first_then_catalog(self):
        for _ in range(3):
            S.list_add({"items": ["Oat milk"]})
            with S.db() as c:
                c.execute("UPDATE shopping_items SET checked=1")
        out = S.grocery_suggest("milk")["items"]
        self.assertEqual(out[0]["name"], "Oat milk")
        self.assertEqual(out[0]["source"], "history")
        self.assertIn("Whole milk", [x["name"] for x in out])
        self.assertEqual(S.grocery_suggest("2 whole milk")["items"][0]["name"], "Whole milk")   # prefix ignored

    def test_quantity_prefix_and_aisle(self):
        S.list_add({"items": ["2 whole milk"]})
        it = open_lines()
        line = next(v for k, v in it.items() if "milk" in k.lower())
        self.assertIn("2", line["qty"] + line["text"])
        self.assertEqual(line["aisle"], "Dairy & Eggs")
        self.assertTrue(line["manual"])

    def test_usual_items_fall_back_to_popular(self):
        u = S.grocery_usual()
        self.assertEqual(len(u["items"]), 12)
        self.assertNotIn("Table salt", u["items"])                         # "always have" staples are skipped


def product(food, name="Whole Milk", brand="Kemps", qty="1 gal"):
    with S.db() as c:
        fid = S._food_id(c, food)
    return {"found": True, "food_id": fid, "name": name, "brand": brand, "quantity": qty, "pack": {}}


class GenericToSpecific(unittest.TestCase):
    def setUp(self):
        clear()

    def scan(self, food, code="0041383090400", **kw):
        with mock.patch.object(S, "upc_lookup", return_value=product(food, **kw)):
            return S.scan_add({"code": code, "store_id": None})

    def test_generic_line_filled_by_specific_product_and_learned(self):
        S.list_add({"items": ["Whole milk"]})
        r = self.scan("whole milk")
        self.assertIsNotNone(r["list_checked"])
        self.assertIsNone(r["list_ask"])
        done = [i for i in S.ongoing_list()["items"] if i["checked"]][0]
        self.assertIn("Whole milk → Kemps", done["bought"])
        self.assertEqual(r["item"]["product"].split(" · ")[0], "Kemps")      # inventory has the specific product
        S.list_add({"items": ["Whole milk"]})
        self.assertIn("Last time: Kemps", open_lines()["Whole milk"]["last"])

    def test_variants_dont_cross_match(self):
        S.list_add({"items": ["2% milk"]})
        r = self.scan("whole milk")
        self.assertIsNone(r["list_checked"])
        self.assertIsNone(r["list_ask"])
        self.assertIn("2% milk", open_lines())
        S.list_add({"items": ["Table salt"]}) if False else None

    def test_ambiguous_asks_then_fulfils(self):
        S.list_add({"items": ["Milk"]})
        r = self.scan("whole milk")
        self.assertIsNone(r["list_checked"])                               # a generic "Milk" line: ask, don't guess
        self.assertEqual([c["text"] for c in r["list_ask"]["candidates"]], ["Milk"])
        res = S.list_fulfill({"item_id": r["list_ask"]["candidates"][0]["id"], "pantry_item_id": r["item"]["id"]})
        self.assertTrue(res["list_checked"])
        self.assertNotIn("Milk", open_lines())

    def test_store_suggested_next_time(self):
        with S.db() as c:
            sid = S.n_lists.list_stores(c)[0]["id"]
        S.list_add({"items": ["Whole milk"]})
        with mock.patch.object(S, "upc_lookup", return_value=product("whole milk")):
            S.scan_add({"code": "0041383090400", "store_id": sid})
        S.list_add({"items": ["Whole milk"]})
        self.assertEqual(open_lines()["Whole milk"]["store_id"], sid)


if __name__ == "__main__":
    unittest.main()
