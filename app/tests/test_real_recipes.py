"""Real recipes only: no AI-written recipes; AI finds and matches published ones, every page verified here."""
import http.client
import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest
from datetime import timedelta
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-real-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import ideas as I  # noqa: E402
from app.native import scraper as SC  # noqa: E402

_P = []


def setUpModule():
    for k, v in (("DATA_DIR", _TMP), ("DB_PATH", os.path.join(_TMP, "t.db")), ("IMG_DIR", os.path.join(_TMP, "img")),
                 ("BACKUP_DIR", os.path.join(_TMP, "bk")), ("NATIVE", True), ("PUBLIC_MODE", False)):
        p = mock.patch.object(S, k, v); p.start(); _P.append(p)
    S.init_db(); S.load_cfg()
    S.set_cfg(people=2, setup_complete=True)
    S.save_settings({"polish_imports": False})


def tearDownModule():
    for p in reversed(_P):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


def clean():
    with S.db() as c:
        for t in ("pantry_items", "ext_cache", "idea_cache", "idea_dismissed", "recipes", "ai_usage"):
            c.execute(f"DELETE FROM {t}")
    S.set_internal("idea_denylist", "")
    S._ideas_rate.clear()
    S._recipe_cache["at"] = 0


def stock(name, expires=None, loc="fridge"):
    with S.db() as c:
        pid = S.add_pantry_item(c, name, loc, None, "")
        if expires is not None:
            c.execute("UPDATE pantry_items SET expires_on=? WHERE id=?", (S.iso(S.today() + timedelta(days=expires)), pid))
    return pid


def page(name="Spinach Frittata", ings=("6 eggs", "2 cups spinach", "1/2 cup feta"), steps=("Whisk the eggs.", "Bake 20 minutes.")):
    ld = {"@context": "https://schema.org", "@type": "Recipe", "name": name, "recipeIngredient": list(ings),
          "recipeInstructions": [{"@type": "HowToStep", "text": s} for s in steps], "totalTime": "PT30M"}
    return f'<html><head><title>x</title><script type="application/ld+json">{json.dumps(ld)}</script></head><body></body></html>'


PLAIN = "<html><head><title>Best Frittata</title></head><body><h2>Ingredients</h2><ul><li>6 eggs</li></ul><p>Whisk and bake.</p></body></html>"


class NoAiRecipes(unittest.TestCase):
    def test_ai_idea_route_is_gone(self):
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
            conn.request("POST", "/api/ideas/ai", body="{}", headers={"Content-Type": "application/json", "X-TablePlan": "1"})
            self.assertEqual(conn.getresponse().status, 404)
        finally:
            httpd.shutdown()
        self.assertFalse(hasattr(S, "ai_recipe_ideas"))
        self.assertFalse(hasattr(I, "check_ai_idea"))
        self.assertFalse(hasattr(I, "AI_SCHEMA"))

    def test_save_refuses_unknown_sources(self):
        clean()
        with S.db() as c:
            S._store_ideas(c, [{"id": "ai:x", "source": "ai", "title": "Made up", "ingredients": ["x"], "steps": ["y"]}])
        with self.assertRaises(S.ApiError):
            S.idea_save({"id": "ai:x"})

    def test_import_prompts_forbid_adding(self):
        import inspect
        src = inspect.getsource(S)
        self.assertIn("never add an ingredient, amount, time, temperature or step that isn't in the material", src)
        self.assertIn("NEVER change ingredients, amounts", S.POLISH_PROMPT)


