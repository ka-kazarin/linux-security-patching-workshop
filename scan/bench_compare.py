#!/usr/bin/env python3
"""Compare two load-baseline JSON files produced by ansible/bench.yml.

Reads a "before" and an "after" bench run (nginx/PHP via ab, MySQL via
mysqlslap — one entry per host/metric, schema documented in
ansible/bench.yml), prints a before/after/delta table per host/metric/measure,
and flags anything that regressed past a tolerance.

This is a smoke-level baseline, not a rigorous benchmark: a single VM's
noise floor is comfortably within double digits of percent between two
otherwise-identical runs. The default 20% tolerance is chosen to absorb
that noise, not to hide a real regression -- runs on a webinar demo stand,
not a performance lab.

Runs on the standard library only. Invoked from the Makefile ``bench`` target.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from report_style import page

DEFAULT_TOLERANCE_PCT = 20.0


class BenchError(Exception):
    """A problem the user can act on; printed as one line, no traceback."""


def load_report(path: Path) -> list[dict]:
    """Load a bench JSON report, raising BenchError with the offending path."""
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise BenchError(
            f"report not found: {path} (run `make bench-before`/`make bench-after` first)"
        )
    except json.JSONDecodeError as exc:
        raise BenchError(f"invalid JSON in {path}: {exc}")
    if not isinstance(data, list):
        raise BenchError(f"{path}: expected a JSON list of bench entries")
    return data


def index_by_key(entries: list[dict]) -> dict[tuple[str, str], dict]:
    """Key entries by (host, metric) — one row per host/metric in bench.yml."""
    indexed: dict[tuple[str, str], dict] = {}
    for entry in entries:
        try:
            key = (entry["host"], entry["metric"])
        except KeyError as exc:
            raise BenchError(f"bench entry missing field {exc}: {entry}")
        indexed[key] = entry
    return indexed


def pct_delta(before: float, after: float) -> float:
    """Percent change from before to after; before=0 reports +inf as a flag."""
    if before == 0:
        return float("inf") if after else 0.0
    return (after - before) / before * 100


def verdict_for(measure: str, delta: float, tolerance: float) -> str:
    """OK unless the change is a regression beyond tolerance.

    requests_per_sec: a drop worse than -tolerance% is a regression.
    latency_ms: a rise worse than +tolerance% is a regression.
    Either metric getting *better* is never flagged.
    """
    if measure == "requests_per_sec":
        return "REGRESSION" if delta < -tolerance else "OK"
    return "REGRESSION" if delta > tolerance else "OK"  # latency_ms


def build_rows(before: dict[tuple[str, str], dict],
                after: dict[tuple[str, str], dict],
                tolerance: float) -> list[tuple[str, float, float, float, str]]:
    """One row per host/metric/measure present in both runs."""
    rows = []
    missing = (before.keys() ^ after.keys())
    if missing:
        keys = ", ".join(f"{h}/{m}" for h, m in sorted(missing))
        print(f"bench: skipping metrics only present in one report: {keys}", file=sys.stderr)
    for key in sorted(before.keys() & after.keys()):
        host, metric = key
        b, a = before[key], after[key]
        for measure, unit in (("requests_per_sec", "req/s"), ("latency_ms", "ms")):
            b_val, a_val = b[measure], a[measure]
            delta = pct_delta(b_val, a_val)
            label = f"{host}/{metric} {measure} ({unit})"
            rows.append((label, b_val, a_val, delta, verdict_for(measure, delta, tolerance)))
    return rows


def print_table(rows: list[tuple[str, float, float, float, str]]) -> None:
    """Print an aligned metric | before | after | delta% | verdict table."""
    header = ("metric", "before", "after", "delta %", "verdict")
    formatted = [
        (label, f"{b:.2f}", f"{a:.2f}", f"{delta:+.1f}%",
         "OK" if verdict == "OK" else "⚠ REGRESSION")
        for label, b, a, delta, verdict in rows
    ]
    widths = [max(len(header[i]), *(len(r[i]) for r in formatted)) for i in range(5)]

    def fmt_row(cols: tuple) -> str:
        return "  ".join(c.ljust(w) for c, w in zip(cols, widths))

    print(fmt_row(header))
    print("  ".join("-" * w for w in widths))
    for row in formatted:
        print(fmt_row(row))


def write_html_report(rows: list[tuple[str, float, float, float, str]],
                      tolerance: float, path: Path) -> None:
    """Render a self-contained HTML load-baseline report in the shared style
    (scan/report_style.py) — a before/after/delta table with an OK/regression
    verdict per metric. Same visual identity as the scan delta report."""
    regressions = sum(1 for r in rows if r[4] == "REGRESSION")
    reg_class = "bad" if regressions else "good"
    trows = []
    for label, b, a, delta, verdict in rows:
        ok = verdict == "OK"
        trows.append(
            f"<tr><td>{label}</td>"
            f"<td class='num'>{b:.2f}</td>"
            f"<td class='num'>{a:.2f}</td>"
            f"<td class='num {'delta-good' if ok else 'delta-bad'}'>{delta:+.1f}%</td>"
            f"<td><span class='badge {'ok' if ok else 'bad'}'>"
            f"{'OK' if ok else '⚠ REGRESSION'}</span></td></tr>")
    body = (
        "<div class='stats'>"
        f"<div class='pill {reg_class}'><span class='n'>{regressions}</span>"
        f"<span class='l'>regression{'' if regressions == 1 else 's'}</span></div>"
        f"<div class='pill'><span class='n'>{tolerance:.0f}%</span>"
        "<span class='l'>tolerance</span></div>"
        "</div>"
        "<p class='legend'>Smoke-level load baseline &mdash; not a rigorous "
        "benchmark. A metric is flagged only if it moved unfavourably by more "
        "than the tolerance (single-VM noise floor sits comfortably under it).</p>"
        "<section class='card'><h2>Before / after &mdash; throughput &amp; latency</h2>"
        "<table><thead><tr><th>Metric</th><th class='num'>Before</th>"
        "<th class='num'>After</th><th class='num'>&Delta;</th><th>Verdict</th>"
        f"</tr></thead><tbody>{''.join(trows)}</tbody></table></section>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        page("Load baseline", "Performance before / after patching",
             body, "scan/bench_compare.py"),
        encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare two bench.yml load-baseline reports.")
    parser.add_argument("--before", type=Path, default=Path("results/bench-before.json"))
    parser.add_argument("--after", type=Path, default=Path("results/bench-after.json"))
    parser.add_argument("--html", type=Path, default=Path("results/bench.html"),
                        help="self-contained HTML report (default: results/bench.html)")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE_PCT,
                        help=f"allowed drift in %% before flagging a regression (default: {DEFAULT_TOLERANCE_PCT})")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        before = index_by_key(load_report(args.before))
        after = index_by_key(load_report(args.after))
        rows = build_rows(before, after, args.tolerance)
    except BenchError as exc:
        print(f"bench: {exc}", file=sys.stderr)
        return 1
    if not rows:
        print("bench: no matching host/metric pairs between before and after", file=sys.stderr)
        return 1
    print(f"Load baseline comparison (smoke-level, tolerance {args.tolerance:.0f}%):\n")
    print_table(rows)
    write_html_report(rows, args.tolerance, args.html)
    regressions = sum(1 for r in rows if r[4] == "REGRESSION")
    print()
    if regressions:
        print(f"bench: {regressions} metric(s) outside tolerance -- see ⚠ REGRESSION above")
    else:
        print("bench: no significant regression detected")
    print(f"  HTML: {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
