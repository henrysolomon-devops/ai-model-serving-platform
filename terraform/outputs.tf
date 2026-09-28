# Point at the Elastic IPs, since those stay put across rebuilds.
output "control_plane_public_ip" {
  description = "Public IP of the control plane node (hosts staging)"
  value       = aws_eip.control_plane.public_ip
}

output "worker_public_ip" {
  description = "Public IP of the worker node (hosts production)"
  value       = aws_eip.worker.public_ip
}

# The worker joins the cluster over the VPC's private network.
output "control_plane_private_ip" {
  description = "Private IP of the control plane, used by the worker to join"
  value       = aws_instance.control_plane.private_ip
}
