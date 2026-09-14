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
from app.models import Attempt, ExecutionSession, Task
from app.provisioning import initial_provision_steps, provisioner
from app.serialization import task_event
from app.settings_service import get_poll_interval_seconds
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
        # task_id -> provisioning in flight (host_provisioning stage):
        #   {session_id, phase, checks, next_check_at, last_error}
        self._provisioning: dict[str, dict] = {}
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
            await asyncio.sleep(get_poll_interval_seconds())

    async def _tick(self) -> None:
        db = SessionLocal()
        changed: set[str] = set()
        try:
            # NOTE: no backlog -> queued promotion here. Tasks start executing
            # only after a human approves them for execution (POST
            # /tasks/{id}/approve_execution). In-flight attempts are resumed by
            # _start_available, which only looks at queued/executing.
            await self._start_available(db, changed)
            await self._poll_provisioning(db, changed)
            await self._poll_running(db, changed)
            db.commit()
            for task_id in changed:
                task = db.query(Task).filter(Task.id == task_id).first()
                if task:
                    await bus.publish(task_event(task, db))
        finally:
            db.close()

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
        capacity = max(0, settings.agent_capacity - len(self._running) - len(self._provisioning))
        started = 0
        for task in candidates:
            if started >= capacity:
                break
            if task.id in self._running or task.id in self._provisioning or self._phase_for(task) is None:
                continue
            if task.not_before and task.not_before > now:
                continue
            if task.status == "queued":
                if self.adapter.needs_provisioning(task):
                    transition(
                        db, task, "host_provisioning", actor="orchestrator",
                        reason="queued → bringing execution host to readiness",
                    )
                    task.provisioning_steps = json.dumps(initial_provision_steps())
                    db.commit()
                    self._provisioning[task.id] = {
                        "session_id": None,
                        "phase": self._phase_for(task) or "execute",
                        "checks": 0,
                        "next_check_at": None,  # first check fires immediately
                        "last_error": None,
                    }
                    changed.add(task.id)
                    continue
                transition(db, task, "executing", actor="orchestrator", reason="queued → assigned to agent")
                changed.add(task.id)
            if not await self._start_attempt(db, task, changed):
                continue
            started += 1

    async def _poll_provisioning(self, db: Session, changed: set[str]) -> None:
        """Escalating-timer host readiness checks for the host_provisioning stage.

        The first check fires immediately (on entry), then every failed check
        doubles the delay (10s, 20s, 40s, … capped) per settings, so a slow
        CompassX host bring-up never burns attempt budget. When the host is
        ready the task moves to executing and its first attempt reuses the
        already-created session.
        """
        for task_id in list(self._provisioning.keys()):
            entry = self._provisioning[task_id]
            now = asyncio.get_running_loop().time()
            if entry["next_check_at"] and now < entry["next_check_at"]:
                continue
            entry["next_check_at"] = None  # check in flight
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task or task.status != "host_provisioning":
                self._provisioning.pop(task_id, None)
                continue
            if entry["checks"] >= settings.host_provisioning_max_checks:
                reason = (
                    "host not ready after "
                    f"{entry['checks']} provisioning checks: "
                    f"{entry['last_error'] or 'host still unavailable'}"
                )
                task.escalation_reason = reason
                transition(db, task, "blocked", actor="orchestrator", reason=reason)
                log_action(db, task, "blocked", actor="orchestrator", to_status="blocked", reason=reason)
                changed.add(task.id)
                self._provisioning.pop(task_id, None)
                continue
            if await self._provision_host(db, task, entry, changed):
                self._provisioning.pop(task_id, None)
                continue
            entry["checks"] += 1
            delay = min(
                settings.host_provisioning_first_check_seconds * (2 ** (entry["checks"] - 1)),
                settings.host_provisioning_max_check_seconds,
            )
            entry["next_check_at"] = now + delay
            logger.warning(
                "task %s host not ready (check %d/%d); next check in %.0fs",
                task.id, entry["checks"], settings.host_provisioning_max_checks, delay,
            )

    async def _provision_host(self, db: Session, task: Task, entry: dict, changed: set[str]) -> bool:
        """One readiness probe. Returns True once the host is ready and the first
        attempt has been started (task moved to executing)."""
        if not entry["session_id"]:
            if task.session_id:
                # The task already owns an agent session (created on the first
                # attempt or by the user's explicit "new session" click). Never
                # double-create: reuse it for every subsequent attempt.
                entry["session_id"] = task.session_id
                await self._record_step(
                    db, task, "create_session", "done",
                    f"reusing session {task.session_id}",
                )
                entry["last_error"] = None
                return await self._finish_provisioning(db, task, entry, changed)
            try:
                host = await provisioner.ensure_host(
                    task, record=self._step_recorder(db, task)
                )
                self._persist_host(db, task, host)
            except Exception as exc:  # host still coming up / transient
                entry["last_error"] = str(exc)
                logger.warning(
                    "task %s host provisioning probe failed: %s",
                    task.id, exc,
                )
                return False
            await self._record_step(
                db, task, "create_session", "running",
                "creating agent session on the Omnigent server",
            )
            try:
                session_id = await self.adapter.provision(task, entry["phase"])
            except Exception as exc:
                entry["last_error"] = str(exc)
                await self._record_step(db, task, "create_session", "failed", str(exc)[:200])
                logger.warning(
                    "task %s session provisioning failed: %s",
                    task.id, exc,
                )
                return False
            if not session_id:
                entry["last_error"] = "workspace path not ready yet"
                return False
            entry["session_id"] = session_id
            task.session_id = session_id
            db.commit()
            await self._record_step(
                db, task, "create_session", "done", f"session {session_id} created",
            )
            entry["last_error"] = None
            return await self._finish_provisioning(db, task, entry, changed)
        return await self._finish_provisioning(db, task, entry, changed)

    async def _finish_provisioning(self, db: Session, task: Task, entry: dict, changed: set[str]) -> bool:
        """Host is ready: persist the session, move to executing, start the attempt."""
        transition(db, task, "executing", actor="orchestrator", reason="host ready — starting execution")
        db.commit()
        log_action(
            db, task, "host_ready", actor="orchestrator", to_status="executing",
            reason=(
                f"execution host ready; reusing session {entry['session_id']} "
                f"on host {task.host_id} ({task.host_name or '?'})"
            ),
        )
        changed.add(task.id)
        await self._start_attempt(db, task, changed, session_id=entry["session_id"], host_ready=True)
        return True

    @staticmethod
    def _persist_host(db: Session, task: Task, host: dict) -> None:
        task.host_id = host.get("host_id") or task.host_id
        task.host_name = host.get("host_name") or task.host_name
        task.compassx_workspace_id = host.get("workspace_id") or task.compassx_workspace_id
        if host.get("workspace_name"):
            task.compassx_workspace_name = host["workspace_name"]
        if host.get("workspace"):
            task.workspace = host["workspace"]
        if host.get("dev_url"):
            task.dev_url = host["dev_url"]

    # ----------------------------------------------------- provisioning steps

    @staticmethod
    def _load_steps(task: Task) -> list[dict]:
        raw = task.provisioning_steps or ""
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []

    async def _record_step(
        self, db: Session, task: Task, name: str, status: str, detail: str
    ) -> None:
        """Persist one provisioning-step update on the task and push it to the
        UI (SSE) so the checklist updates live during host bring-up."""
        steps = self._load_steps(task)
        entry = next((s for s in steps if s.get("name") == name), None)
        stamp = utcnow().isoformat()
        if entry is None:
            steps.append(
                {"name": name, "status": status, "detail": detail or "", "updated_at": stamp}
            )
        else:
            entry["status"] = status
            if detail:
                entry["detail"] = detail
            entry["updated_at"] = stamp
        task.provisioning_steps = json.dumps(steps)
        db.commit()
        await bus.publish(task_event(task, db))

    def _step_recorder(self, db: Session, task: Task):
        """Bound record callback handed to the provisioner's ensure_host."""

        async def record(name: str, status: str, detail: str) -> None:
            await self._record_step(db, task, name, status, detail)

        return record

    async def _start_attempt(
        self,
        db: Session,
        task: Task,
        changed: set[str],
        *,
        session_id: str | None = None,
        host_ready: bool = False,
    ) -> bool:
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
            if (task.compassx_app_id or "").strip() and not host_ready:
                host = await provisioner.ensure_host(task, record=self._step_recorder(db, task))
                self._persist_host(db, task, host)
                db.commit()
                log_action(
                    db,
                    task,
                    "host_provisioned",
                    actor="orchestrator",
                    to_status=task.status,
                    reason=(
                        f"dev host {task.host_id} ({task.host_name or '?'}) ready on "
                        f"Omnigent; workspace {task.workspace}"
                    ),
                )
                db.commit()
            if session_id is None:
                session_id = task.session_id or None
            execution_id = await self.adapter.submit(
                task, task.current_attempt, attempt.id, str(artifacts_dir), phase,
                session_id=session_id,
            )
        except Exception as exc:
            attempt.status = "failed"
            attempt.failure_reason = f"adapter submit failed: {exc}"
            risk = RISK_RULES.get(task.risk_tier, RISK_RULES["low"])
            max_attempts = task.max_attempts or risk["max_attempts"]
            task.current_attempt += 1
            if task.current_attempt >= max_attempts:
                reason = f"max attempts ({task.current_attempt}/{max_attempts}) reached: {exc}"
                task.escalation_reason = reason
                transition(db, task, "blocked", actor="orchestrator", reason=reason)
                log_action(db, task, "blocked", actor="orchestrator", to_status="blocked", reason=str(exc))
            else:
                task.not_before = utcnow() + timedelta(seconds=min(2 ** (task.current_attempt + 1), 30))
                transition(
                    db, task, "queued", actor="orchestrator",
                    reason=f"adapter submit failed (attempt {task.current_attempt}/{max_attempts}), retry scheduled: {exc}",
                )
                log_action(db, task, "retry", actor="orchestrator", to_status="queued", reason=str(exc))
            db.commit()
            logger.exception("adapter submit failed for task %s", task.id)
            return False
        attempt.execution_id = execution_id or attempt.id
        if execution_id and not task.session_id:
            # The adapter created the session internally (non-provisioned path or
            # a fallback). Own it on the task so every later attempt reuses it.
            task.session_id = execution_id
        db.commit()
        self._running[task.id] = {"execution_id": execution_id, "phase": phase}
        changed.add(task.id)
        return True

    # --------------------------------------------------------------- poll

    def _record_session(
        self, db: Session, task_id: str, execution_id: str, session: dict, status: str
    ) -> None:
        provider = str(session.get("provider") or "")
        sid = str(session.get("session_id") or "")
        if not provider or not sid:
            return
        row = (
            db.query(ExecutionSession)
            .filter(
                ExecutionSession.task_id == task_id,
                ExecutionSession.provider == provider,
                ExecutionSession.session_id == sid,
            )
            .first()
        )
        if row:
            if session.get("link") and row.link != session["link"]:
                row.link = session["link"]
            row.status = status
            row.updated_at = utcnow()
        else:
            # New active session: archive every other still-active session so the
            # task keeps exactly one active session at a time (old ones are kept,
            # flagged, never deleted).
            for stale in (
                db.query(ExecutionSession)
                .filter(
                    ExecutionSession.task_id == task_id,
                    ExecutionSession.archived.is_(False),
                )
                .all()
            ):
                stale.archived = True
                stale.updated_at = utcnow()
            db.add(
                ExecutionSession(
                    task_id=task_id,
                    provider=provider,
                    session_id=sid,
                    link=session.get("link") or "",
                    status=status,
                )
            )

    async def _poll_running(self, db: Session, changed: set[str]) -> None:
        for task_id in list(self._running.keys()):
            entry = self._running[task_id]
            status: ExecutionStatus = await self.adapter.poll(entry["execution_id"])
            if status.session:
                st = "running" if status.running else ("failed" if status.state == "failed" else "finished")
                self._record_session(db, task_id, entry["execution_id"], status.session, st)
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

        # Record the session(s) for this execution and link them to the attempt.
        if result.session_id:
            self._record_session(
                db,
                task_id,
                entry["execution_id"],
                {
                    "provider": result.provider or self.adapter.name,
                    "session_id": result.session_id,
                    "link": result.session_link,
                },
                "failed" if not result.success else "finished",
            )
        if attempt:
            unlinked = (
                db.query(ExecutionSession)
                .filter(
                    ExecutionSession.task_id == task_id,
                    ExecutionSession.attempt_id.is_(None),
                )
                .all()
            )
            for srow in unlinked:
                srow.attempt_id = attempt.id

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

        verdict = None
        if task.bypass_verification:
            # Verification bypass: skip the definition-of-done criteria entirely
            # and route the finished execution straight to the configured
            # outcome (needs_review by default, done if opted in).
            attempt.verification_result = "bypassed"
            attempt.verification_details = (
                f"verification bypassed; routed to {task.verification_bypass_outcome}"
            )
            db.commit()
            if not result.success:
                reason = "agent execution failed: " + (attempt.failure_reason or "unknown error")
                await self._handle_failure(db, task, reason, max_attempts, changed)
            elif task.verification_bypass_outcome == "done":
                task.escalation_reason = None
                if task.plan_required:
                    task.plan_status = "done"
                transition(db, task, "done", actor="orchestrator", reason="verification bypassed")
                await self._publish_changes(db, task)
            else:
                task.escalation_reason = "Verification bypassed — requires review"
                transition(db, task, "needs_review", actor="orchestrator", reason=task.escalation_reason)
                log_action(db, task, "escalation", actor="orchestrator", to_status="needs_review", reason=task.escalation_reason)
        else:
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
                    await self._publish_changes(db, task)
            else:
                await self._handle_failure(db, task, verdict.failure_reason or "verification failed", max_attempts, changed)

        changed.add(task.id)
        await bus.publish(
            {
                "type": "verification",
                "task_id": task.id,
                "verdict": "bypassed" if task.bypass_verification else (verdict.verdict if verdict else "pending"),
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
            transition(db, task, "blocked", actor="orchestrator", reason=f"max attempts ({task.current_attempt}/{max_attempts}) reached: {reason}")
            log_action(db, task, "blocked", actor="orchestrator", to_status="blocked", reason=reason)
        changed.add(task.id)

    async def _publish_changes(self, db: Session, task: Task, actor: str = "orchestrator") -> bool:
        """Commit & push a CompassX-bound task's completed changes to git."""
        if not (task.compassx_app_id or "").strip():
            return False
        if task.compassx_published:
            return False
        try:
            commit_message = (
                f"{task.title}\n\nTask {task.id}\n"
                f"Intent: {(task.intent or '')[:200]}"
            )
            result = await provisioner.publish(task, commit_message, actor=actor)
            task.compassx_published = True
            sha = str((result or {}).get("commit_sha") or "")
            log_action(
                db,
                task,
                "published",
                actor=actor,
                to_status=task.status,
                reason=f"changes committed & pushed to git" + (f" ({sha})" if sha else ""),
            )
            db.commit()
            await bus.publish(task_event(task, db))
            logger.info("published task %s changes via CompassX (sha=%s)", task.id, sha)
            return True
        except Exception as exc:  # noqa: BLE001 — publish is best-effort post-completion
            logger.warning("dev/publish failed for task %s: %s", task.id, exc)
            return False

    # -------------------------------------------------------------- recovery

    def _recover(self) -> None:
        db = SessionLocal()
        try:
            interrupted = db.query(Task).filter(
                Task.status.in_(["host_provisioning", "executing", "verifying"])
            ).all()
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
        await self._publish_changes(db, task, actor=actor)
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