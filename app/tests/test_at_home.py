"""Shopping list "at home" hints (26)."""
import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tableplan-home-")
os.environ.setdefault("DATA_DIR", _TMP)

from app import server as S  # noqa: E402

_P = []


def setUpModule():
    for k, v in (("DATA_DIR", _TMP), ("DB_PATH", os.path.join(_TMP, "t.db")), ("IMG_DIR", os.path.join(_TMP, "img")),
                 ("BACKUP_DIR", os.path.join(_TMP, "bk")), ("NATIVE", True), ("PUBLIC_MODE", False)):
        p = mock.patch.object(S, k, v); p.start(); _P.append(p)
    S.init_db(); S.load_cfg()
    S.set_cfg(people=2, setup_complete=True)
    S.save_settings({"polish_imports": False, "staples": []})


def tearDownModule():
    for p in reversed(_P):
        p.stop()
    shutil.rmtree(_TMP, ignore_errors=True)


def stock(name, loc="fridge", qty=None, unit="", left=None):
    with S.db() as c:
        pid = S.add_pantry_item(c, name, loc, None, "")
        if qty is not None:
            S.apply_pantry_action(c, pid, {"action": "amount", "qty": qty, "unit": unit})
        if left is not None:
            S.apply_pantry_action(c, pid, {"action": "fill", "left": left})
    return pid


def recipe(name, ings):
    return S._save_new_recipe({"name": name, "recipeIngredient": [{"note": x} for x in ings], "recipeInstructions": [{"text": "Cook."}]},
                              None, dup="keep")


class AtHome(unittest.TestCase):
    def test_hints(self):
        stock("milk", left=0.5)
        stock("eggs", qty=6)
        stock("butter")
        stock("rice", loc="pantry", qty=1, unit="cup")
        tue = S.today() + timedelta(days=2)
        for slug in (recipe("Scramble", ["2 eggs", "1 tbsp butter"]), recipe("Rice bowl", ["3 cups rice"])):
            rid = S.recipe_detail(slug)["id"]
            S.plan_assign({"date": S.iso(tue), "entry_type": "dinner", "recipe_id": rid})
        S.sync_list()
        S.list_add({"items": ["milk", "eggs", "butter", "flour"]})
        lst = S.ongoing_list()
        by = {}
        for i in lst["items"]:
            by.setdefault((i["food"] or i["name"]).lower(), []).append(i)
        milk = by["milk"][0]["home"]
        self.assertEqual((milk["kind"], milk["text"]), ("have", "1 at home · ½ left"))
        self.assertEqual(milk["items"][0]["place"], "Fridge")
        eggs = [i["home"] for i in by["egg"] + by.get("eggs", []) if i["manual"]] if "egg" in by else [i["home"] for i in by["eggs"] if i["manual"]]
        self.assertEqual(eggs[0]["text"], "1 at home · 4 left")                  # 2 of the 6 are set aside for Tuesday
        butter = [i["home"] for i in by["butter"] if i["manual"]][0]
        self.assertEqual(butter["kind"], "reserved")
        self.assertEqual(butter["text"], f"1 at home (reserved for {tue.strftime('%a')})")
        rice = [i for i in by["rice"]][0]
        self.assertEqual(rice["home"]["kind"], "short")
        self.assertEqual(rice["home"]["text"], "need 2 cups more")
        self.assertIsNone(by["flour"][0]["home"])                                  # nothing at home: no hint


if __name__ == "__main__":
    unittest.main()
