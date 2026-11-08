<p align="center"><img src="app/static/icon.svg" width="88" alt="TablePlan"></p>
<h1 align="center">TablePlan</h1>
<p align="center"><b>Recipes, auto meal plans, a smart pantry and grocery lists for your household, self-hosted.</b><br>
Runs on ZimaOS, CasaOS, Unraid, Portainer or any Linux server with Docker. One app, one container.</p>

<p align="center">
<a href="#install-in-3-steps">Install</a> ·
<a href="docs/user-guide.md">User guide</a> ·
<a href="docs/importing-from-mealie.md">Coming from Mealie?</a> ·
<a href="#updating">Updating</a> ·
<a href="docs/https-and-remote-access.md">HTTPS</a> ·
<a href="docs/troubleshooting.md">Troubleshooting</a> ·
<a href="docs/README.md">All docs</a>
</p>

---

## What it does

- 📸 **Save recipes from anywhere.** Paste a link from a recipe site, Instagram, TikTok, YouTube or a Google Doc, share it from your phone, paste text, or snap a screenshot, cookbook page or PDF.
- 🗓️ **Auto meal plans.** Fill a week or a month in one tap. Nothing repeats too often, and food that's about to expire gets used first. It can even plan next week for you automatically.
- 👨‍👩‍👧 **Right-sized portions.** Tell it how many people you cook for, and planned meals and shopping lists scale to match.
- 🍳 **Cook with confidence.** Switch any recipe to *Step-by-step*, tuned to your stove and oven, then cook hands-free with built-in timers.
- 🥛 **Smart pantry.** Tick items off the shopping list and they get real use-by dates from the USDA FoodKeeper database. Open something and the date switches to "after opening"; freeze it and it switches to the freezer date. Scan barcodes to add items.
- 🛒 **Lists that know your pantry.** Before a list is built, confirm what you already have. Ingredients from different recipes merge and are sorted by store section.
- 📲 **Sent to your phone.** Lists, plans and use-soon alerts by Telegram, ntfy or email. Print or export them, and add plans to your calendar (.ics).
- 📱 **Feels like an app.** Add it to your phone's Home Screen.

