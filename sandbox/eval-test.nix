# Evaluates nixos.nix in a minimal NixOS configuration, the way CI checks it; prints the container's start script
#   nix-instantiate --eval --strict --json sandbox/eval-test.nix | jq -r .
(import <nixpkgs/nixos> {
  configuration = {
    imports = [ ./nixos.nix ];
    boot.loader.grub.enable = false;
    fileSystems."/" = { device = "/dev/sda1"; fsType = "ext4"; };
    system.stateVersion = "25.05";
    services.radagent-sandbox = {
      enable = true;
      authorizedKeys = [ "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDOFEcdL/VdbF9bsnHPSZMPQVSYwNwsX7SFVPlx0hmJY test" ];
      allowedSources = [ "203.0.113.7/32" ];
    };
  };
}).config.systemd.services.docker-radagent-sandbox.script
