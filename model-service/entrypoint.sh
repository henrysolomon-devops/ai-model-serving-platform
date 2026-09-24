#!/usr/bin/env bash
# Checks local disk, then S3 cache, then falls back to Hugging Face,
# caching each fresh download back to S3 for the next run.
set -euo pipefail

MODEL_ID="meta-llama/Llama-3.2-3B-Instruct"
MODEL_DIR="/models/Llama-3.2-3B-Instruct"
S3_PREFIX="s3://${WEIGHTS_BUCKET}/Llama-3.2-3B-Instruct/"

mkdir -p "${MODEL_DIR}"

if [ ! -f "${MODEL_DIR}/config.json" ]; then
  echo "Not on local disk, checking the S3 cache..."
  aws s3 sync "${S3_PREFIX}" "${MODEL_DIR}" --only-show-errors || true
fi

if [ ! -f "${MODEL_DIR}/config.json" ]; then
  echo "Not cached in S3 either, downloading from Hugging Face..."
  huggingface-cli download "${MODEL_ID}" \
    --local-dir "${MODEL_DIR}" \
    --token "${HF_TOKEN}"

  echo "Caching this download to S3 so the next run doesn't repeat it..."
  aws s3 sync "${MODEL_DIR}" "${S3_PREFIX}" --only-show-errors
else
  echo "Using weights already present (local disk or S3 cache)."
fi

# Tuned for a single T4's 16GB, not the model's full default, since
# each environment gets exactly one T4, not a whole free card.
exec vllm serve "${MODEL_DIR}" \
  --host 0.0.0.0 \
  --port 8000 \
  --served-model-name llama-3.2-3b-instruct \
  --api-key "${API_KEY}" \
  --gpu-memory-utilization 0.90 \
  --max-model-len 8192
