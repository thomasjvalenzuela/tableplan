"""Start-to-finish estimates: prep, preheat overlap, boiling water, overnight waits, recipe-stated totals, learned speed,
and the eat-at start time."""

import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-eta-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import eta as E  # noqa: E402

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
    S.set_cfg(people=2, setup_complete=True, openai_key="")


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


BAKE_INGS = ["2 cups flour", "1 cup sugar", "2 eggs", "1/2 cup butter, melted", "1 tsp vanilla", "3 apples, peeled and sliced",
             "1 tsp cinnamon", "1/2 tsp salt"]
BAKE_STEPS = ["Preheat the oven to 350°F.", "Mix the dry ingredients.", "Whisk in the eggs, butter and vanilla.",
              "Fold in the apples.", "Bake 40-45 minutes until golden.", "Cool 10 minutes."]


class Estimator(unittest.TestCase):
    def test_bake_preheat_overlaps_prep(self):
        e = E.estimate(BAKE_INGS, BAKE_STEPS, "conventional")
        prep = next(p for p in e["parts"] if p["k"] == "prep")["min"]
        pre = next(p for p in e["parts"] if p["k"] == "preheat")
        self.assertGreaterEqual(prep, 12)
        self.assertTrue(pre["overlaps"])
        self.assertEqual(pre["adds"], 0)                       # it heats while you prep
        self.assertEqual(e["passive"], 50)                     # 40 bake (low end) + 10 cool
        self.assertEqual(e["total"], prep + 4 + 50)            # 4 short hands-on steps
        self.assertFalse(e["approx"])
        # a short prep leaves some preheat on the clock; an air fryer barely needs any
        short = E.estimate(["1 bag fries"], ["Bake at 425°F for 20 minutes."], "conventional")
        self.assertEqual(next(p for p in short["parts"] if p["k"] == "preheat")["adds"], 7)
        fryer = E.estimate(["1 bag fries"], ["Bake at 425°F for 20 minutes."], "air_fryer")
        self.assertEqual(next(p for p in fryer["parts"] if p["k"] == "preheat")["adds"], 0)

    def test_pasta_boil_and_meanwhile(self):
        e = E.estimate(["1 lb spaghetti", "4 cloves garlic, minced", "1 cup cream"],
                       ["Bring a large pot of salted water to a boil.", "Cook the pasta 9 minutes.",
                        "Meanwhile, sauté the garlic until fragrant.", "Toss with the cream."])
        self.assertTrue(any(p["k"] == "boil" and p["min"] == 10 for p in e["parts"]))
        self.assertTrue(any(p["k"] == "overlap" for p in e["parts"]))
        self.assertTrue(e["approx"])                           # "until fragrant" has no stated time
        self.assertEqual(e["total"], 31)

    def test_overnight_is_shown_separately(self):
        e = E.estimate(["2 lb chicken thighs", "1 cup yogurt"], ["Marinate the chicken overnight.", "Grill 6 minutes per side."])
        self.assertEqual(e["long"], ["Overnight"])
        self.assertLess(e["total"], 30)
        self.assertIn("plus overnight", E.label(e))

    def test_recipe_stated_total_wins_when_close(self):
        ings, steps = ["1 onion, diced", "2 carrots, chopped"], ["Sauté until soft.", "Simmer 20 minutes."]
        mine = E.estimate(ings, steps)
        close = E.estimate(ings, steps, stated={"total": mine["total"] + 3})
        self.assertEqual((close["total"], close["based_on"]), (mine["total"] + 3, "recipe"))
        far = E.estimate(ings, steps, stated={"total": mine["total"] * 3})
        self.assertEqual(far["based_on"], "steps")
        self.assertEqual(far["stated"], {"total": mine["total"] * 3})

    def test_speed_factor_and_sessions(self):
        self.assertEqual(E.speed_factor([1.3]), 1.0)                        # needs 2+
        self.assertAlmostEqual(E.speed_factor([1.2, 1.4, 1.3]), 1.3)
        self.assertEqual(E.speed_factor([2.5, 2.8]), 1.6)                   # clamped
        self.assertEqual(E.speed_factor([0.4, 0.5]), 0.7)
        self.assertTrue(E.keep_session(50, 45))
        self.assertFalse(E.keep_session(200, 45))                           # left cook mode open
        self.assertFalse(E.keep_session(5, 45))                             # closed right away


