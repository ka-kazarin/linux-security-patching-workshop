#!/usr/bin/env python3
"""Compute the delta between two Trivy JSON reports.

Reads a "before" and an "after" Trivy report, classifies every finding as
fixed / new / remaining, writes a registry-style CSV (one row per finding with
owner/SLA triage columns), and renders a self-contained HTML bar chart
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

from report_style import PALETTE, page

# Severity order, most severe first. Anything else buckets into UNKNOWN.
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")

# Registry CSV header. delta.py fills what it can infer; the rest is left
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
    """Write rows in the registry CSV layout; blanks stay for manual triage."""
    # Trivy status -> registry status: a gone finding is closed, everything else open.
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

    Each severity gets a "before" (solid) and "after" (translucent) bar side
    by side, with a value label above and a B/A tick below — the tick plus the
    legend answer real test feedback ("which column is before, which is after?").
    """
    peak = max([*before.values(), *after.values(), 1])
    pad_l, pad_r, top, plot_h = 8, 8, 22, 170
    bar, gap_ba, gap_grp = 24, 9, 40
    base = top + plot_h
    grp_w = 2 * bar + gap_ba
    width = pad_l + len(SEVERITIES) * grp_w + (len(SEVERITIES) - 1) * gap_grp + pad_r
    height = base + 40
    parts = [f'<line x1="{pad_l}" y1="{base}" x2="{width - pad_r}" y2="{base}" '
             f'stroke="#d7e0e8" stroke-width="1"/>']
    for i, sev in enumerate(SEVERITIES):
        gx = pad_l + i * (grp_w + gap_grp)
        for j, (label, counts) in enumerate((("before", before), ("after", after))):
            n = counts[sev]
            h = (n / peak) * plot_h
            bx = gx + j * (bar + gap_ba)
            opacity = "1" if label == "before" else ".45"
            parts.append(
                f'<rect x="{bx}" y="{base - h:.1f}" width="{bar}" height="{h:.1f}" '
                f'rx="3" fill="{PALETTE[sev]}" fill-opacity="{opacity}"/>'
                f'<text x="{bx + bar / 2:.0f}" y="{base - h - 6:.0f}" font-size="12" '
                f'font-weight="600" text-anchor="middle" fill="#0f1b28">{n}</text>'
                f'<text x="{bx + bar / 2:.0f}" y="{base + 15}" font-size="10" '
                f'text-anchor="middle" fill="#8b96a5">{label[0].upper()}</text>')
        parts.append(
            f'<text x="{gx + grp_w / 2:.0f}" y="{base + 31}" font-size="11" '
            f'font-weight="600" text-anchor="middle" fill="#5a6b7b">{sev}</text>')
    return (f'<svg viewBox="0 0 {width} {height}" role="img" '
            f'style="width:100%;height:auto;max-height:240px" '
            f'xmlns="http://www.w3.org/2000/svg">' + "".join(parts) + "</svg>")


def _chart_section(title: str, before: dict[str, int], after: dict[str, int],
                   klass: str = "card") -> str:
    """One card: <h2> + bar chart, reused for the overall total and each host."""
    return (f"<section class='{klass}'><h2>{title}</h2>"
            + _svg_bars(before, after) + "</section>")


def write_html_chart(before: dict[str, int], after: dict[str, int],
                     before_by_host: dict[str, dict[str, int]],
                     after_by_host: dict[str, dict[str, int]],
                     rows: list[dict], path: Path) -> None:
    """Render a self-contained HTML report: overall totals + a chart per
    host (inline SVG + CSS, no external assets)."""
    fixed = sum(1 for r in rows if r["status"] == "fixed")
    new = sum(1 for r in rows if r["status"] == "new")
    remaining = sum(1 for r in rows if r["status"] == "remaining")
    zero = {sev: 0 for sev in SEVERITIES}
    all_hosts = sorted(set(before_by_host) | set(after_by_host))
    per_host_sections = "".join(
        _chart_section(host, before_by_host.get(host, zero), after_by_host.get(host, zero))
        for host in all_hosts
    )
    # Overall full-width, hosts in their own responsive grid below: sized to
    # the actual host count (auto-fit) so it stays on one screen without
    # horizontal scroll on stage-only (2 hosts) or the full profile (4) alike.
    host_columns = max(len(all_hosts), 1)
    # Status pills use their OWN palette (grey / violet / blue), deliberately
    # NOT the red-orange-yellow-green severity ramp the bars use — mixing the
    # two reads as "green = good severity". fixed=grey (done, at rest),
    # new=violet (arrived, needs a look), remaining=blue (still open).
    extra_css = (f".host-grid{{display:grid;gap:1.25rem;"
                 f"grid-template-columns:repeat({host_columns},minmax(0,1fr))}}"
                 "@media(max-width:640px){.host-grid{grid-template-columns:1fr}}"
                 ".pill.fixed{border-left-color:#8b96a5}.pill.fixed .n{color:#5a6b7b}"
                 ".pill.new{border-left-color:#8b5cf6}.pill.new .n{color:#7c3aed}"
                 ".pill.remaining{border-left-color:#3b82c4}.pill.remaining .n{color:#2f6fb0}")
    body = (
        "<div class='stats'>"
        f"<div class='pill fixed'><span class='n'>{fixed}</span><span class='l'>fixed</span></div>"
        f"<div class='pill remaining'><span class='n'>{remaining}</span><span class='l'>remaining</span></div>"
        f"<div class='pill new'><span class='n'>{new}</span><span class='l'>new</span></div>"
        "</div>"
        "<p class='legend'><b>new</b> = present only in the after-scan &mdash; a "
        "package upgraded to a newer version brought its own advisories, not a "
        "regression the patch caused.</p>"
        "<p class='legend'><span class='sw'></span>before"
        "<span class='sw after'></span>after &mdash; two bars per severity (B / A).</p>"
        + _chart_section("Overall — all hosts", before, after, "card overall")
        + f"<div class='host-grid'>{per_host_sections}</div>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        page("Scan delta",
             "Vulnerability findings before / after patching",
             body, "scan/delta.py", extra_css),
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
