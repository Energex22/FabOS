#!/usr/bin/env bash
set -euo pipefail

FABOS_DIR="${FABOS_DIR:-/opt/fabos}"
WEB_DIR="${WEB_DIR:-/opt/fabos-web}"
DATA_DIR="${DATA_DIR:-/var/lib/fabos}"
ENV_DIR="/etc/fabos"
ENV_FILE="${ENV_DIR}/server.env"
SERVICE_FILE="/etc/systemd/system/fabos.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo)."
  exit 1
fi

for cmd in python3 git npm runuser; do
  command -v "$cmd" >/dev/null || { echo "Missing required command: $cmd"; exit 1; }
done

command -v node >/dev/null || { echo "Missing required command: node"; exit 1; }
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [[ "$NODE_MAJOR" -ne 24 ]]; then echo "Node.js 24 is required by FabOS-Web (found $NODE_MAJOR)."; exit 1; fi
NPM_MAJOR="$(npm --version | cut -d. -f1)"
if [[ "$NPM_MAJOR" -ne 11 ]]; then echo "npm 11 is required by FabOS-Web (found $NPM_MAJOR)."; exit 1; fi

id fabos >/dev/null 2>&1 || useradd --system --home "$FABOS_DIR" --shell /usr/sbin/nologin fabos
mkdir -p "$FABOS_DIR" "$DATA_DIR" "$ENV_DIR"
chown -R fabos:fabos "$FABOS_DIR" "$DATA_DIR"
chmod 750 "$DATA_DIR"

if [[ ! -d "$FABOS_DIR/.git" ]]; then
  echo "FabOS checkout not found at $FABOS_DIR."
  echo "Clone/copy the repository there, then rerun this installer."
  exit 1
fi
if [[ ! -f "$WEB_DIR/package.json" ]]; then
  echo "FabOS-Web checkout not found at $WEB_DIR."
  exit 1
fi

if [[ ! -x "$FABOS_DIR/.venv/bin/python" ]]; then
  python3 -m venv "$FABOS_DIR/.venv"
fi
"$FABOS_DIR/.venv/bin/python" -m pip install --upgrade pip
"$FABOS_DIR/.venv/bin/python" -m pip install -e "$FABOS_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<EOF
FABOS_DATA_DIR=$DATA_DIR
FABOS_API_HOST=127.0.0.1
FABOS_API_PORT=8000
FABOS_API_THREADS=8
FABOS_PAYMENT_PROVIDER=stripe
FABOS_API_DOCS=false
FABOS_TRUSTED_PROXIES=127.0.0.1
FABOS_ALLOWED_HOSTS=fabvex.duckdns.org
FABOS_CORS_ORIGINS=https://fabvex.duckdns.org
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_SUCCESS_URL=https://fabvex.duckdns.org/orders.html
STRIPE_CANCEL_URL=https://fabvex.duckdns.org/checkout.html
EOF
  chmod 640 "$ENV_FILE"
  chown root:fabos "$ENV_FILE"
fi

install -m 644 "$FABOS_DIR/deployment/linux/fabos.service" "$SERVICE_FILE"

runuser -u fabos -- bash -c "cd '$WEB_DIR' && npm ci && npm test && npm run build"
chown -R fabos:fabos "$WEB_DIR"

"$FABOS_DIR/.venv/bin/python" -m fabos_core.cli init
systemctl daemon-reload
systemctl enable fabos.service

echo
echo "FabOS Linux installation prepared."
echo "Configure $ENV_FILE, then run:"
echo "  $FABOS_DIR/.venv/bin/python -m fabos_core.cli setup-owner"
echo "  $FABOS_DIR/.venv/bin/python -m fabos_core.cli setup-dns"
echo "  $FABOS_DIR/.venv/bin/python -m fabos_core.cli setup-stripe"
echo "  $FABOS_DIR/.venv/bin/python -m fabos_core.cli production-check"
echo "  systemctl start fabos.service"
echo
echo "Install/configure Caddy using deployment/linux/Caddyfile."
