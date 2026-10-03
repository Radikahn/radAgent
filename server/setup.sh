#!/usr/bin/env bash
# Writes .env with fresh secrets for Garage and creates the data folders; leaves an existing .env alone
set -euo pipefail
cd "$(dirname "$0")"

if [[ -f .env ]]; then
	echo ".env already exists; delete it first to generate new secrets" >&2
	exit 1
fi

access_key="GK$(openssl rand -hex 16)"
secret_key="$(openssl rand -hex 32)"

umask 077
cat > .env <<EOF
# Garage's cluster secret; never leaves this server
GARAGE_RPC_SECRET=$(openssl rand -hex 32)

# The bucket and the key radagent uses, created when Garage first starts
GARAGE_DEFAULT_ACCESS_KEY=${access_key}
GARAGE_DEFAULT_SECRET_KEY=${secret_key}
GARAGE_DEFAULT_BUCKET=radagent

# Where the S3 API listens on this machine: 127.0.0.1, or the server's Tailscale IP to reach it from your devices
S3_BIND=127.0.0.1

# Only for \`docker compose --profile public up -d\`: the public hostname Caddy serves the S3 API on
S3_DOMAIN=
EOF

umask 022
mkdir -p data/meta data/data

cat <<EOF
Wrote .env. Start Garage with:

    docker compose up -d

Then add these to agent/.env on each device, with the endpoint your devices reach this server on:

    RADAGENT_S3_ENDPOINT=http://<server>:3900
    RADAGENT_S3_BUCKET=radagent
    RADAGENT_S3_REGION=garage
    RADAGENT_S3_ACCESS_KEY=${access_key}
    RADAGENT_S3_SECRET_KEY=${secret_key}
EOF
