<p align="center"><img src="app/static/icon.svg" width="88" alt="TablePlan"></p>
<h1 align="center">TablePlan</h1>
<p align="center"><b>Recipes, auto meal plans, a smart pantry and grocery lists for your household, self-hosted.</b><br>
Runs on ZimaOS, CasaOS, Unraid, Portainer or any Linux server with Docker. One app, one container.</p>

<p align="center">
<a href="#-install-in-3-steps">Install</a> ·
<a href="#step-2-run-the-setup-wizard">Setup wizard</a> ·
<a href="#coming-from-mealie">Coming from Mealie?</a> ·
<a href="#updating">Updating</a> ·
<a href="#https-remove-chromes-not-secure-warning">HTTPS</a> ·
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

> 💡 **TablePlan is a single app.** Recipes, photos, meal plans, shopping lists and your pantry are all stored by TablePlan itself, in one container with one data folder. There's no separate recipe server, database or extra account to set up.

### ✨ New in v0.4

- **No more Mealie:** one app, one container; link import uses TablePlan's own recipe reader with AI fallback; screenshot import is a single AI call.

### New in v0.3

- **Recipes tab** with search and favorites.
- **Edit recipes in TablePlan**, or create one from scratch with **Type it**. Plain-text ingredients scale automatically too.
- **Two recipe styles:** *Classic* or *Step-by-step*, tuned to your stove (gas, electric or induction) and oven (conventional or convection).
- **Cook mode** with built-in timers.
- **Import progress** with a time estimate.
- **Pantry barcode scanning** (via Open Food Facts) and a weekly pantry check-in reminder.
- **Confirm what you have** before a shopping list is built, so you don't buy what's already in the pantry.
- **AI spending tracker** with budget alerts. Add an optional OpenAI *admin* key to see exact costs.
- **Ingredient and recipe photos.** Tap **Try another** or upload your own.
- **What's new** popup after each update, **light/dark mode**, and a desktop sidebar showing your version and a GitHub link.

---

## 🚀 Install in 3 steps

### Before you start

You need:

- A home server with **Docker**, such as ZimaOS, CasaOS, Unraid, or Ubuntu or Debian. Raspberry Pi 4/5 and other ARM boards work too.
- A few hundred MB of free RAM, plus some disk space for recipe photos.
- One free port: **9930**. Most servers have it free.

Optional, and both can be set up later:

- An **OpenAI API key** to import recipes from screenshots or photos. It costs a few cents per recipe.
- An **email account** to email yourself shopping lists. Gmail works with an App Password.

### Step 1: Install

Pick **one** of these:

<details open>
<summary><b>🟠 ZimaOS: install from the App Store (easiest)</b></summary>

1. Open **App Store**, click **Community store** (top right), then **Add**.
2. Paste this address and confirm:
   ```
   https://thomasjvalenzuela.github.io/tableplan/store.json
   ```
3. Switch to the **TablePlan** store, click **TablePlan**, then **Install**.
4. Wait a minute or two for the first download. When the TablePlan tile shows **Running**, click it.

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

### Step 2: Run the setup wizard

Open **`http://YOUR-SERVER-IP:9930`** in your browser. A short wizard appears. You can **skip** any step and finish it later in **Settings**.

