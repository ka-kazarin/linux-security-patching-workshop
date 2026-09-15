"""Shared pytest fixtures and marker wiring.

Two test sizes (rules/testing.md):
- unit: nothing outside the process; the default run, green on any dev machine.
- stand: needs a provisioned stand; skipped with a clear message when the stand
  URL is not reachable, never failed.
"""

from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

import pytest

STAND_URL = os.environ.get("STAND_URL", "http://192.168.56.10")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "unit: no external dependencies, always runs")
    config.addinivalue_line("markers", "stand: needs a provisioned stand VM")


def _stand_reachable(url: str, timeout: float = 1.0) -> bool:
    """True if the stand host accepts a TCP connection on its web port."""
    parsed = urlparse(url)
    host, port = parsed.hostname, parsed.port or 80
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def stand_url() -> str:
    """Base URL of the stand; skips the test cleanly when unreachable."""
    if not _stand_reachable(STAND_URL):
        pytest.skip(f"stand unreachable at {STAND_URL} "
                    "(bring up the stand or set STAND_URL) — skipped, not failed")
    return STAND_URL


# --- Reporting -------------------------------------------------------------
# pytest's default output (dots, then long tracebacks on failure) is hard to
# read at a glance. Instead we print one line per test --
#   <name> — <description> ..... OK/FAIL/SKIP   [cause]
# -- and render results/verify.html in the SAME visual style as the stand's
# other reports (scan/delta/bench, via scan/report_style.py), not pytest-html.
import sys as _sys
from pathlib import Path as _Path

_SCAN_DIR = str(_Path(__file__).resolve().parent.parent / "scan")
if _SCAN_DIR not in _sys.path:
    _sys.path.insert(0, _SCAN_DIR)

_DESC: dict[str, str] = {}       # nodeid -> one-line description (from docstring)
_RESULTS: dict[str, dict] = {}   # nodeid -> {name, desc, outcome, cause}


def _short_name(nodeid: str) -> str:
    """test_health.py::TestWebHost::test_nginx_running[web-stage] -> the tail."""
    return nodeid.split("::")[-1]


def pytest_itemcollected(item) -> None:
    doc = (getattr(item.obj, "__doc__", None) or "").strip()
    _DESC[item.nodeid] = doc.splitlines()[0].rstrip(".") if doc else ""


def pytest_collection_modifyitems(items) -> None:
    """Run (and therefore report) health checks before functional ones, and
    SSH reachability first of all -- you want "is the host even up?" before
    "does the service answer?", not the other way round."""
    def rank(item) -> int:
        n = item.nodeid
        if "test_ssh_reachable" in n:
            return 0
        if "test_health" in n:
            return 1
        if "test_functional" in n:
            return 2
        return 3
    items.sort(key=rank)


def pytest_runtest_logreport(report) -> None:
    """Record the decisive phase of each test: the call outcome, or a
    skip/error that happened during setup (skipped tests never reach 'call')."""
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        cause = ""
        if report.failed:
            crash = getattr(report.longrepr, "reprcrash", None)
            cause = crash.message.splitlines()[0] if crash else str(report.longrepr).splitlines()[-1]
        elif report.skipped:
            lr = report.longrepr
            if isinstance(lr, tuple) and len(lr) == 3:
                cause = lr[2].replace("Skipped: ", "")
        _RESULTS[report.nodeid] = {
            "name": _short_name(report.nodeid),
            "desc": _DESC.get(report.nodeid, ""),
            "outcome": report.outcome,
            "cause": cause,
        }


def pytest_terminal_summary(terminalreporter) -> None:
    if not _RESULTS:
        return
    tw = terminalreporter
    tw.write_sep("=", "stand health", bold=True)
    label = {"passed": "OK", "failed": "FAIL", "skipped": "SKIP"}
    markup = {"passed": {"green": True}, "failed": {"red": True}, "skipped": {"yellow": True}}
    for nodeid in _RESULTS:            # execution order (health first, see modifyitems)
        r = _RESULTS[nodeid]
        left = r["name"] + (f" — {r['desc']}" if r["desc"] else "")
        tw.write(left + " " + "." * max(3, 62 - len(left)) + " ")
        tw.write(label[r["outcome"]], **markup[r["outcome"]])
        if r["cause"]:
            tw.write(f"  [{r['cause']}]")
        tw.line("")
    import os
    if os.environ.get("STAND_ENV"):   # only the `make verify` flow owns verify.html
        try:
            _write_verify_html()
            tw.line(f"health report: {_Path('results/verify.html').resolve()}")
        except Exception as exc:       # reporting must never fail the run
            tw.line(f"verify.html not written: {exc}")


def _write_verify_html() -> None:
    import html
    import os
    from datetime import datetime, timezone
    from report_style import page   # scan/ is on sys.path (see top of file)

    counts = {"passed": 0, "failed": 0, "skipped": 0}
    badge = {"passed": ("ok", "OK"), "failed": ("bad", "FAIL"), "skipped": ("", "SKIP")}
    rows = []
    for nodeid in _RESULTS:            # execution order (health first, see modifyitems)
        r = _RESULTS[nodeid]
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
        bcls, btxt = badge.get(r["outcome"], ("", r["outcome"]))
        rows.append(
            f"<tr><td>{html.escape(r['name'])}</td>"
            f"<td>{html.escape(r['desc'])}</td>"
            f"<td><span class='badge {bcls}'>{btxt}</span></td>"
            f"<td>{html.escape(r['cause'])}</td></tr>"
        )
    env = os.environ.get("STAND_ENV", "?")
    body = (
        "<div class='stats'>"
        f"<div class='pill good'><span class='n'>{counts['passed']}</span><span class='l'>passed</span></div>"
        f"<div class='pill bad'><span class='n'>{counts['failed']}</span><span class='l'>failed</span></div>"
        f"<div class='pill'><span class='n'>{counts['skipped']}</span><span class='l'>skipped</span></div>"
        "</div>"
        "<p class='legend'>Health smoke over SSH (testinfra) + external HTTP. "
        "Green before and after a patch means the patch broke nothing; a red row "
        "names what is down (VM, service, or DB).</p>"
        "<section class='card'><h2>Checks</h2>"
        "<table><thead><tr><th>Test</th><th>What it checks</th><th>Result</th>"
        f"<th>Cause (on failure)</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>"
    )
    out = _Path("results/verify.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        page(f"Verify — {env}",
             f"Stand health smoke, {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
             body, "tests (pytest + testinfra)"),
        encoding="utf-8")
