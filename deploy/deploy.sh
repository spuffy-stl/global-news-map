#!/bin/bash
# Deploy the news map from the latest main branch. Idempotent; run as root.
set -euo pipefail

cd /opt/news-app
git fetch origin
git reset --hard origin/main

docker build -t newsmap .
docker rm -f newsmap || true
docker run -d --name newsmap --restart unless-stopped \
  -p 80:8000 \
  -v /opt/news-data:/srv/data \
  -e "GA_MEASUREMENT_ID=${GA_MEASUREMENT_ID:-}" \
  newsmap

echo "newsmap redeployed: $(date -u +%FT%TZ)"
