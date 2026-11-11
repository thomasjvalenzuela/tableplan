"""Themes: the look is set on the page before the first paint (cookie), and kept per person."""

import os
import tempfile
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-look-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402

PAGE = (b'<html lang="en">\n<meta name="theme-color" content="#FFFFFF" media="(prefers-color-scheme: light)">\n'
        b'<meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)">')


class Look(unittest.TestCase):
    def test_cookie_sets_theme_and_mode_before_paint(self):
        out = S.look_index(PAGE, "a=1; tp_look=midnight.dark; b=2")
        self.assertIn(b'<html lang="en" data-theme="midnight" data-mode="dark">', out)
        self.assertEqual(out.count(b'content="#050B1A"'), 2)            # both metas: the forced dark colour
        sys_ = S.look_index(PAGE, "tp_look=blossom.system")
        self.assertIn(b'data-theme="blossom">', sys_)
        self.assertIn(b'content="#FFF5F7" media="(prefers-color-scheme: light)"', sys_)
        self.assertIn(b'content="#0D070B" media="(prefers-color-scheme: dark)"', sys_)

    def test_bad_cookies_change_nothing(self):
        for c in ("", "tp_look=neon.dark", "tp_look=mono.sepia", 'tp_look=mono.dark"><script>', "xtp_look=forest.dark"):
            self.assertEqual(S.look_index(PAGE, c), PAGE, c)

    def test_palette_setting_is_validated_and_per_person(self):
        self.assertIn("palette", S.PER_USER_SETTINGS)
        self.assertEqual(S.validate_setting("palette", "forest"), "forest")
        with self.assertRaises(S.ApiError):
            S.validate_setting("palette", "green")


if __name__ == "__main__":
    unittest.main()
