# Self-Study Exercises

Reproducible on the lightweight stand: `make up-lite` (2 VMs, stage only).
Exercise 1 works even without a stand — on the examples in `scan/examples/`.

## 1. A vulnerability with no patch → a compensating control

Run `make delta` and open `results/delta.html`. Find a finding with status
`open` in the registry (`results/delta.csv`) that has no OS-layer patch
available (hint: layer `app`, owner `dev`). Propose a compensating control that
closes the risk until a patch ships. Justify why this is `mitigated`, not `closed`.

## 2. A narrow WAF rule for a CVE + prove it with a test

Take `waf/modsecurity/wp2shell.conf`. Explain why the rule is narrow (exactly what
it matches) and why it doesn't catch legitimate WordPress traffic. Then make
`test_vulnerability.py` go **red** before `make waf-on` and **green** after. The
test *is* the verification of the virtual patch.

## 3. A finding in the registry: owner and SLA

Add a fresh finding from a Trivy report to the `Registry` sheet (Google Sheets
template). Set the layer, owner (infra/DBA/dev), severity, discovery date, and
target SLA deadline per the `SLA` matrix. Use the formula to determine whether
it's overdue.

## 4. The stage → prod pipeline: why verify matters

Run the chain `make scan-before → make patch ENV=stage → make verify →
make scan-after`. Then `make rollout`. Explain in your own words why `verify` is
mandatory **before** `rollout` and exactly what it guarantees. What would happen
if you skipped it and rolled out to prod directly?
