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
SEVERITY ?= CRITICAL,HIGH,MEDIUM,LOW
# Command to run through the wp2shell-poc shell (make attack-shell).
CMD ?= id
# Load-baseline methodology (make bench-before/bench-after): fixed
# sub-saturation rate + latency (vegeta on web, sysbench --rate on db), NOT
# peak throughput -- a rate held under each endpoint's ceiling keeps the
# service from ever queueing, so p95 latency barely drifts between two
# otherwise-identical runs. 1 warmup run (discarded) + BENCH_RUNS timed runs
# of BENCH_DURATION seconds each, sampled every BENCH_INTERVAL seconds. The
# web host runs nginx-static then php sequentially and each timed run is a
# sequence of short vegeta windows (per-window startup adds up), so wall time
# is more than the raw seconds suggest. 20 + 2*60s lands the whole thing
# under ~8 min (measured); still 12 samples/metric for a usable median.
# Override for a quick mechanics check, e.g. BENCH_DURATION=20 BENCH_WARMUP=10.
# Stage only -- bench-before/after/delta always target web-stage/db-stage,
# no ENV parameter (unlike scan/patch/verify).
BENCH_WARMUP   ?= 20
BENCH_DURATION ?= 60
BENCH_RUNS     ?= 2
BENCH_INTERVAL ?= 10

# VMs paused for the duration of a bench run to remove CPU contention on the
# host (mon + prod share the same physical cores as web-stage/db-stage under
# the full profile). Each suspend/resume is best-effort per VM: under the
# lite profile prod doesn't exist, and the loop must not fail the whole
# target over a VM that was never up.
BENCH_NEIGHBORS := mon web-prod db-prod
define pause_bench_neighbors
	cd $(STAND_DIR) && for vm in $(BENCH_NEIGHBORS); do vagrant suspend "$$vm" >/dev/null 2>&1 || true; done
endef
# Plain `vagrant resume` is the happy path; VirtualBox occasionally corrupts
# a saved state into "aborted-saved" (observed live on this host resuming
# several suspended VMs back to back) where resume itself always fails --
# the only way out is discarding the saved state and booting fresh
# (`vagrant up` self-heals a stopped/aborted VM; disk state survives, only
# in-RAM state is lost, same as a hard power cycle). Best-effort throughout:
# a VM this run never suspended (lite profile has no prod) is silently a
# no-op.
define resume_bench_neighbors
	cd $(STAND_DIR) && for vm in $(BENCH_NEIGHBORS); do \
		vagrant resume "$$vm" >/dev/null 2>&1 && continue; \
		vbox_id=$$(VBoxManage list vms 2>/dev/null | grep "\"stand_$${vm}_" | grep -o '{[a-f0-9-]*}' | tr -d '{}'); \
		[ -n "$$vbox_id" ] && VBoxManage discardstate "$$vbox_id" >/dev/null 2>&1; \
		vagrant up "$$vm" >/dev/null 2>&1 || true; \
	done
endef

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
        patch-plan patch patch-reboot patch-wordpress verify scan-delta bench-before bench-after bench-delta rollout \
        waf-on waf-off doctor init clean-results change-log

banner:
	@printf "$(BOLD)"
	@echo '  ╔═══════════════════╗'
	@echo '  ║  VULN MGMT STAND  ║'
	@echo '  ╚═══════════════════╝'
	@echo '  Vulnerability Management · training stand'
	@printf "$(NC)\n"

help: banner ## show this help
	@printf "$(BOLD)Commands:$(NC)\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN{FS=":.*?## "}{printf "  $(GREEN)%-14s$(NC) %s\n", $$1, $$2}'
	@printf "\nVariables: $(BOLD)ENV=stage|prod$(NC) (default: stage) -- scan-before/scan-after also "
	@printf "accept $(BOLD)ENV=all$(NC); $(BOLD)SEVERITY=CRIT,HIGH,...$(NC) for scan (default: $(SEVERITY))\n"
	@printf "$(BOLD)bench-before/bench-after/bench-delta$(NC) are stage-only (no ENV) and pause mon/prod "
	@printf "VMs for the run; $(BOLD)BENCH_WARMUP/BENCH_DURATION/BENCH_RUNS/BENCH_INTERVAL$(NC) tune them "
	@printf "(default: warmup=$(BENCH_WARMUP)s, $(BENCH_RUNS)x$(BENCH_DURATION)s runs, sampled every $(BENCH_INTERVAL)s -- a full bench run is slow by design)\n"
	@printf "Start with $(BOLD)make doctor$(NC), then $(BOLD)make scan-delta$(NC) — both work without a stand.\n\n"

# --- Setup ---------------------------------------------------------------------

init: ## create a local venv with test dependencies (needed for make verify)
	$(call run,python3 -m venv $(VENV_DIR) && $(VENV_DIR)/bin/pip install -q -U pip -r requirements-dev.txt)

