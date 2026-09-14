"""Health smoke: distinguishes "VM down" from "service down" from "stand not
brought up" (owner feedback -- a plain HTTP-only verify couldn't tell these
apart, and never checked the DB host at all). Marker `stand`.

Backend: pytest-testinfra's `ansible` connection -- host list, IPs and SSH
keys all come from ansible/inventory.yml (the same source Ansible playbooks
use), never a second hardcoded address. STAND_ENV picks the group (stage or
prod, default stage); role (web/db) comes from the web/db group membership
already in inventory.yml.

Skip-vs-fail semantics (the actual point of this file):
  - none of the ENV group's hosts answer SSH -> the stand simply isn't up
    -> clean skip (exit 0), same as every other `stand`-marked test.
  - at least one host answers, another doesn't -> that VM is down
    -> FAIL on the unreachable host (test_ssh_reachable), not skip.
  - a reachable host with a dead service -> FAIL on that specific service.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.stand

testinfra = pytest.importorskip(
    "testinfra", reason="pip install -r requirements-dev.txt (pytest-testinfra)"
)
from testinfra.utils.ansible_runner import AnsibleRunner  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = str(ROOT / "ansible" / "inventory.yml")
STAND_ENV = os.environ.get("STAND_ENV", "stage")

if STAND_ENV not in ("stage", "prod"):
    pytest.exit(f"STAND_ENV must be stage or prod (got {STAND_ENV!r})", returncode=2)

_runner = AnsibleRunner(INVENTORY)
ENV_HOSTS = _runner.get_hosts(STAND_ENV)
WEB_HOSTS = [h for h in ENV_HOSTS if h in _runner.get_hosts("web")]
DB_HOSTS = [h for h in ENV_HOSTS if h in _runner.get_hosts("db")]


def _probe(host: str) -> tuple[bool, object]:
    """One SSH round-trip per host: (True, live testinfra Host) on success,
    (False, short reason) when the connection itself failed.

    ssh exiting 255 (refused, timed out, VM gone) makes the backend raise
    RuntimeError -- that is never a normal remote-command failure, so it is
    a trustworthy "this VM is down" signal, not a flaky test.
    """
    ti_host = _runner.get_host(host)
    try:
        ti_host.run("true")
    except RuntimeError as exc:
        result = exc.args[0] if exc.args else None
        stderr = getattr(result, "stderr", "").strip()
        reason = stderr.splitlines()[-1] if stderr else str(exc)
        return False, reason
    return True, ti_host


@pytest.fixture(scope="session")
def reachability() -> dict[str, tuple[bool, object]]:
    return {host: _probe(host) for host in ENV_HOSTS}


@pytest.fixture(scope="session", autouse=True)
def _stand_must_be_up(reachability: dict[str, tuple[bool, object]]) -> None:
    """Owner's core requirement: zero reachable hosts means the stand was
    never brought up -- skip cleanly instead of failing on every check."""
    if not any(ok for ok, _ in reachability.values()):
        pytest.skip(
            f"no host of group '{STAND_ENV}' ({', '.join(ENV_HOSTS)}) answers "
            "SSH -- stand not brought up (`make up-lite`/`make up`) -- "
            "skipped, not failed"
        )


@pytest.mark.parametrize("host", ENV_HOSTS)
def test_ssh_reachable(host: str, reachability: dict[str, tuple[bool, object]]) -> None:
    """Every host of the ENV group must accept SSH -- a VM that's down
    (halted, never rebooted after patch-reboot, ...) fails here, loudly,
    never skips, while a live sibling host's checks still run."""
    ok, info = reachability[host]
    assert ok, f"{host} unreachable over SSH ({info})"


@pytest.fixture
def web_host(request: pytest.FixtureRequest, reachability: dict[str, tuple[bool, object]]):
    host = request.param
    ok, info = reachability[host]
    if not ok:
        pytest.skip(f"{host} unreachable over SSH -- see test_ssh_reachable[{host}] ({info})")
    return info


