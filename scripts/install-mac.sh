#!/usr/bin/env bash
# Build the Mac app for the agent on AWS and put it in /Applications.
#
# Needs client/.env.production (scripts/client-env.sh, after the first deploy). The app is ad-hoc signed
# (tauri.conf.json > bundle > macOS > signingIdentity "-"), which is enough for this Mac: a build made here is never
# quarantined. Each rebuild has a new signature, so the first launch after one asks once to use the Keychain
# entry with the sign-in; choose Always Allow.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f client/.env.production ]]; then
  echo "client/.env.production is missing: deploy (scripts/deploy-agent.sh), then run scripts/client-env.sh" >&2
  exit 1
fi

cd client
bun install --frozen-lockfile
bun tauri build --target aarch64-apple-darwin --bundles app

app="src-tauri/target/aarch64-apple-darwin/release/bundle/macos/radAgent.app"
if [[ -d /Applications/radAgent.app ]]; then
  osascript -e 'quit app "radAgent"' >/dev/null 2>&1 || true
  rm -rf /Applications/radAgent.app
fi
cp -R "$app" /Applications/
codesign -dv /Applications/radAgent.app 2>&1 | grep -E '^(Identifier|Signature)' || true
echo "Installed /Applications/radAgent.app"