# --- Stand (Vagrant) ----------------------------------------------------------
# up/up-lite are EXPLICIT about the profile (STAND_PROFILE=full|lite) and the
# Vagrantfile persists it to .vagrant/stand_profile -- so a later bare
# `vagrant provision`/`reload` (no env) falls back to whatever was last brought
# up. Without the explicit STAND_PROFILE here, `make up` would inherit a "lite"
# marker left by a previous `make up-lite` and quietly bring up only 3 VMs.

up: ## bring up the full stand (5 VMs: stage + prod + mon)
	$(call run,cd $(STAND_DIR) && STAND_PROFILE=full vagrant up)

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

# Scan/bench output files are tagged with ENV (scan-before-stage.json, ...)
# so a stage run and a prod run never overwrite each other -- the delta of an
# env is that env's own before vs after, and mixing stage/prod findings into
# one report was a real bug (reported live). (Unlike patch-plan, which is one
# shared file on purpose: a scan delta is per-env, a patch plan is not.)
scan-before: ## scan BEFORE patching (Trivy on the live VMs via Ansible -> HTML report, ENV=stage|prod|all)
	$(call check_scan_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/scan.yml -e env=$(ENV) -e out=results/scan-before-$(ENV) -e vuln_severities=$(SEVERITY))

scan-after: ## scan AFTER patching (Trivy on the live VMs via Ansible -> HTML report, ENV=stage|prod|all)
	$(call check_scan_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/scan.yml -e env=$(ENV) -e out=results/scan-after-$(ENV) -e vuln_severities=$(SEVERITY))

scan-delta: ## compute the scan delta for ENV -> CSV (Registry) + HTML chart (ENV=stage|prod|all)
	$(call check_scan_env)
	$(call run,python3 scan/delta.py --before results/scan-before-$(ENV).json --after results/scan-after-$(ENV).json --csv results/delta-$(ENV).csv --html results/delta-$(ENV).html)

change-log: ## render results/change-log.html -- CMDB-style calendar of past patch/rollout/patch-wordpress/patch-reboot runs, with search
	$(call run,python3 scan/change_log_report.py)

clean-results: ## remove generated demo artifacts under results (keeps README.md and change-log.jsonl -- that's history, not a report)
	$(call run,rm -f results/scan-*.json results/scan-*.html results/delta*.csv results/delta*.html results/verify.html results/attack.log results/bench*.json results/bench*.html results/patch-plan*.json results/patch-plan*.html results/change-log.html)

# --- Load baseline (smoke-level, not a rigorous benchmark) ---------------------
# Slow by design: warmup + BENCH_RUNS timed runs per metric, see BENCH_* above.
# Stage-only (web-stage/db-stage) -- mon/web-prod/db-prod are paused for the
# run to remove CPU contention on the host, then resumed unconditionally
# (even if the bench run itself fails, via the shell `;`/`$$?` below -- a
# `&&` chain would leave the neighbors suspended on any bench failure).

bench-before: ## load baseline BEFORE patching (fixed rate + p95 latency, vegeta+sysbench on stage via Ansible; pauses mon/prod VMs)
	@printf "$(YELLOW)→ running:$(NC) %s\n" 'cd $(STAND_DIR) && vagrant suspend $(BENCH_NEIGHBORS) (best-effort)'
	@$(pause_bench_neighbors)
	@printf "$(YELLOW)→ running:$(NC) %s\n" 'ansible-playbook -i $(INVENTORY) ansible/bench.yml -e out=results/bench-before -e bench_warmup=$(BENCH_WARMUP) -e bench_duration=$(BENCH_DURATION) -e bench_runs=$(BENCH_RUNS) -e bench_interval=$(BENCH_INTERVAL)'
	@ansible-playbook -i $(INVENTORY) ansible/bench.yml -e out=results/bench-before -e bench_warmup=$(BENCH_WARMUP) -e bench_duration=$(BENCH_DURATION) -e bench_runs=$(BENCH_RUNS) -e bench_interval=$(BENCH_INTERVAL); ret=$$?; \
	printf "$(YELLOW)→ running:$(NC) %s\n" 'cd $(STAND_DIR) && vagrant resume $(BENCH_NEIGHBORS)'; \
	$(resume_bench_neighbors); \
	exit $$ret

