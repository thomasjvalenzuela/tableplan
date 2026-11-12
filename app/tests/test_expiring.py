"""Expiring view (23): segments, Still good, and Find recipes for one food."""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

from app import server as S


class Segments(unittest.TestCase):
    def test_expiry_segment(self):
        seg = S.expiry_segment
        self.assertEqual(seg(-1, "fridge", 0), "expired")
        self.assertEqual(seg(0, "fridge", 0), "soon")
        self.assertEqual(seg(3, "pantry", 40), "soon")
        self.assertIsNone(seg(4, "pantry", 5))
        self.assertEqual(seg(None, "pantry", 21), "stale")
        self.assertEqual(seg(30, "fridge", 30), "stale")
        self.assertIsNone(seg(None, "freezer", 200))       # the freezer is never stale
        self.assertEqual(seg(-2, "freezer", 200), "expired")
        self.assertIsNone(seg(None, "pantry", 20))
        self.assertIsNone(seg(None, "pantry", None))


class ExpiringApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.patches = [mock.patch.object(S, k, v) for k, v in (
            ("DATA_DIR", d), ("DB_PATH", os.path.join(d, "t.db")), ("IMG_DIR", os.path.join(d, "img")),
            ("BACKUP_DIR", os.path.join(d, "bk")), ("NATIVE", True), ("PUBLIC_MODE", False))]
        for p in self.patches:
            p.start()
        S.init_db(); S.load_cfg()
        self.t = S.today()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def add(self, name, loc="pantry", exp=None, bought_days_ago=0):
        with S.db() as c:
            iid = S.add_pantry_item(c, name, loc, None, "")
            bought = S.iso(self.t - timedelta(days=bought_days_ago))
            c.execute("UPDATE pantry_items SET expires_on=?, expiry_source=?, purchased_on=?, created_at=? WHERE id=?",
                      (S.iso(self.t + timedelta(days=exp)) if exp is not None else None, "manual" if exp is not None else "none",
                       bought, bought + "T09:00:00", iid))
            c.execute("UPDATE pantry_events SET at=? WHERE item_id=?", (bought + "T09:00:00", iid))
        return iid

    def test_view_and_actions(self):
        old = self.add("Old milk", "fridge", exp=-2)
        soon = self.add("Spinach", "fridge", exp=1)
        stale = self.add("Capers", "pantry", bought_days_ago=30)
        frozen = self.add("Frozen peas", "freezer", bought_days_ago=90)
        fresh = self.add("Rice", "pantry", bought_days_ago=2)
        v = S.expiring_view()
        ids = {k: [i["id"] for i in v[k]] for k in ("expired", "soon", "stale")}
        self.assertEqual(ids, {"expired": [old], "soon": [soon], "stale": [stale]})
        self.assertEqual(v["counts"], {"expired": 1, "soon": 1, "stale": 1})
        self.assertGreaterEqual(v["stale"][0]["touched_days"], 30)
        self.assertNotIn(frozen, sum(ids.values(), []))
        self.assertNotIn(fresh, sum(ids.values(), []))
        # Still good: no longer stale
        with S.db() as c:
            S.apply_pantry_action(c, stale, {"action": "still_good"})
        self.assertEqual(S.expiring_view()["stale"], [])
        # Gone counts as waste (status tossed); Used doesn't
        with S.db() as c:
            S.apply_pantry_action(c, old, {"action": "toss"})
            S.apply_pantry_action(c, soon, {"action": "use", "left": 0})
            self.assertEqual(S.pantry_row(c, old)["status"], "tossed")
            self.assertEqual(S.pantry_row(c, soon)["status"], "used")
        self.assertEqual(S.expiring_view()["counts"], {"expired": 0, "soon": 0, "stale": 0})

    def test_make_focus(self):
        with mock.patch.object(S, "recipe_pool", lambda: []):
            iid = self.add("Spinach", "fridge", exp=-1)   # even past its date, Find recipes works
            out = S.what_can_i_make(str(iid))
            self.assertEqual(out["focus"]["id"], iid)
            self.assertEqual(out["use_up"], [])
            with self.assertRaises(S.ApiError):
                S.what_can_i_make("999999")


if __name__ == "__main__":
    unittest.main()
