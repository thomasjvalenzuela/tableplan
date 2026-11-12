"""Fast batch scan view (22): static wiring checks for the client-only view."""
import json
import os
import re
import unittest

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")


def read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as f:
        return f.read()


class BatchScanView(unittest.TestCase):
    def setUp(self):
        self.js = read("recipes.js")

    def test_toggle_is_remembered(self):
        self.assertIn('localStorage.getItem("tp.scanView")', self.js)
        self.assertIn('localStorage.setItem("tp.scanView"', self.js)
        self.assertIn('id="sb-view"', self.js)

    def test_batch_view_parts(self):
        body = self.js[self.js.index("function drawBatch"):]
        body = body[: body.index("\n}\n")]
        for part in ("bt-sum", "to review", "data-bfill", "data-bdate", "data-bdel", "onpointermove", "bumpScan"):
            self.assertIn(part, body)
        self.assertNotRegex(body, r"\son[a-z]+=\"")          # no inline handlers (strict CSP)
        html = body[: body.index("$$(\".bt-row\"")]
        for m in re.finditer(r"\$\{(?!esc\(|ic\(|i\}|r\.count > 1|r\.unknown|review \?|it\.image \?|it\.expires_on \?)", html):
            self.fail("unescaped interpolation near: " + html[m.start(): m.start() + 40])

    def test_whatsnew_entry(self):
        ids = [e["id"] for e in json.loads(read("whatsnew.json"))]
        self.assertIn("batch-scan", ids)


if __name__ == "__main__":
    unittest.main()
