"""Prices and budget: unit prices, partial packages, source precedence and staleness, AI results without a cited page
dropped, budget periods across time zones, waste, the Kroger and BLS clients, and costs on recipes, lists and plans."""

import json
import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

_TMP = tempfile.mkdtemp(prefix="tableplan-prices-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import prices as P  # noqa: E402
from app.native import units as U  # noqa: E402

_PATCHES = []
T = date(2026, 11, 18)


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


def rec(source, price, qty, unit, days_ago=0, **kw):
    up, base = P.unit_price(price, qty, unit, U.convert, U.dimension)
    return {"source": source, "price": price, "qty": qty, "unit": unit, "unit_price": up, "base": base,
            "observed_on": (T - timedelta(days=days_ago)).isoformat(), **kw}


class UnitPrices(unittest.TestCase):
    def test_normalized_to_grams_millilitres_or_each(self):
        up, base = P.unit_price(3.99, 1, "gallon", U.convert, U.dimension)
        self.assertEqual(base, "ml")
        self.assertAlmostEqual(up * 3785.41, 3.99, places=4)
        up, base = P.unit_price(2.50, 1, "lb", U.convert, U.dimension)
        self.assertEqual(base, "g")
        self.assertAlmostEqual(up * 453.592, 2.50, places=3)
        self.assertEqual(P.unit_price(4.20, 1, "dozen", U.convert, U.dimension), (0.35000000000000003, "each"))
        self.assertEqual(P.unit_price(0, 1, "lb", U.convert, U.dimension), (None, None))
        self.assertEqual(S._pack_of("12 × 355 ml"), (4260.0, "ml"))

    def test_parse_money(self):
        self.assertEqual(P.parse_money("$3.49"), 3.49)
        self.assertEqual(P.parse_money("2 for $5"), 2.5)
        self.assertIsNone(P.parse_money("call for price"))


class Precedence(unittest.TestCase):
    def test_best_source_first_fresh_before_stale(self):
        recs = [rec("bls", 3.00, 1, "gallon"), rec("manual", 3.50, 1, "gallon", 10), rec("receipt", 3.79, 1, "gallon", 30)]
        self.assertEqual(P.best(recs, T)["source"], "receipt")
        recs[2] = rec("receipt", 3.79, 1, "gallon", 200)   # stale receipt: a fresh price you set wins
        self.assertEqual(P.best(recs, T)["source"], "manual")
        stale = [rec("bls", 3.0, 1, "gallon", 400), rec("receipt", 3.79, 1, "gallon", 300)]
        self.assertEqual(P.best(stale, T)["source"], "receipt")   # all stale: still the best source
        self.assertTrue(P.approx(P.best(stale, T), T))
        self.assertFalse(P.approx(rec("receipt", 1, 1, "lb"), T))
        self.assertTrue(P.approx(rec("ai", 1, 1, "lb"), T))
        newer = [rec("receipt", 4.0, 1, "gallon", 40), rec("receipt", 3.5, 1, "gallon", 2)]
        self.assertEqual(P.best(newer, T)["price"], 3.5)

    def test_base_must_match(self):
        recs = [rec("receipt", 2.0, 1, "lb")]
        self.assertIsNone(P.cost_used(1, "cup", recs, T, U.convert, U.dimension))   # a cup can't be priced from pounds


class Packages(unittest.TestCase):
    def test_partial_package_and_whole_packages_to_buy(self):
        milk = [rec("receipt", 3.99, 1, "gallon")]
        used = P.cost_used(1, "cup", milk, T, U.convert, U.dimension)
        self.assertAlmostEqual(used["cost"], 3.99 * 236.588 / 3785.41, places=3)
        buy = P.cost_to_buy(1, "cup", milk, T, U.convert, U.dimension)
        self.assertEqual((buy["cost"], buy["packages"]), (3.99, 1))
        buy = P.cost_to_buy(1.5, "gallon", milk, T, U.convert, U.dimension)
        self.assertEqual((buy["cost"], buy["packages"]), (7.98, 2))
        eggs = [rec("receipt", 4.20, 12, "")]
        self.assertEqual(P.cost_to_buy(14, "", eggs, T, U.convert, U.dimension)["packages"], 2)
        self.assertAlmostEqual(P.cost_used(3, "", eggs, T, U.convert, U.dimension)["cost"], 1.05)


class AIResults(unittest.TestCase):
    def res(self, data, cited):
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(data),
                "annotations": [{"type": "url_citation", "url": u} for u in cited]}]}]}

    def test_only_cited_pages_with_price_and_size(self):
        good = {"price": "$3.49", "size": "1 gal", "url": "https://shop.example/milk", "store": "Shop"}
        self.assertEqual(S._ai_price_result(self.res(good, ["https://www.shop.example/milk/"])),
                         (3.49, 1.0, "gallon", "https://shop.example/milk", "Shop"))
        self.assertIsNone(S._ai_price_result(self.res(good, [])))                                  # page never cited
        self.assertIsNone(S._ai_price_result(self.res({**good, "url": ""}, ["https://shop.example/milk"])))
        self.assertIsNone(S._ai_price_result(self.res({**good, "size": "family size"}, ["https://shop.example/milk"])))
        self.assertIsNone(S._ai_price_result(self.res({**good, "price": "see store"}, ["https://shop.example/milk"])))