@pytest.fixture
def db_host(request: pytest.FixtureRequest, reachability: dict[str, tuple[bool, object]]):
    host = request.param
    ok, info = reachability[host]
    if not ok:
        pytest.skip(f"{host} unreachable over SSH -- see test_ssh_reachable[{host}] ({info})")
    return info


def _php_fpm_service(host) -> str:
    """The php*-fpm unit name carries the PHP version the distro shipped
    (e.g. php8.5-fpm) -- ask systemd live instead of hardcoding a version
    that will drift the next time the base image updates.

    list-unit-FILES, not list-units: `list-units` only shows currently
    loaded units, so a stopped php-fpm drops off it and the name lookup would
    wrongly read as "not installed" (caught live). `list-unit-files` lists
    installed unit files whatever their run state, so the name resolves even
    when the service is down -- and then the is_running check below can fail
    honestly with "<unit> is not running" instead of "not installed"."""
    out = host.run(
        "systemctl list-unit-files --no-legend --plain 'php*-fpm.service'"
    )
    lines = out.stdout.strip().splitlines()
    assert lines, "no php*-fpm unit file found (php-fpm not installed?)"
    return lines[0].split()[0]


@pytest.mark.parametrize("web_host", WEB_HOSTS, indirect=True)
class TestWebHost:
    """web group (Ubuntu): nginx + php-fpm serving WordPress."""

    def test_nginx_running(self, web_host) -> None:
        assert web_host.service("nginx").is_running, "nginx is not running"

    def test_port_80_listening(self, web_host) -> None:
        assert web_host.socket("tcp://0.0.0.0:80").is_listening, "nothing listening on :80"

    def test_home_page_returns_200(self, web_host) -> None:
        cmd = web_host.run("curl -sf -o /dev/null -w '%{http_code}' http://localhost/")
        code = cmd.stdout.strip()
        assert cmd.rc == 0 and code == "200", (
            f"GET localhost/ failed: rc={cmd.rc} code={code!r} stderr={cmd.stderr!r}"
        )

    def test_wp_admin_not_server_error(self, web_host) -> None:
        # Not a 200: /wp-admin/ redirects to the login form when logged out.
        # The point is a deliberate HTTP response, not a 5xx PHP crash.
        cmd = web_host.run("curl -s -o /dev/null -w '%{http_code}' http://localhost/wp-admin/")
        code = cmd.stdout.strip()
        assert code and not code.startswith("5"), f"/wp-admin/ returned {code!r} (PHP crash?)"

    def test_php_fpm_running(self, web_host) -> None:
        service = _php_fpm_service(web_host)
        assert web_host.service(service).is_running, f"{service} is not running"


@pytest.mark.parametrize("db_host", DB_HOSTS, indirect=True)
class TestDbHost:
    """db group (Oracle Linux): MySQL backing WordPress."""

    def test_mysqld_running(self, db_host) -> None:
        assert db_host.service("mysqld").is_running, "mysqld is not running"

    def test_port_3306_listening(self, db_host) -> None:
        # mysqld binds the host-only IP explicitly (db.sh), not 0.0.0.0 --
        # ask for that exact address, taken from the live ssh connection.
        ip = db_host.backend.hostname
        assert db_host.socket(f"tcp://{ip}:3306").is_listening, f"nothing listening on {ip}:3306"

    def test_select_1(self, db_host) -> None:
        # Local socket, root@localhost, no password -- same access path
        # db.sh's own provisioning uses. Proves MySQL answers the protocol,
        # not just that the process/port exist.
        cmd = db_host.run("mysql -uroot -e 'SELECT 1'")
        assert cmd.rc == 0 and "1" in cmd.stdout, (
            f"mysql -uroot -e 'SELECT 1' failed: rc={cmd.rc} stderr={cmd.stderr!r}"
        )
