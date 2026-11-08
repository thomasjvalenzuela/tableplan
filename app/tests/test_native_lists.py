import re
import sqlite3
import unittest

from app.native import lists

UNITS = {"cup": ("cup", "cups"), "cups": ("cup", "cups"), "tbsp": ("tbsp", "tbsp"), "lb": ("lb", "lbs")}


def parse(text):
    m = re.match(r"^(\d+(?:\.\d+)?)\s+(?:(\w+)\s+)?([^,]+?)(?:,\s*(.*))?$", text.strip())
    if not m:
        return None
    unit = UNITS.get((m.group(2) or "").lower())
    food = m.group(3) if unit or not m.group(2) else f"{m.group(2)} {m.group(3)}"
    return {"quantity": float(m.group(1)), "unit": unit[0] if unit else "", "unit_plural": unit[1] if unit else "",
            "food": food.strip(), "note": m.group(4) or ""}


def categorize(s):
    return {"milk": "Dairy", "onion": "Produce", "flour": "Baking"}.get(s.lower())


def fake_mealie(store, calls=None):
    def mealie(method, path, body=None):
        if calls is not None:
            calls.append((method, path))
        assert method == "GET"
        if path.startswith("/api/households/shopping/lists?"):
            return {"items": [{"id": l["id"], "name": l["name"]} for l in store]}
        lid = path.rsplit("/", 1)[1]
        return next(l for l in store if l["id"] == lid)
    return mealie