class WebSearch(unittest.TestCase):
    def setUp(self):
        clean()
        S.set_cfg(openai_key="sk-test")
        stock("spinach", expires=1)
        stock("eggs")
        stock("feta")
        stock("tortillas", loc="pantry")

    def tearDown(self):
        S.set_cfg(openai_key="")

    def test_whole_inventory_query(self):
        with S.db() as c:
            foods = S._idea_foods_all(c, S._make_stock(c, S.today()), S.today())
        self.assertEqual((foods[0]["name"].lower(), foods[0]["expiring"]), ("spinach", True))
        self.assertEqual({f["name"].lower().rstrip("s") for f in foods}, {"spinach", "egg", "feta", "tortilla"})
        foods = [{**f, "name": f["name"].lower()} for f in foods]
        angles = I.search_angles(foods, "breakfast", 30, "something cosy")
        self.assertTrue(2 <= len(angles) <= 4)
        self.assertTrue(angles[0].startswith("recipe using spinach"))          # expiring first
        self.assertTrue(any("egg" in a and "tortilla" in a for a in angles))  # the biggest overlap
        self.assertTrue(any(a.startswith("breakfast recipe") for a in angles))  # the meal type
        self.assertTrue(all(a.endswith("something cosy under 30 minutes") for a in angles))

    def run_find(self, results, cited, pages, **b):
        def fetch(u):
            if u not in pages:
                raise S.ApiError(404, "gone")
            return u, pages[u]
        with mock.patch.object(S, "_responses_web_search", return_value=({"recipes": results}, {S._url_norm(u) for u in cited})) as ws, \
                mock.patch.object(S, "_fetch_page", side_effect=fetch), mock.patch.object(S, "mealdb_ideas", return_value=[]), \
                mock.patch.object(S, "wikibooks_ideas", return_value=[]):
            out = S.find_ideas({"web": True, **b}, "u1")
        return out, ws

    def test_uncited_unstructured_denylisted_and_http_dropped(self):
        good, uncited, plain = "https://cooks.example/frittata", "https://other.example/r", "https://plain.example/r"
        spam, http = "https://www.pinterest.com/pin/1", "http://cooks.example/old"
        res = [{"title": "AI says: amazing", "url": u} for u in (good, uncited, plain, spam, http)]
        out, ws = self.run_find(res, [good, plain, spam, http], {good: page(), uncited: page(), plain: PLAIN, spam: page(), http: page()})
        self.assertIn("spinach", ws.call_args[0][0].lower())
        self.assertEqual([i["url"] for i in out["ideas"]], [good])
        i = out["ideas"][0]
        self.assertEqual((i["title"], i["site"], i["source"]), ("Spinach Frittata", "cooks.example", "web"))   # the page's name, not the AI's

    def test_scored_from_the_pages_own_ingredients(self):
        a, b = "https://a.example/r", "https://b.example/r"
        pages = {a: page("Spinach Frittata", ("6 eggs", "2 cups spinach", "1/2 cup feta")),
                 b: page("Lasagna", ("1 lb pasta", "2 cups ricotta", "1 jar sauce", "2 eggs"))}
        out, _ = self.run_find([{"title": "Uses everything you have!", "url": b}, {"title": "x", "url": a}], [a, b], pages)
        top, low = out["ideas"]
        self.assertEqual((top["url"], top["missing_n"], [e["name"] for e in top["expiring"]]), (a, 0, ["spinach"]))
        self.assertEqual(low["missing_n"], 3)

    def test_denylist_is_configurable(self):
        S.ideas_config({"denylist": "spam.example\nhttps://www.junk.example/x, not a domain"})
        self.assertEqual(S.idea_denylist(), ["spam.example", "junk.example"])
        self.assertTrue(I.denied("https://recipes.spam.example/r", S.idea_denylist()))
        u = "https://spam.example/r"
        out, _ = self.run_find([{"title": "x", "url": u}], [u], {u: page()})
        self.assertEqual(out["ideas"], [])

    def test_cache_and_budget(self):
        u = "https://a.example/r"
        out, ws = self.run_find([{"title": "x", "url": u}], [u], {u: page()})
        self.assertFalse(out["cached"])
        out2, ws2 = self.run_find([], [], {})
        self.assertTrue(out2["cached"])
        ws2.assert_not_called()                                                   # same inventory: no new search
        self.assertEqual([i["url"] for i in out2["ideas"]], [u])
        stock("rice", loc="pantry")                                               # inventory changed: search again
        _, ws3 = self.run_find([], [], {})
        ws3.assert_called_once()
        clean()
        stock("eggs")
        with mock.patch.object(S, "_ai_over_budget", return_value=True), mock.patch.object(S, "mealdb_ideas", return_value=[]), \
                mock.patch.object(S, "wikibooks_ideas", return_value=[]), mock.patch.object(S, "_https_json") as h:
            out = S.find_ideas({"web": True}, "u9")
        h.assert_not_called()
        self.assertTrue(any("budget" in e for e in out["errors"]))               # the free sources still answer

    def test_no_key_free_sources_still_work(self):
        S.set_cfg(openai_key="")
        mealdb = {"id": "mealdb:1", "source": "mealdb", "label": "Recipe · TheMealDB", "title": "Egg Fried Rice",
                  "url": "https://www.themealdb.com/meal/1", "image": "", "ingredients": ["2 eggs", "2 cups rice"], "steps": ["Fry."]}
        with mock.patch.object(S, "mealdb_ideas", return_value=[mealdb]), mock.patch.object(S, "wikibooks_ideas", return_value=[]), \
                mock.patch.object(S, "_responses_web_search") as ws:
            out = S.find_ideas({"web": True}, "u1")
        ws.assert_not_called()
        self.assertFalse(out["sources"]["web"])
        self.assertEqual(out["ideas"][0]["title"], "Egg Fried Rice")


