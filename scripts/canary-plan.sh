#!/usr/bin/env bash
# Decides whether a canary step may run right now. If it may, it prints the
# image tag to release and whether the canary has to be started first, as
# key=value lines. If not, it says why and exits with an error.
# Needs gh and a GH_TOKEN that can read commit statuses.
set -euo pipefail

WEIGHT="${1:-}"
STAGING="${STAGING_VALUES:-helm/ai-model-serving/values-staging.yaml}"
PRODUCTION="${PRODUCTION_VALUES:-helm/ai-model-serving/values-production.yaml}"
CANARY="${CANARY_VALUES:-helm/ai-model-serving/values-production-canary.yaml}"

fail() {
  echo "::error::$*" >&2
  exit 1
}

# The steps go 10, then 50, then 100. Each one needs the one before it approved.
case "$WEIGHT" in
  10)
    previous=""
    later="canary-weight-50 canary-weight-100"
    ;;
  50)
    previous="canary-weight-10"
    later="canary-weight-100"
    ;;
  100)
    previous="canary-weight-50"
    later=""
    ;;
  *) fail "The weight must be 10, 50 or 100." ;;
esac

tags() { sed -n 's/^    tag: "\(.*\)"$/\1/p' "$1" | sort -u; }

staging=$(tags "$STAGING")
if [ -z "$staging" ] || [ "$(echo "$staging" | wc -l)" -ne 1 ]; then
  fail "Staging must have exactly one image tag, refusing to release."
fi
production=$(tags "$PRODUCTION" | paste -sd, -)
if [ "$staging" = "$production" ]; then
  fail "Production already runs ${staging:0:7}, there is nothing to release."
fi

# Results are recorded as commit statuses on the image's commit.
status() {
  gh api "repos/$GITHUB_REPOSITORY/commits/$staging/statuses" \
    --jq "[.[] | select(.context == \"$1\")] | .[0].state // \"none\""
}

if [ "$(status staging-smoke-test)" != "success" ]; then
  fail "${staging:0:7} has no passing staging smoke test. Run the Staging smoke test workflow first."
fi

enabled=$(sed -n 's/^  enabled: \(.*\)$/\1/p' "$CANARY")
running=$(sed -n 's/^    tag: "\(.*\)"$/\1/p' "$CANARY")

if [ "$enabled" = "true" ] && [ "$running" != "$staging" ]; then
  fail "The canary is still running ${running:0:7}. Finish or roll back that release first."
fi
if [ "$WEIGHT" != "10" ] && [ "$enabled" != "true" ]; then
  fail "The canary is not running. Start with weight 10."
fi
if [ -n "$previous" ] && [ "$(status "$previous")" != "success" ]; then
  fail "Run and approve $previous first."
fi
for context in $later; do
  if [ "$(status "$context")" = "success" ]; then
    fail "$context is already approved, so going back to $WEIGHT is not allowed."
  fi
done

echo "tag=$staging"
if [ "$enabled" = "true" ]; then
  echo "wake=false"
else
  echo "wake=true"
fi
