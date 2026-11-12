"""Recipe ideas from the kitchen (TheMealDB, Spoonacular) and the inventory export."""

import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-ideas-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import ideas as I  # noqa: E402

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
    S.save_settings({"polish_imports": False})


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


def stock(name, text="", expires=None, loc="fridge"):
    with S.db() as c:
        pid = S.add_pantry_item(c, name, loc, None, text)
        if expires is not None:
            c.execute("UPDATE pantry_items SET expires_on=? WHERE id=?", (S.iso(S.today() + timedelta(days=expires)), pid))
    return pid


MEAL = {"idMeal": "52772", "strMeal": "Teriyaki <b>Chicken</b> Casserole", "strCategory": "Chicken", "strArea": "Japanese",
        "strInstructions": "STEP 1\r\nPreheat oven to 350.\r\nSTEP 2\r\nBake 35 minutes.<script>x</script>",
        "strMealThumb": "https://www.themealdb.com/images/media/meals/x.jpg", "strSource": "javascript:alert(1)",
        **{f"strIngredient{i}": v for i, v in enumerate(["chicken breast", "rice", "soy sauce", ""], 1)},
        **{f"strMeasure{i}": v for i, v in enumerate(["2", "1 cup", "1/4 cup", ""], 1)}}


def clean_db():
    with S.db() as c:
        for t in ("pantry_items", "ext_cache", "idea_cache", "idea_dismissed", "recipes", "ai_usage", "prices", "purchases"):
            c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM settings WHERE key LIKE 'spoon_%'")
    S._ideas_rate.clear()


class Untrusted(unittest.TestCase):
    def test_mealdb_shape_is_sanitized(self):
        i = I.mealdb_idea(MEAL)
        self.assertEqual(i["title"], "Teriyaki Chicken Casserole")
        self.assertEqual(i["url"], "https://www.themealdb.com/meal/52772")      # javascript: link dropped
        self.assertEqual(i["ingredients"], ["2 chicken breast", "1 cup rice", "1/4 cup soy sauce"])
        self.assertEqual(i["steps"], ["Preheat oven to 350.", "Bake 35 minutes. x"])
        self.assertIsNone(I.mealdb_idea({"idMeal": "1; DROP"}))

    def test_spoon_shape(self):
        info = {"id": 7, "title": "Rice Bowl", "sourceUrl": "https://site.example/r", "readyInMinutes": 25, "servings": 2,
                "image": "https://img.spoonacular.com/r.jpg", "extendedIngredients": [{"original": "1 cup <i>rice</i>"}],
                "analyzedInstructions": [{"steps": [{"step": "Cook rice 18 minutes."}]}]}
        i = I.spoon_idea(info)
        self.assertEqual((i["title"], i["minutes"], i["ingredients"], i["steps"]), ("Rice Bowl", 25, ["1 cup rice"], ["Cook rice 18 minutes."]))


class MealDB(unittest.TestCase):
    def setUp(self):
        clean_db()

    def test_works_without_keys_caches_and_scores(self):
        stock("chicken breast", "1 lb", expires=1)
        stock("rice", "2 lb", loc="pantry")
        calls = []

        def fake(url, **kw):
            calls.append(url)
            if "wikibooks" in url:
                return {}
            self.assertIn("/api/json/v1/1/", url)               # the free test key
            self.assertLessEqual(kw["max_bytes"], 2_000_000)
            if "filter.php" in url:
                return {"meals": [{"idMeal": "52772"}]} if "chicken" in url else {"meals": None}
            return {"meals": [MEAL]}
        with mock.patch.object(S, "_https_json", side_effect=fake):
            out = S.recipe_ideas({})
            n = len(calls)
            S.recipe_ideas({})
        self.assertEqual(len(calls), n)                           # second time all from the 7-day cache
        idea = out["ideas"][0]
        self.assertEqual((idea["label"], idea["missing"]), ("Recipe · TheMealDB", ["1/4 cup soy sauce"]))
        self.assertEqual(idea["have_n"], 2)
        self.assertEqual(idea["expiring"][0]["name"].lower(), "chicken breast")
        self.assertTrue(idea["image"].startswith("/api/ideas/image/"))   # proxied, never hotlinked
        self.assertNotIn("spoonacular", " ".join(calls))

    def test_dismissed_for_30_days(self):
        stock("chicken breast", "1 lb")
        fake = lambda url, **kw: {"meals": [{"idMeal": "52772"}]} if "filter" in url else {"meals": [MEAL]}  # noqa: E731
        with mock.patch.object(S, "_https_json", side_effect=fake):
            iid = S.recipe_ideas({})["ideas"][0]["id"]
            S.idea_dismiss({"id": iid})
            self.assertEqual(S.recipe_ideas({})["ideas"], [])


