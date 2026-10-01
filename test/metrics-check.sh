#!/usr/bin/env bash
# Checks the metrics around the smoke test prompt. Run "before", then the
# smoke test, then "after". Needs kubectl pointed at the cluster and python3.
set -euo pipefail

if [ $# -ne 3 ] || { [ "$1" != "before" ] && [ "$1" != "after" ]; }; then
  echo "Usage: $0 <before|after> <staging|production> <state-file>"
  exit 1
fi

MODE="$1"
ENVIRONMENT="$2"
STATE_FILE="$3"

if [ "$ENVIRONMENT" != "staging" ] && [ "$ENVIRONMENT" != "production" ]; then
  echo "Environment must be 'staging' or 'production'."
  exit 1
fi

# Prometheus is reached through the Kubernetes API server, so no extra
# port has to be opened.
PROM="/api/v1/namespaces/monitoring/services/monitoring-kube-prometheus-prometheus:http-web/proxy"

# Seconds to wait for the model to be scraped, then for the new request to show up.
TARGET_WAIT=900
POLL_WAIT=300
INTERVAL=10
# vLLM reserves most of the GPU at startup, so this much memory in use
# means the model is really loaded on it.
MIN_GPU_MIB=8000

# Prints the first value of an instant query, or nothing if there is none.
query() {
  local encoded
  encoded=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$1")
  kubectl get --raw "${PROM}/api/v1/query?query=${encoded}" 2> /dev/null | python3 -c '
import json, sys
try:
    result = json.load(sys.stdin)["data"]["result"]
    value = result[0]["value"][1] if result else ""
    print("" if value in ("NaN", "+Inf", "-Inf") else value)
except Exception:
    pass
' || true
}

# True when the first number is greater than the second.
greater() {
  python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) > float(sys.argv[2]) else 1)' "$1" "$2"
}

# Runs a command every few seconds until it succeeds or the time is up.
wait_until() {
  local seconds="$1" what="$2"
  shift 2
  local deadline=$((SECONDS + seconds))
  until "$@"; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "Gave up waiting for ${what}."
      return 1
    fi
    sleep "$INTERVAL"
  done
}

SUCCESS_TOTAL="sum(vllm:request_success_total{namespace=\"${ENVIRONMENT}\"}) or vector(0)"
GPU_MEMORY="max(DCGM_FI_DEV_FB_USED{namespace=\"${ENVIRONMENT}\"})"

# Metrics the alert rules and the dashboard use. Keep this list in step with
# them: a renamed metric would leave panels empty and alerts quiet.
EXPECTED_METRICS=(
  "vllm:kv_cache_usage_perc"
  "vllm:num_requests_waiting"
  "vllm:e2e_request_latency_seconds_count"
  "DCGM_FI_DEV_GPU_TEMP"
  "chat_requests_total"
)
MISSING=()

target_is_up() {
  [ "$(query "up{job=\"model-service\", namespace=\"${ENVIRONMENT}\"}")" = "1" ]
}

requests_went_up() {
  local now
  now=$(query "$SUCCESS_TOTAL")
  [ -n "$now" ] && greater "$now" "$BEFORE"
}

has_value() {
  [ -n "$(query "$1")" ]
}

# True when every expected metric exists. Fills MISSING with the ones that do not.
all_metrics_exist() {
  MISSING=()
  local metric
  for metric in "${EXPECTED_METRICS[@]}"; do
    has_value "count(${metric}{namespace=\"${ENVIRONMENT}\"})" || MISSING+=("$metric")
  done
  [ "${#MISSING[@]}" -eq 0 ]
}

if [ "$MODE" = "before" ]; then
  echo "Waiting for Prometheus to scrape the ${ENVIRONMENT} model..."
  wait_until "$TARGET_WAIT" "Prometheus to scrape the ${ENVIRONMENT} model" target_is_up

  BEFORE=$(query "$SUCCESS_TOTAL")
  if [ -z "$BEFORE" ]; then
    echo "Prometheus has no request counter for ${ENVIRONMENT}."
    exit 1
  fi
  echo "$BEFORE" > "$STATE_FILE"
  echo "The model has served ${BEFORE} requests so far."
  exit 0
fi

BEFORE=$(cat "$STATE_FILE")

echo "Waiting for the new request to show up in Prometheus..."
wait_until "$POLL_WAIT" "the request counter to go up from ${BEFORE}" requests_went_up
echo "The request counter went up."

if ! wait_until "$POLL_WAIT" "GPU memory data" has_value "$GPU_MEMORY"; then
  echo "No GPU memory is attributed to ${ENVIRONMENT}. Check that the DCGM exporter maps the GPU to the model pod."
  exit 1
fi
GPU=$(query "$GPU_MEMORY")
if ! greater "$GPU" "$MIN_GPU_MIB"; then
  echo "The GPU is using ${GPU} MiB, less than the ${MIN_GPU_MIB} MiB a loaded model needs."
  exit 1
fi
echo "The GPU is using ${GPU} MiB."

if ! wait_until "$POLL_WAIT" "all expected metrics" all_metrics_exist; then
  echo "These metrics are missing for ${ENVIRONMENT}: ${MISSING[*]}"
  echo "Dashboard panels and alerts that use them would stay empty or quiet."
  exit 1
fi
echo "All the metrics the dashboard and alerts use are there."
echo "Metrics check passed."
