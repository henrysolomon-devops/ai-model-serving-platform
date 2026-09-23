# State lives in its own S3 bucket.
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
