#!/bin/bash
# Shared by the prepared AMI and first-boot fallback. No credentials or job data.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl unzip git python3 python3-venv jq chrony
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo 'deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable' > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
cat > /etc/docker/daemon.json <<'JSON'
{"data-root":"/var/lib/docker","default-address-pools":[{"base":"10.208.0.0/12","size":24}],"log-driver":"json-file","log-opts":{"max-size":"64m","max-file":"3"},"live-restore":false}
JSON
systemctl enable --now containerd docker chrony
systemctl restart docker
swapoff -a || true
python3 -m venv /opt/hr-venv
/opt/hr-venv/bin/pip install --quiet boto3 awscli harbor==0.23.0 toml==0.10.2 'anthropic[bedrock]==1.8.0'
ln -sf /opt/hr-venv/bin/aws /usr/local/bin/aws
curl -fsSL https://claude.ai/install.sh -o /tmp/install-claude.sh
CLAUDE_INSTALL_ALLOW_SUDO=1 bash /tmp/install-claude.sh
rm /tmp/install-claude.sh
# Common task bases; uncommon task images still build on demand.
for image in python:3.10-slim python:3.11-slim python:3.12-slim python:3.13-slim-bookworm debian:bookworm-slim; do
  docker pull --platform linux/amd64 "$image"
done
# Dependency layer is identical to the proxy's Dockerfile.
docker build -q -t hr-proxy-dependencies - <<'DOCKERFILE'
FROM python:3.12-slim
RUN pip install -q --root-user-action=ignore boto3 cryptography
DOCKERFILE
touch /etc/hr-image-ready
