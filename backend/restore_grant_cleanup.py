"""Bounded startup and scheduled cleanup for one-time restore grants."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import func

import database
from models.workspace import RestoreGrant
from workspace_store import cleanup_restore_grants

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RestoreGrantCleanupRun:
    deleted: int
    batches: int
    backlog: int
    target_reached: bool
    elapsed_ms: float


_metrics_lock = threading.Lock()
_metrics: dict[str, Any] = {
    "runs": 0,
    "deleted_total": 0,
    "last_deleted": 0,
    "backlog": 0,
    "errors": 0,
    "last_success": None,
    "last_error": None,
    "running": False,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count_backlog(db) -> int:
    now = datetime.now(timezone.utc)
    return int(
        db.query(func.count(RestoreGrant.id))
        .filter(RestoreGrant.cleanup_at <= now)
        .scalar()
        or 0
    )


def restore_grant_cleanup_metrics() -> dict[str, Any]:
    with _metrics_lock:
        return dict(_metrics)


def _record_batch(deleted: int) -> None:
    with _metrics_lock:
        _metrics["deleted_total"] += deleted


def _record_success(result: RestoreGrantCleanupRun) -> None:
    with _metrics_lock:
        _metrics["runs"] += 1
        _metrics["last_deleted"] = result.deleted
        _metrics["backlog"] = result.backlog
        _metrics["last_success"] = _utc_now()
        _metrics["last_error"] = None


def _record_error(*, deleted: int, backlog: int) -> None:
    with _metrics_lock:
        _metrics["runs"] += 1
        _metrics["last_deleted"] = deleted
        _metrics["backlog"] = backlog
        _metrics["errors"] += 1
        _metrics["last_error"] = _utc_now()


def run_restore_grant_cleanup(
    *,
    session_factory: Optional[Callable[[], Any]] = None,
    batch_size: int = 100,
    max_batches: int = 10,
    time_budget_seconds: float = 2.0,
    backlog_target: int = 0,
) -> RestoreGrantCleanupRun:
    """Delete repeated bounded pages until the target or run budget is reached."""
    session_factory = session_factory or database.SessionLocal
    batch_size = max(1, min(int(batch_size), 1000))
    max_batches = max(1, int(max_batches))
    time_budget_seconds = max(0.01, float(time_budget_seconds))
    backlog_target = max(0, int(backlog_target))
    started = time.monotonic()
    deleted_total = 0
    batches = 0
    backlog = 0

    try:
        while (
            batches < max_batches and time.monotonic() - started < time_budget_seconds
        ):
            db = session_factory()
            try:
                backlog = _count_backlog(db)
                if backlog <= backlog_target:
                    db.rollback()
                    break
                deleted = cleanup_restore_grants(db, limit=batch_size)
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
            deleted = int(deleted or 0)
            deleted_total += deleted
            batches += 1
            _record_batch(deleted)
            if deleted == 0:
                break

        db = session_factory()
        try:
            backlog = _count_backlog(db)
            db.rollback()
        finally:
            db.close()
        result = RestoreGrantCleanupRun(
            deleted=deleted_total,
            batches=batches,
            backlog=backlog,
            target_reached=backlog <= backlog_target,
            elapsed_ms=round((time.monotonic() - started) * 1000, 3),
        )
        _record_success(result)
        return result
    except Exception:
        try:
            db = session_factory()
            try:
                backlog = _count_backlog(db)
                db.rollback()
            finally:
                db.close()
        except Exception:
            backlog = max(backlog, backlog_target + 1)
        _record_error(deleted=deleted_total, backlog=backlog)
        raise


class RestoreGrantCleanupLifecycle:
    """One startup pass plus a retrying scheduled maintenance loop."""

    def __init__(
        self,
        *,
        interval_seconds: Optional[float] = None,
        run_cleanup: Callable[..., RestoreGrantCleanupRun] = run_restore_grant_cleanup,
    ) -> None:
        self.interval_seconds = max(
            0.01,
            float(
                interval_seconds
                if interval_seconds is not None
                else os.getenv("RESTORE_GRANT_CLEANUP_INTERVAL_SECONDS", "300")
            ),
        )
        self._run_cleanup = run_cleanup
        self._lifecycle_lock = threading.Lock()
        self._tasks: dict[
            asyncio.AbstractEventLoop,
            tuple[asyncio.Event, asyncio.Task[None]],
        ] = {}
        self._starting_loops: set[asyncio.AbstractEventLoop] = set()

    def _run_kwargs(self) -> dict[str, Any]:
        return {
            "batch_size": int(os.getenv("RESTORE_GRANT_CLEANUP_BATCH_SIZE", "100")),
            "max_batches": int(os.getenv("RESTORE_GRANT_CLEANUP_MAX_BATCHES", "10")),
            "time_budget_seconds": float(
                os.getenv("RESTORE_GRANT_CLEANUP_TIME_BUDGET_SECONDS", "2")
            ),
            "backlog_target": int(
                os.getenv("RESTORE_GRANT_CLEANUP_BACKLOG_TARGET", "0")
            ),
        }

    async def _run_once(self) -> None:
        try:
            result = await asyncio.to_thread(self._run_cleanup, **self._run_kwargs())
            logger.info(
                "restore_grant_cleanup deleted=%d batches=%d backlog=%d target_reached=%s",
                result.deleted,
                result.batches,
                result.backlog,
                result.target_reached,
            )
        except Exception as exc:
            logger.warning(
                "restore_grant_cleanup_failed error_type=%s",
                type(exc).__name__,
            )

    async def _run_scheduled(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self.interval_seconds,
                )
            except TimeoutError:
                await self._run_once()

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        with self._lifecycle_lock:
            current = self._tasks.get(loop)
            if (
                current is not None and not current[1].done()
            ) or loop in self._starting_loops:
                return
            self._starting_loops.add(loop)
        try:
            await self._run_once()
            stop_event = asyncio.Event()
            task = asyncio.create_task(
                self._run_scheduled(stop_event),
                name="restore-grant-cleanup",
            )
            with self._lifecycle_lock:
                self._tasks[loop] = (stop_event, task)
                running = bool(self._tasks)
        finally:
            with self._lifecycle_lock:
                self._starting_loops.discard(loop)
        with _metrics_lock:
            _metrics["running"] = running

    async def stop(self) -> None:
        loop = asyncio.get_running_loop()
        with self._lifecycle_lock:
            current = self._tasks.pop(loop, None)
        if current is not None:
            stop_event, task = current
            stop_event.set()
            await task
        with self._lifecycle_lock:
            running = bool(self._tasks)
        with _metrics_lock:
            _metrics["running"] = running

    def status(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            task_active = any(not task.done() for _event, task in self._tasks.values())
        return {
            **restore_grant_cleanup_metrics(),
            "interval_seconds": self.interval_seconds,
            "task_active": task_active,
        }


restore_grant_cleanup_lifecycle = RestoreGrantCleanupLifecycle()


__all__ = [
    "RestoreGrantCleanupLifecycle",
    "RestoreGrantCleanupRun",
    "restore_grant_cleanup_lifecycle",
    "restore_grant_cleanup_metrics",
    "run_restore_grant_cleanup",
]
