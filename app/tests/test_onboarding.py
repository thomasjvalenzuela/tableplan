"""Onboarding: tour state per member (validation, snooze expiry), sample data added and wiped, checklist."""

import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-onboard-")
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
    S.set_cfg(people=2, setup_complete=True)


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


class Tour(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(S.clean_tour({"step": 3}), {"step": 3})
        self.assertEqual(S.clean_tour({"done": True, "skipped": True}), {"done": True, "skipped": True})
        self.assertIsNone(S.clean_tour(None))
        for bad in ({"step": 7}, {"step": -1}, {"done": "yes"}, {"snoozed_until": "soon"}, {"html": "<b>"}, ["x"], {"step": True}):
            with self.assertRaises(S.ApiError, msg=bad):
                S.clean_tour(bad)

    def test_due_and_snooze_expiry(self):
        now = int(time.time() * 1000)
        self.assertTrue(S.tour_due(None, now))
        self.assertTrue(S.tour_due({"step": 4}, now))                 # unfinished: picks up again
        self.assertFalse(S.tour_due({"done": True}, now))
        self.assertFalse(S.tour_due({"done": True, "skipped": True}, now))
        self.assertFalse(S.tour_due({"snoozed_until": now + S.TOUR_SNOOZE_MS}, now))
        self.assertTrue(S.tour_due({"snoozed_until": now + S.TOUR_SNOOZE_MS}, now + S.TOUR_SNOOZE_MS + 1))

    def test_per_member(self):
        with S.db() as c:
            a = S.n_users.create(c, "Ana", "", "password", "correct horse battery", False)
            b = S.n_users.create(c, "Ben", "", "password", "correct horse battery", False)
            S.n_users.put_state(c, a["id"], {"tour": S.clean_tour({"done": True})})
            now = int(time.time() * 1000)
            self.assertFalse(S.tour_due(S.n_users.get_state(c, a["id"]).get("tour"), now))
            self.assertTrue(S.tour_due(S.n_users.get_state(c, b["id"]).get("tour"), now))   # a new member still sees it


class Demo(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("recipes", "pantry_items"):
                c.execute(f"DELETE FROM {t}")

    def test_add_once_and_wipe_only_demo(self):
        mine = S.mealie("POST", "/api/recipes", {"name": "My Soup"})
        with S.db() as c:
            S.add_pantry_item(c, "butter", "fridge", None, "1 lb")
        out = S.demo_add()
        self.assertEqual((out["added"], out["items"]), (3, 6))
        self.assertTrue(S.demo_add()["already"])
        with S.db() as c:
            recs = [S.n_recipes.get(c, r["id"]) for r in c.execute("SELECT id FROM recipes")]
            self.assertEqual(sum(1 for r in recs if (r.get("extras") or {}).get("demo")), 3)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM pantry_items WHERE product='Demo'").fetchone()[0], 6)
        pasta = next(r for r in recs if r["name"] == "Sheet-Pan Lemon Chicken")
        self.assertEqual([t["name"] for t in pasta["tags"]], ["Demo"])
        S.danger_reset("demo", {"confirm": "Demo data"})
        with S.db() as c:
            self.assertEqual([r["slug"] for r in c.execute("SELECT slug FROM recipes")], [mine])
            self.assertEqual([r["name"] for r in c.execute("SELECT name FROM pantry_items")], ["butter"])


class Checklist(unittest.TestCase):
    def test_ai_item_ticks_with_a_key(self):
        self.assertIn("ai", [i for i, _, _ in S.CHECKLIST])
        self.assertNotIn("ai", S.checklist_auto(None))
        S.set_cfg(openai_key="sk-x")
        try:
            self.assertIn("ai", S.checklist_auto(None))
        finally:
            S.set_cfg(openai_key="")
