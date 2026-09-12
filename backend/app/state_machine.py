from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import AuditLog, Task


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "backlog": {"queued", "blocked", "rejected"},
    "queued": {"executing", "blocked", "rejected"},
    "executing": {"verifying", "blocked", "rejected", "queued"},
    "verifying": {"done", "needs_review", "executing", "blocked", "rejected"},
    "needs_review": {"done", "executing", "rejected", "blocked"},
    "blocked": {"queued", "rejected"},
}


def is_valid_transition(from_status: str, to_status: str) -> bool:
    return to_status in ALLOWED_TRANSITIONS.get(from_status, set())


def transition(
    db: Session,
    task: Task,
    to_status: str,
    actor: str = "system",
    reason: str = "",
) -> None:
    if task.status == to_status:
        return
    if not is_valid_transition(task.status, to_status):
        raise ValueError(f"Invalid transition: {task.status!r} → {to_status!r}")
    from_s = task.status
    task.status = to_status
    task.updated_at = utcnow()
    db.add(
        AuditLog(
            task_id=task.id,
            actor=actor,
            action="status_change",
            from_status=from_s,
            to_status=to_status,
            reason=reason,
        )
    )
    db.flush()