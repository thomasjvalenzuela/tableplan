"""Pan sizes: found in recipes and stored parsed, scaling advice, the cook's choice, Pans I have, quick-look question."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-pans-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import pans as P  # noqa: E402

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


class Detect(unittest.TestCase):
    def test_sizes(self):
        cases = {"Grease a 9x13-inch baking pan.": "9×13 in pan", "Pour into a 9 x 13 inch pan": "9×13 in pan",
                 "13 by 9 inch dish": "9×13 in pan", "an 8-inch square baking dish": "8×8 in square",
                 "two 9-inch round cake pans": "9 in round", "a 9x5 inch loaf pan": "9×5 in loaf",
                 "line a 12-cup muffin tin": "12-cup muffin tin", "a 10-inch cast iron skillet": "10 in skillet",
                 "a 5-quart Dutch oven": "5 qt Dutch oven", "a 9-inch springform pan": "9 in springform",
                 "9” pie plate": "9 in pie dish", "a half sheet pan": "13×18 in pan"}
        for text, want in cases.items():
            self.assertEqual((P.detect([text]) or {}).get("label"), want, text)
        self.assertIsNone(P.detect(["Bake in a greased pan 30 minutes."]))
        self.assertIsNone(P.detect(["a 10-inch pan"]))                # ambiguous: not guessed
        self.assertEqual(P.detect(["Stir.", "Spread in a 9x13 pan, then later an 8x8 pan."])["label"], "9×13 in pan")

    def test_needs_parse_clean(self):
        self.assertTrue(P.needs_pan(["Preheat oven to 350.", "Pour into the prepared baking pan."]))
        self.assertFalse(P.needs_pan(["Preheat oven to 350.", "Pour into a 9x13 baking pan."]))
        self.assertFalse(P.needs_pan(["Simmer the soup in a pot."]))
        self.assertEqual(P.parse("9x13")["label"], "9×13 in pan")
        self.assertEqual(P.parse("9 in round")["label"], "9 in round")
        self.assertEqual(P.parse("12-cup muffin tin")["cups"], 12)
        self.assertIsNone(P.parse("the big one"))
        self.assertIsNone(P.clean({"kind": "rect", "w": 99}))
        self.assertIsNone(P.clean({"kind": "laser"}))
        self.assertEqual(P.clean({"kind": "square", "w": 8})["label"], "8×8 in square")


class Advice(unittest.TestCase):
    def test_scaling(self):
        a = P.advice({"kind": "round", "d": 8}, 1.25)
        self.assertEqual(a["fits"][0]["label"], "9 in round")
        self.assertIn("1.25× deeper", a["time"])
        self.assertNotIn("pie", " ".join(f["label"] for f in a["fits"]))   # a cake isn't moved into a pie dish
        b = P.advice({"kind": "rect", "w": 13, "h": 9}, 2.0, owned=[{"kind": "rect", "w": 18, "h": 13, "label": "Half sheet"}])
        self.assertEqual(b["fits"][0]["label"], "Half sheet")
        self.assertIn("as deep", P.advice({"kind": "rect", "w": 13, "h": 9}, 0.5)["time"])
        m = P.advice({"kind": "muffin", "cups": 12}, 1.5)
        self.assertEqual(m["cups"], 18)
        self.assertIsNone(P.advice({"kind": "rect", "w": 13, "h": 9}, 1.0))
        self.assertEqual(P.advice({"kind": "loaf", "w": 9, "h": 5}, 2)["split"], "Or bake it in 2 pans, each a 9×5 in loaf, for the same time")


def recipe(name, ings, steps):
    slug = S.mealie("POST", "/api/recipes", {"name": name})
    S.recipe_update(slug, {"servings": 12, "ingredients": ings, "steps": steps})
    return slug


class Recipes(unittest.TestCase):
    def test_stored_parsed_and_choices(self):
        slug = recipe("Brownies", ["1 cup butter", "2 cups sugar"], ["Preheat oven to 350.", "Spread in a 9x13-inch baking pan.", "Bake 25 minutes."])
        with S.db() as c:
            rec = S.n_recipes.get(c, slug)
        self.assertEqual(rec["extras"]["pan_detected"]["label"], "9×13 in pan")   # stored when saved
        d = S.recipe_detail(slug)
        self.assertEqual((d["pan"]["pan"]["label"], d["pan"]["source"], d["pan"]["pref"]), ("9×13 in pan", "recipe", None))
        out = S.recipe_pan_api(slug, "GET", {"factor": "1.5"}, {})
        self.assertTrue(out["advice"]["fits"])
        S.recipe_pan_api(slug, "POST", {}, {"pref": "different", "pref_pan": {"kind": "rect", "w": 18, "h": 13}})
        out = S.recipe_pan_api(slug, "GET", {"factor": "2"}, {})
        self.assertEqual(out["pref"]["choice"], "different")
        self.assertEqual(out["advice_alt"]["label"], "13×18 in pan")
        S.recipe_pan_api(slug, "POST", {}, {"pan": "8x8"})
        self.assertEqual(S.recipe_detail(slug)["pan"]["source"], "set")
        with self.assertRaises(S.ApiError):
            S.recipe_pan_api(slug, "POST", {}, {"pan": "huge"})
        with self.assertRaises(S.ApiError):
            S.recipe_pan_api(slug, "POST", {}, {"pref": "different"})

    def test_owned_pans_setting(self):
        S.save_settings({"pans": [{"kind": "rect", "w": 13, "h": 9}, {"kind": "muffin", "cups": 12}]})
        self.assertEqual([p["label"] for p in S.owned_pans()], ["9×13 in pan", "12-cup muffin tin"])
        with self.assertRaises(S.ApiError):
            S.save_settings({"pans": [{"kind": "rect"}]})
        S.save_settings({"pans": []})

    def test_quick_look_asks_and_answer_sets_pan(self):
        draft = {"name": "Lemon Bars", "recipeIngredient": [{"note": "1 cup flour"}],
                 "recipeInstructions": [{"text": "Preheat oven to 350."}, {"text": "Press into the prepared baking pan and bake 20 minutes."}]}
        jid = S.import_job_create("scan", "waiting", pages=1)
        with mock.patch.object(S, "_job_pages_data", return_value=[]), \
                mock.patch.object(S, "ai_recipe", return_value=(draft, {"questions": [], "title_found": True, "suggested_title": ""})):
            S.import_job_process(jid)
        view = S.import_job_view(S._job_row(jid))
        self.assertEqual(view["status"], "review")
        self.assertEqual([q["text"] for q in view["questions"]], ["What size pan?"])
        S.import_job_answer(jid, {"answers": {"pan": "9×13 in"}})
        view = S.import_job_view(S._job_row(jid))
        self.assertEqual(view["status"], "done")
        with S.db() as c:
            rec = S.n_recipes.get(c, view["slug"])
        self.assertEqual(rec["extras"]["pan"]["label"], "9×13 in pan")
        self.assertEqual(S.recipe_detail(view["slug"])["pan"]["source"], "set")
