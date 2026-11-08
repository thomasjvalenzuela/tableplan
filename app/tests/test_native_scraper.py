"""Tests for app.native.scraper (stdlib unittest, inline HTML fixtures)."""

import unittest

from app.native.scraper import NoRecipe, clean_text, parse_duration, parse_html, scrape

WPRM_GRAPH = """<!DOCTYPE html><html><head>
<title>Creamy Tuscan Chicken - Sally Cooks</title>
<meta property="og:image" content="https://sallycooks.example/wp-content/uploads/og.jpg">
<script type="application/ld+json" class="yoast-schema-graph">
{"@context":"https://schema.org","@graph":[
 {"@type":"Article","@id":"https://sallycooks.example/tuscan-chicken/#article","headline":"Creamy Tuscan Chicken",
  "image":{"@id":"https://sallycooks.example/tuscan-chicken/#primaryimage"}},
 {"@type":"WebPage","@id":"https://sallycooks.example/tuscan-chicken/","name":"Creamy Tuscan Chicken"},
 {"@type":"ImageObject","@id":"https://sallycooks.example/tuscan-chicken/#primaryimage",
  "url":"https://sallycooks.example/wp-content/uploads/tuscan.jpg","width":1200,"height":1800},
 {"@type":"Recipe","name":"Creamy Tuscan Chicken &amp; Spinach",
  "author":{"@type":"Person","name":"Sally"},
  "description":"A <strong>30-minute</strong> skillet dinner with sun&#8209;dried tomatoes.",
  "image":["https://sallycooks.example/wp-content/uploads/tuscan-225x225.jpg",
           "https://sallycooks.example/wp-content/uploads/tuscan-260x195.jpg",
           "https://sallycooks.example/wp-content/uploads/tuscan-720x540.jpg",
           "https://sallycooks.example/wp-content/uploads/tuscan-320x180.jpg"],
  "recipeYield":["4","4 servings"],
  "prepTime":"PT10M","cookTime":"PT20M","totalTime":"PT30M",
  "recipeIngredient":["1 &frac12; lb chicken breasts","1\u00bd cups heavy cream",
     "<a href=\\"https://amzn.example\\">2 tablespoons</a> olive oil","  ","&#8532; cup parmesan, grated",
     "1\u20442 cup sun-dried tomatoes"],
  "recipeInstructions":[
    {"@type":"HowToStep","text":"Season the chicken with salt &amp; pepper.","name":"Season the chicken","url":"https://sallycooks.example/tuscan-chicken/#wprm-recipe-1-step-0-0"},
    {"@type":"HowToStep","text":"Sear in oil until golden, 5&ndash;6 minutes per side."},
    {"@type":"HowToStep","text":"Stir in the cream, parmesan and tomatoes; simmer 5 minutes."}],
  "recipeCategory":["Main Course"],"recipeCuisine":["Italian"],
  "keywords":"tuscan chicken, easy dinner, Main course",
  "@id":"https://sallycooks.example/tuscan-chicken/#recipe",
  "isPartOf":{"@id":"https://sallycooks.example/tuscan-chicken/#article"}}
]}
</script></head><body><h1>Creamy Tuscan Chicken</h1></body></html>"""

ALLRECIPES_LIST = """<html><head>
<script id="allrecipes-schema_1-0" class="comp allrecipes-schema mntl-schema-unified" type="application/ld+json">
[{"@context":"http://schema.org","@type":["Recipe","NewsArticle"],
  "headline":"World's Best Lasagna","name":"World's Best Lasagna",
  "description":"It takes a little work, but it is worth it.",
  "image":{"@type":"ImageObject","url":"https://www.allrecipes.example/thmb/lasagna.jpg","height":1125,"width":1500},
  "recipeYield":["12","1 (9x13-inch) lasagna"],
  "prepTime":"PT30M","cookTime":"PT2H30M","totalTime":"PT3H15M",
  "recipeIngredient":["1 pound sweet Italian sausage","¾ pound lean ground beef","½ cup minced onion"],
  "recipeInstructions":[
    {"@type":"HowToStep","image":[{"@type":"ImageObject","url":"https://x.example/a.jpg"}],
     "text":"Cook sausage, ground beef, and onion over medium heat until well browned.\\n"},
    {"@type":"HowToStep","text":"Stir in crushed tomatoes and tomato sauce.\\n"}],
  "recipeCategory":["Dinner","Main Dishes"],"recipeCuisine":["Italian"],
  "nutrition":{"@type":"NutritionInformation","calories":"448 kcal"}}]
</script></head><body><main><h1>World's Best Lasagna</h1></main></body></html>"""

