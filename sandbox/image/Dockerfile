# The sandbox the agent runs code in: an Ubuntu LTS box reached over SSH, where it writes, runs and tests code and runs
# long jobs. sshd runs as root only to log the agent in; everything the agent runs is the unprivileged `agent` user,
# without sudo. See ../README.md
#   docker build -t radagent-sandbox .      (the NixOS module and docker-compose.yml build it for you)
# Plain Dockerfile syntax only, so it also builds without BuildKit

FROM ubuntu:26.04

# A toolbox for writing and testing code; anything else the agent installs per project (uv, venvs, npm) in its home
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openssh-server tini ca-certificates \
        bash-completion build-essential pkg-config git curl wget jq ripgrep fd-find tree less vim-tiny file \
        unzip zip xz-utils bzip2 rsync sqlite3 procps psmisc lsof iproute2 dnsutils time \
        python3 python3-dev python3-venv python3-pip \
        nodejs npm \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* \
    && rm -f /etc/ssh/ssh_host_*

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /usr/local/bin/

# A fixed UID so the home directory on the host can be owned by it (the NixOS module and docker-compose.yml use 2000).
# The password field is "*" rather than useradd's "!", which sshd without PAM would read as a locked account
RUN groupadd --gid 2000 agent \
    && useradd --uid 2000 --gid 2000 --create-home --shell /bin/bash agent \
    && usermod --password '*' agent \
    && mkdir -p /etc/ssh/host_keys /etc/ssh/authorized_keys

COPY sshd_config /etc/ssh/sshd_config
COPY profile.sh /etc/profile.d/radagent.sh
COPY entrypoint.sh /usr/local/bin/entrypoint
RUN chmod 644 /etc/ssh/sshd_config /etc/profile.d/radagent.sh && chmod 755 /usr/local/bin/entrypoint

# Host keys persist in this volume, so the key the agent pins stays the same across rebuilds
VOLUME ["/etc/ssh/host_keys", "/home/agent"]
EXPOSE 2222

# tini reaps the agent's background jobs once they finish
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint"]
