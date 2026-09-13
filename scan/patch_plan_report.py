#!/usr/bin/env python3
"""Render the HTML report for a frozen patch-plan manifest.

Reads the JSON manifest ``ansible/patch-plan.yml`` writes (results/patch-
plan-<env>.json: per-host pending SECURITY package/version pairs, nothing
installed yet) and renders it in the stand's shared report style
(``report_style.py``) -- one card per host with a package -> version ->
advisory table, "packages / advisories" pill counters answering "what will
this close, and how much of it."

Runs on the standard library only. Invoked from ansible/patch-plan.yml's
controller-side play (the ``patch-plan`` Makefile target), right after the
manifest JSON is written.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from report_style import page


class PatchPlanError(Exception):
    """A problem the user can act on; printed as one line, no traceback."""


def load_manifest(path: Path) -> dict:
    """Load the patch-plan manifest JSON, raising PatchPlanError with the offending path."""
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise PatchPlanError(f"manifest not found: {path} (run `make patch-plan` first)")
    except json.JSONDecodeError as exc:
        raise PatchPlanError(f"invalid JSON in {path}: {exc}")


def _host_section(host: str, data: dict) -> str:
    """One card: host name/OS + its package table, or an empty-state line
    when the host has zero pending security packages (already up to date,
    not an error)."""
    packages = data.get("packages", [])
    counts = data.get("counts", {"packages": len(packages), "advisories": 0})
    if not packages:
        body = "<p class='legend'>No pending security updates — already up to date.</p>"
    else:
        rows = "".join(
            f"<tr><td>{p['name']}</td><td>{p['version']}</td>"
            f"<td>{', '.join(p.get('advisories', [])) or '&mdash;'}</td></tr>"
            for p in packages
        )
        body = (
            "<table><thead><tr><th>Package</th><th>Version</th>"
            f"<th>Advisory</th></tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        f"<section class='card'><h2>{host} <span class='sub-os'>({data.get('os', 'unknown')})</span></h2>"
        "<div class='stats'>"
        f"<div class='pill'><span class='n'>{counts.get('packages', 0)}</span><span class='l'>packages</span></div>"
        f"<div class='pill'><span class='n'>{counts.get('advisories', 0)}</span><span class='l'>advisories</span></div>"
        "</div>"
        + body + "</section>"
    )


def write_html_report(manifest: dict, path: Path) -> None:
    """Render a self-contained HTML patch-plan report, one card per host."""
    hosts = manifest.get("hosts", {})
    total_packages = sum(h.get("counts", {}).get("packages", 0) for h in hosts.values())
    total_advisories = sum(h.get("counts", {}).get("advisories", 0) for h in hosts.values())
    extra_css = ".sub-os{font-weight:400;color:var(--muted);font-size:.82rem}"
    body = (
        "<div class='stats'>"
        f"<div class='pill'><span class='n'>{total_packages}</span><span class='l'>packages</span></div>"
        f"<div class='pill'><span class='n'>{total_advisories}</span><span class='l'>advisories</span></div>"
        f"<div class='pill'><span class='n'>{len(hosts)}</span><span class='l'>hosts</span></div>"
        "</div>"
        "<p class='legend'>Frozen security-update plan — computed, not installed. "
        "<code>make patch ENV=...</code> installs exactly these package/version "
        "pairs when this manifest exists; a host with zero pending packages is "
        "already up to date, not a bug.</p>"
        + "".join(_host_section(host, data) for host, data in sorted(hosts.items()))
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        page(f"Patch plan — {manifest.get('env', 'unknown')}",
             f"Pending security updates, frozen at {manifest.get('generated_at', 'unknown time')}",
             body, "scan/patch_plan_report.py", extra_css),
        encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render the HTML report for a patch-plan manifest.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--html", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except PatchPlanError as exc:
        print(f"patch_plan_report: {exc}", file=sys.stderr)
        return 1
    write_html_report(manifest, args.html)
    print(f"patch_plan_report: wrote {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
