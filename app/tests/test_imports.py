"""Duplicate detection and the scan import queue: thresholds, Keep both / Replace / Cancel, suggested names, questions."""

import base64
import os
import shutil
import tempfile
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-imports-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import dupes as D  # noqa: E402

_PATCHES = []
JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 200).decode()


def setUpModule():
    for name, value in (("DATA_DIR", _TMP), ("DB_PATH", os.path.join(_TMP, "tableplan.db")),
                        ("IMG_DIR", os.path.join(_TMP, "images")), ("BACKUP_DIR", os.path.join(_TMP, "backups")),
                        ("NATIVE", True), ("PUBLIC_MODE", False), ("GUIDED_DEBOUNCE", 30)):
        p = mock.patch.object(S, name, value)
        p.start()
        _PATCHES.append(p)
    S.init_db()
    S.load_cfg()
    S.set_cfg(people=2, setup_complete=True, openai_key="sk-test")
    S.save_settings({"polish_imports": False})


def tearDownModule():
    S.set_cfg(openai_key="")
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


class Matching(unittest.TestCase):
    def test_titles(self):
        self.assertEqual(D.title_similarity("The Best Lemon Bars", "lemon bars"), 1.0)
        self.assertGreaterEqual(D.title_similarity("Lemon Bars", "Easy Lemon Bar"), D.TITLE_SAME)
        self.assertLess(D.title_similarity("Lemon Bars", "Chocolate Chip Cookies"), D.TITLE_LOOSE)

    def test_thresholds(self):
        bars = {"name": "Lemon Bars", "ingredients": ["1 cup butter, softened", "2 cups flour", "4 eggs", "1/2 cup lemon juice", "2 cups sugar"]}
        same = {"name": "Classic Lemon Bars", "ingredients": ["1 c. butter", "2 cups all-purpose flour", "4 large eggs", "lemon juice", "sugar"]}
        renamed = {"name": "Lemon Squares", "ingredients": bars["ingredients"]}
        other = {"name": "Lemon Chicken", "ingredients": ["2 lb chicken", "1 lemon", "garlic"]}
        cookies = {"name": "Sugar Cookies", "ingredients": ["1 cup butter", "2 cups flour", "1 egg", "1 cup sugar", "vanilla"]}
        self.assertEqual(D.match(bars, same)[1], ["same name"])
        self.assertTrue(D.match(bars, renamed)[0])            # same ingredients, loosely similar name
        self.assertEqual(D.match(bars, other), (0.0, []))
        self.assertEqual(D.match(bars, cookies), (0.0, []))   # shared basics aren't enough
        url = {"name": "x", "ingredients": [], "url": "https://www.example.com/lemon-bars/"}
        self.assertEqual(D.match(url, {"name": "y", "ingredients": [], "url": "http://example.com/lemon-bars"})[1], ["same source"])

    def test_keep_both_name(self):
        self.assertEqual(D.keep_both_name("Lemon Bars", ["lemon bars"]), "Lemon Bars (2)")
        self.assertEqual(D.keep_both_name("Lemon Bars", ["Lemon Bars", "Lemon Bars (2)"]), "Lemon Bars (3)")
        self.assertEqual(D.keep_both_name("Lemon Bars", ["Lemon Squares"]), "Lemon Bars")


def recipe_data(name, ings, steps=("Mix.", "Bake 30 minutes.")):
    return {"name": name, "recipeIngredient": [{"note": x, "display": x, "originalText": x} for x in ings],
            "recipeInstructions": [{"id": str(i), "title": "", "text": t, "ingredientReferences": []} for i, t in enumerate(steps)]}


