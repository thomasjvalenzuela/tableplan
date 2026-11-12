"""P (UI audit): bare barcodes never become item titles; recipe cards carry their cost; static wiring."""
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-ui-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
_P = []


def setUpModule():
    for k, v in (("DATA_DIR", _TMP), ("DB_PATH", os.path.join(_TMP, "t.db")), ("IMG_DIR", os.path.join(_TMP, "img")),
                 ("BACKUP_DIR", os.path.join(_TMP, "bk")), ("NATIVE", True), ("PUBLIC_MODE", False)):
        p = mock.patch.object(S, k, v); p.start(); _P.append(p)
    S.init_db(); S.load_cfg()


def tearDownModule():
    for p in reversed(_P):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


class BarcodeNames(unittest.TestCase):
    def test_migration_turns_old_unknown_scans_into_review_placeholders(self):
        with S.db() as c:
            t = S.iso(S.today())
            ids = []
            for name in ("635878113539", "711535506496", "12345", "Milk"):
                c.execute("INSERT INTO pantry_items(name, location, amount_left, purchased_on, status, created_at) "
                          "VALUES (?, 'pantry', 1, ?, 'active', ?)", (name, t, t + "T09:00:00"))
                ids.append(c.execute("SELECT last_insert_rowid()").fetchone()[0])
            S._migrate_barcode_names(c)
            rows = {r["id"]: r for r in c.execute("SELECT * FROM pantry_items")}
        self.assertEqual(rows[ids[0]]["name"], "Unknown item · 635878113539")
        self.assertEqual(rows[ids[0]]["upc"], "635878113539")
        self.assertEqual(rows[ids[0]]["review"], 1)
        self.assertEqual(rows[ids[2]]["name"], "12345")              # too short to be a barcode
        self.assertEqual(rows[ids[3]]["name"], "Milk")
        with S.db() as c:
            S._migrate_barcode_names(c)                               # running again changes nothing
            self.assertEqual(c.execute("SELECT name FROM pantry_items WHERE id=?", (ids[0],)).fetchone()[0], "Unknown item · 635878113539")

    def test_never_a_bare_barcode_as_a_title(self):
        self.assertEqual(S.pantry_display_name("0123456789012"), "Unknown item · 0123456789012")
        self.assertEqual(S.pantry_display_name("Oat milk"), "Oat milk")


class Wiring(unittest.TestCase):
    def test_client(self):
        app = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
        css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
        self.assertIn("markUpdSeen()", app)                               # the dot clears once seen
        self.assertIn('id="nav-make"', app)                               # What can I make? in the sidebar
        self.assertIn("SHORTCUTS", app)
        self.assertIn("[hidden]{display:none!important}", css)
        self.assertIn("@media (min-width:768px) and (max-width:1023px)", css)   # the tablet rail
        stats = app[app.index("function homeStats"):app.index("const storeName")]
        self.assertNotIn("plural(week.length, \"meal\"))}</i>", stats)
        for zero in ("Stock up", "Add to list", "Plan a meal"):
            self.assertIn(zero, stats)
        radii = set(re.findall(r"border-radius:(\d+)px", css))
        self.assertTrue(radii <= {"2", "3", "4", "5", "6", "7", "8", "12", "16", "22", "28", "999"}, radii)


if __name__ == "__main__":
    unittest.main()
