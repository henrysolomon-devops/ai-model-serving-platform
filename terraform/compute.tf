# Import a locally generated public key instead of letting AWS create
# one. The private half never has to touch AWS at all.
resource "aws_key_pair" "ai_model_serving" {
  key_name   = "ai-model-serving-key"
  public_key = file(var.public_key_path)
}

# Ships with the NVIDIA driver, Docker, and NVIDIA Container Toolkit
# already installed. Always grab the latest one instead of hardcoding
# an AMI ID, since the name carries a release date and a hardcoded ID
# would go stale.
data "aws_ami" "deep_learning" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# g4dn.12xlarge gives 4 physical T4 GPUs, one dedicated GPU per
# environment (staging, production, and a canary revision later).
# Requested as spot since this server only runs a few hours per
# version before being destroyed.
resource "aws_instance" "server" {
  ami                    = data.aws_ami.deep_learning.id
  instance_type          = "g4dn.12xlarge"
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.server.id]
  key_name               = aws_key_pair.ai_model_serving.key_name

  # Manually created in AWS Console, not managed by Terraform, since
  # it's a stable one-time role like the GitHub OIDC role.
  iam_instance_profile = "ai-model-serving-ec2-weights-access"

  instance_market_options {
    market_type = "spot"
    spot_options {
      instance_interruption_behavior = "terminate"
      spot_instance_type             = "one-time"
    }
  }

  # The Deep Learning AMI ships with a large preinstalled toolset, so
  # the root volume needs more room than the 8GB default.
  root_block_device {
    volume_size = 100
    volume_type = "gp3"
  }

  tags = {
    Name = "ai-model-serving-server"
  }
}

# A static IP that stays locked to the instance across every
# apply/destroy cycle, so it doesn't need chasing down again each time.
resource "aws_eip" "server" {
  instance = aws_instance.server.id
  domain   = "vpc"

  tags = {
    Name = "ai-model-serving-eip"
  }
}
