"""Recipe scraper: turns a recipe web page into a Mealie-shaped recipe dict.

Sources, in priority order:
  1. schema.org ``Recipe`` objects in JSON-LD (``@graph``, lists, nested
     entities, ``@type`` arrays, and lightly malformed JSON are handled).
  2. schema.org microdata (``itemscope``/``itemprop``).

If neither yields both ingredients and instructions, :class:`NoRecipe` is
raised carrying a cleaned visible-text extract of the page so the caller can
hand it to an AI extractor instead.

Network access is the caller's job: ``scrape(url, fetch)`` calls
``fetch(url) -> (final_url, html_text)``, and the caller is responsible for
SSRF protection, size limits and timeouts.

Stdlib only.
"""

import html
import json
import re
import uuid
from html.parser import HTMLParser
from urllib.parse import urljoin

__all__ = ["scrape", "parse_html", "NoRecipe", "clean_text", "parse_duration"]

PAGE_TEXT_LIMIT = 20_000


class NoRecipe(Exception):
    """No structured recipe was found. ``page_text`` holds the visible page text."""

    def __init__(self, page_text):
        super().__init__("no structured recipe data found on page")
        self.page_text = page_text


# --------------------------------------------------------------------------
# Minimal, error-tolerant DOM
# --------------------------------------------------------------------------

_VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
_BLOCK = frozenset(
    "address article aside blockquote br dd details div dl dt fieldset figcaption "
    "figure form h1 h2 h3 h4 h5 h6 header hr li main ol p pre section summary "
    "table td th tr ul".split()
)
_INVISIBLE = frozenset(
    "script style noscript template svg nav footer head iframe canvas object".split()
)


class _Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []
        self.parent = parent

    def iter(self):
        stack = [self]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(c for c in reversed(node.children) if isinstance(c, _Node))

    def raw_text(self):
        return "".join(c if isinstance(c, str) else c.raw_text() for c in self.children)

    def block_text(self, skip=frozenset()):
        """Text with newlines at block boundaries; subtrees tagged in ``skip`` are omitted."""
        out = []

        def walk(node):
            for child in node.children:
                if isinstance(child, str):
                    out.append(child)
                elif child.tag not in skip and "hidden" not in child.attrs:
                    block = child.tag in _BLOCK
                    if block:
                        out.append("\n")
                    walk(child)
                    if block:
                        out.append("\n")

        walk(self)
        return "".join(out)


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        if tag in ("li", "p"):
            self._autoclose(tag)
        parent = self.stack[-1]
        node = _Node(tag, {k: (v if v is not None else "") for k, v in attrs}, parent)
        parent.children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def _autoclose(self, tag):
        # An open <li>/<p> is implicitly closed by a new sibling of the same kind.
        barrier = {"li": ("ul", "ol"), "p": ()}[tag]
        for i in range(len(self.stack) - 1, 0, -1):
            name = self.stack[i].tag
            if name == tag:
                del self.stack[i:]
                return
            if name in barrier or (tag == "p" and name not in ("span", "b", "i", "em", "strong", "a")):
                return

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _build_tree(text):
    builder = _TreeBuilder()
    builder.feed(text)
    builder.close()
    return builder.root


# --------------------------------------------------------------------------
# Text cleaning
# --------------------------------------------------------------------------

_TAG_RE = re.compile(r"<!--.*?-->|</?[a-zA-Z][^<>]*>", re.S)
_BREAK_TAG_RE = re.compile(r"<\s*(?:br\s*/?|/\s*(?:p|li|div|h[1-6]|tr)\s*)>", re.I)
_SPACE_CHARS = dict.fromkeys(map(ord, "\u00a0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000\t\r\f\v"), " ")
_SPACE_CHARS.update(dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None))
_VULGAR = {
    "1/2": "\u00bd", "1/3": "\u2153", "2/3": "\u2154", "1/4": "\u00bc", "3/4": "\u00be",
    "1/5": "\u2155", "2/5": "\u2156", "3/5": "\u2157", "4/5": "\u2158", "1/6": "\u2159",
    "5/6": "\u215a", "1/7": "\u2150", "1/8": "\u215b", "3/8": "\u215c", "5/8": "\u215d",
    "7/8": "\u215e", "1/9": "\u2151", "1/10": "\u2152",
}
_FRAC_CHARS = "".join(_VULGAR.values())
_FRAC_SLASH_RE = re.compile(r"(\d+)\s*[\u2044\u2215]\s*(\d+)")
_DIGIT_FRAC_RE = re.compile(r"(\d)([" + _FRAC_CHARS + r"])")
_SPACE_BEFORE_PUNCT_RE = re.compile(r" +([,.;:!?)])")


