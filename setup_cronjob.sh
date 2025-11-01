#!/bin/bash
#
# Sets up a cron job to run a Python script every 5 minutes in Docker/Compose.
# - If the service is running: uses `docker compose exec -T <service> python ...`
# - If the service is NOT running: falls back to `docker compose run --rm --no-deps <service> python ...`
# The job also cds into the project directory so relative paths and .env resolution are stable.

set -euo pipefail

# ====== CONFIGURATION ======
CRON_TIME="*/5 * * * *"          # Every 5 minutes (adjust as needed)
DOCKER_SERVICE="web"             # The compose service that has your deps installed
CONTAINER_PYTHON="python"        # Or "python3" if that's what you use in the container

# Directory of this setup script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Your Python script relative to THIS setup script (host path)
RELATIVE_SCRIPT_PATH="email_job.py"
HOST_SCRIPT_PATH="$(realpath "$SCRIPT_DIR/$RELATIVE_SCRIPT_PATH")"

# Path to the script *inside* the container (adjust if your mount path differs)
CONTAINER_SCRIPT_PATH="/app/${RELATIVE_SCRIPT_PATH}"

# Log file on host
LOG_PATH="$SCRIPT_DIR/email_job.log"

# Try to auto-detect whether "docker compose" (v2) or "docker-compose" (v1) is available
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
else
  echo "❌ Neither 'docker compose' nor 'docker-compose' found in PATH." >&2
  exit 1
fi
# ============================

mkdir -p "$(dirname "$LOG_PATH")"
chmod +x "$HOST_SCRIPT_PATH"

# Minimal PATH for cron so it can find docker binaries
CRON_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Build the Docker/Compose execution snippet:
# 1) cd into the project folder on host (so docker uses the right compose files/context)
# 2) If the service is running -> exec
# 3) else -> run a one-off container without deps
DOCKER_RUN_SNIPPET="
cd \"$SCRIPT_DIR\" && \
$COMPOSE_CMD ps --services --filter status=running | grep -qx \"$DOCKER_SERVICE\" && \
$COMPOSE_CMD exec -T \"$DOCKER_SERVICE\" $CONTAINER_PYTHON \"$CONTAINER_SCRIPT_PATH\" || \
$COMPOSE_CMD run --rm --no-deps \"$DOCKER_SERVICE\" $CONTAINER_PYTHON \"$CONTAINER_SCRIPT_PATH\"
"

# Compose the actual cron line
# - We use /usr/bin/env to set a safe PATH for this command only
# - Append logs and errors to LOG_PATH
CRON_JOB="$CRON_TIME /usr/bin/env PATH=$CRON_PATH bash -lc '$DOCKER_RUN_SNIPPET' >> \"$LOG_PATH\" 2>&1"

# Check if a cron job for this script already exists (search by container script path)
if crontab -l 2>/dev/null | grep -F "$CONTAINER_SCRIPT_PATH" >/dev/null; then
  echo "✅ Cron job already exists for $CONTAINER_SCRIPT_PATH"
else
  # Add the cron job
  (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
  echo "🚀 Added new cron job:"
  echo "$CRON_JOB"
fi

echo
echo "📅 Current cron jobs:"
crontab -l
