"""What can I make? Make right now / Almost there / Use it up, ranking, planned recipes left out, web suggestions."""

import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-make-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import whatcan as W  # noqa: E402

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


def recipe(name, ingredients, minutes=None):
    slug = S.mealie("POST", "/api/recipes", {"name": name})
    body = {"servings": 2, "ingredients": list(ingredients), "steps": ["Cook."]}
    if minutes:
        body["total_minutes"] = minutes
    S.recipe_update(slug, body)
    S._recipe_cache["at"] = 0
    with S.db() as c:
        return S.n_recipes.get(c, slug)["id"]


def stock(name, text="", expires=None, location="fridge"):
    with S.db() as c:
        pid = S.add_pantry_item(c, name, location, None, text)
        if expires is not None:
            c.execute("UPDATE pantry_items SET expires_on=? WHERE id=?", (day(expires), pid))
        return pid


def names(rows):
    return [r["name"] for r in rows]


class Ranking(unittest.TestCase):
    def test_order_expiring_then_rating_then_time(self):
        rows = [{"name": "Slow", "rating": 5, "minutes": 90, "missing": [], "expiring": [], "need_n": 3},
                {"name": "Quick", "rating": 5, "minutes": 15, "missing": [], "expiring": [], "need_n": 3},
                {"name": "Low", "rating": 2, "minutes": 5, "missing": [], "expiring": [], "need_n": 3},
                {"name": "Saves", "rating": 0, "minutes": None, "missing": [], "expiring": [{"name": "spinach"}], "need_n": 3},
                {"name": "Planned", "rating": 5, "minutes": 5, "missing": [], "expiring": [], "need_n": 3, "planned_soon": True},
                {"name": "Far", "rating": 5, "minutes": 5, "missing": [1, 2, 3, 4], "expiring": [], "need_n": 5}]
        b = W.buckets(rows)
        self.assertEqual(names(b["ready"]), ["Saves", "Quick", "Slow", "Low"])
        self.assertEqual(b["almost"], [])
        self.assertEqual(names(b["use_up"]), ["Saves"])

    def test_enough(self):
        conv = S.n_units.convert
        self.assertTrue(W.enough(1, "cup", [(None, "")], conv))
        self.assertTrue(W.enough(1, "cup", [(16, "tbsp")], conv))
        self.assertFalse(W.enough(2, "cup", [(16, "tbsp")], conv))
        self.assertTrue(W.enough(None, "", [(0.1, "cup")], conv))


