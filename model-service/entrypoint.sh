#!/usr/bin/env bash
# Loads Llama-3.2-3B-Instruct from S3 if it's already cached there
# from a previous run, otherwise downloads it from Hugging Face (using
# a gated-model token) and uploads it to S3 so the next run skips the
# download entirely. Then hands off to vLLM to actually serve it.
#
# A cold start can take ten minutes or more and used to be silent. Every
# step below now logs a timestamp and how long it took, so the log panel
# in Grafana shows where a slow start is spending its time.
set -euo pipefail

MODEL_ID="meta-llama/Llama-3.2-3B-Instruct"
MODEL_DIR="${MODEL_DIR:-/models/Llama-3.2-3B-Instruct}"
S3_PREFIX="s3://${WEIGHTS_BUCKET}/Llama-3.2-3B-Instruct/"

# Plain text only: a UTC time and a message. Never print the tokens or
# keys this script is given.
log() {
  printf '[entrypoint %s] %s\n' "$(date -u +%H:%M:%S)" "$*"
}

START=$SECONDS
log "Starting up. Model: ${MODEL_ID}, weights bucket: ${WEIGHTS_BUCKET}"

mkdir -p "${MODEL_DIR}"

# The marker is written only after a full download and upload. A cache
# with config.json but no marker is a half finished one and is not used.
MARKER="${MODEL_DIR}/.complete"

if [ ! -f "${MARKER}" ]; then
  log "Weights are not on local disk, checking the S3 cache..."
  step=$SECONDS
  aws s3 sync "${S3_PREFIX}" "${MODEL_DIR}" --only-show-errors || true
  log "S3 cache check finished in $((SECONDS - step))s."
fi

if [ ! -f "${MARKER}" ]; then
  log "No complete copy in S3 either, downloading from Hugging Face..."
  step=$SECONDS
  hf download "${MODEL_ID}" \
    --local-dir "${MODEL_DIR}" \
    --token "${HF_TOKEN}"
  log "Hugging Face download finished in $((SECONDS - step))s."

  log "Caching this download to S3 so the next run doesn't repeat it..."
  step=$SECONDS
  aws s3 sync "${MODEL_DIR}" "${S3_PREFIX}" --only-show-errors
  touch "${MARKER}"
  aws s3 cp "${MARKER}" "${S3_PREFIX}.complete" --only-show-errors
  log "Upload to S3 finished in $((SECONDS - step))s."
else
  log "Using weights already present (local disk or S3 cache)."
fi

log "Weights are ready after $((SECONDS - START))s. Handing off to vLLM, which still has to load the model and compile kernels."

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
