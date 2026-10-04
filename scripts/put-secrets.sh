#!/usr/bin/env bash
# Store the agent's secrets in Secrets Manager as one JSON object:
#   EXA_API_KEY, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN, and the sandbox's SANDBOX_HOST,
#   SANDBOX_PORT, SANDBOX_USER, SANDBOX_HOST_KEY, SANDBOX_CF_ACCESS_CLIENT_ID, SANDBOX_CF_ACCESS_CLIENT_SECRET
#                  from the environment, else agent/.env (each left out when unset)
#   SECRET_PROMPT  contents of the file at SECRET_PROMPT_PATH (environment, else agent/.env; left out when unset)
#   SANDBOX_SSH_KEY contents of the file at SANDBOX_SSH_KEY_PATH, the same way (sandbox/keygen.sh makes it)
# Values are never printed; only the key names are.
set -euo pipefail

caller_dir="$PWD"
cd "$(dirname "$0")/.."

env_file="agent/.env"

# Print KEY's value from agent/.env (last assignment wins), without quotes or a trailing comment.
dotenv_get() {
  local key="$1" line val
  [[ -f "$env_file" ]] || return 0
  line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" "$env_file" | tail -n 1)" || return 0
  [[ -n "$line" ]] || return 0
  val="${line#*=}"
  val="${val%$'\r'}"
  val="${val#"${val%%[![:space:]]*}"}"
  if [[ "$val" == \"* ]]; then
    val="${val#\"}"
    val="${val%%\"*}"
  elif [[ "$val" == \'* ]]; then
    val="${val#\'}"
    val="${val%%\'*}"
  else
    val="${val%%[[:space:]]#*}"
    val="${val%"${val##*[![:space:]]}"}"
  fi
  printf '%s' "$val"
}

tf_out() { terraform -chdir=infra output -raw "$1"; }

region="$(tf_out region)"
secret_id="$(tf_out secret_id)"

# Plain keys copied as they are; SPOTIFY_REFRESH_TOKEN comes from `uv run radagent --spotify-login`
env_keys=(EXA_API_KEY SPOTIFY_CLIENT_ID SPOTIFY_CLIENT_SECRET SPOTIFY_REFRESH_TOKEN
  SANDBOX_HOST SANDBOX_PORT SANDBOX_USER SANDBOX_HOST_KEY SANDBOX_CF_ACCESS_CLIENT_ID SANDBOX_CF_ACCESS_CLIENT_SECRET)

# Print the file a *_PATH setting names. A relative path is relative to where it was set: the caller's
# directory for the environment, agent/ for agent/.env (the agent runs from agent/).
setting_path() {
  local name="$1" path=""
  if [[ -n "${!name:-}" ]]; then
    path="${!name}"
    [[ "$path" == /* ]] || path="${caller_dir}/${path}"
  else
    path="$(dotenv_get "$name")"
    if [[ -n "$path" && "$path" != /* ]]; then
      path="agent/${path}"
    fi
  fi
  if [[ -n "$path" && ! -f "$path" ]]; then
    echo "error: ${name} is set but ${path} does not exist" >&2
    exit 1
  fi
  printf '%s' "$path"
}

prompt_path="$(setting_path SECRET_PROMPT_PATH)"
sandbox_key_path="$(setting_path SANDBOX_SSH_KEY_PATH)"

jq_args=(-n)
filter='{}'
for key in "${env_keys[@]}"; do
  value="${!key:-$(dotenv_get "$key")}"
  if [[ -n "$value" ]]; then
    # Passed to jq through the environment rather than --arg so it never shows up in argv.
    export "$key=$value"
    filter+=" + {${key}: \$ENV.${key}}"
  fi
done
if [[ -n "$prompt_path" ]]; then
  jq_args+=(--rawfile secret_prompt "$prompt_path")
  filter+=' + {SECRET_PROMPT: $secret_prompt}'
fi
if [[ -n "$sandbox_key_path" ]]; then
  jq_args+=(--rawfile sandbox_key "$sandbox_key_path")
  filter+=' + {SANDBOX_SSH_KEY: $sandbox_key}'
fi

umask 077
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
chmod 600 "$tmp"

jq "${jq_args[@]}" "$filter" > "$tmp"

keys="$(jq -r 'keys | if length == 0 then "(none)" else join(", ") end' "$tmp")"
if [[ "$keys" == "(none)" ]]; then
  echo "warning: none of ${env_keys[*]}, SECRET_PROMPT_PATH or SANDBOX_SSH_KEY_PATH is set; storing an empty object" >&2
fi

aws secretsmanager put-secret-value \
  --region "$region" \
  --secret-id "$secret_id" \
  --secret-string "file://${tmp}" \
  --query VersionId --output text >/dev/null

echo "Stored ${keys} in ${secret_id}"
