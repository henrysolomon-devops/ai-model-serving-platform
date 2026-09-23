# State lives in its own S3 bucket, separate from devops-cicd-pipeline's,
# so the two projects never share a state file or step on each other.
terraform {
  backend "s3" {
    bucket = "ai-model-serving-platform-tfstate"
    key    = "ai-model-serving-platform/terraform.tfstate"
    region = "us-east-1"

    # Terraform 1.10+ handles state locking natively through S3's
    # conditional writes, so no separate DynamoDB table is needed.
    use_lockfile = true
  }
}
