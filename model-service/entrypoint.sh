#!/usr/bin/env bash
# Loads Llama-3.2-3B-Instruct from S3 if it's already cached there
# from a previous run, otherwise downloads it from Hugging Face (using
# a gated-model token) and uploads it to S3 so the next run skips the
# download entirely. Then hands off to vLLM to actually serve it.
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
  hf download "${MODEL_ID}" \
    --local-dir "${MODEL_DIR}" \
    --token "${HF_TOKEN}"

  echo "Caching this download to S3 so the next run doesn't repeat it..."
  aws s3 sync "${MODEL_DIR}" "${S3_PREFIX}" --only-show-errors
else
  echo "Using weights already present (local disk or S3 cache)."
fi

# --gpu-memory-utilization and --max-model-len are tuned for a single
# T4's 16GB, not for the full model default, since every environment
# here gets exactly one T4, not the whole card free for one process.
exec vllm serve "${MODEL_DIR}" \
  --host 0.0.0.0 \
  --port 8000 \
  --served-model-name llama-3.2-3b-instruct \
  --api-key "${API_KEY}" \
  --gpu-memory-utilization 0.90 \
  --max-model-len 8192
