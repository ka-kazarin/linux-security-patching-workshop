#!/usr/bin/env bash
# Monitoring stack: Prometheus + Grafana + exporters via docker-compose.
# Brought up AHEAD OF TIME: during the webinar we show a ready dashboard, no
# airtime spent installing it. Idempotent
# (compose up -d).
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
	# Install Docker Engine (Ubuntu). Once.
	export DEBIAN_FRONTEND=noninteractive
	apt-get update -y
	apt-get install -y docker.io docker-compose-v2
	systemctl enable --now docker
fi

# Registry mirrors — guards against Docker Hub rate limits when many students
# pull the same images (Prometheus/Grafana/exporters) at once from home.
if [ ! -f /etc/docker/daemon.json ]; then
	mkdir -p /etc/docker
	printf '{"registry-mirrors":["https://mirror.gcr.io"]}\n' > /etc/docker/daemon.json
	systemctl restart docker
fi

# Dashboards and datasources — provisioned from files in the repo (no manual UI).
# /monitoring is a separate synced_folder (see Vagrantfile): /vagrant only
# mounts stand/, and monitoring/ lives one level up.
docker compose -f /monitoring/docker-compose.yml up -d
echo "monitoring: stack is up (Grafana on :3000)"

# TODO: confirm node_exporter/blackbox_exporter targets can see the web/db
# nodes on the host-only network; livepatch dashboard with 3-4 panels.
