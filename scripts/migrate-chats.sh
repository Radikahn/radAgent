#!/usr/bin/env bash
# One-time copy of the local chats and memory (agent/.agent) into the chats bucket.
set -euo pipefail
cd "$(dirname "$0")/.."

tf_out() { terraform -chdir=infra output -raw "$1"; }

region="$(tf_out region)"
bucket="$(tf_out bucket)"

# local dir -> bucket prefix
sources=("agent/.agent/chats:chats" "agent/.agent/memory:memory")

echo "This will copy local files into s3://${bucket} (existing objects with the same key are overwritten):"
planned=()
for entry in "${sources[@]}"; do
  dir="${entry%%:*}"
  prefix="${entry#*:}"
  if [[ -d "$dir" ]]; then
    planned+=("$entry")
    echo "  aws s3 sync ${dir} s3://${bucket}/${prefix}/ --exclude '.DS_Store' --exclude '*/.DS_Store'"
  else
    echo "  (skipping ${dir}: not found)"
  fi
done

if [[ ${#planned[@]} -eq 0 ]]; then
  echo "Nothing to migrate."
  exit 0
fi

read -rp "Run the sync(s) above? [y/N] " answer
if [[ ! "$answer" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

for entry in "${planned[@]}"; do
  dir="${entry%%:*}"
  prefix="${entry#*:}"
  aws s3 sync "$dir" "s3://${bucket}/${prefix}/" \
    --region "$region" \
    --exclude '.DS_Store' \
    --exclude '*/.DS_Store'
done
echo "Done."