class Periods(unittest.TestCase):
    def test_time_zone_decides_the_day(self):
        moment = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)   # Monday 03:00 UTC = Sunday evening in Los Angeles
        self.assertEqual(P.local_today(moment, ZoneInfo("America/Los_Angeles")), date(2026, 11, 15))
        self.assertEqual(P.local_today(moment, ZoneInfo("Asia/Tokyo")), date(2026, 11, 16))
        la = P.local_today(moment, ZoneInfo("America/Los_Angeles"))
        self.assertEqual(P.period_bounds("week", la, "mon"), (date(2026, 11, 9), date(2026, 11, 15)))
        self.assertEqual(P.period_bounds("week", la, "sun"), (date(2026, 11, 15), date(2026, 11, 21)))

    def test_months_and_history(self):
        self.assertEqual(P.period_bounds("month", date(2026, 12, 31)), (date(2026, 12, 1), date(2026, 12, 31)))
        self.assertEqual(P.period_bounds("month", date(2028, 2, 10)), (date(2028, 2, 1), date(2028, 2, 29)))
        h = P.previous_periods("month", date(2026, 1, 15), 3)
        self.assertEqual([s for s, _ in h], [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1)])
        self.assertEqual([P.budget_level(x, 100) for x in (79, 80, 99.9, 100, 150)], ["", "warn", "warn", "over", "over"])
        self.assertEqual(P.budget_level(50, 0), "")


class Waste(unittest.TestCase):
    def test_value_of_what_was_tossed(self):
        self.assertEqual(P.waste_value(0.5, 4.0, [], None, "", T, U.convert, U.dimension), (2.0, False))
        v, ap = P.waste_value(0.5, None, [rec("receipt", 3.0, 1, "lb")], 2, "lb", T, U.convert, U.dimension)
        self.assertAlmostEqual(v, 3.0)
        self.assertFalse(ap)
        self.assertEqual(P.waste_value(0, 4.0, [], None, "", T, U.convert, U.dimension), (0.0, False))
        self.assertEqual(P.waste_value(1, None, [], None, "", T, U.convert, U.dimension), (0.0, True))   # never invented


