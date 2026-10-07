#!/usr/bin/env bash
# Edits the release state file and sends the change through a pull request.
#   canary-state.sh write <on|off> <weight> <tag>
#   canary-state.sh pr <branch> <title>
#   canary-state.sh close-open
#   canary-state.sh running <tag>
# "pr" needs git and gh, and a GH_TOKEN that may open and merge pull requests.
# It waits until the pull request is merged and leaves the checkout on the
# new main. "close-open" closes pull requests from earlier canary runs that
# are still open, so a half finished one can not merge later. "running"
# succeeds only if the canary is on for that tag. If GITHUB_OUTPUT is set, the pull request number goes there as pr.
set -euo pipefail

STATE_FILE="${CANARY_VALUES:-helm/ai-model-serving/values-production-canary.yaml}"
WAIT_SECONDS="${PR_WAIT_SECONDS:-900}"
POLL_SECONDS="${PR_POLL_SECONDS:-10}"

write_state() {
  local mode="$1" weight="$2" tag="$3" enabled=false
  case "$weight" in
    '' | *[!0-9]*)
      echo "The weight must be a whole number."
      exit 1
      ;;
  esac
  if [ "$weight" -gt 100 ]; then
    echo "The weight can not be more than 100."
    exit 1
  fi
  if [ "$mode" = "on" ]; then
    enabled=true
    if [ -z "$tag" ]; then
      echo "A running canary needs an image tag."
      exit 1
    fi
  elif [ "$mode" != "off" ]; then
    echo "The mode must be on or off."
    exit 1
  fi
  cat > "$STATE_FILE" << YAML
# The state of the current release. Only the canary workflows edit this file.
canary:
  enabled: ${enabled}
  weight: ${weight}
  image:
    tag: "${tag}"
YAML
}

open_pr() {
  local branch="$1" title="$2" url number state
  if git diff --quiet -- "$STATE_FILE"; then
    echo "The release state is already what it should be, no pull request needed."
    return 0
  fi

  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git checkout -q -b "$branch"
  git commit -q -am "$title"
  git push -q origin "$branch"

  url=$(gh pr create --base main --head "$branch" --title "$title" \
    --body "${PR_BODY:-Automated change to the release state.}")
  number="${url##*/}"
  echo "Opened pull request #${number}."
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "pr=${number}" >> "$GITHUB_OUTPUT"
  fi
  gh pr merge "$branch" --auto --squash

  local deadline=$((SECONDS + WAIT_SECONDS))
  until state=$(gh pr view "$branch" --json state --jq .state) && [ "$state" = "MERGED" ]; do
    if [ "${state:-}" = "CLOSED" ]; then
      echo "::error::Pull request #${number} was closed without being merged."
      exit 1
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "::error::Pull request #${number} was not merged in time. Check that CI passed."
      exit 1
    fi
    sleep "$POLL_SECONDS"
  done
  echo "Pull request #${number} is merged."

  git fetch -q origin main
  git checkout -q -B main origin/main
}

close_open() {
  gh pr list --state open --json number,headRefName \
    --jq '.[] | select(.headRefName | startswith("bot/canary-")) | .number' |
    while read -r n; do
      gh pr close "$n" --delete-branch --comment "Closed because the release was stopped."
    done
}

is_running() {
  local enabled running
  enabled=$(sed -n 's/^  enabled: \(.*\)$/\1/p' "$STATE_FILE")
  running=$(sed -n 's/^    tag: "\(.*\)"$/\1/p' "$STATE_FILE")
  [ "$enabled" = "true" ] && [ -n "$1" ] && [ "$running" = "$1" ]
}

case "${1:-}" in
  write)
    [ $# -eq 4 ] || { echo "Usage: $0 write <on|off> <weight> <tag>"; exit 2; }
    write_state "$2" "$3" "$4"
    ;;
  pr)
    [ $# -eq 3 ] || { echo "Usage: $0 pr <branch> <title>"; exit 2; }
    open_pr "$2" "$3"
    ;;
  close-open)
    close_open
    ;;
  running)
    [ $# -eq 2 ] || { echo "Usage: $0 running <tag>"; exit 2; }
    is_running "$2"
    ;;
  *)
    echo "Usage: $0 write <on|off> <weight> <tag>"
    echo "       $0 pr <branch> <title>"
    echo "       $0 close-open"
    echo "       $0 running <tag>"
    exit 2
    ;;
esac
