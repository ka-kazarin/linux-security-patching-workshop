#!/usr/bin/env python3
"""Compare two load-baseline JSON files produced by ansible/bench.yml.

Reads a "before" and an "after" bench run (wrk against nginx/PHP on the web
host, sysbench oltp_read_only against MySQL on the db host — one entry per
host/metric, schema documented in ansible/bench.yml: a warmup run discarded,
then 2 timed runs sampled at a fixed interval into a throughput+latency time
series). Prints a before/after/delta table per host/metric/measure using the
**median** across every sample from both timed runs, shows p90 alongside for
context, and flags anything that regressed past a tolerance.

This is a smoke-level baseline, not a rigorous benchmark: a single VM's
noise floor is comfortably within double digits of percent between two
otherwise-identical runs. The default 20% tolerance is chosen to absorb
that noise, not to hide a real regression -- runs on a webinar demo stand,
not a performance lab. The median/p90-over-samples methodology (rather than
one shot from a single run) exists specifically to keep a warmed-up OS disk
cache on the second run from reading as a false "regression".

Runs on the standard library only. Invoked from the Makefile ``bench-delta``
target.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from report_style import page

DEFAULT_TOLERANCE_PCT = 20.0

# (measure, unit, higher-is-worse) -- throughput regresses on a *drop*,
# latency regresses on a *rise*. Keys in the bench JSON are median_<measure>
# / p90_<measure>.
MEASURES = (("throughput", "req/s", False), ("latency", "ms", True))


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


def build_rows(before: dict[tuple[str, str], dict],
                after: dict[tuple[str, str], dict],
                tolerance: float) -> list[dict]:
    """One row per host/metric/measure present in both runs, median-driven.

    p90 rides along for context but never drives the verdict: a single
    slow-tail sample is expected noise on a shared VM, not a regression.
    """
    rows = []
    missing = (before.keys() ^ after.keys())
    if missing:
        keys = ", ".join(f"{h}/{m}" for h, m in sorted(missing))
        print(f"bench: skipping metrics only present in one report: {keys}", file=sys.stderr)
    for key in sorted(before.keys() & after.keys()):
        host, metric = key
        b, a = before[key], after[key]
        if b.get("tool") != a.get("tool"):
            print(f"bench: {host}/{metric} used different tools before ({b.get('tool')}) "
                  f"vs after ({a.get('tool')}) -- numbers are not comparable", file=sys.stderr)
        for measure, unit, higher_is_worse in MEASURES:
            median_b, median_a = b[f"median_{measure}"], a[f"median_{measure}"]
            p90_b, p90_a = b[f"p90_{measure}"], a[f"p90_{measure}"]
            delta = pct_delta(median_b, median_a)
            regressed = delta > tolerance if higher_is_worse else delta < -tolerance
            rows.append({
                "label": f"{host}/{metric} {measure} ({unit})",
                "host": host, "metric": metric, "measure": measure,
                "median_before": median_b, "median_after": median_a, "delta": delta,
                "p90_before": p90_b, "p90_after": p90_a,
                "verdict": "REGRESSION" if regressed else "OK",
                # Sparkline data rides only on the throughput row -- the
                # instructive time series is "did throughput hold up over
                # the run", not a duplicate chart per measure.
                "samples_before": b["samples"] if measure == "throughput" else None,
                "samples_after": a["samples"] if measure == "throughput" else None,
            })
    return rows


def print_table(rows: list[dict]) -> None:
    """Print an aligned metric | median before/after | delta% | p90 before/after | verdict table."""
    header = ("metric", "median before", "median after", "delta %", "p90 before", "p90 after", "verdict")
    formatted = [
        (r["label"], f"{r['median_before']:.2f}", f"{r['median_after']:.2f}", f"{r['delta']:+.1f}%",
         f"{r['p90_before']:.2f}", f"{r['p90_after']:.2f}",
         "OK" if r["verdict"] == "OK" else "⚠ REGRESSION")
        for r in rows
    ]
    widths = [max(len(header[i]), *(len(row[i]) for row in formatted)) for i in range(len(header))]

    def fmt_row(cols: tuple) -> str:
        return "  ".join(c.ljust(w) for c, w in zip(cols, widths))

    print(fmt_row(header))
    print("  ".join("-" * w for w in widths))
    for row in formatted:
        print(fmt_row(row))


def _svg_sparkline(samples_before: list[dict], samples_after: list[dict],
                   width: int = 420, height: int = 70, pad: int = 6) -> str:
    """Inline SVG line chart of throughput over samples, before vs after
    overlaid (solid navy = before, dashed cyan = after) -- same "no external
    assets" inline-SVG style as scan/delta.py's _svg_bars, adapted from bars
    to a time series. X is sample *index*, not wall-clock time: before/after
    runs are independent processes and this keeps both lines plotted even if
    one run collected a slightly different sample count than the other.
    """
    values = [s["throughput"] for s in samples_before] + [s["throughput"] for s in samples_after]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0

    def polyline(samples: list[dict]) -> str:
        n = len(samples)
        pts = []
        for i, s in enumerate(samples):
            x = pad + ((i / (n - 1)) if n > 1 else 0.5) * (width - 2 * pad)
            y = pad + (1 - (s["throughput"] - lo) / span) * (height - 2 * pad)
            pts.append(f"{x:.1f},{y:.1f}")
        return " ".join(pts)

    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'style="width:100%;height:auto;max-height:90px" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<polyline points="{polyline(samples_before)}" fill="none" '
        f'stroke="#16324f" stroke-width="2"/>'
        f'<polyline points="{polyline(samples_after)}" fill="none" '
        f'stroke="#18c3e6" stroke-width="2" stroke-dasharray="5 3"/>'
        f'</svg>'
    )


def write_html_report(rows: list[dict], tolerance: float, path: Path) -> None:
    """Render a self-contained HTML load-baseline report in the shared style
    (scan/report_style.py) — a before/after/delta table with an OK/regression
    verdict per metric, plus a throughput sparkline (before vs after
    overlaid) per metric. Same visual identity as the scan delta report."""
    regressions = sum(1 for r in rows if r["verdict"] == "REGRESSION")
    reg_class = "bad" if regressions else "good"
    trows = []
    for r in rows:
        ok = r["verdict"] == "OK"
        trend = (f"<td class='trend'>{_svg_sparkline(r['samples_before'], r['samples_after'])}</td>"
                 if r["samples_before"] is not None else "<td class='trend'>&mdash;</td>")
        trows.append(
            f"<tr><td>{r['label']}</td>"
            f"<td class='num'>{r['median_before']:.2f}</td>"
            f"<td class='num'>{r['median_after']:.2f}</td>"
            f"<td class='num {'delta-good' if ok else 'delta-bad'}'>{r['delta']:+.1f}%</td>"
            f"<td class='num'>{r['p90_before']:.2f}</td>"
            f"<td class='num'>{r['p90_after']:.2f}</td>"
            f"<td><span class='badge {'ok' if ok else 'bad'}'>"
            f"{'OK' if ok else '⚠ REGRESSION'}</span></td>"
            + trend + "</tr>")
    extra_css = (".trend{min-width:140px}"
                 ".trend svg{display:block}")
    body = (
        "<div class='stats'>"
        f"<div class='pill {reg_class}'><span class='n'>{regressions}</span>"
        f"<span class='l'>regression{'' if regressions == 1 else 's'}</span></div>"
        f"<div class='pill'><span class='n'>{tolerance:.0f}%</span>"
        "<span class='l'>tolerance</span></div>"
        "</div>"
        "<p class='legend'>Smoke-level load baseline &mdash; not a rigorous "
        "benchmark. Each metric: 1 warmup run (discarded) + 2 timed runs, "
        "sampled at a fixed interval; <b>median</b> drives the verdict, "
        "<b>p90</b> is shown for context only. A metric is flagged only if "
        "its median moved unfavourably by more than the tolerance.</p>"
        "<p class='legend'><span class='trend-sw before'></span>before"
        "<span class='trend-sw after'></span>after"
        "&mdash; throughput per sample across both timed runs.</p>"
        "<section class='card'><h2>Before / after &mdash; median, p90 &amp; trend</h2>"
        "<table><thead><tr><th>Metric</th><th class='num'>Median before</th>"
        "<th class='num'>Median after</th><th class='num'>&Delta; (median)</th>"
        "<th class='num'>P90 before</th><th class='num'>P90 after</th>"
        "<th>Verdict</th><th>Trend (throughput)</th>"
        f"</tr></thead><tbody>{''.join(trows)}</tbody></table></section>")
    extra_css += (".trend-sw{display:inline-block;width:16px;height:2px;vertical-align:middle;"
                  "margin:0 .3rem 0 .8rem;background:#16324f}"
                  ".trend-sw.after{background:repeating-linear-gradient(90deg,#18c3e6 0 5px,transparent 5px 8px)}"
                  ".trend-sw:first-of-type{margin-left:0}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        page("Load baseline", "Performance before / after patching",
             body, "scan/bench_compare.py", extra_css),
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
    print(f"Load baseline comparison (smoke-level, median-driven, tolerance {args.tolerance:.0f}%):\n")
    print_table(rows)
    write_html_report(rows, args.tolerance, args.html)
    regressions = sum(1 for r in rows if r["verdict"] == "REGRESSION")
    print()
    if regressions:
        print(f"bench: {regressions} metric(s) outside tolerance -- see ⚠ REGRESSION above")
    else:
        print("bench: no significant regression detected")
    print(f"  HTML: {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
