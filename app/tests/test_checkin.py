"""Kitchen check-in: when it's due, which items are asked about (and why), answers with Undo, and learning how fast
food goes."""

import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-checkin-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import checkin as K  # noqa: E402

_PATCHES = []
T = date(2026, 11, 18)   # a Wednesday


def setUpModule():
    for name, value in (("DATA_DIR", _TMP), ("DB_PATH", os.path.join(_TMP, "tableplan.db")),
                        ("IMG_DIR", os.path.join(_TMP, "images")), ("BACKUP_DIR", os.path.join(_TMP, "backups")),
                        ("NATIVE", True), ("PUBLIC_MODE", False)):
        p = mock.patch.object(S, name, value)
        p.start()
        _PATCHES.append(p)
    S.init_db()
    S.load_cfg()


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


def item(i, **kw):
    base = {"id": i, "name": f"item{i}", "purchased_on": (T - timedelta(days=2)).isoformat(), "expires_on": None,
            "amount_left": 1.0, "location": "fridge", "key": f"k{i}"}
    return {**base, **kw}


class Due(unittest.TestCase):
    def test_sunday_evening_weekly_and_fortnightly(self):
        sun_5pm, sun_7pm = datetime(2026, 11, 15, 17), datetime(2026, 11, 15, 19)
        last = datetime(2026, 11, 8, 19)
        self.assertFalse(K.is_due(sun_5pm, last, 7))          # not yet 6 pm
        self.assertTrue(K.is_due(sun_7pm, last, 7))
        self.assertTrue(K.is_due(datetime(2026, 11, 17, 9), last, 7))   # still due on Tuesday
        self.assertFalse(K.is_due(sun_7pm, datetime(2026, 11, 15, 18, 30), 7))   # done this evening
        self.assertFalse(K.is_due(sun_7pm, last, 14))         # every 2 weeks: last one was a week ago
        self.assertTrue(K.is_due(datetime(2026, 11, 22, 19), last, 14))
        self.assertFalse(K.is_due(sun_7pm, last, 0))           # off
        self.assertEqual(K.last_slot(datetime(2026, 11, 18, 10), "sun", 18), datetime(2026, 11, 15, 18))

    def test_status_uses_settings(self):
        S.save_settings({"pantry_check_days": 7, "checkin_day": "sun", "checkin_hour": 18})
        S.set_internal("pantry_checked_at", "2026-11-08T19:00:00")
        self.assertTrue(S.pantry_checkin_status(datetime(2026, 11, 15, 19))["due"])
        S.set_internal("pantry_checked_at", "2026-11-15")      # an old date-only value counts as that evening
        self.assertFalse(S.pantry_checkin_status(datetime(2026, 11, 15, 19))["due"])


