#!/usr/bin/env python3
"""Print the stand's demo credentials.

Intentionally weak, single source of truth in stand/secrets.json (read by
web-app.sh/db.sh during provisioning too) — see SECURITY.md.
"""
import json
import os

YELLOW = "\033[0;33m"
NC = "\033[0m"

SECRETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secrets.json")

with open(SECRETS_PATH) as f:
    s = json.load(f)

print(f"  WordPress admin (/wp-admin): {s['WP_ADMIN_USER']} / {YELLOW}{s['WP_ADMIN_PASS']}{NC}")
print(f"  MySQL ({s['WP_DB_NAME']} database)   : {s['WP_DB_USER']} / {YELLOW}{s['WP_DB_PASS']}{NC}")
print("  Demo-only, intentionally weak — see SECURITY.md.")
