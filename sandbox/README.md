# Sandbox

A Linux container on your own server where the agent writes, runs and tests code, runs long jobs, and does anything
else that needs real compute. The agent reaches it over SSH with the `sandbox_*` tools
(`agent/src/radagent/tools/sandbox`):

| Tool               | Does                                                                                   |
| ------------------ | -------------------------------------------------------------------------------------- |
| `sandbox_status`   | Checks the connection; shows CPUs, memory, disk, toolchains and running jobs            |
| `sandbox_run`      | Runs a command (bash, login shell) and returns its exit status and output; `background=True` starts a job |
| `sandbox_jobs`     | Lists background jobs, reads their output, stops or removes them                        |
| `sandbox_write`    | Writes a text file                                                                      |
| `sandbox_read`     | Reads a text file with line numbers                                                     |
| `sandbox_edit`     | Replaces exact text in a file                                                           |
| `sandbox_upload`   | Copies a file or folder from the agent's machine to the sandbox (never `.env`, `.ssh` and the like) |
| `sandbox_download` | Copies a file or folder back, e.g. a chart the agent then looks at with `read`           |

The container is Ubuntu 26.04 LTS with build tools, Python 3 with uv, Node with npm, git, ripgrep and so on
(`image/Dockerfile`). The agent logs in as `agent`, without root or sudo, and works in `~/work`, which persists between
commands and chats. It installs what a project needs into its home: `uv` or `python3 -m venv` for Python, `npm` for
Node. For system packages, add them to `image/Dockerfile`.

```
 agent (AgentCore or your Mac)                         your NixOS server
┌──────────────────────────┐                    ┌──────────────────────────────────────────┐
│ sandbox_* tools          │   SSH, end to end  │  docker: radagent-sandbox                 │
│  asyncssh                ├───────────────────►│   sshd :2222 (keys only, agent user only) │
│  key + pinned host key   │  via a Cloudflare  │   ~/work, background jobs                 │
│  (cloudflared)           │  Tunnel, or direct │   read-only root, no capabilities         │
└──────────────────────────┘                    │   internet yes; LAN, tailnet, host no     │
                                                └──────────────────────────────────────────┘
```

## Set up the server (NixOS)

1. On your Mac, make the agent's key: `sandbox/keygen.sh`. It saves the private key in `agent/.sandbox/` (git
   ignores it) and prints the public key.

2. On the server, import the module and give it that public key:

   ```nix
   # configuration.nix
   imports = [ /path/to/radAgent/sandbox/nixos.nix ];

   services.radagent-sandbox = {
     enable = true;
     authorizedKeys = [ "ssh-ed25519 AAAA... radagent@2026-10-03" ];
     # Optional, with their defaults:
     # cpus = "4"; memory = "8g"; tmpSize = "4g"; pids = 1024;
     # listenAddress = "127.0.0.1"; port = 2222;
   };
   ```

   The module needs the whole `sandbox/` folder next to it (it builds `image/`), so point it at a checkout of this
   repository, or copy the folder into your configuration.

3. `sudo nixos-rebuild switch`. The first start builds the image, which takes a few minutes. Then check it:

   ```sh
   systemctl status docker-radagent-sandbox
   journalctl -u docker-radagent-sandbox -n 20      # sshd's log: every login with its key's fingerprint
   ```

4. Read the sandbox's host key, on the server itself, so you know it's the real one:

   ```sh
   sudo cat /var/lib/radagent-sandbox/host-keys/ssh_host_ed25519_key.pub
   ```

   It goes into the agent's settings as `SANDBOX_HOST_KEY`. The agent trusts that key and no other, so a server that
   answers with a different one is refused instead of trusted on first use.

What the module sets up:

- **The container**, with the root filesystem read-only (only `~`, `/tmp` and `/run` are writable), every Linux
  capability dropped except the five sshd needs to log a user in, `no-new-privileges`, and CPU, memory and process
  limits. sshd accepts only the agent's Ed25519 key, only for `agent`, with no port, agent or X11 forwarding; the
  key's `authorized_keys` file is mounted read-only, so code in the sandbox can't add keys of its own.
