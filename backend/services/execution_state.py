from collections.abc import Collection, Mapping
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from models.execution import Execution


def transition_execution(
    db: Session,
    execution_id: str,
    *,
    from_statuses: Collection[str],
    to_status: str,
    organization_id: str,
    values: Mapping[str, Any] | None = None,
) -> bool:
    """Atomically transition an execution only while it is in an allowed state."""
    update_values = dict(values or {})
    update_values["status"] = to_status

    result = db.execute(
        update(Execution)
        .where(
            Execution.id == execution_id,
            Execution.organization_id == organization_id,
            Execution.status.in_(tuple(from_statuses)),
        )
        .values(**update_values)
    )
    db.commit()
    return result.rowcount == 1
