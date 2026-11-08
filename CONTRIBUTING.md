# Contributing to TablePlan

## Run it locally

TablePlan uses only the Python 3.12+ standard library, SQLite and vanilla JS. There's nothing to install and no build step.

```bash
cd app
DATA_DIR=./.data python3 server.py
# open http://localhost:8080 and the setup wizard starts
```

TablePlan is a single app: recipes, meal plans, shopping lists and the pantry are all stored in its own SQLite database under `DATA_DIR`.

Run the tests from the repo root with `python3 -m unittest discover -s app/tests -t .`

| Path | What's there |
|---|---|
| `app/server.py` | HTTP API, meal-plan generator, pantry and shelf-life logic, notifications, exports, the one-time "Import from Mealie" |
| `app/native/` | Recipe, meal-plan and shopping-list storage, and the recipe reader used for link imports |
| `app/tests/` | Unit tests for `app/native/` |
| `app/static/` | The PWA. `app.js` holds the main UI and `setup.js` holds sign-in, the setup wizard and the Settings sections. |
| `app/seed/` | Starter shelf-life table, used until the USDA FoodKeeper sync runs |
| `install/` | One-command installer and plain compose files |
| `zimaos-store/` | ZimaOS community app store definition (store v2 format) |
| `docs/setup.html` | Illustrated install guide, published to `/setup/` on GitHub Pages |

Please keep the no-dependencies rule. It's what makes the image tiny and the install painless.

## How releases work

Every push to `main` (except Markdown-only changes) runs `.github/workflows/release.yml`, which does three things:

1. **Builds the image** for `linux/amd64` and `linux/arm64`, then pushes `ghcr.io/<owner>/tableplan:<version>` and `:latest`.
2. **Stamps the version** into `zimaos-store/Apps/TablePlan/docker-compose.yml`, then builds the store with `IceWhaleTech/build-appstore-action`.
3. **Publishes to GitHub Pages** (the `gh-pages` branch):
   - `store.json` and `index.json`: the ZimaOS community store. ZimaOS shows **Update** when the version changes.
   - `version.json`: drives the in-app "Update available" banner.
   - `install.sh`, `docker-compose.yml`
   - `setup/`: the install guide

Versions are numbered `<VERSION file>.<workflow run number>`, for example `0.2.17`. Bump `VERSION` for bigger releases. The first line of the commit message becomes the release note.

## Publishing your own fork

The workflow uses your GitHub username and repo name automatically.

1. Fork the repo. In **Settings → Actions → General → Workflow permissions**, choose **Read and write**.
2. Push to `main` and wait for the **Release** workflow to go green.
3. In **Settings → Pages**, choose **Deploy from a branch** → `gh-pages` / `root`.
4. In your profile → **Packages → tableplan → Package settings**, change visibility to **Public**.
5. Your store URL is `https://<you>.github.io/<repo>/store.json`.

The hard-coded `thomasjvalenzuela` in the README, the installer defaults and `app/server.py` (`TABLEPLAN_UPDATE_FEED`) are for the main project. Change them in your fork if you want your own update feed.

## Security

- Never commit secrets. User credentials (the OpenAI key, notification tokens and SMTP password) live only in the server's `data/tableplan.db`, and the API never returns them.
- Report security issues privately through GitHub's **Security → Report a vulnerability**, not as public issues.
