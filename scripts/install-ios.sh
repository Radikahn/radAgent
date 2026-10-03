#!/usr/bin/env bash
# Build the iPhone app for the agent on AWS and install it on your phone, signed with a free Apple ID.
#
#   APPLE_DEVELOPMENT_TEAM=<team id> scripts/install-ios.sh [device name or UDID]
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

: "${APPLE_DEVELOPMENT_TEAM:?Set APPLE_DEVELOPMENT_TEAM to your Personal Team ID (Xcode > Settings > Accounts)}"
export APPLE_DEVELOPMENT_TEAM

if [[ ! -f client/.env.production ]]; then
  echo "client/.env.production is missing: deploy (scripts/deploy-agent.sh), then run scripts/client-env.sh" >&2
  exit 1
fi

device="${1:-}"
if [[ -z "$device" ]]; then
  echo "Which device? Pass its name or UDID:" >&2
  xcrun devicectl list devices >&2
  exit 1
fi

# Tauri's Swift side doesn't build or link with Xcode 27 as is; scripts/ios-swift/swift says why
export PATH="$PWD/scripts/ios-swift:$PATH"

cd client
bun install --frozen-lockfile
# Development signing, which is what a free team can do
bun tauri ios build --export-method debugging

ipa="$(ls -t src-tauri/gen/apple/build/arm64/*.ipa | head -1)"
xcrun devicectl device install app --device "$device" "$ipa"
echo "Installed $(basename "$ipa") on $device"
