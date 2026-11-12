"""Step-by-step cache: rebuilt after edits, kitchen settings applied locally, warm-up order; stated-time timers."""

import os
import shutil
import tempfile
import time
import unittest
from datetime import timedelta
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-guided-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import timers as T  # noqa: E402

_PATCHES = []


def setUpModule():
    for name, value in (("DATA_DIR", _TMP), ("DB_PATH", os.path.join(_TMP, "tableplan.db")),
                        ("IMG_DIR", os.path.join(_TMP, "images")), ("BACKUP_DIR", os.path.join(_TMP, "backups")),
                        ("NATIVE", True), ("PUBLIC_MODE", False), ("GUIDED_DEBOUNCE", 0.05)):
        p = mock.patch.object(S, name, value)
        p.start()
        _PATCHES.append(p)
    S.init_db()
    S.load_cfg()
    S.set_cfg(people=2, setup_complete=True, openai_key="sk-test")


def tearDownModule():
    S.set_cfg(openai_key="")
    time.sleep(0.3)   # let background step-by-step builds finish
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


def new_recipe(name, steps):
    slug = S.mealie("POST", "/api/recipes", {"name": name})
    S.recipe_update(slug, {"servings": 4, "ingredients": ["2 cups flour", "1 cup sugar"], "steps": steps})
    S._recipe_cache["at"] = 0
    return slug


AI_REPLY = {"tips": [], "steps": [
    {"title": "Bake", "text": "Bake at 350°F for 10–12 minutes until golden.", "ingredients": [{"index": 0, "portion": 1}, {"index": 1, "portion": 1}],
     "timer_minutes": 10, "timer_label": "Bake", "heat": None, "temperature": "350°F"},
    {"title": "Rest", "text": "Let it rest 7 minutes.", "ingredients": [], "timer_minutes": 7, "timer_label": "Rest", "heat": None, "temperature": None},
    {"title": "Cool", "text": "Cool on a rack.", "ingredients": [], "timer_minutes": 15, "timer_label": "Cool", "heat": None, "temperature": None},
]}


