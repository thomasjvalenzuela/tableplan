"""The amount-left slider's server side: fill keeps the package amount in step, 0 finishes, Undo restores."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-fill-")
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


def act(pid, body):
    with S.db() as c:
        S.apply_pantry_action(c, pid, body)
        return S.pantry_json(c, S.pantry_row(c, pid))


class Fill(unittest.TestCase):
    def test_package_amount_finish_and_undo(self):
        with S.db() as c:
            pid = S.add_pantry_item(c, "whole milk", "fridge", None, "1 gallon")
        r = act(pid, {"action": "fill", "left": 0.5})
        self.assertEqual((r["amount_left"], r["qty"], r["unit"]), (0.5, 0.5, "gallon"))
        self.assertTrue(r["opened_on"])                              # using some opens it
        r = act(pid, {"action": "fill", "left": 0.25})
        self.assertEqual(r["qty"], 0.25)
        r = act(pid, {"action": "use", "left": 0})
        self.assertEqual(r["status"], "used")
        act(pid, {"action": "restore"})                              # Undo: back, at the amount it had
        r = act(pid, {"action": "fill", "left": 0.25})
        self.assertEqual((r["status"], r["amount_left"], r["qty"]), ("active", 0.25, 0.25))

    def test_count_items(self):
        with S.db() as c:
            pid = S.add_pantry_item(c, "eggs", "fridge", None, "12")
        r = act(pid, {"action": "fill", "left": 0.75})
        self.assertEqual((r["qty"], r["amount_left"]), (9, 0.75))