class WhatCanIMake(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("meal_plans", "shopping_items", "pantry_items", "allocations", "recipes"):
                c.execute(f"DELETE FROM {t}")
        S._recipe_cache["at"] = 0

    def test_buckets_from_inventory(self):
        recipe("Spinach Eggs", ["2 eggs", "1 cup spinach", "1 tsp salt"], 10)
        recipe("Cheese Omelet", ["3 eggs", "1/2 cup cheddar cheese", "1 tbsp butter"], 15)
        recipe("Lasagna", ["1 lb ground beef", "9 lasagna noodles", "2 cups ricotta", "1 jar marinara", "2 cups mozzarella"], 90)
        stock("eggs", "12")
        stock("spinach", "", expires=2)
        stock("cheddar cheese", "8 oz")
        out = S.what_can_i_make()
        self.assertEqual(names(out["ready"]), ["Spinach Eggs"])   # salt is an "always have"
        self.assertEqual(names(out["almost"]), ["Cheese Omelet"])
        self.assertEqual([m["food"] for m in out["almost"][0]["missing"]], ["butter"])
        self.assertEqual(names(out["use_up"]), ["Spinach Eggs"])
        self.assertEqual(out["use_up"][0]["expiring"][0]["name"].lower(), "spinach")
        self.assertEqual(out["use_up"][0]["expiring"][0]["days_left"], 2)
        self.assertNotIn("Lasagna", names(out["ready"]) + names(out["almost"]))
        self.assertEqual([e["name"].lower() for e in out["expiring"]], ["spinach"])

    def test_short_amount_is_missing(self):
        recipe("Big Omelet", ["12 eggs", "1 cup milk"])
        stock("eggs", "6")
        stock("milk", "1 quart")
        out = S.what_can_i_make()
        self.assertEqual(names(out["almost"]), ["Big Omelet"])
        miss = out["almost"][0]["missing"][0]
        self.assertTrue(miss["short"])
        self.assertIn("egg", miss["food"])

    def test_planned_soon_and_expired_left_out(self):
        rid = recipe("Planned Eggs", ["2 eggs"])
        recipe("Old Milk Pudding", ["1 cup milk"])
        stock("eggs", "12")
        stock("milk", "1 quart", expires=-1)   # expired: doesn't count as having it
        S.plan_assign({"date": day(2), "recipe_id": rid})
        out = S.what_can_i_make()
        self.assertNotIn("Planned Eggs", names(out["ready"]))
        self.assertEqual(out["planned_skipped"], 1)
        self.assertEqual(names(out["almost"]), ["Old Milk Pudding"])

    def test_unknown_scans_dont_count(self):
        recipe("Toast", ["2 slices bread"])
        pid = stock("bread")
        with S.db() as c:
            c.execute("UPDATE pantry_items SET review=1 WHERE id=?", (pid,))
        self.assertEqual(S.what_can_i_make()["ready"], [])

    def test_does_not_create_foods(self):
        recipe("Odd", ["1 cup zzqx fruit"])
        with S.db() as c:
            before = c.execute("SELECT COUNT(*) FROM foods").fetchone()[0]
        S.what_can_i_make()
        with S.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM foods").fetchone()[0], before)


PAGE = """<html><head><script type="application/ld+json">{"@type":"Recipe","name":"Spinach Frittata",
"recipeIngredient":["6 eggs","2 cups spinach","1/2 cup feta"],"recipeInstructions":["Whisk.","Bake 20 minutes."],
"totalTime":"PT30M"}</script></head><body></body></html>"""


class WebSuggestions(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("pantry_items", "recipes"):
                c.execute(f"DELETE FROM {t}")
        S.set_cfg(openai_key="sk-test")
        stock("spinach", "", expires=1)
        stock("eggs", "12")

    def tearDown(self):
        S.set_cfg(openai_key="")

    def test_only_cited_working_recipe_pages(self):
        ai = {"output": [{"type": "message", "content": [{"type": "output_text",
              "text": '{"recipes":[{"title":"Frittata","url":"https://good.example/frittata?utm_source=x"},'
                      '{"title":"Made up","url":"https://invented.example/r"},'
                      '{"title":"Broken","url":"https://broken.example/r"},'
                      '{"title":"Not a recipe","url":"https://blog.example/top-10"}]}',
              "annotations": [{"type": "url_citation", "url": "https://www.good.example/frittata"},
                              {"type": "url_citation", "url": "https://broken.example/r"},
                              {"type": "url_citation", "url": "https://blog.example/top-10"}]}]}],
              "usage": {"input_tokens": 10, "output_tokens": 10}}

        def page(url):
            if "good.example" in url:
                return url, PAGE
            if "blog.example" in url:
                return url, "<html><body>Ten great ideas</body></html>"
            raise S.ApiError(502, "down")
        with mock.patch.object(S, "_https_json", return_value=ai) as h, mock.patch.object(S, "_fetch_page", side_effect=page):
            out = S.make_web_suggestions({})
        self.assertIn("web_search", str(h.call_args))
        self.assertEqual([x["title"] for x in out["suggestions"]], ["Spinach Frittata"])
        s = out["suggestions"][0]
        self.assertEqual(s["uses"], ["spinach"])
        self.assertEqual(s["missing"], ["1/2 cup feta"])
        self.assertEqual(out["foods"], ["spinach"])

    def test_needs_key(self):
        S.set_cfg(openai_key="")
        with self.assertRaises(S.ApiError):
            S.make_web_suggestions({})
