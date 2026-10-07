#!/usr/bin/env bash
# Decides whether the image on staging may be promoted to production. If it
# may, it prints the new and the old tag as key=value lines. If not, it says
# why and exits with an error.
# Needs gh and a GH_TOKEN that can read commit statuses.
set -euo pipefail

STAGING="${STAGING_VALUES:-helm/ai-model-serving/values-staging.yaml}"
PRODUCTION="${PRODUCTION_VALUES:-helm/ai-model-serving/values-production.yaml}"
CANARY="${CANARY_VALUES:-helm/ai-model-serving/values-production-canary.yaml}"

fail() {
  echo "::error::$*" >&2
  exit 1
}

tags() { sed -n 's/^    tag: "\(.*\)"$/\1/p' "$1" | sort -u; }

staging=$(tags "$STAGING")
if [ -z "$staging" ] || [ "$(echo "$staging" | wc -l)" -ne 1 ]; then
  fail "Staging must have exactly one image tag, refusing to promote."
fi
production=$(tags "$PRODUCTION" | paste -sd, -)
if [ "$staging" = "$production" ]; then
  fail "Production already runs ${staging:0:7}, there is nothing to promote."
fi

# The full canary run must be done: approved at 100 percent, and live in Git.
state=$(gh api "repos/$GITHUB_REPOSITORY/commits/$staging/statuses" \
  --jq '[.[] | select(.context == "canary-weight-100")] | .[0].state // "none"')
if [ "$state" != "success" ]; then
  fail "${staging:0:7} has not passed the canary at 100 percent (result: $state). Run the Canary step workflow first."
fi

enabled=$(sed -n 's/^  enabled: \(.*\)$/\1/p' "$CANARY")
weight=$(sed -n 's/^  weight: \(.*\)$/\1/p' "$CANARY")
running=$(sed -n 's/^    tag: "\(.*\)"$/\1/p' "$CANARY")
if [ "$enabled" != "true" ] || [ "$weight" != "100" ] || [ "$running" != "$staging" ]; then
  fail "The canary is not at 100 percent on ${staging:0:7} right now. Run the Canary step workflow again."
fi

echo "tag=$staging"
echo "old=$production"
