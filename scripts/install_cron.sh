#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_BIN="$REPO_DIR/.venv/bin"

mkdir -p "$REPO_DIR/out"

CRON_FILE="/tmp/jobbot_cron"
cat << EOF > "$CRON_FILE"
CRON_TZ=Asia/Kolkata
# Daily scrape+rank+tailor+digest — 08:45 IST, Mon-Fri
45 8 * * 1-5 cd $REPO_DIR && flock -n .cron.lock $VENV_BIN/jobbot daily >> out/cron.log 2>&1

# Send approved applications — every hour 10:30–16:30 IST, Mon-Fri
30 10-16 * * 1-5 cd $REPO_DIR && flock -n .send.lock $VENV_BIN/jobbot send --limit 6 >> out/cron.log 2>&1

# Weekly report — Friday 18:00 IST
0 18 * * 5 cd $REPO_DIR && $VENV_BIN/jobbot report --week >> out/cron.log 2>&1
EOF

crontab "$CRON_FILE"
rm "$CRON_FILE"
echo "JobBot crontab successfully installed."
crontab -l
