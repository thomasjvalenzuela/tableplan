# Changelog

All notable changes to TablePlan are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Release builds are numbered
`<VERSION>.<build>` (for example `0.4.12`), so each minor version below covers every build
published from it.

## [0.5.0] - 2026-11-08
### Added
- Plan tab: a rolling two-week dinner board. Tap a day to pick a recipe, drag meals between days (touch and hold on phones), remove with Undo.
- Planning a meal adds its ingredients to the shopping list (skipping what the pantry covers); removing it takes unbought items back off.
- "Your plan runs out" reminder through Telegram, ntfy or email (Settings → Planning).
- One ongoing shopping list with stores (Aldi and Costco to start, add your own). Each item remembers its store; filter by the store you're in.
- "I have this" on list items; Start cooking shows missing ingredients until you have them.
- Recipe Share & Export: print or save as PDF on index cards (3×5, 4×6), 5×7, half letter, Letter or A4; send, share, copy, or download as text, Markdown or JSON.
- Automatic nightly backups (14 kept) plus a snapshot before every update; Settings → Backups to download a backup or everything as a .zip.
- A warning banner if data isn't on a persistent volume.

## [Unreleased]

### Added
- Railway deployment config (`railway.toml`).
- CI (syntax checks, unit tests, Docker build and smoke test), CodeQL scanning and Dependabot.
- Security policy, code of conduct, issue and pull request templates.

### Changed
- The container now runs as an unprivileged user (uid 1000). On start-up it takes ownership of
  an existing `/data` volume created by older, root-run versions, so upgrades need no manual steps.
- The Docker health check honours the `PORT` environment variable.
- yt-dlp is pinned in the image and kept current by Dependabot.

### Security
- Release workflow: least-privilege token permissions, third-party actions pinned to commit SHAs,
  and commit messages handled only through environment variables.

## [0.4] - 2026-11-08

### Added
- More ways to import recipes: Instagram, TikTok and YouTube videos, Google Docs, PDFs,
  pasted text and the phone share sheet.
- Recipe photos taken from the source page.
- Update alerts: a banner on every screen, a dot on Settings and a one-time phone notification.

### Changed
- TablePlan runs on its own backend (SQLite); Mealie is no longer required. Existing Mealie data
  can be imported once.
- Step-by-step cook mode uses AI automatically, and each step lists only the ingredients it adds.
- Plain-English meal planner settings; better link import for sites such as NYT Cooking.

### Fixed
- Screenshot import failing with "Unterminated string", with a plain-text fallback when the
  structured answer is unreadable.
- Planner: turning off "Only fill empty days" now replaces existing meals instead of duplicating them.

## [0.3] - 2026-11-08

### Added
- Recipes inside TablePlan, step-by-step cook mode, pantry scan and more reliable screenshot import.
- Notifications through Telegram, ntfy and email, with a daily "use soon" alert.
- HTTPS guide (Tailscale Serve or a reverse proxy) and a Mealie link address setting.
- Beginner-friendly install docs; the installer supports an existing Mealie.
- Docs for adding the ZimaOS community store via `/store.json`.

### Fixed
- Store build failing when the commit subject contains a colon.

### Removed
- Personal details from public docs.

## [0.2] - 2026-11-08

### Added
- First public release: setup wizard, headless Mealie, ZimaOS community store and SSH installer.

[Unreleased]: https://github.com/thomasjvalenzuela/tableplan/compare/2bb542f...HEAD
[0.4]: https://github.com/thomasjvalenzuela/tableplan/compare/560cb04...2bb542f
[0.3]: https://github.com/thomasjvalenzuela/tableplan/compare/8b622bf...560cb04
[0.2]: https://github.com/thomasjvalenzuela/tableplan/commit/8b622bf
