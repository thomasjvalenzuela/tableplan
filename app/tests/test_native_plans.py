import sqlite3
import unittest
import urllib.parse
from datetime import date

from app.native import plans

RECIPES = {"r1": {"id": "r1", "name": "Tacos", "slug": "tacos", "has_image": True, "image_v": "abc"}}


def lookup(rid):
    return RECIPES.get(rid)


class FakeMealie:
    def __init__(self, items):
        self.items, self.calls = items, []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        return {"items": list(self.items)}


class PlansTest(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        self.c.row_factory = sqlite3.Row
        plans.init(self.c)
        plans.init(self.c)  # idempotent

    def tearDown(self):
        self.c.close()

    def test_add_and_get_shape_and_order(self):
        plans.add_entry(self.c, "2026-11-02", "dinner", "r1", scale=2)
        plans.add_entry(self.c, "2026-11-02", "snack", title="Popcorn")
        plans.add_entry(self.c, "2026-11-02", "side", title="Rice")
        plans.add_entry(self.c, "2026-11-02", "breakfast", title="Eggs")
        plans.add_entry(self.c, "2026-11-01", "lunch", "missing")
        plans.add_entry(self.c, "2026-11-09", "dinner", title="Out of range")
        got = plans.get_plans(self.c, "2026-11-01", "2026-11-08", lookup)
        self.assertEqual([(p["date"], p["entry_type"]) for p in got], [
            ("2026-11-01", "lunch"), ("2026-11-02", "breakfast"), ("2026-11-02", "dinner"),
            ("2026-11-02", "side"), ("2026-11-02", "snack")])
        self.assertIsNone(got[0]["recipe"])
        self.assertEqual(got[0]["recipeId"], "missing")
        d = got[2]
        self.assertEqual(set(d), {"id", "date", "entry_type", "title", "text", "scale", "recipe", "recipeId"})
        self.assertEqual(d["recipe"], RECIPES["r1"])
        self.assertEqual(d["scale"], 2.0)
        self.assertIsNone(got[1]["recipe"])

    def test_lookup_exception_yields_none(self):
        plans.add_entry(self.c, "2026-11-01", "dinner", "r1")
        got = plans.get_plans(self.c, "2026-11-01", "2026-11-01", lambda r: 1 / 0)
        self.assertIsNone(got[0]["recipe"])

    def test_validation(self):
        for args in (("2026-13-01", "dinner"), ("nope", "dinner"), ("2026-11-01", "brunch")):
            with self.assertRaises(ValueError):
                plans.add_entry(self.c, *args, title="x")
        with self.assertRaises(ValueError):
            plans.add_entry(self.c, "2026-11-01", "dinner")
        with self.assertRaises(ValueError):
            plans.add_entry(self.c, "2026-11-01", "dinner", title="x", scale=0)
        self.assertEqual(plans.add_entry(self.c, "2026-11-01", "Dinner", title="x"), 1)

    def test_update_and_delete(self):
        i = plans.add_entry(self.c, "2026-11-01", "dinner", title="x")
        self.assertTrue(plans.update_entry(self.c, i, date="2026-11-03", entry_type="lunch", scale=1.5))
        row = plans.get_plans(self.c, "2026-11-03", "2026-11-03", lookup)[0]
        self.assertEqual((row["entry_type"], row["scale"], row["title"]), ("lunch", 1.5, "x"))
        with self.assertRaises(ValueError):
            plans.update_entry(self.c, i, entry_type="brunch")
        with self.assertRaises(ValueError):
            plans.update_entry(self.c, i, created_at="x")
        self.assertFalse(plans.update_entry(self.c, 999, title="y"))
        self.assertTrue(plans.delete_entry(self.c, i))
        self.assertFalse(plans.delete_entry(self.c, i))

    def test_migrate_idempotent(self):
        fake = FakeMealie([
            {"id": 10, "date": "2026-11-01", "entryType": "dinner", "recipeId": "r1", "recipeScale": 3,
             "title": "", "text": "", "recipe": {"id": "r1"}},
            {"id": 11, "date": "2026-11-02", "entryType": "side", "recipeId": None,
             "title": "Salad", "text": "greens", "recipeScale": None},
            {"id": 12, "date": "2026-11-02", "entryType": "bogus", "title": "Bad"},
        ])
        counts = plans.migrate_from_mealie(self.c, fake, today=date(2026, 11, 8))
        self.assertEqual(counts, {"fetched": 3, "imported": 2, "skipped": 0, "errors": 1})
        method, path, _ = fake.calls[0]
        self.assertEqual(method, "GET")
        u = urllib.parse.urlparse(path)
        self.assertEqual(u.path, "/api/households/mealplans")
        self.assertEqual(urllib.parse.parse_qs(u.query),
                         {"start_date": ["2025-11-08"], "end_date": ["2027-11-08"], "perPage": ["-1"]})
        got = plans.get_plans(self.c, "2026-11-01", "2026-11-02", lookup)
        self.assertEqual(got[0]["recipe"]["name"], "Tacos")
        self.assertEqual(got[0]["scale"], 3.0)
        self.assertEqual((got[1]["title"], got[1]["text"], got[1]["scale"]), ("Salad", "greens", 1.0))
        again = plans.migrate_from_mealie(self.c, fake, today=date(2026, 11, 8))
        self.assertEqual(again, {"fetched": 3, "imported": 0, "skipped": 2, "errors": 1})
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM meal_plans").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
