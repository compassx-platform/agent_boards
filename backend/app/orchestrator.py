from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.adapters import ExecutionStatus, get_adapter
from app.audit import log_action
from app.config import RISK_RULES, settings
from app.db import SessionLocal
from app.events import bus
from app.models import Attempt, Task
from app.serialization import task_event
from app.state_machine import transition, utcnow
from app.verification import verify_attempt

logger = logging.getLogger("taskexec.orchestrator")

PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "urgent": 3}


class Orchestrator:
    """Background worker owning the task lifecycle.

    Each tick:
      1. promote dependency-clear backlog tasks to queued
      2. start queued / due retry tasks (respecting agent capacity + backoff)
      3. poll in-flight executions; on completion run verification and apply
         risk gating rules to pick the next state.
    """

    def __init__(self) -> None:
        self.adapter = get_adapter(settings.adapter)
        self._running: dict[str, str] = {}  # task_id -> execution_id
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await asyncio.to_thread(self._recover)
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("orchestrator tick failed")
            await asyncio.sleep(settings.poll_interval_seconds)

    async def _tick(self) -> None:
        db = SessionLocal()
        changed: set[str] = set()
        try:
            self._promote_backlog(db, changed)
            await self._start_available(db, changed)
            await self._poll_running(db, changed)
            db.commit()
            for task_id in changed:
                task = db.query(Task).filter(Task.id == task_id).first()
                if task:
                    await bus.publish(task_event(task, db))
        finally:
            db.close()

    # ------------------------------------------------------------- promote

    def _promote_backlog(self, db: Session, changed: set[str]) -> None:
        for task in db.query(Task).filter(Task.status == "backlog").all():
            deps = task.deps(db)
            if not deps:
                transition(db, task, "queued", actor="orchestrator", reason="dependencies satisfied")
                changed.add(task.id)
                continue
            if any(d.status not in {"done"} for d in deps):
                if any(d.status in {"rejected", "blocked"} for d in deps):
                    transition(db, task, "blocked", actor="orchestrator", reason="a dependency failed or is blocked")
                    changed.add(task.id)
                continue
            transition(db, task, "queued", actor="orchestrator", reason="all dependencies done")
            changed.add(task.id)

    # -------------------------------------------------------------- start

    async def _start_available(self, db: Session, changed: set[str]) -> None:
        now = utcnow()
        candidates = (
            db.query(Task)
            .filter(Task.status.in_(["queued", "executing"]))
            .all()
        )
        candidates.sort(key=lambda t: (-PRIORITY_RANK.get(t.priority, 1), t.created_at or now))
        capacity = max(0, settings.agent_capacity - len(self._running))
        started = 0
        for task in candidates:
            if started >= capacity:
                break
            if task.id in self._running:
                continue
            if task.not_before and task.not_before > now:
                continue
            if task.status == "queued":
                transition(db, task, "executing", actor="orchestrator", reason="queued → assigned to agent")
                changed.add(task.id)
            if not await self._start_attempt(db, task, changed):
                continue
            started += 1

    async def _start_attempt(self, db: Session, task: Task, changed: set[str]) -> bool:
        artifacts_dir = settings.artifacts_dir / task.id / f"attempt-{task.current_attempt}"
        attempt = Attempt(
            task_id=task.id,
            attempt_number=task.current_attempt,
            status="running",
            started_at=utcnow(),
            logs_ref=str(artifacts_dir),
        )
        db.add(attempt)
        db.commit()
        try:
            execution_id = await self.adapter.submit(
                task, task.current_attempt, attempt.id, str(artifacts_dir)
            )
        except Exception as exc:
            attempt.status = "failed"
            attempt.failure_reason = f"adapter submit failed: {exc}"
            db.commit()
            logger.exception("adapter submit failed for task %s", task.id)
            return False
        attempt.execution_id = execution_id or attempt.id
        db.commit()
        self._running[task.id] = attempt.execution_id
        changed.add(task.id)
        return True

    # --------------------------------------------------------------- poll

    async def _poll_running(self, db: Session, changed: set[str]) -> None:
        for task_id in list(self._running.keys()):
            execution_id = self._running[task_id]
            status = await self.adapter.poll(execution_id)
            if not status.running:
                await self._finish_execution(db, task_id, changed)

    async def _finish_execution(self, db: Session, task_id: str, changed: set[str]) -> None:
        execution_id = self._running.pop(task_id, None)
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or not execution_id:
            return
        attempt = (
            db.query(Attempt)
            .filter(Attempt.task_id == task_id, Attempt.execution_id == execution_id)
            .first()
        )
        result = await self.adapter.get_result(execution_id)
        risk = RISK_RULES.get(task.risk_tier, RISK_RULES["low"])
        max_attempts = task.max_attempts or risk["max_attempts"]
        auto_approve = risk["auto_approve"]

        if attempt:
            attempt.status = "finished"
            attempt.finished_at = utcnow()
            attempt.agent_output = result.output
            attempt.tools_used = json.dumps(result.tools_used)
            if result.logs_ref:
                attempt.logs_ref = result.logs_ref
            if not result.success:
                attempt.failure_reason = "agent reported failure"
        db.commit()

        transition(db, task, "verifying", actor="orchestrator", reason="agent output ready")
        db.flush()

        verdict = await verify_attempt(db, attempt, task.criteria)
        attempt.verification_result = (
            verdict.verdict if verdict.verdict != "requires_review" else "pending"
        )
        attempt.verification_details = verdict.details
        if verdict.failure_reason:
            attempt.failure_reason = verdict.failure_reason
        db.commit()

        if verdict.verdict == "requires_review":
            task.escalation_reason = verdict.failure_reason or "requires reviewer"
            transition(db, task, "needs_review", actor="orchestrator", reason=task.escalation_reason)
            log_action(db, task, "escalation", actor="orchestrator", to_status="needs_review", reason=task.escalation_reason)
        elif verdict.verdict == "pass":
            if not auto_approve:
                task.escalation_reason = "Risk tier requires human sign-off"
                transition(db, task, "needs_review", actor="orchestrator", reason=task.escalation_reason)
                log_action(db, task, "escalation", actor="orchestrator", to_status="needs_review", reason=task.escalation_reason)
            else:
                task.escalation_reason = None
                transition(db, task, "done", actor="orchestrator", reason="all criteria passed, auto-approved")
        else:
            if task.current_attempt < max_attempts:
                task.current_attempt += 1
                task.not_before = utcnow() + timedelta(seconds=min(2 ** task.current_attempt, 30))
                task.escalation_reason = None
                transition(db, task, "executing", actor="orchestrator", reason=f"retry {task.current_attempt} scheduled")
                log_action(db, task, "retry", actor="orchestrator", to_status="executing", reason=verdict.failure_reason or "verification failed")
            else:
                task.escalation_reason = verdict.failure_reason or "max attempts exhausted"
                transition(db, task, "needs_review", actor="orchestrator", reason=f"max attempts ({max_attempts}) reached: {task.escalation_reason}")
                log_action(db, task, "escalation", actor="orchestrator", to_status="needs_review", reason=task.escalation_reason)
        changed.add(task.id)
        await bus.publish(
            {
                "type": "verification",
                "task_id": task.id,
                "verdict": verdict.verdict,
            }
        )

    # -------------------------------------------------------------- recovery

    def _recover(self) -> None:
        db = SessionLocal()
        try:
            interrupted = db.query(Task).filter(Task.status.in_(["executing", "verifying"])).all()
            for task in interrupted:
                for a in [a for a in task.attempts if a.status == "running"]:
                    a.status = "interrupted"
                    a.failure_reason = "orchestrator restarted"
                transition(db, task, "queued", actor="system", reason="orchestrator restart: in-flight work re-queued")
            if interrupted:
                db.commit()
                logger.info("recovered %d in-flight tasks", len(interrupted))
        finally:
            db.close()

    # -------------------------------------------------------------- review

    async def review_retry(self, db: Session, task: Task, note: str = "", actor: str = "reviewer") -> None:
        """Move a needs_review task back into the queue with reviewer context."""
        task.current_attempt += 1
        task.not_before = None
        task.escalation_reason = None
        transition(db, task, "executing", actor=actor, reason=f"reviewer requested retry: {note}".strip())
        log_action(db, task, "review", actor=actor, to_status="executing", reason=note or "reviewer retry")
        db.commit()
        await bus.publish(task_event(task, db))

    async def review_approve(self, db: Session, task: Task, note: str = "", actor: str = "reviewer") -> None:
        task.escalation_reason = None
        transition(db, task, "done", actor=actor, reason=f"reviewer approved: {note}".strip())
        log_action(db, task, "review", actor=actor, to_status="done", reason=note or "approved")
        db.commit()
        await bus.publish(task_event(task, db))

    async def review_reject(self, db: Session, task: Task, note: str = "", actor: str = "reviewer") -> None:
        task.escalation_reason = note or "rejected by reviewer"
        transition(db, task, "rejected", actor=actor, reason=note or "task invalid as specified")
        log_action(db, task, "review", actor=actor, to_status="rejected", reason=note or "rejected")
        db.commit()
        await bus.publish(task_event(task, db))


orchestrator = Orchestrator()