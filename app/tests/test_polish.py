"""AI polish of imported recipes and "Reword with AI" (openai_chat mocked)."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-polish-")
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
    S.set_cfg(setup_complete=True, app_password_hash="", openai_key="sk-test")


def tearDownModule():
    S.set_cfg(openai_key="")
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


def imported(name="Pancakes"):
    lines = ["2 c. flour", "1 ½ cups milk", "1 egg"]
    return {"name": name, "description": "pancakes",
            "recipeIngredient": [{"title": "Batter" if i == 0 else None, "note": l, "display": l, "originalText": l,
                                  "quantity": 0, "unit": None, "food": None} for i, l in enumerate(lines)],
            "recipeInstructions": [{"text": "mix"}, {"text": "cook 3 min"}, {"text": "serve"}]}


GOOD = {"description": "Fluffy pancakes.",
        "ingredients": [{"section": "Batter", "quantity_text": "2 cups", "name": "all-purpose flour", "note": ""},
                        {"section": "Batter", "quantity_text": "1 1/2 cups", "name": "milk", "note": ""},
                        {"section": "Batter", "quantity_text": "1", "name": "large egg", "note": ""}],
        "steps": ["Whisk everything in a large bowl until smooth.",
                  "Cook ladlefuls in a buttered skillet over medium heat for 3 minutes, until golden.",
                  "Serve warm."]}


class Polish(unittest.TestCase):
    def setUp(self):
        S.save_settings({"polish_imports": True})

    def save(self, reply, name="Pancakes"):
        with mock.patch.object(S, "openai_chat", return_value=reply) as oc:
            slug = S._save_new_recipe(imported(name))
        with S.db() as c:
            return S.n_recipes.get(c, slug), oc

    def test_polish_applied_and_original_kept(self):
        rec, oc = self.save(GOOD)
        self.assertEqual(oc.call_args.args[3], "polish")
        self.assertEqual([g["note"] for g in rec["recipeIngredient"]],
                         ["2 cups all-purpose flour", "1 1/2 cups milk", "1 large egg"])
        self.assertEqual(rec["recipeIngredient"][0]["title"], "Batter")
        self.assertEqual(rec["recipeInstructions"][1]["text"], GOOD["steps"][1])
        self.assertEqual(rec["description"], "Fluffy pancakes.")
        self.assertEqual(rec["extras"]["original"], {"ingredients": ["2 c. flour", "1 ½ cups milk", "1 egg"],
                                                     "steps": ["mix", "cook 3 min", "serve"], "description": "pancakes"})
        self.assertEqual(S.recipe_detail(rec["slug"])["original"]["steps"], ["mix", "cook 3 min", "serve"])

    def test_changed_number_reverts_ingredients_only(self):
        bad = dict(GOOD, ingredients=[{"section": "", "quantity_text": "3 cups", "name": "flour", "note": ""}] + GOOD["ingredients"][1:])
        rec, _ = self.save(bad, "Pancakes 2")
        self.assertEqual([g["note"] for g in rec["recipeIngredient"]], ["2 c. flour", "1 ½ cups milk", "1 egg"])
        self.assertEqual(rec["recipeInstructions"][2]["text"], "Serve warm.")
        self.assertEqual(rec["description"], "Fluffy pancakes.")

    def test_dropped_steps_discard_everything(self):
        rec, _ = self.save(dict(GOOD, steps=["Do it all."]), "Pancakes 3")
        self.assertEqual([s["text"] for s in rec["recipeInstructions"]], ["mix", "cook 3 min", "serve"])
        self.assertEqual(rec["description"], "pancakes")
        self.assertNotIn("original", rec.get("extras") or {})

    def test_setting_off_or_failure_means_no_polish(self):
        S.save_settings({"polish_imports": False})
        rec, oc = self.save(GOOD, "Pancakes 4")
        oc.assert_not_called()
        self.assertEqual(rec["description"], "pancakes")
        S.save_settings({"polish_imports": True})
        with mock.patch.object(S, "openai_chat", side_effect=S.ApiError(504, "timeout")):
            slug = S._save_new_recipe(imported("Pancakes 5"))
        with S.db() as c:
            self.assertEqual(S.n_recipes.get(c, slug)["description"], "pancakes")
        with self.assertRaises(S.ApiError):
            S.save_settings({"polish_imports": "yes"})

    def test_reword_and_restore(self):
        S.save_settings({"polish_imports": False})
        rec, _ = self.save(GOOD, "Pancakes 6")
        with S.db() as c:
            c.execute("INSERT INTO guided_cache(recipe_id, profile, data) VALUES (?,?,?)", (rec["id"], "p", "{}"))
        with mock.patch.object(S, "openai_chat", return_value=GOOD) as oc:
            d = S.recipe_polish(rec["slug"])
        self.assertIn("Reword for clarity only", oc.call_args.args[0][0]["content"])
        self.assertEqual(d["steps"][0]["text"], GOOD["steps"][0])
        self.assertEqual(d["original"]["steps"], ["mix", "cook 3 min", "serve"])
        with S.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM guided_cache WHERE recipe_id=?", (rec["id"],)).fetchone()[0], 0)
        # rewording again keeps the true original
        again = dict(GOOD, steps=[s + " Enjoy." for s in GOOD["steps"]])
        with mock.patch.object(S, "openai_chat", return_value=again):
            d = S.recipe_polish(rec["slug"])
        self.assertEqual(d["original"]["steps"], ["mix", "cook 3 min", "serve"])
        d = S.recipe_restore_original(rec["slug"])
        self.assertEqual([s["text"] for s in d["steps"]], ["mix", "cook 3 min", "serve"])
        self.assertEqual([i["raw"] for i in d["ingredients"]], ["2 c. flour", "1 ½ cups milk", "1 egg"])
        with mock.patch.object(S, "openai_chat", return_value=dict(GOOD, steps=["x"])):
            with self.assertRaises(S.ApiError):
                S.recipe_polish(rec["slug"])
        S.set_cfg(openai_key="")
        try:
            with self.assertRaises(S.ApiError):
                S.recipe_polish(rec["slug"])
        finally:
            S.set_cfg(openai_key="sk-test")


if __name__ == "__main__":
    unittest.main()


class TitleCaseOnSave(unittest.TestCase):
    def test_import_edit_and_migration(self):
        S.save_settings({"polish_imports": False})
        slug = S._save_new_recipe(dict(imported("french toast with berries")))
        self.assertEqual(S.recipe_detail(slug)["name"], "French Toast with Berries")
        S.recipe_update(slug, {"name": "grandma's slow-cooker chili"})
        with S.db() as c:
            rid = S.n_recipes.get(c, "grandma-s-slow-cooker-chili")["id"]
            self.assertEqual(S.n_recipes.get(c, rid)["name"], "Grandma's Slow-Cooker Chili")
            rec = S.n_recipes.get(c, rid)
            S.n_recipes.update(c, rid, dict(rec, name="old lower name"))
            c.execute("DELETE FROM settings WHERE key='titlecase_migrated'")
        S.init_db()
        with S.db() as c:
            self.assertEqual(S.n_recipes.get(c, rid)["name"], "Old Lower Name")


class Categories(unittest.TestCase):
    def setUp(self):
        S.save_settings({"categories": S.DEFAULT_SETTINGS["categories"], "polish_imports": False})

    def make(self, name, cats=()):
        slug = S.mealie("POST", "/api/recipes", {"name": name})
        if cats:
            S.recipe_update(slug, {"categories": list(cats)})
        return slug

    def cats(self, slug):
        with S.db() as c:
            return S._rec_categories(S.n_recipes.get(c, slug))

    def test_validation(self):
        self.assertEqual(S.save_settings({"categories": ["  Mains ", "Sides"]})["categories"], ["Mains", "Sides"])
        for bad in (["x" * 31], [""], ["A", "a"], "Mains", [5], ["c"] * 31):
            with self.assertRaises(S.ApiError):
                S.save_settings({"categories": bad})
        S.save_settings({"categories": S.DEFAULT_SETTINGS["categories"]})
        slug = self.make("Cat Soup", ["soup", "Main dish"])
        self.assertEqual(self.cats(slug), ["Main dish", "Soup"])   # settings spelling and order
        with self.assertRaises(S.ApiError):
            S.recipe_update(slug, {"categories": ["Nope"]})
        self.assertEqual(S.recipe_detail(slug)["categories"], ["Main dish", "Soup"])

    def test_rename_and_delete_propagate(self):
        a, b = self.make("Cat A", ["Soup"]), self.make("Cat B", ["Soup", "Salad"])
        out = S.category_rename({"from": "Soup", "to": "Soups & stews"})
        self.assertEqual(out["recipes"], 2)
        self.assertIn("Soups & stews", S.get_settings()["categories"])
        self.assertEqual(self.cats(a), ["Soups & stews"])
        with self.assertRaises(S.ApiError):
            S.category_rename({"from": "Soups & stews", "to": "Salad"})   # duplicate
        out = S.category_delete({"name": "Soups & stews"})
        self.assertNotIn("Soups & stews", out["categories"])
        self.assertEqual((self.cats(a), self.cats(b)), ([], ["Salad"]))
        S.category_undo_delete(out["undo"])
        self.assertEqual(S.get_settings()["categories"][2], "Soups & stews")
        self.assertEqual(self.cats(b), ["Soups & stews", "Salad"])

    def test_bulk_set(self):
        a, b = self.make("Bulk A"), self.make("Bulk B", ["Dessert"])
        self.assertEqual(S.recipes_bulk({"slugs": [a, b, "missing"], "categories": ["Snack"]})["updated"], 2)
        self.assertEqual((self.cats(a), self.cats(b)), (["Snack"], ["Snack"]))
        for bad in ({"slugs": [], "categories": []}, {"slugs": [a], "categories": ["Nope"]}, {"slugs": a}):
            with self.assertRaises(S.ApiError):
                S.recipes_bulk(bad)

    def test_ai_picks_only_known_categories(self):
        S.save_settings({"polish_imports": True})
        reply = dict(GOOD, categories=["Breakfast", "Brunch", "Dessert", "Snack"])
        with mock.patch.object(S, "openai_chat", return_value=reply) as oc:
            slug = S._save_new_recipe(imported("Cat Pancakes"))
        self.assertIn("Main dish; Side dish", oc.call_args.args[0][0]["content"])
        self.assertEqual(self.cats(slug), ["Breakfast", "Dessert"])


class DiaryAndAdjust(unittest.TestCase):
    def setUp(self):
        S.save_settings({"polish_imports": False})
        with S.db() as c:
            c.execute("DELETE FROM diary")
        self.slug = S._save_new_recipe(dict(imported(f"Diary Pancakes {id(self)}"), recipeServings=2))
        S._recipe_cache["at"] = 0

    def test_cooked_creates_entry_rating_average_and_undo(self):
        out = S.recipe_cooked(self.slug, {})
        self.assertIsNotNone(out["diary_id"])
        S.diary_update(out["diary_id"], {"rating": 5, "note": "Less sugar next time"})
        second = S.recipe_cooked(self.slug, {})
        S.diary_update(second["diary_id"], {"rating": 4})
        d = S.recipe_detail(self.slug)
        self.assertEqual(d["rating"], 4.5)
        self.assertEqual([e["rating"] for e in d["diary"]], [4, 5])
        pool = {r["slug"]: r for r in S.recipe_pool(refresh=True)}
        self.assertEqual(pool[self.slug]["rating"], 4.5)
        self.assertEqual([e["note"] for e in S.diary_list("notes")], ["Less sugar next time"])
        self.assertEqual(len(S.diary_list("top")), 2)
        S.cooked_undo({"undo_token": second["undo_token"]})   # undoing a cook removes its diary entry
        self.assertEqual(len(S.recipe_detail(self.slug)["diary"]), 1)
        note = S.diary_add({"slug": self.slug, "note": "Try with blueberries"})
        self.assertEqual(note["kind"], "note")
        for bad in ({"rating": 6}, {"rating": True}):
            with self.assertRaises(S.ApiError):
                S.diary_update(note["id"], bad)
        S.diary_delete(note["id"])

    def test_adjust_preview_save_and_revert(self):
        proposal = {"summary": "spicier: +1 tsp chili flakes", "ingredients": [
            {"status": "same", "was": "2 c. flour", "line": "2 c. flour", "reason": ""},
            {"status": "changed", "was": "1 ½ cups milk", "line": "1 ½ cups buttermilk", "reason": "tangier"},
            {"status": "removed", "was": "1 egg", "line": "", "reason": "lighter"},
            {"status": "added", "was": "", "line": "1 tsp chili flakes", "reason": "spicier"}],
            "steps": [{"status": "same", "was": "mix", "text": "mix", "reason": ""},
                      {"status": "changed", "was": "cook 3 min", "text": "cook 3 min with the chili", "reason": "spice"},
                      {"status": "same", "was": "serve", "text": "serve", "reason": ""}]}
        with mock.patch.object(S, "openai_chat", return_value=proposal) as oc:
            p = S.recipe_adjust(self.slug, {"request": "spicier"})
        self.assertIn("Make only the changes needed", oc.call_args.args[0][0]["content"])
        d = S.recipe_adjust_save(self.slug, {**p, "request": "spicier"})
        self.assertEqual([i["raw"] for i in d["ingredients"]], ["2 c. flour", "1 ½ cups buttermilk", "1 tsp chili flakes"])
        self.assertEqual(d["steps"][1]["text"], "cook 3 min with the chili")
        self.assertEqual(d["versions"], 1)
        self.assertTrue(d["diary"][0]["note"].startswith("Adjusted: spicier: +1 tsp chili flakes"))
        vs = S.recipe_versions(d["slug"])["versions"]
        d = S.recipe_version_restore(d["slug"], vs[0]["n"])
        self.assertEqual([i["raw"] for i in d["ingredients"]], ["2 c. flour", "1 ½ cups milk", "1 egg"])
        self.assertEqual(d["versions"], 1)   # the adjusted text is kept as a version too
        S.set_cfg(openai_key="")
        try:
            with self.assertRaises(S.ApiError):
                S.recipe_adjust(self.slug, {"request": "spicier"})
        finally:
            S.set_cfg(openai_key="sk-test")
