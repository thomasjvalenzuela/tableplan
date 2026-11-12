"""Product photos on inventory items: upload (metadata stripped, fresh file names), background cut-out keeps the
original, restore, and clean-up on delete."""

import base64
import os
import shutil
import struct
import tempfile
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-pphoto-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402
from app.native import imgmeta as M  # noqa: E402

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


def jpeg(w=40, h=30):
    seg = lambda m, data: b"\xff" + bytes([m]) + struct.pack(">H", len(data) + 2) + data  # noqa: E731
    return (b"\xff\xd8" + seg(0xE1, b"Exif\x00\x00GPS-HOME") + seg(0xC0, b"\x08" + struct.pack(">HH", h, w) + b"\x01\x01\x11\x00")
            + b"\xff\xda\x00\x02DATA\xff\xd9")


def png(w=40, h=40):
    return b"\x89PNG\r\n\x1a\n" + M.png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + M.png_chunk(b"IDAT", b"x") + M.png_chunk(b"IEND", b"")


url = lambda b, t: f"data:{t};base64," + base64.b64encode(b).decode()  # noqa: E731


class ProductPhotos(unittest.TestCase):
    def setUp(self):
        with S.db() as c:
            self.pid = S.add_pantry_item(c, "ketchup", "fridge", None, "")

    def files(self):
        d = os.path.join(S.IMG_DIR, "pantry")
        return sorted(f for f in os.listdir(d) if f.startswith(f"{self.pid}-"))

    def test_upload_cutout_restore_delete(self):
        it = S.pantry_photo(self.pid, {"image": url(jpeg(), "image/jpeg")})
        self.assertFalse(it["image_cut"])
        name = self.files()[0]
        self.assertRegex(name, rf"^{self.pid}-[0-9a-f]{{6}}\.jpg$")
        with open(os.path.join(S.IMG_DIR, "pantry", name), "rb") as f:
            self.assertNotIn(b"GPS", f.read())                         # location data stripped
        it = S.pantry_photo(self.pid, {"image": url(png(), "image/png"), "cutout": True})
        self.assertTrue(it["image_cut"])
        self.assertEqual(len(self.files()), 2)                          # the cut-out and the kept original
        self.assertTrue(any(f.endswith("-orig.jpg") for f in self.files()))
        self.assertIn(".png", it["image"])
        it = S.pantry_photo_restore(self.pid)
        self.assertFalse(it["image_cut"])
        self.assertEqual([f.rsplit(".", 1)[1] for f in self.files()], ["jpg"])
        with self.assertRaises(S.ApiError):
            S.pantry_photo_restore(self.pid)
        S.pantry_photo(self.pid, {"image": url(png(), "image/png"), "cutout": True})
        S.pantry_photo(self.pid, {"image": url(jpeg(20, 20), "image/jpeg")})   # a new photo: the old original goes
        self.assertEqual(len(self.files()), 1)
        S.pantry_photo(self.pid, {"image": url(png(), "image/png"), "cutout": True})
        S.scan_undo({"pantry_item_id": self.pid})                       # removing the item removes both files
        self.assertEqual(self.files(), [])

    def test_rejects_huge_and_serves_new_names(self):
        with self.assertRaises(S.ApiError):
            S.pantry_photo(self.pid, {"image": url(jpeg(4000, 3000), "image/jpeg")})
        it = S.pantry_photo(self.pid, {"image": url(jpeg(), "image/jpeg")})
        fn = it["image"].split("?v=")[1]
        self.assertRegex(fn, r"^\d+-[0-9a-f]{6}\.jpg$")
