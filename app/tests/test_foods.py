"""Canonical foods: normalisation, resolution, merge with Undo, and the migration."""

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
