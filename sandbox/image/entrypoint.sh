#!/bin/sh
# Generates the host key on first start (it persists in the host_keys volume), then runs sshd in the foreground
set -eu

key=/etc/ssh/host_keys/ssh_host_ed25519_key
if [ ! -s "$key" ]; then
	ssh-keygen -q -t ed25519 -N '' -C radagent-sandbox -f "$key"
	echo "entrypoint: generated a new host key" >&2
fi
chmod 600 "$key"
echo "entrypoint: host key $(ssh-keygen -l -f "$key.pub")" >&2

if [ ! -s /etc/ssh/authorized_keys/agent ]; then
	echo "entrypoint: no key at /etc/ssh/authorized_keys/agent; nobody can log in until one is mounted there" >&2
fi

# sshd's privilege separation directory; /run is a tmpfs when the root filesystem is read-only
mkdir -p /run/sshd
chmod 755 /run/sshd

exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config
