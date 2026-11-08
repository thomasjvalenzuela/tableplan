# FAQ

### Is my data private?

Yes. Recipes, plans, lists, pantry and settings stay on your server. Data only leaves for features you turn on: AI imports go to OpenAI, notifications go through Telegram, ntfy or your mail provider. TablePlan also downloads the public USDA shelf-life database, looks up barcodes on Open Food Facts, fetches food photos, and checks for new versions. The full list is in [security.md](security.md#outbound-connections).

### Does it cost anything?

TablePlan is free and open source (AGPL-3.0). AI features are optional and use your own OpenAI account, typically a few cents per screenshot import and under a cent for a Step-by-step arrangement. **Settings → AI → AI spending** shows what you've spent and can alert you at a monthly budget.

### Do I need an OpenAI key?

No. Without one you can import from most recipe websites, paste or type recipes, plan meals, build shopping lists, track the pantry and scan barcodes. A key is needed for screenshots, photos, PDFs and spoken video recipes. See [What works without AI](user-guide.md#what-works-without-ai).

### Can I use an AI provider other than OpenAI?

Not at the moment. TablePlan uses OpenAI's API directly. You can choose the OpenAI model in **Settings → Setup → AI recipe import**.

### Do I need Mealie?

No. Since v0.4, TablePlan stores everything itself. If your recipes are in Mealie, [import them](importing-from-mealie.md) once.

### Where do use-by dates come from?

From the USDA FoodKeeper database, using the cautious end of each range. When you open or freeze something, the date switches to the "after opening" or freezer time. A date you type from the package always wins, and you can edit any rule or add your own in **Settings → Shelf life data → House rules & edits**.

### Why are use-by dates off by a day?

The container's time zone is wrong. Set `TZ` (for example `America/New_York`) and recreate the container.

### How do several people in my household use it?

Everyone opens the same address. There's one shared library, plan, list and pantry, and no separate user accounts. If you set a household password, each device signs in once.

### Can I use it away from home?

Yes. The easiest safe way is Tailscale. See [HTTPS and remote access](https-and-remote-access.md).

### Why does Chrome say "Not secure"?

Chrome labels every `http://` address that way, including apps on your own network. TablePlan works fine, but adding HTTPS gives you the padlock, live barcode scanning and Android sharing. See [HTTPS and remote access](https-and-remote-access.md).

### Can I run it in the cloud?

Yes, in beta on Railway. See [deploy-railway.md](deploy-railway.md). Any host that runs a Docker image with a persistent volume at `/data` should work the same way; set `TABLEPLAN_PUBLIC=1` there.

### Which devices does it run on?

The server runs on any `amd64` or `arm64` machine with Docker, including Raspberry Pi 4/5. The app runs in any modern browser and can be added to iPhone, iPad and Android Home Screens.

### How do I back it up?

Copy the data folder while TablePlan is stopped, or run `sudo tableplan backup` if you used the installer. See [install.md](install.md#backups).

### Can I build my own version?

Yes. Fork the repo; the release workflow publishes your own image, ZimaOS store and update feed. See [CONTRIBUTING.md](../CONTRIBUTING.md) and [architecture.md](architecture.md).