class Resolutions(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("recipes", "import_jobs", "meal_plans", "favorites", "diary"):
                c.execute(f"DELETE FROM {t}")
        S._recipe_cache["at"] = 0
        self.slug = S._save_new_recipe(recipe_data("Lemon Bars", ["1 cup butter", "2 cups flour", "4 eggs", "lemon juice"]), dup="skip")
        with S.db() as c:
            self.rid = S.n_recipes.get(c, self.slug)["id"]

    def test_direct_import_pauses_then_keep_both(self):
        with self.assertRaises(S.DuplicateFound) as cm:
            S._save_new_recipe(recipe_data("Lemon bars", ["1 cup butter", "2 cups flour", "4 eggs", "juice of 2 lemons"]))
        e = cm.exception
        self.assertEqual(e.status, 409)
        self.assertEqual(e.extra["matches"][0]["slug"], self.slug)
        job = S.import_job_answer(e.extra["job"], {"duplicate": "keep"})
        self.assertEqual((job["status"], job["name"]), ("done", "Lemon Bars (2)"))
        with S.db() as c:
            names = sorted(r["name"] for r in c.execute("SELECT name FROM recipes"))
        self.assertEqual(names, ["Lemon Bars", "Lemon Bars (2)"])

    def test_replace_keeps_slug_plans_favorites_and_old_text(self):
        with S.db() as c:
            S.n_plans.add_entry(c, S.iso(S.today()), "dinner", self.rid)
            S.n_recipes.set_favorite(c, self.rid, True)
        with self.assertRaises(S.DuplicateFound) as cm:
            S._save_new_recipe(recipe_data("Lemon Bars", ["1 cup butter", "2 cups flour", "4 eggs", "1/2 cup lemon juice", "powdered sugar"],
                                           ["Make the crust.", "Bake 20 minutes.", "Add filling and bake 25 minutes."]))
        job = S.import_job_answer(cm.exception.extra["job"], {"duplicate": "replace"})
        self.assertEqual((job["status"], job["slug"]), ("done", self.slug))
        with S.db() as c:
            rec = S.n_recipes.get(c, self.slug)
            self.assertEqual(rec["id"], self.rid)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM recipes").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM meal_plans WHERE recipe_id=?", (self.rid,)).fetchone()[0], 1)
            self.assertIn(self.rid, S.n_recipes.favorite_ids(c))
        self.assertEqual(len(rec["recipeInstructions"]), 3)
        self.assertEqual(rec["extras"]["versions"][-1]["steps"], ["Mix.", "Bake 30 minutes."])   # reversible

    def test_cancel(self):
        with self.assertRaises(S.DuplicateFound) as cm:
            S._save_new_recipe(recipe_data("Lemon Bars", ["butter", "flour", "eggs", "lemon juice"]))
        self.assertEqual(S.import_job_answer(cm.exception.extra["job"], {"duplicate": "cancel"})["status"], "cancelled")
        with S.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM recipes").fetchone()[0], 1)

    def test_different_recipe_saves_straight_away(self):
        slug = S._save_new_recipe(recipe_data("Beef Chili", ["1 lb beef", "1 can beans", "chili powder"]))
        self.assertTrue(slug)


def ai_reply(name="", suggested="", questions=(), ings=None):
    return {"found": True, "complete": True, "missing": "", "source_url": "", "name": name, "description": "",
            "servings": 4, "prep_minutes": 0, "cook_minutes": 0, "total_minutes": 0,
            "ingredients": [{"section": "", "quantity_text": q, "name": n, "note": ""} for q, n in (ings or [("1 lb", "chicken thighs"), ("", "butter"), ("4 cloves", "garlic")])],
            "steps": ["Melt the [?] in a pan.", "Sear the chicken 6 minutes per side."], "tags": [], "categories": [],
            "title_found": bool(name), "suggested_title": suggested, "questions": list(questions)}


