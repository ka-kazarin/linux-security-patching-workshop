#!/usr/bin/env python3
"""Append one record to the append-only change log (results/change-log.jsonl).

Emulates a CMDB/change-management journal -- "what / where / when / who" for
every patch-type Makefile target (patch, rollout, patch-wordpress,
patch-reboot). One JSON object per line (JSON Lines: natural for append,
the file is never rewritten). Wired into the Makefile right after each
target's real work succeeds -- the append is its own echoed step
(rules/bash.md: "mechanics are visible"), not hidden inside another command.

Package payload per action, deliberately not "whatever a fresh mirror
resolve would say" (same manifest-first philosophy as ansible/patch.yml):

  * patch / rollout -- read from results/patch-plan.json if it exists,
    matching hosts the same way patch.yml does: exact inventory hostname
    first, else any plan host sharing the current host's web/db role (a
    plan is always frozen against prod; testing it on stage has no exact
    hostname entry to read, so it falls back to the role match). No plan on
    disk -> empty packages, not an error -- "no data" beats a fabricated
    "0 packages, must already be patched".
  * patch-wordpress -- the app-layer CVE fix is a single fixed wp-cli
    version bump (ansible/patch-wordpress.yml's wp_fixed_version), not
    something the OS patch-plan tracks.
  * patch-reboot -- installs nothing (reboot + old-kernel purge only); an
    empty package list here is the honest answer, not a bug.

Runs on the standard library only. Invoked from the Makefile as e.g.
    python3 scan/change_log_append.py --action patch --env stage
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = REPO_ROOT / "results" / "change-log.jsonl"
SEED_PATH = REPO_ROOT / "scan" / "examples" / "change-log-seed.jsonl"
PLAN_PATH_DEFAULT = REPO_ROOT / "results" / "patch-plan.json"

# Matches ansible/patch-wordpress.yml's wp_fixed_version -- kept in sync by
# eye, the same duplication rules/git.md already accepts for inventory.yml
# vs stand/nodes.json IPs (a static file, not worth a generator for one value).
WORDPRESS_FIXED_VERSION = "7.0.2"

ACTIONS = ("patch", "rollout", "patch-wordpress", "patch-reboot", "rollback")

DEFAULT_NOTES = {
    "patch": "OS/middleware security patch (apt/dnf, frozen plan if present)",
    "rollout": "frozen patch-plan rolled out to prod: patch + WordPress core + reboot cleanup + verify",
    "patch-wordpress": "app-layer CVE fix: WordPress core updated via wp-cli",
    "patch-reboot": "reboot into the new kernel + purge of the old kernel's packages",
    "rollback": "reverted prod to the pre-rollout VM snapshot (change undone)",
}


class ChangeLogError(Exception):
    """A problem the user can act on; printed as one line, no traceback."""


def ensure_log(path: Path = LOG_PATH, seed: Path = SEED_PATH) -> None:
    """Create results/change-log.jsonl from the tracked seed if it's missing
    (fresh clone or after a manual delete) -- the report always has history
    to render, real appends land on top."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if seed.exists():
        shutil.copyfile(seed, path)
    else:
        path.touch()


def hosts_for_action(action: str, env: str) -> list[str]:
    """Hosts a given action's playbook actually targets for this env --
    patch-wordpress only touches the web host (app layer); every other
    action's playbook targets the whole env group (web + db)."""
    if action == "patch-wordpress":
        return [f"web-{env}"]
    return [f"web-{env}", f"db-{env}"]


def _role_prefix(host: str) -> str:
    """"web-stage" -> "web-", "db-prod" -> "db-" -- the fallback patch.yml
    itself uses when a manifest host isn't an exact inventory hostname."""
    return host.split("-", 1)[0] + "-"


def packages_from_plan(hosts: list[str], plan_path: Path) -> list[dict]:
    """Resolve {name, version} pairs for hosts from a patch-plan manifest:
    exact hostname first, else the first manifest host sharing the role (a
    plan is always frozen against prod, so testing it on stage has to fall
    back to the role match, same as ansible/patch.yml)."""
    if not plan_path.exists():
        return []
    try:
        manifest = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ChangeLogError(f"invalid JSON in {plan_path}: {exc}")
    plan_hosts = manifest.get("hosts", {})
    seen: set[tuple[str, str]] = set()
    packages: list[dict] = []
    for host in hosts:
        data = plan_hosts.get(host)
        if data is None:
            prefix = _role_prefix(host)
            data = next((v for k, v in plan_hosts.items() if k.startswith(prefix)), None)
        if data is None:
            continue
        for pkg in data.get("packages", []):
            key = (pkg["name"], pkg["version"])
            if key in seen:
                continue
            seen.add(key)
            packages.append({"name": pkg["name"], "version": pkg["version"]})
    return packages


def packages_for_action(action: str, hosts: list[str], plan_path: Path) -> list[dict]:
    """The package payload for one change-log record -- see the module
    docstring for why each action resolves packages differently."""
    if action in ("patch", "rollout"):
        return packages_from_plan(hosts, plan_path)
    if action == "patch-wordpress":
        return [{"name": "wordpress-core", "version": WORDPRESS_FIXED_VERSION}]
    return []  # patch-reboot installs nothing


def build_record(action: str, env: str, who: str, plan_path: Path, note: str | None) -> dict:
    """Assemble one change-log record for `action` against `env`."""
    hosts = hosts_for_action(action, env)
    packages = packages_for_action(action, hosts, plan_path)
    now = datetime.now(timezone.utc)
    return {
        "timestamp": now.isoformat(),
        "date": now.date().isoformat(),
        "env": env,
        "hosts": hosts,
        "action": action,
        "who": who,
        "packages": packages,
        "package_count": len(packages),
        "note": note or DEFAULT_NOTES[action],
    }


def append_record(record: dict, path: Path = LOG_PATH, seed: Path = SEED_PATH) -> None:
    """Append one JSON line to the change log, seeding it first if new."""
    ensure_log(path, seed)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Append one record to results/change-log.jsonl (CMDB-style change log)."
    )
    parser.add_argument("--action", required=True, choices=ACTIONS)
    parser.add_argument("--env", required=True, choices=("stage", "prod"))
    parser.add_argument("--who", default=None, help="defaults to $USER / the current user")
    parser.add_argument("--plan", type=Path, default=PLAN_PATH_DEFAULT)
    parser.add_argument("--note", default=None, help="overrides the action's default note")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    who = args.who or os.environ.get("USER") or getpass.getuser()
    try:
        record = build_record(args.action, args.env, who, args.plan, args.note)
        append_record(record)
    except ChangeLogError as exc:
        print(f"change_log_append: {exc}", file=sys.stderr)
        return 1
    print(f"change_log_append: appended {args.action}/{args.env} to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