class NativeListsTest(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA foreign_keys=ON")
        lists.init(self.c)
        lists.init(self.c)  # idempotent
        self.lid = lists.create_list(self.c, "Groceries")

    def items(self, lid=None):
        return lists.get_list(self.c, lid or self.lid)["listItems"]

    def test_list_crud(self):
        other = lists.create_list(self.c, "  Costco ")
        self.assertEqual([l["name"] for l in lists.list_lists(self.c)], ["Costco", "Groceries"])
        self.assertTrue(lists.rename_list(self.c, other, "Bulk"))
        self.assertRaises(ValueError, lists.rename_list, self.c, other, " ")
        lists.add_items(self.c, other, ["milk"])
        self.assertTrue(lists.delete_list(self.c, other))
        self.assertIsNone(lists.get_list(self.c, other))
        self.assertEqual(self.c.execute("SELECT count(*) FROM shopping_items").fetchone()[0], 0)
        self.assertFalse(lists.delete_list(self.c, other))
        self.assertRaises(KeyError, lists.add_items, self.c, "nope", ["x"])

    def test_add_items_shape_and_merge(self):
        lists.add_items(self.c, self.lid, ["2 cups milk", "1 onion, diced", "paper towels", "", "1 cup milk"],
                        parse, categorize)
        lists.add_items(self.c, self.lid, ["Paper Towels", "1 onion, diced"], parse, categorize)
        items = self.items()
        self.assertEqual(len(items), 3)
        milk, onion, towels = items
        self.assertEqual(set(milk), {"id", "display", "note", "quantity", "unit", "food", "label", "checked",
                                     "position", "recipeIds", "storeId", "checkedAt"})
        self.assertEqual((milk["quantity"], milk["unit"]["name"], milk["food"], milk["label"]),
                         (3.0, "cup", {"name": "milk"}, {"name": "Dairy"}))
        self.assertEqual(milk["display"], "3 cups milk")
        self.assertEqual((onion["quantity"], onion["unit"], onion["note"], onion["display"]),
                         (2.0, None, "diced", "2 onion, diced"))
        self.assertEqual((towels["food"], towels["display"], towels["label"]), (None, "paper towels", None))
        self.assertEqual([i["position"] for i in items], [0, 1, 2])

    def test_checked_items_are_not_merged(self):
        a = lists.add_items(self.c, self.lid, ["1 cup flour"], parse)[0]
        self.assertTrue(lists.set_checked(self.c, self.lid, a, True))
        b = lists.add_items(self.c, self.lid, ["1 cup flour"], parse)[0]
        self.assertNotEqual(a, b)
        self.assertEqual(lists.add_items(self.c, self.lid, ["2 cup flour"], parse), [b])
        # different unit -> separate item
        self.assertNotIn(b, lists.add_items(self.c, self.lid, ["1 lb flour"], parse))

    def test_recipe_ingredients_scale(self):
        lists.add_recipe_ingredients(self.c, self.lid, "r1", ["0.5 cup flour", "1 tbsp butter, softened", "salt"],
                                     3, parse, categorize)
        lists.add_recipe_ingredients(self.c, self.lid, "r2", ["1 cup flour"], 1, parse, categorize)
        flour, butter, salt = self.items()
        self.assertEqual((flour["quantity"], flour["display"], flour["recipeIds"]), (2.5, "2 1/2 cups flour", ["r1", "r2"]))
        self.assertEqual(butter["display"], "3 tbsp butter, softened")
        self.assertEqual((salt["display"], salt["recipeIds"]), ("salt", ["r1"]))

    def test_item_updates(self):
        a, b = lists.add_items(self.c, self.lid, ["1 cup milk", "eggs"], parse)
        self.assertTrue(lists.update_item(self.c, self.lid, a, quantity="2", note="whole", checked=True))
        it = self.items()[1]
        self.assertEqual((it["quantity"], it["note"], it["checked"]), (2.0, "whole", True))
        self.assertIsNotNone(self.c.execute("SELECT checked_at FROM shopping_items WHERE id=?", (a,)).fetchone()[0])
        self.assertRaises(ValueError, lists.update_item, self.c, self.lid, a, id="x")
        self.assertFalse(lists.update_item(self.c, self.lid, "missing", note="x"))
        self.assertFalse(lists.set_checked(self.c, "other-list", a, False))
        self.assertTrue(lists.delete_item(self.c, self.lid, b))
        self.assertFalse(lists.delete_item(self.c, self.lid, b))
        lists.add_items(self.c, self.lid, ["bread"])
        self.assertEqual(lists.clear_checked(self.c, self.lid), 1)
        self.assertEqual([i["display"] for i in self.items()], ["bread"])

    def test_migrate_from_mealie_idempotent(self):
        store = [{
            "id": "m-list-1", "name": "Weekly", "createdAt": "2026-01-01T00:00:00",
            "listItems": [
                {"id": "m-i1", "display": "2 cups milk", "note": "", "quantity": 2, "checked": False, "position": 0,
                 "unit": {"name": "cup", "pluralName": "cups"}, "food": {"name": "milk"}, "label": {"name": "Dairy"},
                 "recipeReferences": [{"recipeId": "rec-9"}]},
                {"id": "m-i2", "display": "", "note": "dish soap", "quantity": 1, "checked": True, "position": 1,
                 "unit": None, "food": None, "label": None, "updatedAt": "2026-01-02T00:00:00"},
            ]}, {"id": "m-list-2", "name": "Empty", "listItems": []}]
        calls = []
        res = lists.migrate_from_mealie(self.c, fake_mealie(store, calls))
        self.assertEqual(res, {"lists": 2, "items": 2, "lists_skipped": 0, "items_skipped": 0})
        self.assertIn(("GET", "/api/households/shopping/lists?perPage=-1"), calls)
        self.assertIn(("GET", "/api/households/shopping/lists/m-list-1"), calls)
        sl = lists.get_list(self.c, "m-list-1")
        milk, soap = sl["listItems"]
        self.assertEqual((sl["name"], milk["id"], milk["display"], milk["label"], milk["recipeIds"]),
                         ("Weekly", "m-i1", "2 cups milk", {"name": "Dairy"}, ["rec-9"]))
        self.assertEqual((soap["display"], soap["checked"], soap["food"]), ("dish soap", True, None))
        # native edits survive a re-run; nothing is duplicated
        lists.rename_list(self.c, "m-list-1", "Renamed")
        res = lists.migrate_from_mealie(self.c, fake_mealie(store))
        self.assertEqual(res, {"lists": 0, "items": 0, "lists_skipped": 2, "items_skipped": 2})
        self.assertEqual(lists.get_list(self.c, "m-list-1")["name"], "Renamed")
        self.assertEqual(self.c.execute("SELECT count(*) FROM shopping_items").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
