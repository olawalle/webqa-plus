#!/usr/bin/env bash
# deploy.sh — one-shot deployment helper for WebQA-Plus
# Usage: ./deploy.sh [--domain YOUR_DOMAIN] [--email YOUR_EMAIL]
set -euo pipefail

DOMAIN=""
EMAIL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --email)  EMAIL="$2";  shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "======================================================"
echo " WebQA-Plus deployment helper"
echo "======================================================"

# ── 1. Verify .env exists ──────────────────────────────────────────────────
if [[ ! -f .env ]]; then
  echo "[INFO] .env not found — copying from .env.example"
  cp .env.example .env
  echo "[ACTION REQUIRED] Edit .env and set your GOOGLE_API_KEY, then re-run."
  exit 1
fi

# ── 2. Patch domain into nginx config ──────────────────────────────────────
if [[ -n "$DOMAIN" ]]; then
  echo "[INFO] Setting domain to: $DOMAIN"
  sed -i "s/YOUR_DOMAIN/$DOMAIN/g" nginx/nginx.conf
fi

# ── 3. Build and start containers ─────────────────────────────────────────
echo "[INFO] Building Docker images..."
docker compose build --no-cache

echo "[INFO] Starting services..."
docker compose up -d webqa nginx

# ── 4. Provision SSL (requires --domain and --email) ──────────────────────
if [[ -n "$DOMAIN" && -n "$EMAIL" ]]; then
  echo "[INFO] Provisioning SSL certificate for $DOMAIN..."

  # Make sure the ACME challenge directory exists
  mkdir -p nginx/www nginx/certs

  docker compose run --rm certbot certonly \
    --webroot \
    --webroot-path /var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

  echo "[INFO] SSL obtained. Enabling HTTPS in nginx/nginx.conf..."
  # Uncomment the HTTPS server block
  sed -i 's/^# //' nginx/nginx.conf

  echo "[INFO] Reloading Nginx..."
  docker compose exec nginx nginx -s reload

  echo "[INFO] Starting Certbot auto-renewal..."
  docker compose up -d certbot
fi

echo ""
echo "======================================================"
echo " Done!"
if [[ -n "$DOMAIN" ]]; then
  echo " App is live at: https://$DOMAIN"
else
  echo " App is running. Access it at: http://$(curl -s ifconfig.me):80"
  echo " (Add --domain and --email to enable HTTPS)"
fi
echo "======================================================"