| Screen | What to do |
|---|---|
| **Household** | Enter a name and how many people you cook for. |
| **Import from screenshots** | Paste an OpenAI key from [platform.openai.com/api-keys](https://platform.openai.com/api-keys) and add a few dollars of credit there. TablePlan tests the key before saving. You can also **Skip**. |
| **Notifications** | Get lists, plans and use-soon alerts by Telegram, ntfy or email. For email, **Gmail** needs an [App Password](https://myaccount.google.com/apppasswords). A test message is sent to confirm it works. |
| **Lock it** | Optional household password. Use one if anyone outside your home can reach the server. |

### Step 3: Put it on your phone

- **iPhone (Safari):** open `http://YOUR-SERVER-IP:9930`, tap **Share**, then **Add to Home Screen**.
- **Android (Chrome):** open it, tap **⋮**, then **Add to Home screen**.

That's it. Tap **+** on the Home screen to add your first recipe.

## Coming from Mealie?

You can bring everything over in one go:

1. In TablePlan, open **Settings → Advanced → Import from Mealie**.
2. Enter your Mealie address (for example `http://192.168.1.50:9925`) and an API token. Create one in Mealie under **Profile → API Tokens**.
3. Tap **Import**. TablePlan copies your recipes, photos, favorites, meal plans and shopping lists.

It's safe to run more than once, and you can uninstall Mealie afterwards.

> **Used TablePlan v0.3 or earlier?** Those versions ran a bundled Mealie. The one-command installer leaves it running after the upgrade so you can import from it (it prints the address), and `sudo tableplan update` removes it once you're done. If your update already removed it (for example on ZimaOS), its files are still on disk. Start it again temporarily, import, then remove it:
> ```bash
> sudo docker run -d --name old-mealie -p 9925:9000 -v /DATA/AppData/tableplan/mealie:/app/data ghcr.io/mealie-recipes/mealie:v3.30.0
> # import from http://YOUR-SERVER-IP:9925, then:
> sudo docker rm -f old-mealie
> ```
> Use the `mealie` folder from your install (installer: next to `data/`; Compose: `./mealie`).

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

All your data (recipes, photos, plans, lists, pantry and settings) lives in one folder next to the install: `data/`.

```bash
sudo tableplan backup       # installer users: makes a .tgz backup
sudo tableplan uninstall    # removes the app, keeps your data
```
Compose users: `docker compose down` removes the app. Delete the folder too if you want to remove the data.

## HTTPS: remove Chrome's "Not secure" warning

Chrome labels any `http://` address as *Not secure*, including apps on your own Wi-Fi. TablePlan works fine without HTTPS at home. Adding it encrypts traffic, removes the warning, and lets your phone paste links straight from the clipboard. Pick one way:

<details open>
<summary><b>Option 1: Tailscale (easiest, and also gives you access away from home)</b></summary>

1. Install **Tailscale** on the server (it's in the ZimaOS App Store) and on your phones, then sign in to the same account on each.
2. In the [Tailscale admin console → DNS](https://login.tailscale.com/admin/dns), turn on **MagicDNS** and **HTTPS Certificates**.
3. On the server, run:
   ```bash
   # ZimaOS / CasaOS (Tailscale runs as a container). Find its name with: docker ps | grep -i tailscale
   sudo docker exec tailscale tailscale serve --bg 9930
   # Tailscale installed directly on Linux: drop "docker exec tailscale" (e.g. sudo tailscale serve --bg 9930)
   ```
4. Open **`https://<server-name>.<your-tailnet>.ts.net`**, which now shows a padlock 🔒. The exact name is in the Tailscale admin console.

Phones need the Tailscale app running to reach this address.
</details>

<details>
<summary><b>Option 2: your own domain with a reverse proxy (no app needed on phones)</b></summary>

This works with Nginx Proxy Manager, Caddy or Traefik, and a domain you own. Nothing gets opened to the internet.

1. **DNS:** create a `tableplan.example.com` A record pointing to your server's **local** IP. On Cloudflare, set it to *DNS only* (grey cloud).
2. **Proxy host:** send `tableplan.example.com` to `http://SERVER-IP:9930`.
3. **Certificates:** request a Let's Encrypt certificate using the **DNS challenge**. For Cloudflare, use an API token with *Zone → DNS → Edit* permission. The DNS challenge works for local-only addresses, so you don't need to open ports on your router. Turn on *Force SSL*.

Your proxy needs ports 80/443 on the server. On ZimaOS the dashboard uses port 80, so either move the dashboard to another port in ZimaOS settings, or run the proxy on another machine.
</details>

> 📷 **Barcode scanning with the live camera needs HTTPS.** Browsers only allow camera access on secure addresses, so set up Option 1 or 2. On plain `http://`, the pantry scanner falls back to taking a photo of the barcode or typing the number.

### Using it away from home

**Tailscale** (Option 1 above) is the simplest and safest way. If you expose TablePlan through a public domain instead, set `TABLEPLAN_PUBLIC=1` on the TablePlan container. Sign-in is then always required, and until you set a household password, you need a one-time setup code printed in the TablePlan log (ZimaOS → TablePlan → Logs, or `docker logs tableplan`). Never port-forward 9930 straight to the internet.

## Troubleshooting

| Problem | Fix |
|---|---|
| ZimaOS says "Failed to add community store" | Use the full address ending in **`/store.json`**, with no spaces. |
| OpenAI test failed | The key is wrong or has no credit. Check [billing](https://platform.openai.com/settings/organization/billing). |
| Screenshot import doesn't work | Check your OpenAI key and credit in **Settings → AI recipe import**. |
| Import from Mealie fails | Use your server's network IP in the Mealie address, not `localhost` (TablePlan runs in its own container), and a fresh API token from Mealie → Profile → API Tokens. |
| Live barcode scanning doesn't open the camera | The camera needs HTTPS. See [HTTPS](#https-remove-chromes-not-secure-warning), or take a photo of the barcode or type the number instead. |
| Email test failed | Gmail, Yahoo and iCloud need an **app password**, not your normal password. |
| Use-by dates off by a day | Set `TZ` to your time zone and restart TablePlan. |
| Chrome says "Not secure" | Normal for `http://` on a home network. See [HTTPS](#https-remove-chromes-not-secure-warning) to add a padlock. |
| Port already in use | Installer: add `TABLEPLAN_PORT=8930` before `bash`. Compose: change the left-hand port number. |
| Something else | Run `docker logs tableplan`, then [open an issue](https://github.com/thomasjvalenzuela/tableplan/issues) with what you see. |

More detail is in the [full illustrated guide](https://thomasjvalenzuela.github.io/tableplan/setup/).

## FAQ

**Is my data private?**
Yes. Everything stays on your server. The only things that go out are the ones you turn on: AI imports go to OpenAI, and emails go through your mail provider. TablePlan also does a one-time download of the public USDA shelf-life database and a version check.

**Where do use-by dates come from?**
From the USDA FoodKeeper database, using the cautious end of each range. A date you type from the package always wins, and you can edit any rule in Settings.

**Does it cost anything?**
TablePlan is free and open source. AI imports use your own OpenAI account, at a few cents each.

## Contributing

Bug reports and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to develop locally, how releases work, and how to publish your own fork.

## License & credits

- **TablePlan:** [AGPL-3.0](LICENSE).
- **[Mealie](https://github.com/mealie-recipes/mealie)** (AGPL-3.0) inspired TablePlan's recipe, meal-plan and shopping-list data format. Earlier versions used Mealie as their recipe engine.
- **[USDA FSIS FoodKeeper](https://catalog.data.gov/dataset/fsis-foodkeeper-data)** (public domain): shelf-life data.
- **[Open Food Facts](https://world.openfoodfacts.org)** ([ODbL](https://opendatacommons.org/licenses/odbl/1-0/)): barcode product data.
- **[zxing-wasm](https://github.com/Sec-ant/zxing-wasm)** (MIT): barcode decoding in the browser.
- **[TheMealDB](https://www.themealdb.com)**: ingredient images.
- **[Openverse](https://openverse.org)**: openly licensed recipe photos.