class Clients(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            c.execute("DELETE FROM prices")
            c.execute("DELETE FROM settings WHERE key='prices_bls_at'")

    def test_bls_saves_series_and_skips_empty(self):
        res = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
            {"seriesID": "APU0000709112", "data": [{"year": "2026", "period": "M09", "periodName": "September", "value": "4.112"}]},
            {"seriesID": "APU0000708111", "data": []},
            {"seriesID": "NOTOURS", "data": [{"year": "2026", "period": "M09", "value": "9"}]}]}}
        with mock.patch.object(S, "_https_json", return_value=res) as h:
            self.assertEqual(S.bls_refresh(), 1)
        self.assertIn("APU0000709112", json.dumps(h.call_args.kwargs["payload"]))
        with S.db() as c:
            r = c.execute("SELECT * FROM prices WHERE source='bls'").fetchone()
        self.assertEqual((r["name"], r["price"], r["observed_on"]), ("Whole milk", 4.112, "2026-09-01"))

    def test_kroger_token_and_product_price(self):
        S.set_cfg(kroger_client_id="id", kroger_client_secret="sec", kroger_location_id="0123", kroger_location_name="Kroger Main St")
        S._kroger_token.update(token="", until=0)
        calls = []

        def fake(url, **kw):
            calls.append(url)
            if "oauth2/token" in url:
                self.assertTrue(kw["headers"]["Authorization"].startswith("Basic "))
                return {"access_token": "tok", "expires_in": 1800}
            self.assertEqual(kw["headers"]["Authorization"], "Bearer tok")
            if "/locations" in url:
                return {"data": [{"locationId": "0123", "chain": "KROGER", "name": "Main St", "address": {"addressLine1": "1 Main", "city": "Town"}}]}
            return {"data": [{"productId": "0001", "description": "Kroger Whole Milk", "items": [{"size": "1 gal", "price": {"regular": 3.49, "promo": 0}}]}]}
        try:
            with mock.patch.object(S, "_https_json", side_effect=fake):
                self.assertEqual(S.kroger_locations("45202")["locations"][0]["id"], "0123")
                self.assertEqual(S.kroger_price("whole milk"), (3.49, 1.0, "gallon", "https://www.kroger.com/p/-/0001", "Kroger Whole Milk"))
            self.assertEqual(sum("oauth2" in u for u in calls), 1)   # the token is reused
            with self.assertRaises(S.ApiError):
                S.kroger_locations("abc")
        finally:
            S.set_cfg(kroger_client_id="", kroger_client_secret="", kroger_location_id="", kroger_location_name="")
            S._kroger_token.update(token="", until=0)


def recipe(name, servings, ings):
    slug = S.mealie("POST", "/api/recipes", {"name": name})
    S.recipe_update(slug, {"servings": servings, "ingredients": ings, "steps": ["Cook."]})
    S._recipe_cache["at"] = 0
    return slug