def _fraction_slash(match):
    key = f"{match.group(1)}/{match.group(2)}"
    return _VULGAR.get(key, key)


def clean_text(value, multiline=False):
    """Unescape entities, strip tags, normalise whitespace and fraction characters.

    With ``multiline`` the result keeps one line per paragraph/list item and
    drops empty lines; otherwise everything collapses onto one line.
    """
    if value is None:
        return ""
    s = str(value)
    for _ in range(2):  # some sites double-encode (&amp;#8532;)
        unescaped = html.unescape(s)
        if unescaped == s:
            break
        s = unescaped
    s = _BREAK_TAG_RE.sub("\n", s)
    s = _TAG_RE.sub(" ", s)
    s = s.translate(_SPACE_CHARS)
    s = _FRAC_SLASH_RE.sub(_fraction_slash, s)
    s = _DIGIT_FRAC_RE.sub(r"\1 \2", s)
    lines = []
    for line in s.split("\n"):
        line = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", " ".join(line.split()))
        if line:
            lines.append(line)
    return "\n".join(lines) if multiline else " ".join(lines)


# --------------------------------------------------------------------------
# Value helpers
# --------------------------------------------------------------------------

def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _first_text(value):
    for item in _as_list(value):
        if isinstance(item, dict):
            item = item.get("@value", item.get("name", item.get("text")))
        if isinstance(item, (str, int, float)) and not isinstance(item, bool):
            text = clean_text(item)
            if text:
                return text
    return ""


def _types(node):
    out = set()
    for t in _as_list(node.get("@type")):
        if isinstance(t, str):
            out.add(re.split(r"[/:#]", t)[-1].lower())
    return out


_DURATION_RE = re.compile(
    r"^P(?:(\d+(?:[.,]\d+)?)Y)?(?:(\d+(?:[.,]\d+)?)M)?(?:(\d+(?:[.,]\d+)?)W)?(?:(\d+(?:[.,]\d+)?)D)?"
    r"(?:T(?:(\d+(?:[.,]\d+)?)H)?(?:(\d+(?:[.,]\d+)?)M)?(?:(\d+(?:[.,]\d+)?)S)?)?$",
    re.I,
)
_DURATION_UNITS = (365 * 86400, 30 * 86400, 7 * 86400, 86400, 3600, 60, 1)


def parse_duration(value):
    """ISO 8601 duration (``PT1H15M``) -> seconds, or None if absent/invalid/zero."""
    text = _first_text(value).replace(" ", "")
    match = _DURATION_RE.match(text)
    if not text or not match:
        return None
    total = sum(
        float(part.replace(",", ".")) * unit
        for part, unit in zip(match.groups(), _DURATION_UNITS)
        if part
    )
    return int(round(total)) or None


# --------------------------------------------------------------------------
# JSON-LD
# --------------------------------------------------------------------------

_TRAILING_COMMA_RE = re.compile(r'"(?:\\.|[^"\\])*"|,(\s*[}\]])', re.S)
_JSON_WRAPPER_RE = re.compile(r"^\s*(?:<!--|<!\[CDATA\[|//\s*<!\[CDATA\[)|(?:-->|\]\]>|//\s*\]\]>)\s*$")


def _loads_lenient(text):
    try:
        return json.loads(text, strict=False)
    except ValueError:
        pass
    repaired = _JSON_WRAPPER_RE.sub("", text.strip())
    repaired = _TRAILING_COMMA_RE.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(0), repaired)
    repaired = repaired.rstrip().rstrip(";")
    try:
        return json.loads(repaired, strict=False)
    except ValueError:
        return None


def _jsonld_blocks(root):
    for node in root.iter():
        if node.tag == "script" and node.attrs.get("type", "").split(";")[0].strip().lower() == "application/ld+json":
            data = _loads_lenient(node.raw_text())
            if data is not None:
                yield data


def _walk_entities(data, depth=0):
    """Yield every dict entity, descending through lists, @graph and nested values."""
    if depth > 12:
        return
    if isinstance(data, list):
        for item in data:
            yield from _walk_entities(item, depth + 1)
    elif isinstance(data, dict):
        yield data
        for key, value in data.items():
            if key != "@context" and isinstance(value, (dict, list)):
                yield from _walk_entities(value, depth + 1)


