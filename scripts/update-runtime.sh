#!/usr/bin/env bash
# Point the AgentCore runtime at another image and wait until its DEFAULT endpoint serves it. GitHub Actions
# (.github/workflows/main.yml) and scripts/deploy-agent.sh both deploy through this.
#
# Usage: scripts/update-runtime.sh <runtime id> <image uri>
#
# UpdateAgentRuntime replaces the runtime's whole configuration, so everything but the image (role, authorizer,
# environment, lifecycle, ...) is read back from the runtime and sent as it is. Terraform keeps owning those;
# infra/runtime.tf ignores only the image.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <runtime id> <image uri>" >&2
  exit 2
fi
runtime_id="$1"
image="$2"

current="$(aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$runtime_id" --output json)"
request="$(jq --arg image "$image" '
  with_entries(select(.key | IN(
    "agentRuntimeId", "roleArn", "networkConfiguration", "description", "authorizerConfiguration",
    "requestHeaderConfiguration", "protocolConfiguration", "lifecycleConfiguration", "metadataConfiguration",
    "environmentVariables", "filesystemConfigurations", "capacityProviderConfiguration", "platformVersion"
  )))
  + {agentRuntimeArtifact: {containerConfiguration: {containerUri: $image}}}
' <<<"$current")"

version="$(aws bedrock-agentcore-control update-agent-runtime --cli-input-json "$request" \
  --query agentRuntimeVersion --output text)"
echo "==> ${runtime_id} version ${version}: ${image}"

# The update is asynchronous: the runtime goes UPDATING -> READY, then DEFAULT moves to the new version.
deadline=$((SECONDS + 900))
while :; do
  status="$(aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$runtime_id" \
    --query status --output text)"
  endpoint="$(aws bedrock-agentcore-control get-agent-runtime-endpoint --agent-runtime-id "$runtime_id" \
    --endpoint-name DEFAULT --query '[status, liveVersion]' --output text)"
  read -r endpoint_status live_version <<<"$endpoint"
  echo "    runtime ${status}, DEFAULT ${endpoint_status} on version ${live_version}"

  if [[ "$status" == *FAILED || "$endpoint_status" == *FAILED ]]; then
    aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$runtime_id" \
      --query '{status: status, failureReason: failureReason}' --output json >&2
    echo "error: version ${version} failed to deploy" >&2
    exit 1
  fi
  if [[ "$status" == READY && "$endpoint_status" == READY && "$live_version" == "$version" ]]; then
    break
  fi
  if ((SECONDS > deadline)); then
    echo "error: version ${version} wasn't live after 15 minutes" >&2
    exit 1
  fi
  sleep 10
done
echo "==> DEFAULT serves version ${version}"
