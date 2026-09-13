"""Unit tests for scan/delta.py — runs on any dev machine, no stand needed."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scan"))

import delta  # noqa: E402

pytestmark = pytest.mark.unit

EXAMPLES = ROOT / "scan" / "examples"


def _report(results):
    return {"SchemaVersion": 2, "Results": results}


def _vuln(cve, sev, pkg="pkg"):
    return {"VulnerabilityID": cve, "PkgName": pkg, "Severity": sev,
            "PrimaryURL": f"https://x/{cve}", "Title": cve}


def test_extract_findings_flattens_results():
    report = _report([{"Target": "t", "Class": "os-pkgs",
                       "Vulnerabilities": [_vuln("CVE-1", "HIGH")]}])
    findings = delta.extract_findings(report)
    assert ("CVE-1", "pkg") in findings
    assert findings[("CVE-1", "pkg")]["layer"] == "OS/middleware"


def test_extract_findings_rejects_non_trivy_report():
    with pytest.raises(delta.DeltaError, match="Results"):
        delta.extract_findings({"not": "trivy"})


def test_classify_tags_fixed_new_remaining():
    before = delta.extract_findings(_report([{"Target": "t", "Class": "os-pkgs",
        "Vulnerabilities": [_vuln("GONE", "LOW"), _vuln("STAYS", "HIGH")]}]))
    after = delta.extract_findings(_report([{"Target": "t", "Class": "os-pkgs",
        "Vulnerabilities": [_vuln("STAYS", "HIGH"), _vuln("NEW", "MEDIUM")]}]))
    status = {r["cve"]: r["status"] for r in delta.classify(before, after)}
    assert status == {"GONE": "fixed", "STAYS": "remaining", "NEW": "new"}


def test_classify_orders_most_severe_first():
    before = delta.extract_findings(_report([{"Target": "t", "Class": "os-pkgs",
        "Vulnerabilities": [_vuln("LOWSEV", "LOW"), _vuln("CRIT", "CRITICAL")]}]))
    rows = delta.classify(before, {})
    assert rows[0]["cve"] == "CRIT"


def test_write_registry_csv_has_registry_header(tmp_path):
    rows = delta.classify(
        delta.extract_findings(_report([{"Target": "web", "Class": "os-pkgs",
            "Vulnerabilities": [_vuln("CVE-9", "CRITICAL")]}])), {})
    out = tmp_path / "delta.csv"
    delta.write_registry_csv(rows, out)
    with out.open(encoding="utf-8") as fh:
        parsed = list(csv.reader(fh))
    assert parsed[0] == delta.REGISTRY_HEADER
    assert parsed[1][0] == "CVE-9"
    assert parsed[1][8] == "closed"  # a finding gone from "after" is closed


def test_severity_counts_buckets_unknown():
    findings = delta.extract_findings(_report([{"Target": "t", "Class": "x",
        "Vulnerabilities": [_vuln("A", "WEIRD"), _vuln("B", "HIGH", "p2")]}]))
    counts = delta.severity_counts(findings)
    assert counts["UNKNOWN"] == 1 and counts["HIGH"] == 1


def test_load_report_missing_file_raises_deltaerror():
    with pytest.raises(delta.DeltaError, match="not found"):
        delta.load_report(Path("/no/such/report.json"))


def test_end_to_end_on_shipped_examples(tmp_path):
    """The shipped example reports must always parse and produce a delta."""
    rc = delta.main(["--before", str(EXAMPLES / "scan-before.json"),
                     "--after", str(EXAMPLES / "scan-after.json"),
                     "--csv", str(tmp_path / "d.csv"),
                     "--html", str(tmp_path / "d.html")])
    assert rc == 0
    assert (tmp_path / "d.csv").exists()
    assert "<svg" in (tmp_path / "d.html").read_text(encoding="utf-8")
