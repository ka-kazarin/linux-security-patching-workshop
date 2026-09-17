#!/usr/bin/env python3
"""Render the HTML report for a frozen patch-plan manifest.

Reads the JSON manifest ``ansible/patch-plan.yml`` writes
(results/patch-plan.json: per-host pending SECURITY package/version pairs,
nothing installed yet) and renders it in the stand's shared report style
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
    """One collapsible per-host block: the summary always shows host/OS and
    the package/advisory counts; expanding reveals the package table (or an
    empty-state line when the host has zero pending security packages --
    already up to date, not an error). Collapsed by default so a 100+-package
    plan stays scannable."""
    packages = data.get("packages", [])
    counts = data.get("counts", {"packages": len(packages), "advisories": 0})
    n_pkg, n_adv = counts.get("packages", 0), counts.get("advisories", 0)
    if not packages:
        inner = "<p class='legend'>No pending security updates — already up to date.</p>"
    else:
        rows = "".join(
            f"<tr><td>{p['name']}</td><td>{p['version']}</td>"
            f"<td>{', '.join(p.get('advisories', [])) or '&mdash;'}</td></tr>"
            for p in packages
        )
        inner = (
            "<table><thead><tr><th>Package</th><th>Version</th>"
            f"<th>Advisory</th></tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        f"<details class='host'><summary>{host} "
        f"<span class='sub-os'>({data.get('os', 'unknown')})</span> &middot; "
        f"<b>{n_pkg}</b> package(s), <b>{n_adv}</b> advisory(ies)</summary>"
        f"<div class='inner'>{inner}</div></details>"
    )


def write_html_report(manifest: dict, path: Path) -> None:
    """Render a self-contained HTML patch-plan report, one card per host."""
    hosts = manifest.get("hosts", {})
    total_packages = sum(h.get("counts", {}).get("packages", 0) for h in hosts.values())
    total_advisories = sum(h.get("counts", {}).get("advisories", 0) for h in hosts.values())
    extra_css = (
        ".sub-os{font-weight:400;color:var(--muted);font-size:.82rem}"
        # Fixed column geometry so both OSes render identically: without this,
        # auto-layout lets Oracle's long comma-joined ELSA lists blow out the
        # Advisory column and cram Package/Version against the left edge, while
        # Ubuntu's single short USN spreads evenly. Fixed shares + wrapping in
        # the advisory column keep the table full-width and consistent.
        ".host table{table-layout:fixed}"
        ".host td{vertical-align:top;overflow-wrap:anywhere}"
        ".host th:nth-child(1),.host td:nth-child(1){width:34%}"
        ".host th:nth-child(2),.host td:nth-child(2){width:28%}"
        ".host th:nth-child(3),.host td:nth-child(3){width:38%}"
    )
    body = (
        "<div class='stats'>"
        f"<div class='pill'><span class='n'>{total_packages}</span><span class='l'>packages</span></div>"
        f"<div class='pill'><span class='n'>{total_advisories}</span><span class='l'>advisories</span></div>"
        f"<div class='pill'><span class='n'>{len(hosts)}</span><span class='l'>hosts</span></div>"
        "</div>"
        "<p class='legend'>Frozen plan — computed, not installed. A host with "
        "zero pending packages is already up to date.</p>"
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
