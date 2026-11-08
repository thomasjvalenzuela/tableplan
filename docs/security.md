# Security and privacy

How TablePlan protects your household's data, and what it sends outside your server.

- [What's stored where](#whats-stored-where)
- [Signing in](#signing-in)
- [Public mode and the setup code](#public-mode-and-the-setup-code)
- [Protections built in](#protections-built-in)
- [Exposing TablePlan to the internet safely](#exposing-tableplan-to-the-internet-safely)
- [Outbound connections](#outbound-connections)
- [Reporting a vulnerability](#reporting-a-vulnerability)

---

## What's stored where

| Data | Where |
|---|---|
| Recipes, meal plans, shopping lists, pantry, shelf-life rules, settings | `tableplan.db` (SQLite) in the data folder |
| Recipe and ingredient photos | `images/` in the data folder |
| OpenAI keys, SMTP password, Telegram and ntfy tokens | `tableplan.db`, `settings` table, in plain text |
| Household password | `tableplan.db`, as a salted PBKDF2-SHA256 hash (200,000 iterations) |
| Session signing secret | `tableplan.db`, random, created on first start |
| In your browser | A sign-in cookie, and a few preferences in local storage (no credentials) |

Nothing is stored outside the data folder, and TablePlan has no telemetry. Protect the data folder and its backups like you would a password manager export: anyone who can read it can read your API keys.

**Secrets are never sent to the browser.** The API reports only whether a key or password is set ("saved ✓"), never its value. Forms for keys and passwords are write-only.

---

## Signing in

| Situation | Who can open TablePlan |
|---|---|
| No password (default) | Anyone who can reach the server, for example anyone on your Wi-Fi. |
| Household password set | Only devices that signed in with the password. |
| Public mode | Always requires sign-in. See below. |

- Set or change the password in the wizard's **Lock it** step or **Settings → Setup → Password**. It must be at least 4 characters; use a long one if TablePlan is reachable from outside your home.
- Signing in sets an `HttpOnly`, `SameSite=Lax` cookie that lasts 180 days, marked `Secure` on HTTPS.
- After 8 wrong attempts from one address within 10 minutes, that address is blocked until the 10 minutes pass. After 60 wrong attempts from all addresses together, sign-in pauses for everyone, which slows down guessing from many addresses.
- Behind a reverse proxy, set `TABLEPLAN_TRUST_PROXY=1` so the limit applies to the real client address (see [HTTPS and remote access](https-and-remote-access.md#reverse-proxy-notes)).
- **Settings → Advanced → Sign out on this device** ends the session on that device.

**Forgot the password?** Remove it from the database, then restart:

```bash
docker exec tableplan python -c "import sqlite3;c=sqlite3.connect('/data/tableplan.db');c.execute(\"DELETE FROM settings WHERE key='cfg.app_password_hash'\");c.commit()"
docker restart tableplan
```

---

## Public mode and the setup code

Public mode is for servers reachable from the internet. It's on when `TABLEPLAN_PUBLIC=1` is set, and automatically on Railway.

- Sign-in is always required, even before setup.
- Until a household password exists, the only way in is a **one-time setup code**: 16 random letters and digits (80 bits) printed in the server log at startup (`PUBLIC MODE · one-time setup code: …`). A new code is generated on every restart.
- Once you set a password, the code stops working.
- The password can't be removed while public mode is on.
- Expensive work is rate-limited per client: link and file imports, AI calls, and outbound fetches.
- Notification servers you enter (ntfy, SMTP) must be on the public internet, so the server can't be pointed at your private network.

This prevents a stranger from finding a fresh install and running its setup wizard before you do.

---

## Protections built in

| Protection | Details |
|---|---|
| **CSRF** | Every request that changes something (`POST`, `PUT`, `PATCH`, `DELETE`) must carry the header `X-TablePlan: 1`. Browsers can't add custom headers to cross-site requests without CORS, and TablePlan allows no CORS, so other websites can't act on your behalf. |
| **Content Security Policy** | Pages may only load scripts, styles and connections from TablePlan itself. No third-party scripts or CDNs. Frames are denied. |
| **Other headers** | `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, a `Permissions-Policy` that allows only the camera (for barcodes), and HSTS on HTTPS. |
| **Server-side request checks** | Links, photos, Google Docs and video short links are fetched only over `http`/`https`, only from public internet addresses. Every redirect is re-checked, the address actually connected to is checked (so DNS tricks can't reach your network), credentials are never forwarded on a redirect, and downloads are capped in size and time. Video links go only to the dedicated Instagram, TikTok, YouTube, Facebook and Pinterest readers. |
| **Shared links** | Links opened with `/?url=…` are only filled in; you have to tap **Import**. |
| **Credential reuse** | A saved SMTP password or ntfy token is only reused for the same server (and SMTP user), so changing the server can't send it somewhere new. |
| **Upload limits** | Requests up to 40 MB; images up to 8 MB; screenshot imports up to 8 files and 25 MB in total. Uploaded and fetched images are checked by their content and must be real JPEG, PNG, WebP or GIF files. |
| **Input checks** | Settings are validated by type and range, and date ranges are limited to 400 days. |
| **Container** | One Python process running as an unprivileged user (uid 1000). On start, the entrypoint makes `/data` owned by that user, then drops root. The install files also set `no-new-privileges`. |

Addresses set by you as the operator are exempt from the private-address check, because they're often on your home network: the [Import from Mealie](importing-from-mealie.md) address, `TELEGRAM_API_URL` (when changed), `FOODKEEPER_URL`, `TABLEPLAN_UPDATE_FEED`, and, outside public mode, a self-hosted ntfy server.

---

## Exposing TablePlan to the internet safely

1. **Prefer Tailscale.** It gives access away from home with nothing exposed. See [HTTPS and remote access](https-and-remote-access.md).
2. **Never port-forward 9930** on your router. That's unencrypted HTTP.
3. If you use a public domain, put TablePlan behind **HTTPS** (a reverse proxy or tunnel), set **`TABLEPLAN_PUBLIC=1`**, and set a **strong password** right away.
4. Make sure your proxy sets `X-Forwarded-For` and `X-Forwarded-Proto`, and doesn't pass through those headers from clients. TablePlan uses them for the sign-in rate limit and the `Secure` cookie.
5. Keep TablePlan updated. The in-app banner tells you when a new version is out.

---

## Outbound connections

TablePlan only connects out for features you use. Your browser connects only to TablePlan.

| Destination | When | What's sent |
|---|---|---|
| **OpenAI** (`api.openai.com`) | AI features, only with a key: screenshot/PDF import, messy page or text import, video transcription, Step-by-step, testing a key, exact costs (Admin key) | Recipe text, page text, images, PDFs or video audio; your API key |
| **Telegram** (`api.telegram.org`, or `TELEGRAM_API_URL`) | Telegram set up | Lists, plans, alerts; your bot token. Outbound only, no webhook. |
| **ntfy** (`ntfy.sh` or your server) | ntfy set up | Lists, plans, alerts as notification text |
| **Your SMTP server** | Email set up | Emails with lists, plans and CSV/ICS attachments |
| **USDA FoodKeeper** (`www.fsis.usda.gov`, or `FOODKEEPER_URL`) | First start, and **Sync now** | Nothing but the download request |
| **Open Food Facts** (`world.openfoodfacts.org`) | Looking up a barcode not seen before | The barcode number |
| **TheMealDB** (`www.themealdb.com`) | First time an ingredient photo is shown | The ingredient name (in the image URL) |
| **Openverse** (`api.openverse.org`) and the photo hosts it returns | **Try another** on a photo, or no TheMealDB photo for an ingredient | The recipe or ingredient name |
| **GitHub Pages** (`thomasjvalenzuela.github.io`, or `TABLEPLAN_UPDATE_FEED`) | About every 10 minutes | A request for `version.json`, with a `TablePlan/<version>` user agent |
| **Recipe websites** | Importing a link; **Try another** on a recipe photo with a source page | A normal page request |
| **Video sites** (Instagram, TikTok, YouTube, Facebook, Pinterest, Threads) | Importing a video link | A page request; the audio is downloaded only if the recipe is spoken and AI is on (not for Threads) |
| **Google Docs** (`docs.google.com`) | Importing a Google Doc link | A request for the doc's text export |
| **Your Mealie** | **Import from Mealie** | Your Mealie API token |

To stop the version check, set `TABLEPLAN_UPDATE_FEED` to an address that doesn't resolve. If USDA can't be reached, TablePlan uses its starter shelf-life table; you can also place `foodkeeper.json` in the data folder and sync offline.

---

## Reporting a vulnerability

Report security issues privately through GitHub: the repository's **Security → Report a vulnerability**. Please don't open a public issue.
