"""Cooked: pantry deduction with unit conversion, undo, plan entries; pantry amounts; recipe delete cleanup."""

import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-cooked-")
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
    S.set_cfg(people=2, scale_to_household=True, setup_complete=True, app_password_hash="")


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


def day(n):
    return S.iso(S.today() + timedelta(days=n))


def new_recipe(name, servings, ingredients):
    slug = S.mealie("POST", "/api/recipes", {"name": name})
    S.recipe_update(slug, {"servings": servings, "ingredients": list(ingredients), "steps": ["Cook."]})
    S._recipe_cache["at"] = 0
    with S.db() as c:
        return slug, S.n_recipes.get(c, slug)["id"]


class Cooked(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("meal_plans", "shopping_items", "pantry_items", "pantry_events"):
                c.execute(f"DELETE FROM {t}")
        S._recipe_cache["at"] = 0
        self.slug, self.rid = new_recipe(f"Cream Eggs {id(self)}", 2,
                                         ["4 tbsp heavy cream", "2 eggs", "1 tsp salt", "1 tbsp olive oil", "1 cup spinach"])

    def add(self, name, text="", **kw):
        with S.db() as c:
            return S.add_pantry_item(c, name, "fridge", None, text, **kw)

    def row(self, pid):
        with S.db() as c:
            return dict(S.pantry_row(c, pid))

    def test_parse_amount(self):
        self.assertEqual(S.parse_amount("1 pint"), (1.0, "pint"))
        self.assertEqual(S.parse_amount("1 ½ cups"), (1.5, "cup"))
        self.assertEqual(S.parse_amount("2 avocados"), (2.0, ""))
        self.assertEqual(S.parse_amount("16 fl oz"), (16.0, "fl oz"))
        self.assertEqual(S.parse_amount("some"), (None, None))
        pid = self.add("Heavy cream", "1 pint")
        r = self.row(pid)
        self.assertEqual((r["qty"], r["unit"], r["original_qty"]), (1.0, "pint", 1.0))

    def test_deduct_with_cup_to_tbsp_conversion(self):
        cream = self.add("Heavy cream", qty=1, unit="cup")
        eggs = self.add("Eggs", qty=12, unit="")
        salt = self.add("Salt", qty=1, unit="lb")
        out = S.recipe_cooked(self.slug, {"servings": 4})   # doubled: 8 tbsp cream = 1/2 cup, 4 eggs
        r = self.row(cream)
        self.assertAlmostEqual(r["qty"], 0.5, places=3)
        self.assertAlmostEqual(r["amount_left"], 0.5, places=3)
        self.assertEqual((r["original_qty"], r["status"]), (1.0, "active"))
        self.assertIsNotNone(r["opened_on"])
        self.assertEqual(self.row(eggs)["qty"], 8)
        self.assertEqual(self.row(salt)["qty"], 1)   # staple: untouched
        names = {d["name"]: d for d in out["deducted"]}
        self.assertEqual(names["Heavy cream"]["used"], "8 tbsp heavy cream")
        self.assertEqual(names["Heavy cream"]["left_text"], "1/2 cup left")
        self.assertEqual(names["Eggs"]["left_text"], "8 left")
        self.assertNotIn("Salt", names)
        self.assertEqual(out["unknown"], [])
        # cooking again finishes the cream
        out = S.recipe_cooked(self.slug, {"servings": 4})
        self.assertEqual(out["finished"], ["Heavy cream"])
        self.assertEqual(self.row(cream)["status"], "used")

    def test_unknown_amount_opens_and_halves(self):
        spinach = self.add("Spinach")
        self.assertIsNone(self.row(spinach)["qty"])
        out = S.recipe_cooked(self.slug, {})
        r = self.row(spinach)
        self.assertEqual(out["unknown"], ["Spinach"])
        self.assertEqual(r["amount_left"], 0.5)
        self.assertIsNotNone(r["opened_on"])
        S.recipe_cooked(self.slug, {})
        self.assertEqual(self.row(spinach)["status"], "used")

    def test_soonest_expiring_match_and_mismatched_units(self):
        later = self.add("Heavy cream", qty=1, unit="cup")
        sooner = self.add("Heavy cream", qty=1, unit="cup")
        heavy = self.add("Eggs", qty=500, unit="g")   # count vs weight: falls back to "unknown"
        with S.db() as c:
            c.execute("UPDATE pantry_items SET expires_on=? WHERE id=?", (day(2), sooner))
            c.execute("UPDATE pantry_items SET expires_on=? WHERE id=?", (day(9), later))
        out = S.recipe_cooked(self.slug, {})
        self.assertEqual(self.row(later)["qty"], 1)
        self.assertAlmostEqual(self.row(sooner)["qty"], 0.75, places=3)
        self.assertEqual(out["unknown"], ["Eggs"])
        self.assertEqual(self.row(heavy)["amount_left"], 0.5)

    def test_undo_restores_pantry_and_plan(self):
        cream = self.add("Heavy cream", qty=1, unit="cup")
        spinach = self.add("Spinach")
        before = (self.row(cream), self.row(spinach))
        eid = S.plan_assign({"date": day(0), "recipe_id": self.rid})["entry"]["id"]
        detail = S.recipe_detail(self.slug)
        self.assertEqual(detail["cook_entry"], {"id": eid, "date": day(0), "today": True})
        out = S.recipe_cooked(self.slug, {"plan_id": eid})
        plan = S.get_plans(S.today(), S.today())
        self.assertTrue(plan[0]["cooked"])
        self.assertIsNone(S.recipe_detail(self.slug)["cook_entry"])
        self.assertNotEqual(self.row(cream)["qty"], 1)
        res = S.cooked_undo({"undo_token": out["undo_token"]})
        self.assertEqual(res["restored"], 2)
        for pid, b in zip((cream, spinach), before):
            r = self.row(pid)
            for k in S.COOK_SNAPSHOT:
                self.assertEqual(r[k], b[k], k)
        self.assertFalse(S.get_plans(S.today(), S.today())[0]["cooked"])
        with self.assertRaises(S.ApiError):
            S.cooked_undo({"undo_token": out["undo_token"]})
        with self.assertRaises(S.ApiError):
            S.cooked_undo({"undo_token": "x"})

    def test_plan_scale_default_and_skip(self):
        cream = self.add("Heavy cream", qty=1, unit="cup")
        # 2 people / 2 servings -> scale 1; entry scale 2 is used when no servings are given
        eid = S.plan_assign({"date": day(-1), "recipe_id": self.rid})["entry"]["id"]
        with S.db() as c:
            c.execute("UPDATE meal_plans SET scale=2 WHERE id=?", (eid,))
        S.recipe_cooked(self.slug, {"plan_id": eid})
        self.assertAlmostEqual(self.row(cream)["qty"], 0.5, places=3)
        e2 = S.plan_assign({"date": day(-2), "recipe_id": self.rid})["entry"]["id"]
        self.assertEqual(S.plan_skip(e2), {"ok": True})
        plan = {e["id"]: e for e in S.get_plans(S.today() - timedelta(days=2), S.today())}
        self.assertTrue(plan[e2]["skipped"])
        self.assertTrue(plan[eid]["cooked"])
        with self.assertRaises(S.ApiError):
            S.plan_skip(999999)
        for bad in ({"plan_id": "x"}, {"servings": "lots"}, {"servings": -1}, {"plan_id": 999999}):
            with self.assertRaises(S.ApiError):
                S.recipe_cooked(self.slug, bad)

    def test_bought_list_item_sets_amount_and_amount_edit(self):
        S.list_add({"items": ["2 cups heavy cream"]})
        it = S.ongoing_list()["items"][0]
        out = S.Handler.bought(None, S.ensure_list(), it["id"], "bought", {"to_pantry": True})
        p = out["pantry_item"]
        self.assertEqual((p["qty"], p["unit"], p["left_text"]), (2.0, "cup", "2 cups left"))
        with S.db() as c:
            S.apply_pantry_action(c, p["id"], {"action": "amount", "qty": "1", "unit": "cup"})
            r = S.pantry_json(c, S.pantry_row(c, p["id"]))
        self.assertEqual((r["qty"], r["left_text"], r["amount_left"]), (1.0, "1 cup left", 0.5))
        with S.db() as c:
            with self.assertRaises(S.ApiError):
                S.apply_pantry_action(c, p["id"], {"action": "amount", "qty": "1", "unit": "smidgen"})
            S.apply_pantry_action(c, p["id"], {"action": "amount", "qty": None})
            self.assertEqual(S.pantry_json(c, S.pantry_row(c, p["id"]))["left_text"], "50% left")

    def test_recipe_delete_cleans_plan_and_list(self):
        slug, rid = new_recipe(f"Doomed {id(self)}", 2, ["3 cloves garlic", "1 lb beef"])
        S.plan_assign({"date": day(1), "recipe_id": self.rid})
        S.plan_assign({"date": day(1), "recipe_id": rid, "entry_type": "lunch"})
        S.list_add({"items": ["1 lb beef"]})
        S.recipe_delete(slug)
        texts = sorted(i["text"] for i in S.ongoing_list()["items"])
        self.assertNotIn("3 cloves garlic", texts)
        self.assertIn("1 lb beef", texts)   # the typed line stays, minus the recipe's share
        self.assertEqual([e["recipe"]["id"] for e in S.get_plans(S.today(), S.today() + timedelta(days=2))], [self.rid])


if __name__ == "__main__":
    unittest.main()
