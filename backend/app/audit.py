from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditLog, Task


def log_action(
    db: Session,
    task: Task,
    action: str,
    actor: str = "system",
    from_status: str | None = None,
    to_status: str | None = None,
    reason: str = "",
) -> None:
    db.add(
        AuditLog(
            task_id=task.id,
            actor=actor,
            action=action,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
        )
    )