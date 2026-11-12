"""Common US groceries (generic, no brands): name, canonical food, default aisle and a typical size.

The seed lives in grocery_catalog.json next to this file. Matching is word-based with a little typo tolerance, so
"milk" finds Whole milk, 2% milk and Skim milk, and "yogrt" still finds yogurt. Stdlib only.
"""
import json
import os
import re
from difflib import SequenceMatcher

_PATH = os.path.join(os.path.dirname(__file__), "grocery_catalog.json")
_ITEMS = None


def items():
    global _ITEMS
    if _ITEMS is None:
        with open(_PATH, encoding="utf-8") as f:
            _ITEMS = json.load(f)
    return _ITEMS


def words(s):
    out = []
    for w in re.findall(r"[a-z0-9%]+", (s or "").lower()):
        if len(w) > 3 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("es") and w[-3] in "sxz":
            w = w[:-2]
        elif len(w) > 2 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def score(query, name, extra=""):
    """How well `query` matches an item name (0 = no match). Exact > prefix > every word matched > close spelling."""
    q, n = " ".join(words(query)), " ".join(words(name))
    if not q or not n:
        return 0
    if q == n:
        return 100
    if n.startswith(q + " ") or n.startswith(q) and len(n) == len(q):
        return 85 - min(20, len(n) - len(q)) / 2
    if n.startswith(q):   # inside a word: "egg" → "eggplant" ranks below whole words
        return 52
    qw, nw = q.split(), set(words(name) + words(extra))
    hits = 0
    for w in qw:
        if any(x == w or (len(w) >= 3 and x.startswith(w)) for x in nw):
            hits += 1
        elif len(w) >= 4 and any(SequenceMatcher(None, w, x).ratio() >= 0.8 for x in nw):
            hits += 0.7
    if hits >= len(qw) - 1e-9:
        return 60 + 10 * hits / max(1, len(nw)) - len(n) / 40
    if hits and hits >= len(qw) - 0.31:
        return 40 + 5 * hits
    return 0


def search(query, limit=8):
    scored = [(score(query, it["name"], it["food"]) + (6 if it.get("popular") else 0), it) for it in items()]
    scored = [(s if s > 6 else 0, it) for s, it in scored]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    return [dict(it, score=round(s, 1)) for s, it in scored[:limit]]


def find(name):
    k = " ".join(words(name))
    return next((it for it in items() if " ".join(words(it["name"])) == k or " ".join(words(it["food"])) == k), None)


def aisle_of(name):
    it = find(name)
    return it["aisle"] if it else None


def popular():
    return [it for it in items() if it.get("popular")]


def by_aisle():
    out = {}
    for it in items():
        out.setdefault(it["aisle"], []).append(it)
    return [{"aisle": a, "items": v} for a, v in out.items()]


def related(line_food, product_food):
    """A generic list line a specific product could fill: "milk" ⊂ "whole milk". Variants never match: "2% milk" and
    "whole milk" each have a word the other lacks, as do "table salt" and "sea salt"."""
    a, b = set(words(line_food)), set(words(product_food))
    if not a or not b or a == b:
        return a == b and bool(a)
    return a < b or b < a
