"""Smoke tests: the service is alive and answers correctly (rules/testing.md).

Marked `stand`: needs a provisioned stand; skipped cleanly when unreachable.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.stand

requests = pytest.importorskip("requests", reason="pip install -r requirements-dev.txt")


def test_wordpress_home_returns_200(stand_url):
    """Home page returns 200 over the network."""
    resp = requests.get(stand_url, timeout=5)
    assert resp.status_code == 200


def test_wordpress_serves_html(stand_url):
    """Home page is served as HTML."""
    resp = requests.get(stand_url, timeout=5)
    assert "text/html" in resp.headers.get("content-type", "")
