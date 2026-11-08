<p align="center"><img src="app/static/icon.svg" width="88" alt="TablePlan"></p>
<h1 align="center">TablePlan</h1>
<p align="center"><b>Recipes, auto meal plans, a smart pantry and grocery lists for your household, self-hosted.</b><br>
Runs on ZimaOS, CasaOS, Unraid, Portainer or any Linux server with Docker. Built on <a href="https://github.com/mealie-recipes/mealie">Mealie</a>.</p>

<p align="center">
<a href="#-install-in-3-steps">Install</a> ·
<a href="#step-2-run-the-setup-wizard">Setup wizard</a> ·
<a href="#updating">Updating</a> ·
<a href="#troubleshooting">Troubleshooting</a> ·
<a href="https://thomasjvalenzuela.github.io/tableplan/setup/">Full guide</a>
</p>

---

## What it does

- 📸 **Save recipes from anywhere.** Paste a link, or snap a screenshot or cookbook page. AI reads it, and TikTok and YouTube links work too.
- 🗓️ **Auto meal plans.** Fill a week or a month in one tap:
  - nothing repeats too often
  - favorites come up more
  - food that's about to expire gets used first
- 👨‍👩‍👧 **Right-sized portions.** Tell it how many people you cook for, and every planned recipe and shopping list scales to match.
- 🥛 **Smart pantry.** Tick items off the shopping list and they get real use-by dates.
  - Use half the cream and the rest switches to its "after opening" date.
  - Freeze something and it switches to the freezer date.
- 🛒 **Share anything.** Email, print, or export lists and plans. Meal plans export to your calendar (.ics).
- 📱 **Feels like an app.** It looks like Apple's Home app, and you can add it to your phone's Home Screen.

---

## 🚀 Install in 3 steps

### Before you start

You need:

- A home server with **Docker**, such as ZimaOS, CasaOS, Unraid, or Ubuntu or Debian. Raspberry Pi 4/5 and other ARM boards work too.
- About **1.5 GB of free RAM** and **2 GB of disk**.
- Two free ports: **9930** for TablePlan and **9925** for Mealie. Most servers have these free.

Optional, and both can be set up later:

- An **OpenAI API key** to import recipes from screenshots or photos. It costs a few cents per recipe.
- An **email account** to email yourself shopping lists. Gmail works with an App Password.

### Step 1: Install

