# Changelog

All notable user-facing changes to this stand are recorded here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/).

Internal process artifacts (roadmap, dev log) are **not** listed here — only
what a student/user of the stand sees and uses.

## [Unreleased]

### Added
- Repo skeleton and navigation: `README.md` (English, links to
  `docs/en/README.md` / `docs/ru/README.md`), `SECURITY.md` with the
  exploit-isolation disclaimer.
- `exploit/README.md`: target CVE selected for the virtual-patching demo —
  wp2shell (pre-auth RCE in WordPress core, CVE-2026-63030 +
  CVE-2026-60137), fallback option — BookingPress SQLi (CVE-2022-0739), with
  vectors for narrow WAF rules. `exploit/run.sh` implements and verifies the
  confirmed route-confusion payload against the live stand, with a
  colored/emoji vulnerable-vs-protected result. The vendored
  `exploit/wp2shell-poc/` gets a real, unauthenticated end-to-end shell
  (`make attack-shell`), staying interactive until you exit so you can show
  effects live (reading `wp-config.php`, listing the throwaway admin via
  `wp-cli`, writing a file) before cleanup.
- `Makefile` — single branded interface: `help` with a banner, `doctor`,
  every target echoes the real command it runs; targets for
  up/down/scan/patch/verify/delta/rollout/attack/waf. One `ENV=stage|prod`
  variable everywhere (scan-before/scan-after additionally accept
  `ENV=all`), validated up front with a clear error on a bad value;
  `attack`/`attack-shell`/`waf-on`/`waf-off` now target either environment
  instead of a hardcoded stage IP.
