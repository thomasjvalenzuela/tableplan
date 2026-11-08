# HTTPS and remote access

TablePlan works over plain `http://` on your home network. HTTPS is optional, but it unlocks several phone features and is the only safe way to use TablePlan away from home.

- [Why HTTPS matters](#why-https-matters)
- [Option 1: Tailscale (recommended)](#option-1-tailscale-recommended)
- [Option 2: your own domain with a reverse proxy](#option-2-your-own-domain-with-a-reverse-proxy)
- [Using TablePlan away from home](#using-tableplan-away-from-home)
- [Reverse proxy notes](#reverse-proxy-notes)

---

## Why HTTPS matters

Browsers only allow some features on secure (`https://`) addresses:

| Feature | On `http://` | On `https://` |
|---|---|---|
| Live barcode scanning | Camera is blocked. You take a photo of the barcode or type the number. | Camera opens and scans automatically. |
| Install on Android | Chrome adds a plain shortcut. TablePlan doesn't appear in the Share menu. | **Install app** works, and TablePlan appears in every app's **Share** menu. |
| Paste a link from the clipboard | You paste by hand. | The Link field fills in from your clipboard. |
| Cook-mode timer notifications in the background | Not available. | Available after you allow notifications. |
| Chrome's "Not secure" label | Shown. | Padlock instead. |
| Traffic on your network | Unencrypted. | Encrypted. The sign-in cookie is marked `Secure`. |

---

## Option 1: Tailscale (recommended)

Tailscale gives you HTTPS and access away from home, without opening anything on your router.

1. Install **Tailscale** on the server (it's in the ZimaOS App Store) and on each phone, and sign in to the same account everywhere.
2. In the [Tailscale admin console → DNS](https://login.tailscale.com/admin/dns), turn on **MagicDNS** and **HTTPS Certificates**.
3. On the server, run one of these:
   ```bash
   # ZimaOS / CasaOS, where Tailscale runs as a container.
   # Find the container name with: docker ps | grep -i tailscale
   sudo docker exec tailscale tailscale serve --bg 9930

   # Tailscale installed directly on Linux
   sudo tailscale serve --bg 9930
   ```
   Use your TablePlan port if it isn't 9930.
4. Open `https://<server-name>.<your-tailnet>.ts.net`. The exact name is in the Tailscale admin console.

Phones need the Tailscale app connected to reach this address. Update the iPhone Shortcut address (see the [user guide](user-guide.md#iphone-and-ipad-a-one-time-shortcut)) and re-add TablePlan to your Home Screen from the new address.

---

## Option 2: your own domain with a reverse proxy

Use Nginx Proxy Manager, Caddy or Traefik with a domain you own. Phones don't need an extra app, but this only works on your home network unless you also expose it (see below).

1. **DNS:** create an A record such as `tableplan.example.com` pointing to your server's **local** IP (for example `192.168.1.20`). On Cloudflare, set it to **DNS only** (grey cloud).
2. **Proxy host:** forward `tableplan.example.com` to `http://192.168.1.20:9930`.
3. **Certificate:** request a Let's Encrypt certificate with the **DNS challenge** (for Cloudflare, an API token with *Zone → DNS → Edit*). The DNS challenge works for local-only addresses, so no router ports need opening. Turn on **Force SSL**.

The proxy needs ports 80 and 443 on the machine it runs on. On ZimaOS the dashboard uses port 80, so either move the dashboard to another port in ZimaOS settings or run the proxy on another machine.

---

## Using TablePlan away from home

| Approach | Safety | Notes |
|---|---|---|
| **Tailscale** (Option 1) | Best | Nothing is exposed to the internet. |
| **Public domain** through a reverse proxy or tunnel | OK with care | Set `TABLEPLAN_PUBLIC=1` and a strong household password. |
| Port-forwarding 9930 on your router | **Don't** | Plain HTTP over the internet, with no TLS. |

### If you expose TablePlan publicly

1. Put it behind HTTPS (a reverse proxy or a tunnel such as Cloudflare Tunnel).
2. Set `TABLEPLAN_PUBLIC=1` (and `TABLEPLAN_TRUST_PROXY=1` if your proxy sets `X-Forwarded-For`) on the TablePlan container and recreate it. On Railway both are on automatically.
3. Open TablePlan. The sign-in screen asks for a **one-time setup code**. Find it in the log:
   - ZimaOS: TablePlan → **Logs**
   - Docker: `docker logs tableplan`
   - Look for: `PUBLIC MODE · one-time setup code: …` (16 letters and digits; spaces and dashes are ignored when you type it)
4. Sign in with the code, run the wizard, and **set a household password** on the **Lock it** step. After that, the code no longer works and the password is required on every device.

The setup code changes every time TablePlan restarts, until a password is set. In public mode the password can't be removed. More in [security.md](security.md).

---

## Reverse proxy notes

- TablePlan reads `X-Forwarded-Proto` to know the page is on HTTPS (it then marks the sign-in cookie `Secure` and sends HSTS).
- Set `TABLEPLAN_TRUST_PROXY=1` on the TablePlan container when it's behind your proxy, so it uses the real client address from `X-Forwarded-For` (for per-client sign-in and import limits) and the `X-Forwarded-Host` header. Only do this if the proxy overwrites those headers; otherwise a client could fake its address. On Railway it's on automatically.
- Allow request bodies up to about 40 MB, so multi-image screenshot imports aren't rejected. In Nginx: `client_max_body_size 40m;`.
- Link and video imports can take up to a few minutes. Raise proxy read timeouts to at least 180 seconds.
- `/health` returns `ok` without signing in, for health checks.
