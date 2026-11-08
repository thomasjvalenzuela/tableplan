# Contributing to TablePlan

Thanks for helping. Bug reports, fixes, docs and feature ideas are all welcome. By taking part
you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Run it locally

TablePlan uses only the Python 3.12+ standard library, SQLite and vanilla JS. There's nothing to
install and no build step.

```bash
cd app
DATA_DIR=./data python3 server.py
# open http://localhost:8080 and the setup wizard starts
```

Useful environment variables: `DATA_DIR` (where the SQLite database and photos live),
`PORT` / `LISTEN_PORT` (default `8080`), `TZ`, and `TABLEPLAN_PUBLIC=1` to try the
internet-facing sign-in flow. `app/data/` is git-ignored.

Video import needs `yt-dlp` (`pip install -r docker/requirements.txt`); everything else works
without it.

To try the container the way users run it:

```bash
docker build -t tableplan:dev .
docker run --rm -p 8080:8080 -v "$PWD/app/data:/data" tableplan:dev
```

The image runs the server as uid 1000. If the mounted `/data` belongs to someone else, the
entrypoint (`docker/entrypoint.sh`) takes ownership of it before dropping root.

## Project layout

| Path | What's there |
|---|---|
| `app/server.py` | HTTP API, meal-plan generator, pantry and shelf-life logic, notifications, exports, the one-time "Import from Mealie" |
| `app/native/` | Recipe, meal-plan and shopping-list storage, and the recipe reader used for link imports |
| `app/tests/` | Unit tests (`unittest`) |
| `app/static/` | The PWA. `app.js` holds the main UI and `setup.js` holds sign-in, the setup wizard and the Settings sections. `vendor/` is third-party code, left as shipped. |
| `app/seed/` | Starter shelf-life table, used until the USDA FoodKeeper sync runs |
| `docker/` | Container entrypoint and the pinned Python packages baked into the image |
| `install/` | One-command installer and plain compose files |
| `zimaos-store/` | ZimaOS community app store definition (store v2 format) |
| `docs/setup.html` | Illustrated install guide, published to `/setup/` on GitHub Pages |
| `railway.toml` | Railway deployment config |

## Checks

CI (`.github/workflows/ci.yml`) runs these on every pull request. Run them before you push:

```bash
python3 -m py_compile app/server.py app/native/*.py
python3 -m unittest discover -s app/tests -t .
for f in app/static/*.js; do node --check "$f"; done
bash -n install/install.sh
docker build -t tableplan:ci .          # optional, CI does it too
```

CodeQL also scans the Python and JavaScript code on every pull request.

## Code style

- **No new dependencies.** Standard library only on the server, vanilla JS in the browser, no
  build step. That's what keeps the image tiny and the install painless. `yt-dlp` in the image is
  the one, optional exception.
- Python: PEP 8, 4-space indents, small functions. Use parameterised SQL (`?` placeholders), never
  string formatting, for anything that touches user input.
- JavaScript: `"use strict"`, 2-space indents. Escape anything user-supplied before it goes into
  `innerHTML` (use the existing `esc()` / `_esc()` helpers).
- Keep UI text short and in plain English; TablePlan is meant for the whole household, not just
  the person who installed it.
- Never break existing installs: data in `/data` must keep working after an update. If you change
  the database, add a migration.
- `.editorconfig` sets the basics (UTF-8, LF, final newline).

## Pull requests

1. For anything bigger than a small fix, open an issue first so we can agree on the approach.
2. Fork, create a branch from `main`, and keep each pull request focused on one change.
3. Add or update tests in `app/tests/` where it makes sense, and update the docs if behaviour or
   setup changes. Add a line under **Unreleased** in [CHANGELOG.md](CHANGELOG.md).
4. Make sure CI is green, then fill in the pull request template.
5. A maintainer reviews and merges. Pull requests are squash-merged, so the PR title becomes the
   commit subject and the release note: write it as a short, plain-English summary.

By contributing you agree that your contributions are licensed under the
[GNU AGPL-3.0](LICENSE), the project's license.

## How releases work

Every push to `main` (except Markdown-only changes) runs `.github/workflows/release.yml`, which:

1. **Builds the image** for `linux/amd64` and `linux/arm64`, then pushes
   `ghcr.io/<owner>/tableplan:<version>` and `:latest`.
2. **Stamps the version** into `zimaos-store/Apps/TablePlan/docker-compose.yml`, then builds the
   store with `IceWhaleTech/build-appstore-action`.
3. **Publishes to GitHub Pages** (the `gh-pages` branch):
   - `store.json` and `index.json`: the ZimaOS community store. ZimaOS shows **Update** when the version changes.
   - `version.json`: drives the in-app "Update available" banner.
   - `install.sh`, `docker-compose.yml`
   - `setup/`: the install guide

Versions are numbered `<VERSION file>.<workflow run number>`, for example `0.4.17`. Bump `VERSION`
for bigger releases and give the new version its own heading in `CHANGELOG.md`. The first line of
the commit message becomes the release note.

Third-party GitHub Actions are pinned to full commit SHAs (with the version in a comment);
Dependabot opens weekly pull requests to update them, the base image and `yt-dlp`.

## Publishing your own fork

The workflow uses your GitHub username and repo name automatically.

1. Fork the repo and enable Actions on it. The release job requests the write permissions it needs
   itself, so the default workflow permissions can stay **Read repository contents**.
2. Push to `main` and wait for the **Release** workflow to go green.
3. In **Settings → Pages**, choose **Deploy from a branch** → `gh-pages` / `root`.
4. In your profile → **Packages → tableplan → Package settings**, change visibility to **Public**.
5. Your store URL is `https://<you>.github.io/<repo>/store.json`.

The hard-coded `thomasjvalenzuela` in the README, the installer defaults and `app/server.py`
(`TABLEPLAN_UPDATE_FEED`) are for the main project. Change them in your fork if you want your own
update feed.

## Security

- Never commit secrets. User credentials (the OpenAI key, notification tokens and SMTP password)
  live only in the server's `tableplan.db` under `DATA_DIR`, and the API never returns them.
- Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md)
  (**Security → Report a vulnerability**), not as public issues.
