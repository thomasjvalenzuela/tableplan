"""0.5 features: planner board list sync, stores, cook readiness, backups, recipe print/export."""

import http.client
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
import zipfile
from datetime import datetime, timedelta
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-v05-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import lists as n_lists  # noqa: E402

_PATCHES = []


def setUpModule():
    # The server module may already be imported by another test module with its own DATA_DIR: point it here.
    for name, value in (("DATA_DIR", _TMP), ("DB_PATH", os.path.join(_TMP, "tableplan.db")),
                        ("IMG_DIR", os.path.join(_TMP, "images")), ("BACKUP_DIR", os.path.join(_TMP, "backups")),
                        ("NATIVE", True), ("PUBLIC_MODE", False)):
        p = mock.patch.object(S, name, value)
        p.start()
        _PATCHES.append(p)
    S.init_db()
    S.load_cfg()
    S.set_cfg(people=4, scale_to_household=True, setup_complete=True, app_password_hash="")


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


def day(n):
    return S.iso(S.today() + timedelta(days=n))


def new_recipe(name, servings, ingredients, steps=("Cook it.",), minutes=30):
    slug = S.mealie("POST", "/api/recipes", {"name": name})
    S.recipe_update(slug, {"servings": servings, "total_minutes": minutes, "ingredients": list(ingredients),
                           "steps": list(steps)})
    S._recipe_cache["at"] = 0
    with S.db() as c:
        return slug, S.n_recipes.get(c, slug)["id"]


