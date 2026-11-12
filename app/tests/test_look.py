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


CSS = os.path.join(os.path.dirname(__file__), "..", "static", "app.css")


def _tokens():
    """{(palette, mode): {var: value}} for the 8 combinations, read from app.css."""
    import re
    css = open(CSS, encoding="utf-8").read()
    sel = {("mono", "light"): r":root", ("mono", "dark"): r':root\[data-mode="dark"\]'}
    for t in ("midnight", "blossom", "forest"):
        sel[(t, "light")] = rf':root\[data-theme="{t}"\]'
        sel[(t, "dark")] = rf':root\[data-theme="{t}"\]\[data-mode="dark"\]'
    out = {}
    for k, pat in sel.items():
        m = re.search(r"(?m)^" + pat + r"\{(--bg:[^}]*)\}", css)
        out[k] = dict(re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", m.group(1) + ";"))
    return out


def _lum(hexv):
    h = hexv.strip().lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class Contrast(unittest.TestCase):
    def test_update_banner_and_inverse_surfaces_read_in_all_8_combos(self):
        toks = _tokens()
        self.assertEqual(len(toks), 8)
        for (look, mode), t in toks.items():
            # the update bar: --ink/--on-ink in light mode, --card2/--text in dark mode (see app.css "P" section)
            bg, fg = (t["--ink"], t["--on-ink"]) if mode == "light" else (t["--card2"], t["--text"])
            self.assertGreaterEqual(contrast(bg, fg), 4.5, f"update bar {look}/{mode}")
            for b_, f_ in (("--accent", "--on-accent"), ("--toast-bg", "--toast-fg"), ("--ink", "--on-ink")):
                self.assertGreaterEqual(contrast(t[b_], t[f_]), 4.5, f"{b_} on {look}/{mode}")
            self.assertGreaterEqual(contrast(t["--bg"], t["--text"]), 7, f"text {look}/{mode}")

    def test_no_white_text_on_theme_surfaces(self):
        import re
        css = open(CSS, encoding="utf-8").read()
        p = css[css.index("/* ================================================================ P: UI audit"):]
        self.assertIn(".update-bar,.update-banner{background:var(--ink);color:var(--on-ink)", p)
        for rule in re.findall(r"\.update-bar[^{]*\{[^}]*\}", p):
            self.assertNotIn("#fff", rule.lower())


if __name__ == "__main__":
    unittest.main()
