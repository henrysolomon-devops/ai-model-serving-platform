# Points at the Elastic IP rather than the instance's own public IP,
# since that's the address that stays put across rebuilds.
output "server_public_ip" {
  description = "Static public IP address of the GPU EC2 instance (Elastic IP)"
  value       = aws_eip.server.public_ip
}