HOWTO_SECTIONS = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"WebPage","mainEntity":{
 "@type":"Recipe","name":"Cinnamon Rolls","recipeYield":"12 rolls",
 "totalTime":"P0DT2H45M",
 "recipeIngredient":"4 cups flour\\n1 packet yeast\\n<br>\\n1 cup brown sugar",
 "recipeInstructions":[
   {"@type":"HowToSection","name":"For the dough","itemListElement":[
     {"@type":"HowToStep","text":"Mix flour and yeast."},
     {"@type":"HowToStep","text":"Knead 8 minutes; rise 1 hour."}]},
   {"@type":"HowToSection","name":"For the filling","itemListElement":[
     {"@type":"HowToStep","itemListElement":[{"@type":"HowToDirection","text":"Combine sugar and cinnamon."}]}]},
   "Roll, slice, and bake at 350°F for 25 minutes."]}}
</script></head><body></body></html>"""

MICRODATA_ONLY = """<html><head><title>Grandma's Pancakes</title></head><body>
<nav itemscope itemtype="https://schema.org/BreadcrumbList"><span itemprop="name">Home</span></nav>
<article itemscope itemtype="https://schema.org/Recipe">
  <h1 itemprop="name">Grandma's   Pancakes</h1>
  <img itemprop="image" src="/images/pancakes.jpg" alt="">
  <p itemprop="description">Fluffy &amp; light.</p>
  <meta itemprop="prepTime" content="PT5M">
  <span>Cook: <time itemprop="cookTime" datetime="PT15M">15 min</time></span>
  <span itemprop="recipeYield">Serves 6</span>
  <meta itemprop="keywords" content="breakfast, pancakes">
  <span itemprop="recipeCategory">Breakfast</span>
  <ul>
    <li itemprop="recipeIngredient">1 <b>1/2</b> cups flour
    <li itemprop="recipeIngredient">2 eggs
    <li itemprop="ingredients">1 1/4 cups milk</li>
  </ul>
  <div itemprop="recipeInstructions">
    <p>Whisk the dry ingredients.</p>
    <p>Add eggs and milk.<br>Stir until just combined.</p>
  </div>
  <div itemprop="author" itemscope itemtype="https://schema.org/Person"><span itemprop="name">Grandma</span></div>
