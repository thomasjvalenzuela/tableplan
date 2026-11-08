# Architecture

For contributors. How TablePlan is put together, where data lives, and how a release ships. For local development and the release workflow in brief, see [CONTRIBUTING.md](../CONTRIBUTING.md).

- [Principles](#principles)
- [Components](#components)
- [Request flow](#request-flow)
- [Data model](#data-model)
- [Native storage modules](#native-storage-modules)
- [Import pipeline](#import-pipeline)
- [Step-by-step and cook mode](#step-by-step-and-cook-mode)
- [Meal-plan generator](#meal-plan-generator)
- [Pantry and shelf life](#pantry-and-shelf-life)
- [Notifications](#notifications)
- [The scheduler](#the-scheduler)
- [Update feed and release pipeline](#update-feed-and-release-pipeline)
- [Tests](#tests)

---

## Principles

- **One process, one container, one data folder.** No database server, queue or separate recipe service.
- **No dependencies.** The server uses only the Python 3.12 standard library and SQLite. The front end is vanilla JS with no build step. The one exception is `yt-dlp` (pinned in `docker/requirements.txt`), installed in the image for video imports; the server works without it.
- **Untrusted input everywhere.** Recipe text, photo credits and links come from scraped pages and AI output. The front end escapes every server value (`esc()`), vets URLs (`safeUrl()`), and encodes path segments (`enc()`); the server validates request fields and guards every outbound fetch.
- **Secrets stay on the server.** The API never returns credential values.

---

## Components

```
Browser (PWA)                     TablePlan container                       Outside (optional)
─────────────                     ───────────────────                       ──────────────────
index.html                        app/server.py                             OpenAI
setup.js   ── fetch + ──────────▶   Handler (ThreadingHTTPServer)  ───────▶ Telegram / ntfy / SMTP
app.js        X-TablePlan: 1        native_api (Mealie-shaped API)          USDA FoodKeeper
recipes.js                          scheduler thread                        Open Food Facts
vendor/zxing (WASM barcode)         app/native/{recipes,plans,lists,scraper} TheMealDB / Openverse
                                    ▼                                        recipe & video sites
                                  DATA_DIR (/data)                          GitHub Pages (version.json)
                                    tableplan.db  images/
```

| Path | Role |
|---|---|
| `app/server.py` | HTTP server and API, auth, pantry and shelf-life logic, meal-plan generator, shopping-list building, import orchestration, AI calls, notifications, exports, scheduler, update check |
| `app/native/recipes.py` | Recipe storage (JSON documents in SQLite) and image files |
| `app/native/plans.py` | Meal-plan entries |
| `app/native/lists.py` | Shopping lists and items, with merging |
| `app/native/scraper.py` | Recipe reader for web pages (schema.org JSON-LD and microdata) |
| `app/static/index.html` | App shell; loads `setup.js`, `app.js`, `recipes.js` |
| `app/static/setup.js` | Sign-in, setup wizard, and the setup sections reused in Settings |
| `app/static/app.js` | Router, Home, Meals, Shopping, Pantry, Add Recipe, sharing, Settings |
| `app/static/recipes.js` | Recipes tab, recipe page, cook mode, editor, photo picker, AI spending, barcode scanner, check-ins, What's new |
| `app/static/vendor/zxing/` | zxing-wasm barcode decoder (MIT) |
| `app/static/manifest.webmanifest` | PWA manifest, including the Android share target (`/?share_url=…`) |
| `app/seed/starter_shelf_life.json` | Shelf-life rules used until the USDA sync succeeds |
| `install/` | One-line installer and Compose file |
| `Dockerfile`, `docker/entrypoint.sh`, `docker/requirements.txt` | Image build. The entrypoint gives `/data` to uid 1000 and drops root before starting the server. |
| `railway.toml` | Railway build and deploy settings (Dockerfile build, `/health` check, one replica) |
| `zimaos-store/` | ZimaOS community store definition (store v2) |
| `docs/setup.html` | Illustrated install guide, published to GitHub Pages at `/setup/` |

The front end is a single page that routes on the URL hash: `#home`, `#recipes`, `#meals`, `#list`, `#pantry`, `#recipe/<slug>`, `#edit/<slug>`. Sheets (dialogs) are rendered into `#layer`.

---

## Request flow

Every request goes through `Handler.handle_any`:

1. `/health` returns `ok` immediately (used by the Docker healthcheck, the installer and Railway).
2. The request's host and scheme are recorded from `X-Forwarded-Host` / `Host` and `X-Forwarded-Proto`.
3. **CSRF check:** `POST`, `PUT`, `PATCH` and `DELETE` without `X-TablePlan: 1` get `403`.
4. **Auth check:** unless the path is public (`/`, `/static/*`, `/manifest.webmanifest`, `/api/session`, `/api/login`), a valid `tp_session` cookie is required when a password is set or public mode is on. API paths get `401 {"auth": true}`, others redirect to `/`.
5. `route()` matches the method and path and calls a function. `ApiError(status, message)` becomes a JSON `{"error": …}` response; other exceptions become `400` or `500`.
6. `send()` adds the security headers (CSP, `nosniff`, `no-referrer`, `X-Frame-Options`, `Permissions-Policy`, HSTS on HTTPS) and `Cache-Control: no-store` unless the route sets its own.

Sessions are `"<timestamp>.<HMAC-SHA256>"` signed with `cfg.session_secret`, valid for 180 days (`SESSION_DAYS`). `rotate_sessions()` replaces the secret, which signs out every device.

Sign-in failures are limited per client address and globally (`login_throttled`). In public mode, `rate_ok(bucket, ip)` limits imports (20/hour), AI calls (60/hour) and outbound fetches (300/hour) per client. The client address comes from `X-Forwarded-For` only when `TABLEPLAN_TRUST_PROXY` is on.

Heavy imports run under a semaphore (`TABLEPLAN_MAX_IMPORTS`, default 3). Follow-up work (AI Step-by-step preparation, finding a recipe photo) runs on a two-thread pool via `background()`.

`PUT /api/settings` values go through `SETTINGS_VALIDATORS` (types, enums, ranges); the plan generator validates its options the same way. Date ranges from requests go through `date_range()`, capped at 400 days.

### Outbound HTTP

Every fetch made on a user's behalf goes through `_open()`: only `http`/`https`, the target must resolve to public addresses (`_public_host`), every redirect is re-checked and has its `Authorization` header dropped, and the guarded connection classes re-check the address actually dialled, so DNS rebinding can't reach the LAN. `_read_capped()` limits size and total time. Operator-configured targets (Mealie, FoodKeeper, the update feed, a custom Telegram API, a LAN ntfy outside public mode) pass `allow_private=True`.

### The Mealie-shaped internal API

TablePlan used to store everything in Mealie. The server still talks to its storage through `mealie(method, path, body)`, using Mealie's REST paths and JSON shapes. With the default `TABLEPLAN_BACKEND=native`, `mealie()` calls `native_api()`, which answers those paths from SQLite and `images/`. This kept the rest of the server unchanged during the migration. `TABLEPLAN_BACKEND=mealie` still routes to a real Mealie for legacy installs.

New code should keep using `mealie()` (or the native modules directly) rather than reading tables ad hoc, so both stay in sync.

### Main API routes

| Area | Routes |
|---|---|
| Session | `GET /api/session`, `POST /api/login`, `POST /api/logout` |
| Config and setup | `GET /api/config`, `GET /api/setup/status`, `POST /api/setup/{household,ai,email,telegram,telegram/verify,ntfy,password,import-mealie,complete,openai-admin}`, `DELETE /api/setup/{telegram,ntfy,email}` |
| Settings | `GET`/`PUT /api/settings` |
| Recipes | `GET /api/recipes`, `POST /api/recipes/new`, `GET`/`PUT`/`DELETE /api/recipe/<slug>`, `POST /api/recipe/<slug>/{favorite,image/next,image/upload,to-list}`, `GET /api/recipe/<slug>/guided` |
| Import | `POST /api/import/{url,text,images}` |
| Plans | `GET /api/plan`, `POST /api/plan/{generate,reroll,save,preview,to-list}`, `DELETE /api/plan/<id>` |
| Lists | `GET`/`POST /api/lists`, `GET /api/lists/<id>`, `POST /api/lists/<id>/items`, `POST /api/lists/<id>/items/<item>/{bought,undo}` |
| Pantry | `GET`/`POST /api/pantry`, `PATCH /api/pantry/<id>` (`action`: use, open, move, set_date, rule, rename, toss, restore, delete), `GET /api/pantry/match`, `GET /api/pantry/checkin`, `POST /api/pantry/checked`, `GET /api/upc/<code>` |
| Shelf life | `GET`/`POST /api/rules`, `PUT /api/rules/<id>`, `POST /api/rules/sync-usda` |
| Messages | `POST /api/send` (`kind`: list, plan, pantry, test; `channel`: all, email, telegram, ntfy) |
| AI | `GET /api/ai/spending` |
| Misc | `GET /api/summary`, `GET /api/version` |
| Files | `/img/<recipe-id>`, `/img/ing?name=`, `/export/list/<id>.{txt,csv}`, `/export/plan.{csv,ics,txt}`, `/export/pantry.csv`, `/print/{list/<id>,plan,pantry}` |

---

## Data model

One SQLite database, `DATA_DIR/tableplan.db`, in WAL mode with foreign keys on. Tables are created on startup with `CREATE TABLE IF NOT EXISTS`; there is no separate migration step.

**Defined in `server.py`:**

| Table | Holds |
|---|---|
| `settings` | Key/value JSON. User settings (`meal_types`, `stove`, …), wizard config as `cfg.*` (household, credentials, password hash, session secret), and internal flags (`usda_synced_at`, `auto_plan_last`, `update_notified`, `pantry_checked_at`, budget alert flags) |
| `shelf_rules` | Shelf-life rules: name, keywords, `source` (`custom`, `usda`, `starter`), `usda_id`, default location, days for sealed/opened pantry and fridge, freezer, thawed, tips |
| `food_map` | Remembered item name → rule choices made in the pantry |
| `pantry_items` | Name, quantity text, location, amount left, purchased/opened/frozen dates, `expires_on`, `expiry_source` (`estimate`, `package`, `manual`, `none`), rule, status (`active`, `used`, `tossed`), the shopping item it came from |
| `pantry_events` | History of pantry actions per item |
| `recipe_cache` | Ingredient tokens per recipe, keyed on the recipe's updated time (for the "use it up" boost) |
| `guided_cache` | Step-by-step versions per recipe and kitchen profile (stove, oven, unit, AI or built-in) |
| `ai_usage` | Every AI call: time, feature, model, tokens, estimated cost |
| `upc_cache` | Open Food Facts lookups by barcode |
| `image_picks` | Which candidate photo is chosen for each ingredient or recipe, file name and credit |

**Defined in `app/native/`:**

| Table | Module | Holds |
|---|---|---|
| `recipes` | `recipes.py` | `id`, unique `slug`, `name`, `data` (the full recipe as Mealie-shaped JSON), timestamps |
| `favorites` | `recipes.py` | Favorite recipe IDs |
| `aliases` | `recipes.py` | Old slugs of renamed recipes, so old links still work |
| `meal_plans` | `plans.py` | Date, `entry_type` (breakfast, lunch, dinner, side, snack, dessert, drink), recipe, title, text, scale, `source_id` (for idempotent Mealie import) |
| `shopping_lists` | `lists.py` | List ID and name |
| `shopping_items` | `lists.py` | Text, parsed food/quantity/unit, note, aisle `label`, checked, position, source recipe IDs |

**Files:** recipe photos at `images/recipes/<recipe-id>/original.<ext>` (one per recipe; the `image` field in the recipe JSON is a short content hash used for cache busting). Ingredient photos at `images/ing-<sha1>.<ext>`.

---

## Native storage modules

`app/native/*.py` are stdlib-only and never import `server.py`. Each function takes an open `sqlite3` connection; the caller owns the transaction (`with db() as c:`). Collaborators such as the ingredient parser and aisle categorizer are passed in.

- **`recipes.py`** stores each recipe as the same JSON Mealie returns, so rendering code works unchanged. Handles slugs (unique, with aliases on rename), favorites, image saving (type sniffed from content, max 8 MB, atomic write), and `migrate_from_mealie`.
- **`plans.py`** validates dates and entry types and stores plan entries.
- **`lists.py`** adds items, merging an unchecked item with the same food and unit (quantities add up, source recipes are tracked) and returns lists in Mealie's `ShoppingList` shape.
- **`scraper.py`** parses schema.org `Recipe` objects from JSON-LD (including `@graph`, arrays and lightly malformed JSON) and microdata. If it can't find ingredients and instructions it raises `NoRecipe` carrying the page's visible text, for the AI fallback. Network access is the caller's job.

---

## Import pipeline

All imports end in `_save_new_recipe()` and `_imported()`. `_imported()` starts a background thread that prepares the AI Step-by-step version when a key is set.

| Source | Path |
|---|---|
| **Link** (`/api/import/url`) | The first `https://…` in the text is used (share sheets send extra words). Google Docs → `import_gdoc`. Video hosts → `import_video`. Anything else → `scraper.scrape(url, _fetch_page)`. `_fetch_page` blocks private addresses (also after redirects) and reads up to 6 MB. On `NoRecipe`, if a key is set and the page has at least 300 characters of text, `ai_recipe()` reads the text. The page's image is fetched and saved. |
| **Google Doc** | Downloads `…/export?format=txt`. A login redirect means the doc is private. Text goes to `recipe_from_text`. |
| **Video** | Only URLs on known video hosts are accepted. `pin.it` and `fb.watch` short links are resolved first with the guarded opener. Threads posts are read from the page's meta tags (caption only). Everything else goes to `yt-dlp`, restricted to the dedicated extractors for YouTube, Instagram, TikTok, Facebook and Pinterest (never the generic extractor), single items only. It reads the title, caption and thumbnail without downloading. If the caption doesn't look like a recipe (fewer than 3 lines with amounts) and a key is set, the smallest audio is downloaded to a temp folder (aborted past 24 MB or 240 seconds) and transcribed with `gpt-4o-mini-transcribe`. Caption plus transcript go to `recipe_from_text`. |
| **Text** (`/api/import/text`) | `recipe_from_text`: the built-in reader (`local_recipe_from_text`, which needs *Ingredients* and *Instructions*-type headings) runs first; with a key, `ai_recipe()` is used and the built-in result is the fallback. |
| **Images / PDF** (`/api/import/images`) | Up to 8 files, 25 MB total, sent in one `ai_recipe()` call (images as `image_url`, PDFs as `file`). If the AI found a source URL, the photo from that page is fetched in the background. |

`ai_recipe()` uses OpenAI Chat Completions with a strict JSON schema (`AI_RECIPE_SCHEMA`). The prompt tells the model to copy amounts exactly, never invent content, and flag incomplete recipes; incomplete or empty results are rejected with `422`. If the JSON reply can't be parsed, it retries asking for a plain-text format parsed by `parse_recipe_text`. Every call is logged to `ai_usage` with an estimated cost from `AI_PRICES`.

Ingredients are stored as text lines. `parse_ing_text` extracts quantity, unit and food on demand, so plain-text ingredients scale on the recipe page and merge on shopping lists.

---

## Step-by-step and cook mode

`GET /api/recipe/<slug>/guided` returns ordered steps, each with the ingredient indexes and portions it uses, a timer, heat, temperature and a tip.

- **`guided_ai`** asks the model to reorder the recipe for the household's stove, oven and unit, place preheating at the right time, attach each ingredient to the step that uses it, and add timers. A safety net attaches any skipped ingredient to the first step that mentions it.
- **`guided_auto`** (no AI) uses the original steps, finds durations, oven temperatures and heat levels with regexes, converts °F/°C, lowers convection temperatures, adds a preheat step and stove tips.

Results are cached in `guided_cache` per recipe and kitchen profile, and invalidated when the recipe changes. Cook mode in `recipes.js` runs entirely in the browser (timers, Web Audio beeps, vibration, Wake Lock, notifications).

---

## Meal-plan generator

`generate_plan()` in `server.py`:

1. Builds the recipe pool, filtered by include/exclude tags.
2. Collects every date each recipe is used: existing plan entries from `no_repeat_days` before the start through the end, plus each recipe's `lastMade`.
3. If "use food before it goes bad" is on, finds pantry items expiring within the window (+2 days) and boosts recipes whose ingredients share words with them.
4. For each day and meal type (skipping filled slots when `fill_empty_only`), `_pick()` makes a weighted random choice among recipes not used within the no-repeat window. Weight = 1 + rating/5, multiplied for boosted recipes in the first 4 days, reduced for recipes already used in this plan. If nothing qualifies, it picks among the recipes used longest ago.

`save_plan()` sets each entry's scale to people ÷ recipe servings (minimum 0.25) when household scaling is on. `plan_to_list()` sums scales per recipe, drops ingredients the user said they have, scales plain-text lines locally, and adds the rest through the list module so duplicates merge.

---

## Pantry and shelf life

- On first start, `init_db` seeds `shelf_rules` from `app/seed/starter_shelf_life.json`, and a background thread runs `sync_usda()`, which downloads FoodKeeper JSON (or reads `DATA_DIR/foodkeeper.json`), converts ranges to days using the low end, and upserts by `usda_id`.
- `match_rule()` checks `food_map` first, then scores rules by name and keyword overlap, with a bonus for `custom` over `usda` over `starter` rules.
- `apply_pantry_action()` implements use, open, move (freeze, thaw, pantry↔fridge), set date, change rule, toss and restore, logging each to `pantry_events`. Opening can only shorten a date.
- Checking a list item off as bought adds it to the pantry only when a rule matches (`to_pantry: "auto"`).

---

## Notifications

Each message kind has one builder (`msg_list`, `msg_plan`, `msg_pantry`, `msg_expiring`, `msg_test`) returning subject, text, HTML and attachments. `deliver(msg, channel)` sends it to one channel or all configured ones (`channels_ready()`), and only fails if every channel fails.

- **Email:** `smtplib`, STARTTLS / SSL / none, HTML body plus CSV/ICS attachments.
- **Telegram:** Bot API over HTTPS, outbound only. Linking uses a one-time code read with `getUpdates`. Messages are split under 4,000 characters; plans attach the `.ics`.
- **ntfy:** JSON publish to the server root, with an optional bearer token.

---

## The scheduler

A daemon thread started in `main()` loops every **5 minutes**. Each step is wrapped so one failure doesn't stop the others.

| Job | Runs when | Guard against repeats |
|---|---|---|
| New-version notice | An update is available and a channel is set up | `update_notified` = that version |
| Automatic weekly plan | `auto_plan_day` matches today and it's 8:00 or later (server time) | `auto_plan_last` = today |
| Daily "use soon" alert | `expiry_alert` on and the hour ≥ `expiry_alert_hour` | `expiry_alert_last` = today |
| Pantry check-in reminder | A check-in is due and the hour ≥ `expiry_alert_hour` | `checkin_nudge_<last check date>` |
| AI budget alert | `ai_budget` > 0 and spend reaches 80% or 100% | `ai_budget_<month>_<level>` |

Time-based jobs use the container's local time, so `TZ` matters.

---

## Update feed and release pipeline

`.github/workflows/release.yml` runs on every push to `main` (except Markdown-only changes) and on manual dispatch:

1. **Version:** `<VERSION file>.<run number>`, for example `0.4.17`. The first line of the commit message becomes the release note.
2. **Image:** builds `linux/amd64` and `linux/arm64` with Buildx and pushes `ghcr.io/<owner>/<repo>:<version>` and `:latest`. The version is baked into `/app/VERSION`.
3. **ZimaOS store:** stamps the version, image tag, date and release note into `zimaos-store/Apps/TablePlan/docker-compose.yml`, rewrites owner/repo for forks, and builds the store with `IceWhaleTech/build-appstore-action`.
4. **GitHub Pages** (`gh-pages` branch): publishes the store (`store.json`, `index.json`), `version.json`, `install.sh`, `docker-compose.yml`, and `docs/setup.html` as `/setup/`.

At runtime, `update_info()` fetches `TABLEPLAN_UPDATE_FEED` (`version.json`: `version`, `released`, `notes`) at most every 10 minutes and compares the first three numbers of the version. A `dev` build never reports updates. The browser polls `/api/version` hourly and when the tab becomes visible, showing the banner; the scheduler sends the one-time notification. ZimaOS sees the store's new version and shows **Update**.

---

## Tests

Unit tests live in `app/tests/` (`test_native_*.py`) and cover the native modules: recipe storage and images, plans, lists and merging, the Mealie migration, and JSON-LD / microdata parsing. Run them from the repo root:

```bash
python3 -m unittest discover -s app/tests -t .
```
