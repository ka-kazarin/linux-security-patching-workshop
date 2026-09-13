#!/usr/bin/env python3
"""Compute the delta between two Trivy JSON reports.

Reads a "before" and an "after" Trivy report, classifies every finding as
fixed / new / remaining, writes a CSV compatible with the ``Registry`` sheet of
the Google Sheets template, and renders a self-contained HTML bar chart
(inline SVG, no binary artifacts, no third-party deps).

Runs on the standard library only. Invoked from the Makefile ``delta`` target.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

# Severity order, most severe first. Anything else buckets into UNKNOWN.
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")

# Registry sheet header. delta.py fills what it can infer; the rest is left
# blank for manual triage.
REGISTRY_HEADER = [
    "CVE", "Layer", "Host", "Owner", "CVSS", "EPSS", "KEV", "Severity",
    "Status", "Discovered", "Target SLA date", "Closed date",
    "Advisory URL", "Comment",
]

# Map a Trivy result class to the stand layer and its owner.
CLASS_TO_LAYER = {
    "os-pkgs": ("OS/middleware", "infra"),
    "lang-pkgs": ("app", "dev"),
    "config": ("OS/middleware", "infra"),
}


class DeltaError(Exception):
    """A problem the user can act on; printed as one line, no traceback."""


def load_report(path: Path) -> dict:
    """Load a Trivy JSON report, raising DeltaError with the offending path."""
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise DeltaError(f"report not found: {path}")
    except json.JSONDecodeError as exc:
        raise DeltaError(f"invalid JSON in {path}: {exc}")


def extract_findings(report: dict) -> dict[tuple[str, str], dict]:
    """Flatten a Trivy report into {(CVE, pkg): finding} for set arithmetic."""
    if "Results" not in report:
        raise DeltaError("report has no 'Results' key — is this a Trivy report?")
    findings: dict[tuple[str, str], dict] = {}
    for result in report.get("Results") or []:
        target = result.get("Target", "")
        layer, owner = CLASS_TO_LAYER.get(result.get("Class", ""), ("", ""))
        for vuln in result.get("Vulnerabilities") or []:
            cve = vuln.get("VulnerabilityID", "")
            pkg = vuln.get("PkgName", "")
            severity = vuln.get("Severity", "UNKNOWN").upper()
            findings[(cve, pkg)] = {
                "cve": cve,
                "pkg": pkg,
                "target": target,
                "layer": layer,
                "owner": owner,
                "severity": severity if severity in SEVERITIES else "UNKNOWN",
                "url": vuln.get("PrimaryURL", ""),
                "title": vuln.get("Title", ""),
            }
    return findings


def severity_counts(findings: dict[tuple[str, str], dict]) -> dict[str, int]:
    """Count findings per severity bucket."""
    counts = {sev: 0 for sev in SEVERITIES}
    for finding in findings.values():
        counts[finding["severity"]] += 1
    return counts


def severity_counts_by_host(findings: dict[tuple[str, str], dict]) -> dict[str, dict[str, int]]:
    """Count findings per severity bucket, grouped by Trivy's Target string
    (already "host (os version)", e.g. "web-stage (ubuntu 26.04)")."""
    by_host: dict[str, dict[str, int]] = {}
    for finding in findings.values():
        host = finding["target"] or "(unknown)"
        counts = by_host.setdefault(host, {sev: 0 for sev in SEVERITIES})
        counts[finding["severity"]] += 1
    return by_host


def classify(before: dict, after: dict) -> list[dict]:
    """Tag each finding as fixed / new / remaining across the two reports.

    Ordered most-severe first so the CSV lands with priorities on top.
    """
    rows = []
    for key in before.keys() | after.keys():
        in_before, in_after = key in before, key in after
        status = "fixed" if in_before and not in_after else \
                 "new" if in_after and not in_before else "remaining"
        source = after.get(key) or before.get(key)
        rows.append({**source, "status": status})
    rows.sort(key=lambda r: (SEVERITIES.index(r["severity"]), r["status"]))
    return rows


def write_registry_csv(rows: list[dict], path: Path) -> None:
    """Write rows in the Registry sheet layout; blanks stay for manual triage."""
    # Trivy status -> Registry status: a gone finding is closed, everything else open.
    status_map = {"fixed": "closed", "new": "open", "remaining": "open"}
    today = date.today().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(REGISTRY_HEADER)
        for row in rows:
            writer.writerow([
                row["cve"], row["layer"], row["target"], row["owner"],
                "", "", "", row["severity"], status_map[row["status"]],
                today, "", today if row["status"] == "fixed" else "",
                row["url"], f"{row['status']}: {row['title']}".strip(": "),
            ])


def _svg_bars(before: dict[str, int], after: dict[str, int]) -> str:
    """Return an inline SVG grouped bar chart of counts per severity.

    Each severity gets a "B" (before) and "A" (after) bar side by side —
    the B/A tick plus the legend in write_html_chart is the fix for real
    test feedback ("which column is before, which is after?").
    """
    palette = {"CRITICAL": "#b3202c", "HIGH": "#e06c00", "MEDIUM": "#c9a400",
               "LOW": "#3a7d44", "UNKNOWN": "#7a7a7a"}
    peak = max([*before.values(), *after.values(), 1])
    span, base, top, bar = 90, 250, 30, 26
    parts = []
    for i, sev in enumerate(SEVERITIES):
        x = 40 + i * (span + 20)
        for j, (label, counts) in enumerate((("before", before), ("after", after))):
            h = (counts[sev] / peak) * (base - top)
            bx = x + j * (bar + 6)
            fill = palette[sev] if label == "before" else palette[sev] + "88"
            parts.append(
                f'<rect x="{bx}" y="{base - h:.0f}" width="{bar}" '
                f'height="{h:.0f}" fill="{fill}"/>'
                f'<text x="{bx + bar / 2:.0f}" y="{base - h - 6:.0f}" '
                f'font-size="12" text-anchor="middle">{counts[sev]}</text>'
                f'<text x="{bx + bar / 2:.0f}" y="{base + 12}" font-size="10" '
                f'text-anchor="middle" fill="#555">{label[0].upper()}</text>')
        parts.append(
            f'<text x="{x + bar:.0f}" y="{base + 26}" font-size="12" '
            f'text-anchor="middle">{sev}</text>')
    return (f'<svg viewBox="0 0 {40 + len(SEVERITIES) * (span + 20)} 300" '
            f'style="width:100%;height:auto;max-height:280px" '
            f'xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">'
            + "".join(parts) + "</svg>")


def _chart_section(title: str, before: dict[str, int], after: dict[str, int]) -> str:
    """One grid cell: <h2> + bar chart, reused for the overall total and each host."""
    return f"<div class='chart-cell'><h2>{title}</h2>" + _svg_bars(before, after) + "</div>"


def write_html_chart(before: dict[str, int], after: dict[str, int],
                     before_by_host: dict[str, dict[str, int]],
                     after_by_host: dict[str, dict[str, int]],
                     rows: list[dict], path: Path) -> None:
    """Render a self-contained HTML report: overall totals + a chart per
    host (inline SVG, no external assets)."""
    fixed = sum(1 for r in rows if r["status"] == "fixed")
    new = sum(1 for r in rows if r["status"] == "new")
    remaining = sum(1 for r in rows if r["status"] == "remaining")
    zero = {sev: 0 for sev in SEVERITIES}
    all_hosts = sorted(set(before_by_host) | set(after_by_host))
    per_host_sections = "".join(
        _chart_section(host, before_by_host.get(host, zero), after_by_host.get(host, zero))
        for host in all_hosts
    )
    # Overall full-width, hosts in their own single row below (not one grid
    # with everything in it): a fixed 2-1fr-column grid drifted into 3+ rows
    # and needed scrolling as soon as prod hosts joined stage (5 cells,
    # not 3) -- reported live. This way it's always exactly two rows, on
    # stage-only (2 hosts) or the full profile (4 hosts) alike, sized to
    # the actual host count so it stays on one screen without scrolling.
    host_columns = max(len(all_hosts), 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Scan delta</title>"
        "<style>"
        "body{font-family:sans-serif;margin:1.5rem}"
        f".host-grid{{display:grid;grid-template-columns:repeat({host_columns},1fr);"
        "gap:0.5rem 1.5rem;margin-top:0.5rem}}"
        ".chart-cell h2{margin:0 0 0.25rem;font-size:15px}"
        "</style>"
        "</head><body>"
        "<h1>Scan delta: before / after patching</h1>"
        f"<p>Fixed: <b>{fixed}</b> &middot; New: <b>{new}</b> &middot; "
        f"Remaining: <b>{remaining}</b></p>"
        "<p><b>Legend:</b> "
        "<span style='display:inline-block;width:14px;height:14px;"
        "background:#555;vertical-align:middle;margin:0 4px'></span>before"
        "&nbsp;&nbsp;"
        "<span style='display:inline-block;width:14px;height:14px;"
        "background:#55555588;vertical-align:middle;margin:0 4px'></span>after"
        " &mdash; each bar is also marked B/A. Each severity column shows two"
        " bars: before (left, solid) and after (right, translucent).</p>"
        + _chart_section("Overall (all hosts)", before, after)
        + f"<div class='host-grid'>{per_host_sections}</div>"
        + "<p style='color:#666;font-size:12px'>Generated by scan/delta.py.</p>"
        "</body></html>",
        encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Delta between two Trivy reports.")
    parser.add_argument("--before", type=Path,
                        default=root / "examples" / "scan-before.json")
    parser.add_argument("--after", type=Path,
                        default=root / "examples" / "scan-after.json")
    parser.add_argument("--csv", type=Path,
                        default=root.parent / "docs" / "fallback" / "delta.csv")
    parser.add_argument("--html", type=Path,
                        default=root.parent / "docs" / "fallback" / "delta.html")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        before = extract_findings(load_report(args.before))
        after = extract_findings(load_report(args.after))
    except DeltaError as exc:
        print(f"delta: {exc}", file=sys.stderr)
        return 1
    rows = classify(before, after)
    write_registry_csv(rows, args.csv)
    write_html_chart(
        severity_counts(before), severity_counts(after),
        severity_counts_by_host(before), severity_counts_by_host(after),
        rows, args.html,
    )
    fixed = sum(1 for r in rows if r["status"] == "fixed")
    new = sum(1 for r in rows if r["status"] == "new")
    print(f"delta: fixed {fixed}, new {new}, total rows {len(rows)}")
    print(f"  CSV : {args.csv}")
    print(f"  HTML: {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
