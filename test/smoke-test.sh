#!/usr/bin/env bash
# Run by hand after each deploy-model.yml run, since there's no CI/CD
# to automate this yet (that's v2). Checks both health endpoints, then
# sends a real prompt and confirms the model's response looks right.
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "Usage: $0 <staging|production> <server-ip> <api-key>"
  exit 1
fi

ENVIRONMENT="$1"
SERVER_IP="$2"
API_KEY="$3"

if [ "$ENVIRONMENT" = "staging" ]; then
  MODEL_PORT=8011
  UI_PORT=8001
elif [ "$ENVIRONMENT" = "production" ]; then
  MODEL_PORT=8012
  UI_PORT=8002
else
  echo "Environment must be 'staging' or 'production'."
  exit 1
fi

echo "Checking model service health on port ${MODEL_PORT}..."
curl -sf "http://${SERVER_IP}:${MODEL_PORT}/health" > /dev/null

echo "Checking chat UI health on port ${UI_PORT}..."
curl -sf "http://${SERVER_IP}:${UI_PORT}/health" > /dev/null

echo "Sending a real prompt to the model..."
RESPONSE=$(curl -sf -X POST "http://${SERVER_IP}:${MODEL_PORT}/v1/chat/completions" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama-3.2-3b-instruct",
    "messages": [{"role": "user", "content": "Reply with exactly one word: banana."}],
    "max_tokens": 10
  }')

if echo "$RESPONSE" | grep -qi "banana"; then
  echo "Smoke test passed: model responded sensibly."
else
  echo "Smoke test failed: unexpected response:"
  echo "$RESPONSE"
  exit 1
fi
