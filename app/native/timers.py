"""Cooking times from recipe text: "10–12 minutes", "1 hour 15 minutes", "1½ hours", "half an hour", "overnight",
"3 minutes per side". Only times the recipe actually states become timers; vague waits ("a few minutes", "until
golden") become a doneness cue without a countdown. Stdlib only.
"""
import re

WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
         "forty-five": 45, "sixty": 60, "ninety": 90}
FRACS = {"½": .5, "¼": .25, "¾": .75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": .125}
UNIT_SEC = {"h": 3600, "m": 60, "s": 1}
LONG_SEC = 6 * 3600          # 6 hours or more: "overnight"-style, a reminder rather than a countdown

_NUM = r"(?:\d+(?:\.\d+)?(?:\s*[½¼¾⅓⅔⅛])?|\d+\s+\d/\d|\d/\d|[½¼¾⅓⅔⅛]|" + "|".join(
    sorted((re.escape(w) for w in WORDS), key=len, reverse=True)) + r")"
_UNIT = r"(hours?|hrs?|hr|h|minutes?|mins?|min|m|seconds?|secs?|sec|s)\b"
_ONE = rf"({_NUM})\s*(?:-|‐)?\s*{_UNIT}"
# "1 hour 15 minutes", "1 hr and 15 min"
COMPOUND = re.compile(rf"\b({_NUM})\s*(hours?|hrs?|hr|h)\b\s*(?:,|and)?\s*({_NUM})\s*(minutes?|mins?|min|m)\b", re.I)
# "10–12 minutes", "10 to 12 min", "1-2 hours"
RANGE = re.compile(rf"\b({_NUM})\s*(?:-|–|—|to|or)\s*({_NUM})\s*{_UNIT}", re.I)
SINGLE = re.compile(rf"\b{_ONE}", re.I)
HALF_HOUR = re.compile(r"\bhalf\s+an?\s+hour\b", re.I)
HOUR_AND_HALF = re.compile(r"\b(an?|one)\s+hour\s+and\s+a\s+half\b", re.I)
OVERNIGHT = re.compile(r"\bovernight\b", re.I)
VAGUE = re.compile(r"\b(?:a\s+few|several|a\s+couple(?:\s+of)?|few)\s+(?:more\s+)?(?:minutes?|mins?|seconds?|hours?)\b", re.I)
PER_SIDE = re.compile(r"^\s*(?:on\s+)?(?:per|each|a)\s+side\b|^\s*on\s+(?:each|both)\s+sides?\b", re.I)
WAIT_VERB = re.compile(r"\b(bake|baking|roast|simmer|boil|cook|fry|saut[eé]|brown|toast|grill|broil|rest|let\s+(?:it\s+)?(?:sit|stand|rest|rise|cool)|"
                       r"rise|proof|chill|refrigerate|marinate|steep|soak|reduce|caramelize|sear|heat|melt|set|cool|freeze|whisk|stir|knead|blend|beat|mix|until)\b", re.I)
CUE = re.compile(r"\buntil\s+([^.;:!?()]{3,70})", re.I)


def _num(s):
    s = (s or "").strip().lower()
    if s in WORDS:
        return float(WORDS[s])
    if s in FRACS:
        return FRACS[s]
    m = re.fullmatch(r"(\d+)\s+(\d)/(\d)", s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.fullmatch(r"(\d)/(\d)", s)
    if m:
        return int(m.group(1)) / int(m.group(2))
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([½¼¾⅓⅔⅛])?", s)
    if m:
        return float(m.group(1)) + (FRACS[m.group(2)] if m.group(2) else 0)
    return None


def _unit(u):
    u = (u or "").lower()
    return UNIT_SEC["h"] if u.startswith("h") else UNIT_SEC["s"] if u.startswith("s") else UNIT_SEC["m"]


def fmt(sec):
    """Short human duration: 45 sec, 12 min, 1 h 15 min."""
    sec = int(round(sec))
    if sec < 60:
        return f"{sec} sec"
    h, m = divmod(round(sec / 60), 60)
    if not h:
        return f"{m} min"
    return f"{h} h" + (f" {m} min" if m else "")


def _range_label(lo, hi, suffix=""):
    """"10–12 min · check at 10" for ranges (timers start at the low end); suffix goes after the duration."""
    if not hi or hi == lo:
        return fmt(lo) + suffix
    for unit, size, name in (("s", 1, "sec"), ("m", 60, "min"), ("h", 3600, "h")):
        top = 60 if unit != "h" else 10 ** 6
        if lo % size == 0 and hi % size == 0 and lo / size < top and hi / size < top and lo >= size:
            x, y = int(lo // size), int(hi // size)
            return f"{x}–{y} {name}{suffix} · check at {x}" + (" h" if unit == "h" else "")
    return f"{fmt(lo)}–{fmt(hi)}{suffix} · check at {fmt(lo)}"


def parse(text):
    """Every stated time in a step, in reading order: [{sec, high_sec, label, kind, source}].
    kind is countdown, per_side (cook each side) or long (overnight / 6 h+, a reminder rather than a countdown)."""
    text = text or ""
    found, taken = [], []

    def free(a, b):
        return all(b <= x or a >= y for x, y in taken)

    def add(a, b, lo, hi=None, kind=None):
        if lo is None or lo <= 0 or not free(a, b):
            return
        taken.append((a, b))
        if kind is None:
            kind = "per_side" if PER_SIDE.match(text[b:b + 20]) else "long" if lo >= LONG_SEC else "countdown"
        if kind == "long" and OVERNIGHT.search(text[a:b]):
            label = "Overnight"
        else:
            label = _range_label(lo, hi, " per side" if kind == "per_side" else "")
            if kind == "long":
                label += " · overnight"
        found.append({"sec": int(round(lo)), "high_sec": int(round(hi)) if hi and hi != lo else None, "label": label,
                      "kind": kind, "source": text[a:b], "at": a})

    for m in VAGUE.finditer(text):
        taken.append(m.span())                       # "a few minutes": a cue, not a number
    for m in HOUR_AND_HALF.finditer(text):
        add(*m.span(), 5400)
    for m in HALF_HOUR.finditer(text):
        add(*m.span(), 1800)
    for m in COMPOUND.finditer(text):
        h, mi = _num(m.group(1)), _num(m.group(3))
        if h is not None and mi is not None:
            add(*m.span(), h * 3600 + mi * 60)
    for m in RANGE.finditer(text):
        lo, hi, u = _num(m.group(1)), _num(m.group(2)), _unit(m.group(3))
        if lo is not None and hi is not None and hi >= lo:
            add(*m.span(), lo * u, hi * u)
    for m in SINGLE.finditer(text):
        n, unit = _num(m.group(1)), m.group(2)
        if n is None:
            continue
        if unit.lower() in ("m", "s", "h") and not re.search(r"\d", m.group(1)):
            continue                                 # "a m", "one s": not a time
        if unit.lower() == "m" and re.match(r"\s*[a-z]", text[m.end():m.end() + 2] or "", re.I):
            continue
        add(*m.span(), n * _unit(unit))
    for m in OVERNIGHT.finditer(text):
        add(*m.span(), 8 * 3600, kind="long")
    found.sort(key=lambda x: x["at"])
    for f in found:
        f.pop("at", None)
    return found


def cue(text):
    """The doneness cue of a step that waits without a stated time ("until golden brown"), else None."""
    m = CUE.search(text or "")
    if not m or not WAIT_VERB.search(text[:m.start()] + " until"):
        return None
    c = re.sub(r"\s+", " ", m.group(1)).strip(" ,")
    c = re.split(r"\b(?:then|and then|about|approximately|or about)\b", c, maxsplit=1)[0].strip(" ,")
    return f"until {c}" if len(c) >= 3 else None


def step_timing(text):
    """Timers and cue for one step of text."""
    return {"timers": parse(text), "cue": cue(text)}


def stated_seconds(texts):
    """Every duration (low and high ends) the recipe states, for checking AI-provided timers."""
    out = set()
    for t in texts:
        for x in parse(t):
            out.add(x["sec"])
            if x["high_sec"]:
                out.add(x["high_sec"])
    return out


def hints(texts):
    """Short list of the times a recipe states, e.g. ['10–12 min · check at 10', '1 h 15 min']."""
    seen, out = set(), []
    for t in texts:
        for x in parse(t):
            if x["label"] not in seen:
                seen.add(x["label"]); out.append(x["label"])
    return out[:20]
