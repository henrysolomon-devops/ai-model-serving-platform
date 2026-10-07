#!/usr/bin/env bash
# Decides whether a release has to be finished after production moved to a
# new image. Prints act=true or act=false, and the tag, as key=value lines.
set -euo pipefail

PRODUCTION="${PRODUCTION_VALUES:-helm/ai-model-serving/values-production.yaml}"
CANARY="${CANARY_VALUES:-helm/ai-model-serving/values-production-canary.yaml}"

tags() { sed -n 's/^    tag: "\(.*\)"$/\1/p' "$1" | sort -u; }

production=$(tags "$PRODUCTION" | paste -sd, -)
enabled=$(sed -n 's/^  enabled: \(.*\)$/\1/p' "$CANARY")
running=$(sed -n 's/^    tag: "\(.*\)"$/\1/p' "$CANARY")

if [ "$enabled" != "true" ]; then
  echo "::notice::No canary is running, so there is no release to finish." >&2
  echo "act=false"
elif [ "$running" != "$production" ]; then
  echo "::notice::Production runs ${production:0:7} but the canary runs ${running:0:7}, so this is not the end of a release." >&2
  echo "act=false"
else
  echo "act=true"
fi
echo "tag=$production"
