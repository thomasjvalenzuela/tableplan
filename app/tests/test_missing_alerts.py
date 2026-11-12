"""Missing-ingredient alerts: window timing (with the household time zone), the allocation ledger (other meals'
reservations, expired items, unreviewed scans), once per meal per window, nothing for cooked or removed meals."""

import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-missing-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import alerts as A  # noqa: E402

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
    S.set_cfg(people=2, scale_to_household=False, setup_complete=True)


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


D = date(2026, 11, 20)


class Windows(unittest.TestCase):
    def test_day_before_and_morning(self):
        start = datetime(2026, 11, 20, 17, 45)               # start cooking 17:45 to eat at 18:30
        self.assertEqual(A.due_windows(datetime(2026, 11, 19, 17, 30), D, start), [])
        self.assertEqual(A.due_windows(datetime(2026, 11, 19, 17, 45), D, start), ["day_before"])
        self.assertEqual(A.due_windows(datetime(2026, 11, 20, 7, 59), D, start), [])          # morning off-hours
        self.assertEqual(A.due_windows(datetime(2026, 11, 20, 8, 0), D, start), ["morning"])
        self.assertEqual(A.due_windows(datetime(2026, 11, 20, 9, 0), D, start, morning="10:30"), [])
        self.assertEqual(A.due_windows(datetime(2026, 11, 20, 18, 0), D, start), [])          # already cooking time
        self.assertEqual(A.due_windows(datetime(2026, 11, 19, 18, 0), D, None), ["day_before"])   # no time: 6 pm the day before
        self.assertEqual(A.due_windows(datetime(2026, 11, 19, 17, 0), D, None), [])
        self.assertEqual(A.due_windows(datetime(2026, 11, 20, 9, 0), D, start, morning_on=False), ["day_before"])
        self.assertEqual(A.due_windows(datetime(2026, 11, 19, 20, 0), D, start, day_before=False), [])

    def test_household_time_zone(self):
        S.save_settings({"budget": {"timezone": "Pacific/Kiritimati"}})
        east = S._local_now()
        S.save_settings({"budget": {"timezone": "Pacific/Pago_Pago"}})
        west = S._local_now()
        S.save_settings({"budget": {"timezone": ""}})
        self.assertAlmostEqual((east - west).total_seconds() / 3600, 25, delta=0.1)


def recipe(name, ings):
    slug = S.mealie("POST", "/api/recipes", {"name": name})
    S.recipe_update(slug, {"servings": 2, "ingredients": ings, "steps": ["Cook 10 minutes."]})
    S._recipe_cache["at"] = 0
    with S.db() as c:
        return S.n_recipes.get(c, slug)["id"]


class Ledger(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("meal_plans", "shopping_items", "pantry_items", "allocations", "recipes", "settings"):
                c.execute(f"DELETE FROM {t}" + (" WHERE key LIKE 'missing_%'" if t == "settings" else ""))
        S.save_settings({"missing_alert_daybefore": True, "missing_alert_morning": True, "missing_alert_time": "08:00",
                         "eat_times": {"breakfast": "08:00", "lunch": "12:30", "dinner": "18:30"}})
        self.tomorrow = S.today() + timedelta(days=1)

    def stock(self, name, text, **upd):
        with S.db() as c:
            pid = S.add_pantry_item(c, name, "fridge", None, text)
            for k, v in upd.items():
                c.execute(f"UPDATE pantry_items SET {k}=? WHERE id=?", (v, pid))
        return pid

    def plan(self, rid, et="dinner"):
        return S.plan_assign({"date": S.iso(self.tomorrow), "recipe_id": rid, "entry_type": et})["entry"]["id"]

    def run_alerts(self, at):
        with mock.patch.object(S, "channels_ready", return_value={"email": True}), mock.patch.object(S, "deliver") as d:
            sent = S.notify_missing(at)
        return sent, [c.args[0]["subject"] for c in d.call_args_list]

    def test_reservations_expired_and_scans(self):
        r1 = recipe("Scramble", ["6 eggs", "1 cup spinach"])
        r2 = recipe("Omelet", ["4 eggs", "1/2 cup cheddar cheese"])
        self.stock("eggs", "6")
        self.stock("spinach", "1 bag", expires_on=S.iso(S.today() - timedelta(days=1)))     # expired: doesn't count
        self.stock("Unknown item · 0852390000111", "", review=1)
        e1, e2 = self.plan(r1, "lunch"), self.plan(r2, "dinner")
        with S.db() as c:
            miss = S.planned_missing(self.tomorrow, self.tomorrow, c)
        self.assertEqual([m["food"] for m in miss[str(e1)]], ["spinach"])                   # eggs reserved for lunch
        self.assertEqual(sorted(m["food"] for m in miss[str(e2)]), ["cheddar cheese", "eggs"])   # dinner can't use them
        plan = S.enrich_plan(S.get_plans(self.tomorrow, self.tomorrow))
        self.assertEqual({e["id"]: e["missing"] for e in plan}, {e1: 1, e2: 2})

    def test_once_per_window_and_suppression(self):
        rid = recipe("Garlic Pasta", ["8 oz spaghetti", "4 cloves garlic", "1 cup heavy cream", "1 tsp salt"])
        self.stock("spaghetti", "1 lb")
        eid = self.plan(rid)
        evening = datetime.combine(S.today(), datetime.min.time()).replace(hour=19)
        sent, subjects = self.run_alerts(evening)
        self.assertEqual(subjects, ["🛒 Tomorrow's Garlic Pasta is missing 2 items"])        # salt is an "always have"
        self.assertEqual(self.run_alerts(evening + timedelta(hours=1))[1], [])                # once per window
        morning = datetime.combine(self.tomorrow, datetime.min.time()).replace(hour=8, minute=5)
        self.assertEqual(self.run_alerts(morning)[1], ["🛒 Tonight's Garlic Pasta is missing 2 items"])
        with S.db() as c:
            c.execute("DELETE FROM settings WHERE key LIKE 'missing_morning_%'")
            c.execute("UPDATE meal_plans SET cooked_at=? WHERE id=?", (S.iso(S.today()), eid))
        self.assertEqual(self.run_alerts(morning)[1], [])                                    # cooked: nothing
        with S.db() as c:
            c.execute("DELETE FROM settings WHERE key LIKE 'missing_morning_%'")
            c.execute("DELETE FROM meal_plans WHERE id=?", (eid,))
        self.assertEqual(self.run_alerts(morning)[1], [])                                    # removed: nothing

    def test_off_and_bought(self):
        rid = recipe("Toast", ["2 slices bread", "1 tbsp butter"])
        eid = self.plan(rid)
        S.save_settings({"missing_alert_daybefore": False, "missing_alert_morning": False})
        self.assertEqual(self.run_alerts(datetime.combine(S.today(), datetime.min.time()).replace(hour=19))[1], [])
        S.save_settings({"missing_alert_daybefore": True})
        with S.db() as c:   # buying everything on the list covers the meal
            lid = S.n_lists.single_list(c)
            for r in c.execute("SELECT id FROM shopping_items WHERE list_id=?", (lid,)).fetchall():
                S.n_lists.set_checked(c, lid, r["id"], True)
            self.assertEqual(S.planned_missing(self.tomorrow, self.tomorrow, c)[str(eid)], [])
