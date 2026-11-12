"""Recipe ideas from what's in the kitchen: turning TheMealDB / Spoonacular recipes and AI ideas into one safe shape.

Everything that comes from outside is untrusted: HTML is stripped, fields are capped, only http(s) links survive,
and AI ideas are checked against the inventory before anyone sees them.

An idea: {id, source, label, title, url, image, minutes, servings, ingredients: [str], steps: [str], why, ai}
"""

import html
import re

MAX_TITLE, MAX_LINE, MAX_STEP, MAX_WHY = 120, 200, 1000, 240
MAX_INGS, MAX_STEPS = 40, 30
AI_MAX_MISSING = 2
_TAG = re.compile(r"<[^>]*>")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

LABELS = {"mealdb": "Recipe · TheMealDB", "spoonacular": "Recipe · Spoonacular", "ai": "AI-created · not tested"}


def text(v, cap=MAX_LINE, multiline=False):
    """Plain text: tags removed, entities decoded, control characters dropped, whitespace tidied, capped."""
    s = html.unescape(_TAG.sub(" ", str(v or "")))
    s = _CTRL.sub(" ", s)
    s = "\n".join(" ".join(ln.split()) for ln in s.splitlines()) if multiline else " ".join(s.split())
    return s.strip()[:cap].strip()


def no_urls(s):
    return " ".join(_URL.sub("", s).split())


def url(v):
    u = str(v or "").strip()
    return u[:500] if re.match(r"^https?://[^\s<>\"']+$", u) else ""


def split_steps(instructions):
    """MealDB instructions are one block: split into steps on line breaks and "STEP 1" markers."""
    s = text(instructions, 8000, multiline=True)
    parts = re.split(r"\n+|(?i:\bstep\s*\d+\s*[:.)-]?)", s)
    out = []
    for p in parts:
        p = re.sub(r"^\s*\d+[.)]\s*", "", p or "").strip()
        if len(p) > 2:
            out.append(p[:MAX_STEP])
    return out[:MAX_STEPS]


def mealdb_idea(meal):
    """A TheMealDB meal (lookup.php) -> idea, or None."""
    if not isinstance(meal, dict) or not str(meal.get("idMeal") or "").isdigit():
        return None
    ings = []
    for i in range(1, 21):
        name, measure = text(meal.get(f"strIngredient{i}"), 80), text(meal.get(f"strMeasure{i}"), 60)
        if name:
            ings.append(f"{measure} {name}".strip()[:MAX_LINE])
    steps = split_steps(meal.get("strInstructions"))
    title = text(meal.get("strMeal"), MAX_TITLE)
    if not title or not ings or not steps:
        return None
    mid = meal["idMeal"]
    return {"id": f"mealdb:{mid}", "source": "mealdb", "label": LABELS["mealdb"], "title": title,
            "url": url(meal.get("strSource")) or f"https://www.themealdb.com/meal/{mid}",
            "image": url(meal.get("strMealThumb")), "minutes": None, "servings": None,
            "ingredients": ings[:MAX_INGS], "steps": steps, "why": "", "ai": False,
            "category": text(meal.get("strCategory"), 40), "area": text(meal.get("strArea"), 40)}


def spoon_idea(info):
    """A Spoonacular recipe (informationBulk) -> idea, or None."""
    if not isinstance(info, dict) or not isinstance(info.get("id"), int):
        return None
    ings = [text(x.get("original"), MAX_LINE) for x in info.get("extendedIngredients") or [] if isinstance(x, dict)]
    ings = [x for x in ings if x]
    steps = []
    for block in info.get("analyzedInstructions") or []:
        for st in (block or {}).get("steps") or []:
            t = text((st or {}).get("step"), MAX_STEP)
            if t:
                steps.append(t)
    if not steps:
        steps = split_steps(info.get("instructions"))
    title = text(info.get("title"), MAX_TITLE)
    if not title or not ings or not steps:
        return None
    mins = info.get("readyInMinutes")
    serv = info.get("servings")
    return {"id": f"spoon:{info['id']}", "source": "spoonacular", "label": LABELS["spoonacular"], "title": title,
            "url": url(info.get("sourceUrl")) or url(info.get("spoonacularSourceUrl")),
            "image": url(info.get("image")), "minutes": int(mins) if isinstance(mins, (int, float)) and 0 < mins < 1440 else None,
            "servings": int(serv) if isinstance(serv, (int, float)) and 0 < serv < 100 else None,
            "ingredients": ings[:MAX_INGS], "steps": steps[:MAX_STEPS], "why": "", "ai": False}


