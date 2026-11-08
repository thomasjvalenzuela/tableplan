import os
import shutil
import sqlite3
import tempfile
import unittest

from app.native import recipes

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32

TACOS = {
    "id": "11111111-1111-1111-1111-111111111111", "slug": "tacos", "name": "Tacos",
    "description": "Weeknight tacos", "image": "AbCd", "recipeServings": 4, "recipeYield": "8 tacos",
    "totalTime": "30 minutes", "rating": 5, "orgURL": "https://example.com/tacos",
    "tags": [{"name": "Mexican"}], "recipeCategory": [{"name": "Dinner"}],
    "recipeIngredient": [{"referenceId": "ing-1", "title": None, "note": "", "display": "1 lb beef",
                          "originalText": "1 lb beef", "quantity": 1, "unit": {"name": "lb"},
                          "food": {"name": "beef"}}],
    "recipeInstructions": [{"id": "s1", "title": "", "text": "Brown the beef.", "ingredientReferences": []}],
    "dateUpdated": "2026-01-01T00:00:00", "lastMade": None,
}
SOUP = {"id": "22222222-2222-2222-2222-222222222222", "slug": "soup", "name": "Soup",
        "recipeIngredient": [], "recipeInstructions": []}


class FakeMealie:
    def __init__(self, recipes_, media, favorites):
        self.recipes, self.media, self.favorites, self.calls = recipes_, media, favorites, []

    def __call__(self, method, path):
        self.calls.append((method, path))
        if path == "/api/recipes?page=1&perPage=-1":
            return {"items": [{k: v for k, v in r.items() if k not in ("recipeIngredient", "recipeInstructions")}
                              for r in self.recipes]}
        if path == "/api/users/self":
            return {"id": "u1"}
        if path == "/api/users/u1/favorites":
            return {"ratings": [{"recipeId": rid, "isFavorite": True, "rating": None} for rid in self.favorites]
                    + [{"recipeId": SOUP["id"], "isFavorite": False, "rating": 3}]}
        for r in self.recipes:
            if path == f"/api/recipes/{r['slug']}":
                return dict(r)
        raise RuntimeError(f"404 {path}")

    def bytes(self, path):
        self.calls.append(("BYTES", path))
        return self.media.get(path)


