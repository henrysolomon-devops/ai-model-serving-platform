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

  # The Flask chat UI for each environment. 8001 = staging, 8002 =
  # production. Always open for me so I can check the UI in a browser
  # without waiting for a workflow run to open a port first.
  ingress {
    description = "Chat UI app ports (staging/production), always reachable from my own machine"
    from_port   = 8001
    to_port     = 8002
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  # The vLLM model API itself, one port per environment. 8011 =
  # staging, 8012 = production. Kept separate from the chat UI ports
  # so the model endpoint and the proxy in front of it can be reached
  # (or firewalled) independently.
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

  # No permanent ingress rules here for GitHub's runners. Those open
  # and close dynamically per workflow run via the AWS CLI, the same
  # pattern devops-cicd-pipeline uses in infra.yml and deploy.yml.

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