**First question: do you already use [Mealie](https://mealie.io)?**

| | **No, I don't have Mealie** *(most people)* | **Yes, I already run Mealie** |
|---|---|---|
| What gets installed | TablePlan **plus** a fresh Mealie, set up for you | **Only** TablePlan, connected to your Mealie |
| Your recipes | Start fresh. Import them in TablePlan. | Your existing recipes, plans and lists show up right away |
| Setup wizard | Choose **Create account** | Choose **Sign in** and use your Mealie login |
| Go to | [**Path A ↓**](#path-a-i-dont-have-mealie) | [**Path B ↓**](#path-b-i-already-have-mealie) |

The rest of the process is the same either way.

---

#### Path A: I don't have Mealie

Pick **one** of these:

<details open>
<summary><b>🟠 ZimaOS: install from the App Store (easiest)</b></summary>

1. Open **App Store**, click **Community store** (top right), then **Add**.
2. Paste this address and confirm:
   ```
   https://thomasjvalenzuela.github.io/tableplan/store.json
   ```
3. Switch to the **TablePlan** store, click **TablePlan**, then **Install**.
4. Wait 3–5 minutes for the first download. When the TablePlan tile shows **Running**, click it.

ZimaOS will show an **Update** button whenever a new version comes out.
</details>

<details>
<summary><b>🐧 Any Linux server (CasaOS, Ubuntu, Debian, Raspberry Pi…): one command</b></summary>

1. Open a terminal on the server, or connect with SSH: `ssh your-user@your-server-ip`
2. Paste:
   ```bash
   curl -fsSL https://thomasjvalenzuela.github.io/tableplan/install.sh | sudo bash
   ```
3. When it finishes, it prints the address to open, like `http://192.168.1.20:9930`.

The installer checks everything first and won't touch your other apps. Run the same command again any time to update.
</details>

<details>
<summary><b>🐳 Docker Compose, Portainer, Dockge or Unraid</b></summary>

**Docker Compose:**
```bash
mkdir tableplan && cd tableplan
curl -fsSLO https://thomasjvalenzuela.github.io/tableplan/docker-compose.yml
docker compose up -d
```
**Portainer / Dockge:** create a new stack and paste the contents of [`docker-compose.yml`](install/docker-compose.yml).

Optional: edit `TZ` in the file to your time zone (for example `America/New_York`) so use-by dates are exact.
</details>

→ Then continue to [**Step 2**](#step-2-run-the-setup-wizard).

---

#### Path B: I already have Mealie

TablePlan works with **Mealie v3**. Version 3.30 or newer is recommended so AI import can be set up from TablePlan. You need your Mealie's address on your network, for example `http://192.168.1.50:9925`.

> ⚠️ Use your server's **network IP address**, not `localhost`. TablePlan runs in its own container, so `localhost` points at itself.

Pick **one** of these:

<details open>
<summary><b>🐧 Any Linux server, including ZimaOS over SSH: one command</b></summary>

Replace the address with your Mealie's:
```bash
curl -fsSL https://thomasjvalenzuela.github.io/tableplan/install.sh | sudo MEALIE_URL=http://192.168.1.50:9925 bash
```
This installs only TablePlan, connected to your Mealie.
</details>

<details>
<summary><b>🐳 Docker Compose / Portainer / ZimaOS "Install Custom App"</b></summary>

1. Download [`docker-compose.existing-mealie.yml`](install/docker-compose.existing-mealie.yml).
2. Change `MEALIE_URL` to your Mealie address, and `TZ` to your time zone.
3. Start it:
   - **Docker:** `docker compose -f docker-compose.existing-mealie.yml up -d`
   - **Portainer:** create a new stack and paste the file.
   - **ZimaOS:** App Store → My Apps → **Install Custom App** → **YAML**, paste the file, then **Install**.
</details>

> 💡 Don't use the ZimaOS App Store version if you already have Mealie. It installs a second, separate Mealie.

→ Then continue to [**Step 2**](#step-2-run-the-setup-wizard).

---

### Step 2: Run the setup wizard

Open **`http://YOUR-SERVER-IP:9930`** in your browser. A short wizard appears. You can **skip** any step and finish it later in **Settings**.

| Screen | What to do |
|---|---|
| **Household** | Enter a name and how many people you cook for. |
| **Recipe library** | **No Mealie before (Path A):** choose **Create account** and enter your name, email and a password with 8+ characters. This becomes your Mealie login, and it replaces Mealie's default `changeme@example.com` account so nobody else can use it.<br>**Existing Mealie (Path B):** choose **Sign in** with your Mealie email and password. Use an **admin** account if you want the AI step to work. TablePlan creates its own access token and doesn't store your password.<br>Prefer tokens? Choose **Use API token** and paste one from Mealie → Profile → API Tokens. |
| **Import from screenshots** | Paste an OpenAI key from [platform.openai.com/api-keys](https://platform.openai.com/api-keys) and add a few dollars of credit there. TablePlan tests the key before saving. You can also **Skip**. |
| **Email** | Pick your provider and enter your email and password. **Gmail** needs an [App Password](https://myaccount.google.com/apppasswords). A test email is sent to confirm it works. |
| **Lock it** | Optional household password. Use one if anyone outside your home can reach the server. |

### Step 3: Put it on your phone

- **iPhone (Safari):** open `http://YOUR-SERVER-IP:9930`, tap **Share**, then **Add to Home Screen**.
- **Android (Chrome):** open it, tap **⋮**, then **Add to Home screen**.

That's it. Tap **+** on the Home screen to add your first recipe.

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

## Backup & uninstall

All your data lives in two folders next to the install: `data/` (TablePlan) and `mealie/` (recipes, photos, plans and lists). Path B installs only have `data/`.

```bash
sudo tableplan backup       # installer users: makes a .tgz backup
sudo tableplan uninstall    # removes the app, keeps your data
```
Compose users: `docker compose down` removes the app. Delete the folder too if you want to remove the data.

## Using it away from home

Use a private network app like **[Tailscale](https://tailscale.com)**, and your phone reaches TablePlan anywhere as if you were home.

If you'd rather use a domain, put TablePlan behind a reverse proxy with HTTPS (Nginx Proxy Manager, Caddy or Traefik), and **set a household password** in Settings. Don't port-forward 9930 or 9925 straight to the internet.

## Troubleshooting

| Problem | Fix |
|---|---|
| ZimaOS says "Failed to add community store" | Use the full address ending in **`/store.json`**, with no spaces. |
| Wizard says "Can't reach Mealie yet" | Path A: Mealie is still starting, so wait about a minute and tap **Check again**. Path B: check `MEALIE_URL` and that Mealie is running. |
| Wizard says "This Mealie already has an account" | Your Mealie was already set up. Choose **Sign in** instead. |
| OpenAI test failed | The key is wrong or has no credit. Check [billing](https://platform.openai.com/settings/organization/billing). |
| Email test failed | Gmail, Yahoo and iCloud need an **app password**, not your normal password. |
| Use-by dates off by a day | Set `TZ` to your time zone and restart TablePlan. |
| Port already in use | Installer: add `TABLEPLAN_PORT=8930` (and `MEALIE_PORT=8925`) before `bash`. Compose: change the left-hand port number. |
| Something else | Run `docker logs tableplan`, then [open an issue](https://github.com/thomasjvalenzuela/tableplan/issues) with what you see. |

More detail is in the [full illustrated guide](https://thomasjvalenzuela.github.io/tableplan/setup/).

## FAQ

**Is my data private?**
Yes. Everything stays on your server. The only things that go out are the ones you turn on: AI imports go to OpenAI, and emails go through your mail provider. TablePlan also does a one-time download of the public USDA shelf-life database and a version check.

**Where do use-by dates come from?**
From the USDA FoodKeeper database, using the cautious end of each range. A date you type from the package always wins, and you can edit any rule in Settings.

**Does it cost anything?**
TablePlan and Mealie are free and open source. AI imports use your own OpenAI account, at a few cents each.

## Contributing

Bug reports and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to develop locally, how releases work, and how to publish your own fork.

## License & credits

- **TablePlan:** [AGPL-3.0](LICENSE).
- **[Mealie](https://github.com/mealie-recipes/mealie)** (AGPL-3.0) is the recipe engine. TablePlan talks to it over its API.
- Shelf-life data comes from **[USDA FSIS FoodKeeper](https://catalog.data.gov/dataset/fsis-foodkeeper-data)** (public domain).
