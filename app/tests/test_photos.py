"""Recipe photos: metadata stripped, sizes served, picking from sources (nothing auto-assigned but the recipe's own
page photo at import), AI photos kept side by side with the original, the AI budget."""

import base64
import os
import shutil
import struct
import tempfile
import time
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-photos-")
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


def jpeg(w=40, h=30, exif=True):
    seg = lambda m, data: b"\xff" + bytes([m]) + struct.pack(">H", len(data) + 2) + data
    app0 = seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    app1 = seg(0xE1, b"Exif\x00\x00GPS-LAT-51.5") if exif else b""
    com = seg(0xFE, b"taken at home") if exif else b""
    sof = seg(0xC0, b"\x08" + struct.pack(">HH", h, w) + b"\x01\x01\x11\x00")
    return b"\xff\xd8" + app0 + app1 + com + sof + b"\xff\xda\x00\x02SCANDATA\xff\xd9"


def png(w=20, h=10, text=True):
    ihdr = M.png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    meta = M.png_chunk(b"tEXt", b"Comment\x00secret") + M.png_chunk(b"eXIf", b"MM\x00*") if text else b""
    return b"\x89PNG\r\n\x1a\n" + ihdr + meta + M.png_chunk(b"IDAT", b"x") + M.png_chunk(b"IEND", b"")


def webp(exif=True):
    vp8x = b"VP8X" + struct.pack("<I", 10) + bytes([0x08 | 0x04, 0, 0, 0]) + (39).to_bytes(3, "little") + (29).to_bytes(3, "little")
    img = b"VP8L" + struct.pack("<I", 2) + b"\x2f\x00"
    ex = b"EXIF" + struct.pack("<I", 4) + b"GPS!" if exif else b""
    body = b"WEBP" + vp8x + img + ex
    return b"RIFF" + struct.pack("<I", len(body)) + body


def data_url(b, t="image/jpeg"):
    return f"data:{t};base64," + base64.b64encode(b).decode()


class Metadata(unittest.TestCase):
    def test_jpeg(self):
        out = M.strip_metadata(jpeg())
        self.assertNotIn(b"GPS", out)
        self.assertNotIn(b"taken at home", out)
        self.assertIn(b"JFIF", out)
        self.assertTrue(out.endswith(b"SCANDATA\xff\xd9"))
        self.assertEqual(M.size(out), (40, 30))

    def test_png_and_webp(self):
        out = M.strip_metadata(png())
        self.assertNotIn(b"secret", out)
        self.assertNotIn(b"eXIf", out)
        self.assertEqual(M.size(out), (20, 10))
        w = M.strip_metadata(webp())
        self.assertNotIn(b"GPS!", w)
        self.assertEqual(w[20] & 0x0C, 0)                  # EXIF/XMP flags cleared
        self.assertEqual(struct.unpack("<I", w[4:8])[0], len(w) - 8)
        self.assertEqual(M.size(w), (40, 30))

    def test_leaves_other_bytes_alone(self):
        self.assertEqual(M.strip_metadata(b"GIF89a\x01\x00\x01\x00"), b"GIF89a\x01\x00\x01\x00")
        self.assertEqual(M.strip_metadata(b"\xff\xd8\xff\x00junk"), b"\xff\xd8\xff\x00junk")
        self.assertIsNone(M.size(b"nope"))


def recipe(name, url=""):
    slug = S.mealie("POST", "/api/recipes", {"name": name})
    if url:
        with S.db() as c:
            rec = S.n_recipes.get(c, slug)
            S.n_recipes.update(c, slug, {**rec, "orgURL": url})
    return slug


