# Single entry point for the stand. Dispatch only: the real work lives in
# scan/, tests/, ansible/, stand/ (Vagrant + provisioning). Every meaningful
# target echoes the real underlying command ("mechanics are visible", AGENTS.md).

.DEFAULT_GOAL := help
SHELL := /bin/bash

GREEN  := \033[0;32m
YELLOW := \033[0;33m
RED    := \033[0;31m
BOLD   := \033[1m
NC     := \033[0m

# Environment: stage|prod everywhere (rollout always targets prod).
# scan-before/scan-after additionally accept "all" (read-only, safe to
# default wider) -- every other target keeps the conservative default
# below, since they have side effects (patching a host, attacking it,
# toggling its WAF).
ENV ?= stage
# Vuln severities Trivy scans for (make scan-before/after).
SEVERITY ?= CRITICAL,HIGH
# Command to run through the wp2shell-poc shell (make attack-shell).
CMD ?= id
# Load-baseline methodology (make bench-before/bench-after): 1 warmup run
# (discarded) + BENCH_RUNS timed runs of BENCH_DURATION seconds each, sampled
# every BENCH_INTERVAL seconds. Defaults are the boring, honest numbers for a
# real run (warmup + 2x180s takes a while) -- override on the command line
# for a quick mechanics check, e.g. BENCH_DURATION=20 BENCH_WARMUP=10.
BENCH_WARMUP   ?= 60
BENCH_DURATION ?= 180
BENCH_RUNS     ?= 2
BENCH_INTERVAL ?= 10

STAND_DIR   := stand
INVENTORY   := ansible/inventory.yml
VENV_DIR    := .venv
VENV_PYTHON := $(VENV_DIR)/bin/python3
# The web host's URL for the given ENV (stage|prod), from the same
# nodes.json make urls/Vagrantfile use — never a second hardcoded IP. Make
# expands a whole recipe (all lines) before running any of it, so this can
# get evaluated even on an invalid ENV that check_env is about to reject a
# line later -- .get(..., '') keeps that case a quiet empty string instead
# of a raw Python traceback ahead of check_env's own clean error.
WEB_URL      = $(shell python3 -c "import json; print('http://' + json.load(open('stand/nodes.json')).get('web-$(ENV)', {}).get('ip', ''))")

# Print the real command in yellow, then run it.
define run
	@printf "$(YELLOW)→ running:$(NC) %s\n" '$(1)'
	@$(1)
endef

# Fail with a clear message on a bad ENV/SCAN_ENV rather than silently
# matching zero hosts (rules/bash.md: "validate before use").
define check_env
	@case "$(ENV)" in \
		stage|prod) ;; \
		*) printf "$(RED)✗ ENV must be stage or prod (got '$(ENV)')$(NC)\n" >&2; exit 1 ;; \
	esac
endef
define check_scan_env
	@case "$(ENV)" in \
		stage|prod|all) ;; \
		*) printf "$(RED)✗ ENV must be stage, prod, or all (got '$(ENV)')$(NC)\n" >&2; exit 1 ;; \
	esac
endef

.PHONY: help banner up up-lite halt destroy urls creds scan-before scan-after attack attack-shell \
        patch patch-reboot patch-wordpress verify scan-delta bench-before bench-after bench-delta rollout \
        waf-on waf-off doctor init clean-results

banner:
	@printf "$(BOLD)"
	@echo '   ____  _     _   _ ____  __  __'
	@echo '  / ___|| |   | | | |  _ \|  \/  |   Vulnerability Management'
	@echo '  \___ \| |   | | | | |_) | |\/| |   training stand · Slurm'
	@echo '   ___) | |___| |_| |  _ <| |  | |'
	@echo '  |____/|_____|\___/|_| \_\_|  |_|'
	@printf "$(NC)\n"

help: banner ## show this help
	@printf "$(BOLD)Commands:$(NC)\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN{FS=":.*?## "}{printf "  $(GREEN)%-14s$(NC) %s\n", $$1, $$2}'
	@printf "\nVariables: $(BOLD)ENV=stage|prod$(NC) (default: stage) -- scan-before/scan-after also "
	@printf "accept $(BOLD)ENV=all$(NC); $(BOLD)SEVERITY=CRIT,HIGH,...$(NC) for scan (default: $(SEVERITY))\n"
	@printf "$(BOLD)BENCH_WARMUP/BENCH_DURATION/BENCH_RUNS/BENCH_INTERVAL$(NC) for bench-before/bench-after "
	@printf "(default: warmup=$(BENCH_WARMUP)s, $(BENCH_RUNS)x$(BENCH_DURATION)s runs, sampled every $(BENCH_INTERVAL)s -- a full bench run is slow by design)\n"
	@printf "Start with $(BOLD)make doctor$(NC), then $(BOLD)make scan-delta$(NC) — both work without a stand.\n\n"

# --- Setup ---------------------------------------------------------------------

init: ## create a local venv with test dependencies (needed for make verify)
	$(call run,python3 -m venv $(VENV_DIR) && $(VENV_DIR)/bin/pip install -q -U pip -r requirements-dev.txt)

# --- Stand (Vagrant) ----------------------------------------------------------

up: ## bring up the full stand (5 VMs: stage + prod + mon)
	$(call run,cd $(STAND_DIR) && vagrant up)

up-lite: ## bring up the lightweight stand (3 VMs: stage + mon)
	$(call run,cd $(STAND_DIR) && STAND_PROFILE=lite vagrant up)

halt: ## power off the stand, keep the VM disks (fast to bring back up with make up/up-lite)
	$(call run,cd $(STAND_DIR) && vagrant halt)

destroy: ## wipe the stand entirely -- VM disks gone, next up/up-lite starts from zero
	@printf "$(RED)⚠ destroys the VM disks, not just powers them off — next up starts from zero$(NC)\n"
	$(call run,cd $(STAND_DIR) && vagrant destroy -f)

urls: ## print links to the web UIs (WordPress, wp-admin, Grafana, reports)
	$(call run,python3 stand/urls.py)

creds: ## print demo credentials (WordPress admin, MySQL) -- intentionally weak, SECURITY.md
	$(call run,python3 stand/creds.py)

# --- Scanning ------------------------------------------------------------------

scan-before: ## scan BEFORE patching (Trivy on the live VMs via Ansible -> HTML report, ENV=stage|prod|all)
	$(call check_scan_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/scan.yml -e env=$(ENV) -e out=results/scan-before -e vuln_severities=$(SEVERITY))

scan-after: ## scan AFTER patching (Trivy on the live VMs via Ansible -> HTML report, ENV=stage|prod|all)
	$(call check_scan_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/scan.yml -e env=$(ENV) -e out=results/scan-after -e vuln_severities=$(SEVERITY))

scan-delta: ## compute the scan delta -> CSV (Registry) + HTML chart
	$(call run,python3 scan/delta.py --before results/scan-before.json --after results/scan-after.json --csv results/delta.csv --html results/delta.html)

clean-results: ## remove generated demo artifacts under results (keeps README.md)
	$(call run,rm -f results/scan-*.json results/scan-*.html results/delta*.csv results/delta*.html results/verify.html results/attack.log results/bench-*.json)

# --- Load baseline (smoke-level, not a rigorous benchmark) ---------------------
# Slow by design: warmup + BENCH_RUNS timed runs per metric, see BENCH_* above.

bench-before: ## load baseline BEFORE patching (warmup+2x180s runs, wrk+sysbench on the live VMs via Ansible, ENV=stage|prod)
	$(call check_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/bench.yml -e env=$(ENV) -e out=results/bench-before -e bench_warmup=$(BENCH_WARMUP) -e bench_duration=$(BENCH_DURATION) -e bench_runs=$(BENCH_RUNS) -e bench_interval=$(BENCH_INTERVAL))

bench-after: ## load baseline AFTER patching (warmup+2x180s runs, wrk+sysbench on the live VMs via Ansible, ENV=stage|prod)
	$(call check_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/bench.yml -e env=$(ENV) -e out=results/bench-after -e bench_warmup=$(BENCH_WARMUP) -e bench_duration=$(BENCH_DURATION) -e bench_runs=$(BENCH_RUNS) -e bench_interval=$(BENCH_INTERVAL))

bench-delta: ## compare the load baseline -> before/after/delta table + HTML report (median+p90, sparklines), flags regressions past tolerance
	$(call run,python3 scan/bench_compare.py --before results/bench-before.json --after results/bench-after.json --html results/bench.html)

# --- Patching and verification (Ansible + pytest) ------------------------------

patch: ## apply OS/middleware patches (ENV=stage|prod)
	$(call check_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/patch.yml -e env=$(ENV))

patch-reboot: ## reboot after patch + purge the non-running kernel (clears kernel-CVE false positives from a scan)
	$(call check_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/reboot-cleanup.yml -e env=$(ENV))

patch-wordpress: ## patch the app-layer CVE (WordPress core, ENV=stage|prod) -- OS patch never touches this
	$(call check_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/patch-wordpress.yml -e env=$(ENV))

# verify = smoke only: "the patch did not break the service". Green before
# AND after a patch -- that's the point (a patch you can promote is one that
# changed nothing the user can see). It deliberately does NOT prove the CVE
# is closed: that's what `make scan-after` (Trivy) and `make attack` (the live
# PoC) are for -- verifying the fix twice, in pytest and in a scan, would be
# dead duplicate work (three layers, three owners: docs/en/README.md).
# Skips cleanly (exit 0) when the stand is unreachable.
verify: ## smoke-test the stand: services still alive after a patch -> HTML report (STAND_URL from ENV=stage|prod)
	$(call check_env)
ifneq ("$(wildcard $(VENV_PYTHON))","")
	$(call run,. $(VENV_DIR)/bin/activate && STAND_URL=$(WEB_URL) python3 -m pytest -m stand --html=results/verify.html --self-contained-html && deactivate)
else
	$(call run,STAND_URL=$(WEB_URL) python3 -m pytest -m stand --html=results/verify.html --self-contained-html)
endif

rollout: ## roll out to prod with the same playbook (after verify on stage)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/rollout.yml -e env=prod)

# --- Exploit and virtual patch (isolated network only!) -------------------------

attack: ## fast check: is the stand vulnerable? (ENV=stage|prod, host-only network ONLY)
	$(call check_env)
	@printf "$(RED)⚠ isolated host-only network only (SECURITY.md)$(NC)\n"
	$(call run,STAND_URL=$(WEB_URL) bash exploit/run.sh)

attack-shell: ## unauthenticated shell via vendored wp2shell-poc, runs CMD=id then stays open (ENV=stage|prod, host-only network ONLY)
	$(call check_env)
	@printf "$(RED)⚠ isolated host-only network only (SECURITY.md)$(NC)\n"
	$(call run,python3 exploit/wp2shell-poc/wp2shell.py shell $(WEB_URL) --cmd '$(CMD)' -i)

waf-on: ## enable the narrow ModSecurity rule (virtual patch, ENV=stage|prod)
	$(call check_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/waf.yml -e state=on -e env=$(ENV))

waf-off: ## remove the virtual-patching rule (ENV=stage|prod)
	$(call check_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/waf.yml -e state=off -e env=$(ENV))

# --- Readiness -------------------------------------------------------------------

doctor: banner ## check environment readiness before a demo
	@bash stand/doctor.sh
