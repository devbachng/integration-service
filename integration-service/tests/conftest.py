"""
Shared fixtures for the automated test suite.

Strategy: rather than mocking SIS/LMS, we spin them up as real
subprocesses (they are provided, working FastAPI apps) on dedicated test
ports, reset tenant data, and drive the Integration Service's internal
Python functions directly (engine.process_event, handlers, reconcile).
This exercises the real HTTP contracts end-to-end, matching how the
service behaves in production, while staying self-contained and fast
enough for CI (see docs/test-report.md for wall-clock numbers).
"""
from __future__ import annotations
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSHOP_DIR = os.environ.get("WORKSHOP_DIR", "/home/claude/rar_extract/Integration_workshop")

SIS_PORT = 8101
LMS_PORT = 8102
TENANT = "TEST01"
ADMIN_KEY = "admin-secret"
CLIENT_SECRET = "student-secret"


def _wait_port(port: int, timeout: float = 15):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"port {port} did not open in time")


@pytest.fixture(scope="session")
def sis_lms_servers():
    env = dict(os.environ)
    env.update({
        "CLIENT_SECRET": CLIENT_SECRET, "ADMIN_KEY": ADMIN_KEY, "JWT_SECRET": "test-secret",
        # Generous rate limit for the main test servers so bulk reconciliation
        # tests run fast; NFR-12 (429/Retry-After handling) is exercised
        # separately against a dedicated low-limit instance, see
        # `rate_limited_lms_server` below.
        "RATE_LIMIT": "100000",
    })
    test_db_dir = Path(tempfile.gettempdir())
    sis_db = test_db_dir / "sis_test.db"
    lms_db = test_db_dir / "lms_test.db"
    sis_env = dict(env); sis_env["SQLITE_URL"] = f"sqlite:///{sis_db.as_posix()}"
    lms_env = dict(env); lms_env["SQLITE_URL"] = f"sqlite:///{lms_db.as_posix()}"

    for db_file in (sis_db, lms_db):
        if db_file.exists():
            db_file.unlink()

    sis_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "sis.app.main:app", "--app-dir", WORKSHOP_DIR,
         "--host", "127.0.0.1", "--port", str(SIS_PORT)],
        env=sis_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    lms_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "lms.app.main:app", "--app-dir", WORKSHOP_DIR,
         "--host", "127.0.0.1", "--port", str(LMS_PORT)],
        env=lms_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_port(SIS_PORT)
        _wait_port(LMS_PORT)
        time.sleep(0.5)
        yield {"sis_url": f"http://127.0.0.1:{SIS_PORT}", "lms_url": f"http://127.0.0.1:{LMS_PORT}"}
    finally:
        sis_proc.terminate()
        lms_proc.terminate()
        sis_proc.wait(timeout=5)
        lms_proc.wait(timeout=5)


@pytest.fixture
def app_modules(sis_lms_servers, tmp_path, monkeypatch):
    """(Re)configure the Integration Service's app.* modules to point at the
    test SIS/LMS instances with a throwaway sqlite datastore, and reset
    tenant data before every test for isolation."""
    db_path = tmp_path / "integration_test.db"
    monkeypatch.setenv("SIS_URL", sis_lms_servers["sis_url"])
    monkeypatch.setenv("LMS_URL", sis_lms_servers["lms_url"])
    monkeypatch.setenv("TENANT_ID", TENANT)
    monkeypatch.setenv("SIS_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("LMS_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("INTEGRATION_DB_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("MAX_RETRIES", "3")
    monkeypatch.setenv("BACKOFF_BASE_SECONDS", "0.2")
    monkeypatch.setenv("BACKOFF_MAX_SECONDS", "1")
    monkeypatch.setenv("RECONCILE_PACING_SECONDS", "0.01")

    # fresh import of every app module so the new env vars take effect
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    import app.config as config
    import app.db as db
    import app.clients as clients
    import app.handlers as handlers
    import app.engine as engine
    import app.reconcile as reconcile
    import app.poller as poller

    db.init_db()

    httpx.post(f"{sis_lms_servers['sis_url']}/admin/tenants/{TENANT}/reset", headers={"x-admin-key": ADMIN_KEY})
    httpx.post(f"{sis_lms_servers['lms_url']}/admin/tenants/{TENANT}/reset", headers={"x-admin-key": ADMIN_KEY})
    httpx.put(f"{sis_lms_servers['sis_url']}/admin/tenants/{TENANT}/failure/OFF", headers={"x-admin-key": ADMIN_KEY})
    httpx.put(f"{sis_lms_servers['lms_url']}/admin/tenants/{TENANT}/failure/OFF", headers={"x-admin-key": ADMIN_KEY})

    import types
    return types.SimpleNamespace(
        config=config, db=db, clients=clients, handlers=handlers,
        engine=engine, reconcile=reconcile, poller=poller,
    )


@pytest.fixture
def sis_admin_h():
    return {"x-admin-key": ADMIN_KEY}


RATE_LIMITED_LMS_PORT = 8103


@pytest.fixture
def rate_limited_lms_url():
    """A dedicated LMS instance with the default (production-realistic,
    RATE_LIMIT=100/min) limit, isolated from the fast/high-limit servers
    used by every other test, so the 429/Retry-After test is both fast
    and doesn't interfere with (or get interfered with by) other tests."""
    env = dict(os.environ)
    rate_limited_db = Path(tempfile.gettempdir()) / "lms_ratelimit_test.db"
    env.update({"CLIENT_SECRET": CLIENT_SECRET, "ADMIN_KEY": ADMIN_KEY, "JWT_SECRET": "test-secret",
                 "SQLITE_URL": f"sqlite:///{rate_limited_db.as_posix()}"})
    if rate_limited_db.exists():
        rate_limited_db.unlink()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "lms.app.main:app", "--app-dir", WORKSHOP_DIR,
         "--host", "127.0.0.1", "--port", str(RATE_LIMITED_LMS_PORT)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_port(RATE_LIMITED_LMS_PORT)
        time.sleep(0.3)
        yield f"http://127.0.0.1:{RATE_LIMITED_LMS_PORT}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)
