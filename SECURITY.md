# Security and Terms of Use

*[Русская версия](docs/ru/security.md)*

This repository is a **training stand**. It runs intentionally vulnerable
software and working exploits (PoCs) to demonstrate the full vulnerability
management lifecycle. That makes it dangerous if misused.

## The main rule: isolation

- **Exploits and vulnerable services run only inside the stand's host-only
  network.** Never against external, third-party, or production systems.
- The stand is never exposed to the internet or connected to networks that
  carry real data or services.
- `make attack` and any PoC assume the target is a VM of this stand on the
  isolated network, and nothing else.

## This is a training model

- Passwords, keys, and settings in the stand are **demo-only and
  intentionally insecure**. Do not carry them over to real systems.
- Numbers from the demo (patch time, finding counts, metrics) illustrate the
  process on a specific run and **are not benchmarks**.
- The stand is a teaching model, not a reference secure configuration.

## Responsibility

By standing up and running this lab, you take responsibility for maintaining
isolation. The authors are not responsible for the consequences of running
exploits outside the stand's isolated environment.

## Reporting an issue

Found a problem in the stand's own materials (not the intentionally planted
vulnerability) — describe it via a repository issue.