- **Its own network** (`10.250.250.0/24`, bridge `br-radagent`) with firewall rules: the container reaches the
  internet but not private ranges (your LAN, Tailscale's `100.64.0.0/10`, link-local), and not the server itself.
  New SSH connections are limited to 20 a minute per address.
- **Its data** in `/var/lib/radagent-sandbox`: `home/` (the agent's home, owned by UID 2000) and `host-keys/`.

Docker publishes ports with its own iptables rules, which bypass `networking.firewall`: a port published on `0.0.0.0`
is open whatever `allowedTCPPorts` says. That's why `listenAddress` defaults to `127.0.0.1`.

On another Docker host, or to try it on the Mac, `docker compose up -d --build` in this folder runs the same
container with the same limits, except the firewall rules (`keygen.sh` writes the `authorized_keys` it mounts). Its
host key is in a volume: `docker compose exec sandbox cat /etc/ssh/host_keys/ssh_host_ed25519_key.pub`.

## Connect the agent

Every route ends in the same SSH session: the agent's key, checked by sshd, and the server's host key, checked
against `SANDBOX_HOST_KEY`. What carries the connection never sees inside it.

### From the Mac, over Tailscale or the LAN

Works without opening anything, and is the quickest way to try it with the local agent (`uv run radagent --dev`).
Set `listenAddress` to the server's Tailscale IP (`tailscale ip -4`) or LAN IP and rebuild, then add to `agent/.env`:

```sh
SANDBOX_HOST=100.x.y.z
SANDBOX_PORT=2222
SANDBOX_HOST_KEY=ssh-ed25519 AAAA...
SANDBOX_SSH_KEY_PATH=.sandbox/id_ed25519
```

and check it: `uv run --project agent python scripts/smoke_sandbox.py`. It runs every tool once against the
sandbox and cleans up after itself.

The deployed agent on AgentCore isn't on your tailnet or LAN, so it needs one of the next two.

### From AgentCore, through a Cloudflare Tunnel (recommended)

The server opens no ports: `cloudflared` on the server keeps an outbound connection to Cloudflare, and Cloudflare
Access lets through only requests carrying a service token. The agent connects with
`cloudflared access ssh --hostname ... --service-token-id ... --service-token-secret ...`, so it has to get past
three checks: the Access token, then sshd's key check, then its own host key check. Cloudflare relays the SSH stream
but can't read it, since SSH is encrypted end to end (unlike HTTPS proxying, where Cloudflare decrypts at its edge).
Your server's IP stays hidden.

Note that orange-cloud DNS proxying alone doesn't help here: it only proxies HTTP(S). SSH needs the Tunnel.

1. **Create the tunnel** (skip if you already run one; just add the ingress rule below to it):

   ```sh
   cloudflared tunnel login
   cloudflared tunnel create radagent-sandbox          # writes ~/.cloudflared/<tunnel id>.json
   cloudflared tunnel route dns radagent-sandbox sandbox.example.com
   sudo install -D -m 600 ~/.cloudflared/<tunnel id>.json /var/lib/cloudflared/<tunnel id>.json
   ```

2. **Run it on the server**, pointing the hostname at the sandbox's SSH port on localhost:

   ```nix
   services.cloudflared = {
     enable = true;
     tunnels."<tunnel id>" = {
       credentialsFile = "/var/lib/cloudflared/<tunnel id>.json";
       ingress."sandbox.example.com" = "ssh://127.0.0.1:2222";
       default = "http_status:404";
     };
   };
   ```

   `listenAddress` stays `127.0.0.1`. Write `127.0.0.1` rather than `localhost`, which may resolve to IPv6 first,
   where Docker doesn't listen.

   NixOS 24.05 and older run cloudflared as a `cloudflared` user, which can't read the root-only credentials file.
   Have systemd hand it a copy, as newer releases do:

   ```nix
   services.cloudflared.tunnels."<tunnel id>".credentialsFile =
     "/run/credentials/cloudflared-tunnel-<tunnel id>.service/credentials.json";
   systemd.services."cloudflared-tunnel-<tunnel id>".serviceConfig.LoadCredential =
     [ "credentials.json:/var/lib/cloudflared/<tunnel id>.json" ];
   ```

3. **Put Access in front of it**, in the Cloudflare dashboard under Zero Trust, before the tunnel connects:
   - Access > Service credentials > Service Tokens: create one, e.g. `radagent`, and copy its Client ID and Client
     Secret (the secret is shown once). Give it a duration you'll remember to renew, e.g. a year.
   - Access > Applications: add a **self-hosted** application for `sandbox.example.com`, with one policy whose action
     is **Service Auth** and which includes that service token. Nothing else gets through.

   Check it: `curl -s -o /dev/null -w '%{http_code}\n' https://sandbox.example.com` prints 403 without the token. A
   200, or a 1033 error page while the tunnel is down, means no application covers the hostname. Through the tunnel
   every connection comes from this host, so the per-address rate limit doesn't apply, and Access is what keeps
   strangers away from sshd.

4. **Give the agent the settings**, in `agent/.env`:

   ```sh
   SANDBOX_HOST=sandbox.example.com
   SANDBOX_HOST_KEY=ssh-ed25519 AAAA...
   SANDBOX_SSH_KEY_PATH=.sandbox/id_ed25519
   SANDBOX_CF_ACCESS_CLIENT_ID=....access
   SANDBOX_CF_ACCESS_CLIENT_SECRET=...
   ```

   Check it from the Mac first (`brew install cloudflared`, then the smoke test), then `scripts/put-secrets.sh`
   copies them, the key file included, into the agent's secret on AWS. It replaces the whole secret with what
   `agent/.env` has, so first make sure `.env` holds every key the secret does now. A running session picks them up within a
   minute. The agent's image already has `cloudflared` (`agent/Dockerfile`).

### From AgentCore, straight to an open port

If you'd rather not use Cloudflare: forward a port on your router (any high port, e.g. 22022) to the server's 2222,
set `listenAddress = "0.0.0.0"` (or the LAN address the router forwards to), and use your public address or a
dynamic DNS name as `SANDBOX_HOST`, with that port as `SANDBOX_PORT`. The SSH checks are the same; what you accept is
that anyone can reach sshd and see the server's IP. Only keys are accepted, so there's nothing to guess, and the rate
limit slows scanners down; but a hole in sshd itself would be exposed, so keep the image current (see below).

AgentCore's public network mode gives the agent no fixed address, so you can't allowlist it. Moving the runtime into
a VPC with a NAT gateway gives it one Elastic IP, which `allowedSources = [ "<that IP>/32" ];` then makes the only
address that can connect.

## Security model

| Layer                    | Protects against                                                                       |
| ------------------------ | -------------------------------------------------------------------------------------- |
| Cloudflare Access token  | Anyone reaching sshd at all (Tunnel route only)                                         |
| Agent's Ed25519 key      | Anyone else logging in; it lives only in `agent/.sandbox` and the agent's AWS secret    |
| Pinned host key          | Someone in the middle posing as the server: no trust on first use                       |
| SSH itself               | Reading or changing the session on the way, Cloudflare included                         |
| Container limits         | Code in the sandbox reaching the server: no root, no capabilities, read-only system     |
| Network rules            | Code in the sandbox reaching your LAN, tailnet or the server's other services           |
| The agent's trust gate   | Prompt injection: once a chat reads web content from outside `TRUSTED_DOMAINS`, every sandbox tool but `sandbox_status` turns off for that chat, as `shell` does |

What you still accept: the sandbox has the internet, so code running there can download things and send things out,
and anything you put in the sandbox can leave with it. The agent's key on AWS can log in until you remove it from
`authorizedKeys`. The sandbox shares the server's CPU, memory and disk (within the limits).

The trust gate is the one that costs something day to day: a chat that searched the web can't use the sandbox. The
sandbox holds no credentials and can't reach your network, so loosening that later is a reasonable trade, but it's a
decision for later.

## Running it

- **Rotate the agent's key:** run `keygen.sh` after deleting `agent/.sandbox/`, add the new public key to
  `authorizedKeys` next to the old one, rebuild, update `agent/.env` and run `scripts/put-secrets.sh`, then remove
  the old key and rebuild again. Rotate the Access service token the same way: create the new one, add it to the
  policy, update the settings, delete the old one.
- **Update the image:** it's rebuilt when `image/` changes. To pick up Ubuntu's security updates without a change,
  remove it and restart: `docker rmi $(docker images -q radagent-sandbox) ; systemctl restart docker-radagent-sandbox`.
- **Logins:** `journalctl -u docker-radagent-sandbox | grep Accepted` lists every login with its key's fingerprint.
- **Start over:** stop the service and delete `/var/lib/radagent-sandbox/home`; keep `host-keys/` unless you mean to
  change the host key (then update `SANDBOX_HOST_KEY`).
- **Background jobs** live in `~/.radagent/jobs/<id>/` (command, output, exit status) and keep running when the agent
  disconnects. Restarting the container ends them.

## Plan

Steps to get from this code to the deployed agent using the sandbox. Each one ends in a check before the next starts.

**0. Code (this change).** The image, the NixOS module, the agent's tools and trust gate, the settings in
`scripts/put-secrets.sh`, `cloudflared` in the agent's image, and CI that builds the sandbox and runs the smoke test
against it with the agent's tools.

**1. Sandbox on the server, nothing exposed.** `keygen.sh`, import the module, `nixos-rebuild switch`.
*Check:* on the server, `ssh -i <key> -p 2222 agent@127.0.0.1 uname -a`, with the private key copied over for the
test and deleted after, or the smoke test from the next step.

**2. The local agent uses it.** `listenAddress` on the Tailscale or LAN address, the settings in `agent/.env`.
*Check:* `scripts/smoke_sandbox.py` passes; in the app (`--dev`), "run a quick benchmark on my server" works.

**3. The deployed agent uses it, through the Tunnel.** The tunnel, its ingress, the Access application and service
token, `listenAddress` back on `127.0.0.1`, the settings pushed with `scripts/put-secrets.sh`, and a deploy so the
image has `cloudflared`.
*Check:* the smoke test from the Mac through the tunnel passes; then in the released app, `sandbox_status` reports
the server; from outside, a plain `ssh -p 2222` to the server's public IP gets no answer.

**4. Later, as needed.**
- Decide whether the sandbox stays off in chats that read the web (see the security model).
- Short-lived SSH certificates (an SSH CA, or Cloudflare's short-lived certificates) instead of a long-lived key.
- A timer that rebuilds the image weekly for security updates.
- A separate workspace per chat, if chats start stepping on each other's files in `~/work`.
- A disk quota for `home/` (a separate filesystem or an XFS project quota), since only CPU, memory and processes
  are limited now.