AI is optional. With your own OpenAI key, TablePlan reads screenshots, PDFs and spoken video recipes and arranges recipes step by step. Everything else works without it. See [what works without AI](docs/user-guide.md#what-works-without-ai).

> 💡 **TablePlan is a single app.** Recipes, photos, meal plans, shopping lists and your pantry are stored by TablePlan itself, in one container with one data folder. There's no separate recipe server, database or account to set up.

**New in v0.4:** no more Mealie. One app, one container. Link import uses TablePlan's own recipe reader with an AI fallback, and video, Google Doc, PDF and pasted-text imports were added.

---

## Install in 3 steps

### Before you start

You need:

- A home server with **Docker**, such as ZimaOS, CasaOS, Unraid, Ubuntu or Debian. Raspberry Pi 4/5 and other ARM boards work too.
- A few hundred MB of free RAM, plus some disk space for recipe photos.
- One free port: **9930**.

Optional, and both can be set up later:

- An **OpenAI API key** to import recipes from screenshots and photos. It costs a few cents per recipe.
- **Telegram**, **ntfy** or an **email account** to get lists and alerts on your phone.

### Step 1: Install

Pick **one**:

<details open>
<summary><b>🟠 ZimaOS: install from the App Store (easiest)</b></summary>

1. Open **App Store**, click **Community store** (top right), then **Add**.
2. Paste this address and confirm:
   ```
   https://thomasjvalenzuela.github.io/tableplan/store.json
   ```
3. Switch to the **TablePlan** store, click **TablePlan**, then **Install**.
4. When the TablePlan tile shows **Running**, click it.

ZimaOS shows an **Update** button whenever a new version comes out.
</details>

<details>
<summary><b>🐧 Any Linux server (CasaOS, Ubuntu, Debian, Raspberry Pi…): one command</b></summary>

1. Open a terminal on the server, or connect with SSH.
2. Paste:
   ```bash
   curl -fsSL https://thomasjvalenzuela.github.io/tableplan/install.sh | sudo bash
   ```
3. When it finishes, it prints the address to open, like `http://192.168.1.20:9930`.

The installer checks everything first and won't touch your other apps. Afterwards, manage it with `sudo tableplan status | update | logs | backup | uninstall`.
</details>

<details>
<summary><b>🐳 Docker Compose, Portainer, Dockge or Unraid</b></summary>

```bash
mkdir tableplan && cd tableplan
curl -fsSLO https://thomasjvalenzuela.github.io/tableplan/docker-compose.yml
docker compose up -d
```

**Portainer / Dockge:** create a new stack and paste the contents of [`docker-compose.yml`](install/docker-compose.yml).

Edit `TZ` in the file to your time zone (for example `America/New_York`) so use-by dates and reminders are exact.
</details>

More options, including custom ports and folders: [docs/install.md](docs/install.md). Running in the cloud: [Railway (beta)](docs/deploy-railway.md).

### Step 2: Run the setup wizard

Open **`http://YOUR-SERVER-IP:9930`**. A short wizard appears. You can **Skip** any step and finish it later in **Settings**.

| Screen | What to do |
|---|---|
| **Household** | Enter a name and how many people you cook for. |
| **Import from screenshots** | Paste an OpenAI key from [platform.openai.com/api-keys](https://platform.openai.com/api-keys) and add a few dollars of credit there. TablePlan tests the key before saving. |
| **Notifications** | Telegram, ntfy or email. A test message confirms it works. For Gmail, use an [App Password](https://myaccount.google.com/apppasswords). |
| **Lock it** | Optional household password. Use one if anyone outside your home can reach the server. |

### Step 3: Put it on your phone

- **iPhone (Safari):** open `http://YOUR-SERVER-IP:9930`, tap **Share**, then **Add to Home Screen**.
- **Android (Chrome):** open it, tap **⋮**, then **Add to Home screen**.

Tap **+** on the Home tab to add your first recipe. To send links straight from Instagram or TikTok, see [Sharing recipes from your phone](docs/user-guide.md#sharing-recipes-from-your-phone).

---

## Updating

TablePlan shows a blue **Update available** banner when a new version is out.

| Installed with | How to update |
|---|---|
| ZimaOS App Store | App Store → **My Apps** → TablePlan → **Update** |
| One-command installer | `sudo tableplan update`, or run the install command again |
| Docker Compose | In the TablePlan folder: `docker compose pull && docker compose up -d` |
| Portainer | Stacks → tableplan → **Update the stack** with *Re-pull image* turned on |

Your recipes, pantry and settings are kept.

## Backup

All your data (recipes, photos, plans, lists, pantry and settings) lives in one `data/` folder: a SQLite database plus an `images/` folder. Installer users can run `sudo tableplan backup`. Details, restore and uninstall: [docs/install.md](docs/install.md#backups).

## HTTPS and using it away from home

TablePlan works over plain `http://` at home. Adding HTTPS turns on live barcode scanning, lets Android add TablePlan to its Share menu, and removes Chrome's "Not secure" label. The easiest way, which also works away from home, is **Tailscale**. Never port-forward 9930 to the internet. See [docs/https-and-remote-access.md](docs/https-and-remote-access.md).

## Common problems

| Problem | Fix |
|---|---|
| ZimaOS says "Failed to add community store" | Use the full address ending in **`/store.json`**, with no spaces. |
| Screenshot import doesn't work | Check your OpenAI key and credit in **Settings → AI recipe import**. |
| Live barcode scanning doesn't open the camera | The camera needs HTTPS. Take a photo of the barcode or type the number instead. |
| Email test failed | Gmail, Yahoo and iCloud need an **app password**, not your normal password. |
| Use-by dates off by a day | Set `TZ` to your time zone and recreate the container. |
| Port already in use | Installer: add `TABLEPLAN_PORT=8930` before `bash`. Compose: change the left-hand port number. |

More fixes: [docs/troubleshooting.md](docs/troubleshooting.md). Questions about privacy and costs: [docs/faq.md](docs/faq.md).

## Documentation

| | |
|---|---|
| [User guide](docs/user-guide.md) | Every feature, task by task |
| [Install](docs/install.md) | All install methods, updating, backup, restore, uninstall |
| [Configuration](docs/configuration.md) | Environment variables and settings |
| [HTTPS and remote access](docs/https-and-remote-access.md) | Tailscale, reverse proxies, public mode |
| [Deploy on Railway](docs/deploy-railway.md) | Cloud deployment (beta) |
| [Security](docs/security.md) | What's stored where, and what leaves your server |
| [Importing from Mealie](docs/importing-from-mealie.md) | Bring your Mealie library over |
| [Architecture](docs/architecture.md) | For contributors |

## Contributing

Bug reports and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to develop locally, how releases work, and how to publish your own fork.

## License & credits

- **TablePlan:** [AGPL-3.0](LICENSE).
- **[Mealie](https://github.com/mealie-recipes/mealie)** (AGPL-3.0) inspired TablePlan's recipe, meal-plan and shopping-list data format. Earlier versions used Mealie as their recipe engine.
- **[USDA FSIS FoodKeeper](https://catalog.data.gov/dataset/fsis-foodkeeper-data)** (public domain): shelf-life data.
- **[Open Food Facts](https://world.openfoodfacts.org)** ([ODbL](https://opendatacommons.org/licenses/odbl/1-0/)): barcode product data.
- **[zxing-wasm](https://github.com/Sec-ant/zxing-wasm)** (MIT): barcode decoding in the browser.
- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** (Unlicense): reading video recipe posts.
- **[TheMealDB](https://www.themealdb.com)**: ingredient images.
- **[Openverse](https://openverse.org)**: openly licensed recipe photos.
