# Security Policy

TablePlan is a self-hosted app that stores household data and third-party credentials
(an OpenAI API key, notification tokens, SMTP passwords). We take reports seriously and
appreciate responsible disclosure.

## Supported versions

Only the latest release receives security fixes. Releases are rolling: every build of the
current minor line (`0.4.x` today) replaces the previous one, and the ZimaOS store, the
installer's `tableplan update` command and the in-app update banner all move you to it.

| Version              | Supported |
| -------------------- | --------- |
| Latest `0.x` release | Yes       |
| Older builds         | No, please update |

## Reporting a vulnerability

**Please do not open a public issue, discussion or pull request for security problems.**

Report privately through GitHub:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**
   ([direct link](https://github.com/thomasjvalenzuela/tableplan/security/advisories/new)).
3. Describe the issue, the affected version, steps to reproduce, and the impact you expect.
   A proof of concept helps but is not required.

## What to expect

- **Acknowledgement** within 3 business days.
- **Initial assessment** (confirmed, needs more information, or not a vulnerability) within 7 days.
- **Fix**: critical and high-severity issues are prioritised and usually released within 30 days;
  we will keep you updated on progress and agree on a disclosure date with you.
- **Credit** in the published GitHub Security Advisory and the changelog, unless you prefer
  to stay anonymous.

This is a volunteer-run project, so timelines are goals rather than guarantees.

## Scope

In scope:

- The TablePlan server (`app/server.py`, `app/native/`) and web app (`app/static/`).
- The Docker image published at `ghcr.io/thomasjvalenzuela/tableplan`.
- The installer (`install/install.sh`), compose files and the ZimaOS store definition.
- The release workflow and anything it publishes to GitHub Pages.

Examples: authentication or session bypass, access to another household's data, leaking stored
credentials, injection (SQL, command, HTML/script), server-side request forgery through recipe
import, path traversal, and insecure defaults in the image or installer.

Out of scope:

- Vulnerabilities in third-party services TablePlan talks to (OpenAI, Telegram, ntfy, SMTP
  providers, recipe websites); report those to the vendor.
- Issues that need an already-compromised host, Docker socket or admin account.
- Running TablePlan exposed to the internet without HTTPS, contrary to the docs.
- Denial of service through excessive traffic, and missing security headers without a
  demonstrated impact.
- Vulnerabilities in vendored libraries that are not reachable from TablePlan (please report
  upstream).

## Safe harbour

We will not pursue action against good-faith research that respects user privacy, avoids
data destruction and service disruption, only tests against your own installation, and gives
us reasonable time to fix the issue before disclosure.
