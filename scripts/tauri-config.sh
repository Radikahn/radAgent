#!/usr/bin/env bash
# Print the build-time additions to client/src-tauri/tauri.conf.json, for `bun tauri build --config "$(...)"`.
#
# Connect Google (client/src/remote/google.ts) gets Google's answer on the OAuth client's own URL scheme,
# com.googleusercontent.apps.<id>, which depends on VITE_GOOGLE_CLIENT_ID in client/.env.production (or the
# environment); this registers it with the deep-link plugin on macOS and iOS. Prints {} without a Google client.
set -euo pipefail
cd "$(dirname "$0")/.."

client_id="${VITE_GOOGLE_CLIENT_ID:-}"
if [[ -z "$client_id" && -f client/.env.production ]]; then
  client_id="$(grep -E '^VITE_GOOGLE_CLIENT_ID=' client/.env.production | tail -1 | cut -d= -f2-)" || true
fi

if [[ -z "$client_id" ]]; then
  echo '{}'
  exit 0
fi
if [[ ! "$client_id" =~ ^[A-Za-z0-9-]+\.apps\.googleusercontent\.com$ ]]; then
  echo "error: VITE_GOOGLE_CLIENT_ID ($client_id) isn't a Google OAuth client ID" >&2
  exit 1
fi

scheme="com.googleusercontent.apps.${client_id%.apps.googleusercontent.com}"
jq -cn --arg scheme "$scheme" \
  '{plugins: {"deep-link": {desktop: {schemes: [$scheme]}, mobile: [{scheme: [$scheme], appLink: false}]}}}'
