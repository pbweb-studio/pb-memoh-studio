#!/bin/bash
# Idempotent: adds one ed25519 public key to root authorized_keys (no secrets).
set +x
set -e
PUB='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICojV9rmrKPdfG1WM/3+15oPUYqCkbOS2MiLyOFt4H5D memoh-vps-45.145.168.240'
MARK='ICojV9rmrKPdfG1WM'
mkdir -p /root/.ssh
chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys
if ! grep -qF "$MARK" /root/.ssh/authorized_keys 2>/dev/null; then
  printf '%s\n' "$PUB" >>/root/.ssh/authorized_keys
fi
chmod 600 /root/.ssh/authorized_keys
echo KEY_INSTALL_DONE
