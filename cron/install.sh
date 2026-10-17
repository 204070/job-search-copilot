#!/usr/bin/env bash
# Install (or refresh) the daily-scan crontab entry. Idempotent: removes any
# previous version of this line first, and backs up the crontab before
# changing it. Schedule: 06:30 daily, machine local time.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
marker="# job-search-copilot daily scan (managed by cron/install.sh)"
line="30 6 * * * $here/daily_scan.sh >> $here/../logs/scan.log 2>&1"
tmp="$(mktemp)"
backup="$here/crontab.backup.$(date +%Y%m%d%H%M%S)"

crontab -l > "$backup" 2>/dev/null || true
{ crontab -l 2>/dev/null || true; } \
  | awk -v m="$marker" -v p="$here/daily_scan.sh" \
        'index($0, m) != 1 && index($0, p) == 0 { print }' > "$tmp"
printf '%s\n%s\n' "$marker" "$line" >> "$tmp"
crontab "$tmp"
rm -f "$tmp"

echo "Installed. Backup of previous crontab: $backup"
crontab -l | tail -3
