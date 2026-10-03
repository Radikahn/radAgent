#!/usr/bin/env bash
# Build the agent image for arm64, push it to ECR, then point the AgentCore runtime at it: the first time by creating
# the runtime with Terraform, after that with scripts/update-runtime.sh, as GitHub Actions does on pushes to main.
#
# Usage: scripts/deploy-agent.sh [extra terraform apply args, for the first deploy...]
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

# runtime_arn is null until the first deploy, and `output -raw` refuses to print null.
if runtime_arn="$(tf_out runtime_arn 2>/dev/null)" && [[ -n "$runtime_arn" ]]; then
  if [[ $# -gt 0 ]]; then
    echo "note: the runtime exists, so the terraform args aren't used: $*" >&2
  fi
  AWS_REGION="$region" scripts/update-runtime.sh "${runtime_arn##*/}" "$image"
else
  echo "==> terraform apply with image_tag=${tag}"
  terraform -chdir=infra apply -var "image_tag=${tag}" "$@"
fi
