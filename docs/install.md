# Install, update, back up and remove

TablePlan is one container with one data folder. It runs anywhere Docker runs, on `amd64` and `arm64` (Raspberry Pi 4/5 included).

- [Requirements](#requirements)
- [ZimaOS App Store](#zimaos-app-store)
- [One-line installer (any Linux server)](#one-line-installer-any-linux-server)
- [Docker Compose, Portainer, Dockge, Unraid](#docker-compose-portainer-dockge-unraid)
- [Plain docker run](#plain-docker-run)
- [First run](#first-run)
- [Updating](#updating)
- [Backups](#backups)
- [Restore](#restore)
- [Uninstall](#uninstall)

Deploying to the cloud instead? See [deploy-railway.md](deploy-railway.md).

---

## Requirements

- A server with **Docker** and Docker Compose: ZimaOS, CasaOS, Unraid, Ubuntu, Debian, a NAS, or a Raspberry Pi.
- A few hundred MB of free RAM, plus disk space for recipe photos.
- One free port. The default is **9930**.
- Optional: an OpenAI API key (screenshot import), and an email account, Telegram or ntfy for notifications. Both can be added later.

The image is `ghcr.io/thomasjvalenzuela/tableplan:latest`. Inside the container, TablePlan listens on port **8080** (or `PORT` if set) and keeps its data in **`/data`**. It runs as an unprivileged user (uid 1000); on start, the container makes `/data` owned by that user, including data folders created by older versions.

---

## ZimaOS App Store

1. Open **App Store**, click **Community store** (top right), then **Add**.
2. Paste this address and confirm:
   ```
   https://thomasjvalenzuela.github.io/tableplan/store.json
   ```
3. Switch to the **TablePlan** store, click **TablePlan**, then **Install**.
4. Wait for the first download. When the tile shows **Running**, click it.

Data is stored in `/DATA/AppData/tableplan/data`. To use another disk, change the volume path before installing.

---

## One-line installer (any Linux server)

For CasaOS, Ubuntu, Debian, Raspberry Pi OS and similar. Connect with SSH and run:

```bash
curl -fsSL https://thomasjvalenzuela.github.io/tableplan/install.sh | sudo bash
```

Prefer to read it first?

```bash
curl -fsSLO https://thomasjvalenzuela.github.io/tableplan/install.sh
less install.sh
sudo bash install.sh
```

The installer:

- checks that Docker and Docker Compose are installed and running, that the port is free and that no container named `tableplan` exists
- picks an install folder: `/media/DATA/AppData/tableplan`, `/DATA/AppData/tableplan` or `/opt/tableplan`, whichever parent exists first
- writes a `docker-compose.yml` there, using your server's time zone
- installs a `tableplan` helper command, starts the container, waits until it's healthy, and prints the address to open (for example `http://192.168.1.20:9930`)

Options, set before `bash`:

| Variable | Default | Meaning |
|---|---|---|
| `TABLEPLAN_PORT` | `9930` | Port on the server |
| `TABLEPLAN_DIR` | see above | Install folder |
| `TABLEPLAN_IMAGE` | `ghcr.io/thomasjvalenzuela/tableplan:latest` | Image to run |

```bash
curl -fsSL https://thomasjvalenzuela.github.io/tableplan/install.sh | sudo TABLEPLAN_PORT=8930 TABLEPLAN_DIR=/srv/tableplan bash
```

The helper command:

```bash
sudo tableplan status      # container status
sudo tableplan update      # pull the latest image and restart
sudo tableplan logs        # follow the log
sudo tableplan restart
sudo tableplan backup      # write tableplan-backup-DATE.tgz next to the install folder
sudo tableplan uninstall   # remove the container, keep your data
```

Running the install command again also updates TablePlan. It rewrites `docker-compose.yml` but keeps your data.

---

## Docker Compose, Portainer, Dockge, Unraid

```bash
mkdir tableplan && cd tableplan
curl -fsSLO https://thomasjvalenzuela.github.io/tableplan/docker-compose.yml
nano docker-compose.yml   # optional: set TZ, change the port
docker compose up -d
```

The file ([`install/docker-compose.yml`](../install/docker-compose.yml)):

```yaml
name: tableplan
services:
  tableplan:
    container_name: tableplan
    image: ghcr.io/thomasjvalenzuela/tableplan:latest
    restart: unless-stopped
    ports:
      - "9930:8080"                 # change the left number to use another port
    environment:
      TZ: America/Chicago           # your time zone; used for use-by dates
      TABLEPLAN_INSTALL: manual
    volumes:
      - ./data:/data
    security_opt: ["no-new-privileges:true"]
```

- **Portainer:** Stacks → **Add stack**, paste the file.
- **Dockge / Unraid (Compose Manager):** create a stack with the same contents.

Set `TZ` to your time zone (for example `America/New_York`) so use-by dates, the daily reminder and automatic planning happen at the right local time. Other options are in [configuration.md](configuration.md).

---

## Plain docker run

```bash
docker run -d --name tableplan --restart unless-stopped \
  -p 9930:8080 -e TZ=America/Chicago -e TABLEPLAN_INSTALL=manual \
  -v /srv/tableplan/data:/data \
  ghcr.io/thomasjvalenzuela/tableplan:latest
```

---

## First run

Open `http://YOUR-SERVER-IP:9930`. A short setup wizard starts. You can **Skip** any step and finish it later in **Settings**.

| Screen | What it does |
|---|---|
| **Household** | A name, how many people you cook for, and whether recipes scale to fit. |
| **Import from screenshots** | Your OpenAI API key and model. The key is tested before it's saved. |
| **Notifications** | Telegram, ntfy or email. Each sends a test message. |
| **Lock it** | An optional household password. Use one if anyone outside your home can reach the server. |

Then add TablePlan to your phone's Home Screen:

- **iPhone (Safari):** Share → **Add to Home Screen**.
- **Android (Chrome):** **⋮ → Add to Home screen** (or **Install app** on HTTPS).

Run the wizard again any time from **Settings → Advanced → Run setup wizard again**.

---

## Updating

TablePlan checks for new versions about every 10 minutes. When one is out:

- a blue **TablePlan x.y.z is available** banner appears at the top of every tab (tap **How to update**, or **×** to hide it for a day)
- the Settings gear shows a dot, and Settings shows **Update available**
- if notifications are set up, you get one message per new version, with the update command for your install method

| Installed with | How to update |
|---|---|
| ZimaOS App Store | App Store → **My Apps** → TablePlan → **Update**. Refresh the page if the button doesn't show yet. |
| One-line installer | `sudo tableplan update`, or run the install command again |
| Docker Compose | In the TablePlan folder: `docker compose pull && docker compose up -d` |
| Portainer | Stacks → tableplan → **Update the stack** with **Re-pull image** on |
| `docker run` | `docker pull ghcr.io/thomasjvalenzuela/tableplan:latest`, then remove and re-create the container with the same options |

Your data is kept. After an update, a **What's new** sheet appears once.

The in-app **How to update** sheet shows the ZimaOS steps. For other installs, use the table above.

---

## Backups

Everything lives in the data folder (`/data` in the container):

| Path | What it is |
|---|---|
| `tableplan.db` | SQLite database: recipes, meal plans, shopping lists, pantry, shelf-life rules, settings, saved credentials, AI usage log |
| `tableplan.db-wal`, `tableplan.db-shm` | SQLite write-ahead log files. Back them up together with `tableplan.db`. |
| `images/recipes/<id>/original.*` | Recipe photos |
| `images/ing-*.*` | Cached ingredient photos |
| `foodkeeper.json` | Only if you placed it there for an offline USDA sync |

Where the folder is on the server:

| Install | Data folder |
|---|---|
| ZimaOS App Store | `/DATA/AppData/tableplan/data` |
| One-line installer | `<install folder>/data`, for example `/DATA/AppData/tableplan/data` |
| Docker Compose | `./data` next to `docker-compose.yml` |

**Stop TablePlan before copying the folder**, so the database is consistent.

```bash
# One-line installer (stops, archives data/ and docker-compose.yml, starts again)
sudo tableplan backup

# Docker Compose (run in the TablePlan folder)
docker compose stop && tar czf tableplan-backup-$(date +%F).tgz data && docker compose start

# ZimaOS (stop the app in the dashboard first, or:)
sudo docker stop tableplan
sudo tar czf ~/tableplan-backup-$(date +%F).tgz -C /DATA/AppData/tableplan data
sudo docker start tableplan
```

The backup contains your saved credentials (OpenAI key, email password, bot tokens). Store it somewhere private.

---

## Restore

1. Stop TablePlan (`sudo docker stop tableplan`, `docker compose stop`, or stop the app in ZimaOS).
2. Move the current data folder aside, for example `mv data data.old`.
3. Unpack the backup so the folder is back in the same place:
   ```bash
   tar xzf tableplan-backup-2026-11-08.tgz            # Compose / installer: run in the install folder
   sudo tar xzf tableplan-backup-2026-11-08.tgz -C /DATA/AppData/tableplan   # ZimaOS
   ```
4. Start TablePlan again. The container fixes the folder's ownership on start, so restoring as root is fine.

To move to a new server, install TablePlan there, stop it, restore the data folder as above, and start it.

---

## Uninstall

| Installed with | Remove the app | Remove the data too |
|---|---|---|
| ZimaOS App Store | Right-click the TablePlan tile (or open its settings) → **Uninstall** | Delete `/DATA/AppData/tableplan` |
| One-line installer | `sudo tableplan uninstall` | Delete the install folder, for example `sudo rm -rf /DATA/AppData/tableplan` |
| Docker Compose | `docker compose down` | Delete the TablePlan folder |
| `docker run` | `docker rm -f tableplan` | Delete the folder you mounted at `/data` |

Make a backup first if you might want your recipes later.
