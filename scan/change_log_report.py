#!/usr/bin/env python3
"""Render results/change-log.jsonl as a browsable HTML calendar.

Reads the append-only change log (`scan/change_log_append.py` writes it,
one JSON object per line -- seeded from `scan/examples/change-log-seed.jsonl`
on first run so the calendar has history from a fresh clone) and renders it
in the stand's shared report style (`report_style.py`): one grid per month
(newest first), one cell per day, one collapsible `<details>` per event
color-coded by action. A client-side search box filters events by
host/package/action/who against a JS array embedded in the page -- no
external JS, no server round-trip.

Runs on the standard library only. Invoked from the Makefile's `change-log`
target as `python3 scan/change_log_report.py`.
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
from collections import defaultdict
from html import escape
from pathlib import Path

from change_log_append import LOG_PATH, SEED_PATH, ensure_log
from report_style import page

# Human-readable calendar labels, keyed by the raw action string the Makefile
# targets record. Deliberately decoupled from the target/action names: a label
# should read as *what changed* ("kernel"), not the mechanism ("reboot"), and
# name the layer ("OS patch") once "kernel"/"WordPress" sit next to it. The
# action string (and the evt-<action> CSS class) stays the target name.
ACTION_LABELS = {
    "patch": "OS patch",
    "rollout": "rollout",
    "patch-wordpress": "WordPress",
    "patch-reboot": "kernel",
    "rollback": "rollback",
}

EXTRA_CSS = """
.cal-search{margin:0 0 1.2rem}
#cl-search{width:100%;max-width:420px;padding:.55rem .8rem;border:1px solid var(--border);
border-radius:8px;font-size:.9rem;background:var(--card);color:var(--ink)}
#cl-search:focus{outline:2px solid var(--cyan);outline-offset:1px}
.cal-month{margin-bottom:2.2rem}
.cal-month h2{color:var(--navy);font-size:1.05rem;margin:0 0 .7rem}
.cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}
.cal-wd{font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;
text-align:center;padding:.2rem 0}
.cal-day{border:1px solid var(--border);border-radius:8px;background:var(--card);
min-height:96px;padding:.4rem .4rem .5rem;display:flex;flex-direction:column;gap:.3rem;
transition:opacity .15s}
.cal-day.pad{background:transparent;border-color:transparent}
.cal-day.pad .cal-daynum{opacity:.35}
.cal-day.day-hidden{opacity:.18}
.cal-daynum{font-size:.72rem;font-weight:700;color:var(--muted)}
.evt{border-radius:6px;font-size:.7rem;border:1px solid var(--border);background:#fff;overflow:hidden}
.evt summary{list-style:none;cursor:pointer;padding:.2rem .4rem;display:flex;flex-wrap:wrap;
gap:.3rem;align-items:baseline}
.evt summary::-webkit-details-marker{display:none}
.evt .inner{padding:.3rem .4rem .4rem;border-top:1px solid var(--border)}
.evt-badge{font-weight:700;padding:.05rem .42rem;border-radius:999px;color:#fff;font-size:.62rem;
text-transform:uppercase;letter-spacing:.02em}
.evt-patch .evt-badge{background:var(--cyan)}
.evt-rollout .evt-badge{background:var(--bad)}
.evt-patch-wordpress .evt-badge{background:var(--HIGH)}
.evt-patch-reboot .evt-badge{background:var(--ok)}
.evt-rollback .evt-badge{background:#7c3aed}
.evt-env{font-weight:600;color:var(--navy)}
.evt-hosts{color:var(--muted)}
.evt-who{color:var(--muted);font-style:italic}
.evt-count{margin-left:auto;color:var(--muted)}
.evt-pkgs{margin:.2rem 0 .3rem;padding-left:1.1rem;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.evt-empty{margin:.2rem 0;color:var(--muted)}
.evt-note{margin:.2rem 0 0;color:var(--muted);font-size:.7rem}
.sw.evt-patch{background:var(--cyan)}
.sw.evt-rollout{background:var(--bad)}
.sw.evt-patch-wordpress{background:var(--HIGH)}
.sw.evt-patch-reboot{background:var(--ok)}
.legend-item{display:inline-flex;align-items:center;gap:.35rem;margin-right:1.1rem}
"""

# Toggles visibility by element id rather than re-rendering the calendar --
# the grid stays exactly what Python built, JS only hides/dims. EVENTS is
# injected as a JSON literal right above this script (see write_html_report).
FILTER_JS = """
(function(){
  var input = document.getElementById('cl-search');
  if(!input) return;
  function norm(s){ return (s || '').toLowerCase(); }
  function haystack(ev){
    return [ev.action, ev.env, ev.who, ev.hosts, ev.note, (ev.packages || []).join(' ')]
      .join(' ').toLowerCase();
  }
  function applyFilter(){
    var q = norm(input.value);
    var dayHasMatch = {};
    EVENTS.forEach(function(ev){
      var el = document.getElementById(ev.id);
      if(!el) return;
      var ok = !q || haystack(ev).indexOf(q) !== -1;
      el.style.display = ok ? '' : 'none';
      if(ok) dayHasMatch[ev.date] = true;
    });
    document.querySelectorAll('.cal-day[data-date]').forEach(function(cell){
      if(!cell.querySelector('.evt')) return;
      var d = cell.getAttribute('data-date');
      cell.classList.toggle('day-hidden', !!q && !dayHasMatch[d]);
    });
  }
  input.addEventListener('input', applyFilter);
})();
"""


class ChangeLogReportError(Exception):
    """A problem the user can act on; printed as one line, no traceback."""


def load_records(path: Path) -> list[dict]:
    """Load every record from the JSON-Lines change log, in file order."""
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ChangeLogReportError(f"{path}:{lineno}: invalid JSON line: {exc}")
    return records


def group_by_month(records: list[dict]) -> dict[str, dict[str, list[dict]]]:
    """{"YYYY-MM": {"YYYY-MM-DD": [record, ...]}} -- records without a
    parseable date are skipped rather than crashing the whole report."""
    by_month: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for rec in records:
        date = rec.get("date", "")
        if len(date) != 10:
            continue
        by_month[date[:7]][date].append(rec)
    return by_month


def render_event(rec: dict) -> str:
    """One collapsible event: collapsed shows action/env/hosts/who/count,
    expanded adds the package=version list (or an honest empty-state)."""
    action = rec.get("action", "?")
    label = ACTION_LABELS.get(action, action)
    env = escape(str(rec.get("env", "?")))
    hosts = escape(", ".join(rec.get("hosts", [])))
    who = escape(str(rec.get("who", "?")))
    count = rec.get("package_count", len(rec.get("packages", [])))
    packages = rec.get("packages", [])
    if packages:
        pkg_html = "<ul class='evt-pkgs'>" + "".join(
            f"<li>{escape(str(p.get('name', '?')))}={escape(str(p.get('version', '?')))}</li>"
            for p in packages
        ) + "</ul>"
    else:
        pkg_html = "<p class='evt-empty'>no packages recorded</p>"
    note = escape(str(rec.get("note", "")))
    action_css = "evt-" + action
    return (
        f"<details id='{rec['_id']}' class='evt {action_css}'>"
        f"<summary><span class='evt-badge'>{escape(label)}</span>"
        f"<span class='evt-env'>{env}</span>"
        f"<span class='evt-hosts'>{hosts}</span>"
        f"<span class='evt-who'>{who}</span>"
        f"<span class='evt-count'>{count} pkg</span></summary>"
        f"<div class='inner'>{pkg_html}<p class='evt-note'>{note}</p></div>"
        "</details>"
    )


def render_month(ym: str, days: dict[str, list[dict]]) -> str:
    """One calendar grid for a "YYYY-MM" month, Monday-first, padded with
    the adjacent months' leading/trailing days (dimmed, no events)."""
    year, month = int(ym[:4]), int(ym[5:7])
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    header = "".join(
        f"<div class='cal-wd'>{d}</div>" for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    )
    cells = []
    for week in weeks:
        for day in week:
            iso = day.isoformat()
            in_month = day.month == month
            evts = "".join(render_event(r) for r in days.get(iso, []))
            cls = "cal-day" if in_month else "cal-day pad"
            cells.append(
                f"<div class='{cls}' data-date='{iso}'>"
                f"<div class='cal-daynum'>{day.day}</div>{evts}</div>"
            )
    return (
        f"<div class='cal-month'><h2>{calendar.month_name[month]} {year}</h2>"
        f"<div class='cal-grid'>{header}{''.join(cells)}</div></div>"
    )


def build_events_js(records: list[dict]) -> str:
    """JSON array embedded in the page for the client-side search filter --
    DOM ids match the `<details id=...>` the calendar rendered, so the
    filter only toggles visibility, it never re-renders the grid."""
    events = [
        {
            "id": rec["_id"],
            "date": rec.get("date", ""),
            "action": rec.get("action", ""),
            "env": rec.get("env", ""),
            "who": rec.get("who", ""),
            "hosts": ", ".join(rec.get("hosts", [])),
            "packages": [
                f"{p.get('name', '?')}={p.get('version', '?')}" for p in rec.get("packages", [])
            ],
            "note": rec.get("note", ""),
        }
        for rec in records
    ]
    # "</script" inside a string would otherwise close the embedding <script>
    # tag early -- escape the slash so the JSON stays inert markup.
    return json.dumps(events, ensure_ascii=False).replace("</", "<\\/")


def write_html_report(records: list[dict], path: Path) -> None:
    """Render the self-contained change-log calendar to `path`."""
    sortable = sorted(records, key=lambda r: r.get("timestamp", ""))
    for i, rec in enumerate(sortable):
        rec["_id"] = f"evt-{i}"
    by_month = group_by_month(sortable)
    months = sorted(by_month, reverse=True)
    total_packages = sum(r.get("package_count", 0) for r in sortable)
    legend = "".join(
        f"<span class='legend-item'><span class='sw evt-{action}'></span>{label}</span>"
        for action, label in ACTION_LABELS.items()
    )
    month_html = "".join(render_month(ym, by_month[ym]) for ym in months)
    if not month_html:
        month_html = "<p class='legend'>No change-log entries yet -- run a patch/rollout target.</p>"
    body = (
        "<div class='stats'>"
        f"<div class='pill'><span class='n'>{len(sortable)}</span><span class='l'>events</span></div>"
        f"<div class='pill'><span class='n'>{total_packages}</span><span class='l'>packages patched</span></div>"
        f"<div class='pill'><span class='n'>{len(months)}</span><span class='l'>months</span></div>"
        "</div>"
        "<div class='cal-search'><input id='cl-search' type='search' "
        "placeholder='filter by host, package, action, who...' autocomplete='off'></div>"
        f"<p class='legend'>{legend}</p>"
        f"{month_html}"
        f"<script>const EVENTS = {build_events_js(sortable)};\n{FILTER_JS}</script>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        page("Change log — CMDB calendar",
             "Append-only record of what was patched, where, and by whom",
             body, "scan/change_log_report.py", EXTRA_CSS),
        encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render results/change-log.jsonl as an HTML CMDB calendar."
    )
    parser.add_argument("--jsonl", type=Path, default=LOG_PATH)
    parser.add_argument("--html", type=Path, default=LOG_PATH.parent / "change-log.html")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ensure_log(args.jsonl, SEED_PATH)
        records = load_records(args.jsonl)
    except ChangeLogReportError as exc:
        print(f"change_log_report: {exc}", file=sys.stderr)
        return 1
    write_html_report(records, args.html)
    print(f"change_log_report: wrote {args.html} ({len(records)} events)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
