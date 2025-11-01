#!/bin/bash
#
# Sets up a cron job to run a Python script every 5 minutes (for testing).
# Resolves the Python script path dynamically relative to this file.

# ====== CONFIGURATION ======
PYTHON_PATH=$(which python3)       # Auto-detect Python

# Directory of this setup script (resolves symlinks too)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Path to your Python script relative to this shell script
RELATIVE_SCRIPT_PATH="app/email_job.py"  # <-- adjust if needed

# Compute the absolute path
SCRIPT_PATH="$(realpath "$SCRIPT_DIR/$RELATIVE_SCRIPT_PATH")"

# Log file (stored in same folder or nearby)
LOG_PATH="$SCRIPT_DIR/email_job.log"

CRON_TIME="*/5 * * * *"           # Every 5 minutes for testing
# ============================

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_PATH")"

# Make sure the script is executable
chmod +x "$SCRIPT_PATH"

# Define the cron job line
CRON_JOB="$CRON_TIME $PYTHON_PATH $SCRIPT_PATH >> $LOG_PATH 2>&1"

# Check if this job already exists in crontab
(crontab -l 2>/dev/null | grep -F "$SCRIPT_PATH" > /dev/null)

if [ $? -eq 0 ]; then
    echo "✅ Cron job already exists for $SCRIPT_PATH"
else
    # Add the cron job
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "🚀 Added new cron job:"
    echo "$CRON_JOB"
fi

# Display current crontab
echo
echo "📅 Current cron jobs:"
crontab -l