def _jsonld_recipes(root):
    recipes, index = [], {}
    for block in _jsonld_blocks(root):
        for entity in _walk_entities(block):
            if isinstance(entity.get("@id"), str) and len(entity) > 1:
                index.setdefault(entity["@id"], entity)
            if "recipe" in _types(entity):
                recipes.append(entity)
    return recipes, index


# --------------------------------------------------------------------------
# Microdata
# --------------------------------------------------------------------------

_URL_PROP_TAGS = {"img": "src", "audio": "src", "video": "src", "source": "src", "embed": "src",
                  "iframe": "src", "track": "src", "a": "href", "link": "href", "area": "href",
                  "object": "data"}


def _microdata_value(node):
    if "itemscope" in node.attrs:
        return _microdata_item(node)
    attrs = node.attrs
    if "content" in attrs:
        return attrs["content"]
    if node.tag in _URL_PROP_TAGS:
        return attrs.get(_URL_PROP_TAGS[node.tag], "")
    if node.tag == "time" and attrs.get("datetime"):
        return attrs["datetime"]
    if node.tag in ("data", "meter") and "value" in attrs:
        return attrs["value"]
    return node.block_text(skip=_INVISIBLE)


def _microdata_item(scope):
    item = {"@type": [t for t in scope.attrs.get("itemtype", "").split() if t]}
    stack = [c for c in reversed(scope.children) if isinstance(c, _Node)]
    while stack:
        node = stack.pop()
        props = node.attrs.get("itemprop", "").split()
        if props:
            value = _microdata_value(node)
            for prop in props:
                item.setdefault(prop, []).append(value)
        if "itemscope" not in node.attrs:  # nested scopes own their own properties
            stack.extend(c for c in reversed(node.children) if isinstance(c, _Node))
    return item


def _microdata_recipes(root):
    out = []
    for node in root.iter():
        if "itemscope" in node.attrs and "itemprop" not in node.attrs:
            item = _microdata_item(node)
            if "recipe" in _types(item):
                out.append(item)
    return out


# --------------------------------------------------------------------------
# Normalisation to Mealie's recipe shape
# --------------------------------------------------------------------------

def _resolve(value, index):
    if isinstance(value, dict) and set(value) == {"@id"}:
        return index.get(value["@id"], value)
    return value


_DIM_RE = re.compile(r"(\d{2,5})x(\d{2,5})")


def _best_image(value, index, base_url):
    best, best_area = None, -1
    for item in _as_list(_resolve(value, index)):
        item = _resolve(item, index)
        width = height = 0
        if isinstance(item, dict):
            url = _first_text(item.get("url") or item.get("contentUrl"))
            try:
                width = int(_first_text(item.get("width")) or 0)
                height = int(_first_text(item.get("height")) or 0)
            except ValueError:
                width = height = 0
        else:
            url = _first_text(item)
        if not url:
            continue
        if not (width and height):
            dims = _DIM_RE.search(url.rsplit("/", 1)[-1])
            if dims:
                width, height = int(dims.group(1)), int(dims.group(2))
        area = width * height
        if area > best_area:
            best, best_area = url, area
    return urljoin(base_url, best) if best else None


def _ingredients(recipe):
    lines = []
    for value in _as_list(recipe.get("recipeIngredient")) or _as_list(recipe.get("ingredients")):
        if isinstance(value, dict):
            value = value.get("text") or value.get("name")
        if isinstance(value, (str, int, float)):
            lines.extend(clean_text(value, multiline=True).split("\n"))
    return [
        {
            "referenceId": str(uuid.uuid4()),
            "note": line,
            "display": line,
            "originalText": line,
            "quantity": 0,
            "unit": None,
            "food": None,
            "title": None,
        }
        for line in lines
        if line
    ]


