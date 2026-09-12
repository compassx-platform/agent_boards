from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Attempt, Criterion, ContextRef, Task


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def criterion_out(c: Criterion) -> dict:
    config = c.check_config or "{}"
    try:
        parsed = json.loads(config)
    except json.JSONDecodeError:
        parsed = {}
    return {
        "id": c.id,
        "description": c.description,
        "check_type": c.check_type,
        "check_config": parsed,
        "result": c.result,
        "detail": c.detail,
    }


def context_ref_out(r: ContextRef) -> dict:
    return {"id": r.id, "type": r.type, "ref": r.ref, "description": r.description}


def attempt_out(a: Attempt) -> dict:
    try:
        tools = json.loads(a.tools_used)
    except (json.JSONDecodeError, TypeError):
        tools = []
    return {
        "id": a.id,
        "attempt_number": a.attempt_number,
        "execution_id": a.execution_id,
        "status": a.status,
        "started_at": _dt(a.started_at),
        "finished_at": _dt(a.finished_at),
        "agent_output": a.agent_output,
        "verification_result": a.verification_result,
        "verification_details": a.verification_details,
        "failure_reason": a.failure_reason,
        "tools_used": tools,
        "logs_ref": a.logs_ref,
    }


def serialize_task(db: Session, task: Task) -> dict:
    deps = [d.id for d in task.deps(db)]
    return {
        "id": task.id,
        "title": task.title,
        "intent": task.intent,
        "priority": task.priority,
        "risk_tier": task.risk_tier,
        "status": task.status,
        "created_by": task.created_by,
        "agent_capability": task.agent_capability,
        "current_attempt": task.current_attempt,
        "max_attempts": task.max_attempts,
        "escalation_reason": task.escalation_reason,
        "depends_on": deps,
        "created_at": _dt(task.created_at),
        "updated_at": _dt(task.updated_at),
        "criteria": [criterion_out(c) for c in task.criteria],
        "context": [context_ref_out(r) for r in task.context],
        "attempts": [attempt_out(a) for a in task.attempts],
    }


def task_event(task: Task, db: Session) -> dict:
    return {"type": "task", "task": serialize_task(db, task)}