# The VPC the GPU instance lives in. Same 10.0.0.0/16 range as
# devops-cicd-pipeline, no reason to deviate for a single-instance setup.
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "ai-model-serving-vpc"
  }
}

# A public slice of the VPC, made reachable from the internet by the
# route table association below.
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = true
  availability_zone       = "${var.aws_region}a"

  tags = {
    Name = "ai-model-serving-public-subnet"
  }
}

# The door between this VPC and the internet. Without it the instance
# can't be reached, and it can't reach out to pull images or weights.
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "ai-model-serving-igw"
  }
}

# Sends anything leaving the VPC (0.0.0.0/0) out through the internet gateway.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "ai-model-serving-public-rt"
  }
}

# Attaches the route table above to the subnet, so the rule actually applies to something.
resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}
