#!/bin/bash
# Deploy the news map from the latest main branch. Idempotent; run as root.
set -euo pipefail

cd /opt/news-app
git fetch origin
git reset --hard origin/main

docker build -t newsmap .
docker network create newsnet 2>/dev/null || true

# App: no public ports; reachable only via Caddy on the internal network.
docker rm -f newsmap || true
docker run -d --name newsmap --restart unless-stopped \
  --network newsnet \
  -v /opt/news-data:/srv/data \
  -e "GA_MEASUREMENT_ID=${GA_MEASUREMENT_ID:-}" \
  newsmap

# Caddy: terminates TLS for globalnewsmap.net (Let's Encrypt, auto-renew)
# and proxies to the app. Owns ports 80/443 on the host.
mkdir -p /opt/caddy-data
cp -f deploy/Caddyfile /opt/Caddyfile
docker rm -f newscaddy || true
docker run -d --name newscaddy --restart unless-stopped \
  --network newsnet \
  -p 80:80 -p 443:443 \
  -v /opt/caddy-data:/data \
  -v /opt/Caddyfile:/etc/caddy/Caddyfile:ro \
  caddy:2-alpine

echo "newsmap redeployed: $(date -u +%FT%TZ)"
