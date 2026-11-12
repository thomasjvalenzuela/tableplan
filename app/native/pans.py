"""Pan sizes: find them in a recipe, compare them, and say what scaling does to them.

A pan: {kind, w, h, d, cups, quarts, label}. Sizes are inches (w×h for rectangles, d for rounds); muffin tins count
cups; Dutch ovens and slow cookers count quarts. Area (square inches) is what matters for baking: scale a recipe 1.5×
and the batter needs ~1.5× the area to bake the same way; keep the pan and it gets ~1.5× deeper (longer bake).
"""

import math
import re

ROUND = {"round", "springform", "pie", "skillet", "bundt", "tart", "tube", "cake"}
_NUM = r"(\d{1,2}(?:\.\d)?|\d{1,2}\s?½)"
_X = r"\s*(?:x|×|by|X)\s*"
_IN = r"(?:\s*-?\s*(?:inch(?:es)?|in\.?|\"|”|″))?"
_KIND = (r"(baking|cake|sheet|roasting|loaf|square|round|springform|pie|tart|bundt|tube|jelly[- ]roll|muffin|cupcake|"
         r"skillet|frying|casserole|gratin|brownie|bar|pan|dish|tin|plate|dutch oven|pot|slow cooker|crock ?pot)")
RECT = re.compile(rf"\b{_NUM}{_IN}{_X}{_NUM}{_IN}(?:{_X}\d{{1,2}}{_IN})?\s*(?:-?\s*inch)?\s*(?:\w+\s+){{0,2}}?{_KIND}", re.I)
ONE = re.compile(rf"\b{_NUM}{_IN}\s*(square|round)?\s*(?:\w+\s+){{0,2}}?{_KIND}", re.I)
MUFFIN = re.compile(r"\b(6|12|18|24|48)[- ](?:cup|count|hole|well)\s+(?:standard\s+|mini\s+|regular\s+)?(muffin|cupcake)", re.I)
QUART = re.compile(r"\b(\d(?:\.\d)?|\d½)[- ]?(?:quart|qt\.?)\s+(dutch oven|pot|slow cooker|crock ?pot|casserole|saucepan|baking dish)", re.I)
SHEETS = {"half sheet": (18, 13), "quarter sheet": (13, 9), "jelly roll": (15, 10), "full sheet": (26, 18)}
SHEET = re.compile(r"\b(half|quarter|full)[- ]sheet(?: pan)?|\bjelly[- ]roll pan", re.I)
NEEDS = re.compile(r"\b(baking (?:pan|dish|sheet)|cake pan|loaf pan|muffin (?:tin|pan)|springform|bundt|pie (?:dish|plate|pan)|"
                   r"casserole dish|square pan|brownie pan|tart pan|prepared pan|greased pan|lined pan)\b", re.I)
BAKE = re.compile(r"\b(bake|oven|preheat)\b", re.I)

COMMON = [
    {"kind": "rect", "w": 13, "h": 9, "label": "9×13 in pan"},
    {"kind": "square", "w": 8, "h": 8, "label": "8×8 in square"},
    {"kind": "square", "w": 9, "h": 9, "label": "9×9 in square"},
    {"kind": "round", "d": 8, "label": "8 in round"},
    {"kind": "round", "d": 9, "label": "9 in round"},
    {"kind": "rect", "w": 11, "h": 7, "label": "7×11 in pan"},
    {"kind": "loaf", "w": 9, "h": 5, "label": "9×5 in loaf"},
    {"kind": "loaf", "w": 8.5, "h": 4.5, "label": "8½×4½ in loaf"},
    {"kind": "springform", "d": 9, "label": "9 in springform"},
    {"kind": "springform", "d": 10, "label": "10 in springform"},
    {"kind": "pie", "d": 9, "label": "9 in pie dish"},
    {"kind": "bundt", "d": 10, "label": "10 in Bundt"},
    {"kind": "rect", "w": 15, "h": 10, "label": "10×15 in jelly roll"},
    {"kind": "rect", "w": 18, "h": 13, "label": "Half sheet (13×18 in)"},
    {"kind": "rect", "w": 13, "h": 9.5, "label": "Quarter sheet (9×13 in)"},
    {"kind": "muffin", "cups": 12, "label": "12-cup muffin tin"},
    {"kind": "muffin", "cups": 24, "label": "24-cup muffin tin"},
    {"kind": "skillet", "d": 10, "label": "10 in skillet"},
    {"kind": "skillet", "d": 12, "label": "12 in skillet"},
]


