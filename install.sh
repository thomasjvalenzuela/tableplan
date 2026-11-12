#!/usr/bin/env bash
# TablePlan installer: recipes, meal plans, smart pantry & grocery lists. One app, one container.
#
#   curl -fsSL https://thomasjvalenzuela.github.io/tableplan/install.sh | sudo bash
#
# Options (environment variables):
#   TABLEPLAN_DIR=/path      install folder (default: /media/DATA/AppData/tableplan, else /DATA/AppData/tableplan)
#   TABLEPLAN_PORT=9930      TablePlan port
#   TABLEPLAN_IMAGE=...      override the image (default ghcr.io/thomasjvalenzuela/tableplan:latest)
#
# After install, manage it with:  sudo tableplan {status|update|logs|restart|backup|uninstall}
set -euo pipefail

IMAGE="${TABLEPLAN_IMAGE:-ghcr.io/thomasjvalenzuela/tableplan:latest}"
TP_PORT="${TABLEPLAN_PORT:-9930}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n  \033[31m✗ %s\033[0m\n\n' "$*" >&2; exit 1; }

echo
bold "🍳  TablePlan installer"
echo

# ---------- preflight
[ "$(id -u)" -eq 0 ] || die "Run with sudo:  curl -fsSL <url>/install.sh | sudo bash"
command -v docker >/dev/null 2>&1 || die "Docker isn't installed. On ZimaOS/CasaOS it's built in; elsewhere see https://docs.docker.com/engine/install/"
if docker compose version >/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"
else die "Docker Compose isn't available (need 'docker compose' or 'docker-compose')."; fi
docker info >/dev/null 2>&1 || die "Docker is installed but not running."
ok "Docker and Compose found ($DC)"

if [ -n "${TABLEPLAN_DIR:-}" ]; then DIR="$TABLEPLAN_DIR"
elif [ -d /media/DATA ]; then DIR=/media/DATA/AppData/tableplan
elif [ -d /DATA ]; then DIR=/DATA/AppData/tableplan
else DIR=/opt/tableplan; fi

UPGRADE=0
[ -f "$DIR/docker-compose.yml" ] && UPGRADE=1
# Older versions (v0.3 and earlier) bundled a Mealie container. Leave it running on upgrade so its
# recipes can be copied over with Settings → Advanced → "Import from Mealie".
OLD_MEALIE_PORT=""
if [ "$UPGRADE" -eq 1 ] && grep -q 'tableplan-mealie' "$DIR/docker-compose.yml" 2>/dev/null; then
  OLD_MEALIE_PORT="$(sed -n 's/.*"\([0-9]*\):9000".*/\1/p' "$DIR/docker-compose.yml" | head -1)"
  OLD_MEALIE_PORT="${OLD_MEALIE_PORT:-9925}"
fi

port_busy() {
  local p="$1"
  if command -v ss >/dev/null 2>&1; then ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${p}\$"
  else netstat -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${p}\$"; fi
}
if [ "$UPGRADE" -eq 0 ]; then
  port_busy "$TP_PORT" && die "Port $TP_PORT is already in use. Re-run with TABLEPLAN_PORT=… to pick another."
  docker ps -a --format '{{.Names}}' | grep -qx tableplan && die "A container named 'tableplan' already exists. Remove it or run 'sudo tableplan uninstall' first."
  ok "Port $TP_PORT free"
fi

TZ_VAL="$(cat /etc/timezone 2>/dev/null || true)"
[ -z "$TZ_VAL" ] && TZ_VAL="$(readlink /etc/localtime 2>/dev/null | sed -n 's#.*/zoneinfo/##p' || true)"
[ -z "$TZ_VAL" ] && TZ_VAL="UTC"

# ---------- files
mkdir -p "$DIR/data"
ok "Install folder: $DIR"

cat > "$DIR/docker-compose.yml" <<YAML
# Managed by the TablePlan installer. Re-running the installer rewrites this file; your data is kept.
name: tableplan

