# Deploy on Railway (Beta)

> **Beta.** Running TablePlan on [Railway](https://railway.com) works with the standard Docker image, but it's newer and less tested than a home server install. TablePlan is designed for one household; run a single instance.

On Railway, TablePlan is reachable from the internet, so it runs in **public mode**: sign-in is always required, and the first sign-in uses a one-time setup code from the logs.

- [What you need](#what-you-need)
- [1. Create the service](#1-create-the-service)
- [2. Add a volume at /data](#2-add-a-volume-at-data)
- [3. Set variables](#3-set-variables)
- [4. Add a domain](#4-add-a-domain)
- [5. First sign-in with the setup code](#5-first-sign-in-with-the-setup-code)
- [Updating](#updating)
- [Backups](#backups)
- [Limits and tips](#limits-and-tips)

---

## What you need

- A Railway account and project.
- Optional: a domain you own for a custom address.

---

## 1. Create the service

Pick one:

| Source | How |
|---|---|
| **Docker image** (recommended) | In your project, **+ New → Docker Image**, and enter `ghcr.io/thomasjvalenzuela/tableplan:latest`. |
| **GitHub repo** | **+ New → GitHub Repo**, and choose your fork of TablePlan. Railway builds the `Dockerfile` in the repo root. |

---

## 2. Add a volume at /data

TablePlan keeps its database and photos in `/data`. **Without a volume, everything is lost on every redeploy.**

1. Right-click the service (or use the command palette) → **Attach volume**.
2. Set the **mount path** to `/data`.

---

## 3. Set variables

In the service's **Variables** tab:

| Variable | Value | Why |
|---|---|---|
| `TZ` | your time zone, e.g. `America/New_York` | Use-by dates, the daily reminder and automatic planning use local time. |
| `TABLEPLAN_INSTALL` | `manual` | Optional. Makes update notifications give non-ZimaOS instructions. |

You don't need to set these:

- **`PORT`**: Railway sets it, and TablePlan listens on it.
- **Public mode**: TablePlan detects Railway (the `RAILWAY_ENVIRONMENT` variable) and turns on public mode by itself, along with trusting Railway's proxy headers (`TABLEPLAN_TRUST_PROXY`). Setting `TABLEPLAN_PUBLIC=1` as well does no harm. Don't set it to `0` on Railway.
- **`DATA_DIR`**: already `/data` in the image.

If you deploy from the GitHub repo, the included [`railway.toml`](../railway.toml) already sets the Dockerfile build, a `/health` healthcheck, restart on failure and one replica. For an image deploy, set **Settings → Deploy → Healthcheck Path** to `/health` yourself.

API keys and notification settings are entered in the app's setup wizard, not here. (You can pre-fill them with variables; see [configuration.md](configuration.md#optional-credential-defaults).)

---

## 4. Add a domain

In the service's **Settings → Networking**:

- **Generate Domain** gives you a `*.up.railway.app` address with HTTPS.
- **Custom Domain**: enter e.g. `tableplan.example.com`, then add the CNAME record Railway shows at your DNS provider. Railway issues the certificate.

Railway's proxy handles HTTPS. TablePlan sees the forwarded headers, marks its sign-in cookie `Secure` and sends HSTS.

Because Railway gives you HTTPS, live barcode scanning, Android install and the Share menu all work. See [HTTPS and remote access](https-and-remote-access.md#why-https-matters).

---

## 5. First sign-in with the setup code

1. Open the service's **Deployments** tab → the latest deployment → **Deploy Logs**.
2. Find the line:
   ```
   [tableplan] PUBLIC MODE · one-time setup code: ABCD2EFGH3IJKL4M
   ```
   (Yours is different: 16 letters and digits.)
3. Open your TablePlan address, enter the code on the sign-in screen, and run the setup wizard.
4. On the **Lock it** step, **set a household password**. From then on, the password is required and the setup code stops working.

Until a password is set, a new code is generated on every restart or redeploy, so check the latest logs. Don't skip the password step on a public server.

---

## Updating

The `:latest` image is rebuilt on every release.

- **Automatic:** in the service's **Settings → Source**, choose **Configure Auto Updates**, and pick a maintenance window. Railway redeploys when a new image is pushed to the tag you use.
- **Manual:** redeploy the service from the **Deployments** tab.
- **GitHub repo source:** Railway rebuilds when you push to the connected branch.

TablePlan shows an **Update available** banner when a new version is out. Its **How to update** sheet describes ZimaOS; on Railway, use the steps above.

---

## Backups

Your data is the `/data` volume: `tableplan.db` (with its `-wal` and `-shm` files) and the `images/` folder. See [install.md](install.md#backups) for details.

Use Railway's volume backups: open the service's **Backups** tab, choose a schedule (daily, weekly, monthly) or make a manual backup. To restore, pick a backup, click **Restore**, review the staged change, and **Deploy**.

---

## Limits and tips

- **One replica only.** TablePlan uses SQLite on a volume. Don't scale the service to more than one instance.
- **Outbound access.** TablePlan needs outbound internet for AI, notifications, USDA data, barcode lookups and photos. Railway allows this by default. See [security.md](security.md#outbound-connections).
- **Video import from the cloud.** Some video sites block requests from cloud server addresses more often than from home connections. If a video link fails, use screenshots.
- **Costs.** You pay Railway for the service and volume, and OpenAI for AI use. AI is optional.
- **Coming from Mealie.** [Import from Mealie](importing-from-mealie.md) works if your Mealie is reachable from Railway (for example, at a public HTTPS address). A Mealie that's only on your home network can't be reached from the cloud.
