"""Common produce PLU sticker codes (IFPS) -> food. A leading 9 on a 5-digit code means organic.

Codes map to the everyday food name ("Apple", "Banana"); the variety is kept as a label. Stdlib only."""

# code: (food, variety)
PLU = {
    "4011": ("Banana", ""), "4186": ("Banana", "small"), "4229": ("Banana", "burro"), "4234": ("Plantain", ""),
    "4235": ("Plantain", ""),
    "4012": ("Orange", "navel, large"), "4013": ("Orange", "navel"), "4014": ("Orange", "Valencia"),
    "3107": ("Orange", "navel"), "4381": ("Orange", "blood"),
    "4015": ("Apple", "Red Delicious"), "4016": ("Apple", "Red Delicious"), "4017": ("Apple", "Granny Smith"),
    "4139": ("Apple", "Granny Smith"), "4020": ("Apple", "Golden Delicious"), "4021": ("Apple", "Golden Delicious"),
    "4129": ("Apple", "Fuji"), "4131": ("Apple", "Fuji"), "4133": ("Apple", "Gala"), "4135": ("Apple", "Gala"),
    "3283": ("Apple", "Honeycrisp"), "4128": ("Apple", "Pink Lady"), "4130": ("Apple", "Pink Lady"),
    "4103": ("Apple", "Braeburn"), "4104": ("Apple", "Braeburn"), "4152": ("Apple", "McIntosh"), "4153": ("Apple", "McIntosh"),
    "3603": ("Apple", "Jazz"), "4173": ("Apple", "Empire"), "4106": ("Apple", "Cameo"),
    "4022": ("Green grapes", "seedless"), "4023": ("Red grapes", "seedless"), "4056": ("Black grapes", "seedless"),
    "4024": ("Pear", "Bartlett"), "4409": ("Pear", "Bartlett"), "4025": ("Pear", "Anjou"), "4416": ("Pear", "Anjou"),
    "4413": ("Pear", "Bosc"), "4026": ("Pear", "Bosc"), "4407": ("Pear", "Asian"),
    "4030": ("Kiwi", ""), "4301": ("Kiwi", "gold"),
    "4031": ("Watermelon", ""), "4032": ("Watermelon", "seedless"), "3421": ("Watermelon", "mini"),
    "4050": ("Cantaloupe", ""), "4319": ("Cantaloupe", ""), "4034": ("Honeydew", ""), "4329": ("Honeydew", ""),
    "4046": ("Avocado", "Hass, small"), "4225": ("Avocado", "Hass, large"), "4770": ("Avocado", "Hass"),
    "4048": ("Lime", ""), "4305": ("Lime", "key"), "4033": ("Lemon", "small"), "4053": ("Lemon", ""), "4958": ("Lemon", "large"),
    "4051": ("Mango", "red"), "4959": ("Mango", ""), "4311": ("Mango", "green"), "4052": ("Papaya", ""),
    "4430": ("Pineapple", ""), "4029": ("Pineapple", ""),
    "4044": ("Peach", "yellow"), "4038": ("Peach", "yellow"), "4401": ("Peach", "white"), "4036": ("Nectarine", "yellow"),
    "4378": ("Nectarine", "yellow"), "4040": ("Plum", "red"), "4042": ("Plum", "black"), "4218": ("Apricot", ""),
    "4045": ("Cherries", "red"), "4258": ("Cherries", "Rainier"),
    "4041": ("Grapefruit", "red"), "4280": ("Grapefruit", "red"), "4282": ("Grapefruit", "white"),
    "4450": ("Clementine", ""), "4055": ("Tangerine", ""), "3043": ("Mandarin", ""),
    "4060": ("Broccoli", ""), "3082": ("Broccoli", "crowns"), "4547": ("Broccoli", "crowns"), "4548": ("Broccolini", ""),
    "4061": ("Iceberg lettuce", ""), "4640": ("Romaine lettuce", ""), "4076": ("Green leaf lettuce", ""),
    "4075": ("Red leaf lettuce", ""), "4632": ("Romaine hearts", ""), "4090": ("Spinach", ""), "4627": ("Kale", ""),
    "4062": ("Cucumber", ""), "4593": ("English cucumber", ""), "4596": ("Mini cucumbers", ""),
    "4064": ("Tomato", "red"), "4087": ("Roma tomato", ""), "4664": ("Tomato", "on the vine"), "4799": ("Heirloom tomato", ""),
    "4065": ("Green bell pepper", ""), "4088": ("Red bell pepper", ""), "4688": ("Red bell pepper", ""),
    "4689": ("Yellow bell pepper", ""), "3121": ("Orange bell pepper", ""), "4693": ("Jalapeño", ""), "4709": ("Serrano pepper", ""),
    "4690": ("Poblano pepper", ""), "4691": ("Anaheim pepper", ""),
    "4067": ("Zucchini", ""), "4784": ("Yellow squash", ""), "4776": ("Butternut squash", ""), "4759": ("Acorn squash", ""),
    "4068": ("Green onion", ""), "4069": ("Green cabbage", ""), "4554": ("Red cabbage", ""), "4070": ("Celery", ""),
    "4072": ("Russet potato", ""), "4073": ("Red potato", ""), "4727": ("Yukon gold potato", ""), "4083": ("White potato", ""),
    "4816": ("Sweet potato", ""), "4091": ("Sweet potato", ""),
    "4078": ("Corn", "yellow"), "4077": ("Corn", "white"), "4079": ("Cauliflower", ""), "4080": ("Asparagus", ""),
    "4521": ("Asparagus", ""), "4081": ("Eggplant", ""), "4082": ("Red onion", ""), "4093": ("Yellow onion", ""),
    "4665": ("Yellow onion", ""), "4663": ("White onion", ""), "4166": ("Sweet onion", ""), "4159": ("Sweet onion", ""),
    "4562": ("Carrots", ""), "4094": ("Carrots", ""), "4608": ("Garlic", ""), "4612": ("Ginger", ""), "4651": ("Shallot", ""),
    "4645": ("White mushrooms", ""), "4650": ("Cremini mushrooms", ""), "4651x": ("Shallot", ""),
    "4629": ("Green beans", ""), "4066": ("Green beans", ""), "4587": ("Brussels sprouts", ""), "4550": ("Brussels sprouts", ""),
    "4539": ("Beets", ""), "4625": ("Leeks", ""), "4618": ("Fennel", ""), "4627x": ("Kale", ""),
    "4889": ("Cilantro", ""), "4901": ("Parsley", "Italian"), "4899": ("Parsley", "curly"), "4885": ("Basil", ""),
    "4891": ("Dill", ""), "4896": ("Mint", ""), "4903": ("Rosemary", ""), "4907": ("Thyme", ""),
    "4057": ("Strawberries", ""), "4240": ("Blueberries", ""), "4239": ("Raspberries", ""), "4241": ("Blackberries", ""),
    "4458": ("Coconut", ""), "4261": ("Coconut", ""), "4447": ("Pomegranate", ""), "3039": ("Dragon fruit", ""),
    "4232": ("Figs", ""), "4245": ("Dates", ""), "4614": ("Jicama", ""), "4615": ("Radishes", ""), "4796": ("Tomatillo", ""),
    "4644": ("Okra", ""), "4734": ("Bok choy", ""), "4545": ("Baby bok choy", ""), "4095": ("Turnip", ""), "4092": ("Parsnip", ""),
}
PLU = {k: v for k, v in PLU.items() if k.isdigit()}


def lookup(code):
    """'4011' -> {'food': 'Banana', 'variety': '', 'organic': False}; '94011' -> organic. None if unknown."""
    code = (code or "").strip()
    if not code.isdigit() or len(code) not in (4, 5):
        return None
    organic = len(code) == 5 and code[0] == "9"
    base = code[1:] if len(code) == 5 and code[0] in "89" else code
    hit = PLU.get(base)
    if not hit:
        return None
    return {"food": hit[0], "variety": hit[1], "organic": organic, "code": code}