bench-after: ## load baseline AFTER patching (fixed rate + p95 latency, vegeta+sysbench on stage via Ansible; pauses mon/prod VMs)
	@printf "$(YELLOW)→ running:$(NC) %s\n" 'cd $(STAND_DIR) && vagrant suspend $(BENCH_NEIGHBORS) (best-effort)'
	@$(pause_bench_neighbors)
	@printf "$(YELLOW)→ running:$(NC) %s\n" 'ansible-playbook -i $(INVENTORY) ansible/bench.yml -e out=results/bench-after -e bench_warmup=$(BENCH_WARMUP) -e bench_duration=$(BENCH_DURATION) -e bench_runs=$(BENCH_RUNS) -e bench_interval=$(BENCH_INTERVAL)'
	@ansible-playbook -i $(INVENTORY) ansible/bench.yml -e out=results/bench-after -e bench_warmup=$(BENCH_WARMUP) -e bench_duration=$(BENCH_DURATION) -e bench_runs=$(BENCH_RUNS) -e bench_interval=$(BENCH_INTERVAL); ret=$$?; \
	printf "$(YELLOW)→ running:$(NC) %s\n" 'cd $(STAND_DIR) && vagrant resume $(BENCH_NEIGHBORS)'; \
	$(resume_bench_neighbors); \
	exit $$ret

bench-delta: ## compare the stage load baseline -> before/after/delta table + HTML report (median p95 latency + success rate, sparklines), flags regressions
	$(call run,python3 scan/bench_compare.py --before results/bench-before.json --after results/bench-after.json --html results/bench.html)

# --- Patching and verification (Ansible + pytest) ------------------------------

patch-plan: ## freeze pending SECURITY updates -> results/patch-plan.json + HTML, installs nothing (collect against ENV=prod, then test on stage)
	$(call check_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/patch-plan.yml -e env=$(ENV))

patch: ## apply OS/middleware patches -- exact versions from results/patch-plan.json if it exists, else the current security pocket (ENV=stage|prod)
	$(call check_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/patch.yml -e env=$(ENV))
	$(call run,python3 scan/change_log_append.py --action patch --env $(ENV))

patch-reboot: ## reboot after patch + purge the non-running kernel (clears kernel-CVE false positives from a scan)
	$(call check_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/reboot-cleanup.yml -e env=$(ENV))
	$(call run,python3 scan/change_log_append.py --action patch-reboot --env $(ENV))

patch-wordpress: ## patch the app-layer CVE (WordPress core, ENV=stage|prod) -- OS patch never touches this
	$(call check_env)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/patch-wordpress.yml -e env=$(ENV))
	$(call run,python3 scan/change_log_append.py --action patch-wordpress --env $(ENV))

# verify = smoke only: "the patch did not break the service". Green before
# AND after a patch -- that's the point (a patch you can promote is one that
# changed nothing the user can see). It deliberately does NOT prove the CVE
# is closed: that's what `make scan-after` (Trivy) and `make attack` (the live
# PoC) are for -- verifying the fix twice, in pytest and in a scan, would be
# dead duplicate work (three layers, three owners: docs/en/README.md).
# Two layers: test_functional.py (external HTTP, requests) and
# test_health.py (testinfra over SSH via the ansible inventory) -- the
# latter tells apart "a VM is down" (FAIL on that host, SSH-unreachable)
# from "a service on a live VM is down" (FAIL on that service) from "the
# stand was never brought up" (clean skip, exit 0, only when EVERY host of
# ENV is unreachable).
verify: ## health-smoke the stand: SSH + service checks (web+db) after a patch -> HTML report (ENV=stage|prod)
	$(call check_env)
ifneq ("$(wildcard $(VENV_PYTHON))","")
	$(call run,. $(VENV_DIR)/bin/activate && STAND_URL=$(WEB_URL) STAND_ENV=$(ENV) python3 -m pytest -m stand --tb=no && deactivate)
else
	$(call run,STAND_URL=$(WEB_URL) STAND_ENV=$(ENV) python3 -m pytest -m stand --tb=no)
endif

# Hard env=prod throughout, deliberately not ENV-driven like the targets
# above: rollout has exactly one direction (-> prod), never the reverse.
# Applies the FROZEN patch-plan to prod (parity: prod gets the exact
# package/version set that was frozen and tested, not a fresh mirror resolve
# that could've drifted since), then the app-layer patch, kernel reboot
# cleanup, and a final smoke check -- one operation instead of four manual
# steps a presenter could run out of order. patch.yml defaults plan_file to
# results/patch-plan.json, so no -e override is needed here.
rollout: ## roll out the frozen patch-plan to prod: patch -> patch-wordpress -> patch-reboot -> verify (hard env=prod, needs a patch-plan tested on stage first)
	@test -f results/patch-plan.json || { printf "$(RED)✗ no frozen patch-plan (results/patch-plan.json) -- run 'make patch-plan ENV=prod', test it via 'make patch ENV=stage' + 'make verify ENV=stage', then retry$(NC)\n" >&2; exit 1; }
	$(call run,ansible-playbook -i $(INVENTORY) ansible/patch.yml -e env=prod)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/patch-wordpress.yml -e env=prod)
	$(call run,ansible-playbook -i $(INVENTORY) ansible/reboot-cleanup.yml -e env=prod)
	$(MAKE) verify ENV=prod
	$(call run,python3 scan/change_log_append.py --action rollout --env prod)

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