class RecipesTest(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        self.c.row_factory = sqlite3.Row
        recipes.init(self.c)
        recipes.init(self.c)  # idempotent
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(self.c.close)

    def test_slugify(self):
        self.assertEqual(recipes.slugify("  Crème Brûlée & Friends! "), "creme-brulee-friends")
        self.assertEqual(recipes.slugify("!!!"), "recipe")

    def test_create_unique_slugs_and_default_shape(self):
        s1 = recipes.create(self.c, "Chicken Soup")
        s2 = recipes.create(self.c, "Chicken soup")
        s3 = recipes.create(self.c, "chicken-soup")
        self.assertEqual([s1, s2, s3], ["chicken-soup", "chicken-soup-2", "chicken-soup-3"])
        r = recipes.get(self.c, s1)
        for key in ("id", "slug", "name", "description", "image", "recipeServings", "recipeYield",
                    "totalTimeSeconds", "prepTimeSeconds", "performTimeSeconds", "totalTime", "prepTime",
                    "performTime", "rating", "orgURL", "tags", "recipeCategory", "recipeIngredient",
                    "recipeInstructions", "dateUpdated", "lastMade"):
            self.assertIn(key, r)
        self.assertEqual(r["recipeIngredient"], [])
        self.assertEqual(recipes.get(self.c, r["id"])["slug"], s1)
        with self.assertRaises(ValueError):
            recipes.create(self.c, "  ")

    def test_create_with_data_ignores_identity_fields(self):
        slug = recipes.create(self.c, "Tacos", {"id": "x", "slug": "y", "recipeYield": "8",
                                                "recipeIngredient": [{"note": "salt"}],
                                                "recipeInstructions": [{"text": "Mix"}]})
        r = recipes.get(self.c, slug)
        self.assertEqual(slug, "tacos")
        self.assertNotEqual(r["id"], "x")
        self.assertEqual(r["recipeYield"], "8")
        self.assertTrue(r["recipeIngredient"][0]["referenceId"])
        self.assertTrue(r["recipeInstructions"][0]["id"])
        self.assertEqual(r["recipeInstructions"][0]["ingredientReferences"], [])

    def test_list_summaries_omits_detail(self):
        recipes.create(self.c, "b recipe", {"recipeIngredient": [{"note": "x"}]})
        recipes.create(self.c, "A recipe")
        items = recipes.list_summaries(self.c)
        self.assertEqual([i["name"] for i in items], ["A recipe", "b recipe"])
        for i in items:
            self.assertNotIn("recipeIngredient", i)
            self.assertNotIn("recipeInstructions", i)
            self.assertIn("tags", i)

    def test_update_replaces_and_reslugs_with_alias(self):
        slug = recipes.create(self.c, "Tacos", {"description": "old", "rating": 4})
        rid = recipes.get(self.c, slug)["id"]
        recipes.save_image(self.tmp, rid, PNG, "png", c=self.c)
        token = recipes.get(self.c, slug)["image"]
        new = recipes.update(self.c, slug, {"id": "hijack", "name": "Fish Tacos", "description": "new"})
        self.assertEqual(new, "fish-tacos")
        r = recipes.get(self.c, "tacos")  # old slug still resolves
        self.assertEqual((r["id"], r["slug"], r["description"]), (rid, "fish-tacos", "new"))
        self.assertIsNone(r["rating"])  # full replacement
        self.assertEqual(r["image"], token)  # image preserved when not supplied
        self.assertNotEqual(r["dateUpdated"], "")
        # same name keeps slug; a new recipe may claim the freed alias slug
        self.assertEqual(recipes.update(self.c, "fish-tacos", {"name": "Fish Tacos"}), "fish-tacos")
        other = recipes.create(self.c, "Tacos")
        self.assertEqual(other, "tacos")
        self.assertNotEqual(recipes.get(self.c, "tacos")["id"], rid)
        with self.assertRaises(KeyError):
            recipes.update(self.c, "nope", {"name": "x"})

    def test_rename_back_reclaims_slug(self):
        slug = recipes.create(self.c, "Tacos")
        recipes.update(self.c, slug, {"name": "Burritos"})
        self.assertEqual(recipes.update(self.c, "burritos", {"name": "Tacos"}), "tacos")
        self.assertEqual(recipes.get(self.c, "burritos")["slug"], "tacos")

    def test_delete_and_favorites(self):
        slug = recipes.create(self.c, "Tacos")
        rid = recipes.get(self.c, slug)["id"]
        recipes.set_favorite(self.c, rid, True)
        recipes.set_favorite(self.c, rid, True)
        recipes.set_favorite(self.c, "missing", True)
        self.assertEqual(recipes.favorite_ids(self.c), [rid])
        recipes.set_favorite(self.c, rid, False)
        self.assertEqual(recipes.favorite_ids(self.c), [])
        recipes.set_favorite(self.c, rid, True)
        recipes.save_image(self.tmp, rid, JPG, "jpeg")
        self.assertTrue(recipes.delete(self.c, slug, images_dir=self.tmp))
        self.assertIsNone(recipes.get(self.c, slug))
        self.assertEqual(recipes.favorite_ids(self.c), [])
        self.assertIsNone(recipes.image_path(self.tmp, rid))
        self.assertFalse(recipes.delete(self.c, slug))

    def test_save_image_validation_and_replacement(self):
        slug = recipes.create(self.c, "Tacos")
        rid = recipes.get(self.c, slug)["id"]
        for blob, ext in ((PNG, "png"), (JPG, "jpg"), (WEBP, ".WEBP"), (GIF, "gif")):
            token = recipes.save_image(self.tmp, rid, blob, ext, c=self.c)
            path = recipes.image_path(self.tmp, rid)
            self.assertTrue(path.endswith(os.path.join("recipes", rid, f"original.{ext.lower().strip('.')}")))
            self.assertEqual(len(os.listdir(os.path.dirname(path))), 1)  # old variants removed
            self.assertEqual(recipes.get(self.c, slug)["image"], token)
        with self.assertRaises(ValueError):
            recipes.save_image(self.tmp, rid, b"<html>", "png")
        with self.assertRaises(ValueError):
            recipes.save_image(self.tmp, rid, PNG, "jpg")
        with self.assertRaises(ValueError):
            recipes.save_image(self.tmp, rid, PNG + b"\x00" * recipes.MAX_IMAGE_BYTES, "png")
        with self.assertRaises(ValueError):
            recipes.save_image(self.tmp, "../evil", PNG, "png")
        self.assertIsNone(recipes.image_path(self.tmp, "00000000-0000-0000-0000-000000000000"))

    def test_migrate_from_mealie_idempotent(self):
        media = {f"/api/media/recipes/{TACOS['id']}/images/original.webp": WEBP,
                 f"/api/media/recipes/{SOUP['id']}/images/min-original.webp": WEBP}
        broken = {"id": "33333333-3333-3333-3333-333333333333", "slug": "ghost", "name": "Ghost"}
        fake = FakeMealie([TACOS, SOUP], media, [TACOS["id"]])
        fake.recipes.append(broken)
        orig_call = fake.__call__

        def mealie(method, path):
            if path == "/api/recipes/ghost":
                raise RuntimeError("boom")
            return orig_call(method, path)

        counts = recipes.migrate_from_mealie(self.c, mealie, fake.bytes, self.tmp)
        self.assertEqual({k: counts[k] for k in ("recipes", "created", "updated", "images", "favorites")},
                         {"recipes": 2, "created": 2, "updated": 0, "images": 2, "favorites": 1})
        self.assertEqual(len(counts["errors"]), 1)
        self.assertIn("ghost", counts["errors"][0])

        r = recipes.get(self.c, "tacos")
        self.assertEqual(r["id"], TACOS["id"])
        self.assertEqual(r["recipeIngredient"], TACOS["recipeIngredient"])
        self.assertEqual(r["recipeInstructions"], TACOS["recipeInstructions"])
        self.assertEqual(r["tags"], [{"name": "Mexican"}])
        self.assertNotEqual(r["image"], "AbCd")
        self.assertTrue(recipes.image_path(self.tmp, SOUP["id"]).endswith("original.webp"))
        self.assertEqual(recipes.favorite_ids(self.c), [TACOS["id"]])

        image_token = r["image"]
        fake.calls.clear()
        again = recipes.migrate_from_mealie(self.c, mealie, fake.bytes, self.tmp)
        self.assertEqual((again["recipes"], again["created"], again["updated"], again["images"],
                          again["favorites"]), (2, 0, 2, 0, 1))
        self.assertFalse([p for m, p in fake.calls if m == "BYTES"])  # images not refetched
        self.assertEqual(recipes.get(self.c, "tacos")["image"], image_token)
        self.assertEqual(len(recipes.list_summaries(self.c)), 2)

    def test_migrate_slug_collision_with_native_recipe(self):
        recipes.create(self.c, "Tacos")  # native recipe already owns "tacos"
        fake = FakeMealie([TACOS], {}, [])
        counts = recipes.migrate_from_mealie(self.c, fake, fake.bytes, self.tmp)
        self.assertEqual(counts["recipes"], 1)
        self.assertEqual(recipes.get(self.c, TACOS["id"])["slug"], "tacos-2")
        self.assertIsNone(recipes.get(self.c, TACOS["id"])["image"])  # no media -> no stale token


if __name__ == "__main__":
    unittest.main()
