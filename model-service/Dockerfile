# CUDA base matching the host driver. vLLM pulls its own PyTorch/CUDA
# wheels via pip, so nothing here needs building from source.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip curl unzip \
    && rm -rf /var/lib/apt/lists/*

# AWS CLI for entrypoint.sh's S3 weight caching. No credentials baked
# in, the EC2 instance profile supplies them at runtime.
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" \
    && unzip awscliv2.zip && ./aws/install && rm -rf awscliv2.zip aws

RUN pip3 install --no-cache-dir vllm "huggingface_hub[cli]"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
