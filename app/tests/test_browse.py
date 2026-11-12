"""Browse common items: the grid knows what's at home (per item and per aisle), with emoji and cached photos only."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-browse-")
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


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


class Grid(unittest.TestCase):
    def test_at_home_counts(self):
        with S.db() as c:
            S.add_pantry_item(c, "bananas", "pantry", None, "3")
            m = S.add_pantry_item(c, "whole milk", "fridge", None, "1 gallon")
            c.execute("UPDATE pantry_items SET amount_left=0.5 WHERE id=?", (m,))
            S.add_pantry_item(c, "apples", "fridge", None, "")
            u = S.add_pantry_item(c, "Unknown item · 0852390000111", "pantry", None, "")
            c.execute("UPDATE pantry_items SET review=1 WHERE id=?", (u,))
            t = S.add_pantry_item(c, "lemons", "fridge", None, "")
            c.execute("UPDATE pantry_items SET status='used' WHERE id=?", (t,))
        with mock.patch.object(S, "_fetch_image") as f:
            d = S.grocery_catalog_view()
        f.assert_not_called()                                    # never fetches photos just to draw the grid
        items = {i["name"]: i for a in d["aisles"] for i in a["items"]}
        self.assertEqual((items["Bananas"]["home"], items["Apples"]["home"], items["Lemons"]["home"]), (1, 1, 0))
        self.assertEqual((items["Whole milk"]["home"], items["Whole milk"]["left"]), (1, "½ left"))
        self.assertEqual(items["Bananas"]["emoji"], "🍌")
        self.assertFalse(items["Bananas"]["photo"])
        produce = next(a for a in d["aisles"] if a["aisle"] == "Produce")
        self.assertEqual(produce["home"], 2)                     # bananas + apples (not the used lemons)
