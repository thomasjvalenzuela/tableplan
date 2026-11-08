# Importing from Mealie

TablePlan can copy everything from an existing [Mealie](https://github.com/mealie-recipes/mealie) server in one step. Mealie isn't needed afterwards.

## What's copied

| Copied | Details |
|---|---|
| Recipes | All of them, with ingredients, steps, servings, times, tags, categories, ratings and source links. Recipe IDs and slugs are kept. |
| Recipe photos | The main photo of each recipe. |
| Favorites | The favorites of the Mealie user whose API token you use. |
| Meal plans | Entries from one year back to one year ahead. |
| Shopping lists | Every list and item, including checked items. |

Not copied: Mealie users and households, comments, cookbooks, and other Mealie-only data.

## Steps

1. **Get a Mealie API token.** In Mealie, open **Profile → API Tokens**, create one, and copy it.
2. **In TablePlan**, open **Settings → Advanced → Import from Mealie**.
3. Enter the Mealie address and the token. Use the server's network address, for example:
   ```
   http://192.168.1.50:9925
   ```
   Don't use `localhost`. TablePlan runs in its own container, where `localhost` means TablePlan itself.
4. Tap **Import**. Large libraries can take a few minutes. When it's done, TablePlan shows how many recipes, photos, planned meals and list items were copied.

## Running it again

It's safe to run more than once:

- **Recipes** are matched by ID and **updated to the Mealie version**. If you edited an imported recipe in TablePlan, re-importing replaces your edit. Recipes created in TablePlan aren't touched.
- **Photos** already in TablePlan are kept.
- **Meal plans** and **shopping list items** already imported are skipped, so nothing is duplicated and changes you made in TablePlan are kept.

When you're happy with the result, you can uninstall Mealie.

## Upgrading from TablePlan v0.3 or earlier

Versions up to v0.3 ran a bundled Mealie container (`tableplan-mealie`) to store recipes. v0.4 and later store everything in TablePlan.

**One-line installer:** when you upgrade, the installer leaves the old Mealie running and prints its address. Import from that address as above, then run `sudo tableplan update` to remove the old Mealie container. Its files stay in the `mealie` folder of your install until you delete them.

**ZimaOS, or if the old Mealie was already removed:** its files are still on disk. Start it temporarily, import, then remove it:

```bash
sudo docker run -d --name old-mealie -p 9925:9000 \
  -v /DATA/AppData/tableplan/mealie:/app/data \
  ghcr.io/mealie-recipes/mealie:v3.30.0
# In TablePlan, import from http://YOUR-SERVER-IP:9925, then:
sudo docker rm -f old-mealie
```

Use the `mealie` folder from your install: next to `data/` for the installer, or `./mealie` for Docker Compose.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Enter your Mealie address … and an API token" | The address must start with `http://` or `https://`, and the token can't be empty. |
| Can't connect | Use the server's network IP, not `localhost` or `127.0.0.1`. Check the Mealie port (usually `9925`). |
| "Mealie said 401" or "403" | The token is wrong or expired. Create a new one in Mealie → Profile → API Tokens. |
| Some favorites are missing | Only the token owner's favorites are copied. Use a token from the account whose favorites you want. |
| TablePlan is on Railway or another cloud host | A Mealie on your home network isn't reachable from the cloud. Import on a home install first, or make Mealie reachable over HTTPS. |
