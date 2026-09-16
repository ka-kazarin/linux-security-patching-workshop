#!/usr/bin/env python3
"""Shared visual identity for the stand's HTML reports (delta, bench, scan).

One place for the palette + CSS + page frame so `scan/delta.py` and
`scan/bench_compare.py` render identically. The Trivy report
(`scan/trivy-html.tpl`) is a Go template and can't import Python, so it keeps
a pasted copy of the same CSS — keep the two in sync by eye.

Look: dark navy header with an electric-cyan accent, white cards on a light
ground, pill badges, generous spacing. Self-contained
(system fonts, inline CSS/SVG, no external assets) so a report renders offline.

Standard library only.
"""

from __future__ import annotations

# Severity palette, shared by the delta chart bars and the report CSS.
# Semantic (red = critical … green = low), tuned for the light card ground.
PALETTE = {"CRITICAL": "#e5484d", "HIGH": "#f2820c", "MEDIUM": "#e0b400",
           "LOW": "#30a46c", "UNKNOWN": "#8b96a5"}

# Base CSS shared by every report. Kept in sync with scan/trivy-html.tpl by eye.
BASE_CSS = """
:root{--navy:#0e2439;--navy-2:#16324f;--cyan:#18c3e6;--ink:#0f1b28;
--muted:#5a6b7b;--bg:#eef2f6;--card:#fff;--border:#e0e7ee;
--ok:#30a46c;--warn:#e0b400;--bad:#e5484d;
--CRITICAL:#e5484d;--HIGH:#f2820c;--MEDIUM:#e0b400;--LOW:#30a46c;--UNKNOWN:#8b96a5}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.5;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:#0f6f99}
.wrap{max-width:1100px;margin:0 auto;padding:0 1.5rem 3rem}
header{background:linear-gradient(135deg,var(--navy),var(--navy-2));color:#fff;
padding:1.6rem 0 1.7rem;border-bottom:3px solid var(--cyan);margin-bottom:1.75rem}
header .wrap{padding-bottom:0}
h1{margin:0;font-size:1.5rem;letter-spacing:-.01em}
.sub{margin:.3rem 0 0;color:#9fc7dd;font-size:.9rem}
.stats{display:flex;flex-wrap:wrap;gap:.75rem;margin:0 0 1.5rem}
.pill{display:flex;align-items:baseline;gap:.5rem;background:var(--card);
border:1px solid var(--border);border-left:4px solid var(--muted);border-radius:8px;
padding:.6rem .9rem;box-shadow:0 1px 2px rgba(16,35,59,.05)}
.pill .n{font-size:1.35rem;font-weight:700;line-height:1}
.pill .l{font-size:.8rem;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}
.pill.good{border-left-color:var(--ok)} .pill.good .n{color:var(--ok)}
.pill.bad{border-left-color:var(--bad)} .pill.bad .n{color:var(--bad)}
.pill.warn{border-left-color:var(--warn)} .pill.warn .n{color:var(--warn)}
.legend{font-size:.82rem;color:var(--muted);margin:0 0 1.5rem;display:flex;
align-items:center;gap:.4rem;flex-wrap:wrap}
.sw{display:inline-block;width:13px;height:13px;border-radius:3px;
vertical-align:middle;background:var(--muted)}
.sw.after{opacity:.45}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;
padding:1.1rem 1.2rem 1.3rem;box-shadow:0 1px 3px rgba(16,35,59,.06)}
.card h2{margin:0 0 .6rem;font-size:.95rem;color:var(--navy);
display:flex;align-items:center;gap:.45rem}
.card h2::before{content:"";width:7px;height:7px;border-radius:50%;
background:var(--cyan);display:inline-block}
.overall{margin-bottom:1.25rem}
table{border-collapse:collapse;width:100%;font-size:.86rem}
th,td{padding:.5rem .6rem;text-align:left;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:600;text-transform:uppercase;
font-size:.72rem;letter-spacing:.03em}
tbody tr:last-child td{border-bottom:none}
.num{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:.12rem .55rem;border-radius:999px;
font-size:.74rem;font-weight:600}
.badge.ok{background:rgba(48,164,108,.16);color:#1c7a4d}
.badge.bad{background:rgba(229,72,77,.16);color:#c0323a}
.delta-good{color:var(--ok);font-weight:600} .delta-bad{color:var(--bad);font-weight:600}
.sev{font-weight:600}
.sev.CRITICAL{color:var(--CRITICAL)} .sev.HIGH{color:var(--HIGH)}
.sev.MEDIUM{color:var(--MEDIUM)} .sev.LOW{color:var(--LOW)} .sev.UNKNOWN{color:var(--UNKNOWN)}
details{background:var(--card);border:1px solid var(--border);border-radius:10px;
margin-bottom:.6rem;overflow:hidden}
details summary{cursor:pointer;font-weight:600;padding:.7rem .9rem;color:var(--navy)}
details[open] summary{border-bottom:1px solid var(--border)}
details .inner{padding:.4rem .9rem .7rem}
footer{color:var(--muted);font-size:.78rem;margin-top:1.75rem;text-align:center}
footer code{background:#dde5ec;padding:.1rem .35rem;border-radius:4px}
"""


def page(title: str, subtitle: str, body: str, generator: str,
         extra_css: str = "") -> str:
    """Wrap body HTML in the shared document frame (navy header + footer)."""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title><style>{BASE_CSS}{extra_css}</style></head><body>"
        f"<header><div class='wrap'><h1>{title}</h1>"
        f"<p class='sub'>{subtitle}</p></div></header>"
        f"<div class='wrap'>{body}"
        f"<footer>Generated by <code>{generator}</code> &middot; Vulnerability Management Stand</footer>"
        "</div></body></html>")
