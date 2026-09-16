#!/usr/bin/env python3
"""Compare two load-baseline JSON files produced by ansible/bench.yml.

Reads a "before" and an "after" bench run (vegeta against nginx/PHP on the
web host, sysbench oltp_read_only against MySQL on the db host — one entry
per host/metric, schema documented in ansible/bench.yml: a warmup run
discarded, then 2 timed runs at a FIXED sub-saturation rate, sampled at a
fixed interval into a p50/p95-latency + success-rate time series). Prints a
before/after/delta table per host/metric using the **median p95 latency**
(plus success rate) across every sample from both timed runs, and flags
anything that regressed past tolerance.

Fixed-rate-below-the-ceiling is the point: a rate held under the endpoint's
capacity keeps the server from ever queueing, so p95 latency barely moves
between two otherwise-identical runs -- unlike peak-throughput numbers on a
shared demo VM, which chase whatever CPU the noisy-neighbour scheduler
allows *this second* and can legitimately swing ±30-56% run to run. The
default tolerance below is still generous (this remains a smoke-level
baseline on a single VM, not a performance lab) but far tighter than a
throughput-driven one needed to be.

Runs on the standard library only. Invoked from the Makefile ``bench-delta``
target.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from report_style import page

DEFAULT_TOLERANCE_PCT = 25.0
# A drop in success rate, in percentage points, that counts as a regression
# on its own -- independent of the latency tolerance above. At a fixed rate
# safely under the ceiling, success should sit at ~100% before AND after;
# any real drop means the patch made the service start shedding requests.
DEFAULT_SUCCESS_DROP_PP = 1.0


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
                tolerance: float, success_drop_pp: float) -> list[dict]:
    """One row per host/metric present in both runs, median-p95-driven.

    A row regresses if median p95 rose past ``tolerance`` percent OR the
    median success rate dropped more than ``success_drop_pp`` percentage
    points -- either one is a real user-visible regression at a rate that
    was never supposed to saturate the service.
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
        if b.get("rate") != a.get("rate"):
            print(f"bench: {host}/{metric} used different rates before ({b.get('rate')}) "
                  f"vs after ({a.get('rate')}) -- numbers are not comparable", file=sys.stderr)

        p95_b, p95_a = b["median_p95"], a["median_p95"]
        delta = pct_delta(p95_b, p95_a)
        latency_regressed = delta > tolerance

        success_b = b["median_success"] * 100
        success_a = a["median_success"] * 100
        success_regressed = (success_b - success_a) > success_drop_pp

        rows.append({
            "label": f"{host}/{metric}", "host": host, "metric": metric,
            "tool": b.get("tool"), "rate": b.get("rate"),
            "p50_before": b.get("median_p50"), "p50_after": a.get("median_p50"),
            "p95_before": p95_b, "p95_after": p95_a, "delta": delta,
            "success_before": success_b, "success_after": success_a,
            "verdict": "REGRESSION" if (latency_regressed or success_regressed) else "OK",
            "samples_before": b["samples"], "samples_after": a["samples"],
        })
    return rows


def _fmt_rate(row: dict) -> str:
    unit = "tps" if row["tool"] == "sysbench" else "req/s"
    rate = row["rate"]
    return f"{rate} {unit}" if rate is not None else "?"


