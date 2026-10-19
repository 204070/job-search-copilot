#!/usr/bin/env bash
# Install (or refresh) the daily-scan crontab entry, or take it back out with
# --remove. Both are idempotent: the managed line is matched by its marker and
# by the script path, so a previous version (or a hand-edited one) is replaced
# rather than duplicated, and every run backs up the crontab first.
#
#   cron/install.sh            # schedule 06:30 daily, machine local time
#   cron/install.sh --remove   # unschedule; runs become hand-triggered
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

if [ "${1:-}" = "--remove" ]; then
  crontab "$tmp"
  action="Removed"
else
  printf '%s\n%s\n' "$marker" "$line" >> "$tmp"
  crontab "$tmp"
  action="Installed"
fi
rm -f "$tmp"

echo "$action. Backup of previous crontab: $backup"
echo "Crontab now:"
crontab -l 2>/dev/null | tail -3 || echo "  (empty)"
