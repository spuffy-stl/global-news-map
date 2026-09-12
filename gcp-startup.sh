#!/bin/bash
# GCP startup script: install Docker, clone the news map repo (main branch),
# and run it. Re-runs safely on reboot (re-deploys latest main).
set -eux
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y docker.io git
systemctl enable --now docker

mkdir -p /opt/news-data

if [ ! -d /opt/news-app/.git ]; then
  rm -rf /opt/news-app
  git clone --branch main https://github.com/spuffy-stl/global-news-map.git /opt/news-app
else
  git -C /opt/news-app fetch origin
  git -C /opt/news-app reset --hard origin/main
fi

bash /opt/news-app/deploy/deploy.sh

echo "newsmap deployed: $(date -u +%FT%TZ)"
