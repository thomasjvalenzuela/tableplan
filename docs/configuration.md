# Configuration

TablePlan is configured in two places:

1. **The app itself** (setup wizard and Settings). This is where almost everything is set, and it's stored in the database.
2. **Environment variables** on the container. These are for deployment details (port, data folder, public mode) and can optionally pre-fill credentials.

- [Environment variables](#environment-variables)
- [Settings in the app](#settings-in-the-app)
- [Where settings are stored](#where-settings-are-stored)

---

## Environment variables

### Deployment

| Variable | Default | Meaning |
|---|---|---|
| `TZ` | container default (UTC) | Your time zone, for example `America/New_York`. Used for "today", use-by dates, the daily reminder time and the 8 AM auto-plan. Not read by TablePlan directly; the image includes time zone data so it takes effect. |
| `PORT` | unset | Port to listen on inside the container. Set automatically by hosts such as Railway. When set, it's used instead of `LISTEN_PORT`. |
| `LISTEN_PORT` | `8080` | Port to listen on inside the container when `PORT` isn't set. Map it to a host port (the install files use `9930:8080`). |
| `DATA_DIR` | `/data` | Folder for the database (`tableplan.db`) and photos (`images/`). Mount a volume here. |
| `TABLEPLAN_PUBLIC` | off (on when running on Railway) | Public mode, for servers reachable from the internet. Sign-in is always required, and until a household password is set, the one-time setup code from the log is the only way in. Imports, AI calls and outbound fetches are rate-limited per client, and notification servers must be on the public internet. See [security.md](security.md#public-mode-and-the-setup-code). |
| `TABLEPLAN_TRUST_PROXY` | off (on when running on Railway) | Trust `X-Forwarded-For` and `X-Forwarded-Host` from a reverse proxy in front of TablePlan. Turn it on only when such a proxy sets those headers and strips any the client sends. |
| `TABLEPLAN_MAX_IMPORTS` | `3` | How many heavy imports (page reading, video download and transcription, AI) run at the same time. Others wait their turn. |
| `RAILWAY_ENVIRONMENT`, `RAILWAY_ENVIRONMENT_NAME` | set by Railway | When either is present, `TABLEPLAN_PUBLIC` and `TABLEPLAN_TRUST_PROXY` default to on. You don't set these yourself. |
| `TABLEPLAN_INSTALL` | `zimaos` | How TablePlan was installed: `zimaos`, `cli` (one-line installer) or `manual` (Compose and everything else). Only changes the update instructions in "new version" notifications. |
| `TABLEPLAN_UPDATE_FEED` | `https://thomasjvalenzuela.github.io/tableplan/version.json` | Where TablePlan checks for new versions. Point it at your own fork's GitHub Pages, or at an unreachable address to stop the check. |
| `FOODKEEPER_URL` | `https://www.fsis.usda.gov/shared/data/EN/foodkeeper.json` | Where the USDA FoodKeeper shelf-life data is downloaded from. |
| `TELEGRAM_API_URL` | `https://api.telegram.org` | Telegram Bot API base URL. Change only if you run your own Bot API server. |

On/off variables (`TABLEPLAN_PUBLIC`, `TABLEPLAN_TRUST_PROXY`) accept `1`, `true`, `yes`, `on` and `0`, `false`, `no`, `off`. An explicit value overrides the Railway default.

### Optional credential defaults

These pre-fill settings you'd normally enter in the wizard. **A value saved in the app always wins**; the environment variable is only used while the app setting is empty.

| Variable | Default | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | empty | OpenAI API key for AI features. |
| `OPENAI_MODEL` | `gpt-5-mini` | OpenAI model. It must accept images for screenshot import. |
| `OPENAI_ADMIN_KEY` | empty | OpenAI Admin key (`sk-admin-…`), read-only use for exact monthly costs. |
| `SMTP_HOST` | empty | SMTP server for email. |
| `SMTP_PORT` | `587` | SMTP port. |
| `SMTP_SECURITY` | `starttls` | `starttls`, `ssl` or `none`. |
| `SMTP_USER` | empty | SMTP username. |
| `SMTP_PASSWORD` | empty | SMTP password or app password. |
| `SMTP_FROM` | `SMTP_USER` | From address. |
| `MAIL_TO` | empty | Comma-separated recipients. Email is only active when `SMTP_HOST` and `MAIL_TO` are both set. |
| `TELEGRAM_BOT_TOKEN` | empty | Telegram bot token. |
| `TELEGRAM_CHAT_ID` | empty | Telegram chat ID. Both token and chat ID are needed. |
| `NTFY_SERVER` | `https://ntfy.sh` | ntfy server. |
| `NTFY_TOPIC` | empty | ntfy topic. Setting it turns ntfy on. |
| `NTFY_TOKEN` | empty | ntfy access token. |

### Legacy (Mealie backend)

TablePlan v0.3 and earlier stored recipes in a bundled Mealie. That mode still exists for old setups but isn't needed or recommended.

| Variable | Default | Meaning |
|---|---|---|
| `TABLEPLAN_BACKEND` | `native` | `mealie` switches back to storing recipes, plans and lists in Mealie. |
| `MEALIE_URL` | `http://mealie:9000` | Mealie API address (legacy mode). |
| `MEALIE_API_TOKEN` | empty | Mealie API token (legacy mode). If set before setup, the wizard is skipped. |
| `MEALIE_PUBLIC_URL` | empty | Mealie address used for links (legacy mode). |
| `MEALIE_PUBLIC_PORT` | `9925` | Port used for Mealie links when `MEALIE_PUBLIC_URL` is empty (legacy mode). |
| `MEALIE_GROUP_SLUG` | `home` | Mealie group (legacy mode). |

To copy an existing Mealie into TablePlan, you don't need any of these. Use [Import from Mealie](importing-from-mealie.md).

---

## Settings in the app

Paths are as shown in **Settings** (gear button, or the sidebar on desktop).

### Setup

| Setting | Where | Default | Meaning |
|---|---|---|---|
| Household name | Setup → Household | empty | Shown in the app. |
| People you cook for | Setup → Household | 2 | 1–30. Planned meals and shopping lists scale to this. |
| Scale recipes to fit | Setup → Household | On | When on, planning a recipe sets its scale to people ÷ recipe servings. |
| OpenAI API key, Model | Setup → AI recipe import | none, `gpt-5-mini` | Tested before saving. |
| Telegram, ntfy, Email | Setup → Notifications | not set | See the [user guide](user-guide.md#notifications). Each can be disconnected there. |
| Password | Setup → Password | Off | Household password (4+ characters). **Remove password** turns it off (not allowed in public mode). |

### Cooking

| Setting | Values | Default | Meaning |
|---|---|---|---|
| Recipe style | Classic, Step-by-step | Classic | How recipes open. |
| Stovetop | Gas, Electric, Induction | Electric | Tunes heat tips in Step-by-step. |
| Oven | Conventional, Convection / fan | Conventional | Convection lowers oven temperatures by 25 °F / 15 °C in Step-by-step. |
| Temperatures | °F, °C | °F | Unit for Step-by-step temperatures. |

### Meal planning

| Setting | Default | Meaning |
|---|---|---|
| Meals to plan | Dinner | Breakfast, lunch, dinner, side. Default for Auto-plan and automatic planning. |
| No repeats for (days) | 14 | 0–90. A recipe isn't picked again within this many days. |
| Use food before it goes bad | On | Plans favor recipes using items close to their use-by date. |
| Warn me this many days early | 3 | 1–14. Items this close to their use-by date show as "use soon". |
| Plan next week automatically on | Off | A weekday. From 8 AM that day, fills empty slots for the next 7 days. |
| Send me the plan | Off | Send the automatically made plan to all notification channels. |
| Daily "use soon" reminder | Off | A daily message listing food that expires today or tomorrow. |
| Reminder time | 8:00 AM | Time for the daily reminder and the check-in reminder (server time). |

### Pantry

| Setting | Default | Meaning |
|---|---|---|
| Check-in reminder | Weekly | Off, Weekly, Every 2 weeks, Monthly. |

### AI

| Setting | Where | Default | Meaning |
|---|---|---|---|
| Monthly budget | AI → AI spending | Off | USD per month. Alerts at 80% and 100%. |
| Admin key | AI → AI spending | none | Optional OpenAI Admin key for exact costs. |

### Other sections

| Section | What's there |
|---|---|
| Import → **Share to TablePlan from your phone** | iPhone Shortcut and Android steps. |
| Shelf life data | USDA FoodKeeper status, **Sync now**, **House rules & edits**. |
| Advanced | **Import from Mealie**, **Run setup wizard again**, **Sign out on this device** (when a password is set). |

### Settings with no screen

These are saved defaults that the Auto-plan sheet lets you change per run. They can also be set through the API (`PUT /api/settings`).

| Key | Default | Meaning |
|---|---|---|
| `include_tags` | `[]` | Only plan recipes with these tags. |
| `exclude_tags` | `[]` | Never plan recipes with these tags. |
| `fill_empty_only` | `true` | Leave already-planned meals alone. |

All `PUT /api/settings` keys, with the values the server accepts (anything else is rejected with `400`):

| Key | Accepted values |
|---|---|
| `meal_types` | list of `breakfast`, `lunch`, `dinner`, `side`, `snack`, `dessert`, `drink` |
| `no_repeat_days` | 0–365 |
| `prefer_expiring`, `fill_empty_only`, `auto_plan_email`, `expiry_alert` | `true` / `false` |
| `include_tags`, `exclude_tags` | lists of up to 200 tags |
| `auto_plan_day` | `""` (off) or `mon` … `sun` |
| `expiry_alert_hour` | 0–23 |
| `recipe_style` | `classic`, `steps` |
| `stove` | `gas`, `electric`, `induction` |
| `oven` | `conventional`, `convection` |
| `temp_unit` | `F`, `C` |
| `ai_budget` | 0–100000 (USD) |
| `pantry_check_days` | 0–365 (0 = off) |
| `expiring_window_days` | 0–60 |

### Settings kept in the browser

| What | Stored as |
|---|---|
| Last-used shopping list | `tp.list` |
| "Update available" banner hidden for a day | `tp.updSnooze` |
| Last "What's new" seen | `tp.seen` |
| Import time estimates | `tp.eta.*` |

---

## Where settings are stored

All app settings and credentials are rows in the `settings` table of `DATA_DIR/tableplan.db`. Credentials (OpenAI keys, SMTP password, bot and ntfy tokens, the password hash, the session secret) are never sent to the browser. See [security.md](security.md).
