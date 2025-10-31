#!/usr/bin/env bash
set -euo pipefail

# where this script lives
cd "$(dirname "$0")"

echo "==> Pulling latest code (if this is a git repo)…"
if [ -d .git ]; then
  git pull --ff-only
fi

echo "==> Building fresh image(s)…"
docker compose build --pull

echo "==> Stopping existing containers…"
docker compose down

echo "==> Starting updated containers…"
docker compose up -d

echo "==> Checking app health…"
# adjust the URL/port if you front with Caddy on 80/443
curl -fsS http://127.0.0.1:8000/ >/dev/null && echo "OK"
