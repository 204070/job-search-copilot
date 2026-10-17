#!/usr/bin/env bash
# Daily job-board scan. Invoked by cron (see cron/install.sh).
# Writes the lead report to logs/leads/YYYY-MM-DD.md; stdout/stderr go
# to the log file configured in the crontab line.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p logs/leads
exec python3 -m scanner