def _n(s):
    s = str(s).replace(" ", "")
    return float(s.replace("½", "")) + 0.5 if "½" in s else float(s)


def _fmt(v):
    v = float(v)
    return str(int(v)) if v.is_integer() else ("%g" % v).replace(".5", "½") if abs(v * 2 - round(v * 2)) < 1e-9 else "%g" % v


def label(p):
    k = p.get("kind")
    if k == "muffin":
        return f"{int(p['cups'])}-cup muffin tin"
    if k in ("dutch", "pot"):
        return f"{_fmt(p['quarts'])} qt {'Dutch oven' if k == 'dutch' else 'pot'}"
    if p.get("d"):
        word = {"round": "round", "springform": "springform", "pie": "pie dish", "skillet": "skillet", "bundt": "Bundt",
                "tart": "tart pan", "tube": "tube pan"}.get(k, "round")
        return f"{_fmt(p['d'])} in {word}"
    if k == "square":
        return f"{_fmt(p['w'])}×{_fmt(p['w'])} in square"
    if k == "loaf":
        return f"{_fmt(max(p['w'], p['h']))}×{_fmt(min(p['w'], p['h']))} in loaf"
    return f"{_fmt(min(p['w'], p['h']))}×{_fmt(max(p['w'], p['h']))} in pan"


def area(p):
    """Square inches (muffin tins: cups; pots: quarts) — only compare pans of the same family."""
    k = p.get("kind")
    if k == "muffin":
        return float(p.get("cups") or 0)
    if k in ("dutch", "pot"):
        return float(p.get("quarts") or 0)
    if p.get("d"):
        a = math.pi * (float(p["d"]) / 2) ** 2
        return a * 0.85 if k in ("bundt", "tube") else a
    return float(p.get("w") or 0) * float(p.get("h") or p.get("w") or 0)


def family(p):
    k = p.get("kind")
    return {"muffin": "muffin", "dutch": "pot", "pot": "pot", "loaf": "loaf", "skillet": "skillet", "pie": "pie", "bundt": "bundt",
            "tube": "bundt"}.get(k, "pan")


def detect(texts):
    """The first pan named with a size in a recipe's ingredients/steps/notes, or None."""
    blob = " \n".join(t for t in texts if isinstance(t, str))
    best = None
    for rx, fn in ((MUFFIN, _muffin), (QUART, _quart), (SHEET, _sheet), (RECT, _rect), (ONE, _one)):
        for m in rx.finditer(blob):
            p = fn(m)
            if p:
                if best is None or m.start() < best[0]:
                    best = (m.start(), p)
                break
    if not best:
        return None
    p = best[1]
    p["label"] = label(p)
    return p


def _muffin(m):
    return {"kind": "muffin", "cups": int(m.group(1))}


def _quart(m):
    k = m.group(2).lower()
    return {"kind": "dutch" if "dutch" in k else "pot", "quarts": _n(m.group(1))}


def _sheet(m):
    t = m.group(0).lower()
    w, h = SHEETS["jelly roll" if "jelly" in t else f"{m.group(1).lower()} sheet"]
    return {"kind": "rect", "w": w, "h": h}


def _rect(m):
    a, b, kind = _n(m.group(1)), _n(m.group(2)), m.group(3).lower()
    if not (3 <= a <= 30 and 3 <= b <= 30):
        return None
    w, h = max(a, b), min(a, b)
    if kind.startswith("loaf"):
        return {"kind": "loaf", "w": w, "h": h}
    return {"kind": "square" if w == h else "rect", "w": w, "h": h}


