#!/usr/bin/env bash
# Checks both health endpoints, then sends a real prompt and confirms
# the model's response looks right. Run by smoke-test.yml once staging
# has synced, or by hand against either environment.
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
curl -sf --max-time 30 "http://${SERVER_IP}:${MODEL_PORT}/health" > /dev/null

echo "Checking chat UI health on port ${UI_PORT}..."
curl -sf --max-time 30 "http://${SERVER_IP}:${UI_PORT}/health" > /dev/null

echo "Sending a real prompt to the model..."
# The first request can be slow while vLLM compiles its kernels.
RESPONSE=$(curl -sf --max-time 300 -X POST "http://${SERVER_IP}:${MODEL_PORT}/v1/chat/completions" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama-3.2-3b-instruct",
    "messages": [{"role": "user", "content": "Say hello in one short sentence."}],
    "max_tokens": 30
  }')

# A small model won't always follow word tricks exactly (it might
# answer "Peel." to "say banana"), so this checks that a real,
# non-empty completion came back, not the exact wording.
CONTENT=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['choices'][0]['message']['content'])" 2>/dev/null)

if [ -n "$CONTENT" ]; then
  echo "Smoke test passed. Model replied: \"$CONTENT\""
else
  echo "Smoke test failed: no usable completion in the response:"
  echo "$RESPONSE"
  exit 1
fi
