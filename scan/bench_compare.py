#!/usr/bin/env python3
"""Compare two load-baseline JSON files produced by ansible/bench.yml.

Reads a "before" and an "after" bench run (vegeta against nginx/PHP on the
web host, sysbench oltp_read_only against MySQL on the db host — one entry
per host/metric, schema in ansible/bench.yml: a warmup run discarded, then 2
timed runs at a FIXED sub-saturation rate, sampled at a fixed interval into a
p50/p95-latency + success-rate time series). Reports the **median p95
latency** (plus success rate) per metric.

Verdict is a hybrid, because "did it change vs the last run?" is the wrong
question for some metrics:

  * Every metric has an absolute p95 **SLA** (a generous ceiling a healthy
    stack clears easily). Breaching it = a real, gross regression. This is
    the primary, host-noise-proof gate — for a sub-millisecond endpoint like
    static nginx, where a 0.2 ms wobble is 20% but means nothing, it's the
    ONLY gate.
  * For metrics whose latency is large enough that a percentage is meaningful
    (php, mysql — tens of ms), a relative before/after check ALSO runs, to
    catch a real slowdown that's still under the SLA (e.g. 80 ms -> 160 ms).
  * A drop in success rate flags on its own, for any metric.

SLAs are absolute and therefore host-dependent, so they're deliberately
generous (this is a single-VM smoke baseline, not a performance lab) — a
breach means something genuinely broke, not that the laptop was busy.

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
DEFAULT_SUCCESS_DROP_PP = 1.0

# Absolute p95 SLA per metric, in ms: a generous ceiling a healthy stack
# clears with room to spare. Primary, noise-proof gate (see module docstring).
SLA_P95_MS = {
    "nginx-static": 5.0,     # observed ~1 ms; sub-ms, % is pure noise -> SLA only
    "php": 250.0,            # observed ~80 ms (WordPress render through PHP+MySQL)
    "mysql": 20.0,           # observed ~7 ms (sysbench oltp_read_only)
}
# Metrics whose absolute latency is large enough for a before/after percentage
# to be meaningful — these ALSO get the relative check. Sub-ms metrics do not.
RELATIVE_METRICS = {"php", "mysql"}


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
    """One row per host/metric present in both runs. Verdict is hybrid:
    SLA breach (any metric) OR relative p95 rise past tolerance (metrics in
    RELATIVE_METRICS only) OR success-rate drop. See the module docstring."""
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
        success_b = b["median_success"] * 100
        success_a = a["median_success"] * 100

        sla = SLA_P95_MS.get(metric)
        relative_eligible = metric in RELATIVE_METRICS
        sla_breach = sla is not None and p95_a > sla
        relative_regressed = relative_eligible and delta > tolerance
        success_regressed = (success_b - success_a) > success_drop_pp

        reasons = []
        if sla_breach:
            reasons.append(f"p95 {p95_a:.1f}ms over SLA {sla:.0f}ms")
        if relative_regressed:
            reasons.append(f"p95 +{delta:.0f}% vs before")
        if success_regressed:
            reasons.append(f"success {success_a:.1f}% (was {success_b:.1f}%)")

        rows.append({
            "label": f"{host}/{metric}", "host": host, "metric": metric,
            "tool": b.get("tool"), "rate": b.get("rate"),
            "p50_before": b.get("median_p50"), "p50_after": a.get("median_p50"),
            "p95_before": p95_b, "p95_after": p95_a, "delta": delta,
            "success_before": success_b, "success_after": success_a,
            "sla": sla, "relative_eligible": relative_eligible,
            "sla_breach": sla_breach,
            "verdict": "FAIL" if reasons else "OK",
            "reason": "; ".join(reasons),
            "samples_before": b["samples"], "samples_after": a["samples"],
        })
    return rows


def _fmt_rate(row: dict) -> str:
    unit = "tps" if row["tool"] == "sysbench" else "req/s"
    rate = row["rate"]
    return f"{rate} {unit}" if rate is not None else "?"


def _fmt_ms(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "-"


def _fmt_sla(row: dict) -> str:
    return f"< {row['sla']:.0f}" if row["sla"] is not None else "-"


def _fmt_delta(row: dict) -> str:
    """Delta text; sub-ms metrics that don't get a relative check are marked
    'info' so a big-looking % there is clearly not driving the verdict."""
    d = f"{row['delta']:+.1f}%"
    return d if row["relative_eligible"] else f"{d} (info)"


def print_table(rows: list[dict]) -> None:
    """Aligned metric | rate | p95 before/after | SLA | Δ | success | verdict table."""
    header = ("metric", "rate", "p95 before", "p95 after", "SLA p95",
               "Δ p95", "success", "verdict")
    formatted = [
        (r["label"], _fmt_rate(r), f"{r['p95_before']:.2f}", f"{r['p95_after']:.2f}",
         _fmt_sla(r), _fmt_delta(r), f"{r['success_after']:.1f}%",
         "OK" if r["verdict"] == "OK" else f"⚠ FAIL — {r['reason']}")
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
    overlaid (solid navy = before, dashed cyan = after) — same "no external
    assets" inline-SVG style as scan/delta.py. X is sample *index*, not
    wall-clock: before/after are independent runs, this overlays both even
    with slightly different sample counts."""
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
    """Self-contained HTML report in the shared style (scan/report_style.py):
    per metric — p95 before/after (after coloured by its SLA), the SLA, the
    before/after delta (muted 'info' for sub-ms metrics that the delta
    doesn't gate), success, an OK/FAIL verdict with the reason, and a
    p95-latency sparkline."""
    failures = sum(1 for r in rows if r["verdict"] == "FAIL")
    reg_class = "bad" if failures else "good"
    trows = []
    for r in rows:
        ok = r["verdict"] == "OK"
        p95a_cls = "delta-bad" if r["sla_breach"] else "delta-good"
        delta_cls = ("delta-bad" if (r["relative_eligible"] and not ok and "vs before" in r["reason"])
                     else "" if r["relative_eligible"] else "num-info")
        verdict_cell = (f"<span class='badge ok'>OK</span>" if ok
                        else f"<span class='badge bad'>⚠ FAIL</span>"
                             f"<div class='why'>{r['reason']}</div>")
        trows.append(
            f"<tr><td>{r['label']}<br><span class='rate'>{_fmt_rate(r)}, {r['tool']}</span></td>"
            f"<td class='num'>{r['p95_before']:.2f}</td>"
            f"<td class='num {p95a_cls}'>{r['p95_after']:.2f}</td>"
            f"<td class='num'>{_fmt_sla(r)}</td>"
            f"<td class='num {delta_cls}'>{_fmt_delta(r)}</td>"
            f"<td class='num'>{r['success_after']:.1f}%</td>"
            f"<td>{verdict_cell}</td>"
            f"<td class='trend'>{_svg_sparkline(r['samples_before'], r['samples_after'])}</td></tr>")
    extra_css = (".trend{min-width:140px}.trend svg{display:block}"
                 ".rate{color:var(--muted);font-size:.78rem;font-weight:400}"
                 ".num-info{color:var(--muted)}"
                 ".why{color:var(--bad);font-size:.72rem;margin-top:.2rem}"
                 ".trend-sw{display:inline-block;width:16px;height:2px;vertical-align:middle;"
                 "margin:0 .3rem 0 .8rem;background:#16324f}"
                 ".trend-sw.after{background:repeating-linear-gradient(90deg,#18c3e6 0 5px,transparent 5px 8px)}"
                 ".trend-sw:first-of-type{margin-left:0}")
    body = (
        "<div class='stats'>"
        f"<div class='pill {reg_class}'><span class='n'>{failures}</span>"
        f"<span class='l'>failure{'' if failures == 1 else 's'}</span></div>"
        f"<div class='pill'><span class='n'>{len(rows)}</span><span class='l'>metrics</span></div>"
        "</div>"
        "<p class='legend'>Fixed-rate, sub-saturation load baseline &mdash; not peak "
        "throughput, not a rigorous benchmark. Each metric holds a constant rate below "
        "its endpoint's ceiling (1 warmup discarded + 2 timed runs). <b>Verdict = p95 "
        "within its absolute SLA</b> (a generous, host-agnostic ceiling); metrics with "
        "meaningful (tens-of-ms) latency &mdash; php, mysql &mdash; also fail on a "
        f"before/after p95 rise &gt; {tolerance:.0f}%, and any metric fails on a success-rate "
        f"drop &gt; {success_drop_pp:.0f}pp. Sub-millisecond metrics (nginx static) are SLA-only "
        "&mdash; their before/after % is noise, shown as <span class='num-info'>info</span>.</p>"
        "<p class='legend'><span class='trend-sw'></span>before"
        "<span class='trend-sw after'></span>after"
        "&mdash; p95 latency (ms) per sample window across both timed runs.</p>"
        "<section class='card'><h2>Before / after &mdash; p95 latency vs SLA</h2>"
        "<table><thead><tr><th>Metric</th><th class='num'>P95 before</th>"
        "<th class='num'>P95 after</th><th class='num'>SLA p95 (ms)</th>"
        "<th class='num'>&Delta; p95</th><th class='num'>Success</th>"
        "<th>Verdict</th><th>Trend (p95)</th>"
        f"</tr></thead><tbody>{''.join(trows)}</tbody></table></section>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        page("Load baseline", "Fixed sub-saturation rate + p95 latency vs SLA, before / after",
             body, "scan/bench_compare.py", extra_css),
        encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare two bench.yml load-baseline reports.")
    parser.add_argument("--before", type=Path, default=Path("results/bench-before.json"))
    parser.add_argument("--after", type=Path, default=Path("results/bench-after.json"))
    parser.add_argument("--html", type=Path, default=Path("results/bench.html"),
                        help="self-contained HTML report (default: results/bench.html)")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE_PCT,
                        help=f"relative p95 rise %% flagged for large-latency metrics (default: {DEFAULT_TOLERANCE_PCT})")
    parser.add_argument("--success-drop-pp", type=float, default=DEFAULT_SUCCESS_DROP_PP,
                        help=f"success-rate drop in pp flagged for any metric (default: {DEFAULT_SUCCESS_DROP_PP})")
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
    print("Load baseline (fixed-rate, p95 vs SLA; relative check for php/mysql):\n")
    print_table(rows)
    write_html_report(rows, args.tolerance, args.success_drop_pp, args.html)
    failures = sum(1 for r in rows if r["verdict"] == "FAIL")
    print()
    if failures:
        print(f"bench: {failures} metric(s) FAILED -- see above")
    else:
        print("bench: all metrics within SLA, no significant regression")
    print(f"  HTML: {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