AI_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["ideas"],
    "properties": {"ideas": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["title", "why", "servings", "minutes", "ingredients", "steps"],
        "properties": {
            "title": {"type": "string"}, "why": {"type": "string"},
            "servings": {"type": "integer"}, "minutes": {"type": "integer"},
            "ingredients": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["food", "qty", "unit", "note", "from"],
                "properties": {"food": {"type": "string"}, "qty": {"type": "number"}, "unit": {"type": "string"},
                               "note": {"type": "string"}, "from": {"type": "string", "enum": ["inventory", "staple", "missing"]}}}},
            "steps": {"type": "array", "items": {"type": "string"}}}}}}}


def check_ai_idea(raw, have, is_staple, enough, fmt):
    """Validate one AI idea against the kitchen. have(food) -> stock entries [(free, unit)] or None when not in the
    kitchen; is_staple(food) -> bool; enough(qty, unit, entries) -> bool; fmt(qty, unit, food) -> "2 cups rice".
    Returns (idea, None) or (None, reason). Quantities over what's on hand, more than 2 missing foods, or no steps reject
    the idea; links are removed from every field."""
    if not isinstance(raw, dict):
        return None, "not an idea"
    title = no_urls(text(raw.get("title"), MAX_TITLE))
    if not title:
        return None, "no title"
    ings, missing = [], []
    for x in (raw.get("ingredients") or [])[:MAX_INGS]:
        if not isinstance(x, dict):
            continue
        food = no_urls(text(x.get("food"), 80))
        if not food:
            continue
        try:
            qty = float(x.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty < 0 or qty > 100000:
            return None, f"odd amount for {food}"
        unit = no_urls(text(x.get("unit"), 20))
        note = no_urls(text(x.get("note"), 80))
        line = (fmt(qty, unit, food) if qty else food) + (f", {note}" if note else "")
        src = x.get("from")
        stock = have(food)
        if src == "staple" and is_staple(food):
            ings.append(line)
            continue
        if src == "inventory" and stock:
            if qty and not enough(qty, unit, stock):
                return None, f"uses more {food} than you have"
            ings.append(line)
            continue
        if src == "inventory" and is_staple(food):
            ings.append(line)
            continue
        missing.append(line)   # claimed to be at home but isn't, or openly missing
        ings.append(line)
    if len(missing) > AI_MAX_MISSING:
        return None, f"needs {len(missing)} things you don't have"
    steps = [no_urls(text(s, MAX_STEP)) for s in (raw.get("steps") or [])[:MAX_STEPS] if isinstance(s, str)]
    steps = [s for s in steps if s]
    if not ings or not steps:
        return None, "no ingredients or steps"
    mins = raw.get("minutes")
    serv = raw.get("servings")
    return {"source": "ai", "label": LABELS["ai"], "title": title, "url": "", "image": "",
            "minutes": int(mins) if isinstance(mins, int) and 0 < mins < 1440 else None,
            "servings": int(serv) if isinstance(serv, int) and 0 < serv < 50 else None,
            "ingredients": ings, "steps": steps, "why": no_urls(text(raw.get("why"), MAX_WHY)), "ai": True,
            "ai_missing": missing}, None


def safe_name(s, cap=60):
    """An inventory name as plain data for the AI: no control characters, no markup, capped."""
    return text(s, cap)