class Learned(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            c.execute("DELETE FROM cook_times")
        S._speed["at"] = 0

    def recipe(self, name):
        slug = S.mealie("POST", "/api/recipes", {"name": name})
        S.recipe_update(slug, {"servings": 4, "ingredients": BAKE_INGS, "steps": BAKE_STEPS})
        S._recipe_cache["at"] = 0
        return slug

    def test_usual_time_and_household_speed(self):
        a, b = self.recipe(f"Apple Cake {id(self)}"), self.recipe(f"Pear Cake {id(self)}")
        da = S.recipe_detail(a)
        est = da["eta"]["total"]
        self.assertEqual(da["eta"]["shown"], est)
        self.assertTrue(S.record_cook_time(da["id"], est * 1.25, S.eta_base(S.n_recipes.get(S.db(), a))))
        self.assertTrue(S.record_cook_time(da["id"], est * 1.35, S.eta_base(S.n_recipes.get(S.db(), a))))
        self.assertFalse(S.record_cook_time(da["id"], est * 5, S.eta_base(S.n_recipes.get(S.db(), a))))
        da = S.recipe_detail(a)
        self.assertEqual(da["eta"]["basis"], "you")
        self.assertEqual(da["eta"]["shown"], round(est * 1.3))
        db_ = S.recipe_detail(b)                                            # never cooked: household speed applies
        self.assertEqual(db_["eta"]["shown"], round(db_["eta"]["total"] * 1.3))
        self.assertEqual(db_["eta"]["speed"], 1.3)

    def test_estimate_is_cached_without_counting_as_an_edit(self):
        slug = self.recipe(f"Cache Cake {id(self)}")
        with S.db() as c:
            before = S.n_recipes.get(c, slug)["dateUpdated"]
        S.recipe_detail(slug)
        with S.db() as c:
            r = S.n_recipes.get(c, slug)
        self.assertEqual(r["dateUpdated"], before)
        self.assertIn("eta", r["extras"])
        S.save_settings({"oven": "air_fryer"})
        try:
            self.assertEqual(S.eta_base(r)["stamp"][1], "air_fryer")       # oven change: recomputed
        finally:
            S.save_settings({"oven": "conventional"})


class EatAt(unittest.TestCase):
    def test_start_by_rounds_down_and_crosses_midnight(self):
        self.assertEqual(S.start_by("18:30", 50, date(2026, 11, 12)).strftime("%Y-%m-%d %H:%M"), "2026-11-12 17:40")
        self.assertEqual(S.start_by("18:30", 47, date(2026, 11, 12)).strftime("%H:%M"), "17:40")
        self.assertEqual(S.start_by("00:30", 60, date(2026, 11, 12)).strftime("%Y-%m-%d %H:%M"), "2026-11-11 23:30")
        self.assertIsNone(S.start_by("soon", 30, date(2026, 11, 12)))

    def test_plan_entries_get_eat_and_start_times(self):
        slug = S.mealie("POST", "/api/recipes", {"name": f"Weeknight Pasta {id(self)}"})
        S.recipe_update(slug, {"servings": 2, "ingredients": ["1 lb spaghetti"], "steps": ["Cook the pasta 10 minutes."]})
        S._recipe_cache["at"] = 0
        rid = S.recipe_detail(slug)["id"]
        day = S.today() + timedelta(days=1)
        S.save_plan([{"date": S.iso(day), "entry_type": "dinner", "recipe_id": rid}])
        e = next(x for x in S.enrich_plan(S.get_plans(day, day)) if (x.get("recipe") or {}).get("id") == rid)
        self.assertEqual(e["eat_at"], "18:30")
        mins = e["recipe"]["eta"]["shown"]
        self.assertEqual(e["start_by"], S.start_by("18:30", mins, day).strftime("%H:%M"))
        S.plan_eat_at(e["id"], {"eat_at": "19:15"})
        e = next(x for x in S.enrich_plan(S.get_plans(day, day)) if x["id"] == e["id"])
        self.assertEqual((e["eat_at"], e["eat_at_custom"]), ("19:15", True))
        with self.assertRaises(S.ApiError):
            S.plan_eat_at(e["id"], {"eat_at": "7pm"})
        with self.assertRaises(S.ApiError):
            S.save_settings({"eat_times": {"dinner": "25:00"}})


if __name__ == "__main__":
    unittest.main()
