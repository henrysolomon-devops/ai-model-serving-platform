# The AWS region for everything in this project. Kept as a variable
# instead of hardcoded in provider.tf so it can be overridden later
# without touching the provider config itself.
variable "aws_region" {
  description = "AWS region to deploy resources into"
  type        = string
  default     = "us-east-1"
}

# My own public IP, so SSH, the k3s API, and the app/model ports are
# only reachable from me, not the whole internet. No default on
# purpose, this depends on whoever's running the code, so it has to be
# passed in each time (infra.yml passes it from a repo variable).
variable "my_ip" {
  description = "Your public IP address, for restricting SSH, k3s API, and app/model port access"
  type        = string
}

# Path to the public key generated for this project. The matching
# private key is what Ansible uses to connect and install k3s. This is
# its own separate keypair, not the one from devops-cicd-pipeline.
variable "public_key_path" {
  description = "Path to the local SSH public key file for this project"
  type        = string
  default     = "~/.ssh/ai-model-serving-key.pub"
}
