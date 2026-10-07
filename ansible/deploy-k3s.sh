#!/usr/bin/env bash
# Takes the public IPs of the control plane, the worker and the canary
# node, plus the control plane's private IP (all from `terraform output`,
# passed in by infra.yml). Runs the Ansible playbook against the three
# nodes to build the k3s cluster, then fetches the kubeconfig so
# kubectl/helm can be used against it from outside.
set -euo pipefail

if [ $# -lt 4 ]; then
  echo "Usage: $0 <control-plane-public-ip> <worker-public-ip> <canary-public-ip> <control-plane-private-ip>"
  exit 1
fi

CONTROL_PLANE_IP="$1"
WORKER_IP="$2"
CANARY_IP="$3"
CONTROL_PLANE_PRIVATE_IP="$4"
echo "Control plane: $CONTROL_PLANE_IP (private: $CONTROL_PLANE_PRIVATE_IP)"
echo "Worker: $WORKER_IP"
echo "Canary: $CANARY_IP"

INVENTORY=$(mktemp)
trap 'rm -f "$INVENTORY"' EXIT
cat > "$INVENTORY" <<EOF
[control_plane]
${CONTROL_PLANE_IP}

[worker]
${WORKER_IP} node_environment=production

[canary]
${CANARY_IP} node_environment=canary
EOF

ansible-playbook -i "$INVENTORY" install-k3s.yml \
  --extra-vars "ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/ai-model-serving-key tls_san=${CONTROL_PLANE_IP} control_plane_private_ip=${CONTROL_PLANE_PRIVATE_IP}"

echo "Fetching kubeconfig..."
mkdir -p ~/.kube
ssh -i ~/.ssh/ai-model-serving-key -o StrictHostKeyChecking=accept-new \
  ubuntu@"$CONTROL_PLANE_IP" "sudo cat /etc/rancher/k3s/k3s.yaml" > ~/.kube/ai-model-serving-config
sed -i "s/127.0.0.1/${CONTROL_PLANE_IP}/" ~/.kube/ai-model-serving-config

echo "Done. Run this to use kubectl/helm against this cluster:"
echo "  export KUBECONFIG=~/.kube/ai-model-serving-config"
echo ""
echo "Once the model service is deployed (later steps), it will be reachable at:"
echo "  Staging:    http://${CONTROL_PLANE_IP}:8001  (chat UI)   http://${CONTROL_PLANE_IP}:8011  (model API)"
echo "  Production: http://${WORKER_IP}:8002  (chat UI)   http://${WORKER_IP}:8012  (model API)"
echo "  Gateway:    port 8003 on any node (splits traffic between production and the canary)"
