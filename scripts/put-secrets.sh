#!/usr/bin/env bash
# Store the agent's secrets in Secrets Manager as one JSON object:
#   EXA_API_KEY    from the environment, else agent/.env (left out when unset)
#   SECRET_PROMPT  contents of the file at SECRET_PROMPT_PATH (environment, else agent/.env; left out when unset)
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

exa_api_key="${EXA_API_KEY:-$(dotenv_get EXA_API_KEY)}"

# A relative SECRET_PROMPT_PATH is relative to where it was set: the caller's directory for the
# environment, agent/ for agent/.env (the agent runs from agent/).
prompt_path=""
if [[ -n "${SECRET_PROMPT_PATH:-}" ]]; then
  prompt_path="$SECRET_PROMPT_PATH"
  [[ "$prompt_path" == /* ]] || prompt_path="${caller_dir}/${prompt_path}"
else
  prompt_path="$(dotenv_get SECRET_PROMPT_PATH)"
  if [[ -n "$prompt_path" && "$prompt_path" != /* ]]; then
    prompt_path="agent/${prompt_path}"
  fi
fi
if [[ -n "$prompt_path" && ! -f "$prompt_path" ]]; then
  echo "error: SECRET_PROMPT_PATH is set but ${prompt_path} does not exist" >&2
  exit 1
fi

jq_args=(-n)
filter='{}'
if [[ -n "$exa_api_key" ]]; then
  # Passed through the environment rather than --arg so it never shows up in argv.
  filter+=' + {EXA_API_KEY: $ENV.EXA_API_KEY}'
fi
if [[ -n "$prompt_path" ]]; then
  jq_args+=(--rawfile secret_prompt "$prompt_path")
  filter+=' + {SECRET_PROMPT: $secret_prompt}'
fi

umask 077
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
chmod 600 "$tmp"

EXA_API_KEY="$exa_api_key" jq "${jq_args[@]}" "$filter" > "$tmp"

keys="$(jq -r 'keys | if length == 0 then "(none)" else join(", ") end' "$tmp")"
if [[ "$keys" == "(none)" ]]; then
  echo "warning: neither EXA_API_KEY nor SECRET_PROMPT_PATH is set; storing an empty object" >&2
fi

aws secretsmanager put-secret-value \
  --region "$region" \
  --secret-id "$secret_id" \
  --secret-string "file://${tmp}" \
  --query VersionId --output text >/dev/null

echo "Stored ${keys} in ${secret_id}"