services:
  tableplan:
    container_name: tableplan
    image: ${IMAGE}
    restart: unless-stopped
    ports: ["${TP_PORT}:8080"]
    environment:
      TZ: "${TZ_VAL}"
      TABLEPLAN_INSTALL: cli
    volumes:
      - ./data:/data
    security_opt: ["no-new-privileges:true"]
YAML

cat > "$DIR/tableplan" <<'CLI'
#!/usr/bin/env bash
# TablePlan helper: sudo tableplan {status|update|logs|restart|backup|uninstall}
set -euo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$DIR"
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
case "${1:-status}" in
  status)  $DC ps ;;
  update)  echo "Updating TablePlan…"; $DC pull && $DC up -d --remove-orphans && docker image prune -f >/dev/null && echo "✓ Up to date"; $DC ps ;;
  logs)    $DC logs -f --tail=100 "${2:-tableplan}" ;;
  restart) $DC restart ;;
  backup)  f="$DIR/../tableplan-backup-$(date +%F-%H%M).tgz"; $DC stop >/dev/null; items="data docker-compose.yml"; [ -d "$DIR/mealie" ] && items="$items mealie"; tar czf "$f" -C "$DIR" $items; $DC start >/dev/null; echo "✓ Backup: $(readlink -f "$f")" ;;
  uninstall)
    read -r -p "Remove TablePlan containers? Your data in $DIR stays unless you delete it. [y/N] " a
    if [[ "$a" =~ ^[Yy] ]]; then $DC down; rm -f /usr/local/bin/tableplan 2>/dev/null || true; echo "Removed containers. Data kept in $DIR"; fi ;;
  *) echo "usage: tableplan {status|update|logs [service]|restart|backup|uninstall}"; exit 1 ;;
esac
CLI
chmod +x "$DIR/tableplan"
if ln -sf "$DIR/tableplan" /usr/local/bin/tableplan 2>/dev/null; then CLI_CMD="sudo tableplan"; else CLI_CMD="sudo $DIR/tableplan"; fi

# ---------- start
echo
bold "Downloading TablePlan…"
cd "$DIR"
$DC pull
if [ -n "$OLD_MEALIE_PORT" ]; then $DC up -d; else $DC up -d --remove-orphans; fi
ok "TablePlan started"

printf '  Waiting for TablePlan'
HEALTHY=0
for _ in $(seq 1 60); do
  if docker exec tableplan python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=3)" >/dev/null 2>&1; then
    echo; ok "TablePlan is running"; HEALTHY=1; break
  fi
  printf '.'; sleep 2
done
[ "$HEALTHY" -eq 1 ] || { echo; warn "TablePlan hasn't answered yet. Check with: $DC -f $DIR/docker-compose.yml logs tableplan"; }

IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="src"){print $(i+1); exit}}' || true)"
[ -z "$IP" ] && IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
[ -z "$IP" ] && IP="<server-ip>"

WIZ_HINT="The setup wizard creates your login and sets up AI import and email."
echo
if [ "$UPGRADE" -eq 1 ]; then bold "✅  TablePlan updated"; else bold "✅  TablePlan is installed"; fi
cat <<DONE

  Open on your phone:   http://${IP}:${TP_PORT}
  ${WIZ_HINT}

  Manage:  ${CLI_CMD} status | update | logs | backup | uninstall
  Data:    ${DIR}

DONE

if [ -n "$OLD_MEALIE_PORT" ]; then
  cat <<NOTE
  TablePlan no longer needs Mealie. Your old Mealie is still running so you can copy its recipes:
    1. In TablePlan open Settings → Advanced → "Import from Mealie"
    2. Address: http://${IP}:${OLD_MEALIE_PORT}   API token: Mealie → Profile → API Tokens
  When the import is done, run "${CLI_CMD} update" to remove the old Mealie container.
  (Its files stay in ${DIR}/mealie until you delete them.)

NOTE
fi
