# AI Model Serving Platform

GPU-aware AI model serving on Kubernetes, built with Terraform, Ansible, Helm, and GitHub Actions.

## Why this project

This is a companion project to [devops-cicd-pipeline](https://github.com/henrysolomon-devops/devops-cicd-pipeline), which built a full DevOps toolchain against an ordinary Flask web app. This project points that same toolchain at a completely different kind of workload: an AI model running on a GPU. The model itself is never trained or fine-tuned here. The job is entirely infrastructure: getting a model served reliably, scheduled onto the right GPU, and rolled out through the same kind of pipeline a Platform or Infrastructure Engineer would build the day their product team says "we need to run an LLM in production."

Each version of this project adds one thing that exists specifically because the workload is an AI model on a GPU, not because it pads out a roadmap. Full details for each version, including architecture diagrams and screenshots, live in its own file under `docs/`.

## Tech stack

- **Infrastructure:** Terraform, AWS (EC2, IAM, S3)
- **Configuration:** Ansible
- **Orchestration:** Kubernetes (k3s), Helm
- **Model serving:** vLLM, Llama-3.2-3B-Instruct
- **CI/CD:** GitHub Actions, OIDC (no stored AWS credentials)
- **GitOps:** Argo CD
- **App layer:** Flask (chat UI)

## Roadmap

| Version | What it adds | Status |
|---|---|---|
| v1 | GPU Kubernetes cluster, vLLM model service, chat UI, manual apply/deploy/test | ✅ Done ([details](docs/v1-gpu-model-service.md)) |
| v2 | GitHub Actions CI, Argo CD GitOps, automated smoke test gating promotion | ✅ Done ([details](docs/v2-cicd-gitops.md)) |
| v3 | DCGM + Prometheus + Grafana for GPU/model observability | Planned |
| v4 | KServe (RawDeployment mode), canary rollout with automated analysis | Planned |

## License

MIT
