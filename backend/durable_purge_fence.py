"""Durable cross-worker purge fences for process-local compatibility caches.

PostgreSQL lifecycle/tombstone rows are authoritative. Process-local caches may
accelerate active reads, but they may never override a committed purge fence.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

_FENCE_QUERY_BATCH_SIZE = 200


class PurgeFenceUnavailableError(RuntimeError):
    """Raised when durable purge authority cannot be checked truthfully."""


class PurgedScopeError(RuntimeError):
    """Raised when a cache access targets a durably purged diagram."""


@dataclass(frozen=True)
class PurgeFenceDecision:
    """Result of one durable fence lookup."""

    purged: bool
    authoritative: bool


def _scope_filters(model, owner_user_id: Optional[str], tenant_id: Optional[str]):
    filters = []
    if owner_user_id is not None:
        filters.append(model.owner_user_id == owner_user_id)
    if tenant_id is not None:
        filters.append(model.tenant_id == tenant_id)
    return filters


def diagram_purge_fence(
    diagram_id: str,
    *,
    owner_user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> PurgeFenceDecision:
    """Read the indexed durable lifecycle/tombstone authority for one diagram."""
    if not diagram_id:
        return PurgeFenceDecision(purged=False, authoritative=True)

    db = None
    try:
        from database import SessionLocal
        from models.workspace import DiagramLifecycle, PurgeOperation

        db = SessionLocal()
        lifecycle_states = (
            db.query(DiagramLifecycle.state)
            .filter(
                DiagramLifecycle.diagram_id == diagram_id,
                *_scope_filters(
                    DiagramLifecycle,
                    owner_user_id,
                    tenant_id,
                ),
            )
            .all()
        )
        if any(state != "active" for (state,) in lifecycle_states):
            return PurgeFenceDecision(purged=True, authoritative=True)

        # Lifecycle rows are the primary authority. The indexed operation lookup
        # is a defensive fallback for legacy/incomplete rows.
        operation = (
            db.query(PurgeOperation.id)
            .filter(
                PurgeOperation.scope_type == "diagram",
                PurgeOperation.scope_id == diagram_id,
                *_scope_filters(PurgeOperation, owner_user_id, tenant_id),
            )
            .first()
        )
        return PurgeFenceDecision(
            purged=operation is not None,
            authoritative=True,
        )
    except Exception as exc:
        logger.warning(
            "durable_purge_fence_unavailable error_type=%s",
            type(exc).__name__,
        )
        return PurgeFenceDecision(
            purged=True,
            authoritative=False,
        )
    finally:
        if db is not None:
            db.close()


def require_diagram_cache_access(
    diagram_id: str,
    *,
    owner_user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> None:
    """Deny cache reads/writes after purge; fail closed in production."""
    decision = diagram_purge_fence(
        diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if not decision.authoritative:
        raise PurgeFenceUnavailableError("Durable purge authority is unavailable")
    if decision.purged:
        raise PurgedScopeError("Diagram has been purged")


def diagram_is_durably_purged(
    diagram_id: str,
    *,
    owner_user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> bool:
    """Return durable purge truth for fixed-point attestation.

    Unlike ordinary compatibility-cache access, attestation never treats a
    missing authority as absence, including in development/test mode.
    """
    decision = diagram_purge_fence(
        diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if not decision.authoritative:
        raise PurgeFenceUnavailableError("Durable purge authority is unavailable")
    return decision.purged


def durably_purged_diagram_ids(diagram_ids: Iterable[str]) -> set[str]:
    """Return fenced IDs from bounded indexed batches for startup eviction."""
    candidates = sorted({str(value) for value in diagram_ids if value})
    if not candidates:
        return set()

    db = None
    try:
        from database import SessionLocal
        from models.workspace import DiagramLifecycle, PurgeOperation

        db = SessionLocal()
        fenced: set[str] = set()
        for offset in range(0, len(candidates), _FENCE_QUERY_BATCH_SIZE):
            batch = candidates[offset : offset + _FENCE_QUERY_BATCH_SIZE]
            fenced.update(
                str(diagram_id)
                for (diagram_id,) in db.query(DiagramLifecycle.diagram_id)
                .filter(
                    DiagramLifecycle.diagram_id.in_(batch),
                    DiagramLifecycle.state.in_(("purging", "purged")),
                )
                .all()
            )
            fenced.update(
                str(scope_id)
                for (scope_id,) in db.query(PurgeOperation.scope_id)
                .filter(
                    PurgeOperation.scope_type == "diagram",
                    PurgeOperation.scope_id.in_(batch),
                )
                .all()
            )
        return fenced
    except Exception as exc:
        logger.warning(
            "durable_purge_fence_batch_unavailable error_type=%s",
            type(exc).__name__,
        )
        raise PurgeFenceUnavailableError(
            "Durable purge authority is unavailable"
        ) from exc
    finally:
        if db is not None:
            db.close()