class Picks(unittest.TestCase):
    def test_reasons_and_order(self):
        items = [item(1, expires_on=(T - timedelta(days=1)).isoformat()),
                 item(2, opened_on=(T - timedelta(days=9)).isoformat(), expiry_source="opened", expires_on=(T - timedelta(days=2)).isoformat()),
                 item(3, expires_on=(T + timedelta(days=1)).isoformat()),
                 item(4, amount_left=0.2),
                 item(5, name="Milk", key="milk", purchased_on=(T - timedelta(days=8)).isoformat()),
                 item(6, purchased_on=(T - timedelta(days=40)).isoformat()),
                 item(7, purchased_on=(T - timedelta(days=40)).isoformat(), location="freezer"),
                 item(8),
                 item(9, review=1, amount_left=0.1)]
        out = K.candidates(items, T, cadences={"milk": 7})
        ids = [x["id"] for x in out]
        self.assertEqual(ids[:2], [1, 2] if out[0]["id"] == 1 else [2, 1])
        self.assertEqual(set(ids), {1, 2, 3, 4, 5, 6})        # fresh, frozen and unknown scans aren't asked
        why = {x["id"]: x["reason"] for x in out}
        self.assertIn("Past its use-by", why[1])
        self.assertIn("Opened 9 days ago", why[2])
        self.assertEqual(why[3], "Use by tomorrow")
        self.assertEqual(why[4], "Running low last time")
        self.assertEqual(why[5], "You usually buy milk every ~7 days")
        self.assertEqual(why[6], "Not touched in 5 weeks")

    def test_limit_and_quiet_period(self):
        items = [item(i, amount_left=0.1) for i in range(1, 15)]
        self.assertEqual(len(K.candidates(items, T)), 10)
        out = K.candidates(items[:2], T, last_asked={1: (T - timedelta(days=2)).isoformat()})
        self.assertEqual([x["id"] for x in out], [2])

    def test_learned_rate_beats_cadence(self):
        out = K.candidates([item(1, name="Milk", key="milk", purchased_on=(T - timedelta(days=6)).isoformat())], T,
                           cadences={"milk": 7}, rates={"milk": 5.6})
        self.assertEqual(out[0]["reason"], "Usually gone after ~6 days")

    def test_cadence_and_learning(self):
        self.assertEqual(K.cadence(["2026-10-01", "2026-10-08", "2026-10-15", "2026-10-23"]), 7)
        self.assertIsNone(K.cadence(["2026-10-01", "2026-10-08"]))
        self.assertEqual(K.learn(None, 0, 6, "gone"), (6.0, 1))
        self.assertEqual(K.learn(None, 0, 6, "have"), (None, 0))
        self.assertEqual(K.learn(6.0, 1, 10, "gone"), (8.0, 2))
        self.assertAlmostEqual(K.learn(6.0, 2, 10, "have")[0], 7.2)
        self.assertEqual(K.learn(8.0, 2, 3, "have"), (8.0, 2))


class Flow(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            for t in ("pantry_items", "pantry_events", "consumption", "purchases"):
                c.execute(f"DELETE FROM {t}")

    def add(self, name, days_ago, **upd):
        with S.db() as c:
            pid = S.add_pantry_item(c, name, "fridge", None, "")
            c.execute("UPDATE pantry_items SET purchased_on=? WHERE id=?", (S.iso(S.today() - timedelta(days=days_ago)), pid))
            for k, v in upd.items():
                c.execute(f"UPDATE pantry_items SET {k}=? WHERE id=?", (v, pid))
        return pid

    def test_gone_learns_and_undo_restores(self):
        pid = self.add("whole milk", 6, amount_left=0.2)
        cards = S.checkin_cards()["cards"]
        self.assertEqual([c["id"] for c in cards], [pid])
        self.assertEqual(cards[0]["reason"], "Running low last time")
        out = S.checkin_answer({"id": pid, "answer": "gone"})
        self.assertEqual(out["item"]["status"], "used")
        with S.db() as c:
            self.assertEqual(c.execute("SELECT days, n FROM consumption").fetchone()[:], (6.0, 1))
        S.checkin_undo({"undo": out["undo"]})
        with S.db() as c:
            r = S.pantry_row(c, pid)
            self.assertEqual((r["status"], r["amount_left"]), ("active", 0.2))
            self.assertIsNone(c.execute("SELECT 1 FROM consumption").fetchone())
            self.assertIsNone(c.execute("SELECT 1 FROM pantry_events WHERE item_id=? AND action='checkin'", (pid,)).fetchone())

    def test_low_and_have_then_quiet(self):
        a = self.add("spinach", 1, expires_on=S.iso(S.today()))
        b = self.add("yogurt", 2, expires_on=S.iso(S.today() + timedelta(days=1)))
        S.checkin_answer({"id": a, "answer": "low"})
        with S.db() as c:
            self.assertEqual(S.pantry_row(c, a)["amount_left"], 0.25)
        res = S.checkin_finish({"have": [b]})
        self.assertFalse(res["status"]["due"])
        self.assertEqual(S.checkin_cards()["cards"], [])      # both confirmed: not asked again for a few days

    def test_bad_input(self):
        with self.assertRaises(S.ApiError):
            S.checkin_answer({"id": 1, "answer": "maybe"})
        with self.assertRaises(S.ApiError):
            S.checkin_undo({"undo": {"id": 1, "before": {"name": "x"}}})
