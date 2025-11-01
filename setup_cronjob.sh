#!/bin/bash
#
# Set up a cron job to run a Python script every 5 minutes INSIDE Docker/Compose.
# - If the service is running -> exec into it
# - Otherwise -> run a one-off container from the same service image
# The cron line is a SINGLE LINE to avoid "bad minute" errors.

set -euo pipefail

# ====== CONFIGURATION ======
CRON_TIME="*/5 * * * *"          # Every 5 minutes
DOCKER_SERVICE="web"             # Compose service that has your deps installed
CONTAINER_PYTHON="python"        # Or "python3" inside the container

# Directory of this setup script (host)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Your Python script relative to THIS setup script (host path)
RELATIVE_SCRIPT_PATH="email_job.py"
HOST_SCRIPT_PATH="$(realpath "$SCRIPT_DIR/$RELATIVE_SCRIPT_PATH")"

# Path to the script *inside* the container
CONTAINER_SCRIPT_PATH="/app/${RELATIVE_SCRIPT_PATH}"

# Log file on host
LOG_PATH="$SCRIPT_DIR/email_job.log"

# Detect compose command
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

# Build a ONE-LINER shell command for cron (no literal newlines!)
RUN_ONE_LINER="cd \"$SCRIPT_DIR\" && ( $COMPOSE_CMD ps --services --filter status=running | grep -qx \"$DOCKER_SERVICE\" && $COMPOSE_CMD exec -T \"$DOCKER_SERVICE\" $CONTAINER_PYTHON \"$CONTAINER_SCRIPT_PATH\" || $COMPOSE_CMD run --rm --no-deps \"$DOCKER_SERVICE\" $CONTAINER_PYTHON \"$CONTAINER_SCRIPT_PATH\" )"

# Properly shell-escape the command for bash -lc
# printf %q produces a safely quoted string suitable for sh
ESCAPED_RUN_CMD=$(printf "%q" "$RUN_ONE_LINER")

# Final single-line cron job
CRON_JOB="$CRON_TIME /usr/bin/env PATH=$CRON_PATH bash -lc $ESCAPED_RUN_CMD >> \"$LOG_PATH\" 2>&1"

# Install (idempotent)
if crontab -l 2>/dev/null | grep -F "$CONTAINER_SCRIPT_PATH" >/dev/null; then
  echo "✅ Cron job already exists for $CONTAINER_SCRIPT_PATH"
else
  (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
  echo "🚀 Added new cron job:"
  echo "$CRON_JOB"
fi

echo
echo "📅 Current cron jobs:"
crontab -l
