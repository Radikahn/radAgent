# The sandbox as a NixOS service: builds the image in ./image, runs it with Docker and keeps it off your network.
# Import it from your configuration and turn it on; see README.md
#
#   imports = [ /path/to/radAgent/sandbox/nixos.nix ];
#   services.radagent-sandbox = {
#     enable = true;
#     authorizedKeys = [ "ssh-ed25519 AAAA... radagent" ];   # sandbox/keygen.sh prints it
#   };
#
# What it sets up:
#   - radagent-sandbox-image.service  builds the image when ./image changes (tagged by its hash)
#   - radagent-sandbox-net.service    the container's own Docker network, and firewall rules that keep the container
#                                     away from your LAN and this host, and rate limit new SSH connections
#   - docker-radagent-sandbox.service the container itself, via virtualisation.oci-containers
#
# Docker publishes ports with its own iptables rules, which bypass networking.firewall: a port published on 0.0.0.0
# is open whatever allowedTCPPorts says. So the container listens on 127.0.0.1 unless you set listenAddress

{ config, lib, pkgs, ... }:

let
  cfg = config.services.radagent-sandbox;

  # The image is tagged by the hash of its source, so editing ./image rebuilds it and nothing else does
  imageSrc = ./image;
  imageTag = "radagent-sandbox:${builtins.substring 0 12 (builtins.hashString "sha256" "${imageSrc}")}";

  # The UID and GID the image gives the agent user (image/Dockerfile)
  agentId = 2000;
  containerPort = 2222;
  bridge = "br-radagent";
  chain = "RADAGENT-SANDBOX";

  # `restrict` turns off forwarding and the rest for this key on top of sshd_config; `pty` gives terminals back
  authorizedKeysFile = pkgs.writeText "radagent-sandbox-authorized-keys"
    (lib.concatMapStrings (key: "restrict,pty ${key}\n") cfg.authorizedKeys);

  privateRanges = [ "10.0.0.0/8" "172.16.0.0/12" "192.168.0.0/16" "100.64.0.0/10" "169.254.0.0/16" "224.0.0.0/4" ];

  iptables = "${pkgs.iptables}/bin/iptables";
  docker = "${config.virtualisation.docker.package}/bin/docker";

  # Every rule lives in our own chain, jumped to from DOCKER-USER (forwarded traffic) and INPUT (traffic to this
  # host), so starting the service again replaces them and stopping it removes them
  firewallUp = pkgs.writeShellScript "radagent-sandbox-firewall-up" ''
    set -euo pipefail
    ${iptables} -w -N ${chain} 2>/dev/null || ${iptables} -w -F ${chain}
    ${iptables} -w -N ${chain}-IN 2>/dev/null || ${iptables} -w -F ${chain}-IN

    # Replies to connections that were allowed
    ${iptables} -w -A ${chain} -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN

    # New SSH connections into the container, at most ${toString cfg.connectionsPerMinute} a minute from one address
    ${iptables} -w -A ${chain} -o ${bridge} -p tcp --dport ${toString containerPort} -m conntrack --ctstate NEW \
      -m hashlimit --hashlimit-above ${toString cfg.connectionsPerMinute}/minute --hashlimit-burst ${toString cfg.connectionsPerMinute} \
      --hashlimit-mode srcip --hashlimit-name radagent-sandbox -j DROP
    ${lib.optionalString (cfg.allowedSources != [ ]) ''
      ${lib.concatMapStrings (source: ''
        ${iptables} -w -A ${chain} -o ${bridge} -p tcp --dport ${toString containerPort} -s ${source} -j RETURN
      '') cfg.allowedSources}
      ${iptables} -w -A ${chain} -o ${bridge} -j DROP
    ''}

    ${lib.optionalString cfg.blockPrivateNetworks ''
      # The container reaches the internet, not your LAN, your tailnet or link-local services
      ${lib.concatMapStrings (range: ''
        ${iptables} -w -A ${chain} -i ${bridge} -d ${range} -j DROP
      '') privateRanges}
      # Nor this host: only replies to connections the host opened (e.g. cloudflared's to the container) get through
      ${iptables} -w -A ${chain}-IN -i ${bridge} -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
      ${iptables} -w -A ${chain}-IN -i ${bridge} -j DROP
    ''}
    ${iptables} -w -A ${chain} -j RETURN

    ${iptables} -w -N DOCKER-USER 2>/dev/null || true
    ${iptables} -w -C DOCKER-USER -j ${chain} 2>/dev/null || ${iptables} -w -I DOCKER-USER -j ${chain}
    ${iptables} -w -C INPUT -j ${chain}-IN 2>/dev/null || ${iptables} -w -I INPUT -j ${chain}-IN
  '';

  firewallDown = pkgs.writeShellScript "radagent-sandbox-firewall-down" ''
    ${iptables} -w -D DOCKER-USER -j ${chain} 2>/dev/null || true
    ${iptables} -w -D INPUT -j ${chain}-IN 2>/dev/null || true
    ${iptables} -w -F ${chain} 2>/dev/null || true
    ${iptables} -w -X ${chain} 2>/dev/null || true
    ${iptables} -w -F ${chain}-IN 2>/dev/null || true
    ${iptables} -w -X ${chain}-IN 2>/dev/null || true
  '';
