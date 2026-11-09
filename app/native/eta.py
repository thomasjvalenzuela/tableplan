"""Start-to-finish time estimate for a recipe: prep, preheat, cooking, resting, split into hands-on and passive time.

Built only from what the recipe says, plus a small documented table of typical durations for the parts recipes don't
time (knife work, preheating, water coming to a boil, "until soft"). Stdlib only.
"""
import re
import statistics

from . import timers as T

# ---- the table (minutes). Kept deliberately conservative; the household's own cooks correct it over time.
PER_INGREDIENT = 1.0                      # measuring / opening / handling each ingredient
KNIFE = {                                 # extra per ingredient line that needs this knife work
    "chop": 2.0, "chopped": 2.0, "dice": 3.0, "diced": 3.0, "mince": 3.0, "minced": 3.0, "slice": 2.0, "sliced": 2.0,
    "grate": 3.0, "grated": 3.0, "shred": 3.0, "shredded": 3.0, "peel": 2.0, "peeled": 2.0, "julienne": 4.0,
    "zest": 2.0, "zested": 2.0, "trim": 2.0, "trimmed": 2.0, "crush": 1.0, "crushed": 1.0, "cube": 3.0, "cubed": 3.0,
    "quarter": 1.0, "quartered": 1.0, "halve": 1.0, "halved": 1.0, "core": 2.0, "cored": 2.0, "seed": 2.0, "seeded": 2.0,
}
PREP_MIN = 5.0
PREHEAT = {"conventional": 12.0, "convection": 10.0, "air_fryer": 3.0, "toaster_oven": 6.0}
WATER_BOIL = 10.0
# "until …" with no stated time: (pattern, minutes, passive?)
UNTIL = [
    (r"doubled|puffy|risen", 60.0, True), (r"set|firm", 30.0, True), (r"thicken|reduc|syrupy|coats? the back", 10.0, False),
    (r"tender|cooked through|no longer pink|done", 12.0, False), (r"brown|crisp|golden|charred|caramel", 8.0, False),
    (r"soft|translucent|wilt|fragrant|melt|combined|smooth|dissolv|incorporat", 4.0, False),
]
UNTIL_DEFAULT = 5.0
STEP_HANDLING = 1.0                       # a step with no wait at all: reading it and doing it
LONG_PASSIVE = 120                        # minutes: "overnight" and other ≥2 h waits are shown separately

PASSIVE = re.compile(r"\b(bake|baking|roast|rest|resting|let\s+(?:it\s+)?(?:sit|stand|rest|rise|cool)|marinate|chill|refrigerate|"
                     r"rise|proof|freeze|cool|set aside|soak|steep|simmer|braise|slow[- ]cook|pressure[- ]cook|boil|poach|"
                     r"dry|drain|stand|cook\s+(?:the\s+)?(?:pasta|spaghetti|noodles|rice|potatoes|macaroni))\b", re.I)
ACTIVE = re.compile(r"\b(saut[eé]|fry|sear|stir[- ]fry|stir|whisk|knead|flip|toss|brown|grill|broil|toast|blend|mix|beat|fold|"
                    r"shape|roll|form|assemble|baste|scramble)\b", re.I)
OVEN = re.compile(r"\b(oven|bake|baking|roast|broil)\b|°", re.I)
TEMP = re.compile(r"\b(\d{3})\s*°?\s*(F|C)?\b")
BOIL = re.compile(r"\bbring\b[^.]*\bto\s+(?:a\s+)?(?:rolling\s+)?boil\b|\bboil(?:ing)?\s+(?:salted\s+)?water\b", re.I)
BOIL_FOOD = re.compile(r"pasta|spaghetti|noodle|macaroni|penne|linguine|fettuccine|potato|rice|water", re.I)
MEANWHILE = re.compile(r"^\s*(?:meanwhile|in the meantime|while\b)|\bwhile the\b|\bmeanwhile\b", re.I)
QTY = re.compile(r"^\s*(\d+(?:\.\d+)?|\d+/\d+)")


def _knife(line):
    words = re.findall(r"[a-z]+", (line or "").lower())
    per = max((KNIFE[w] for w in words if w in KNIFE), default=0.0)
    if not per:
        return 0.0
    m = QTY.match(line or "")
    n = 1.0
    if m and "/" not in m.group(1):
        unitless = not re.match(r"\s*[\d.]+\s*(?:cups?|tbsp|tsp|tablespoons?|teaspoons?|oz|ounces?|lbs?|pounds?|g|grams?|kg|ml)\b", line, re.I)
        if unitless:
            n = min(float(m.group(1)), 6.0)
    return per * (1 + 0.5 * (n - 1))


def prep_minutes(ingredient_lines, step_texts=()):
    """Hands-on prep: handling each ingredient plus knife work, at least PREP_MIN."""
    lines = [x for x in ingredient_lines if (x or "").strip()]
    total = PER_INGREDIENT * len(lines) + sum(_knife(x) for x in lines)
    return int(max(PREP_MIN, round(total)))


def _until_minutes(cue):
    for pat, mins, passive in UNTIL:
        if re.search(pat, cue or "", re.I):
            return mins, passive
    return UNTIL_DEFAULT, False


