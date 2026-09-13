#!/usr/bin/env bash
# Web+app node (Ubuntu): nginx + PHP-FPM + a deliberately vulnerable WordPress
# 7.0.0. The vulnerability is intentional — the demo target (wp2shell,
# exploit/README.md). Only in the isolated host-only network (SECURITY.md).
# The demo passwords below (WP_DB_PASS) are intentionally insecure — SECURITY.md.
# Idempotent.
set -euo pipefail

WP_VERSION="7.0.0"          # vulnerable to wp2shell (CVE-2026-63030/-60137); patch -> 7.0.2
WP_TARBALL_VERSION="${WP_VERSION%.0}"  # wordpress.org drops the trailing .0 in tarball names (7.0.0 -> 7.0)
WP_ROOT="/var/www/html"
# Address the DB by hostname (db-stage/db-prod), not IP — a shared /etc/hosts
# is set up in common.sh. web-stage -> db-stage, web-prod -> db-prod
# automatically, no risk of mixing up environments (used to be a hardcoded
# db-stage IP for both).
DB_HOST="$(hostname | sed 's/^web-/db-/')"
# shellcheck disable=SC1091
source /vagrant/provision/secrets.sh   # WP_DB_NAME/USER/PASS, WP_ADMIN_USER/PASS/EMAIL
FILES_DIR="/vagrant/provision/files"
export DEBIAN_FRONTEND=noninteractive

# --- nginx + PHP-FPM ---------------------------------------------------------
if ! command -v nginx >/dev/null 2>&1; then
	apt-get update -y
	apt-get install -y nginx php-fpm php-mysql curl
fi

# PHP-FPM listens on a unix socket with a predictable path (simplifies the nginx config).
PHP_POOL_CONF=$(find /etc/php -maxdepth 3 -name "www.conf" 2>/dev/null | head -1)
if [ -n "$PHP_POOL_CONF" ] && ! grep -q "^listen = /run/php/php-fpm.sock" "$PHP_POOL_CONF"; then
	sed -i 's#^listen = .*#listen = /run/php/php-fpm.sock#' "$PHP_POOL_CONF"
	systemctl restart php*-fpm 2>/dev/null || true
fi

if [ ! -L /etc/nginx/sites-enabled/wordpress ]; then
	cp "$FILES_DIR/nginx-wordpress.conf" /etc/nginx/sites-available/wordpress
	rm -f /etc/nginx/sites-enabled/default
	ln -sf /etc/nginx/sites-available/wordpress /etc/nginx/sites-enabled/wordpress
	systemctl reload nginx
fi

# --- WordPress (intentionally vulnerable version) -----------------------------
if [ ! -f "$WP_ROOT/wp-includes/version.php" ]; then
	# WARNING: intentionally vulnerable version. Never expose to a real network.
	curl -fsSL "https://wordpress.org/wordpress-${WP_TARBALL_VERSION}.tar.gz" -o /tmp/wp.tgz
	tar -xzf /tmp/wp.tgz -C /tmp
	cp -a /tmp/wordpress/. "$WP_ROOT/"
	rm -rf /tmp/wp.tgz /tmp/wordpress
	echo "web-app: deployed WordPress ${WP_VERSION} (vulnerable, for the demo)"
else
	echo "web-app: WordPress already deployed, skipping"
fi

if [ ! -f "$WP_ROOT/wp-config.php" ]; then
	cp "$WP_ROOT/wp-config-sample.php" "$WP_ROOT/wp-config.php"
	sed -i "s/database_name_here/${WP_DB_NAME}/" "$WP_ROOT/wp-config.php"
	sed -i "s/username_here/${WP_DB_USER}/" "$WP_ROOT/wp-config.php"
	sed -i "s/password_here/${WP_DB_PASS}/" "$WP_ROOT/wp-config.php"
	sed -i "s/localhost/${DB_HOST}/" "$WP_ROOT/wp-config.php"
	# Pin the version deliberately: WordPress's own background updater would
	# otherwise silently upgrade core past the vulnerable release the demo
	# relies on (observed live: a VM left running a few days drifted from
	# 7.0.0 to 7.1.0 on its own, breaking the exploit).
	sed -i "/^\/\* That's all, stop editing/i define('WP_AUTO_UPDATE_CORE', false);" "$WP_ROOT/wp-config.php"
	echo "web-app: wp-config.php created (DB at ${DB_HOST}, core auto-update disabled)"
