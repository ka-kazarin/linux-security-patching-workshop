#!/usr/bin/env bash
# DB node (Oracle Linux): MySQL for WordPress. A separate VM means a separate
# owner (DBA) and a separate SLA.
# The demo password below is intentionally insecure — see SECURITY.md.
# Idempotent.
set -euo pipefail

# shellcheck disable=SC1091
source /vagrant/provision/secrets.sh   # WP_DB_NAME / WP_DB_USER / WP_DB_PASS
# (Vagrant runs shell provisioners from a copied temp path, so $0 isn't
# reliable here — /vagrant is always the stand/ synced folder.)
# The stand's host-only subnet (stage + prod web nodes) — DB access from here only.
WEB_SUBNET="192.168.56.%"

# Oracle Linux 10: the package is versioned (mysql-server), not a generic mysql-server.
if ! rpm -q mysql-server >/dev/null 2>&1; then
	dnf install -y mysql-server mysql
	systemctl enable --now mysqld
	echo "db: MySQL installed and running"
else
	echo "db: MySQL already installed, skipping"
fi

# Bind to the private host-only interface, not 0.0.0.0.
BIND_IP=$(ip -4 -o addr show | awk '/192\.168\.56\./{print $4}' | cut -d/ -f1 | head -1)
if [ -n "$BIND_IP" ] && ! grep -q "^bind-address" /etc/my.cnf.d/mysql-server.cnf 2>/dev/null; then
	printf '\n[mysqld]\nbind-address = %s\n' "$BIND_IP" >> /etc/my.cnf.d/mysql-server.cnf
	systemctl restart mysqld
fi

# Idempotent: CREATE ... IF NOT EXISTS, GRANT is safe to repeat.
mysql -uroot <<SQL
CREATE DATABASE IF NOT EXISTS ${WP_DB_NAME} CHARACTER SET utf8mb4;
CREATE USER IF NOT EXISTS '${WP_DB_USER}'@'${WEB_SUBNET}' IDENTIFIED BY '${WP_DB_PASS}';
GRANT ALL PRIVILEGES ON ${WP_DB_NAME}.* TO '${WP_DB_USER}'@'${WEB_SUBNET}';
FLUSH PRIVILEGES;
SQL

echo "db: database ${WP_DB_NAME} and user ${WP_DB_USER} ready (accessible from ${WEB_SUBNET})"

# firewalld (on by default on Oracle Linux) blocks 3306 — open it only for the
# stand's host-only subnet, not for everyone (a rich rule, not a generic --add-port).
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
	if ! firewall-cmd --list-rich-rules | grep -q 'port="3306"'; then
		firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.56.0/24" port protocol="tcp" port="3306" accept'
		firewall-cmd --reload
		echo "db: firewalld — opened 3306 for 192.168.56.0/24"
	fi
fi

# TODO: backup before patching ("DB: window, backup, test cycle").
