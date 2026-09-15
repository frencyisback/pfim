"""HTTP quiescence and advisory locks for SQLite file operations. Restore prevents new requests
and waits for active sessions and streamed responses to close before replacing the database.
File locks complement the in-process gate by excluding concurrent backends and administrative
operations.
"""

from __future__ import annotations

import errno
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.utils.errors import PFIMError


def durable_replace(source: Path, destination: Path) -> None:
    """Atomically rename with write-through semantics where Windows supports them."""

    # Do not use resolve: if a destination name was replaced by a symlink, replace the link
    # itself, never its target file.
    source = Path(os.path.abspath(source))
    destination = Path(os.path.abspath(destination))
    if os.name != "nt":
        os.replace(source, destination)
        return

    import ctypes
    from ctypes import wintypes

    move_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move_file_ex.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move_file_ex.restype = wintypes.BOOL
    movefile_replace_existing = 0x1
    movefile_write_through = 0x8
    if not move_file_ex(
        str(source),
        str(destination),
        movefile_replace_existing | movefile_write_through,
    ):
        raise ctypes.WinError(ctypes.get_last_error())


class MaintenanceBusyError(PFIMError):
    status_code = 503
    error_code = "MAINTENANCE_BUSY"


class MaintenanceTimeoutError(PFIMError):
    status_code = 503
    error_code = "MAINTENANCE_TIMEOUT"


class InterprocessLockError(PFIMError):
    status_code = 503
    error_code = "INTERPROCESS_LOCK_UNAVAILABLE"


_LOCAL_LOCKS_GUARD = threading.Lock()
_LOCAL_LOCKS: dict[Path, threading.Lock] = {}


def _local_lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _LOCAL_LOCKS_GUARD:
        return _LOCAL_LOCKS.setdefault(resolved, threading.Lock())


class InterprocessFileLock:
    """Portable, non-destructive exclusive lock on one byte. The file deliberately remains on
    disk: lock ownership belongs to the descriptor and the OS releases it even after a crash.
    A local lock supplements the OS lock because flock and msvcrt.locking differ in
    same-process reentrancy.
    """

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self._local_lock = _local_lock_for(self.path)
        self._stream: BinaryIO | None = None

    @staticmethod
    def _try_os_lock(stream: BinaryIO) -> None:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            return

        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_os(stream: BinaryIO) -> None:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _is_contention(exc: OSError) -> bool:
        return exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(
            exc, "winerror", None
        ) in {33, 36, 158}

    def acquire(self, *, timeout: float = 30.0) -> None:
        if self._stream is not None:
            raise RuntimeError(f"Lock already acquired: {self.path}")
        if timeout < 0:
            raise ValueError("timeout cannot be negative")

        deadline = time.monotonic() + timeout
        if not self._local_lock.acquire(timeout=timeout):
            raise InterprocessLockError(
                "Another PFIM operation is still in progress",
                detail={"lock": self.path.name, "retryable": True},
            )

        stream: BinaryIO | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            stream = self.path.open("a+b")
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()

            while True:
                try:
                    self._try_os_lock(stream)
                    self._stream = stream
                    return
                except OSError as exc:
                    if not self._is_contention(exc):
                        raise
                    if time.monotonic() >= deadline:
                        raise InterprocessLockError(
                            "Another PFIM process holds the operational lock",
                            detail={"lock": self.path.name, "retryable": True},
                        ) from exc
                    time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        except BaseException:
            if stream is not None:
                stream.close()
            self._local_lock.release()
            raise

    def release(self) -> None:
        stream = self._stream
        if stream is None:
            return
        try:
            self._unlock_os(stream)
        finally:
            self._stream = None
            stream.close()
            self._local_lock.release()

    @contextmanager
    def hold(self, *, timeout: float = 30.0) -> Iterator[None]:
        self.acquire(timeout=timeout)
        try:
            yield
        finally:
            self.release()


