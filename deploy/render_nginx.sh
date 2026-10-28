#!/usr/bin/env bash
# Render the nginx site for SITE_URL in the root .env:
#   deploy/render_nginx.sh            -> deploy/nginx/build/<host>.conf, then prints the install steps
# Nothing is installed and sudo is never run here; the printed commands do that.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
env_value() { { grep -E "^$1=" "$ROOT/.env" || true; } | tail -1 | cut -d= -f2- | tr -d '"'"'"'' ; }

SITE_URL="$(env_value SITE_URL)"
[ -n "$SITE_URL" ] || { echo "SITE_URL is not set in $ROOT/.env" >&2; exit 1; }
SITE_HOST="$(printf '%s' "$SITE_URL" | sed -E 's#^[a-z]+://##; s#[:/].*$##')"
LEGACY_CDN_ROOT="$(env_value LEGACY_CDN_ROOT)"
LEGACY_CDN_ROOT="${LEGACY_CDN_ROOT:-/mnt/sda2/cdn.samian.mong.ir/public_html/wwwroot}"
PROJECT_DIR="$ROOT"
export SITE_HOST PROJECT_DIR LEGACY_CDN_ROOT

mkdir -p "$ROOT/deploy/nginx/build"
OUT="$ROOT/deploy/nginx/build/$SITE_HOST.conf"
# Only our three placeholders; nginx's $variables stay as they are.
envsubst '${SITE_HOST} ${PROJECT_DIR} ${LEGACY_CDN_ROOT}' < "$ROOT/deploy/nginx/site.conf.template" > "$OUT"
echo "Wrote $OUT"

cat <<STEPS

Install (on the server):
  sudo cp $ROOT/deploy/nginx/mong-img-map.conf /etc/nginx/conf.d/
  sudo cp $OUT /etc/nginx/sites-available/$SITE_HOST.conf
  sudo ln -sf /etc/nginx/sites-available/$SITE_HOST.conf /etc/nginx/sites-enabled/
  sudo nginx -t && sudo systemctl reload nginx
  sudo certbot --nginx -d $SITE_HOST

Loopback, so server-side rendering reaches the API on this machine instead of
going out through DNS (add once):
  grep -q " $SITE_HOST\$" /etc/hosts || echo "127.0.0.1 $SITE_HOST" | sudo tee -a /etc/hosts

Then rebuild and restart the frontend (it bakes SITE_URL in) and restart Django.
STEPS