class Queue(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("recipes", "import_jobs"):
                c.execute(f"DELETE FROM {t}")
        S._recipe_cache["at"] = 0

    def test_titled_scan_with_nothing_to_ask_saves_silently(self):
        job = S.import_queue_add({"pages": [JPEG, JPEG]})
        self.assertEqual((job["status"], job["pages"]), ("waiting", 2))
        reply = ai_reply("Garlic Chicken", ings=[("1 lb", "chicken"), ("2 tbsp", "butter")])
        reply["steps"] = ["Sear the chicken 6 minutes per side."]
        with mock.patch.object(S, "openai_chat", return_value=reply):
            S.import_job_process(job["id"])
        j = S.import_job_view(S._job_row(job["id"]))
        self.assertEqual(j["status"], "done")
        self.assertTrue(j["slug"])
        self.assertTrue(os.path.exists(S._job_page_path(job["id"], 2)))   # pages kept until dismissed

    def test_no_title_and_questions_need_a_quick_look(self):
        job = S.import_queue_add({"pages": [JPEG]})
        qs = [{"kind": "amount", "text": "How much butter?", "choices": ["2 tbsp", "4 tbsp"], "ingredient": 1, "step": -1, "page": 0},
              {"kind": "unreadable", "text": "Melt the … in a pan?", "choices": ["butter", "oil"], "ingredient": -1, "step": 0, "page": 1}]
        with mock.patch.object(S, "openai_chat", return_value=ai_reply("", "Garlic Butter Chicken Thighs", qs)):
            S.import_job_process(job["id"])
        j = S.import_job_view(S._job_row(job["id"]))
        self.assertEqual((j["status"], j["label"]), ("review", "Needs a quick look"))
        self.assertTrue(j["suggested"])
        self.assertEqual(set(j["todo"]), {"name", "q1", "q2"})
        self.assertEqual(S.import_queue_list()["counts"]["review"], 1)
        j = S.import_job_answer(job["id"], {"approve_name": True, "answers": {"q1": "2 tbsp"}})
        self.assertEqual(j["status"], "review")                          # still one question open
        j = S.import_job_answer(job["id"], {"answers": {"q2": "butter"}})
        self.assertEqual(j["status"], "done")
        d = S.recipe_detail(j["slug"])
        self.assertEqual(d["name"], "Garlic Butter Chicken Thighs")
        self.assertTrue(d["name_suggested"])                             # never presented as the original title
        self.assertEqual([x["raw"] for x in d["ingredients"]][1], "2 tbsp butter")
        self.assertEqual(d["steps"][0]["text"], "Melt the butter in a pan.")

    def test_edit_name_and_skip(self):
        job = S.import_queue_add({"pages": [JPEG]})
        qs = [{"kind": "cutoff", "text": "Step 3 is cut off at the bottom of page 1.", "choices": [], "ingredient": -1, "step": -1, "page": 1}]
        with mock.patch.object(S, "openai_chat", return_value=ai_reply("", "Chicken Thighs", qs)):
            S.import_job_process(job["id"])
        j = S.import_job_answer(job["id"], {"name": "Sunday Chicken", "answers": {"q1": "skip"}})
        self.assertEqual(j["status"], "done")
        d = S.recipe_detail(j["slug"])
        self.assertEqual(d["name"], "Sunday Chicken")
        self.assertFalse(d["name_suggested"])
        self.assertEqual(d["steps"][0]["text"], "Melt the (unreadable) in a pan.")   # never guessed

    def test_scan_duplicate_and_retake_and_failure(self):
        S._save_new_recipe(recipe_data("Garlic Chicken", ["1 lb chicken thighs", "butter", "4 cloves garlic"]), dup="skip")
        job = S.import_queue_add({"pages": [JPEG]})
        with mock.patch.object(S, "openai_chat", return_value=ai_reply("Garlic Chicken")):
            S.import_job_process(job["id"])
        j = S.import_job_view(S._job_row(job["id"]))
        self.assertEqual((j["status"], j["label"]), ("review", "Possible duplicate"))
        self.assertEqual(j["dups"][0]["name"], "Garlic Chicken")
        j = S.import_job_retake(job["id"], 1, {"data": JPEG})
        self.assertEqual(j["status"], "waiting")
        with mock.patch.object(S, "openai_chat", side_effect=S.ApiError(502, "The AI is busy.")):
            S.import_job_process(job["id"])
        j = S.import_job_view(S._job_row(job["id"]))
        self.assertEqual((j["status"], j["error"]), ("failed", "The AI is busy."))
        self.assertEqual(S.import_job_retry(job["id"])["status"], "waiting")
        S.import_job_dismiss(job["id"])
        self.assertFalse(os.path.exists(S._job_dir(job["id"])))

    def test_queue_rejects_non_photos(self):
        with self.assertRaises(S.ApiError):
            S.import_queue_add({"pages": ["data:image/jpeg;base64," + base64.b64encode(b"<svg>").decode()]})
        with self.assertRaises(S.ApiError):
            S.import_queue_add({"pages": [JPEG] * 9})


if __name__ == "__main__":
    unittest.main()
