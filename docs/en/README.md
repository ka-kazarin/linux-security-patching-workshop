# Vulnerability Management Stand (Slurm)

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
2. `make patch ENV=stage` — patch OS/middleware via Ansible.
3. `make verify` — pytest smoke: services still alive after the patch (it
   didn't break anything). Proof the CVE is *closed* comes from
   `make scan-after` and `make attack`, not from here.
4. `make scan-after` — vulnerabilities closed.
5. `make rollout` — roll out to prod with the same playbook.
6. `make delta` — scan delta, exported for the registry.

Live exploit and virtual patching: `make attack` → `make waf-on` →
`make attack` (403) → `make patch-wordpress` (the real fix) → `make waf-off`
→ `make attack` (still dead — patched now, not just shielded).

## Findings registry (Google Sheets)

The live vulnerability registry lives in a Google Sheets template (outside
this repo): _link to be added_.

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
