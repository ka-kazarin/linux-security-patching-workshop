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
- The stand: `Vagrantfile` (full 4-VM profile + lite 2-VM profile),
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
- Monitoring stack `monitoring/` (Prometheus + Grafana + exporters,
  provisioned from files, livepatch dashboard).
- `docs/en/exercises.md` / `docs/ru/exercises.md` (4 exercises). Webinar
  theory lives in a separate slide deck, not this repo — `docs/{en,ru}/`
  hold the stand's own scenario/usage guide instead (in progress).
- Load baseline: `make bench-before` / `make bench-after` (`ansible/bench.yml`)
  run `ab` against nginx (static file) and PHP-FPM+MySQL (WordPress home
  page) on the web host, and `mysqlslap` against MySQL on the db host; `make
  bench` (`scan/bench_compare.py`) prints a before/after/delta table and
  flags anything outside a ~20% tolerance. Smoke-level on purpose — a single
  VM's noise floor, not a performance lab — meant to show that a patch
  didn't quietly slow the stack down, not to certify throughput numbers.