def wait_for(pred, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


class GuidedCache(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            c.execute("DELETE FROM guided_cache")
            c.execute("DELETE FROM meal_plans")
        S.save_settings({"stove": "gas", "oven": "conventional", "temp_unit": "F"})
        S._gw_failed.clear()

    def test_ai_timers_must_be_stated_and_ranges_start_low(self):
        slug = new_recipe(f"Cookies {id(self)}", ["Mix.", "Bake at 350°F for 10-12 minutes.", "Cool on a rack."])
        with mock.patch.object(S, "openai_chat", return_value=AI_REPLY) as ai:
            g = S.guided(slug, True)
        self.assertEqual(ai.call_count, 1)
        bake, rest, cool = g["steps"]
        self.assertEqual(bake["timer_sec"], 600)                         # low end of 10–12
        self.assertEqual(bake["timers"][0]["high_sec"], 720)
        self.assertIn("check at 10", bake["timer_label"])
        self.assertIsNone(rest["timer_sec"])                            # "7 minutes" isn't in the recipe
        self.assertIsNone(cool["timer_sec"])                            # AI timer without a stated time
        self.assertEqual(bake["temperature"], "350°F")

    def test_settings_change_needs_no_ai_call(self):
        slug = new_recipe(f"Bars {id(self)}", ["Bake at 350°F for 10-12 minutes."])
        with mock.patch.object(S, "openai_chat", return_value=AI_REPLY) as ai:
            S.guided(slug, True)
            S.save_settings({"temp_unit": "C", "oven": "convection", "stove": "induction"})
            g = S.guided(slug)
            self.assertEqual(ai.call_count, 1)
        self.assertTrue(g["cached"] and g["ai_available"])
        self.assertEqual(g["steps"][0]["temperature"], "160°C")          # 175°C, convection −15

    def test_cook_mode_never_waits_for_the_ai(self):
        slug = new_recipe(f"Muffins {id(self)}", ["Bake 20 minutes until golden."])
        gate = mock.Mock(side_effect=lambda *a, **k: (time.sleep(0.3), AI_REPLY)[1])
        with mock.patch.object(S, "openai_chat", gate):
            t0 = time.time()
            g = S.guided(slug)
            self.assertLess(time.time() - t0, 0.25)                     # instant built-in version
            self.assertEqual(g["source"], "auto")
            self.assertTrue(g["ai_pending"])
            self.assertEqual(g["steps"][0]["timer_sec"], 1200)
            self.assertEqual(g["steps"][0]["cue"], "until golden")
            self.assertTrue(wait_for(lambda: S.guided(slug).get("source") == "ai"))

    def test_reword_rebuilds_the_cache(self):
        slug = new_recipe(f"Bread {id(self)}", ["Bake at 350°F for 10-12 minutes."])
        with mock.patch.object(S, "openai_chat", return_value=AI_REPLY) as ai:
            S.guided(slug, True)
            with S.db() as c:
                rec = S.n_recipes.get(c, slug)
            reworded = dict(rec, recipeInstructions=[{"id": "x", "title": "", "text": "Bake at 350°F for 10-12 minutes, until browned.",
                                                      "ingredientReferences": []}])
            with mock.patch.object(S, "polish_recipe", return_value=reworded):
                out = S.recipe_polish(slug)
            self.assertTrue(wait_for(lambda: ai.call_count == 2))
            key = S._guided_key(S.recipe_detail(out["slug"]))
            with S.db() as c:
                self.assertTrue(wait_for(lambda: S._guided_cached(c, rec["id"], S.GUIDED_AI, key) is not None))

    def test_warm_up_starts_with_planned_recipes(self):
        planned = new_recipe(f"Planned {id(self)}", ["Simmer 20 minutes."])
        new_recipe(f"Newer {id(self)}", ["Simmer 30 minutes."])
        rid = S.recipe_detail(planned)["id"]
        S.save_plan([{"date": S.iso(S.today() + timedelta(days=2)), "entry_type": "dinner", "recipe_id": rid}])
        self.assertEqual(S.guided_warm_candidates()[0], planned)
        time.sleep(0.3)            # let the edit-triggered background builds (no AI here) finish and fail first
        S._gw_failed.clear()
        with mock.patch.object(S, "openai_chat", return_value=AI_REPLY):
            self.assertEqual(S.guided_warm_next(), planned)


class TimeParser(unittest.TestCase):
    def one(self, text):
        ts = T.parse(text)
        self.assertEqual(len(ts), 1, (text, ts))
        return ts[0]

    def test_stated_times(self):
        cases = {"Bake 10–12 minutes.": (600, 720), "Simmer 10 to 12 min.": (600, 720), "Roast 1 hour 15 minutes.": (4500, None),
                 "Braise 1½ hours.": (5400, None), "Bake for an hour.": (3600, None), "Rest half an hour.": (1800, None),
                 "Boil 30 seconds.": (30, None), "Bake 1 1/2 hours": (5400, None), "Simmer 1-2 hours": (3600, 7200),
                 "Cook an hour and a half.": (5400, None)}
        for text, (lo, hi) in cases.items():
            t = self.one(text)
            self.assertEqual((t["sec"], t["high_sec"]), (lo, hi), text)
        self.assertEqual(self.one("Bake 10–12 minutes.")["label"], "10–12 min · check at 10")

    def test_vague_overnight_and_per_side(self):
        self.assertEqual(T.parse("Cook a few minutes until soft."), [])
        self.assertEqual(T.cue("Cook a few minutes until soft."), "until soft")
        self.assertEqual(T.cue("Let rise until doubled."), "until doubled")
        o = self.one("Marinate overnight.")
        self.assertEqual((o["kind"], o["label"]), ("long", "Overnight"))
        self.assertEqual(self.one("Chill 8 hours.")["kind"], "long")
        self.assertEqual(self.one("Sear 3 minutes per side.")["kind"], "per_side")
        self.assertEqual(T.parse("Mix in 1 cup flour and 2 m of ribbon"), [])
        self.assertEqual(T.parse("Preheat oven to 400°F."), [])


if __name__ == "__main__":
    unittest.main()
