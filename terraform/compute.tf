# Import a locally generated public key instead of letting AWS create
# one. The private half never has to touch AWS at all.
resource "aws_key_pair" "ai_model_serving" {
  key_name   = "ai-model-serving-key"
  public_key = file(var.public_key_path)
}

# Ships with the NVIDIA driver, Docker, and NVIDIA Container Toolkit
# already installed. Pinned to the exact image the cluster was tested
# with, so a new release can't change the driver between sessions. AWS
# retires old images after a while, so refresh this name every few months.
data "aws_ami" "deep_learning" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04) 20260929"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Three nodes with one T4 each: the control plane hosts staging, the
# worker hosts production, and the canary node hosts the canary during
# a release. g4dn.xlarge keeps it at 12 vCPUs, well inside the GPU quota
# of 24. On-demand, so a node never disappears mid-test.
resource "aws_instance" "control_plane" {
  ami                    = data.aws_ami.deep_learning.id
  instance_type          = "g4dn.xlarge"
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.server.id]
  key_name               = aws_key_pair.ai_model_serving.key_name

  # Manually created in AWS Console, not managed by Terraform, since
  # it's a stable one-time role like the GitHub OIDC role.
  iam_instance_profile = "ai-model-serving-ec2-weights-access"

  # Lets pods reach the instance credentials. With the default of 1 the
  # extra network hop inside a pod is blocked, and Loki cannot get into S3.
  metadata_options {
    http_put_response_hop_limit = 2
  }

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

  metadata_options {
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_size = 100
    volume_type = "gp3"
  }

  tags = {
    Name = "ai-model-serving-worker"
  }
}

resource "aws_instance" "canary" {
  ami                    = data.aws_ami.deep_learning.id
  instance_type          = "g4dn.xlarge"
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.server.id]
  key_name               = aws_key_pair.ai_model_serving.key_name
  iam_instance_profile   = "ai-model-serving-ec2-weights-access"

  metadata_options {
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_size = 100
    volume_type = "gp3"
  }

  tags = {
    Name = "ai-model-serving-canary"
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

resource "aws_eip" "canary" {
  instance = aws_instance.canary.id
  domain   = "vpc"

  tags = {
    Name = "ai-model-serving-canary-eip"
  }
}
