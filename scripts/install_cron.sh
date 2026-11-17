#!/usr/bin/env bash
set -euo pipefail

CRON_FILE="/tmp/jobbot_cron"
cat << 'EOF' > "$CRON_FILE"
CRON_TZ=Asia/Kolkata
# Daily scrape+rank+tailor+digest — 08:45 IST, Mon-Fri
45 8 * * 1-5 cd /path/to/jobot && flock -n .cron.lock /path/to/jobot/.venv/bin/jobbot daily >> out/cron.log 2>&1

# Send approved applications — every hour 10:30–16:30 IST, Mon-Fri
30 10-16 * * 1-5 cd /path/to/jobot && flock -n .send.lock /path/to/jobot/.venv/bin/jobbot send --limit 6 >> out/cron.log 2>&1

# Weekly report — Friday 18:00 IST
0 18 * * 5 cd /path/to/jobot && /path/to/jobot/.venv/bin/jobbot report --week >> out/cron.log 2>&1
EOF

crontab "$CRON_FILE"
rm "$CRON_FILE"
echo "JobBot crontab successfully installed."
crontab -l
