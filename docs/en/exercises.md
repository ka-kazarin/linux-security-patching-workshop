# Self-Study Exercises

Reproducible on the lightweight stand: `make up-lite` (3 VMs: stage + mon).
Exercise 1 works even without a stand — on the examples in `scan/examples/`.

## 1. A vulnerability the OS patch can't reach → a compensating control

Run `make scan-delta` and open `results/delta.html` + `results/delta.csv`. Both
example scans still list `CVE-2026-63030` as `open` — it's an **app-layer**
finding (layer `app`, owner `dev`, WordPress core), and `apt`/`dnf` never touch
the application layer, so `make patch` can't close it. A real fix exists
(WordPress 7.0.2) but shipping it is a dev cycle. Which compensating control
does this stand apply in the meantime (hint: look in `waf/`)? Explain why the
finding is `mitigated`, not `closed`, and what must happen for it to become
`closed`.

## 2. A narrow WAF rule for a CVE + prove it with the live PoC

Take `waf/modsecurity/wp2shell.conf`. Explain why the rule is narrow (exactly what
it matches) and why it doesn't catch legitimate WordPress traffic. Then prove it
with the live exploit: `make attack` (🔴 VULNERABLE) → `make waf-on` →
`make attack` (🟢 PROTECTED). The virtual patch is verified by the exploit going
dead — while `make scan-after` still lists the CVE, showing a WAF *mitigates*,
it doesn't *close*.

## 3. A finding in the registry: owner and SLA

Open `results/delta-<env>.csv` (the findings registry `make scan-delta` writes).
Pick a finding and fill in the blank triage columns: layer, owner
(infra/DBA/dev), severity, discovery date, and a target SLA deadline (e.g.
critical 72 h, high 7 days). Work out whether it's overdue.

## 4. The stage → prod pipeline: why verify matters

Run the chain `make scan-before → make patch ENV=stage → make verify →
make scan-after`. Then `make rollout`. Explain in your own words what `make verify`
*guarantees* (the services still answer as before — the patch broke nothing) and,
just as important, what it does **not** guarantee (that the CVE is closed — that's
`make scan-after` and `make attack`). Why is a green `verify` mandatory **before**
`rollout`, and what breaks if you skip it and patch prod directly?