class Photos(unittest.TestCase):
    def rid(self, slug):
        with S.db() as c:
            return S.n_recipes.get(c, slug)

    def served(self, rid, size):
        h = mock.MagicMock()
        S.Handler.image(h, rid, size)
        return h.send.call_args[0][1]

    def test_upload_sizes_strip_and_serve(self):
        slug = recipe("Shakshuka")
        S.save_recipe_photo(slug, {"data": data_url(jpeg(1600, 1200)), "card": data_url(jpeg(800, 600)),
                                   "thumb": data_url(jpeg(320, 240)), "credit": "Your photo"})
        rec = self.rid(slug)
        full, card, thumb = self.served(rec["id"], "full"), self.served(rec["id"], "min"), self.served(rec["id"], "tiny")
        self.assertEqual((M.size(full), M.size(card), M.size(thumb)), ((1600, 1200), (800, 600), (320, 240)))
        self.assertNotIn(b"GPS", full + card + thumb)
        self.assertEqual(S.recipe_photo_info(rec), {"credit": "Your photo", "ai": False, "kept": False})
        time.sleep(1.1)
        S._upload_recipe_image(slug, jpeg(500, 400), "image/jpeg")       # replaced some other way: old sizes are ignored
        self.assertEqual(M.size(self.served(rec["id"], "min")), (500, 400))
        with self.assertRaises(S.ApiError):
            S.save_recipe_photo(slug, {"data": data_url(jpeg(5000, 3000))})
        with self.assertRaises(S.ApiError):
            S.save_recipe_photo(slug, {"data": data_url(jpeg(800, 600)), "card": data_url(jpeg(2000, 1500))})

    def test_candidates_never_assign_and_page_photo_first(self):
        slug = recipe("Pad Thai", "https://cook.example/pad-thai")
        page = '<html><head><meta property="og:image" content="https://cook.example/pt.jpg"></head><body></body></html>'
        ov = {"results": [{"url": f"https://ov.example/{i}.jpg", "title": f"T{i}", "creator": "C", "license": "by"} for i in range(5)]}
        wm = {"query": {"pages": {"1": {"index": 1, "title": "File:Pad thai.jpg", "imageinfo": [{"thumburl": "https://wm.example/p.jpg",
              "extmetadata": {"Artist": {"value": "<a href='x'>Jane</a>"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}}}}

        def fake(url, **kw):
            return ov if "openverse" in url else wm if "wikimedia" in url else {}
        with mock.patch.object(S, "_fetch_page", return_value=("https://cook.example/pad-thai", page)), \
                mock.patch.object(S, "_https_json", side_effect=fake):
            out = S.recipe_photo_candidates(slug)["candidates"]
        self.assertEqual(len(out), 6)
        self.assertEqual(out[0]["source"], "Recipe page")
        self.assertIn("Wikimedia Commons", [x["source"] for x in out])
        self.assertEqual(next(x["credit"] for x in out if x["source"] == "Wikimedia Commons"), "“Pad thai” by Jane (CC BY-SA 4.0), Wikimedia Commons")
        self.assertFalse(self.rid(slug).get("image"))                  # nothing assigned
        with mock.patch.object(S, "_fetch_image", return_value=(jpeg(), "image/jpeg")) as f:
            blob, ctype = S.recipe_photo_candidate(slug, 0)
            S.recipe_photo_candidate(slug, 0)
        self.assertEqual(f.call_count, 1)
        self.assertEqual(f.call_args[0][0], "https://cook.example/pt.jpg")
        with self.assertRaises(S.ApiError):
            S.recipe_photo_candidate(slug, 9)

    def test_stock_sources_need_keys(self):
        self.assertEqual(S.unsplash_candidates("soup"), [])
        self.assertEqual(S.pexels_candidates("soup"), [])
        S.set_cfg(unsplash_key="u", pexels_key="p")
        try:
            with mock.patch.object(S, "_https_json", side_effect=[
                    {"results": [{"urls": {"regular": "https://un.example/a.jpg"}, "user": {"name": "Ann"}}]},
                    {"photos": [{"src": {"large": "https://px.example/b.jpg"}, "photographer": "Bo"}]}]) as h:
                self.assertEqual(S.unsplash_candidates("soup")[0]["credit"], "Photo by Ann on Unsplash")
                self.assertEqual(S.pexels_candidates("soup")[0]["credit"], "Photo by Bo on Pexels")
            self.assertEqual(h.call_args_list[0].kwargs["headers"]["Authorization"], "Client-ID u")
        finally:
            S.set_cfg(unsplash_key="", pexels_key="")

    def test_ai_photo_kept_side_by_side_and_restored(self):
        slug = recipe("Lemon Bars")
        S.save_recipe_photo(slug, {"data": data_url(jpeg(1200, 900)), "credit": "Your photo"})
        S.set_cfg(openai_key="sk-test")
        try:
            gen = {"data": [{"b64_json": base64.b64encode(png(1536, 1024)).decode()}], "usage": {"input_tokens": 50, "output_tokens": 4000}}
            with mock.patch.object(S, "_https_json", return_value=gen) as h:
                out = S.recipe_photo_ai(slug, {"mode": "new"})
            self.assertIn("images/generations", h.call_args[0][0])
            self.assertIn("ai-pending", out["src"])
            self.assertEqual(M.size(S.recipe_photo_pending(slug)[0]), (1536, 1024))
            self.assertEqual(self.served(self.rid(slug)["id"], "full")[:3], b"\xff\xd8\xff")   # still the cook's photo
            S.save_recipe_photo(slug, {"data": data_url(png(1536, 1024), "image/png"), "ai": True, "keep": True})
            info = S.recipe_photo_info(self.rid(slug))
            self.assertEqual(info, {"credit": "AI image", "ai": True, "kept": True})
            S.recipe_photo_restore(slug)
            rec = self.rid(slug)
            self.assertEqual(S.recipe_photo_info(rec), {"credit": "Your photo", "ai": False, "kept": False})
            self.assertEqual(M.size(self.served(rec["id"], "full")), (1200, 900))
            with S.db() as c:
                self.assertTrue(c.execute("SELECT 1 FROM ai_usage WHERE feature='recipe photo'").fetchone())
            with mock.patch.object(S, "_https_json", return_value=gen) as h:
                S.recipe_photo_ai(slug, {"mode": "enhance"})
            self.assertIn("images/edits", h.call_args[0][0])
            self.assertIn(b'name="image"', h.call_args.kwargs["data"])
            with mock.patch.object(S, "_ai_over_budget", return_value=True), mock.patch.object(S, "_https_json") as h:
                with self.assertRaises(S.ApiError) as e:
                    S.recipe_photo_ai(slug, {"mode": "new"})
            self.assertEqual(e.exception.status, 402)
            h.assert_not_called()
        finally:
            S.set_cfg(openai_key="")
