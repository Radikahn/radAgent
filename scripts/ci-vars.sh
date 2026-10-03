#!/usr/bin/env bash
# Store what .github/workflows/main.yml needs in the repository's Actions variables, from the Terraform outputs
# (none of these values are secret; AWS sign-in is OIDC, so there are no keys). Needs the GitHub CLI, signed in.
set -euo pipefail
cd "$(dirname "$0")/.."

tf_out() { terraform -chdir=infra output -raw "$1"; }
# These are null until they exist, and `output -raw` refuses to print null.
need() {
  local value
  if ! value="$(tf_out "$1" 2>/dev/null)" || [[ -z "$value" ]]; then
    echo "error: $1 is not set yet; $2" >&2
    exit 1
  fi
  printf '%s' "$value"
}

repo="$(need github_repository "set github_repository in infra/terraform.tfvars and terraform apply")"
role_arn="$(need github_actions_role_arn "set github_repository in infra/terraform.tfvars and terraform apply")"
runtime_arn="$(need runtime_arn "deploy the agent first (scripts/deploy-agent.sh)")"

gh variable set AWS_REGION --repo "$repo" --body "$(tf_out region)"
gh variable set AWS_ROLE_ARN --repo "$repo" --body "$role_arn"
gh variable set ECR_REPOSITORY --repo "$repo" --body "$(tf_out ecr_url)"
gh variable set AGENT_RUNTIME_ID --repo "$repo" --body "${runtime_arn##*/}"
echo "Set the Actions variables of ${repo}"