class Spoonacular(unittest.TestCase):
    def setUp(self):
        clean_db()
        S.set_cfg(spoonacular_key="sk-spoon")

    def tearDown(self):
        S.set_cfg(spoonacular_key="")

    def test_quota_backoff_and_cache(self):
        stock("rice", "2 lb")
        err = S.ApiError(502, "quota")
        err.http_status = 402

        def fake(url, **kw):
            if "themealdb" in url:
                return {"meals": None}
            raise err
        with mock.patch.object(S, "_https_json", side_effect=fake) as h:
            self.assertEqual(S.recipe_ideas({})["ideas"], [])
            spoon = [c for c in h.call_args_list if "spoonacular" in c.args[0]]
            self.assertEqual(len(spoon), 1)
            self.assertNotIn("sk-spoon", json.dumps(S.recipe_ideas({})))     # key never leaves the server
            spoon = [c for c in h.call_args_list if "spoonacular" in c.args[0]]
            self.assertEqual(len(spoon), 1)                                   # backed off until tomorrow
        S.set_internal("spoon_backoff_until", 0)
        info = {"id": 7, "title": "Rice Bowl", "sourceUrl": "https://site.example/r", "extendedIngredients": [{"original": "1 cup rice"}],
                "analyzedInstructions": [{"steps": [{"step": "Cook."}]}]}

        def ok(url, **kw):
            if "themealdb" in url:
                return {"meals": None}
            return {"data": [{"id": 7}]} if "findByIngredients" in url else {"data": [info]}
        with mock.patch.object(S, "_https_json", side_effect=ok) as h:
            out = S.recipe_ideas({})
            S.recipe_ideas({})
        self.assertEqual(out["ideas"][0]["label"], "Recipe · Spoonacular")
        self.assertEqual(sum("spoonacular" in c.args[0] for c in h.call_args_list), 2)   # find + bulk once, then cached


class Export(unittest.TestCase):
    def setUp(self):
        clean_db()

    def test_csv_quoting_guard_filters_bom(self):
        a = stock('=HYPERLINK("http://x","milk")', "1 gallon")
        stock("eggs, large", "12", loc="fridge")
        stock("rice", "2 lb", loc="pantry")
        used = stock("old bread", "")
        with S.db() as c:
            c.execute("UPDATE pantry_items SET status='used' WHERE id=?", (used,))
        body = S.pantry_export_csv({})
        self.assertTrue(body.startswith("﻿"))
        rows = list(csv.DictReader(io.StringIO(body[1:])))
        self.assertEqual(list(rows[0].keys()), S.CSV_HEADERS)
        names = [r["Name"] for r in rows]
        self.assertIn("'=HYPERLINK(\"http://x\",\"milk\")", names)
        self.assertIn("eggs, large", names)                       # quoted, not split
        self.assertNotIn("old bread", names)
        self.assertIn('"eggs, large"', body)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(S.pantry_export_csv({"finished": "1"})[1:])))), 4)
        self.assertEqual([r["Name"] for r in csv.DictReader(io.StringIO(S.pantry_export_csv({"loc": "pantry"})[1:]))], ["rice"])
        self.assertEqual(len(list(csv.DictReader(io.StringIO(S.pantry_export_csv({"ids": f"{a}"})[1:])))), 1)
        self.assertEqual(S.csv_safe("-5"), "'-5")
        self.assertEqual(S.csv_safe("@sum"), "'@sum")
        self.assertEqual(S.csv_safe(3.5), 3.5)
