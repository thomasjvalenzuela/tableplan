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


class Arrange(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            c.execute("DELETE FROM meal_plans")
        S._recipe_cache["at"] = 0
        self.r = [new_recipe(f"Arr {i} {id(self)}", 2, ["1 cup rice"])[1] for i in range(4)]

    def test_validation(self):
        for bad in ({"recipe_ids": [], "start": day(0), "end": day(3)}, {"recipe_ids": "x", "start": day(0), "end": day(3)},
                    {"recipe_ids": self.r, "start": day(3), "end": day(0)}, {"recipe_ids": self.r, "start": "x", "end": day(1)},
                    {"recipe_ids": self.r, "start": day(0), "end": day(90)}):
            with self.assertRaises(S.ApiError) as cm:
                S.plan_arrange(bad)
            self.assertEqual(cm.exception.status, 400, bad)
        with self.assertRaises(S.ApiError) as cm:
            S.plan_arrange({"recipe_ids": ["nope"], "start": day(0), "end": day(1)})
        self.assertEqual(cm.exception.status, 404)

    def test_fallback_uses_only_empty_days_and_drops_extras(self):
        S.plan_assign({"date": day(1), "recipe_id": self.r[0]})
        with mock.patch.object(S, "cfg", side_effect=lambda k: "" if k == "openai_key" else S._cfg.get(k)):
            out = S.plan_arrange({"recipe_ids": self.r, "start": day(0), "end": day(3)})
        self.assertFalse(out["ai"])
        self.assertEqual((out["empty_days"], out["dropped"]), (3, 1))
        self.assertEqual([a["date"] for a in out["assignments"]], [day(0), day(2), day(3)])
        self.assertEqual(len({a["recipe_id"] for a in out["assignments"]}), 3)

    def test_ai_answer_is_filtered(self):
        reply = {"assignments": [{"date": day(1), "recipe_id": self.r[1]}, {"date": day(9), "recipe_id": self.r[0]},
                                 {"date": day(0), "recipe_id": "evil"}, {"date": day(0), "recipe_id": self.r[1]}]}
        with mock.patch.object(S, "cfg", side_effect=lambda k: "sk" if k == "openai_key" else S._cfg.get(k)), \
                mock.patch.object(S, "openai_chat", return_value=reply) as oc:
            out = S.plan_arrange({"recipe_ids": self.r[:2], "start": day(0), "end": day(1)})
        self.assertIn("variety", oc.call_args.args[0][0]["content"])
        self.assertTrue(out["ai"])
        self.assertEqual(out["assignments"], [{"date": day(0), "recipe_id": self.r[0]}, {"date": day(1), "recipe_id": self.r[1]}])
        with mock.patch.object(S, "cfg", side_effect=lambda k: "sk" if k == "openai_key" else S._cfg.get(k)), \
                mock.patch.object(S, "openai_chat", side_effect=S.ApiError(502, "down")):
            out = S.plan_arrange({"recipe_ids": self.r[:2], "start": day(0), "end": day(1)})
        self.assertFalse(out["ai"])
        self.assertEqual(len(out["assignments"]), 2)


class SeveralPerDay(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            c.execute("DELETE FROM meal_plans")
        S._recipe_cache["at"] = 0
        self.r = [new_recipe(f"Day {i} {id(self)}", 2, ["1 cup rice"])[1] for i in range(4)]

    def plan(self):
        return [(e["date"], e["entry_type"], e["recipe"]["id"]) for e in S.get_plans(S.today(), S.today() + timedelta(days=3))]

    def test_entries_add_up_and_swap_needs_replace_id(self):
        a = S.plan_assign({"date": day(1), "recipe_id": self.r[0]})["entry"]["id"]
        S.plan_assign({"date": day(1), "recipe_id": self.r[1]})                       # a second dinner
        S.plan_assign({"date": day(1), "recipe_id": self.r[2], "entry_type": "lunch"})
        S.plan_assign({"date": day(1), "recipe_id": self.r[3], "entry_type": "side"})
        S.plan_assign({"date": day(1), "recipe_id": self.r[3], "entry_type": "side"})  # same recipe, same slot: no-op
        self.assertEqual([t for _, t, _ in self.plan()], ["lunch", "dinner", "dinner", "side"])
        S.plan_assign({"date": day(1), "recipe_id": self.r[2], "replace_id": a})
        self.assertNotIn(self.r[0], [r for _, _, r in self.plan()])
        self.assertEqual(len(self.plan()), 4)
        with self.assertRaises(S.ApiError):
            S.plan_assign({"date": day(1), "recipe_id": self.r[0], "replace_id": 999999})

    def test_per_entry_move_and_swap(self):
        a = S.plan_assign({"date": day(1), "recipe_id": self.r[0]})["entry"]["id"]
        b = S.plan_assign({"date": day(1), "recipe_id": self.r[1], "entry_type": "lunch"})["entry"]["id"]
        c_ = S.plan_assign({"date": day(2), "recipe_id": self.r[2]})["entry"]["id"]
        self.assertEqual(S.plan_move({"id": b, "date": day(2)}), {"ok": True, "swapped_with": None})
        dates = {e["id"]: e["date"] for e in S.get_plans(S.today(), S.today() + timedelta(days=3))}
        self.assertEqual((dates[a], dates[b], dates[c_]), (day(1), day(2), day(2)))
        self.assertEqual(S.plan_move({"id": a, "date": day(2), "swap_with": c_})["swapped_with"], c_)
        dates = {e["id"]: e["date"] for e in S.get_plans(S.today(), S.today() + timedelta(days=3))}
        self.assertEqual((dates[a], dates[c_]), (day(2), day(1)))
        with self.assertRaises(S.ApiError):   # swapping needs a meal of the same type on that day
            S.plan_move({"id": a, "date": day(1), "swap_with": b})


class Allocation(unittest.TestCase):
    """Pantry stock is claimed meal by meal in date order; only the shortfall goes on the list."""

    def setUp(self):
        with S.db() as c:
            for t in ("meal_plans", "shopping_items", "pantry_items", "allocations"):
                c.execute(f"DELETE FROM {t}")
        S._recipe_cache["at"] = 0
        S.save_settings({"staples": S.DEFAULT_SETTINGS["staples"]})
        self.tue = new_recipe(f"Milanese {id(self)}", 2, ["1 tbsp salted butter", "chili flakes to taste"])[1]
        self.thu = new_recipe(f"Pad Thai {id(self)}", 2, ["2 tbsp salted butter", "chili flakes to taste", "1 tsp salt"])[1]

    def butter(self):
        return [i for i in S.ongoing_list()["items"] if "butter" in i["text"].lower() and not i["checked"]]

    def plan_both(self):
        a = S.plan_assign({"date": day(1), "recipe_id": self.tue})["entry"]["id"]
        b = S.plan_assign({"date": day(3), "recipe_id": self.thu})["entry"]["id"]
        return a, b

    def test_amounts_add_up_with_tags_and_text_amounts_once(self):
        self.plan_both()
        b = self.butter()
        self.assertEqual([i["text"] for i in b], ["3 tbsp salted butter"])
        self.assertEqual([u["qty_text"] for u in b[0]["uses"]], ["1 tbsp", "2 tbsp"])
        self.assertEqual([u["date"] for u in b[0]["uses"]], [day(1), day(3)])
        flakes = [i for i in S.ongoing_list()["items"] if "chili" in i["text"].lower()]
        self.assertEqual(len(flakes), 1)
        self.assertEqual(len(flakes[0]["uses"]), 2)
        self.assertFalse(any("salt" == (i["food"] or "").lower() for i in S.ongoing_list()["items"]))   # a staple

    def test_pantry_covers_earliest_meal_first_and_moves_shift_it(self):
        with S.db() as c:
            S.add_pantry_item(c, "salted butter", "fridge", None, "", None, 2, "tbsp")
        a, b = self.plan_both()
        items = self.butter()
        self.assertEqual([i["text"] for i in items], ["1 tbsp salted butter"])
        self.assertEqual([u["entry_id"] for u in items[0]["uses"]], [b])
        plan = {e["id"]: e for e in S.enrich_plan(S.get_plans(S.today(), S.today() + timedelta(days=4)))}
        self.assertEqual(plan[a]["missing"], 1)    # only the chili flakes
        S.plan_move({"id": b, "date": day(0)})     # Pad Thai now comes first and claims the butter
        items = self.butter()
        self.assertEqual([(i["text"], [u["entry_id"] for u in i["uses"]]) for i in items], [("1 tbsp salted butter", [a])])

    def test_cooking_spends_the_allocation_and_delete_frees_it(self):
        with S.db() as c:
            pid = S.add_pantry_item(c, "salted butter", "fridge", None, "", None, 2, "tbsp")
        a, b = self.plan_both()
        S.recipe_cooked(S.recipe_detail(self.tue)["slug"] if False else self._slug(self.tue), {"plan_id": a})
        with S.db() as c:
            self.assertAlmostEqual(S.pantry_row(c, pid)["qty"], 1.0)
        self.assertEqual([i["text"] for i in self.butter()], ["1 tbsp salted butter"])
        S.plan_delete(b)
        self.assertEqual(self.butter(), [])
        with S.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM allocations").fetchone()[0], 0)

    def _slug(self, rid):
        with S.db() as c:
            return S.n_recipes.get(c, rid)["slug"]

    def test_units_convert_when_merging(self):
        r3 = new_recipe(f"Cake {id(self)}", 2, ["1/4 cup salted butter"])[1]
        S.plan_assign({"date": day(1), "recipe_id": self.tue})
        S.plan_assign({"date": day(2), "recipe_id": r3})
        self.assertEqual([i["text"] for i in self.butter()], ["5 tbsp salted butter"])

    def test_unknown_amount_covers_every_meal_and_have_this(self):
        a, b = self.plan_both()
        item = self.butter()[0]
        with S.db() as c:
            S.n_lists.mark_have(c, [item["id"]])
            S._have_to_pantry(c, [item["id"]])
            S.sync_plan_list(c)
        self.assertEqual(self.butter(), [])
        r3 = new_recipe(f"Toast {id(self)}", 2, ["1 tbsp salted butter"])[1]
        S.plan_assign({"date": day(4), "recipe_id": r3})          # a later meal doesn't ask again
        self.assertEqual(self.butter(), [])

    def test_always_have(self):
        self.plan_both()
        S.list_add({"items": ["chili flakes"]})
        out = S.staples_add({"name": "chili flakes"})
        self.assertEqual(out["name"], "Chili flake")
        self.assertFalse(any("chili" in i["text"].lower() for i in S.ongoing_list()["items"]))
        with S.db() as c:
            S.sync_plan_list(c)
        self.assertFalse(any("chili" in i["text"].lower() for i in S.ongoing_list()["items"]))
        S.staples_remove({"name": out["name"], "restore": out["restore"]})
        with S.db() as c:
            S.sync_plan_list(c)
        self.assertTrue(any("chili" in i["text"].lower() for i in S.ongoing_list()["items"]))
        with self.assertRaises(S.ApiError):
            S.save_settings({"staples": ["x" * 41]})


class UseByDates(unittest.TestCase):
    """Never guess a sealed item's date: printed dates only, or a countdown once opened or frozen."""

    def add(self, name, loc="fridge", **kw):
        with S.db() as c:
            return S.add_pantry_item(c, name, loc, kw.get("pkg"), kw.get("text", ""), None, kw.get("qty"), kw.get("unit"))

    def row(self, pid):
        with S.db() as c:
            return S.pantry_json(c, S.pantry_row(c, pid))

    def act(self, pid, body):
        with S.db() as c:
            S.apply_pantry_action(c, pid, body)
            return S.pantry_json(c, S.pantry_row(c, pid))

    def test_sealed_items_get_no_date(self):
        r = self.row(self.add("Heavy cream"))
        self.assertEqual((r["expires_on"], r["expiry_source"], r["expiry_label"]), (None, "none", None))
        self.assertIn("after opening", r["keeps_hint"] or "")
        r = self.row(self.add("Heavy cream", pkg=day(9)))
        self.assertEqual((r["expires_on"], r["expiry_source"], r["expiry_label"][:6]), (day(9), "package", "Use by"))

    def test_fill_math_and_opened_countdown(self):
        pid = self.add("Heavy cream", qty=2, unit="cup")
        r = self.act(pid, {"action": "fill", "left": 0.5})
        self.assertEqual((r["amount_left"], r["qty"]), (0.5, 1.0))
        self.assertIsNotNone(r["opened_on"])
        self.assertEqual(r["expiry_source"], "opened")
        self.assertTrue(r["expiry_label"].startswith("Opened · use within"))
        r = self.act(pid, {"action": "fill", "left": 1})   # back to Full right after scanning: not open after all
        self.assertEqual((r["amount_left"], r["qty"], r["opened_on"], r["expires_on"]), (1.0, 2.0, None, None))
        # a sooner printed date wins over the countdown
        pid2 = self.add("Heavy cream", pkg=day(1))
        r = self.act(pid2, {"action": "fill", "left": 0.25})
        self.assertEqual((r["expires_on"], r["expiry_source"]), (day(1), "package"))
        # no rule, no date
        r = self.act(self.add("Mystery sauce"), {"action": "open"})
        self.assertEqual((r["expires_on"], r["expiry_source"]), (None, "none"))

    def test_freezing_starts_a_freezer_countdown(self):
        pid = self.add("Ground beef")
        r = self.act(pid, {"action": "move", "location": "freezer"})
        self.assertEqual(r["expiry_source"], "frozen")
        self.assertTrue(r["expiry_label"].startswith("Frozen"))
        r = self.act(pid, {"action": "set_date", "expires_on": day(5), "source": "package"})
        self.assertEqual(r["expiry_source"], "package")

    def test_migration_drops_estimates(self):
        a, b = self.add("Heavy cream"), self.add("Milk")
        with S.db() as c:
            c.execute("UPDATE pantry_items SET expires_on=?, expiry_source='estimate' WHERE id IN (?,?)", (day(7), a, b))
            c.execute("UPDATE pantry_items SET opened_on=? WHERE id=?", (day(-1), b))
            n = S.migrate_expiry_estimates(c)
        self.assertEqual((n["cleared"], n["opened"]), (1, 1))
        self.assertEqual((self.row(a)["expires_on"], self.row(a)["expiry_source"]), (None, "none"))
        self.assertEqual(self.row(b)["expiry_source"], "opened")


class PantryBulk(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            c.execute("DELETE FROM pantry_items")
            self.ids = [S.add_pantry_item(c, n, "fridge") for n in ("Milk", "Eggs", "Spinach")]

    def rows(self):
        with S.db() as c:
            return {r["id"]: dict(r) for r in c.execute("SELECT * FROM pantry_items")}

    def test_move_used_date(self):
        S.pantry_bulk({"ids": self.ids[:2], "action": "move", "location": "pantry"})
        S.pantry_bulk({"ids": [self.ids[2]], "action": "used"})
        S.pantry_bulk({"ids": self.ids[:2], "action": "set_date", "expires_on": day(4), "source": "package"})
        r = self.rows()
        self.assertEqual([r[i]["location"] for i in self.ids[:2]], ["pantry", "pantry"])
        self.assertEqual(r[self.ids[2]]["status"], "used")
        self.assertEqual({r[i]["expires_on"] for i in self.ids[:2]}, {day(4)})
        with self.assertRaises(S.ApiError):
            S.pantry_bulk({"ids": self.ids, "action": "move", "location": "garage"})
        with self.assertRaises(S.ApiError):
            S.pantry_bulk({"ids": [], "action": "used"})

    def test_soft_delete_undo_and_purge(self):
        S.pantry_bulk({"ids": self.ids[:2], "action": "delete"})
        with S.db() as c:
            self.assertEqual([i["name"] for i in S.list_pantry(c)], ["Spinach"])
        S.pantry_bulk({"ids": self.ids[:2], "action": "restore"})
        with S.db() as c:
            self.assertEqual(len(S.list_pantry(c)), 3)
        S.pantry_bulk({"ids": self.ids[:1], "action": "delete"})
        S.pantry_bulk({"ids": self.ids[:1], "action": "purge"})
        self.assertNotIn(self.ids[0], self.rows())


class DangerZone(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("meal_plans", "shopping_items", "pantry_items", "allocations", "diary", "trips", "purchases"):
                c.execute(f"DELETE FROM {t}")
        self.slug, self.rid = new_recipe(f"Reset Me {id(self)}", 2, ["1 cup rice", "2 eggs"])
        S.plan_assign({"date": day(1), "recipe_id": self.rid})
        S.list_add({"items": ["paper towels"]})
        with S.db() as c:
            S.add_pantry_item(c, "Eggs", "fridge", None, "", None, 12, "")
            S.sync_plan_list(c)
        S.recipe_cooked(self.slug, {})
        S.trip_record_scans({"pantry_item_ids": [self.pid()], "store_name": "Aldi"})

    def pid(self):
        with S.db() as c:
            return c.execute("SELECT id FROM pantry_items LIMIT 1").fetchone()[0]

    def count(self, table, where="1=1"):
        with S.db() as c:
            return c.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0]

    def test_confirm_required_and_backup_made(self):
        with self.assertRaises(S.ApiError) as cm:
            S.danger_reset("inventory", {"confirm": "inv"})
        self.assertEqual(cm.exception.status, 400)
        with self.assertRaises(S.ApiError):
            S.danger_reset("nope", {"confirm": "x"})
        out = S.danger_reset("inventory", {"confirm": " inventory "})
        self.assertTrue(os.path.isfile(out["backup_path"]))
        self.assertTrue(out["backup"].startswith("pre-reset-inventory-"))
        self.assertEqual((self.count("pantry_items"), self.count("allocations")), (0, 0))
        self.assertEqual(self.count("meal_plans"), 1)   # other sections untouched

    def test_each_section(self):
        S.danger_reset("plan", {"confirm": "Meal plan"})
        self.assertEqual((self.count("meal_plans"), self.count("allocations")), (0, 0))
        self.assertEqual([i["text"] for i in S.ongoing_list()["items"]], ["paper towels"])   # planned lines went with the plan
        S.danger_reset("list", {"confirm": "Shopping list"})
        self.assertEqual(self.count("shopping_items"), 0)
        S.danger_reset("trips", {"confirm": "Grocery trips"})
        self.assertEqual((self.count("trips"), self.count("purchases")), (0, 0))
        S.danger_reset("diary", {"confirm": "Cooking diary"})
        self.assertEqual(self.count("diary"), 0)
        S.danger_reset("demo", {"confirm": "Demo data"})
        self.assertGreater(self.count("recipes"), 0)
        S.danger_reset("recipes", {"confirm": "Recipes"})
        self.assertEqual(self.count("recipes"), 0)
        self.assertEqual(self.count("pantry_items"), 1)

    def test_everything(self):
        S.danger_reset("everything", {"confirm": "Everything"})
        for t in ("recipes", "meal_plans", "shopping_items", "pantry_items", "allocations", "diary", "trips", "purchases"):
            self.assertEqual(self.count(t), 0, t)
        self.assertGreater(self.count("stores"), 0)
        self.assertGreater(self.count("foods"), 0)
