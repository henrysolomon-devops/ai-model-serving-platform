#!/usr/bin/env bash
# Takes the server's public IP as an argument (passed in from
# `terraform output` by infra.yml), runs the Ansible playbook against
# it to install k3s, then fetches the kubeconfig so kubectl/helm can
# be used against this cluster from outside.
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <server-public-ip>"
  exit 1
fi

SERVER_IP="$1"
echo "Using server IP: $SERVER_IP"

ansible-playbook -i "${SERVER_IP}," install-k3s.yml \
  --extra-vars "ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/ai-model-serving-key tls_san=${SERVER_IP}"

echo "Fetching kubeconfig..."
mkdir -p ~/.kube
ssh -i ~/.ssh/ai-model-serving-key -o StrictHostKeyChecking=accept-new \
  ubuntu@"$SERVER_IP" "sudo cat /etc/rancher/k3s/k3s.yaml" > ~/.kube/ai-model-serving-config
sed -i "s/127.0.0.1/${SERVER_IP}/" ~/.kube/ai-model-serving-config

echo "Done. Run this to use kubectl/helm against this cluster:"
echo "  export KUBECONFIG=~/.kube/ai-model-serving-config"
echo ""
echo "Once the model service is deployed (later steps), it will be reachable at:"
echo "  Staging:    http://${SERVER_IP}:8001  (chat UI)   http://${SERVER_IP}:8011  (model API)"
echo "  Production: http://${SERVER_IP}:8002  (chat UI)   http://${SERVER_IP}:8012  (model API)"