class MaintenanceGate:
    """Count active requests and provide an exclusive restore section."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active_requests = 0
        self._maintenance = False
        self._operation_id: str | None = None
        self._poisoned = False

    def enter_request(self) -> bool:
        with self._condition:
            if self._maintenance or self._poisoned:
                return False
            self._active_requests += 1
            return True

    def leave_request(self) -> None:
        with self._condition:
            if self._active_requests <= 0:
                raise RuntimeError("Unbalanced maintenance request counter")
            self._active_requests -= 1
            self._condition.notify_all()

    def begin(
        self,
        operation_id: str,
        *,
        current_request_tracked: bool,
        timeout: float,
    ) -> None:
        if timeout < 0:
            raise ValueError("timeout cannot be negative")
        excluded = 1 if current_request_tracked else 0
        deadline = time.monotonic() + timeout
        with self._condition:
            if self._maintenance or self._poisoned:
                raise MaintenanceBusyError(
                    "PFIM is already in maintenance mode",
                    detail={"active_restore_id": self._operation_id},
                )
            if self._active_requests < excluded:
                raise RuntimeError("The restore request is not registered in the gate")
            self._maintenance = True
            self._operation_id = operation_id
            while self._active_requests > excluded:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._maintenance = False
                    self._operation_id = None
                    self._condition.notify_all()
                    raise MaintenanceTimeoutError(
                        "Timed out waiting for active requests to finish",
                        detail={"active_requests": self._active_requests - excluded},
                    )
                self._condition.wait(timeout=remaining)

    def end(self, operation_id: str) -> None:
        with self._condition:
            if self._operation_id != operation_id:
                raise RuntimeError("Attempt to close a different maintenance operation")
            if not self._poisoned:
                self._maintenance = False
                self._operation_id = None
                self._condition.notify_all()

    def poison(self, operation_id: str) -> None:
        """Keep the gate closed when database validity cannot be established."""

        with self._condition:
            if self._operation_id != operation_id:
                raise RuntimeError("Attempt to poison a different maintenance operation")
            self._poisoned = True
            self._maintenance = True
            self._condition.notify_all()

    @contextmanager
    def exclusive(
        self,
        operation_id: str,
        *,
        current_request_tracked: bool,
        timeout: float,
    ) -> Iterator[None]:
        self.begin(
            operation_id,
            current_request_tracked=current_request_tracked,
            timeout=timeout,
        )
        try:
            yield
        finally:
            self.end(operation_id)

    def snapshot(self) -> dict[str, object]:
        with self._condition:
            return {
                "maintenance_mode": self._maintenance or self._poisoned,
                "active_restore_id": self._operation_id,
                "active_requests": self._active_requests,
                "poisoned": self._poisoned,
            }


maintenance_gate = MaintenanceGate()

OPERATION_LOCK_FILENAME = ".pfim-backup-restore.lock"
INSTANCE_LOCK_FILENAME = ".pfim-backend-instance.lock"


def operation_lock(data_dir: Path) -> InterprocessFileLock:
    return InterprocessFileLock(data_dir / OPERATION_LOCK_FILENAME)


def backend_instance_lock(data_dir: Path) -> InterprocessFileLock:
    return InterprocessFileLock(data_dir / INSTANCE_LOCK_FILENAME)


class MaintenanceGateMiddleware:
    """Reject new requests while restore is waiting for or holding quiescence."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        gate: MaintenanceGate = maintenance_gate,
        control_paths: set[str] | None = None,
    ) -> None:
        self.app = app
        self.gate = gate
        self.control_paths = control_paths or set()

    def _is_control_request(self, scope: Scope) -> bool:
        if scope.get("method", "").upper() != "GET":
            return False
        path = scope.get("path", "")
        return path in self.control_paths or path.startswith("/api/v1/backup/restore-operations/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._is_control_request(scope):
            await self.app(scope, receive, send)
            return

        if not self.gate.enter_request():
            response = JSONResponse(
                status_code=503,
                content={
                    "error_code": "MAINTENANCE_MODE",
                    "message": "PFIM is temporarily under maintenance for a restore",
                    "detail": self.gate.snapshot(),
                },
                headers={"Cache-Control": "no-store", "Retry-After": "1"},
            )
            await response(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            self.gate.leave_request()