class Base(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("meal_plans", "shopping_items", "pantry_items", "food_store", "stores"):
                c.execute(f"DELETE FROM {t}")
            n_lists.seed_stores(c, S.DEFAULT_STORES)
            c.execute("DELETE FROM settings WHERE key IN ('plan_runout_notified', 'plan_reminder_days')")
        S._recipe_cache["at"] = 0

    def items(self):
        return S.ongoing_list()["items"]

    def texts(self):
        return sorted(i["text"] for i in self.items())


class Fixtures:
    tacos = pasta = None

    @classmethod
    def recipes(cls):
        if not cls.tacos:
            cls.tacos = new_recipe("Test Tacos", 2, ["1 lb chicken breast", "2 cups shredded cheddar cheese",
                                                    "1 onion, diced", "8 tortillas"],
                                   ["Cook the chicken for 10 minutes.", "Bake at 400F for 8 minutes."])
            cls.pasta = new_recipe("Test Pasta", 4, ["1 lb spaghetti", "1 onion", "2 cups milk"], ["Boil pasta."])
        return cls.tacos, cls.pasta


class PlannerListSync(Base):
    def setUp(self):
        super().setUp()
        (self.tslug, self.tid), (self.pslug, self.pid) = Fixtures.recipes()

    def test_assign_scales_links_and_skips_pantry(self):
        with S.db() as c:
            S.add_pantry_item(c, "cheddar cheese")
        res = S.plan_assign({"date": day(1), "recipe_id": self.tid})
        self.assertEqual(res["added"], 3)
        self.assertEqual(res["skipped"], ["cheddar cheese"])
        e = res["entry"]
        self.assertEqual((e["date"], e["entry_type"], e["scale"], e["missing"]), (day(1), "dinner", 2.0, 3))
        self.assertEqual((e["recipe"]["id"], e["recipe"]["slug"], e["recipe"]["minutes"]), (self.tid, self.tslug, 30))
        self.assertIn("image_v", e["recipe"])
        self.assertEqual(self.texts(), ["16 tortillas", "2 lb chicken breast", "2 onion, diced"])
        self.assertTrue(all(i["recipes"] == ["Test Tacos"] for i in self.items()))

    def test_assign_validates(self):
        for body in ({"date": "2026-02-30", "recipe_id": self.tid}, {"date": day(1), "recipe_id": ""},
                     {"date": day(1), "recipe_id": self.tid, "entry_type": "brunch"}, {"date": 20261110, "recipe_id": self.tid}):
            with self.assertRaises(S.ApiError) as cm:
                S.plan_assign(body)
            self.assertEqual(cm.exception.status, 400, body)
        with self.assertRaises(S.ApiError) as cm:
            S.plan_assign({"date": day(1), "recipe_id": "11111111-2222-3333-4444-555555555555"})
        self.assertEqual(cm.exception.status, 404)

    def test_assign_replaces_existing_entry_and_its_items(self):
        first = S.plan_assign({"date": day(1), "recipe_id": self.tid})["entry"]["id"]
        res = S.plan_assign({"date": day(1), "recipe_id": self.pid, "replace_id": first})
        self.assertEqual(res["replaced_removed"], 3)   # the old recipe's items go; the onion is reused for the new one
        plan = S.get_plans(S.today(), S.today() + timedelta(days=3))
        self.assertEqual([(p["date"], p["recipe"]["id"]) for p in plan], [(day(1), self.pid)])
        onion = next(i for i in self.items() if i["food"] == "onion")
        self.assertEqual(onion["recipes"], ["Test Pasta"])
        self.assertEqual(self.texts(), ["1 lb spaghetti", "1 onion", "2 cups milk"])
        # assigning the same recipe again is a no-op
        again = S.plan_assign({"date": day(1), "recipe_id": self.pid})
        self.assertEqual((again["added"], again["entry"]["id"]), (0, res["entry"]["id"]))
        self.assertEqual(len(self.items()), 3)

    def test_move_and_swap_leave_the_list_alone(self):
        a = S.plan_assign({"date": day(1), "recipe_id": self.tid})["entry"]["id"]
        b = S.plan_assign({"date": day(2), "recipe_id": self.pid})["entry"]["id"]
        before = self.texts()
        self.assertEqual(S.plan_move({"id": a, "date": day(2), "swap_with": b}), {"ok": True, "swapped_with": b})
        self.assertEqual(S.plan_move({"id": a, "date": day(5)}), {"ok": True, "swapped_with": None})
        self.assertEqual(S.plan_move({"id": a, "date": day(5)}), {"ok": True, "swapped_with": None})
        plan = {p["id"]: p["date"] for p in S.get_plans(S.today(), S.today() + timedelta(days=7))}
        self.assertEqual(plan, {a: day(5), b: day(1)})
        self.assertEqual(self.texts(), before)
        for body, status in (({"id": 999999, "date": day(1)}, 404), ({"id": "1 OR 1", "date": day(1)}, 400),
                             ({"id": True, "date": day(1)}, 400), ({"id": a, "date": "tomorrow"}, 400)):
            with self.assertRaises(S.ApiError) as cm:
                S.plan_move(body)
            self.assertEqual(cm.exception.status, status, body)

    def test_delete_removes_only_items_no_other_day_needs(self):
        a = S.plan_assign({"date": day(1), "recipe_id": self.tid})["entry"]["id"]
        b = S.plan_assign({"date": day(3), "recipe_id": self.tid})["entry"]["id"]
        S.plan_assign({"date": day(2), "recipe_id": self.pid})
        tortillas = next(i for i in self.items() if i["food"] == "tortillas")
        self.assertEqual(tortillas["text"], "32 tortillas")
        # the same recipe is planned again within 30 days: nothing is removed
        res = S.plan_delete(a)
        self.assertEqual(res["removed"], 0)
        self.assertEqual(res["undo"], {"date": day(1), "recipe_id": self.tid, "entry_type": "dinner"})
        # bought items stay; shared items (onion) are unlinked, not deleted
        S.Handler.bought(None, S.ensure_list(), tortillas["id"], "bought", {"to_pantry": False})
        res = S.plan_delete(b)
        self.assertEqual(res["removed"], 2)   # chicken + cheese
        # the shared onion loses exactly the tacos' share (2 + 2); only pasta's 1 is left. The bought tortillas
        # stay checked, so they're still shown (struck through) for a few hours.
        self.assertEqual(sorted(i["text"] for i in self.items() if not i["checked"]),
                         ["1 lb spaghetti", "1 onion", "2 cups milk"])
        self.assertEqual(next(i for i in self.items() if i["food"] == "onion")["recipes"], ["Test Pasta"])
        with S.db() as c:
            self.assertEqual(c.execute("SELECT checked FROM shopping_items WHERE id=?", (tortillas["id"],)).fetchone()[0], 1)
        with self.assertRaises(S.ApiError) as cm:
            S.plan_delete(b)
        self.assertEqual(cm.exception.status, 404)
        # Undo = assign again
        S.plan_assign(res["undo"])
        self.assertIn("2 lb chicken breast", self.texts())

    def test_far_future_plan_does_not_keep_items(self):
        a = S.plan_assign({"date": day(1), "recipe_id": self.pid})["entry"]["id"]
        S.plan_assign({"date": day(45), "recipe_id": self.pid})
        self.assertEqual(S.plan_delete(a)["removed"], 3)

    def test_readiness_counts_and_have_all(self):
        S.plan_assign({"date": day(1), "recipe_id": self.tid})
        entries = S.enrich_plan(S.get_plans(S.today(), S.today() + timedelta(days=2)))
        self.assertEqual(entries[0]["missing"], 4)
        detail = S.recipe_detail(self.tslug)
        self.assertEqual(sorted(m["text"] for m in detail["missing"]),
                         ["16 tortillas", "2 lb chicken breast", "2 onion, diced", "4 cups shredded cheddar cheese"])
        # "have" one item: checked; the food is now in the inventory (amount unknown)
        with S.db() as c:
            self.assertEqual(n_lists.mark_have(c, [detail["missing"][0]["id"]]), 1)
            S._have_to_pantry(c, [detail["missing"][0]["id"]])
            self.assertEqual(c.execute("SELECT count(*) FROM pantry_items").fetchone()[0], 1)
        self.assertEqual(len(S.recipe_detail(self.tslug)["missing"]), 3)
        self.assertEqual(S.recipe_have_all(self.tslug), {"ok": True, "count": 3})
        self.assertEqual(S.recipe_detail(self.tslug)["missing"], [])
        self.assertEqual(S.enrich_plan(S.get_plans(S.today(), S.today() + timedelta(days=2)))[0]["missing"], 0)
        self.assertEqual(S.recipe_have_all(self.tslug)["count"], 0)
        data = S.ongoing_list()   # checked in the last 4 hours: shown in place, labelled "have"
        self.assertEqual((len(data["recently_checked"]), data["count"]), (0, 0))
        self.assertTrue(all(i["checked"] and i["have"] for i in data["items"]))
        later = S.ongoing_list(now=datetime.now(S.timezone.utc) + timedelta(hours=5))
        self.assertEqual((len(later["recently_checked"]), later["items"]), (4, []))
        with S.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM pantry_items").fetchone()[0], 4)

    def test_plan_status(self):
        st = S.plan_status()
        self.assertEqual((st["planned_through"], st["days_left"], st["horizon_days"], st["reminder_days"]), (None, 0, 14, 3))
        S.plan_assign({"date": day(0), "recipe_id": self.tid})
        S.plan_assign({"date": day(4), "recipe_id": self.pid})
        st = S.plan_status()
        self.assertEqual((st["planned_through"], st["days_left"], st["planned_days"]), (day(4), 5, 2))

    def test_runout_reminder_sent_once(self):
        noon = datetime.combine(S.today(), datetime.min.time()).replace(hour=12)
        S.plan_assign({"date": day(1), "recipe_id": self.tid})
        S._app_url["url"] = "https://kitchen.example"
        with mock.patch.object(S, "channels_ready", return_value={"email": True, "telegram": False, "ntfy": False}), \
                mock.patch.object(S, "deliver") as deliver:
            msg = S.notify_plan_runout(noon)
            deliver.assert_called_once()
            weekday = (S.today() + timedelta(days=1)).strftime("%A")
            self.assertEqual(msg["subject"], f"🗓️ Your meal plan runs out {weekday}")
            self.assertIn("1 planned day left. 4 items on your shopping list.", msg["text"])
            self.assertIn("https://kitchen.example", msg["text"])
            self.assertIsNone(S.notify_plan_runout(noon))   # once per run-out
            self.assertEqual(deliver.call_count, 1)
            S.plan_assign({"date": day(2), "recipe_id": self.pid})   # extended: a new run-out date notifies again
            self.assertIsNotNone(S.notify_plan_runout(noon))
            S.save_settings({"plan_reminder_days": 0})
            S.plan_assign({"date": day(3), "recipe_id": self.pid})
            self.assertIsNone(S.notify_plan_runout(noon))
        with mock.patch.object(S, "channels_ready", return_value={"email": False, "telegram": False, "ntfy": False}):
            S.save_settings({"plan_reminder_days": 3})
            self.assertIsNone(S.notify_plan_runout(noon))

    def test_settings_validation(self):
        for k, v in (("plan_horizon_days", 6), ("plan_horizon_days", 29), ("plan_reminder_days", -1),
                     ("plan_reminder_days", 8), ("plan_horizon_days", True)):
            with self.assertRaises(S.ApiError):
                S.save_settings({k: v})
        out = S.save_settings({"plan_horizon_days": 21, "plan_reminder_days": 0})
        self.assertEqual((out["plan_horizon_days"], out["plan_reminder_days"]), (21, 0))
        S.save_settings({"plan_horizon_days": 14, "plan_reminder_days": 3})


class StoresAndList(Base):
    def test_single_list_merge(self):
        with S.db() as c:
            keep = n_lists.single_list(c)
            other = n_lists.create_list(c, "Costco run")
            n_lists.add_items(c, other, ["bananas"])
            n_lists.add_items(c, keep, ["apples"])
            self.assertEqual(n_lists.single_list(c), keep)
            self.assertEqual([l["id"] for l in n_lists.list_lists(c)], [keep])
        self.assertEqual(self.texts(), ["apples", "bananas"])
        self.assertEqual([l["id"] for l in S.get_lists()], [keep])
        self.assertEqual(S.ensure_list("someone-else"), keep)

    def test_store_memory_and_replace(self):
        with S.db() as c:
            stores = n_lists.list_stores(c)
        self.assertEqual([s["name"] for s in stores][:2], ["Aldi", "Costco"])
        aldi, costco = stores[0]["id"], stores[1]["id"]
        res = S.list_add({"items": ["2 cups milk", "  ", "eggs"]})
        self.assertEqual(res["added"], 2)
        milk = next(i for i in res["items"] if i["food"] == "milk")
        self.assertIsNone(milk["store_id"])
        with S.db() as c:
            it = n_lists.get_item(c, milk["id"])
            self.assertTrue(n_lists.set_item_store(c, milk["id"], costco, S._item_key(it)))
            self.assertRaises(KeyError, n_lists.set_item_store, c, milk["id"], "nope", "milk")
        # a new milk item (bought the old one) goes to Costco automatically, also from a recipe
        with S.db() as c:
            n_lists.mark_have(c, [milk["id"]])
        again = S.list_add({"items": ["1 gallon milk"]})["items"][0]
        self.assertEqual(again["store_id"], costco)
        # an explicit store wins; unknown stores are refused
        towels = S.list_add({"items": ["paper towels"], "store_id": aldi})["items"][0]
        self.assertEqual(towels["store_id"], aldi)
        with self.assertRaises(S.ApiError) as cm:
            S.list_add({"items": ["x"], "store_id": "missing"})
        self.assertEqual(cm.exception.status, 404)
        for bad in ({"items": "milk"}, {"items": []}, {"items": [5]}):
            with self.assertRaises(S.ApiError):
                S.list_add(bad)
        # list JSON shape
        data = S.ongoing_list()
        self.assertEqual(set(data), {"id", "name", "items", "recently_checked", "stores", "count"})
        self.assertEqual(set(data["items"][0]), {"id", "text", "name", "food", "qty", "emoji", "checked", "store_id",
                                                 "aisle", "recipes", "checked_at", "have", "uses", "manual"})
        self.assertEqual(data["stores"][0], {"id": aldi, "name": "Aldi"})
        # replace: ids kept, renamed, reordered; a removed store un-assigns its items and forgets its foods
        out = S.stores_replace([{"id": costco, "name": "Costco Wholesale"}, {"name": "Target"}])
        self.assertEqual([(s["name"], s["position"]) for s in out], [("Costco Wholesale", 0), ("Target", 1)])
        self.assertEqual(out[0]["id"], costco)
        self.assertIsNone(next(i for i in self.items() if i["id"] == towels["id"])["store_id"])
        for bad in ([{"name": ""}], [{"name": "x" * 41}], [{"name": "A"}, {"name": "a"}],
                    [{"name": f"s{i}"} for i in range(13)], "Aldi", [5]):
            with self.assertRaises(S.ApiError):
                S.stores_replace(bad)
        S.stores_replace({"stores": [{"id": costco, "name": "Costco"}, {"name": "Aldi"}]})
        self.assertEqual([s["name"] for s in S.ongoing_list()["stores"]], ["Costco", "Aldi"])

    def test_exports_group_by_store_then_aisle(self):
        with S.db() as c:
            costco = next(x["id"] for x in n_lists.list_stores(c) if x["name"] == "Costco")
        S.list_add({"items": ["2 onions", "paper towels"]})
        S.list_add({"items": ["2 cups milk"], "store_id": costco})
        sl = S.get_list(S.ensure_list())
        text = S.render_list_text(sl)
        self.assertLess(text.index("== Costco =="), text.index("== Any store =="))
        self.assertLess(text.index("DAIRY & EGGS"), text.index("== Any store =="))
        self.assertLess(text.index("HOUSEHOLD"), text.index("PRODUCE"))
        rows = S.render_list_csv(sl).splitlines()
        self.assertEqual(rows[0], "Store,Section,Item,Quantity,Unit,Food,Note")
        self.assertTrue(rows[1].startswith("Costco,Dairy & Eggs,2 cups milk"))
        S._req.nonce = "n"
        self.assertIn('<h3 class="store">Costco</h3>', S.print_list(sl))
        # without any store assignments, the old aisle-only layout
        with S.db() as c:
            c.execute("UPDATE shopping_items SET store_id=NULL")
        self.assertNotIn("==", S.render_list_text(S.get_list(S.ensure_list())))


class RecipeExport(Base):
    def setUp(self):
        super().setUp()
        (self.slug, self.rid), _ = Fixtures.recipes()
        S._req.nonce = "testnonce"

    def test_print_sizes(self):
        for size in ("letter", "a4"):
            out = S.print_recipe(self.slug, size, 4, "classic", True)
            self.assertIn(f"@page{{size:{S.PRINT_SIZES[size]['page']};", out, size)
            self.assertIn("minmax(0,2fr) minmax(0,3fr)", out)
            self.assertIn(f"min={S.PRINT_SIZES[size]['min']}", out)
        for size in ("card35", "card46", "card57", "half", "letter", "a4"):
            out = S.print_recipe(self.slug, size, 4, "classic", True)
            self.assertIn('<script nonce="testnonce">', out)
            self.assertNotIn(" onclick=", out)
            self.assertIn("2 lb chicken breast", out)   # 2 servings -> 4
            self.assertIn("TablePlan</span>", out)
            self.assertNotIn("<img", out)   # no photo on this recipe
        self.assertIn("<li>1 lb chicken breast</li>", S.print_recipe(self.slug, "letter", None))

    def test_print_cards_on_letter_with_cut_lines(self):
        dims = {"card35": ("5.0in", "3.0in", 3), "card46": ("6.0in", "4.0in", 2), "card57": ("7.0in", "5.0in", 2),
                "half": ("8.0in", "5.25in", 2)}
        for size, (w, h, per) in dims.items():
            out = S.print_recipe(self.slug, size, 4, "classic", True)
            self.assertIn("@page{size:letter;margin:0.25in}", out, size)
            self.assertIn(f".card{{position:relative;width:{w};height:{h};border:1px dashed #999;break-inside:avoid", out)
            self.assertIn("print-color-adjust:exact", out)
            self.assertIn(f"per={per};", out)
            self.assertIn("\u2702", out)   # scissors mark
            self.assertIn('<div class="b ing">2 lb chicken breast</div>', out)
            self.assertIn('<div class="b step"><span class="n">1.</span>', out)
            self.assertIn("Prints on Letter paper with dashed lines to cut out", out)
            self.assertIn("continued", out)
            self.assertGreaterEqual(S.PRINT_SIZES[size]["min"], 8)
        self.assertIn("@page{size:A4;", S.print_recipe(self.slug, "a4", None))

    def test_print_photo_steps_and_escaping(self):
        S.recipe_update(self.slug, {"description": "<b>bold</b>"})
        with mock.patch.object(S, "recipe_detail", wraps=S.recipe_detail) as rd:
            out = S.print_recipe(self.slug, "letter", None, "steps", True)
            self.assertTrue(rd.called)
        self.assertIn("Preheat", out)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", out)
        with mock.patch.object(S, "guided", side_effect=S.ApiError(500, "boom")):
            out = S.print_recipe(self.slug, "letter", None, "steps", True)
        self.assertIn("<li>Cook the chicken for 10 minutes.</li>", out)
        real = S.recipe_detail

        def with_image(slug):
            r = real(slug)
            r["has_image"] = True
            return r
        with mock.patch.object(S, "recipe_detail", side_effect=with_image):
            card = S.print_recipe(self.slug, "card46", None, "classic", True)
            self.assertIn(f'src="/img/{self.rid}?size=full"', card)
            self.assertIn(".photo{float:right;width:35%", card)
            self.assertNotIn("<img", S.print_recipe(self.slug, "card46", None, "classic", False))

    def test_text_markdown_json(self):
        txt = S.render_recipe_text(self.slug, 4)
        self.assertTrue(txt.startswith("Test Tacos\nServes 4 · 30 min\n"))
        self.assertIn("- 2 lb chicken breast\n", txt)
        self.assertIn("1. Cook the chicken for 10 minutes.", txt)
        md = S.render_recipe_md(self.slug)
        self.assertTrue(md.startswith("# Test Tacos\n"))
        self.assertIn("- 1 lb chicken breast", md)
        self.assertIn("## Steps", md)
        data = json.loads(S.render_recipe_json(self.slug, 6))
        self.assertEqual(data["recipeServings"], 6)
        self.assertEqual(data["recipeIngredient"][0]["display"], "3 lb chicken breast")
        self.assertEqual(data["id"], self.rid)
        self.assertEqual(json.loads(S.render_recipe_json(self.slug))["recipeIngredient"][0]["display"], "1 lb chicken breast")
        msg = S.build_msg({"kind": "recipe", "slug": self.slug, "servings": 4})
        self.assertEqual(msg["subject"], "🍳 Test Tacos")
        self.assertIn("2 lb chicken breast", msg["text"])
        self.assertIn("<li>2 lb chicken breast</li>", msg["html"])
        for bad in ({"kind": "recipe", "slug": "../x"}, {"kind": "recipe", "slug": self.slug, "servings": -2},
                    {"kind": "recipe", "slug": self.slug, "servings": "lots"}):
            with self.assertRaises(S.ApiError):
                S.build_msg(bad)


class Backups(Base):
    def test_backup_rotation_and_permissions(self):
        os.makedirs(S.BACKUP_DIR, exist_ok=True)
        for f in os.listdir(S.BACKUP_DIR):
            os.remove(os.path.join(S.BACKUP_DIR, f))
        for i in range(20):
            open(os.path.join(S.BACKUP_DIR, f"tableplan-2025-01-{i + 1:02d}.db"), "w").close()
        for i in range(8):
            p = os.path.join(S.BACKUP_DIR, f"pre-0.{i}-to-0.{i + 1}.db")
            open(p, "w").close()
            os.utime(p, (time.time() - 1000 + i, time.time() - 1000 + i))
        open(os.path.join(S.BACKUP_DIR, "notes.txt"), "w").close()
        info = S.make_backup()
        self.assertEqual(info["name"], f"tableplan-{S.iso(S.today())}.db")
        names = sorted(os.listdir(S.BACKUP_DIR))
        daily = [n for n in names if n.startswith("tableplan-")]
        pre = [n for n in names if n.startswith("pre-")]
        self.assertEqual(len(daily), 14)
        self.assertEqual(daily[-1], info["name"])
        self.assertNotIn("tableplan-2025-01-06.db", daily)
        self.assertEqual(sorted(pre), [f"pre-0.{i}-to-0.{i + 1}.db" for i in range(3, 8)])
        self.assertIn("notes.txt", names)
        p = os.path.join(S.BACKUP_DIR, info["name"])
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)
        with sqlite3.connect(p) as c:
            self.assertGreater(c.execute("SELECT count(*) FROM shelf_rules").fetchone()[0], 0)
        listed = S.list_backups()
        self.assertEqual({b["name"] for b in listed}, set(daily) | set(pre))
        self.assertEqual(set(listed[0]), {"name", "size", "created"})
        self.assertEqual(S.storage_info()["backups"], 19)

    def test_backup_names_are_strictly_validated(self):
        S.make_backup()
        good = f"tableplan-{S.iso(S.today())}.db"
        self.assertTrue(S.backup_path(good).endswith(good))
        os.symlink(S.DB_PATH, os.path.join(S.BACKUP_DIR, "link.db"))
        try:
            for bad in ("../tableplan.db", "..%2Ftableplan.db", "/etc/passwd", "tableplan.db", ".hidden.db", "..db",
                        "a/b.db", "x.txt", "", "missing.db", "link.db", "a\x00.db", None):
                with self.assertRaises(S.ApiError, msg=repr(bad)) as cm:
                    S.backup_path(bad)
                self.assertEqual(cm.exception.status, 404)
        finally:
            os.remove(os.path.join(S.BACKUP_DIR, "link.db"))

    def test_pre_upgrade_snapshot(self):
        S.set_internal("last_run_version", "0.4.2")
        with mock.patch.object(S, "APP_VERSION", "0.5.0"):
            name = S.pre_upgrade_snapshot()
            self.assertEqual(name, "pre-0.4.2-to-0.5.0.db")
            self.assertTrue(os.path.isfile(os.path.join(S.BACKUP_DIR, name)))
            S.set_internal("last_run_version", "0.5.0")
            self.assertIsNone(S.pre_upgrade_snapshot())

    def test_zip_has_db_and_images(self):
        img = os.path.join(S.IMG_DIR, "recipes", "abc")
        os.makedirs(img, exist_ok=True)
        with open(os.path.join(img, "original.jpg"), "wb") as f:
            f.write(b"\xff\xd8\xffdata")
        f, size = S.build_backup_zip()
        with f:
            self.assertGreater(size, 0)
            z = zipfile.ZipFile(f)
            self.assertIn("tableplan.db", z.namelist())
            self.assertIn("images/recipes/abc/original.jpg", z.namelist())
        self.assertFalse([n for n in os.listdir(S.BACKUP_DIR) if n.startswith(".snap-")])
        with mock.patch.object(S, "ZIP_CAP", 10):
            with self.assertRaises(S.ApiError) as cm:
                S.build_backup_zip()
            self.assertEqual(cm.exception.status, 413)

    def test_integrity_and_persistence(self):
        self.assertEqual(S.integrity_check(), "ok")
        info = S.storage_info()
        self.assertEqual(set(info), {"persistent", "last_backup", "backups", "integrity", "data_dir"})
        self.assertEqual(info["integrity"], "ok")
        with mock.patch.object(S.os.path, "exists", return_value=False), mock.patch.object(S, "ON_RAILWAY", False):
            self.assertTrue(S.storage_persistent())
        real_stat = os.stat
        with mock.patch.object(S, "ON_RAILWAY", True), \
                mock.patch.object(S.os, "stat", side_effect=lambda p: real_stat("/")), \
                mock.patch("builtins.open", mock.mock_open(read_data="overlay / overlay rw 0 0\n")):
            self.assertFalse(S.storage_persistent())
        with mock.patch.object(S, "ON_RAILWAY", True), \
                mock.patch.object(S.os, "stat", side_effect=lambda p: real_stat("/")), \
                mock.patch("builtins.open", mock.mock_open(read_data=f"/dev/sdb1 {os.path.realpath(S.DATA_DIR)} ext4 rw 0 0\n")):
            self.assertTrue(S.storage_persistent())