class Costs(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("prices", "purchases", "trips", "pantry_items", "shopping_items", "meal_plans", "recipes", "diary"):
                c.execute(f"DELETE FROM {t}")
        S._cost_cache["at"] = 0
        S.save_settings({"budget": {"period": "week", "amount": 0}})

    def buy(self, name, price, qty, unit, store="Aldi", d=None, total=None, store_id=None):
        with S.db() as c:
            tid = c.execute("INSERT INTO trips(store_id, store_name, date, method, total, created_at) VALUES (?,?,?,?,?,?)",
                            (store_id, store, S.iso(d or S.today()), "receipt", total, "x")).lastrowid
            fid = S._food_id(c, name)
            c.execute("INSERT INTO purchases(trip_id, store_name, date, food_id, name, qty, unit, price) VALUES (?,?,?,?,?,?,?,?)",
                      (tid, store, S.iso(d or S.today()), fid, name, qty, unit, price))
        return tid

    def test_recipe_cost_and_need_to_buy(self):
        self.buy("whole milk", 3.99, 1, "gallon")
        self.buy("eggs", 4.20, 12, "")
        S.price_set({"food": "cheddar cheese", "price": "5.00", "size": "8 oz"})
        slug = recipe("Omelet", 2, ["4 eggs", "1/2 cup whole milk", "2 oz cheddar cheese", "1 tbsp chives"])
        out = S.recipe_cost_api(slug, {})
        self.assertAlmostEqual(out["total"], round(1.40 + 3.99 * 118.294 / 3785.41 + 1.25, 2), places=2)
        self.assertAlmostEqual(out["per_serving"], round(out["total"] / 2, 2), places=2)
        self.assertEqual(out["unpriced"], ["chives"])
        self.assertTrue(out["approx"])
        self.assertAlmostEqual(out["to_buy"]["total"], 4.20 + 3.99 + 5.00, places=2)   # nothing at home: whole packages
        doubled = S.recipe_cost_api(slug, {"servings": "4"})
        self.assertAlmostEqual(doubled["total"], out["total"] * 2, delta=0.02)

    def test_list_totals_per_store_and_unpriced(self):
        with S.db() as c:
            stores = S.n_lists.replace_stores(c, [{"name": "Aldi"}, {"name": "Costco"}])
        aldi = stores[0]["id"]
        self.buy("whole milk", 3.99, 1, "gallon")
        S.list_add({"items": ["2 gallons whole milk", "1 bag mystery snack"], "store_id": aldi})
        out = S.list_costs()
        self.assertEqual(out["total"], 7.98)
        self.assertEqual(out["unpriced"], 1)
        self.assertEqual([(s["name"], s["total"]) for s in out["stores"]], [("Aldi", 7.98)])

    def test_budget_spending_and_waste(self):
        S.save_settings({"budget": {"period": "month", "amount": 100, "week_start": "mon"}})
        self.buy("whole milk", 3.99, 1, "gallon", total=85.0)
        self.buy("bread", 3.00, 1, "lb", d=S.today() - timedelta(days=70))
        st = S.budget_status()
        self.assertEqual((st["spent"], st["level"], st["left"]), (85.0, "warn", 15.0))
        with S.db() as c:
            pid = S.add_pantry_item(c, "whole milk", "fridge", None, "1 gallon")
            c.execute("UPDATE pantry_items SET status='tossed', finished_on=?, amount_left=0.5 WHERE id=?", (S.iso(S.today()), pid))
        sp = S.spending({"by": "month", "n": "3"})
        self.assertEqual(sp["periods"][-1]["spent"], 85.0)
        self.assertEqual(sp["stores"][0]["name"], "Aldi")
        self.assertAlmostEqual(sp["waste"]["total"], 2.0, places=1)
        self.assertTrue(any(c_["total"] == 3.99 for c_ in sp["categories"]))

    def test_almost_there_shows_cost_to_complete(self):
        self.buy("butter", 4.50, 1, "lb")
        recipe("Buttered Eggs", 1, ["2 eggs", "1 tbsp butter"])
        with S.db() as c:
            S.add_pantry_item(c, "eggs", "fridge", None, "12")
        out = S.what_can_i_make()
        self.assertEqual(out["almost"][0]["to_buy"]["total"], 4.5)

    def test_refresh_saves_kroger_and_respects_ai_switch(self):
        S.set_cfg(kroger_client_id="id", kroger_client_secret="s", kroger_location_id="1", kroger_location_name="Kroger")
        S.list_add({"items": ["whole milk"]})
        try:
            with mock.patch.object(S, "kroger_price", return_value=(3.29, 1.0, "gallon", "https://www.kroger.com/p/-/1", "Milk")), \
                    mock.patch.object(S, "bls_refresh", return_value=0), mock.patch.object(S, "ai_price") as ai:
                S.prices_refresh(force=True)
            ai.assert_not_called()   # AI estimates are off unless switched on
            with S.db() as c:
                r = c.execute("SELECT * FROM prices WHERE source='kroger'").fetchone()
            self.assertEqual((r["price"], r["store"]), (3.29, "Kroger"))
        finally:
            S.set_cfg(kroger_client_id="", kroger_client_secret="", kroger_location_id="", kroger_location_name="")

    def test_manual_price_validation(self):
        with self.assertRaises(S.ApiError):
            S.price_set({"food": "milk"})
        with self.assertRaises(S.ApiError):
            S.save_settings({"budget": {"period": "fortnight"}})
        with self.assertRaises(S.ApiError):
            S.save_settings({"budget": {"timezone": "Mars/Base"}})