</article>
<footer>Copyright</footer>
</body></html>"""

BROKEN_JSONLD = """<html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Foodsite",}</script>
<script type="application/ld+json">
<!--
{
  "@context": "https://schema.org/",
  "@type": "Recipe",
  "name": "Lemon Bars",
  "image": [{"@type": "ImageObject", "url": "https://lemon.example/bars.jpg", "width": 800, "height": 600,},],
  "recipeYield": 16,
  "prepTime": "PT20M",
  "recipeIngredient": [
    "1 cup butter, softened",
    "2 cups flour, divided",
  ],
  "recipeInstructions": "Preheat oven to 350°F.
Press crust into pan, and bake 15 minutes.",
  "keywords": ["dessert", "Dessert", "lemon",],
}
-->
</script></head><body></body></html>"""

NO_RECIPE = """<html><head><title>About us</title>
<style>body { color: red }</style>
<script>window.dataLayer = [];</script>
<script type="application/ld+json">{"@type":"Recipe","name":"Teaser","recipeIngredient":["1 egg"]}</script>
</head><body>
<nav><a href="/">Home</a> <a href="/recipes">Recipes</a></nav>
<main><h1>Our   Kitchen</h1><p>We cook &amp; eat.</p><p hidden>secret</p>
<p>Grandma's chili:<br>2 cans beans</p></main>
<footer>&copy; 2026 Foodsite</footer></body></html>"""


def _texts(recipe):
    return [s["text"] for s in recipe["recipeInstructions"]]


def _notes(recipe):
    return [i["note"] for i in recipe["recipeIngredient"]]


class WPRMGraphTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fetch(url):
            self.calls.append(url)
            return "https://sallycooks.example/tuscan-chicken/", WPRM_GRAPH

        self.r = scrape("http://sallycooks.example/?p=12", fetch)

    def test_core_fields(self):
        r = self.r
        self.assertEqual(self.calls, ["http://sallycooks.example/?p=12"])
        self.assertEqual(r["name"], "Creamy Tuscan Chicken & Spinach")
        self.assertEqual(r["description"], "A 30-minute skillet dinner with sun\u2011dried tomatoes.")
        self.assertEqual(r["orgURL"], "https://sallycooks.example/tuscan-chicken/")
        self.assertEqual(r["recipeYield"], "4 servings")
        self.assertEqual(r["recipeServings"], 4.0)
        self.assertEqual((r["prepTimeSeconds"], r["performTimeSeconds"], r["totalTimeSeconds"]), (600, 1200, 1800))
        self.assertEqual(r["image_url"], "https://sallycooks.example/wp-content/uploads/tuscan-720x540.jpg")

    def test_ingredients_cleaned(self):
        self.assertEqual(_notes(self.r), [
            "1 ½ lb chicken breasts",
            "1 ½ cups heavy cream",
            "2 tablespoons olive oil",
            "⅔ cup parmesan, grated",
            "½ cup sun-dried tomatoes",
        ])
        ing = self.r["recipeIngredient"][0]
        self.assertEqual(ing["display"], ing["originalText"])
        self.assertEqual((ing["quantity"], ing["unit"], ing["food"], ing["title"]), (0, None, None, None))
        self.assertEqual(len({i["referenceId"] for i in self.r["recipeIngredient"]}), 5)

    def test_instructions_and_tags(self):
        self.assertEqual(_texts(self.r), [
            "Season the chicken with salt & pepper.",
            "Sear in oil until golden, 5–6 minutes per side.",
            "Stir in the cream, parmesan and tomatoes; simmer 5 minutes.",
        ])
        step = self.r["recipeInstructions"][0]
        self.assertEqual((step["title"], step["ingredientReferences"]), ("", []))
        self.assertTrue(step["id"])
        self.assertEqual([t["name"] for t in self.r["tags"]],
                         ["tuscan chicken", "easy dinner", "Main course", "Italian"])


class AllrecipesListTest(unittest.TestCase):
    def test_list_with_type_array(self):
        r = parse_html(ALLRECIPES_LIST, "https://www.allrecipes.example/recipe/23600/")
        self.assertEqual(r["name"], "World's Best Lasagna")
        self.assertEqual(r["image_url"], "https://www.allrecipes.example/thmb/lasagna.jpg")
        self.assertEqual(r["recipeYield"], "1 (9x13-inch) lasagna")
        self.assertEqual(r["recipeServings"], 12.0)
        self.assertEqual(r["totalTimeSeconds"], 3 * 3600 + 15 * 60)
        self.assertEqual(r["performTimeSeconds"], 9000)
        self.assertEqual(_notes(r)[1], "¾ pound lean ground beef")
        self.assertEqual(len(r["recipeInstructions"]), 2)
        self.assertEqual(_texts(r)[1], "Stir in crushed tomatoes and tomato sauce.")
        self.assertEqual([t["name"] for t in r["tags"]], ["Dinner", "Main Dishes", "Italian"])


class HowToSectionTest(unittest.TestCase):
    def test_sections_flattened(self):
        r = parse_html(HOWTO_SECTIONS, "https://rolls.example/r")
        steps = r["recipeInstructions"]
        self.assertEqual([(s["title"], s["text"]) for s in steps], [
            ("For the dough", "Mix flour and yeast."),
            ("", "Knead 8 minutes; rise 1 hour."),
            ("For the filling", "Combine sugar and cinnamon."),
            ("", "Roll, slice, and bake at 350°F for 25 minutes."),
        ])
        self.assertEqual(_notes(r), ["4 cups flour", "1 packet yeast", "1 cup brown sugar"])
        self.assertEqual(r["totalTimeSeconds"], 9900)
        self.assertEqual((r["recipeServings"], r["recipeYield"]), (12.0, "12 rolls"))
        self.assertIsNone(r["image_url"])


class MicrodataTest(unittest.TestCase):
    def test_microdata_fallback(self):
        r = parse_html(MICRODATA_ONLY, "https://grandma.example/pancakes/")
        self.assertEqual(r["name"], "Grandma's Pancakes")
        self.assertEqual(r["description"], "Fluffy & light.")
        self.assertEqual(r["image_url"], "https://grandma.example/images/pancakes.jpg")
        self.assertEqual((r["prepTimeSeconds"], r["performTimeSeconds"], r["totalTimeSeconds"]), (300, 900, 1200))
        self.assertEqual((r["recipeYield"], r["recipeServings"]), ("Serves 6", 6.0))
        self.assertEqual(_notes(r), ["1 1/2 cups flour", "2 eggs"])
        self.assertEqual(_texts(r), ["Whisk the dry ingredients.", "Add eggs and milk.", "Stir until just combined."])
        self.assertEqual([t["name"] for t in r["tags"]], ["breakfast", "pancakes"])

    def test_incomplete_jsonld_falls_back_to_microdata(self):
        page = MICRODATA_ONLY.replace(
            "</head>",
            '<script type="application/ld+json">{"@type":"Recipe","name":"Stub","recipeIngredient":["x"]}</script></head>',
        )
        self.assertEqual(parse_html(page, "https://g.example/")["name"], "Grandma's Pancakes")


class BrokenJsonLdTest(unittest.TestCase):
    def test_trailing_commas_and_comment_wrapper(self):
        r = parse_html(BROKEN_JSONLD, "https://lemon.example/bars")
        self.assertEqual(r["name"], "Lemon Bars")
        self.assertEqual(r["image_url"], "https://lemon.example/bars.jpg")
        self.assertEqual((r["recipeYield"], r["recipeServings"]), ("16", 16.0))
        self.assertEqual(_notes(r), ["1 cup butter, softened", "2 cups flour, divided"])
        self.assertEqual(_texts(r), ["Preheat oven to 350°F.", "Press crust into pan, and bake 15 minutes."])
        self.assertEqual(r["tags"], [{"name": "dessert"}, {"name": "lemon"}])
        self.assertEqual(r["totalTimeSeconds"], 1200)


class NoRecipeTest(unittest.TestCase):
    def test_raises_with_visible_text(self):
        with self.assertRaises(NoRecipe) as ctx:
            parse_html(NO_RECIPE, "https://foodsite.example/about")
        self.assertEqual(ctx.exception.page_text, "Our Kitchen\nWe cook & eat.\nGrandma's chili:\n2 cans beans")

    def test_page_text_capped(self):
        page = "<html><body>" + "".join(f"<p>Paragraph {i} " + "word " * 40 + "</p>" for i in range(500)) + "</body></html>"
        with self.assertRaises(NoRecipe) as ctx:
            scrape("https://x.example/", lambda u: (u, page))
        text = ctx.exception.page_text
        self.assertLessEqual(len(text), 20_000)
        self.assertTrue(text.startswith("Paragraph 0 word"))
        self.assertTrue(text.endswith("word"))

    def test_empty_page(self):
        with self.assertRaises(NoRecipe) as ctx:
            parse_html("", "")
        self.assertEqual(ctx.exception.page_text, "")


class HelperTest(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(parse_duration("PT1H15M"), 4500)
        self.assertEqual(parse_duration("P1DT30S"), 86430)
        self.assertEqual(parse_duration("pt0.5h"), 1800)
        self.assertIsNone(parse_duration("PT0S"))
        self.assertIsNone(parse_duration("15 minutes"))
        self.assertIsNone(parse_duration(None))

    def test_clean_text(self):
        self.assertEqual(clean_text("1&#189;  cups&nbsp;<em>milk</em> ,"), "1 ½ cups milk,")
        self.assertEqual(clean_text("<p>a</p><p></p><p>b</p>", multiline=True), "a\nb")
        self.assertEqual(clean_text("3\u20444 tsp; 5\u20447 x"), "¾ tsp; 5/7 x")
        self.assertEqual(clean_text("if x < 5 and y > 3"), "if x < 5 and y > 3")
        self.assertEqual(clean_text("&amp;frac12; cup"), "½ cup")


if __name__ == "__main__":
    unittest.main()
