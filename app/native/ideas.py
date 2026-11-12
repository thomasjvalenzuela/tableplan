"""Recipe ideas from what's in the kitchen: real recipes only (TheMealDB, Spoonacular, the Wikibooks Cookbook, and
recipe pages found on the web), turned into one safe shape. Nothing here writes a recipe: every idea is a published one.

Everything that comes from outside is untrusted: HTML and wiki markup are stripped, fields are capped, only http(s)
links survive, and web pages count only when they publish schema.org Recipe data.

An idea: {id, source, label, site, title, url, image, minutes, servings, ingredients: [str], steps: [str], why, credit?}
"""

import hashlib
import html
import re
import urllib.parse

MAX_TITLE, MAX_LINE, MAX_STEP, MAX_WHY = 120, 200, 1000, 240
MAX_INGS, MAX_STEPS = 40, 30
_TAG = re.compile(r"<[^>]*>")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

LABELS = {"mealdb": "Recipe · TheMealDB", "spoonacular": "Recipe · Spoonacular"}


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


# ---- found on the web: only pages that publish schema.org Recipe data, from sites not on the denylist
# Social networks and pin boards host copies or links, not the recipe itself. The list is editable in
# Settings → Recipe ideas (add any AI-content or spam domain you run into).
DEFAULT_DENYLIST = ["pinterest.com", "facebook.com", "instagram.com", "tiktok.com", "youtube.com", "reddit.com",
                    "x.com", "twitter.com", "quora.com"]


def host_of(u):
    m = re.match(r"^https?://([^/?#:]+)", str(u or "").strip(), re.I)
    return m.group(1).lower().removeprefix("www.") if m else ""


def denied(u, deny):
    """Is the link's site (or a parent domain) on the denylist?"""
    h = host_of(u)
    return not h or any(h == d or h.endswith("." + d) for d in (x.strip().lower().removeprefix("www.") for x in deny or []) if d)


def clean_denylist(v):
    out = []
    for x in (v if isinstance(v, list) else str(v or "").replace(",", "\n").splitlines())[:200]:
        x = str(x).strip()
        d = host_of(x if "://" in x else "https://" + x)
        if d and re.fullmatch(r"[a-z0-9.-]{1,120}\.[a-z]{2,}", d) and d not in out:
            out.append(d)
    return out


def search_angles(foods, meal=None, max_minutes=None, mood=""):
    """2-4 web search angles for the whole usable inventory. foods = [{"name", "expiring"}], expiring first.
    Angles: what's expiring, the biggest overlap with the kitchen, the requested meal type. Mood only adds words."""
    names = [text(f.get("name"), 40) for f in foods if text(f.get("name"), 40)]
    if not names:
        return []
    exp = [text(f["name"], 40) for f in foods if f.get("expiring") and text(f.get("name"), 40)]
    extra = " ".join(x for x in (text(mood, 60), f"under {int(max_minutes)} minutes" if max_minutes else "") if x)
    sfx = f" {extra}" if extra else ""
    angles = []
    if exp:
        angles.append(f"recipe using {', '.join(exp[:3])}{sfx}")
    angles.append(f"recipe with {', '.join(names[:5])}{sfx}")
    if meal:
        angles.append(f"{text(meal, 20)} recipe with {', '.join((exp or names)[:3])}{sfx}")
    if len(names) > 5:
        angles.append(f"recipe with {', '.join(names[5:9])}{sfx}")
    if len(angles) < 2:
        angles.append(f"easy recipe with {names[0]}{sfx}")
    return list(dict.fromkeys(angles))[:4]


