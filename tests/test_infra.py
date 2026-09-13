"""Infra assertions via testinfra: package versions and service state.

Marked `stand`: needs SSH access to the stand (testinfra). Skipped cleanly when
testinfra is not installed or no host is configured (rules/testing.md).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.stand

testinfra = pytest.importorskip(
    "testinfra", reason="pip install -r requirements-dev.txt")


@pytest.fixture(scope="module")
def host():
    """testinfra host from TESTINFRA_HOST, else skip (no stand to talk to)."""
    import os
    spec = os.environ.get("TESTINFRA_HOST")
    if not spec:
        pytest.skip("TESTINFRA_HOST not set — infra assertions skipped, not failed")
    return testinfra.get_host(spec)


def test_nginx_service_is_running(host):
    assert host.service("nginx").is_running


def test_wordpress_is_patched(host):
    """After the app patch, WordPress core must be 7.0.2+ (wp2shell fixed)."""
    version = host.file("/var/www/html/wp-includes/version.php")
    assert version.exists
