#!/usr/bin/env bash
# Compares the canary with production at its current traffic weight.
# Needs kubectl pointed at the cluster, python3, and the gateway reachable
# on port 8003 of the server. Writes a markdown table to canary-report.md,
# or to the file named in CANARY_REPORT. Exits 0 when the canary looks
# healthy and 1 when it does not.
set -euo pipefail

if [ $# -ne 3 ]; then
  echo "Usage: $0 <weight 0-100> <server-ip> <api-key>"
  exit 2
fi

exec python3 "$(dirname "$0")/canary_check.py" "$@"