def _instructions(recipe, index):
    steps = []
    pending_title = [""]

    def add(text):
        for line in clean_text(text, multiline=True).split("\n"):
            if line:
                steps.append({
                    "id": str(uuid.uuid4()),
                    "title": pending_title[0],
                    "text": line,
                    "ingredientReferences": [],
                })
                pending_title[0] = ""

    def walk(value, depth=0):
        if depth > 8:
            return
        value = _resolve(value, index)
        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
        elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
            add(value)
        elif isinstance(value, dict):
            types = _types(value)
            children = value.get("itemListElement")
            if "howtosection" in types or ("itemlist" in types and children is not None):
                title = _first_text(value.get("name"))
                if title and "howtosection" in types:
                    pending_title[0] = title
                walk(children, depth + 1)
                return
            if _first_text(value.get("text")):
                walk(value["text"], depth + 1)
            elif children is not None:
                walk(children, depth + 1)
            else:
                walk(value.get("description") or value.get("name"), depth + 1)

    walk(recipe.get("recipeInstructions"))
    return steps


def _tags(recipe):
    seen, tags = set(), []
    for key in ("keywords", "recipeCategory", "recipeCuisine"):
        for value in _as_list(recipe.get(key)):
            if isinstance(value, dict):
                value = value.get("name")
            if not isinstance(value, str):
                continue
            for part in clean_text(value).split(","):
                name = part.strip()
                if name and name.lower() not in seen:
                    seen.add(name.lower())
                    tags.append({"name": name})
    return tags


_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _yield(recipe):
    texts = [_first_text(v) for v in _as_list(recipe.get("recipeYield") or recipe.get("yield"))]
    texts = [t for t in texts if t]
    if not texts:
        return "", 0.0
    servings = 0.0
    for t in texts:
        match = _NUMBER_RE.search(t)
        if match:
            servings = float(match.group().replace(",", "."))
            break
    label = next((t for t in texts if re.search(r"[^\W\d_]", t)), texts[0])
    return label, servings


def _to_mealie(recipe, index, page_url):
    prep = parse_duration(recipe.get("prepTime"))
    perform = parse_duration(recipe.get("cookTime") or recipe.get("performTime"))
    total = parse_duration(recipe.get("totalTime"))
    if total is None and (prep or perform):
        total = (prep or 0) + (perform or 0)
    recipe_yield, servings = _yield(recipe)
    return {
        "name": _first_text(recipe.get("name") or recipe.get("headline")),
        "description": _first_text(recipe.get("description")),
        "recipeServings": servings,
        "recipeYield": recipe_yield,
        "prepTimeSeconds": prep,
        "performTimeSeconds": perform,
        "totalTimeSeconds": total,
        "orgURL": page_url,
        "image_url": _best_image(recipe.get("image") or recipe.get("thumbnailUrl"), index, page_url),
        "recipeIngredient": _ingredients(recipe),
        "recipeInstructions": _instructions(recipe, index),
        "tags": _tags(recipe),
    }


# --------------------------------------------------------------------------
# Page text fallback
# --------------------------------------------------------------------------

def _page_text(root, limit=PAGE_TEXT_LIMIT):
    text = clean_text(root.block_text(skip=_INVISIBLE), multiline=True)
    if len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        text = text[: cut if cut > limit // 2 else limit]
    return text


def _og_image(root, base_url):
    for node in root.iter():
        if node.tag == "meta" and node.attrs.get("property", node.attrs.get("name", "")).lower() in ("og:image", "og:image:url", "twitter:image"):
            url = node.attrs.get("content", "").strip()
            if url:
                return urljoin(base_url, url)
    return None


def page_image(page_html, page_url=""):
    """Best share image (og:image / twitter:image) for any page, or None."""
    return _og_image(_build_tree(page_html or ""), page_url)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def parse_html(page_html, page_url=""):
    """Extract a Mealie-shaped recipe from HTML; raises NoRecipe if none is found."""
    root = _build_tree(page_html or "")
    jsonld, index = _jsonld_recipes(root)
    for source, idx in ((jsonld, index), (_microdata_recipes(root), {})):
        for candidate in source:
            recipe = _to_mealie(candidate, idx, page_url)
            if recipe["recipeIngredient"] and recipe["recipeInstructions"]:
                if not recipe["image_url"]:
                    recipe["image_url"] = _og_image(root, page_url)
                if not recipe["name"]:
                    title = next((n for n in root.iter() if n.tag == "title"), None)
                    recipe["name"] = clean_text(title.raw_text()) if title else ""
                return recipe
    err = NoRecipe(_page_text(root))
    err.image_url = _og_image(root, page_url)
    raise err


def scrape(url, fetch):
    """Fetch ``url`` via ``fetch(url) -> (final_url, html_text)`` and parse the recipe."""
    final_url, page_html = fetch(url)
    return parse_html(page_html, final_url or url)
