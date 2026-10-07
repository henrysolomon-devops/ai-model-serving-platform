resource "aws_security_group" "server" {
  name        = "ai-model-serving-sg"
  description = "Security group for the GPU k3s nodes. SSH, k3s API, the chat UI and the gateway are always open for me. GitHub runners get temporary access per workflow run."
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "SSH, only from my own machine"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  ingress {
    description = "Chat UI app ports (staging/production), always reachable from my own machine"
    from_port   = 8001
    to_port     = 8002
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  ingress {
    description = "Gateway port, where the canary traffic split happens"
    from_port   = 8003
    to_port     = 8003
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  ingress {
    description = "k3s API, always reachable from my own machine"
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  ingress {
    description = "All traffic between the cluster nodes"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "ai-model-serving-sg"
  }
}

output "security_group_id" {
  value = aws_security_group.server.id
}
