#!/usr/bin/env bash
# Common provisioning for every node: /etc/hosts, base packages, a run marker.
# Idempotent: safe to run repeatedly (Vagrant re-runs provisioners).
# Declared at the top level of the Vagrantfile — applies to every node without
# repeating it in each node.vm.define block.
set -euo pipefail

# /etc/hosts for name-based addressing instead of IPs — this lets web-app.sh
# reach its DB as "db-${env}" without hardcoding the stand's address, and
# without mixing up stage/prod (see web-app.sh; deriving the IP via
# `ip -4` is redundant once this is in place).
# Static: every possible node of the profile, whether or not it's actually up
# — an unresolved entry is harmless if that host isn't part of this session.
entries=(
	"192.168.56.10 web-stage"
	"192.168.56.11 db-stage"
	"192.168.56.20 web-prod"
	"192.168.56.21 db-prod"
)
for entry in "${entries[@]}"; do
	grep -qF "$entry" /etc/hosts || echo "$entry" >> /etc/hosts
done

STAMP=/var/lib/stand-common.done
if [ -f "$STAMP" ]; then
	echo "common: base packages already configured, skipping"
	exit 0
fi

# Pick the package manager by distro family (apt vs dnf).
if command -v apt-get >/dev/null 2>&1; then
	export DEBIAN_FRONTEND=noninteractive
	apt-get update -y
	apt-get install -y curl ca-certificates
elif command -v dnf >/dev/null 2>&1; then
	dnf install -y curl ca-certificates
fi

touch "$STAMP"
echo "common: done"
