<p align="center"><img src="app/static/icon.svg" width="88" alt="TablePlan"></p>
<h1 align="center">TablePlan</h1>
<p align="center"><b>Recipes, auto meal plans, a smart pantry and grocery lists for your household, self-hosted.</b><br>
Built on <a href="https://github.com/mealie-recipes/mealie">Mealie</a>. Made for ZimaOS, and runs on any Docker host.</p>

---

## Features

- **Recipes from anywhere.** Paste a link, or snap a screenshot or cookbook page. AI import uses your own OpenAI key. TikTok and YouTube links work too.
- **Auto meal plans.** Fill a week or a month in one tap:
  - nothing repeats within N days
  - favorites come up more often
  - recipes that use food expiring soon go first
- **Portions that fit.** Set how many people you cook for, and every planned recipe and shopping list is scaled to match.
- **Smart pantry.** Check items off the shopping list and they get real use-by dates from USDA FoodKeeper.
  - Use half the cream and the rest switches to its after-opening date.
  - Freeze it and it switches to the freezer date.
- **Share anything.** Email (SMTP), print, CSV, text, or `.ics` calendar export for lists, plans and pantry.
- **Apple Home–style app.** Add it to your phone's Home Screen. Light and dark mode.
- **Setup wizard.** Creates your recipe account and API token, connects OpenAI and email, and sets an optional password. You can skip any step and finish it later in Settings.

## Install

### Option A: ZimaOS App Store (recommended, with update prompts)

1. In ZimaOS open **App Store → Community store → Add** and paste:
   ```
   https://thomasjvalenzuela.github.io/tableplan/store.json
   ```
2. Pick the **TablePlan** store, find **TablePlan** and tap **Install**. Mealie is installed with it.
3. Open TablePlan. The setup wizard walks you through the rest.

Every push to `main` publishes a new version to that store. ZimaOS then shows **Update** on TablePlan, and the app shows an update banner too.

### Option B: one command over SSH

```bash
curl -fsSL https://thomasjvalenzuela.github.io/tableplan/install.sh | sudo bash
```

This installs to `/media/DATA/AppData/tableplan` (or `/DATA/AppData/tableplan`), starts TablePlan on **:9930** and Mealie on **:9925**, and prints the address to open. To manage it later:

```bash
sudo tableplan status | update | logs | backup | uninstall
```

### Option C: any Docker host

Copy the compose block from [`install/install.sh`](install/install.sh). It's two services: `ghcr.io/thomasjvalenzuela/tableplan:latest` and `ghcr.io/mealie-recipes/mealie`.

## How releases work

```
git push main ─► GitHub Actions ─┬─► ghcr.io/thomasjvalenzuela/tableplan:0.2.N  (+ :latest, amd64 + arm64)
                                 ├─► ZimaOS store on GitHub Pages (version 0.2.N) ──► ZimaOS shows "Update"
                                 └─► version.json ──► in-app "Update available" banner
```

- The version is `VERSION` (major.minor) followed by the workflow run number. Bump `VERSION` for bigger releases.
- The release note is the first line of the commit message.

### One-time GitHub setup

1. Push this repo to `github.com/thomasjvalenzuela/tableplan` as a **public** repo.
2. The first push runs the **Release** workflow. Wait for it to go green.
3. Go to **Settings → Pages**: Source = *Deploy from a branch*, Branch = `gh-pages` / `root`.
4. Go to **Profile → Packages → tableplan → Package settings**: set visibility to **Public**, so ZimaOS can pull the image without logging in.

## Development

```bash
cd app && DATA_DIR=./.data MEALIE_URL=http://<your-mealie>:9925 python3 server.py   # http://localhost:8080
```

- No dependencies: it's Python standard library, SQLite and vanilla JS.
- `app/server.py` is the API and the Mealie client.
- `app/static/` holds the PWA, with the setup wizard in `setup.js`.
- `zimaos-store/` holds the ZimaOS app store definition.
- `install/install.sh` is the SSH installer.

## Data and privacy

- Everything stays on your server.
- TablePlan stores its settings, pantry and shelf-life rules in `data/tableplan.db`. Secrets such as the Mealie token and SMTP password are never sent back to the browser.
- Recipes, meal plans and shopping lists live in Mealie.
- The OpenAI key is stored in Mealie and used only for imports.

## Credits

- [Mealie](https://github.com/mealie-recipes/mealie) (AGPL-3.0) is the recipe engine. TablePlan talks to it only over its REST API.
- Shelf-life data comes from [USDA FSIS FoodKeeper](https://catalog.data.gov/dataset/fsis-foodkeeper-data) (public domain).