def web_idea(rec, page_url):
    """A recipe read from a page's own schema.org data (scraper output) -> idea, or None."""
    u = url(page_url)
    if not u.startswith("https://") or not isinstance(rec, dict):
        return None
    title = text(rec.get("name"), MAX_TITLE)
    ings = [text(x.get("note") if isinstance(x, dict) else x, MAX_LINE) for x in rec.get("recipeIngredient") or []]
    steps = [text(x.get("text") if isinstance(x, dict) else x, MAX_STEP) for x in rec.get("recipeInstructions") or []]
    ings, steps = [x for x in ings if x], [x for x in steps if x]
    if not title or not ings or not steps:
        return None
    mins = rec.get("totalTimeSeconds")
    serv = rec.get("recipeServings")
    site = host_of(u)
    img = url(rec.get("image_url"))
    return {"id": "web:" + hashlib.sha1(u.encode()).hexdigest()[:14], "source": "web", "label": site, "site": site,
            "title": title, "url": u, "image": img if img.startswith("https://") else "",
            "minutes": int(mins // 60) if isinstance(mins, (int, float)) and 0 < mins < 86400 else None,
            "servings": int(serv) if isinstance(serv, (int, float)) and 0 < serv < 100 else None,
            "ingredients": ings[:MAX_INGS], "steps": steps[:MAX_STEPS], "why": "", "ai": False}


# ---- Wikibooks Cookbook (CC BY-SA): recipes are wikitext with an Ingredients list and a numbered Procedure
WIKIBOOKS = "Wikibooks Cookbook"
WIKI_LICENSE = "CC BY-SA 4.0"
WIKI_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
_ING_H = re.compile(r"ingredient", re.I)
_STEP_H = re.compile(r"procedure|method|direction|instruction|preparation|steps", re.I)
_BOLD = re.compile(r"'{2,5}")


def wiki_clean(s):
    """Wikitext -> plain text: templates, refs, files and markup removed, links turned into their words."""
    s = str(s or "")
    s = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", s, flags=re.S | re.I)
    for _ in range(4):
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:File|Image|Category):[^\]]*\]\]", "", s, flags=re.I)
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", lambda m: m.group(1).split(":")[-1], s)
    s = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", s)
    s = re.sub(r"\[https?://[^\]]*\]", "", s)
    return text(_BOLD.sub("", s), MAX_STEP)


def wikibooks_idea(page_title, wikitext):
    """A Cookbook page's wikitext -> idea (with its licence and attribution), or None if it isn't a recipe."""
    title = text(str(page_title or "").removeprefix("Cookbook:"), MAX_TITLE)
    if not title or "/" in title:
        return None
    sec, sections = "", {}
    for ln in str(wikitext or "").splitlines():
        h = re.match(r"^\s*=+\s*(.*?)\s*=+\s*$", ln)
        if h:
            sec = h.group(1)
            continue
        sections.setdefault(sec, []).append(ln)
    ings, steps = [], []
    for name, lines in sections.items():
        rows = [wiki_clean(re.sub(r"^\s*[*#:]+\s*", "", ln)) for ln in lines if re.match(r"^\s*[*#]", ln)]
        if _ING_H.search(name):
            ings += rows
        elif _STEP_H.search(name):
            steps += rows
    ings, steps = [x for x in ings if x][:MAX_INGS], [x for x in steps if x][:MAX_STEPS]
    if not ings or not steps:
        return None
    page = "Cookbook:" + title
    link = "https://en.wikibooks.org/wiki/" + urllib.parse.quote(page.replace(" ", "_"), safe=":")
    return {"id": "wb:" + hashlib.sha1(page.encode()).hexdigest()[:14], "source": "wikibooks",
            "label": f"{WIKIBOOKS} · CC BY-SA", "site": "en.wikibooks.org", "title": title, "url": link, "image": "",
            "minutes": None, "servings": None, "ingredients": ings, "steps": steps, "why": "", "ai": False,
            "credit": {"site": WIKIBOOKS, "title": page, "url": link, "license": WIKI_LICENSE, "license_url": WIKI_LICENSE_URL,
                       "authors": "Wikibooks contributors"}}


def rank_key(i):
    """One ranked list across sources: fewest missing, then most expiring food used, then rating when there is one."""
    return (i.get("missing_n") or 0, -len(i.get("expiring") or []), -float(i.get("rating") or 0), (i.get("title") or "").lower())


def safe_name(s, cap=60):
    """An inventory name as plain data for a search prompt: no control characters, no markup, capped."""
    return text(s, cap)
