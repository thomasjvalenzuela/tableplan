import unittest

from app.native import units


class UnitsTest(unittest.TestCase):
    def test_normalize_and_dimension(self):
        self.assertEqual(units.normalize("Cups"), "cup")
        self.assertEqual(units.normalize("T"), "tbsp")
        self.assertEqual(units.normalize("t"), "tsp")
        self.assertEqual(units.normalize("fl. oz"), "fl oz")
        self.assertEqual(units.normalize(None), "")
        self.assertEqual(units.dimension("pints"), "volume")
        self.assertEqual(units.dimension("kg"), "weight")
        self.assertEqual(units.dimension(""), "count")
        self.assertEqual(units.dimension("cloves"), "count")
        self.assertIsNone(units.dimension("pinch"))

    def test_convert(self):
        self.assertAlmostEqual(units.convert(1, "cup", "tbsp"), 16, places=2)
        self.assertAlmostEqual(units.convert(3, "tsp", "tbsp"), 1, places=3)
        self.assertAlmostEqual(units.convert(1, "pint", "cup"), 2, places=3)
        self.assertAlmostEqual(units.convert(1, "gallon", "quart"), 4, places=3)
        self.assertAlmostEqual(units.convert(1, "l", "ml"), 1000)
        self.assertAlmostEqual(units.convert(2, "fl oz", "tbsp"), 4, places=2)
        self.assertAlmostEqual(units.convert(1, "lb", "oz"), 16, places=3)
        self.assertAlmostEqual(units.convert(1, "kg", "g"), 1000)
        self.assertAlmostEqual(units.convert(500, "g", "lb"), 1.1023, places=3)
        self.assertEqual(units.convert(2, "", "piece"), 2)
        self.assertEqual(units.convert(3, "cloves", "clove"), 3)
        self.assertEqual(units.convert(1, "dozen", ""), 12)

    def test_different_dimensions_return_none(self):
        self.assertIsNone(units.convert(1, "cup", "g"))
        self.assertIsNone(units.convert(1, "lb", "cup"))
        self.assertIsNone(units.convert(2, "", "cup"))
        self.assertIsNone(units.convert(1, "can", "clove"))
        self.assertIsNone(units.convert(1, "pinch", "tsp"))
        self.assertIsNone(units.convert(None, "cup", "cup"))

    def test_fmt(self):
        self.assertEqual(units.fmt(1, "cup"), "1 cup")
        self.assertEqual(units.fmt(2.5, "cups"), "2 1/2 cups")
        self.assertEqual(units.fmt(0.75, "cup", "cream"), "3/4 cup cream")
        self.assertEqual(units.fmt(3, "", "eggs"), "3 eggs")
        self.assertEqual(units.fmt(1.1023, "lb"), "1.1 lb")


if __name__ == "__main__":
    unittest.main()