fi

chown -R www-data:www-data "$WP_ROOT"

# --- wp-cli: finish the install without a manual wizard ------------------------
if [ ! -x /usr/local/bin/wp ]; then
	curl -fsSL https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar -o /usr/local/bin/wp
	chmod +x /usr/local/bin/wp
fi

# Wait for the DB node: web-app and db come up in parallel, DB may start later.
for i in $(seq 1 30); do
	sudo -u www-data wp --path="$WP_ROOT" db check >/dev/null 2>&1 && break
	sleep 2
done

if ! sudo -u www-data wp --path="$WP_ROOT" core is-installed >/dev/null 2>&1; then
	# Explicitly pick the host-only address (not the NAT interface) — the site
	# must resolve on it.
	HOST_ONLY_IP=$(ip -4 -o addr show | awk '/192\.168\.56\./{print $4}' | cut -d/ -f1 | head -1)
	sudo -u www-data wp --path="$WP_ROOT" core install \
		--url="http://${HOST_ONLY_IP}" \
		--title="Stand: Vulnerability Management" \
		--admin_user="${WP_ADMIN_USER}" --admin_password="${WP_ADMIN_PASS}" \
		--admin_email="${WP_ADMIN_EMAIL}" --skip-email
	echo "web-app: WordPress installed (creds: make creds — SECURITY.md)"
else
	echo "web-app: WordPress already installed, skipping"
fi

# --- ModSecurity (WAF virtual patch: make waf-on/waf-off) ----------------------
# Engine on, rules directory empty by default — `make waf-on` drops in the
# narrow wp2shell CVE rule (waf/modsecurity/wp2shell.conf), `make waf-off`
# removes it. Installing the engine here (not in waf.yml) so the rules
# directory always exists, regardless of whether waf-on has ever run.
if ! dpkg -s libnginx-mod-http-modsecurity >/dev/null 2>&1; then
	# Just the engine, not modsecurity-crs: the OWASP Core Rule Set is
	# hundreds of generic rules and false-positive-prone — the opposite of
	# this stand's "narrow, single-CVE rule" point.
	apt-get install -y libnginx-mod-http-modsecurity
	mkdir -p /etc/modsecurity/rules
	# ModSecurity's Include, unlike Apache's, errors out on a glob that
	# matches zero files — found live via nginx -t on an empty rules/ dir.
	# A placeholder keeps the glob non-empty regardless of waf-on/waf-off.
	echo "# placeholder so Include /etc/modsecurity/rules/*.conf never matches zero files" \
		> /etc/modsecurity/rules/00-placeholder.conf
	# The connector package ships its base config at /etc/nginx/modsecurity.conf
	# (not /etc/modsecurity/modsecurity.conf-recommended — that path doesn't
	# exist on this system; found by reading the actual nginx -t error).
	sed -i 's/SecRuleEngine DetectionOnly/SecRuleEngine On/' /etc/nginx/modsecurity.conf
	cat > /etc/modsecurity/main.conf <<-'EOF'
	Include /etc/nginx/modsecurity.conf
	Include /etc/modsecurity/rules/*.conf
	EOF
	if ! grep -q "modsecurity on;" /etc/nginx/sites-available/wordpress 2>/dev/null; then
		sed -i '/root \/var\/www\/html;/a\\tmodsecurity on;\n\tmodsecurity_rules_file /etc/modsecurity/main.conf;' \
			/etc/nginx/sites-available/wordpress
	fi
	systemctl reload nginx
	echo "web-app: ModSecurity installed (engine on, rules dir empty until make waf-on)"
else
	echo "web-app: ModSecurity already installed, skipping"
fi
