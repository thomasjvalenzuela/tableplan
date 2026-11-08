import sqlite3
import unittest

from app.native import meals


def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    meals.init(c)
    return c


LIB = [{"id": "m", "name": "Chicken Milanese"}, {"id": "s", "name": "Spicy Marinara Sauce"},
       {"id": "p", "name": "Spaghetti Cacio e Pepe"}, {"id": "t", "name": "Beef Tacos"}]
LOOK = {x["id"]: x for x in LIB}.get


class MealsTest(unittest.TestCase):
    def test_create_get_and_cleanup(self):
        c = conn()
        mid = meals.create(c, " Milanese  Night ", ["m", "s", "p"])
        m = meals.get(c, mid, LOOK)
        self.assertEqual(m["name"], "Milanese Night")
        self.assertEqual([r["id"] for r in m["recipes"]], ["m", "s", "p"])
        self.assertFalse(meals.add_recipe(c, mid, "m"))            # no duplicates
        self.assertEqual(meals.meals_for_recipe(c, "s")[0]["name"], "Milanese Night")
        for rid in ("m", "s", "p"):
            meals.forget_recipe(c, rid)
        self.assertIsNone(meals.get(c, mid, LOOK))                  # empty meal removed
        with self.assertRaises(ValueError):
            meals.create(c, "   ")

    def test_suggest_from_serve_with_text(self):
        c = conn()
        rec = {"id": "m", "name": "Chicken Milanese", "description": "",
               "recipeInstructions": [{"text": "Fry until golden."},
                                      {"text": "Serve with the spicy marinara and a side of cacio e pepe."}]}
        got = {s["id"]: s["reason"] for s in meals.suggest(c, rec, LIB)}
        self.assertIn("s", got)
        self.assertIn("p", got)
        self.assertNotIn("t", got)

    def test_suggest_hints_reverse_coplanned_dismiss_and_existing_meal(self):
        c = conn()
        meals.save_hints(c, "s", ["chicken milanese"])
        rec = {"id": "m", "name": "Chicken Milanese", "recipeInstructions": []}
        got = {s["id"] for s in meals.suggest(c, rec, LIB, co_planned={"t": 2})}
        self.assertEqual(got, {"s", "t"})
        meals.dismiss(c, "m", "t")
        self.assertEqual({s["id"] for s in meals.suggest(c, rec, LIB, co_planned={"t": 5})}, {"s"})
        meals.create(c, "Milanese Night", ["m", "s"])
        self.assertEqual(meals.suggest(c, rec, LIB), [])          # already together


if __name__ == "__main__":
    unittest.main()
