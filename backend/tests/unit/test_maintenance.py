"""HTTP gate and OS locks used by restore."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.maintenance import (
    InterprocessFileLock,
    InterprocessLockError,
    MaintenanceGate,
    MaintenanceGateMiddleware,
    MaintenanceTimeoutError,
)


def test_gate_stops_new_requests_and_waits_for_the_active_one():
    gate = MaintenanceGate()
    assert gate.enter_request() is True  # restore request
    assert gate.enter_request() is True  # another request already admitted
    entered = threading.Event()
    release = threading.Event()

    def maintenance() -> None:
        with gate.exclusive(
            "operation",
            current_request_tracked=True,
            timeout=2,
        ):
            entered.set()
            assert gate.enter_request() is False
            assert release.wait(timeout=2)

    worker = threading.Thread(target=maintenance)
    worker.start()
    assert not entered.wait(timeout=0.1)
    gate.leave_request()  # finish the other request
    assert entered.wait(timeout=1)
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    gate.leave_request()  # finish the restore response
    assert gate.enter_request() is True
    gate.leave_request()


def test_gate_timeout_reopens_without_starting_maintenance():
    gate = MaintenanceGate()
    assert gate.enter_request() is True

    with pytest.raises(MaintenanceTimeoutError):
        gate.begin(
            "operation",
            current_request_tracked=False,
            timeout=0.01,
        )

    assert gate.snapshot()["maintenance_mode"] is False
    gate.leave_request()


def test_middleware_keeps_only_control_plane_available_during_restore():
    gate = MaintenanceGate()
    test_app = FastAPI()
    test_app.add_middleware(
        MaintenanceGateMiddleware,
        gate=gate,
        control_paths={"/health"},
    )

    @test_app.get("/health")
    def health():
        return {"status": "maintenance"}

    @test_app.get("/data")
    def data():
        return {"value": 1}

    gate.begin("operation", current_request_tracked=False, timeout=0)
    try:
        with TestClient(test_app) as client:
            blocked = client.get("/data")
            health_response = client.get("/health")
    finally:
        gate.end("operation")

    assert blocked.status_code == 503
    assert blocked.json()["error_code"] == "MAINTENANCE_MODE"
    assert health_response.status_code == 200


def test_interprocess_lock_is_released_after_process_termination(tmp_path: Path):
    lock_path = tmp_path / "operation.lock"
    code = (
        "import sys,time; from pathlib import Path; "
        "from app.maintenance import InterprocessFileLock; "
        "lock=InterprocessFileLock(Path(sys.argv[1])); lock.acquire(timeout=2); "
        "print('ready', flush=True); time.sleep(30)"
    )
    worker = subprocess.Popen(
        [sys.executable, "-c", code, str(lock_path)],
        cwd=Path(__file__).resolve().parents[2],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert worker.stdout is not None
        assert worker.stdout.readline().strip() == "ready"
        with pytest.raises(InterprocessLockError):
            InterprocessFileLock(lock_path).acquire(timeout=0.1)
    finally:
        worker.terminate()
        worker.wait(timeout=5)

    contender = InterprocessFileLock(lock_path)
    contender.acquire(timeout=1)
    contender.release()