def _one(m):
    d, shape, kind = _n(m.group(1)), (m.group(2) or "").lower(), m.group(3).lower()
    if not 4 <= d <= 16:
        return None
    if shape == "square" or kind == "square" or kind in ("brownie",):
        return {"kind": "square", "w": d, "h": d}
    for k in ("springform", "pie", "skillet", "bundt", "tart", "tube"):
        if k in kind:
            return {"kind": k, "d": d}
    if kind in ("frying",):
        return {"kind": "skillet", "d": d}
    if shape == "round" or kind in ("cake", "round"):
        return {"kind": "round", "d": d}
    return None   # "a 10-inch pan" alone is ambiguous


def needs_pan(texts):
    """A baked recipe that uses a pan but never says which size."""
    blob = " ".join(t for t in texts if isinstance(t, str))
    return bool(BAKE.search(blob) and NEEDS.search(blob)) and detect(texts) is None


def parse(text):
    """The cook's answer ("9x13", "8 inch round", "12 cup muffin") -> pan, or None."""
    t = str(text or "")
    p = detect([t]) or detect([t + " pan"])
    if p:
        return p
    m = re.match(r"^\s*" + _NUM + r"\s*(?:x|×|by)\s*" + _NUM + r"\s*$", t, re.I)
    if m:
        a, b = _n(m.group(1)), _n(m.group(2))
        p = {"kind": "square" if a == b else "rect", "w": max(a, b), "h": min(a, b)}
        p["label"] = label(p)
        return p
    return None


def clean(p):
    """A pan from the client, validated (or None)."""
    if not isinstance(p, dict) or p.get("kind") not in ("rect", "square", "loaf", "round", "springform", "pie", "skillet",
                                                          "bundt", "tart", "tube", "muffin", "dutch", "pot"):
        return None
    out = {"kind": p["kind"]}
    for k, lo, hi in (("w", 2, 30), ("h", 2, 30), ("d", 2, 20), ("cups", 1, 48), ("quarts", 0.5, 12)):
        v = p.get(k)
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                return None
            out[k] = float(v)
    if out["kind"] in ("rect", "square", "loaf") and "w" not in out:
        return None
    if out["kind"] in ("round", "springform", "pie", "skillet", "bundt", "tart", "tube") and "d" not in out:
        return None
    if out["kind"] == "muffin" and "cups" not in out:
        return None
    if out["kind"] in ("dutch", "pot") and "quarts" not in out:
        return None
    if out["kind"] == "square":
        out["h"] = out["w"]
    out["label"] = label(out)
    return out


def advice(pan, factor, owned=None):
    """What scaling by `factor` means for this pan: {depth, time, fits: [pans with about the right area]}."""
    if not pan or not factor or abs(factor - 1) < 0.05:
        return None
    a = area(pan)
    want = a * factor
    out = {"factor": round(factor, 2), "depth": round(factor, 2)}
    fam = family(pan)
    if fam == "muffin":
        out["cups"] = round(pan["cups"] * factor)
        out["note"] = f"Makes about {out['cups']} muffins: fill {math.ceil(out['cups'] / pan['cups'])} tin(s) the same way; bake time stays the same."
        out["fits"] = []
        return out
    if factor > 1:
        out["time"] = f"In the same pan it's about {'%g' % round(factor, 2)}× deeper: bake longer (often 15–30% more) and check the middle."
    else:
        out["time"] = f"In the same pan it's about {'%g' % round(factor, 2)}× as deep: check it early, it'll bake faster."
    pool = [p for p in (owned or []) if family(p) == fam] or [p for p in COMMON if family(p) == fam]
    fits = []
    for p in pool:
        r = area(p) / want
        if 0.85 <= r <= 1.18:
            fits.append({**p, "label": p.get("label") or label(p), "match": round(r, 2)})
    fits.sort(key=lambda p: abs(1 - p["match"]))
    if not fits and factor >= 1.6:
        n = math.ceil(factor - 0.15)
        out["split"] = f"Or bake it in {n} pans, each a {label(pan)}, for the same time"
    out["fits"] = fits[:3]
    return out
