"""Ingredient parsing (number-less amounts, notes, splitting) and recipe-name title case."""

import os
import tempfile
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="tableplan-parse-"))

from app import server as S  # noqa: E402


def p(t):
    r = S.parse_ing_text(t)
    return r and (r["quantity"], r["unit"], r["food"], r["note"], r["amount_text"])


class Parsing(unittest.TestCase):
    def test_numbers_units_notes(self):
        self.assertEqual(p("1 ½ cups heavy cream, divided"), (1.5, "cup", "heavy cream", "divided", ""))
        self.assertEqual(p("2 c. flour"), (2.0, "cup", "flour", "", ""))
        self.assertEqual(p("3 cloves garlic, minced"), (3.0, "clove", "garlic", "minced", ""))
        self.assertEqual(p("2 tbsp of butter, softened"), (2.0, "tbsp", "butter", "softened", ""))

    def test_numberless_amounts(self):
        self.assertEqual(p("pinch of salt"), (1.0, "pinch", "salt", "", "pinch"))
        self.assertEqual(p("a dash of hot sauce"), (1.0, "dash", "hot sauce", "", "dash"))
        self.assertEqual(p("handful of spinach"), (1.0, "handful", "spinach", "", "handful"))
        self.assertEqual(p("a splash of milk"), (1.0, "splash", "milk", "", "splash"))
        self.assertEqual(p("salt to taste"), (0, "", "salt", "", "to taste"))
        self.assertEqual(p("some parsley"), (0, "", "parsley", "", "some"))
        self.assertEqual(p("a few sprigs of thyme"), (0, "", "thyme", "", "a few sprigs"))
        self.assertEqual(p("a couple carrots"), (0, "", "carrots", "", "a couple"))
        self.assertIsNone(S.parse_ing_text("Salt"))

    def test_salt_and_pepper_split(self):
        r = S.parse_ing_text("salt and pepper, to taste")
        self.assertEqual((r["food"], r["amount_text"]), ("salt and pepper", "to taste"))
        self.assertEqual([x["food"] for x in S.split_foods(r)], ["salt", "pepper"])
        self.assertEqual([x["food"] for x in S.split_foods(S.parse_ing_text("2 cups mac and cheese"))], ["mac and cheese"])

    def test_list_keeps_word_amounts_unscaled(self):
        import sqlite3
        from app.native import lists
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        lists.init(c)
        lid = lists.create_list(c, "G")
        lists.add_recipe_ingredients(c, lid, "r", ["pinch of salt", "2 cups milk"], 3, S.parse_ing_text, None)
        items = {i["food"]["name"]: i for i in lists.get_list(c, lid)["listItems"]}
        self.assertEqual((items["salt"]["quantity"], items["salt"]["note"]), (None, "pinch"))
        self.assertEqual(items["milk"]["quantity"], 6)

    def test_sentence_case_and_rebuilt_lines(self):
        self.assertEqual(S.sentence_case("all-purpose flour"), "All-purpose flour")
        self.assertEqual(S.ing_line_from({"quantity_text": "1 ½ cups", "name": "heavy cream", "note": "divided"}),
                         "1 ½ cups heavy cream, divided")
        self.assertEqual(S.ing_line_from({"quantity_text": "to taste", "name": "salt", "note": ""}), "salt to taste")
        self.assertEqual(S.ing_line_from({"quantity_text": "pinch", "name": "salt", "note": ""}), "pinch of salt")
        self.assertEqual(S._num_tokens("1 ½ cups"), S._num_tokens("1 1/2 cups"))


class TitleCase(unittest.TestCase):
    def test_rules(self):
        cases = {"french toast": "French Toast",
                 "chicken tikka masala with naan": "Chicken Tikka Masala with Naan",
                 "the best mac and cheese": "The Best Mac and Cheese",
                 "a dish to die for": "A Dish to Die For",
                 "BBQ ribs": "BBQ Ribs", "BLT sandwich": "BLT Sandwich",
                 "McDonald's style fries": "McDonald's Style Fries", "iPhone cake": "iPhone Cake",
                 "slow-cooker chili": "Slow-Cooker Chili", "grandma's apple pie": "Grandma's Apple Pie",
                 "pasta e fagioli": "Pasta e Fagioli", "  extra   spaces ": "Extra Spaces",
                 "PIZZA": "PIZZA", "pot-of-gold soup": "Pot-of-Gold Soup"}
        for raw, want in cases.items():
            self.assertEqual(S.title_case(raw), want, raw)


if __name__ == "__main__":
    unittest.main()