in
{
  options.services.radagent-sandbox = {
    enable = lib.mkEnableOption "the radagent sandbox, a container the agent runs code in over SSH";

    authorizedKeys = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      example = [ "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... radagent" ];
      description = ''
        Public keys allowed to log in as the sandbox's agent user, one "ssh-ed25519 ..." line each: the agent's
        (sandbox/keygen.sh makes it), and during a rotation the new one too.
      '';
    };

    listenAddress = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      example = "0.0.0.0";
      description = ''
        Where the host publishes the container's SSH port. 127.0.0.1 is enough with a Cloudflare Tunnel, whose
        cloudflared runs on this host. Use the host's LAN or Tailscale address (or 0.0.0.0, with a router port
        forward) to connect to it directly.
      '';
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 2222;
      description = "The host port the container's SSH is published on.";
    };

    allowedSources = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "203.0.113.7/32" "192.168.1.0/24" ];
      description = ''
        When set, only these addresses (CIDR) may open SSH connections to the container, e.g. the agent's fixed egress
        IP. Empty allows any source, which is what a Cloudflare Tunnel needs (its connections come from this host).
      '';
    };

    connectionsPerMinute = lib.mkOption {
      type = lib.types.ints.positive;
      default = 20;
      description = "New SSH connections allowed per minute from one address; the agent needs one per chat.";
    };

    blockPrivateNetworks = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Keep the container off private and link-local ranges (your LAN, Tailscale's 100.64.0.0/10) and off this
        host, so code the agent runs can reach the internet but nothing else of yours.
      '';
    };

    dns = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "1.1.1.1" "9.9.9.9" ];
      description = ''
        Resolvers the container uses. Docker sends the container's DNS queries from inside its network, so a resolver
        on your LAN (often the router) would be blocked by blockPrivateNetworks.
      '';
    };

    subnet = lib.mkOption {
      type = lib.types.str;
      # Outside Docker's own pools (172.17-172.31.0.0/16, then 192.168.0.0/16 in /20s), which a host with many
      # Compose projects fills, and Docker refuses to create a network that overlaps one it already has
      default = "10.250.250.0/24";
      description = "The container's Docker network; change it if it overlaps one you already use.";
    };

    dataDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/radagent-sandbox";
      description = "Holds the agent's home directory (home/) and the container's SSH host key (host-keys/).";
    };

    cpus = lib.mkOption {
      type = lib.types.str;
      default = "4";
      description = "CPUs the container may use (docker run --cpus).";
    };

    memory = lib.mkOption {
      type = lib.types.str;
      default = "8g";
      description = "Memory the container may use (docker run --memory); swap is not added on top.";
    };

    pids = lib.mkOption {
      type = lib.types.ints.positive;
      default = 1024;
      description = "Processes and threads the container may run at once.";
    };

    tmpSize = lib.mkOption {
      type = lib.types.str;
      default = "4g";
      description = "Size of the container's /tmp, which is in memory and counts against `memory`.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.authorizedKeys != [ ];
        message = "services.radagent-sandbox.authorizedKeys needs the agent's public key (sandbox/keygen.sh)";
      }
    ];

    virtualisation.docker.enable = true;
    virtualisation.oci-containers.backend = "docker";

    systemd.tmpfiles.rules = [
      "d ${cfg.dataDir} 0755 root root -"
      "d ${cfg.dataDir}/home 0750 ${toString agentId} ${toString agentId} -"
      "d ${cfg.dataDir}/host-keys 0700 root root -"
    ];

    systemd.services.radagent-sandbox-image = {
      description = "Build the radagent sandbox image";
      after = [ "docker.service" "network-online.target" ];
      requires = [ "docker.service" ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        TimeoutStartSec = "30min";
      };
      script = ''
        if ! ${docker} image inspect ${imageTag} >/dev/null 2>&1; then
          ${docker} build --pull --tag ${imageTag} ${imageSrc}
        fi
      '';
    };

    systemd.services.radagent-sandbox-net = {
      description = "Network and firewall rules for the radagent sandbox";
      after = [ "docker.service" "firewall.service" ];
      requires = [ "docker.service" ];
      # Docker and the firewall rebuild their chains when they restart, so the rules follow them
      partOf = [ "docker.service" "firewall.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStop = firewallDown;
      };
      script = ''
        if ! ${docker} network inspect radagent-sandbox >/dev/null 2>&1; then
          ${docker} network create --driver bridge --subnet ${cfg.subnet} \
            --opt com.docker.network.bridge.name=${bridge} radagent-sandbox
        fi
        ${firewallUp}
      '';
    };

    virtualisation.oci-containers.containers.radagent-sandbox = {
      image = imageTag;
      ports = [ "${cfg.listenAddress}:${toString cfg.port}:${toString containerPort}" ];
      volumes = [
        "${cfg.dataDir}/home:/home/agent"
        "${cfg.dataDir}/host-keys:/etc/ssh/host_keys"
        "${authorizedKeysFile}:/etc/ssh/authorized_keys/agent:ro"
      ];
      extraOptions = [
        "--network=radagent-sandbox"
        "--hostname=radagent-sandbox"
      ] ++ map (server: "--dns=${server}") cfg.dns ++ [
        # Only the agent's home, /tmp and /run can be written; system files stay as the image has them
        "--read-only"
        "--tmpfs=/tmp:rw,exec,nosuid,size=${cfg.tmpSize}"
        "--tmpfs=/run:rw,noexec,nosuid,size=16m"
        # What sshd needs to log a user in, and nothing else; the agent's own processes get none of it
        "--cap-drop=ALL"
        "--cap-add=SETUID"
        "--cap-add=SETGID"
        "--cap-add=SYS_CHROOT"
        "--cap-add=CHOWN"
        "--cap-add=KILL"
        "--security-opt=no-new-privileges"
        "--cpus=${cfg.cpus}"
        "--memory=${cfg.memory}"
        "--memory-swap=${cfg.memory}"
        "--pids-limit=${toString cfg.pids}"
        "--ulimit=nofile=65536:65536"
      ];
    };

    systemd.services.docker-radagent-sandbox = {
      after = [ "radagent-sandbox-image.service" "radagent-sandbox-net.service" ];
      requires = [ "radagent-sandbox-image.service" "radagent-sandbox-net.service" ];
    };
  };
}
