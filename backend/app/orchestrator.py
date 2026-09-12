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

PLAN_STATES = {
    "none": "plan",
    "planning": "plan",
    "failed": "plan",
    "approved": "implement",
    "implementing": "implement",
}


class Orchestrator:
    """Background worker owning the task lifecycle.

    Each tick:
      1. promote dependency-clear backlog tasks to queued
      2. start queued / due retry tasks (respecting agent capacity + backoff)
      3. poll in-flight executions; on completion run the phase handler
         (plan-ready ⇒ human approval; implement/execute ⇒ verification +
         risk gating).
    """

    def __init__(self) -> None:
        self.adapter = get_adapter(settings.adapter)
        self._running: dict[str, dict] = {}  # task_id -> {execution_id, phase}
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

    def _phase_for(self, task: Task) -> str | None:
        if not task.plan_required:
            return "execute"
        if task.plan_status == "awaiting_approval":
            return None  # must not execute until a human approves the plan
        return PLAN_STATES.get(task.plan_status, "plan")

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
            if task.id in self._running or self._phase_for(task) is None:
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
        phase = self._phase_for(task) or "execute"
        if phase == "plan" and task.plan_status != "planning":
            task.plan_status = "planning"
        elif phase == "implement" and task.plan_status != "implementing":
            task.plan_status = "implementing"

        artifacts_dir = settings.artifacts_dir / task.id / f"attempt-{task.current_attempt}"
        attempt = Attempt(
            task_id=task.id,
            attempt_number=task.current_attempt,
            phase=phase,
            status="running",
            started_at=utcnow(),
            logs_ref=str(artifacts_dir),
        )
        db.add(attempt)
        db.commit()
        try:
            execution_id = await self.adapter.submit(
                task, task.current_attempt, attempt.id, str(artifacts_dir), phase
            )
        except Exception as exc:
            attempt.status = "failed"
            attempt.failure_reason = f"adapter submit failed: {exc}"
            task.not_before = utcnow() + timedelta(seconds=min(2 ** (task.current_attempt + 1), 30))
            transition(db, task, "queued", actor="orchestrator", reason=f"adapter submit failed, retry scheduled: {exc}")
            db.commit()
            logger.exception("adapter submit failed for task %s", task.id)
            return False
        attempt.execution_id = execution_id or attempt.id
        db.commit()
        self._running[task.id] = {"execution_id": execution_id, "phase": phase}
        changed.add(task.id)
        return True

    # --------------------------------------------------------------- poll

    async def _poll_running(self, db: Session, changed: set[str]) -> None:
        for task_id in list(self._running.keys()):
            entry = self._running[task_id]
            status: ExecutionStatus = await self.adapter.poll(entry["execution_id"])
            if not status.running:
                await self._finish_execution(db, task_id, changed)

    async def _finish_execution(self, db: Session, task_id: str, changed: set[str]) -> None:
        entry = self._running.pop(task_id, None)
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or not entry:
            return
        attempt = (
            db.query(Attempt)
            .filter(Attempt.task_id == task_id, Attempt.execution_id == entry["execution_id"])
            .first()
        )
        result = await self.adapter.get_result(entry["execution_id"])
        risk = RISK_RULES.get(task.risk_tier, RISK_RULES["low"])
        max_attempts = task.max_attempts or risk["max_attempts"]
        auto_approve = risk["auto_approve"]

        if attempt:
            attempt.status = "finished"
            attempt.finished_at = utcnow()
            attempt.agent_output = result.output
            attempt.pr_url = result.pr_url or attempt.pr_url
            attempt.tools_used = json.dumps(result.tools_used)
            if result.logs_ref:
                attempt.logs_ref = result.logs_ref
            if not result.success:
                attempt.failure_reason = result.output and result.output[:500] or "agent reported failure"
        db.commit()

        # ---------------------------------------------------- plan phase done
        if entry["phase"] == "plan":
            if result.success:
                task.plan_text = result.plan or result.output
                task.plan_status = "awaiting_approval"
                task.escalation_reason = "Implementation plan ready — awaiting approval"
                transition(db, task, "needs_review", actor="orchestrator", reason=task.escalation_reason)
                log_action(db, task, "plan_ready", actor="orchestrator", to_status="needs_review", reason="plan produced")
            else:
                task.plan_status = "failed"
                reason = "planning failed: " + (attempt.failure_reason or "no plan produced")
                await self._handle_failure(db, task, reason, max_attempts, changed)
            changed.add(task.id)
            await bus.publish({"type": "verification", "task_id": task.id, "verdict": "plan"})
            return

        # ------------------------------------------- implement / execute: verify
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

        if not result.success:
            reason = "agent execution failed: " + (attempt.failure_reason or "unknown error")
            await self._handle_failure(db, task, reason, max_attempts, changed)
        elif verdict.verdict == "requires_review":
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
                if task.plan_required:
                    task.plan_status = "done"
                transition(db, task, "done", actor="orchestrator", reason="all criteria passed, auto-approved")
        else:
            await self._handle_failure(db, task, verdict.failure_reason or "verification failed", max_attempts, changed)

        changed.add(task.id)
        await bus.publish(
            {
                "type": "verification",
                "task_id": task.id,
                "verdict": verdict.verdict,
            }
        )

    async def _handle_failure(self, db: Session, task: Task, reason: str, max_attempts: int, changed: set[str]) -> None:
        if task.current_attempt < max_attempts:
            task.current_attempt += 1
            task.not_before = utcnow() + timedelta(seconds=min(2 ** task.current_attempt, 30))
            task.escalation_reason = None
            transition(db, task, "executing", actor="orchestrator", reason=f"retry {task.current_attempt} scheduled")
            log_action(db, task, "retry", actor="orchestrator", to_status="executing", reason=reason)
        else:
            task.escalation_reason = reason
            transition(db, task, "needs_review", actor="orchestrator", reason=f"max attempts ({max_attempts}) reached: {reason}")
            log_action(db, task, "escalation", actor="orchestrator", to_status="needs_review", reason=reason)
        changed.add(task.id)

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
        if task.plan_required and task.plan_status in {"awaiting_approval", "failed"}:
            task.plan_status = "planning"
            reason = f"reviewer requested a new plan: {note}".strip()
        else:
            reason = f"reviewer requested retry: {note}".strip()
        task.current_attempt += 1
        task.not_before = None
        task.escalation_reason = None
        transition(db, task, "executing", actor=actor, reason=reason)
        log_action(db, task, "review", actor=actor, to_status="executing", reason=note or "reviewer retry")
        db.commit()
        await bus.publish(task_event(task, db))

    async def review_approve(self, db: Session, task: Task, note: str = "", actor: str = "reviewer") -> None:
        if task.plan_required and task.plan_status == "planning":
            raise ValueError("planning failed — approve_plan unavailable; re-plan or reject instead")
        task.escalation_reason = None
        if task.plan_required:
            task.plan_status = "done"
        transition(db, task, "done", actor=actor, reason=f"reviewer approved: {note}".strip())
        log_action(db, task, "review", actor=actor, to_status="done", reason=note or "approved")
        db.commit()
        await bus.publish(task_event(task, db))

    async def review_approve_plan(self, db: Session, task: Task, note: str = "", actor: str = "reviewer") -> None:
        """Approve a produced plan: the implementation phase starts immediately."""
        if task.plan_status not in {"awaiting_approval", "failed"}:
            raise ValueError(f"no pending plan to approve (plan_status={task.plan_status!r})")
        task.plan_status = "approved"
        task.current_attempt = 0  # reset attempt budget for the implement phase
        task.not_before = None
        task.escalation_reason = None
        transition(db, task, "queued", actor=actor, reason=f"plan approved, implementation queued: {note}".strip())
        log_action(db, task, "plan_approved", actor=actor, to_status="queued", reason=note or "plan approved")
        db.commit()
        await bus.publish(task_event(task, db))

    async def review_reject(self, db: Session, task: Task, note: str = "", actor: str = "reviewer") -> None:
        task.escalation_reason = note or "rejected by reviewer"
        transition(db, task, "rejected", actor=actor, reason=note or "task invalid as specified")
        log_action(db, task, "review", actor=actor, to_status="rejected", reason=note or "rejected")
        db.commit()
        await bus.publish(task_event(task, db))


orchestrator = Orchestrator()