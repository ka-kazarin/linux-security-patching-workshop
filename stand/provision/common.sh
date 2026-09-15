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
	"192.168.56.30 mon"
)
for entry in "${entries[@]}"; do
	grep -qF "$entry" /etc/hosts || echo "$entry" >> /etc/hosts
done

STAMP=/var/lib/stand-common.done
if [ -f "$STAMP" ]; then
	echo "common: base packages already configured, skipping"
else
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
fi

# --- node_exporter (native, every node) -----------------------------------
# Metrics for the continuity dashboard (mon's Prometheus scrapes :9100 on
# every node). Native, not a container: the old setup ran node_exporter as a
# single container on web-stage, which could only ever see web-stage's own
# kernel — no per-node uptime. A pinned static binary is identical across
# Ubuntu and Oracle Linux (Go binary, no distro packaging needed), so this
# lives here in common.sh rather than being duplicated in web-app.sh/db.sh/
# monitoring.sh (DRY — one cross-distro install, one place).
NODE_EXPORTER_VERSION="1.12.1"  # latest release, verified live against
# https://api.github.com/repos/prometheus/node_exporter/releases/latest
NODE_EXPORTER_BIN=/usr/local/bin/node_exporter
if [ -x "$NODE_EXPORTER_BIN" ] && systemctl is-active --quiet node_exporter 2>/dev/null; then
	echo "common: node_exporter already installed and running, skipping"
else
	ARCH="$(uname -m)"
	case "$ARCH" in
		x86_64) NE_ARCH="amd64" ;;
		aarch64) NE_ARCH="arm64" ;;
		*) echo "common: unsupported arch $ARCH for node_exporter" >&2; exit 1 ;;
	esac
	NE_TARBALL="node_exporter-${NODE_EXPORTER_VERSION}.linux-${NE_ARCH}.tar.gz"
	NE_URL="https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/${NE_TARBALL}"
	curl -fsSL "$NE_URL" -o "/tmp/${NE_TARBALL}"
	tar -xzf "/tmp/${NE_TARBALL}" -C /tmp
	install -m 0755 "/tmp/node_exporter-${NODE_EXPORTER_VERSION}.linux-${NE_ARCH}/node_exporter" "$NODE_EXPORTER_BIN"
	rm -rf "/tmp/${NE_TARBALL}" "/tmp/node_exporter-${NODE_EXPORTER_VERSION}.linux-${NE_ARCH}"

	if ! id node_exporter >/dev/null 2>&1; then
		useradd --no-create-home --shell /usr/sbin/nologin node_exporter 2>/dev/null \
			|| useradd --no-create-home --shell /sbin/nologin node_exporter
	fi

	cat > /etc/systemd/system/node_exporter.service <<-'EOF'
	[Unit]
	Description=Prometheus node_exporter
	After=network.target

	[Service]
	User=node_exporter
	ExecStart=/usr/local/bin/node_exporter
	Restart=on-failure

	[Install]
	WantedBy=multi-user.target
	EOF

	systemctl daemon-reload
	systemctl enable --now node_exporter
	echo "common: node_exporter ${NODE_EXPORTER_VERSION} installed and running on :9100"
fi

# Oracle Linux ships firewalld on by default (see db.sh's 3306 rule); Ubuntu
# boxes here don't run ufw. Open 9100 for the stand's own subnet only, same
# rich-rule pattern as db.sh, so mon can actually reach it.
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
	if ! firewall-cmd --list-rich-rules | grep -q 'port="9100"'; then
		firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.56.0/24" port protocol="tcp" port="9100" accept'
		firewall-cmd --reload
		echo "common: firewalld — opened 9100 for 192.168.56.0/24"
	fi
fi

# --- Pre-install demo tools at provisioning time (not on the webinar clock) --
# scan.yml/bench.yml still install these idempotently as a safety net, but
# doing it here means `make up` (run well ahead of the demo) pays the cost,
# and the live `make scan-*` / `make bench-*` start instantly. Scoped by host
# role: mon neither scans nor is load-tested, so it gets none of it.
install_trivy() {
	if [ ! -x /usr/local/bin/trivy ]; then
		# Same official prebuilt-binary install scan.yml uses (idempotent).
		curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh \
			| sh -s -- -b /usr/local/bin
	fi
	# Warm the vulnerability DB (root's cache, same user the scan runs as) so
	# the first live scan doesn't spend time downloading it.
	/usr/local/bin/trivy image --download-db-only >/dev/null 2>&1 || true
}

case "$(hostname)" in
	web-*)
		install_trivy
		if ! command -v wrk >/dev/null 2>&1; then   # web load baseline (bench.yml)
			export DEBIAN_FRONTEND=noninteractive
			apt-get install -y wrk || true
		fi
		echo "common: pre-installed trivy + wrk (web)"
		;;
	db-*)
		install_trivy
		if ! command -v sysbench >/dev/null 2>&1; then   # MySQL load baseline (bench.yml)
			dnf install -y epel-release || true
			dnf install -y sysbench || true
		fi
		echo "common: pre-installed trivy + sysbench (db)"
		;;
	*)
		echo "common: $(hostname) — no scan/bench tools needed"
		;;
esac
