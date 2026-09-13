# Documentation Index

This index separates two different kinds of material. Don't confuse them.

## Documentation (kept up to date)

Describes how things work **now**. If it disagrees with the process history
below, **the documentation wins**.

| Path | Audience | Purpose |
|------|----------|---------|
| [`../README.md`](../README.md) | student | entry point: what this is, where to start, demo order |
| [`../SECURITY.md`](../SECURITY.md) | student | disclaimer: exploits run only in the isolated network |
| [`en/`](en/) | student | scenario description + usage/reproduction guide (English) |
| [`ru/`](ru/) | student (RU) | the same, in Russian, for the live webinar audience |
| [`../results/`](../results/) | presenter | scan/patch/verify/attack output — doubles as the pre-captured fallback if a live demo step fails |

The webinar's theory lives in a separate slide deck, not in this repo. What's
here is scoped to the stand itself: what each scenario shows and how to run
and reproduce it. That guide is still to be written (owner's material,
composed together later) — for now `en/`/`ru/` hold `README.md` (navigation)
and `exercises.md` (self-study tasks).

## Process history (written at the time, never rewritten afterward)

Reflects the state at the moment it was written. **Not committed to git** (see
`rules/git.md`). If it disagrees with the documentation above, **the
documentation wins**.

| Path | Purpose |
|------|---------|
| `stand-spec.md` | internal build spec: versions, layout, Makefile, demos, acceptance criteria |
| `process/roadmap.md` | roadmap, status per component |
| `process/context.md` | append-only log of decisions and steps |

Development/agent rules live in [`../AGENTS.md`](../AGENTS.md) and
[`../rules/`](../rules/) (also outside git).
