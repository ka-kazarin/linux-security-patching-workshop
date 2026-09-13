#!/usr/bin/env python3
"""Print links to the stand's web UIs.

IPs come from nodes.json (the same file the Vagrantfile reads) so this
never drifts out of sync with the actual topology (DRY).
"""
import json
import os

GREEN = "\033[0;32m"
NC = "\033[0m"

NODES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodes.json")

with open(NODES_PATH) as f:
    nodes = json.load(f)

for env in ("stage", "prod"):
    key = f"web-{env}"
    if key not in nodes:
        continue
    web_ip = nodes[key]["ip"]
    print(f"  WordPress ({env:<7}) : {GREEN}http://{web_ip}{NC}")
    print(f"  wp-admin ({env:<7})  : {GREEN}http://{web_ip}/wp-admin{NC}  (creds: make creds)")

# Grafana runs on its own `mon` node (stand/Vagrantfile: monitoring.sh is
# provisioned there only), up in both profiles including lite.
print(f"  Grafana             : {GREEN}http://{nodes['mon']['ip']}:3000{NC}")
print(f"  Delta report        : {GREEN}results/delta.html{NC}")
