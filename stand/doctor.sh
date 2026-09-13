#!/usr/bin/env bash
# Checks environment readiness before a demo. Never fails — summarizes what's
# missing. Prints what each check actually does ("mechanics are visible",
# AGENTS.md principle).
set -uo pipefail

GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; NC=$'\033[0m'
missing=0

# check <label> <probe-command> <hint-if-missing>
check() {
	local label="$1" probe="$2" hint="${3:-}"
	if eval "$probe" >/dev/null 2>&1; then
		printf "  ${GREEN}✓${NC} %-22s %s\n" "$label" "$(eval "$probe" 2>/dev/null | head -1)"
	else
		printf "  ${RED}✗${NC} %-22s ${YELLOW}%s${NC}\n" "$label" "$hint"
		missing=$((missing + 1))
	fi
}

echo "Tools:"
check "python3"  "python3 --version"        "needs Python 3 (delta.py and test suite)"
check "make"     "make --version"           "needs GNU make"
check "vagrant"  "vagrant --version"        "for make up/up-lite (full stand)"
check "virtualbox" "VBoxManage --version"   "Vagrant needs a provider (VirtualBox)"
check "ansible"  "ansible --version"        "for make patch/rollout/waf"
check "trivy"    "trivy --version"          "for make scan-before/after (else falls back to scan/examples)"
check "docker"   "docker --version"         "for the monitoring stack and the local WordPress lab"

echo "Test dependencies (optional, for make verify):"
check "pytest"   ".venv/bin/python3 -m pytest --version 2>/dev/null || python3 -m pytest --version" "make init  (creates .venv with requirements-dev.txt)"

echo "Stand files:"
check "scan examples" "test -f scan/examples/scan-before.json -a -f scan/examples/scan-after.json" "no Trivy examples — make delta won't work"
check "results dir" "test -d results || mkdir -p results && test -d results" "couldn't create results"
check "delta.py"       "test -f scan/delta.py"     "scan/delta.py is missing"

echo
if [ "$missing" -eq 0 ]; then
	printf "${GREEN}Ready: everything is in place.${NC}\n"
else
	printf "${YELLOW}Missing items: %s. The demo is partially available (see hints above).${NC}\n" "$missing"
fi
# Always exits 0: doctor informs, it doesn't block.
exit 0