- Repo layout simplified: Ansible playbooks moved from `stand/ansible/` to
  top-level `ansible/` (they're core demo mechanics, not Vagrant plumbing);
  generated scan/delta/verify/attack output moved from `docs/fallback/` to
  top-level `results/` (`docs/` is now purely textual, `results/` is a
  self-describing name instead of the "why is it called fallback"
  question). `make clean-fallback` renamed `make clean-results` to match.
- `scan/delta.py` + sample scans — delta between two Trivy reports → CSV
  (matches the `Registry` sheet) and an HTML/SVG chart; runs without trivy
  installed locally.
- `tests/` (pytest): unit tests for `scan/delta.py` + smoke tests against the
  stand (`make verify` — services still answer after a patch, green before and
  after); HTML report via pytest-html. Deliberately no test that re-verifies
  the CVE is closed: that role is already filled by `make scan-after` (Trivy)
  and `make attack` (the live PoC), so a pytest assertion for it would be dead
  duplicate work.
- The stand: `Vagrantfile` (full 5-VM profile + lite 3-VM profile),
  provisioning scripts, Ansible playbooks (patch/rollout/scan/verify/waf),
  `scan/trivy-html.tpl`. `scan.yml` and `patch.yml` verified against a live
  stand end to end. `scan.yml` now also reports the WordPress core CVE as an
  app-layer finding (invisible to Trivy's OS scan otherwise), and resets its
  per-host workspace on every run so a narrower scan never inherits stale
  hosts from a previous, wider one. `reboot-cleanup.yml` now force-purges
  every package tagged with a non-running kernel version after reboot (not
  just `linux-image-*` — the modules/tools/headers siblings carry their own
  CVEs and apt's autoremove leaves them behind too, verified live: one
  leftover module package alone accounted for CRITICAL 67→16 / HIGH
  1094→344 on a single host), re-reads the running kernel fresh after the
  reboot rather than trusting Ansible's pre-reboot facts, and refuses to
  purge anything unless the host actually booted into its newest installed
  kernel — verified live end to end.
- `make patch-wordpress` (`ansible/patch-wordpress.yml`): patches the
  app-layer CVE (WordPress core, via wp-cli) independently of `make patch`
  (OS/middleware only) — direct demo of "three layers, three owners".
  Verified live end to end: exploit dead without the WAF, the app-layer scan
  finding disappears from the next scan on its own.
- Narrow ModSecurity rule `waf/modsecurity/wp2shell.conf`; `exploit/run.sh`
  refuses to run outside the host-only network.
- Monitoring stack `monitoring/` (Prometheus + Grafana + blackbox_exporter,
  provisioned from files) on its own `mon` node (192.168.56.30), up in both
  profiles. `node_exporter` runs natively on every node (web/db/mon, Ubuntu
  and Oracle Linux alike — `stand/provision/common.sh`) instead of as a
  single container, so kernel uptime is real per-host data. Prometheus's
  scrape config is generated at provision time from `nodes.json`'s active
  node set for the current profile, so `STAND_PROFILE=lite` never carries
  static targets for prod hosts that aren't up; the chosen profile is
  persisted so a later bare `vagrant provision`/`reload` keeps it instead of
  reverting to full. Every target (node and blackbox alike) is labelled with
  its node name, so Grafana legends read "web-stage", not an IP. Dashboard:
  "Service continuity" (`continuity.json`) — a state timeline of
  `probe_success` per probed service (HTTP on web nodes, TCP on db nodes) and
  a kernel-uptime panel per node.
- `docs/en/exercises.md` / `docs/ru/exercises.md` (4 exercises). Webinar
  theory lives in a separate slide deck, not this repo — `docs/{en,ru}/`
  hold the stand's own scenario/usage guide instead (in progress).
- Load baseline: `make bench-before` / `make bench-after` (`ansible/bench.yml`)
  run `wrk` against nginx (static file) and PHP-FPM+MySQL (WordPress home
  page) on the web host, and `sysbench oltp_read_only` (via EPEL) against
  MySQL on the db host. Methodology: per metric, 1 warmup run (discarded, so
  a warmed-up OS disk cache on the second run can't masquerade as a
  regression) + 2 timed runs, each sampled at a fixed interval
  (`BENCH_WARMUP`/`BENCH_DURATION`/`BENCH_RUNS`/`BENCH_INTERVAL`, default
  60s/180s/2/10s) into a throughput+latency time series. `make bench-delta`
  (`scan/bench_compare.py`) prints a before/after **median**+p90/delta table
  (verdict driven by median, p90 shown for context only) and renders a
  self-contained HTML report (`results/bench.html`) with a throughput
  sparkline (before vs after overlaid) per metric, flagging anything whose
  median moved outside a ~20% tolerance. Smoke-level on purpose — a single
  VM's noise floor, not a performance lab — meant to show that a patch
  didn't quietly slow the stack down, not to certify throughput numbers.
- All HTML reports (scan, delta, bench) now share one visual identity —
  a dark-navy header with a cyan accent, white cards, pill badges, inspired
  by slurm.io — factored into `scan/report_style.py` (the Trivy Go template
  keeps a synced copy of the CSS). Self-contained, offline-renderable.
- `results/` holds generated artifacts only (gitignored except its README):
  regenerated by the make targets and refreshed before the event, not
  committed. The fallback still works — the presenter keeps the last good
  run on disk — it just no longer lives in git history.
- `make patch-plan ENV=stage|prod` (`ansible/patch-plan.yml`): freezes pending
  **security** updates as exact `{name, version}` pairs per host into a single
  `results/patch-plan.json` (no env suffix — like `scan-before.html`), without
  installing anything. Debian/Ubuntu via `apt-get -s dist-upgrade` filtered to
  the `-security` pocket (machine-readable `Inst` lines, versions read straight
  off); Oracle Linux via `dnf check-update --security` +
  `dnf updateinfo list security` for versions and advisory IDs (ELSA). Solves a
  real drift problem: between freezing the plan and rolling it out, a plain
  `apt/dnf upgrade` can resolve a *different* set as new updates land on the
  mirror — the manifest makes "prod gets exactly what was tested" a fact, not a
  hope. Intended flow: collect the plan against prod's real pending set
  (`make patch-plan ENV=prod`), test it on stage (`make patch ENV=stage` +
  `make verify ENV=stage`), then ship it (`make rollout`) — one file, every
  command reads it. Renders `results/patch-plan.html` in the shared report
  style (`scan/patch_plan_report.py`) — a collapsible per-host section with a
  package/version/advisory table and packages/advisories pill counters.
- `make patch` (`ansible/patch.yml`) is now manifest-aware: when
  `results/patch-plan.json` exists, it installs exactly those package/version
  pairs (`apt`/`dnf` pinned to the frozen version, idempotent no-op if already
  at that version) instead of re-resolving "whatever the mirror serves right
  now"; with no manifest, behaviour is unchanged (plain security-only upgrade)
  plus a notice pointing at `make patch-plan`. Every other task in `patch.yml`
  (allowlist, power-state fix, autoremove, needrestart install + CVE guard +
  run, needs-restarting) is untouched — only the two "apply security updates"
  steps became conditional.
- `make rollout` no longer just re-runs `patch.yml` against `env=prod`: it's
  now a hard-`prod`, no-`ENV`-argument sequence that (1) applies the frozen
  `results/patch-plan.json` to prod (parity: prod installs the exact set that
  was frozen and tested, not a fresh, possibly-drifted mirror resolve),
  (2) `patch-wordpress.yml`, (3) `reboot-cleanup.yml`, (4) `make verify ENV=prod`.
  Refuses to run with a clear error if `results/patch-plan.json` doesn't exist
  yet. Manifest package lists key off the scanned hostname (e.g. `web-prod`);
  `patch.yml` matches a manifest host by exact `inventory_hostname` first,
  falling back to any manifest host sharing the current host's `web`/`db` role
  group, so a plan collected on prod still resolves against `web-stage`/`db-stage`
  when tested on stage. `ansible/rollout.yml` (the old thin
  `import_playbook: patch.yml` wrapper) is removed — nothing imports it anymore.
- `make verify` is now a real health-smoke, not HTTP-only: `tests/test_health.py`
  (pytest-testinfra, `ansible` connection backend — hosts/IPs/SSH keys come
  from `ansible/inventory.yml`, `STAND_ENV` picks the stage/prod group)
  checks, per host of the group: SSH reachable; web hosts — nginx running,
  `:80` listening, `localhost/` returns 200, `/wp-admin/` responds without a
  5xx, php-fpm running (unit name read live via systemd, not hardcoded); db
  hosts — mysqld running, `:3306` listening, `mysql -uroot -e 'SELECT 1'`
  answers. Tells apart three failure modes the old requests-only smoke could
  not: a service down on a live VM fails on that service; a VM that never
  came back up (e.g. missed a patch-reboot) fails on SSH reachability for
  that host specifically, while a live sibling host's checks still run;
  every host of the group unreachable means the stand was never brought up
  and the whole run skips cleanly (exit 0), same as before. The previous
  external HTTP smoke (`tests/test_functional.py`, `requests`) stays as-is,
  checking the same page from outside the VM over the network.
