variable "aws_region" {
  description = "AWS region to deploy resources into"
  type        = string
  default     = "us-east-1"
}

variable "my_ip" {
  description = "Your public IP address, for restricting SSH, k3s API, and app/model port access"
  type        = string
}

variable "public_key_path" {
  description = "Path to the local SSH public key file for this project"
  type        = string
  default     = "~/.ssh/ai-model-serving-key.pub"
}