def estimate(ingredient_lines, steps, oven="conventional", stated=None):
    """steps: list of step texts. stated: {"prep","cook","total"} minutes the recipe itself gives (or None).
    Returns minutes: total, active (hands-on), passive, plus parts, flags and what it's based on."""
    stated = {k: v for k, v in (stated or {}).items() if v}
    prep = prep_minutes(ingredient_lines, steps)
    parts = [{"k": "prep", "label": "Prep", "min": prep, "active": True}]
    approx, long_waits, oven_temp, boil_added = False, [], None, False
    timeline = []                       # per step: (minutes, passive)
    for text in steps:
        text = text or ""
        if oven_temp is None and OVEN.search(text):
            m = TEMP.search(text)
            if m and 200 <= int(m.group(1)) <= 550 or (m and (m.group(2) or "").upper() == "C"):
                oven_temp = m.group(0)
        ts = T.parse(text)
        passive = bool(PASSIVE.search(text)) and not (ACTIVE.search(text) and not re.search(r"\b(bake|roast|rest|chill|marinate|rise|simmer|pasta|noodles)\b", text, re.I))
        mins = 0.0
        for t in ts:
            m = t["sec"] / 60.0
            if t["kind"] == "per_side":
                m *= 2
            if t["kind"] == "long" or (passive and m >= LONG_PASSIVE):
                long_waits.append(t["label"] if t["kind"] == "long" else T.fmt(t["sec"]))
                continue
            mins += m
        if not ts:
            cue = T.cue(text)
            if cue:
                mins, p2 = _until_minutes(cue)
                passive = passive or p2
                approx = True
            else:
                mins = STEP_HANDLING
                passive = False
        if BOIL.search(text) and BOIL_FOOD.search(text) and not ts and not boil_added:
            timeline.append((WATER_BOIL, True, text))
            boil_added = True
            parts.append({"k": "boil", "label": "Water to boil", "min": WATER_BOIL, "active": False})
        timeline.append((mins, passive, text))
    # parallel work: a passive wait overlaps the hands-on steps that say "meanwhile" / "while the … bakes"
    overlap = 0.0
    for i, (mins, passive, _) in enumerate(timeline):
        if not passive:
            continue
        budget = mins
        for m2, p2, t2 in timeline[i + 1:]:
            if p2 or not MEANWHILE.search(t2) or budget <= 0:
                break
            o = min(budget, m2)
            overlap += o
            budget -= o
    cook_active = sum(m for m, p, _ in timeline if not p)
    cook_passive = sum(m for m, p, _ in timeline if p)
    preheat_add = 0.0
    if oven_temp:
        ph = PREHEAT.get(oven or "conventional", PREHEAT["conventional"])
        preheat_add = max(0.0, ph - prep)           # it heats while you prep
        parts.append({"k": "preheat", "label": "Preheat", "min": ph, "adds": round(preheat_add), "overlaps": preheat_add == 0,
                      "active": False})
    if cook_active:
        parts.append({"k": "cook", "label": "Cook (hands-on)", "min": round(cook_active), "active": True})
    if cook_passive - (WATER_BOIL if boil_added else 0) > 0:
        parts.append({"k": "wait", "label": "Bake, simmer & rest", "min": round(cook_passive - (WATER_BOIL if boil_added else 0)),
                      "active": False})
    if overlap:
        parts.append({"k": "overlap", "label": "Done while it cooks", "min": -round(overlap), "active": None})
    active = prep + cook_active
    total = prep + preheat_add + cook_active + cook_passive - overlap
    out = {"total": max(1, round(total)), "active": max(1, round(min(active, total))), "passive": max(0, round(total - min(active, total))),
           "approx": approx, "long": long_waits[:2], "parts": parts, "stated": stated or None, "based_on": "steps"}
    st_total = stated.get("total") or ((stated.get("prep") or 0) + (stated.get("cook") or 0)) or None
    if st_total and abs(st_total - out["total"]) <= 0.25 * st_total:
        out["total"], out["based_on"] = int(st_total), "recipe"
        out["active"] = min(out["active"], out["total"])
        out["passive"] = out["total"] - out["active"]
    return out


def clamp_speed(f):
    return max(0.7, min(1.6, f))


def speed_factor(ratios):
    """Median of actual/estimate across the household's cooks (at least 2), clamped to 0.7–1.6. 1.0 without data."""
    r = [x for x in ratios if x and 0.3 <= x <= 3]
    return clamp_speed(statistics.median(r)) if len(r) >= 2 else 1.0


def keep_session(actual_min, estimate_min):
    """Ignore cook sessions far off the estimate (left open, or closed right away)."""
    return bool(estimate_min) and 0.3 * estimate_min <= actual_min <= 3 * estimate_min


def label(eta):
    """"≈ 45 min · 20 hands-on", "≈ 1 h 10 min · 25 hands-on · plus overnight"."""
    if not eta:
        return ""
    t = eta.get("shown") or eta["total"]
    s = f"≈ {fmt_min(t)}"
    if eta.get("active") and eta["active"] < t:
        s += f" · {eta['active']} hands-on"
    if eta.get("long"):
        s += " · plus " + ("overnight" if any("vernight" in x for x in eta["long"]) else eta["long"][0])
    return s


def fmt_min(m):
    m = int(round(m))
    return f"{m} min" if m < 60 else f"{m // 60} h" + (f" {m % 60} min" if m % 60 else "")
