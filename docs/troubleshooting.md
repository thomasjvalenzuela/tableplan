# Troubleshooting

Start with the log. It usually says what went wrong:

| Install | Log |
|---|---|
| ZimaOS | Dashboard → TablePlan → **Logs** |
| One-line installer | `sudo tableplan logs` |
| Docker / Compose | `docker logs tableplan` |
| Railway | Service → **Deployments** → **Deploy Logs** |

- [Installing and updating](#installing-and-updating)
- [Signing in](#signing-in)
- [Importing recipes](#importing-recipes)
- [Pantry and barcodes](#pantry-and-barcodes)
- [Notifications](#notifications)
- [Phone and browser](#phone-and-browser)
- [Still stuck?](#still-stuck)

---

## Installing and updating

| Problem | Fix |
|---|---|
| ZimaOS: "Failed to add community store" | Use the full address ending in `/store.json`, with no spaces: `https://thomasjvalenzuela.github.io/tableplan/store.json` |
| ZimaOS doesn't show **Update** | Refresh the App Store page. ZimaOS checks the store periodically. |
| Installer: "Port 9930 is already in use" | Pick another port: `curl -fsSL https://thomasjvalenzuela.github.io/tableplan/install.sh \| sudo TABLEPLAN_PORT=8930 bash`. For Compose, change the left number in `ports`. |
| Installer: "A container named 'tableplan' already exists" | Remove it (`sudo docker rm -f tableplan`), or run `sudo tableplan uninstall` first. Your data folder is kept. |
| Installer: "Docker isn't installed" / "not running" | Install Docker from docs.docker.com, or start it (`sudo systemctl start docker`). |
| Page doesn't load after install | The first download takes a minute or two. Wait until the container is **Running** / **healthy**, then check the log. |
| "Update available" stays after updating | Make sure the new image was pulled (`docker compose pull`), then reload the page. |
| Log says "/data is not writable by uid 1000; running as root" | The data folder is on a share that doesn't allow changing ownership (for example some NAS or NFS mounts). TablePlan still runs. To fix it, make the folder writable by uid/gid 1000 on the host, or use a local folder. |

## Signing in

| Problem | Fix |
|---|---|
| Forgot the household password | `docker exec tableplan python -c "import sqlite3;c=sqlite3.connect('/data/tableplan.db');c.execute(\"DELETE FROM settings WHERE key='cfg.app_password_hash'\");c.commit()"`, then `docker restart tableplan`. |
| Asked for a "setup code" | Public mode is on and no password is set yet (always the case on Railway). Find `PUBLIC MODE · one-time setup code` in the log. It changes on each restart. Then set a password in the wizard. |
| "Wrong setup code" | Use the code from the **latest** start in the log. |
| "Too many tries" | Wait 10 minutes. |
| Signed out on one device only | Sign-ins are per device and last 180 days. Sign in again. |

## Importing recipes

| Problem | Fix |
|---|---|
| "This needs AI" / screenshot import doesn't work | Add your OpenAI key in **Settings → Setup → AI recipe import**. |
| OpenAI test failed when saving the key | The key is wrong, the model name is wrong, or the account has no credit. Check billing at platform.openai.com. |
| "That site blocks apps from reading its recipes" | The site needs a login or subscription. Take screenshots and use the **Screenshot** tab. |
| "Couldn't find a recipe on that page" | The page has no recipe data and AI isn't set up (or the page has too little text). Use screenshots, or paste the text. |
| "That link can't be opened" | Only public `https://` pages work. Links to your home network are blocked on purpose. |
| "This recipe looks incomplete, so it wasn't saved" | Part of the recipe is missing. Add the other screenshot (or the rest of the text) and try again. |
| Video: "can't be opened without logging in" | The post is private or the site is blocking. Screenshot the caption instead. |
| Video: "This video's recipe is spoken" | Add an OpenAI key so TablePlan can transcribe it. |
| Google Doc: "That Google Doc is private" | In Google Docs, **Share → General access → Anyone with the link**. Or copy the text into the **Paste** tab. |
| Paste: "Couldn't find ingredients and steps" | Add an *Ingredients* heading and an *Instructions* heading, or add an OpenAI key. |
| Ingredients don't scale | Lines need the amount first, like `2 cups flour`. Fix them with **Edit**. |
| Video: "Paste a link to a single video or post" | Channel, profile and playlist links don't work. Open the post and share or copy its own link. |
| Video: "That short link couldn't be opened" | Open the `pin.it` / `fb.watch` link in a browser and paste the full link it leads to. |
| Shared link opens TablePlan but nothing imports | That's expected: shared links are filled in for you to check. Tap **Import**. |
| Imports or AI refused after many tries (public mode) | Public servers limit imports and AI calls per hour. Wait and try again. |
| Import from Mealie fails | See [importing-from-mealie.md](importing-from-mealie.md#troubleshooting). |

## Pantry and barcodes

| Problem | Fix |
|---|---|
| Live barcode scanning doesn't open the camera | The camera needs HTTPS. See [HTTPS and remote access](https-and-remote-access.md). Meanwhile, take a photo of the barcode or type the number. |
| "Isn't in Open Food Facts yet" | Type what the item is and add it. |
| Use-by dates are off by a day | Set `TZ` to your time zone and recreate the container. |
| Wrong shelf life for an item | Tap the item → **Shelf life** and pick the right rule. TablePlan remembers it for that name. |
| "Couldn't sync USDA FoodKeeper" | The server can't reach the USDA site. Download `foodkeeper.json` from the USDA FoodKeeper data page on another computer, copy it into the TablePlan data folder, and tap **Settings → Shelf life data → Sync now**. The starter table is used until then. |
| Checked-off item didn't go to the pantry | Only items with shelf-life data are added automatically. Tap **Track it** in the message, or add it on the Pantry tab. |

## Notifications

| Problem | Fix |
|---|---|
| Email test failed: username or password rejected | Gmail, Yahoo and iCloud need an **app password**, not your normal password. Gmail requires 2-Step Verification first. |
| Email test failed: connection error | Check the SMTP server, port and security. Some networks block outgoing SMTP; try Telegram or ntfy. |
| Telegram: "Haven't seen the code yet" | Open the bot in Telegram and tap **Start** (or send the code in your group), then **I tapped Start, check**. |
| Telegram: "The link code expired" | Codes last 15 minutes. Tap **Start over**. |
| ntfy: "Topic must be 8–64 letters…" | Use the suggested random topic. |
| ntfy.sh asks for a longer topic | On the public server, use a topic of 20+ characters or an access token. |
| No automatic plan or daily reminder | Check the settings in **Settings → Meal planning**, that a notification channel is set up, and that `TZ` is right. Jobs run from the chosen hour, checked every 5 minutes. |

## Phone and browser

| Problem | Fix |
|---|---|
| Chrome says "Not secure" | Normal for `http://`. Add HTTPS for a padlock. |
| Everything looks tiny on iPhone | Safari's page zoom is below 100%. Tap **aA** → **100%**. If TablePlan is on your Home Screen, remove it and add it again afterwards. |
| TablePlan isn't in Android's Share menu | Install it from Chrome (**⋮ → Install app**). This needs HTTPS. |
| iPhone Share → TablePlan does nothing | Check the Shortcut's URL action is your TablePlan address followed by `/?url=` and the **Shortcut Input** variable. See the [user guide](user-guide.md#iphone-and-ipad-a-one-time-shortcut). |
| Cook-mode timer didn't beep | Tap **Start timer** in cook mode (browsers need a tap before playing sound), and keep the phone's volume up. |

## Still stuck?

Check the log, then [open an issue](https://github.com/thomasjvalenzuela/tableplan/issues) with what you did, what you expected, and the relevant log lines. Remove any keys or passwords before posting.