class HttpRoutes(Base):
    """New routes over HTTP: CSRF header, auth in public mode, and the contract shapes."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = S.Server(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        h = {"X-TablePlan": "1"} if method != "GET" else {}
        h.update(headers or {})
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
        r = c.getresponse()
        out = (r.status, dict(r.getheaders()), r.read())
        c.close()
        return out

    def test_versioned_assets_and_no_store_index(self):
        st, h, body = self.req("GET", "/")
        v = S.urllib.parse.quote(S.APP_VERSION, safe="")
        self.assertEqual((st, h.get("Cache-Control")), (200, "no-store"))
        for a in S.VERSIONED_ASSETS:
            self.assertIn(f'"/static/{a}?v={v}"'.encode(), body)
        st, h, _ = self.req("GET", f"/static/app.js?v={v}")
        self.assertEqual((st, h.get("Cache-Control")), (200, "public, max-age=31536000, immutable"))
        self.assertEqual(self.req("GET", "/static/app.js?v=0.0.1")[1].get("Cache-Control"), "no-cache")
        self.assertEqual(self.req("GET", "/static/app.js")[1].get("Cache-Control"), "no-cache")

    def test_contract_over_http(self):
        (tslug, tid), _ = Fixtures.recipes()
        st, _, body = self.req("POST", "/api/plan/assign", {"date": day(1), "recipe_id": tid})
        self.assertEqual(st, 200)
        res = json.loads(body)
        self.assertEqual(set(res) >= {"entry", "added", "skipped"}, True)
        st, _, body = self.req("GET", f"/api/plan?start={day(0)}&end={day(3)}")
        e = json.loads(body)["entries"][0]
        self.assertTrue({"id", "date", "entry_type", "scale", "recipe", "missing"} <= set(e))
        self.assertTrue({"id", "name", "slug", "has_image", "image_v", "minutes"} <= set(e["recipe"]))
        self.assertEqual(json.loads(self.req("GET", "/api/plan/status")[2])["planned_through"], day(1))
        items = json.loads(self.req("GET", "/api/list")[2])["items"]
        iid = items[0]["id"]
        stores = json.loads(self.req("GET", "/api/stores")[2])
        st, _, body = self.req("PATCH", f"/api/list/items/{iid}", {"store_id": stores[0]["id"]})
        self.assertEqual((st, json.loads(body)["item"]["store_id"]), (200, stores[0]["id"]))
        st, _, body = self.req("PATCH", f"/api/list/items/{iid}", {"checked": True, "to_pantry": True})
        self.assertEqual(st, 200)
        self.assertIsNotNone(json.loads(body)["pantry_item"])
        self.assertEqual(self.req("POST", f"/api/list/items/{items[1]['id']}/have")[0], 200)
        self.assertEqual(self.req("POST", "/api/list/items/nope/have")[0], 404)
        self.assertEqual(self.req("POST", f"/api/recipe/{tslug}/have-all")[0], 200)
        self.assertEqual(self.req("PUT", "/api/stores", [{"id": stores[0]["id"], "name": "Aldi"}])[0], 200)
        self.assertEqual(self.req("POST", "/api/list/items", {"items": ["bread"]})[0], 200)
        self.assertEqual(self.req("PATCH", f"/api/list/items/{iid}", {"text": "x"}, headers={"X-TablePlan": "0"})[0], 403)
        st, _, body = self.req("DELETE", f"/api/plan/{res['entry']['id']}")
        self.assertEqual(set(json.loads(body)), {"ok", "removed", "undo"})
        st, hdrs, body = self.req("GET", f"/print/recipe/{tslug}?size=card46&servings=3&auto=1")
        self.assertEqual(st, 200)
        self.assertIn("'nonce-", hdrs["Content-Security-Policy"])
        self.assertEqual(self.req("GET", f"/print/recipe/{tslug}?size=poster")[0], 400)
        st, hdrs, _ = self.req("GET", f"/export/recipe/{tslug}.md")
        self.assertEqual(hdrs["Content-Disposition"], 'attachment; filename="test-tacos.md"')
        st, _, body = self.req("POST", "/api/backups")
        name = json.loads(body)["backup"]["name"]
        self.assertIn(name, [b["name"] for b in json.loads(self.req("GET", "/api/backups")[2])])
        st, hdrs, body = self.req("GET", f"/backups/{name}")
        self.assertEqual((st, hdrs["Content-Type"]), (200, "application/octet-stream"))
        self.assertTrue(body.startswith(b"SQLite format 3"))
        for bad in ("..%2Ftableplan.db", "%2e%2e%2ftableplan.db", "tableplan.db", "x.txt"):
            self.assertEqual(self.req("GET", f"/backups/{bad}")[0], 404, bad)
        st, hdrs, body = self.req("GET", "/export/backup.zip")
        self.assertEqual((st, hdrs["Content-Type"]), (200, "application/zip"))
        self.assertTrue(body.startswith(b"PK"))
        storage = json.loads(self.req("GET", "/api/config")[2])["storage"]
        self.assertEqual(storage["integrity"], "ok")

    def test_public_mode_requires_sign_in(self):
        with mock.patch.object(S, "PUBLIC_MODE", True):
            for path in ("/backups/tableplan-2026-01-01.db", "/export/backup.zip", "/print/recipe/x",
                         "/export/recipe/x.txt"):
                st, hdrs, _ = self.req("GET", path)
                self.assertEqual((st, hdrs.get("Location")), (302, "/"), path)
            for method, path in (("GET", "/api/list"), ("GET", "/api/stores"), ("GET", "/api/backups"),
                                 ("GET", "/api/plan/status"), ("POST", "/api/backups"), ("POST", "/api/plan/assign"),
                                 ("POST", "/api/plan/move"), ("PUT", "/api/stores"), ("PATCH", "/api/list/items/x"),
                                 ("POST", "/api/list/items/x/have"), ("POST", "/api/recipe/x/have-all")):
                self.assertEqual(self.req(method, path, {})[0], 401, path)


if __name__ == "__main__":
    unittest.main()
