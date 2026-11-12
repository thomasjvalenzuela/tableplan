"""Item page (25): price paid vs best, history, recipes that use it, restock; checklist account tick."""
import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-item-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402

_P = []


def setUpModule():
    for k, v in (("DATA_DIR", _TMP), ("DB_PATH", os.path.join(_TMP, "t.db")), ("IMG_DIR", os.path.join(_TMP, "img")),
                 ("BACKUP_DIR", os.path.join(_TMP, "bk")), ("NATIVE", True), ("PUBLIC_MODE", False)):
        p = mock.patch.object(S, k, v); p.start(); _P.append(p)
    S.init_db(); S.load_cfg()
    S.save_settings({"polish_imports": False})


def tearDownModule():
    for p in reversed(_P):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


class ItemPage(unittest.TestCase):
    def test_page(self):
        with S.db() as c:
            eggs = S.add_pantry_item(c, "Eggs", "fridge", None, "12")
            fid = S.pantry_row(c, eggs)["food_id"]
            t = S.today()
            c.execute("INSERT INTO purchases(store_name,date,food_id,name,qty,unit,price,pantry_item_id) VALUES ('Costco',?,?,'Eggs',12,'each',4.29,?)",
                      (S.iso(t), fid, eggs))
            c.execute("INSERT INTO purchases(store_name,date,food_id,name,qty,unit,price) VALUES ('Aldi',?,?,'Eggs',12,'each',2.89)",
                      (S.iso(t - timedelta(days=20)), fid))
            S.remember_purchase(c, fid, product="Vital Farms", size="12 ct")
        S._save_new_recipe({"name": "Omelet", "recipeIngredient": [{"note": "3 eggs"}, {"note": "1 cup spinach"}],
                            "recipeInstructions": [{"text": "Cook."}]}, None, dup="keep")
        S._save_new_recipe({"name": "Toast", "recipeIngredient": [{"note": "2 slices bread"}],
                            "recipeInstructions": [{"text": "Toast."}]}, None, dup="keep")
        S._recipe_cache["at"] = 0
        d = S.pantry_page(eggs)
        self.assertEqual(d["item"]["name"], "Eggs")
        self.assertEqual((d["paid"]["price"], d["paid"]["store"]), (4.29, "Costco"))
        self.assertEqual((d["best"]["price"], d["best"]["store"]), (2.89, "Aldi"))
        self.assertTrue(d["best"]["cheaper"])
        self.assertEqual([h["store"] for h in d["history"]], ["Costco", "Aldi"])
        self.assertEqual([r["name"] for r in d["recipes"]], ["Omelet"])
        self.assertEqual(d["recipes"][0]["missing_n"], 1)
        self.assertEqual(d["restock"]["product"], "Vital Farms")
        with S.db() as c:
            S.apply_pantry_action(c, eggs, {"action": "toss"})
            self.assertEqual(S.pantry_row(c, eggs)["status"], "tossed")    # Spoiled = waste
        with self.assertRaises(S.ApiError):
            S.pantry_page(999999)

    def test_account_step_ticks_when_an_account_exists(self):
        self.assertNotIn("account", S.checklist_auto(None))
        with S.db() as c:
            S.n_users.create(c, "Sam", "", "password", "correct horse 99", False, admin=True)
        self.assertIn("account", S.checklist_auto(None))


if __name__ == "__main__":
    unittest.main()
