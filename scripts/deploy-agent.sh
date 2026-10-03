#!/usr/bin/env bash
# Build the agent image for arm64, push it to ECR, then point the AgentCore runtime at it.
#
# Usage: scripts/deploy-agent.sh [extra terraform apply args...]
#   e.g. scripts/deploy-agent.sh -var budget_email=me@example.com
set -euo pipefail
cd "$(dirname "$0")/.."

tf_out() { terraform -chdir=infra output -raw "$1"; }

region="$(tf_out region)"
ecr_url="$(tf_out ecr_url)"
registry="${ecr_url%%/*}"
tag="$(git rev-parse --short HEAD)-$(date +%Y%m%d%H%M%S)"
image="${ecr_url}:${tag}"

if [[ -n "$(git status --porcelain -- agent)" ]]; then
  echo "note: agent/ has uncommitted changes; they go into ${tag} too" >&2
fi

echo "==> Logging in to ${registry}"
aws ecr get-login-password --region "$region" \
  | docker login --username AWS --password-stdin "$registry"

# --provenance=false pushes a plain arm64 image manifest instead of an index with an attestation.
echo "==> Building and pushing ${image}"
docker buildx build --platform linux/arm64 --provenance=false -t "$image" --push agent/

echo "==> terraform apply with image_tag=${tag}"
terraform -chdir=infra apply -var "image_tag=${tag}" "$@"
