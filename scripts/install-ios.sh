#!/usr/bin/env bash
# Build the iPhone app for the agent on AWS and install it on your phone, signed with a free Apple ID.
#
#   scripts/install-ios.sh
#
# Your Personal Team's ID and the phone come from .env at the repo's root (gitignored), so they stay out of git:
#
#   APPLE_DEVELOPMENT_TEAM=<team id>
#   IOS_DEVICE=<device name or UDID>
#
# Setting either in the environment, or passing the device as the argument, takes the place of .env's for that run.
#
# Once: sign in to Xcode with your Apple ID (Settings > Accounts; the Personal Team's ID is shown there), turn on
# Developer Mode on the iPhone (Settings > Privacy & Security), and connect it by cable (later Wi-Fi works too, after
# "Connect via network" in Xcode's Devices window). After the first install, trust the developer on the phone:
# Settings > General > VPN & Device Management.
#
# A free team's signature lasts 7 days: run this again within the week. Installing over the old app keeps its data
# and the sign-in in the Keychain.
#
# If signing fails here (free teams sometimes need Xcode to create the profile first): with the iPhone connected,
# `bun tauri ios open` in client/, select the radagent-client_iOS target > Signing & Capabilities, pick your Personal
# Team, and wait for Xcode to make the profile; then run this script again.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f client/.env.production ]]; then
  echo "client/.env.production is missing: deploy (scripts/deploy-agent.sh), then run scripts/client-env.sh" >&2
  exit 1
fi

# One KEY=value from .env, quotes stripped. Read rather than sourced, so nothing else in the file runs or leaks in
env_value() {
  [[ -f .env ]] || return 0
  local value
  value="$(grep -E "^$1=" .env | tail -1)" || return 0
  value="${value#*=}"
  if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then
    value="${BASH_REMATCH[1]}"
  fi
  printf '%s' "$value"
}

team="${APPLE_DEVELOPMENT_TEAM:-$(env_value APPLE_DEVELOPMENT_TEAM)}"
device="${1:-${IOS_DEVICE:-$(env_value IOS_DEVICE)}}"

if [[ -z "$team" ]]; then
  echo "Set APPLE_DEVELOPMENT_TEAM in .env to your Personal Team ID (Xcode > Settings > Accounts)" >&2
  exit 1
fi
if [[ -z "$device" ]]; then
  echo "Which device? Set IOS_DEVICE in .env to its name or UDID:" >&2
  xcrun devicectl list devices >&2
  exit 1
fi
export APPLE_DEVELOPMENT_TEAM="$team"

# Tauri's Swift side doesn't build or link with Xcode 27 as is; scripts/ios-swift/swift says why
export PATH="$PWD/scripts/ios-swift:$PATH"

cd client
bun install --frozen-lockfile
# Development signing, which is what a free team can do
bun tauri ios build --export-method debugging

ipa="$(ls -t src-tauri/gen/apple/build/arm64/*.ipa | head -1)"
xcrun devicectl device install app --device "$device" "$ipa"
echo "Installed $(basename "$ipa") on $device"
