#!/usr/bin/env bash
# Write client/.env.production from the Terraform outputs (none of these values are secret).
set -euo pipefail
cd "$(dirname "$0")/.."

tf_out() { terraform -chdir=infra output -raw "$1"; }

region="$(tf_out region)"
client_id="$(tf_out client_id)"
# runtime_arn is null until the first deploy, and `output -raw` refuses to print null.
if ! runtime_arn="$(tf_out runtime_arn 2>/dev/null)" || [[ -z "$runtime_arn" ]]; then
  echo "error: runtime_arn is not set yet; deploy the agent first (scripts/deploy-agent.sh)" >&2
  exit 1
fi

# Empty until google_client_id is set in infra/terraform.tfvars; the app then offers Connect Google in Settings.
google_client_id="$(tf_out google_client_id 2>/dev/null)" || google_client_id=""

out="client/.env.production"
cat > "$out" <<EOF
VITE_AWS_REGION=${region}
VITE_RUNTIME_ARN=${runtime_arn}
VITE_COGNITO_CLIENT_ID=${client_id}
EOF
if [[ -n "$google_client_id" ]]; then
  echo "VITE_GOOGLE_CLIENT_ID=${google_client_id}" >> "$out"
fi
echo "Wrote ${out}"
