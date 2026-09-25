#!/bin/bash
# runner-init.sh — cloud-init for a harness-report runner.  Rendered by runplane.tf.
#
# The boot sequence from RUN-PLANE.md, in order, before the instance advertises itself:
#   1. format and mount the NVMe, start docker
#   2. pull the 8 bake-list bases in parallel, plus hr-proxy
#   3. warm BuildKit
#   4. tag self hr:state=free
#
# Warm-up is invisible as long as the pool is deeper than arrivals during warm-up, which is the
# whole reason the tag goes on last.
set -euxo pipefail

REGION="${region}"
QUEUE_URL="${queue_url}"
RUNS_BUCKET="${runs_bucket}"
RECIPES_BUCKET="${recipes_bucket}"
TABLE="${table}"
REGISTRY="${registry}"

IID=$(curl -sf -H "X-aws-ec2-metadata-token: $(curl -sf -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" \
  http://169.254.169.254/latest/meta-data/instance-id)

# ---------------------------------------------------------------- 1. disk and daemon

# docker-ce pinned from Docker's own repo, same major as the laptop that generated the recipes:
# the design leans on current BuildKit and the containerd image store, and Ubuntu's docker.io lags.
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin awscli jq

# /var/lib/docker on instance store, formatted at every boot.  -m0 because no reserved blocks are
# wanted on a cache; noatime because image unpack writes millions of inodes and nothing reads atime.
NVME=$(lsblk -dpno NAME,MODEL | awk '/Instance Storage/ {print $1; exit}')
if [ -n "$NVME" ]; then
  mkfs.ext4 -m0 -F "$NVME"
  mkdir -p /mnt/nvme
  mount -o noatime,nodiratime "$NVME" /mnt/nvme
  mkdir -p /mnt/nvme/docker
fi

mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'JSON'
{
  "data-root": "/mnt/nvme/docker",
  "storage-driver": "overlay2",
  "default-address-pools": [{"base": "10.200.0.0/12", "size": 24}],
  "max-concurrent-downloads": 10,
  "log-driver": "json-file",
  "log-opts": {"max-size": "64m", "max-file": "3"},
  "live-restore": false,
  "features": {"containerd-snapshotter": true}
}
JSON
# Docker's built-in pools give ~30 user-defined networks; two networks per run puts 8 concurrent
# runs within a factor of two of the ceiling, and the failure reads as a flaky harness.

# No swap: when a build or an agent blows its budget the cgroup should OOM-kill it, not thrash the
# host.  codex-rs already OOMs at 8 GB and that is a finding, not a condition to paper over.
swapoff -a || true

cat > /etc/sysctl.d/99-harness-report.conf <<'SYSCTL'
fs.inotify.max_user_instances = 8192
fs.inotify.max_user_watches = 1048576
net.netfilter.nf_conntrack_max = 1048576
kernel.pid_max = 4194304
vm.max_map_count = 262144
SYSCTL
sysctl --system

# SigV4 and TLS both fail on skew, and a run that dies from clock drift looks exactly like a harness bug.
DEBIAN_FRONTEND=noninteractive apt-get install -y chrony
systemctl enable --now chrony

systemctl enable --now docker

# ---------------------------------------------------------------- 2. the hot image set

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY" || true

# 8 bases = 81% of the 49,170-task corpus.  Baking 50 buys 88% — stop at 8.
for image in \
  python:3.11-slim \
  ghcr.io/laude-institute/t-bench/python-3-13:20250620 \
  python:3.10-slim \
  python:3.12-slim \
  python:3.11-slim-bookworm \
  ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 \
  python:3.13-slim-bookworm \
  debian:bookworm-slim \
  buildpack-deps:jammy \
  "$REGISTRY/harness-report/proxy:latest"
do
  docker pull --platform linux/amd64 "$image" &
done
wait || true

# ---------------------------------------------------------------- 3. BuildKit

docker buildx create --use --name hr || true
docker buildx inspect --bootstrap || true

# ---------------------------------------------------------------- 4. hr-agentd
#
# NOT WRITTEN YET.  When it exists it leases from $QUEUE_URL, runs the existing run.sh stages,
# streams stage events to $TABLE, syncs the run folder to s3://$RUNS_BUCKET and drops the lease.
# Until then an instance boots, warms its cache, advertises itself and idles — which is why
# enable_run_plane defaults to false.

cat > /etc/harness-report.env <<ENVFILE
AWS_REGION=$REGION
HR_QUEUE_URL=$QUEUE_URL
HR_RUNS_BUCKET=$RUNS_BUCKET
HR_RECIPES_BUCKET=$RECIPES_BUCKET
HR_TABLE=$TABLE
HR_REGISTRY=$REGISTRY
HR_PLATFORM=linux/amd64
ENVFILE

aws ec2 create-tags --region "$REGION" --resources "$IID" --tags Key=hr:state,Value=free
