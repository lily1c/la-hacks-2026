#!/usr/bin/env bash
# Run on the Ubuntu VM from this checkout. Does not change cloud firewall rules.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Linux ]]; then
  echo 'Run this installer on the Ubuntu VM.' >&2
  exit 1
fi
sudo apt-get update
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 python3
sudo systemctl enable --now docker
if [[ ! -f cloud/.env && ! -f cloud/mediamtx.generated.yml ]]; then
  sudo python3 cloud/configure.py
fi
sudo docker compose -f cloud/compose.yaml up -d --build relay snapshots
sudo docker compose -f cloud/compose.yaml ps
