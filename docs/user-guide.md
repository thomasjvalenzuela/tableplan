# User guide

How to use every part of TablePlan, task by task. For installing, see [install.md](install.md). For every setting, see [configuration.md](configuration.md).

**Finding Settings:** on a phone, tap the gear button at the top right of any tab. On a desktop, use **Settings** at the bottom of the sidebar.

- [The five tabs](#the-five-tabs)
- [Adding recipes](#adding-recipes)
- [Sharing recipes from your phone](#sharing-recipes-from-your-phone)
- [The recipe page](#the-recipe-page)
- [Meal planning](#meal-planning)
- [Shopping lists](#shopping-lists)
- [Pantry and use-by dates](#pantry-and-use-by-dates)
- [Notifications](#notifications)
- [Sharing, printing and exporting](#sharing-printing-and-exporting)
- [AI features and AI spending](#ai-features-and-ai-spending)
- [What works without AI](#what-works-without-ai)

---

## The five tabs

| Tab | What's there |
|---|---|
| **Home** | Tonight's meal, the next 7 days, items to use soon, a pantry check-in reminder when one is due, and quick actions: **Add Recipe**, **Plan My Meals**, **Send List**, **Scan to Pantry**. |
| **Recipes** | Your library, with search and filters. |
| **Meals** | The meal plan, by week or month. |
| **Shopping** | Your shopping lists. |
| **Pantry** | What's in the fridge, freezer and pantry, with use-by dates. |

---

## Adding recipes

Tap **+** on Home or Recipes (or **Add Recipe** under Quick Actions). The **Add a Recipe** sheet has four tabs.

### Link

Paste a link and tap **Import**. On a secure (HTTPS) address, TablePlan fills in a link from your clipboard when you tap the field.

| Kind of link | What happens | Needs AI? |
|---|---|---|
| **Recipe website** | TablePlan reads the recipe data most recipe sites publish (schema.org). Usually a few seconds. The page's photo is saved too. | No. If the page has no recipe data, AI reads the page text instead (only if you've added an OpenAI key). |
| **Instagram, TikTok, YouTube, Facebook, Pinterest** | TablePlan reads the post's caption. If the recipe is only spoken, AI transcribes the audio and writes up the recipe (about 30–90 seconds). Short links (`pin.it`, `fb.watch`) work too. | Only for spoken recipes, or captions without clear *Ingredients* / *Instructions* headings. |
| **Threads** | TablePlan reads the post's text. Audio isn't transcribed. | Only for text without clear headings. |
| **Google Doc** | TablePlan downloads the document's text. The doc must be shared as **Anyone with the link**. | Only if the text has no *Ingredients* and *Instructions* headings. |

Sites behind a login or paywall can't be read. Use screenshots instead. Private social accounts can't be read either. Video links must point to a single post, not a channel or playlist, and spoken-recipe audio is limited to a short download (about 24 MB or 4 minutes of downloading).

### Screenshot (photos and PDFs)

Choose up to **8 files**: screenshots, photos of a recipe card or cookbook page, or a PDF (15 MB max per PDF). Tap **Read recipe with AI**. Expect 20–60 seconds.

- This always needs an OpenAI key.
- If part of the recipe is missing (for example, a second page wasn't included), TablePlan doesn't save it. It tells you what's missing so you can add the other screenshot and try again.
- If a screenshot shows the recipe's web address, TablePlan fetches that page's photo in the background.

### Paste

Paste the full recipe text (from Notes, an email, a message) and tap **Import text**. Without AI, the text needs an **Ingredients** heading and an **Instructions** (or Directions, Method, Steps) heading. With an OpenAI key, any layout works.

### Type it

Enter a name and tap **Start writing**. The recipe editor opens so you can type the ingredients and steps. See [Editing a recipe](#editing-a-recipe).

### After an import

TablePlan shows **Added "…"** with the ingredient count. Tap **Open recipe** to check it, or **Add another**. A progress bar estimates how long each import will take, learning from your past imports on that device.

---

## Sharing recipes from your phone

Send a link from Instagram, TikTok, Safari or any app straight into TablePlan. Instructions are also in the app at **Settings → Import → Share to TablePlan from your phone**.

### iPhone and iPad (a one-time Shortcut)

1. Open the **Shortcuts** app and tap **+**. Name the shortcut **TablePlan**.
2. Tap the **ⓘ** info button and turn on **Show in Share Sheet**. Set it to receive **URLs** and **Text**.
3. Add the action **URL** and set it to your TablePlan address followed by `/?url=`, for example:
   ```
   http://192.168.1.20:9930/?url=
   ```
   Tap after the `=` and insert the variable **Shortcut Input**. (In the app, **Copy the address for step 3** copies the exact address for you.)
4. Add the action **Open URLs**.

Now, in any app, tap **Share → TablePlan**. The first time, it may be under **More**. TablePlan opens the **Add a Recipe** sheet with the link filled in. Check it and tap **Import**.

### Android

Install TablePlan as an app from Chrome: open it, tap **⋮ → Install app**. TablePlan then shows up in every app's **Share** menu. Shared links open with the link filled in; tap **Import**.

> Chrome only offers a real install (and the Share menu entry) on an HTTPS address. On plain `http://`, it adds a shortcut instead. See [HTTPS and remote access](https-and-remote-access.md).

### Any device

Opening `http://192.168.1.20:9930/?url=<link>` opens **Add a Recipe** with that link filled in. This is what the Shortcut does. TablePlan never imports a shared link without your tap, so a link someone sends you can't add recipes on its own.

---

## The recipe page

Open any recipe from Recipes, Meals or Home.

### Servings and scaling

The **Servings** stepper (**−** / **+**) starts at the recipe's own serving count, or your household size if the recipe doesn't say. Every ingredient that starts with an amount ("2 cups flour", "1 ½ lb chicken") scales as you change it. Lines without an amount ("salt to taste") are shown as written.

Planned meals and shopping lists scale automatically to the number of people in **Settings → Household** (when **Scale recipes to fit** is on).

### Classic vs Step-by-step

Use the toggle under the stats. The default is set in **Settings → Cooking → Recipe style**.

| Style | What you see |
|---|---|
| **Classic** | Ingredients, then numbered instructions. |
| **Step-by-step** | Each step shows only the ingredients it uses, with the amounts for that step. It adds a preheat step at the right moment, converts temperatures to your unit, lowers oven temperatures for a convection oven, and adds stove tips and timers. |

Step-by-step is tuned to **Settings → Cooking**: **Stovetop** (gas, electric, induction), **Oven** (conventional, convection/fan) and **Temperatures** (°F, °C).

- With an OpenAI key, Step-by-step is arranged by AI (shown as **✨ AI-arranged**). This happens in the background right after you import a recipe, so it's usually instant. Tap **Re-do with AI** to regenerate it.
- Without a key, TablePlan's built-in arranger is used (shown as **Auto-arranged**). It finds times, temperatures and heat levels in the text.

### Cook mode and timers

Tap **Start cooking** for a full-screen walkthrough, one step at a time. It uses the Step-by-step version (prepared on first use, about 15 seconds with AI). If that can't be made, cook mode uses the recipe's own steps.

- Steps with a wait (simmer, bake, rest) show a timer. Tap **Start timer**. Use **+1 min** or **Stop** as needed.
- Timers keep running when you move to other steps. Running timers appear in a tray at the bottom; tap one to jump back to its step.
- When a timer ends, TablePlan beeps, vibrates (on phones that support it) and shows the next step. If the page is in the background, it also sends a browser notification (needs HTTPS and your permission).
- The screen stays awake while cooking, on browsers that support it.
- On a keyboard: **→** next, **←** back, **Esc** to exit.

### Other buttons on the recipe page

| Button | What it does |
|---|---|
| **♡ / ♥** | Favorite. Favorites appear under the **♥ Favorites** filter on the Recipes tab. |
| **Camera** (on the photo) | Change the recipe photo. See [Photos](#photos). |
| **Plan it** | Add this recipe to a day and meal (breakfast, lunch, dinner, side, snack, dessert). |
| **Add missing to list** | Adds the ingredients you don't have in the pantry to your shopping list. Untick anything you already have. |
| **Edit** | Opens the recipe editor. |
| **Original** | Opens the source web page, if there is one. |

Ingredients that match something in your pantry are tagged **In fridge** (or freezer, pantry) or **Use soon**.

### Editing a recipe

Tap **Edit**. You can change the name, description, servings, prep, cook and total minutes, ingredients and instructions.

- **Ingredients:** one per line, amount first ("2 cups flour"), so they scale. Start a line with `#` for a heading, such as `# Sauce`.
- **Instructions:** leave a blank line between steps.
- Tap **Save**. The Step-by-step version is rebuilt next time you open it.
- **Delete recipe** removes it from your library and from any meal plans that use it.

### Photos

- **Recipe photo:** tap the camera button on the recipe photo. **Try another** first tries the photo from the recipe's original web page, then openly licensed food photos from Openverse. **Upload** uses your own photo (JPG, PNG or WebP, 8 MB max).
- **Ingredient photos:** tap an ingredient's picture. Photos come from TheMealDB, then Openverse. **Try another** and **Upload** work the same way.

Your own photo always wins over a found one.

### Finding recipes

On the **Recipes** tab, search by name or tag. Filter chips include **All**, **♥ Favorites**, meal tags (Breakfast, Lunch, Dinner, Dessert, Snack) and up to 12 other tags. Tags come from imported recipes.

---

## Meal planning

### The Meals tab

Switch between **Week** (the next 7 days, then earlier or later weeks with the arrows) and **Month**. Tap a meal to **Open recipe**, **Swap** it for another recipe, or **Remove** it. Tap **Not planned** on an empty day to fill just that day.

### Auto-plan

Tap **Auto-plan week** / **Auto-plan month** on the Meals tab, or **Plan My Meals** on Home. The **Plan meals for me** sheet has:

| Option | What it does |
|---|---|
| **Starting** / **How long** | Week, 2 weeks or a month. |
| **Which meals should I plan?** | Breakfast, lunch, dinner, side. |
| **No repeats for** | The same recipe won't be picked again within this many days (counting meals already planned). |
| **Use food before it goes bad** | Favors recipes that use pantry items close to their use-by date, in the first few days of the plan. These show an **uses expiring** badge. |
| **Only fill empty days** | Leaves meals you already planned alone. Turn it off to replace them. |
| **Kinds of recipes** | Tap a tag once to **only** use recipes with it, twice to **skip** it, again to clear. |

Tap **Suggest meals**, then swap (shuffle icon) or remove (×) any suggestion, tap **Redo** for a fresh set, and **Save** when you're happy. If you have fewer recipes than slots, TablePlan warns you that some will repeat sooner.

Recipes that have a rating (for example, imported from Mealie) are picked slightly more often.

The defaults for meals, no-repeat days and "use food before it goes bad" come from **Settings → Meal planning**.

### Automatic weekly planning

In **Settings → Meal planning → Plan next week automatically on**, choose a day. On that day, from 8:00 AM server time, TablePlan fills the empty slots for the next 7 days (starting the following day) using your saved meal-planning settings. It never replaces meals you've already planned.

Turn on **Send me the plan** to receive the new plan on every notification channel you've set up.

---

## Shopping lists

### Adding items

| From | How |
|---|---|
| **Your meal plan** | Meals tab → **Add to list**. See [Confirm what you have](#confirm-what-you-have). |
| **One recipe** | Recipe page → **Add missing to list**. |
| **By hand** | Shopping tab → **Add items**. One item per line; amounts are optional. |

Items are sorted into store sections automatically (Produce, Meat & Seafood, Dairy & Eggs, Bakery, Frozen, Spices, Pantry, Beverages, Household, Other). The same ingredient from two recipes is merged into one line when the units match.

If you have no list yet, tap **Start a shopping list** (it's called "Groceries"), or just add a week of meals and one is created for you. If you have more than one list (for example, imported from Mealie), switch between them at the top of the Shopping tab.

### Confirm what you have

When you add a meal plan to a list, TablePlan first shows **Do you already have these?** It lists ingredients that match your pantry and common staples (salt, oil, butter, flour and so on). Items you have plenty of are pre-ticked. Anything ticked stays off the list. Tap **Build my list**.

Ingredients are scaled to your household size and merged.

### Checking items off

Tap an item when it's in your cart. If TablePlan knows the item's shelf life, it moves it into your pantry with a use-by date, and a message shows where it went (for example, *Heavy cream → Fridge · use by Nov 15*). Tap **Undo** to take it back.

Items without shelf-life data (paper towels, soap) are just checked off. Tap **Track it** in the message if you want it in the pantry anyway.

---

## Pantry and use-by dates

### How items get in

- Check them off your shopping list (see above).
- Pantry tab → **+**. Type a name; TablePlan shows which shelf-life rule matched. Pick where it's stored (or **Auto**), and enter the **Printed date** if the package has one.
- **Scan barcodes** (Pantry tab) or **Scan to Pantry** (Home). See below.

### Where use-by dates come from

TablePlan uses the **USDA FoodKeeper** database, taking the cautious end of each range. Until the first download finishes, a small starter table is used.

- A date you enter from the package always wins.
- Opening an item switches it to the "after opening" time. This can only make the date sooner, never later.
- Moving an item to the freezer switches it to the freezer time. Moving it out switches to the "after thawing" time.
- Moving between fridge and pantry recalculates the date and keeps the sooner one.

### Updating an item

Tap any item:

| Control | What it does |
|---|---|
| **How much did you use?** ¼ ½ ¾ **All** | Records what you used. The first use marks it opened. **All** finishes it. |
| **Left** slider | Set the amount left directly. |
| **Stored in** | Fridge, Freezer or Pantry. The date updates. |
| **Use-by date** | Type your own date. |
| **Shelf life** | Pick a different rule if the match was wrong. TablePlan remembers your choice for that item name. |
| **Opened** | Mark as opened without using any. |
| **Toss** | Remove it as thrown away. **Undo** brings it back. |

Use the **All / Fridge / Freezer / Pantry** filter at the top of the tab.

### Shelf-life rules

**Settings → Shelf life data**:

- **USDA FoodKeeper** shows how many foods are loaded and when. Tap **Sync now** / **Re-sync now** to download the latest data.
- **House rules & edits** lets you search all rules, edit one, or tap **New rule**. Rules have a name, extra words they match ("Also matches"), where the food is usually stored, and how many days it keeps: fridge sealed, fridge after opening, pantry sealed, pantry after opening, freezer, fridge after thawing.
- Editing a USDA rule turns it into a house rule, so a re-sync never overwrites your numbers. House rules win over USDA rules.

If your server can't reach the USDA website, download `foodkeeper.json` yourself, put it in the TablePlan data folder, and tap **Sync now**.

### Barcode scanning

Pantry tab → **Scan barcodes**, or Home → **Scan to Pantry**.

- **On HTTPS:** the camera opens and scans EAN and UPC barcodes automatically.
- **On plain http://:** browsers block the live camera, so TablePlan asks you to take a photo of the barcode instead.
- You can always **type the barcode number** and tap **Look up**.

Product names come from **Open Food Facts**. TablePlan suggests where to store it and lets you add a printed date, then **Add to pantry**. If the barcode isn't in Open Food Facts, type what it is. Looked-up barcodes are remembered, so scanning the same product again doesn't go online.

### Pantry check-ins

A quick "still have it?" review keeps dates and shopping lists honest. Pantry tab → **Check-in**, or tap the reminder on Home when one is due.

For each item tap **✓** (still have it), **½** (about half left) or **✕** (gone), then **Done**.

Set how often you're reminded in **Settings → Pantry → Check-in reminder**: Off, Weekly (recommended), Every 2 weeks or Monthly. If notifications are set up, the reminder is also sent to your phone or email.

---

## Notifications

Set up one or more channels in the setup wizard or **Settings → Setup → Notifications**. Each sends a test message when you connect it.

| Channel | Good for | What you need |
|---|---|---|
| **Telegram** | Free, works when email doesn't. | A bot you create with @BotFather. |
| **ntfy** | Push notifications, no account. | The free ntfy app. |
| **Email** | Lists and plans with attachments. | An email account that allows SMTP. |

### Telegram

1. In Telegram, open **@BotFather**, send `/newbot`, pick a name and a username ending in `bot`.
2. Paste the **token** BotFather sends into TablePlan and continue.
3. Tap **Open @yourbot in Telegram → Start**, then **I tapped Start, check**.
   To send to a family group instead, add the bot to the group and send the 8-character **link code** there (valid 15 minutes).

TablePlan only sends messages out. Nothing on your server is opened to the internet. Meal plans include the `.ics` calendar file.

### ntfy

1. Keep the suggested random **Topic** (treat it like a password), or use your own ntfy server and an **Access token**.
2. In the ntfy app, tap **+** and subscribe to the same topic.
3. Tap **Connect ntfy**. A test arrives.

On the public `ntfy.sh` server, anyone who knows the topic can read it, so TablePlan requires a long topic (20+ characters) or an access token there. Plain `http://` ntfy servers are only accepted on your home network.

### Email

Pick a provider: **Gmail / Google Workspace**, **Outlook / Microsoft 365**, **iCloud Mail**, **Yahoo**, or **Other (SMTP)**. Enter your email, password and the addresses to send to (comma-separated).

| Provider | Password to use |
|---|---|
| Gmail | An **App Password** (turn on 2-Step Verification first). |
| Outlook | Your password, or an app password if 2-step sign-in is on. SMTP must be allowed for your mailbox. |
| iCloud | An app-specific password from appleid.apple.com. |
| Yahoo | An app password from Yahoo Account Security. |
| Other | Your provider's SMTP server, port and security (STARTTLS, SSL or none). Services like Brevo or SMTP2GO work. |

### What gets sent

| Message | When |
|---|---|
| Shopping lists, meal plans, pantry reports | When you tap **Send** (see below). |
| The new week's plan | After automatic weekly planning, if **Send me the plan** is on. |
| **Use soon** | Daily at the **Reminder time**, if **Daily "use soon" reminder** is on and something expires today or tomorrow (or already has). |
| Pantry check-in reminder | When a check-in is due. |
| AI budget alerts | At 80% and 100% of your monthly AI budget. |
| New version available | Once per new version. |

Automatic messages go to every channel you've set up.

---

## Sharing, printing and exporting

Use the share button at the top of Meals, Shopping and Pantry, or **Send** / **Print** on the Shopping tab.

| What | Options |
|---|---|
| **Shopping list** | Send to Telegram / ntfy / email, **Print**, **Text file**, **Spreadsheet (CSV)**, **Send via…** (your phone's share sheet) |
| **Meal plan** (the week or month on screen) | Send, **Print**, **Add to calendar (.ics)**, **Spreadsheet (CSV)**, **Send via…** |
| **Pantry** | Send, **Print**, **Spreadsheet (CSV)** |

Emails include the list or plan as a table plus CSV attachments, and plans include the `.ics` file.

---

## AI features and AI spending

TablePlan uses **OpenAI** as its optional AI provider, with your own API key. Add it in the wizard or **Settings → Setup → AI recipe import**. TablePlan tests the key before saving it. The default model is `gpt-5-mini`; the model has to be able to read images.

### What uses AI

| Feature | When AI is used |
|---|---|
| Screenshot, photo and PDF import | Always. |
| Recipe website import | Only when the page has no structured recipe data. |
| Video import | To transcribe spoken recipes, and to read captions. |
| Paste and Google Doc import | Whenever a key is set (it reads any layout). Without a key, the built-in reader handles text with headings. |
| Step-by-step | Whenever a key is set, prepared in the background after import and cached. |

### AI spending

**Settings → AI → AI spending** shows:

- This month's estimated spend from TablePlan's own AI calls, by feature, with a daily chart and recent calls. Estimates use OpenAI list prices for the model.
- **Monthly budget:** enter a USD amount to get a notification at 80% and 100%. This is an alert, not a cap. To hard-cap spending, also set a limit in your OpenAI account.
- **Exact costs from OpenAI:** paste an optional **Admin key** (starts with `sk-admin-`, from OpenAI → Settings → Organization → Admin keys). TablePlan then shows your real bill for the month. This covers everything on your OpenAI account, not just TablePlan.

Video transcription isn't priced in the estimate; the exact (Admin key) figure includes it.

---

## What works without AI

Everything except screenshot, photo and PDF import and spoken-video import.

| Works without a key | Needs a key |
|---|---|
| Importing from recipe websites that publish recipe data (most do) | Screenshots, photos, PDFs |
| Paste, Google Docs and video captions with *Ingredients* / *Instructions* headings | Videos where the recipe is only spoken |
| Typing recipes, editing, scaling | Messy pages and text without headings |
| Step-by-step (built-in arranger) and cook mode | AI-arranged Step-by-step |
| Meal planning, shopping lists, pantry, barcode scanning, notifications, exports | |
