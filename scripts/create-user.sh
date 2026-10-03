#!/usr/bin/env bash
# Create the Cognito user (email as username, already verified) and set a permanent password.
# Re-running for an existing user just sets a new password.
#
# Usage: scripts/create-user.sh <email>
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <email>" >&2
  exit 2
fi
email="$1"

cd "$(dirname "$0")/.."

tf_out() { terraform -chdir=infra output -raw "$1"; }

region="$(tf_out region)"
pool_id="$(tf_out user_pool_id)"

if err="$(aws cognito-idp admin-create-user \
  --region "$region" \
  --user-pool-id "$pool_id" \
  --username "$email" \
  --user-attributes Name=email,Value="$email" Name=email_verified,Value=true \
  --message-action SUPPRESS 2>&1 >/dev/null)"; then
  echo "Created ${email}"
elif [[ "$err" == *UsernameExistsException* ]]; then
  echo "${email} already exists; setting a new password"
else
  echo "$err" >&2
  exit 1
fi

read -rsp "Password for ${email}: " password
echo
read -rsp "Repeat password: " password2
echo
if [[ "$password" != "$password2" ]]; then
  echo "error: passwords do not match; run the script again" >&2
  exit 1
fi
if [[ -z "$password" ]]; then
  echo "error: empty password" >&2
  exit 1
fi
unset password2

# Hand the password to the CLI through a 600 temp file (never argv, where `ps` could see it).
umask 077
request="$(mktemp)"
trap 'rm -f "$request"' EXIT
PASSWORD="$password" jq -n \
  --arg pool "$pool_id" \
  --arg user "$email" \
  '{UserPoolId: $pool, Username: $user, Password: $ENV.PASSWORD, Permanent: true}' > "$request"
unset password

aws cognito-idp admin-set-user-password --region "$region" --cli-input-json "file://${request}"
echo "Password set; ${email} is confirmed"
