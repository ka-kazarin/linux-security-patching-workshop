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
