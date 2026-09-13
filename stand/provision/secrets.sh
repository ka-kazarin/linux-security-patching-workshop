# Sourced by db.sh / web-app.sh (not a provisioner itself). Loads
# stand/secrets.json (mounted at /vagrant/secrets.json, since /vagrant is
# stand/) into shell vars, so the demo credentials live in one file instead
# of being duplicated across provisioning scripts.
SECRETS_FILE="${SECRETS_FILE:-/vagrant/secrets.json}"
eval "$(python3 -c "
import json
d = json.load(open('$SECRETS_FILE'))
for k, v in d.items():
    print(f'{k}={v!r}')
")"
