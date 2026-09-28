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

# Two nodes with one T4 each: the control plane hosts staging and the
# worker hosts production, so each environment gets its own GPU.
# g4dn.xlarge because the account's GPU vCPU quota is 8, which fits
# exactly two of them. On-demand, so a node never disappears mid-test.
resource "aws_instance" "control_plane" {
  ami                    = data.aws_ami.deep_learning.id
  instance_type          = "g4dn.xlarge"
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.server.id]
  key_name               = aws_key_pair.ai_model_serving.key_name

  # Manually created in AWS Console, not managed by Terraform, since
  # it's a stable one-time role like the GitHub OIDC role.
  iam_instance_profile = "ai-model-serving-ec2-weights-access"

  # The Deep Learning AMI ships with a large preinstalled toolset, so
  # the root volume needs more room than the 8GB default.
  root_block_device {
    volume_size = 100
    volume_type = "gp3"
  }

  tags = {
    Name = "ai-model-serving-control-plane"
  }
}

resource "aws_instance" "worker" {
  ami                    = data.aws_ami.deep_learning.id
  instance_type          = "g4dn.xlarge"
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.server.id]
  key_name               = aws_key_pair.ai_model_serving.key_name
  iam_instance_profile   = "ai-model-serving-ec2-weights-access"

  root_block_device {
    volume_size = 100
    volume_type = "gp3"
  }

  tags = {
    Name = "ai-model-serving-worker"
  }
}

# Static IPs that stay locked to each instance across every
# apply/destroy cycle, so they don't need chasing down again each time.
resource "aws_eip" "control_plane" {
  instance = aws_instance.control_plane.id
  domain   = "vpc"

  tags = {
    Name = "ai-model-serving-control-plane-eip"
  }
}

resource "aws_eip" "worker" {
  instance = aws_instance.worker.id
  domain   = "vpc"

  tags = {
    Name = "ai-model-serving-worker-eip"
  }
}
