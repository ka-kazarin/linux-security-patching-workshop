# Vulnerability Management Stand

A hands-on stand for a vulnerability management / security patching webinar.
Full lifecycle — scanning, prioritization, patching, verification, rollout —
demonstrated on a real multi-layer stand across two Linux distributions
(Ubuntu 26.04 LTS + Oracle Linux 9.6), orchestrated with Vagrant + Ansible +
a plain Makefile. No hidden CLI framework: every target echoes the real
command it runs.

> **Status:** work in progress. Components land per the roadmap; this README
> grows as the stand fills in.

## ⚠️ Exploit isolation

This stand runs **intentionally vulnerable** services and working exploits.
Any PoC runs **only inside the stand's host-only network**, never against
external systems. Full disclaimer in [`SECURITY.md`](../../SECURITY.md).
Standing the lab up means you agree to these terms.

## Getting started

```bash
make help      # branded help for every command
make doctor    # checks your environment is ready
make up-lite   # lightweight stand (3 VMs: stage + mon) — for home use
make up        # full stand (5 VMs: stage + prod + mon)
```

By default `vagrant up` fetches the base images (`bento/ubuntu-26.04`,
`bento/oraclelinux-9`) from Vagrant Cloud. **If Vagrant Cloud isn't reachable
from your network**, download the images ahead of time and import them
locally, no network access needed:

```bash
vagrant box add bento/ubuntu-26.04   /path/to/downloaded/ubuntu-26.04.box   --provider virtualbox
vagrant box add bento/oraclelinux-9  /path/to/downloaded/oraclelinux-9.box  --provider virtualbox
```

The names (`bento/ubuntu-26.04`, `bento/oraclelinux-9`) must match
`stand/Vagrantfile` exactly — then `vagrant up` sees the box already
imported and never touches the network. Link to the images: _to be added_.

## Demo flow (short version)

1. `make scan-before` — vulnerability scan (Trivy, orchestrated by Ansible
   against the live VMs).
2. `make patch-plan ENV=prod` — freeze pending SECURITY updates as exact
   `package=version` pairs into a single `results/patch-plan.json` (installs
   nothing). Collect it against **prod's** real pending set — prod is the
   target — then test that same plan on stage. Between freezing the plan and
   rolling it out, a plain `apt/dnf upgrade` can pull in a *different* set (new
   updates land on the mirror in between) — the manifest is what makes "prod
   gets exactly what was tested" true rather than aspirational. Each package is
   also linked to the security advisory that fixed its exact version — ELSA on
   Oracle (from `dnf updateinfo`, in the repo metadata) and USN on Ubuntu
   (apt carries no advisory metadata, so the plan enriches from Canonical's
   live Ubuntu Security Notices feed) — and both show up in the HTML report.
3. `make patch ENV=stage` — patch OS/middleware on **stage** via Ansible, to
   test the plan. Installs the frozen manifest's exact versions when it exists,
   otherwise falls back to "whatever the security pocket currently serves" (and
   says so).
4. `make verify` — pytest smoke: services still alive after the patch (it
   didn't break anything). Proof the CVE is *closed* comes from
   `make scan-after` and `make attack`, not from here.
5. `make scan-after` — vulnerabilities closed.
6. `make rollout` — roll out to **prod**, hard-coded: applies the *stage*
   manifest to prod (parity — the exact package set already verified on
   stage, not a fresh mirror resolve that could've drifted since), patches
   the WordPress core CVE, reboots + cleans up the old kernel, then reruns
   `make verify ENV=prod`. Refuses to run without a tested stage manifest.
7. `make scan-delta ENV=stage` — scan delta (that env's before vs after),
   exported for the registry. Scan outputs are ENV-tagged, so stage and prod
   deltas never mix; the load baseline (`make bench-before/after/delta`) is
   stage-only by design, no ENV.

Live exploit and virtual patching: `make attack` → `make waf-on` →
`make attack` (403) → `make patch-wordpress` (the real fix) → `make waf-off`
→ `make attack` (still dead — patched now, not just shielded).

Every `patch`/`rollout`/`patch-wordpress`/`patch-reboot` run above appends a
record to `results/change-log.jsonl` — what was patched, where, when, and by
whom, a CMDB/change-management stand-in. `make change-log` renders it as a
searchable HTML calendar (`results/change-log.html`).

## Findings registry

The scan delta doubles as a findings registry: `make scan-delta` writes
`results/delta-<env>.csv` — one row per finding with its layer, owner,
severity, status (open/closed), discovery date, and SLA columns, ready for
triage.

## Documentation

The webinar's theory is covered in a separate slide deck (not part of this
repo). What lives here instead: [`exercises.md`](exercises.md) for
self-study tasks, [`../../exploit/README.md`](../../exploit/README.md) for
the CVE this stand demonstrates and how to reproduce the attack, and this
README for the scenario/usage guide. Russian version at
[`../ru/README.md`](../ru/README.md).

## Stack

Vagrant · Ansible · Ubuntu 26.04 LTS · Oracle Linux 9.6 · Trivy ·
ModSecurity + OWASP CRS · pytest · Prometheus + Grafana · Docker Compose ·
WordPress (deliberately vulnerable)
