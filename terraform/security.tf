resource "aws_security_group" "server" {
  name        = "ai-model-serving-sg"
  description = "Security group for the GPU EC2/k3s server. SSH, k3s API, and app/model ports are always open for me. GitHub runners get temporary access per workflow run."
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

  # Kept separate from the chat UI ports so the model endpoint can be
  # firewalled independently later if needed.
  ingress {
    description = "Model API ports (staging/production), always reachable from my own machine"
    from_port   = 8011
    to_port     = 8012
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
