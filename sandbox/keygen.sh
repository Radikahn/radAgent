#!/usr/bin/env bash
# Makes the agent's SSH key for the sandbox in agent/.sandbox/ (leaves an existing one alone), writes
# sandbox/authorized_keys for docker-compose.yml, and prints what goes where
set -euo pipefail
cd "$(dirname "$0")/.."

key=agent/.sandbox/id_ed25519
if [[ -f "$key" ]]; then
	echo "Using the existing key ${key}; delete it first to make a new one" >&2
else
	mkdir -p agent/.sandbox
	chmod 700 agent/.sandbox
	ssh-keygen -q -t ed25519 -N '' -C "radagent@$(date +%Y-%m-%d)" -f "$key"
fi
public="$(cat "${key}.pub")"

# The same restrictions the NixOS module puts on the key, for docker-compose.yml
umask 022
printf 'restrict,pty %s\n' "$public" > sandbox/authorized_keys

cat <<EOT
The agent's key is ${key} (the private half never goes on the server).

1. On the server, add its public key to the NixOS configuration (or use sandbox/authorized_keys with Docker Compose):

    services.radagent-sandbox.authorizedKeys = [ "${public}" ];

2. Once the sandbox is running, read its host key on the server itself, not over the network:

    sudo cat /var/lib/radagent-sandbox/host-keys/ssh_host_ed25519_key.pub

3. Add these to agent/.env, with the host key from step 2 and the address the agent reaches the sandbox at:

    SANDBOX_HOST=<server address, or the Cloudflare hostname>
    SANDBOX_PORT=2222
    SANDBOX_HOST_KEY=ssh-ed25519 AAAA...
    SANDBOX_SSH_KEY_PATH=.sandbox/id_ed25519

   and, through a Cloudflare Tunnel, the Access service token:

    SANDBOX_CF_ACCESS_CLIENT_ID=....access
    SANDBOX_CF_ACCESS_CLIENT_SECRET=...

4. Check it: uv run --project agent python scripts/smoke_sandbox.py
   For the deployed agent: scripts/put-secrets.sh
EOT
