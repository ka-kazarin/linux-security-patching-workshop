# Contributing

Thanks for your interest. This repository is a **hands-on lab stand** built for
a vulnerability-management / security-patching webinar. It is meant to be cloned
and run, and it tracks a specific teaching scenario — contributions are welcome,
but keep that scope in mind.

## Ground rules

- **Everything runs in an isolated host-only network.** The stand includes a
  working exploit against a deliberately outdated component; only ever run it in
  the isolated lab network the stand provisions. See [`SECURITY.md`](SECURITY.md).
- **Demo credentials are intentionally weak** (`stand/secrets.json`) and exist
  only for the throwaway lab — never reuse them anywhere real.

## Running it

Requirements: VirtualBox, Vagrant, Ansible, and `make`. Then:

```
make up        # full stand (or: make up-lite for a smaller footprint)
make doctor    # sanity-check the environment
make help      # list every target
```

The scenario and per-step guide live in [`docs/en/`](docs/en/) (English) and
[`docs/ru/`](docs/ru/) (Russian).

## Reporting problems

Open an issue with:

- what you ran (the exact `make` target / command),
- what you expected and what actually happened (paste the relevant output),
- your host OS and the VirtualBox / Vagrant / Ansible versions.

## Pull requests

- Keep changes focused and describe the *why*, not just the *what*.
- If you change a `make` target or a playbook, update the docs that mention it
  and add a `CHANGELOG.md` entry under `[Unreleased]`.
- Match the surrounding style; keep the HTML reports self-contained (no external
  assets).

By contributing you agree that your work is licensed under the repository's
[MIT License](LICENSE).