class MergedRanking(unittest.TestCase):
    def test_rank(self):
        ideas = [{"title": "C", "missing_n": 1, "expiring": [1, 2], "rating": 0},
                 {"title": "A", "missing_n": 0, "expiring": [], "rating": 0},
                 {"title": "B", "missing_n": 0, "expiring": [1], "rating": 0},
                 {"title": "D", "missing_n": 0, "expiring": [1], "rating": 4.5}]
        self.assertEqual([i["title"] for i in sorted(ideas, key=I.rank_key)], ["D", "B", "A", "C"])


WIKI_TEXT = """{{recipe summary|category=Egg recipes|servings=2}}
'''Spinach omelette''' is quick.
== Ingredients ==
* 3 [[Cookbook:Egg|eggs]]
* 1 cup [[Cookbook:Spinach|spinach]]<ref>fresh</ref>
* [[Cookbook:Salt|Salt]]
== Procedure ==
# Whisk the eggs.
# Wilt the spinach for 2 minutes, then add the eggs.
# Cook until set.
[[Category:Egg recipes]]"""


class Wikibooks(unittest.TestCase):
    def setUp(self):
        clean()
        stock("spinach", expires=1)
        stock("eggs")

    def test_parse_cache_and_credit(self):
        calls = []

        def fake(url, **kw):
            calls.append(url)
            self.assertTrue(url.startswith("https://en.wikibooks.org/w/api.php?"))
            self.assertIn("TablePlan", kw["headers"]["User-Agent"])
            if "list=search" in url:
                return {"query": {"search": [{"title": "Cookbook:Spinach Omelette"}, {"title": "Cookbook:Spinach"}]}}
            if "Spinach+Omelette" in url or "Spinach%20Omelette" in url:
                return {"parse": {"title": "Cookbook:Spinach Omelette", "wikitext": WIKI_TEXT}}
            return {"parse": {"title": "Cookbook:Spinach", "wikitext": "Spinach is a leafy green.\n== Selection ==\n* Fresh"}}
        with mock.patch.object(S, "_https_json", side_effect=fake):
            got = S.wikibooks_ideas(["spinach"])
            n = len(calls)
            S.wikibooks_ideas(["spinach"])
        self.assertEqual(len(calls), n)                                           # cached (7 days)
        self.assertEqual(len(got), 1)                                             # the ingredient article isn't a recipe
        i = got[0]
        self.assertEqual(i["ingredients"], ["3 eggs", "1 cup spinach", "Salt"])
        self.assertEqual(i["steps"][1], "Wilt the spinach for 2 minutes, then add the eggs.")
        self.assertEqual(i["label"], "Wikibooks Cookbook · CC BY-SA")
        self.assertEqual(i["url"], "https://en.wikibooks.org/wiki/Cookbook:Spinach_Omelette")
        with S.db() as c:
            S._store_ideas(c, [i])
        slug = S.idea_save({"id": i["id"]})["slug"]
        with S.db() as c:
            rec = S.n_recipes.get(c, slug)
        cr = rec["extras"]["source_credit"]
        self.assertEqual((cr["site"], cr["license"], cr["url"]), ("Wikibooks Cookbook", "CC BY-SA 4.0", i["url"]))
        self.assertEqual(S.recipe_detail(slug)["source_credit"]["license_url"], "https://creativecommons.org/licenses/by-sa/4.0/")
        self.assertEqual(rec["orgURL"], i["url"])


class AiCreatedReview(unittest.TestCase):
    def test_count_and_filter_flag(self):
        clean()
        a = S._save_new_recipe({"name": "Old AI Idea", "recipeIngredient": [{"note": "1 egg"}],
                                "recipeInstructions": [{"text": "Cook."}], "extras": {"ai_generated": True}}, None, dup="keep")
        S._save_new_recipe({"name": "Grandma's Soup", "recipeIngredient": [{"note": "1 onion"}],
                            "recipeInstructions": [{"text": "Simmer."}]}, None, dup="keep")
        S._recipe_cache["at"] = 0
        pool = {r["slug"]: r for r in S.recipe_pool(refresh=True)}
        self.assertTrue(pool[a]["ai_generated"])
        self.assertEqual(sum(1 for r in pool.values() if r.get("ai_generated")), 1)
        self.assertEqual(S.ideas_status()["ai_created"], 1)
        self.assertTrue(S.recipe_detail(a)["ai_generated"])                     # kept, badge and all


class StrictParser(unittest.TestCase):
    def test_structured_only(self):
        self.assertEqual(SC.parse_structured(page(), "https://a.example/r")["name"], "Spinach Frittata")
        with self.assertRaises(SC.NoRecipe):
            SC.parse_structured(PLAIN, "https://a.example/r")
        nameless = page(name="")
        with self.assertRaises(SC.NoRecipe):
            SC.parse_structured(nameless, "https://a.example/r")


if __name__ == "__main__":
    unittest.main()
