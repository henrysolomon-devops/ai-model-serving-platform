# CUDA runtime base, matched to the driver the Deep Learning AMI
# already installs on the host. vLLM ships as a pip package and pulls
# in the matching PyTorch/CUDA wheels itself, so nothing here needs to
# be built from source.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# build-essential and python3-dev are needed at runtime, not just
# build time: vLLM's torch.compile backend (Triton) compiles CUDA
# kernels on the fly on first request, using both a C compiler and
# both the standard C headers and the Python C headers (Python.h),
# none of which this minimal "runtime" CUDA base image ships by default.
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-dev curl unzip build-essential \
    && rm -rf /var/lib/apt/lists/*

# AWS CLI, used only by entrypoint.sh to sync cached model weights
# to/from S3. No credentials baked in here: the EC2 instance itself
# carries an IAM instance profile, so the CLI picks up temporary
# credentials from the instance metadata service automatically.
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" \
    && unzip awscliv2.zip && ./aws/install && rm -rf awscliv2.zip aws

RUN pip3 install --no-cache-dir vllm "huggingface_hub[cli]"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
