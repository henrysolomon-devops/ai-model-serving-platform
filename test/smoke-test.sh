#!/usr/bin/env bash
# Checks both health endpoints, then sends a real prompt to the model and
# another one through the chat UI, and confirms the answers look right.
# Run by smoke-test.yml once staging has synced, or by hand against either
# environment.
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "Usage: $0 <staging|production> <server-ip> <api-key>"
  exit 1
fi

ENVIRONMENT="$1"
SERVER_IP="$2"
API_KEY="$3"

if [ "$ENVIRONMENT" = "staging" ]; then
  UI_PORT=8001
elif [ "$ENVIRONMENT" = "production" ]; then
  UI_PORT=8002
else
  echo "Environment must be 'staging' or 'production'."
  exit 1
fi

# The model has no port of its own. It is reached through the gateway, and
# KServe routes by host name: <model>-<namespace>.example.com.
GATEWAY_PORT=8003
MODEL_HOST="model-service-${ENVIRONMENT}.example.com"

echo "Checking model health through the gateway on port ${GATEWAY_PORT}..."
curl -sf --max-time 30 -H "Host: ${MODEL_HOST}" "http://${SERVER_IP}:${GATEWAY_PORT}/health" > /dev/null

echo "Checking chat UI health on port ${UI_PORT}..."
curl -sf --max-time 30 "http://${SERVER_IP}:${UI_PORT}/health" > /dev/null

echo "Sending a real prompt to the model..."
# The first request can be slow while vLLM compiles its kernels.
RESPONSE=$(curl -sf --max-time 300 -X POST "http://${SERVER_IP}:${GATEWAY_PORT}/v1/chat/completions" \
  -H "Host: ${MODEL_HOST}" \
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
CONTENT=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['choices'][0]['message']['content'])" 2>/dev/null) || true

if [ -z "$CONTENT" ]; then
  echo "Smoke test failed: no usable completion in the response:"
  echo "$RESPONSE"
  exit 1
fi
echo "The model replied: \"$CONTENT\""

# The way a user gets an answer: chat UI, then the cluster's route, then the
# gateway, then the model.
echo "Sending a prompt through the chat UI..."
CHAT_RESPONSE=$(curl -s --max-time 120 -X POST "http://${SERVER_IP}:${UI_PORT}/chat" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Say hello in one short sentence."}]}') || true

CHAT_REPLY=$(echo "$CHAT_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['reply'])" 2>/dev/null) || true

if [ -z "$CHAT_REPLY" ]; then
  echo "Smoke test failed: the chat UI gave no usable reply:"
  echo "$CHAT_RESPONSE"
  exit 1
fi
echo "Smoke test passed. The chat UI replied: \"$CHAT_REPLY\""
