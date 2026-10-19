#!/usr/bin/env bash
# Daily job-board scan. Invoked by cron (see cron/install.sh).
# Writes the lead report to logs/leads/YYYY-MM-DD.md; stdout/stderr go
# to the log file configured in the crontab line.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# cron's PATH is minimal, so `opencli` is not on it and the boards read through
# Chrome (HiringCafe, Work at a Startup, X Bookmarks) report "opencli not
# installed" instead of running. This dir holds opencli and node, no
# interpreter, so prepending it only makes the bridge reachable.
export PATH="$HOME/.local/share/vite-plus/bin:$PATH"
mkdir -p logs/leads
exec python3 -m scanner
