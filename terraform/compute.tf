# Importing the public key generated locally instead of letting AWS
# create a new key pair. The private half never has to touch AWS at
# all, only the public half gets uploaded here.
resource "aws_key_pair" "ai_model_serving" {
  key_name   = "ai-model-serving-key"
  public_key = file(var.public_key_path)
}

# The AWS Deep Learning Base OSS Nvidia Driver GPU AMI ships with the
# NVIDIA driver, Docker, and the NVIDIA Container Toolkit already
# installed, so there's no separate driver-install step for Ansible to
# handle. Confirmed via `aws ec2 describe-images` rather than guessed,
# since Quick Start AMI Catalog defaults to the Neuron variant (for
# AWS's own Inferentia/Trainium chips), not the NVIDIA one this
# project actually needs. Always grabbing the latest one instead of
# hardcoding an AMI ID, since these get updated regularly (the name
# even carries a release date) and a hardcoded ID would go stale.
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

# The server itself. g4dn.12xlarge gives 4 physical T4 GPUs, so
# staging, production, and later a canary revision (v4) each get a
# dedicated GPU instead of sharing one through time-slicing.
#
# Requested as a spot instance since this server only runs for a few
# hours per version before being destroyed (see infra.yml), so the
# discount matters more here than the small risk of an interruption
# during a short-lived test window.
resource "aws_instance" "server" {
  ami                    = data.aws_ami.deep_learning.id
  instance_type          = "g4dn.12xlarge"
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.server.id]
  key_name               = aws_key_pair.ai_model_serving.key_name

  instance_market_options {
    market_type = "spot"
    spot_options {
      instance_interruption_behavior = "terminate"
      spot_instance_type             = "one-time"
    }
  }

  # Deep Learning AMIs ship with a large set of preinstalled
  # frameworks and CUDA toolkits, so the root volume needs more room
  # than the 8GB default gives it.
  root_block_device {
    volume_size = 100
    volume_type = "gp3"
  }

  tags = {
    Name = "ai-model-serving-server"
  }
}

# A static public IP that stays locked to the instance no matter what
# happens underneath it. Without this, every apply/destroy cycle hands
# out a new IP and Ansible, the kubeconfig, and the security group's
# my_ip rules would all need chasing down again.
resource "aws_eip" "server" {
  instance = aws_instance.server.id
  domain   = "vpc"

  tags = {
    Name = "ai-model-serving-eip"
  }
}