def _fmt_ms(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "-"


def print_table(rows: list[dict]) -> None:
    """Print an aligned metric | rate | p50/p95 before/after | delta% | success | verdict table."""
    header = ("metric", "rate", "p50 before", "p50 after", "p95 before", "p95 after",
               "delta % (p95)", "success before", "success after", "verdict")
    formatted = [
        (r["label"], _fmt_rate(r), _fmt_ms(r["p50_before"]), _fmt_ms(r["p50_after"]),
         f"{r['p95_before']:.2f}", f"{r['p95_after']:.2f}", f"{r['delta']:+.1f}%",
         f"{r['success_before']:.1f}%", f"{r['success_after']:.1f}%",
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
    """Inline SVG line chart of p95 latency over samples, before vs after
    overlaid (solid navy = before, dashed cyan = after) -- same "no external
    assets" inline-SVG style as scan/delta.py's _svg_bars. X is sample
    *index*, not wall-clock time: before/after runs are independent
    processes and this keeps both lines plotted even if one run collected a
    slightly different sample count than the other.
    """
    values = [s["p95_ms"] for s in samples_before] + [s["p95_ms"] for s in samples_after]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0

    def polyline(samples: list[dict]) -> str:
        n = len(samples)
        pts = []
        for i, s in enumerate(samples):
            x = pad + ((i / (n - 1)) if n > 1 else 0.5) * (width - 2 * pad)
            y = pad + (1 - (s["p95_ms"] - lo) / span) * (height - 2 * pad)
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


def write_html_report(rows: list[dict], tolerance: float, success_drop_pp: float, path: Path) -> None:
    """Render a self-contained HTML load-baseline report in the shared style
    (scan/report_style.py) — a before/after/delta table with an OK/regression
    verdict per metric, plus a p95-latency sparkline (before vs after
    overlaid) per metric. Same visual identity as the scan delta report."""
    regressions = sum(1 for r in rows if r["verdict"] == "REGRESSION")
    reg_class = "bad" if regressions else "good"
    trows = []
    for r in rows:
        ok = r["verdict"] == "OK"
        trend = f"<td class='trend'>{_svg_sparkline(r['samples_before'], r['samples_after'])}</td>"
        trows.append(
            f"<tr><td>{r['label']}<br><span class='rate'>{_fmt_rate(r)}, {r['tool']}</span></td>"
            f"<td class='num'>{_fmt_ms(r['p50_before'])}</td>"
            f"<td class='num'>{_fmt_ms(r['p50_after'])}</td>"
            f"<td class='num'>{r['p95_before']:.2f}</td>"
            f"<td class='num'>{r['p95_after']:.2f}</td>"
            f"<td class='num {'delta-good' if ok else 'delta-bad'}'>{r['delta']:+.1f}%</td>"
            f"<td class='num'>{r['success_before']:.1f}%</td>"
            f"<td class='num'>{r['success_after']:.1f}%</td>"
            f"<td><span class='badge {'ok' if ok else 'bad'}'>"
            f"{'OK' if ok else '⚠ REGRESSION'}</span></td>"
            + trend + "</tr>")
    extra_css = (".trend{min-width:140px}"
                 ".trend svg{display:block}"
                 ".rate{color:var(--muted);font-size:.78rem;font-weight:400}")
    body = (
        "<div class='stats'>"
        f"<div class='pill {reg_class}'><span class='n'>{regressions}</span>"
        f"<span class='l'>regression{'' if regressions == 1 else 's'}</span></div>"
        f"<div class='pill'><span class='n'>{tolerance:.0f}%</span>"
        "<span class='l'>p95 tolerance</span></div>"
        f"<div class='pill'><span class='n'>{success_drop_pp:.0f}pp</span>"
        "<span class='l'>success-drop tolerance</span></div>"
        "</div>"
        "<p class='legend'>Fixed-rate, sub-saturation load baseline &mdash; not a "
        "rigorous benchmark, and not peak throughput. Each metric holds a "
        "constant rate below its endpoint's ceiling: 1 warmup run (discarded) "
        "+ 2 timed runs, sampled at a fixed interval. A metric is flagged if "
        "its <b>median p95 latency</b> rose past tolerance, or its "
        "<b>success rate</b> dropped past tolerance &mdash; single-VM smoke, "
        "not a certified number.</p>"
        "<p class='legend'><span class='trend-sw before'></span>before"
        "<span class='trend-sw after'></span>after"
        "&mdash; p95 latency (ms) per sample window across both timed runs.</p>"
        "<section class='card'><h2>Before / after &mdash; p50/p95 latency &amp; trend</h2>"
        "<table><thead><tr><th>Metric</th><th class='num'>P50 before</th>"
        "<th class='num'>P50 after</th><th class='num'>P95 before</th>"
        "<th class='num'>P95 after</th><th class='num'>&Delta; (p95)</th>"
        "<th class='num'>Success before</th><th class='num'>Success after</th>"
        "<th>Verdict</th><th>Trend (p95)</th>"
        f"</tr></thead><tbody>{''.join(trows)}</tbody></table></section>")
    extra_css += (".trend-sw{display:inline-block;width:16px;height:2px;vertical-align:middle;"
                  "margin:0 .3rem 0 .8rem;background:#16324f}"
                  ".trend-sw.after{background:repeating-linear-gradient(90deg,#18c3e6 0 5px,transparent 5px 8px)}"
                  ".trend-sw:first-of-type{margin-left:0}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        page("Load baseline", "Fixed sub-saturation rate + latency, before / after patching",
             body, "scan/bench_compare.py", extra_css),
        encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare two bench.yml load-baseline reports.")
    parser.add_argument("--before", type=Path, default=Path("results/bench-before.json"))
    parser.add_argument("--after", type=Path, default=Path("results/bench-after.json"))
    parser.add_argument("--html", type=Path, default=Path("results/bench.html"),
                        help="self-contained HTML report (default: results/bench.html)")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE_PCT,
                        help=f"allowed p95 drift in %% before flagging a regression (default: {DEFAULT_TOLERANCE_PCT})")
    parser.add_argument("--success-drop-pp", type=float, default=DEFAULT_SUCCESS_DROP_PP,
                        help="allowed success-rate drop in percentage points before flagging a "
                             f"regression (default: {DEFAULT_SUCCESS_DROP_PP})")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        before = index_by_key(load_report(args.before))
        after = index_by_key(load_report(args.after))
        rows = build_rows(before, after, args.tolerance, args.success_drop_pp)
    except BenchError as exc:
        print(f"bench: {exc}", file=sys.stderr)
        return 1
    if not rows:
        print("bench: no matching host/metric pairs between before and after", file=sys.stderr)
        return 1
    print(f"Load baseline comparison (smoke-level, fixed-rate, median-p95-driven, "
          f"tolerance {args.tolerance:.0f}% / success drop {args.success_drop_pp:.0f}pp):\n")
    print_table(rows)
    write_html_report(rows, args.tolerance, args.success_drop_pp, args.html)
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
