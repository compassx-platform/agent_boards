from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    # naive-UTC everywhere: SQLite strips tzinfo, so keep one convention.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id() -> str:
    return str(uuid4())


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), primary_key=True)
    dependency_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), primary_key=True)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255))
    intent: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    risk_tier: Mapped[str] = mapped_column(String(16), default="low")
    status: Mapped[str] = mapped_column(String(32), default="backlog", index=True)
    created_by: Mapped[str] = mapped_column(String(128), default="creator@example.com")
    agent_capability: Mapped[str] = mapped_column(String(128), default="default")
    # Omnigent harness (execution engine) this task runs under. Stored per task;
    # resolved to a fresh agent_id against the live server at submit time.
    harness: Mapped[str] = mapped_column(String(64), default="opencode-native")
    # Optional per-task workspace override: the host directory of the app/repo
    # the agent should work in. Falls back to settings.omnigent_workspace.
    workspace: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_attempt: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    not_before: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    # Implementation-plan lifecycle (plan-first execution).
    # plan_status: none | planning | awaiting_approval | approved |
    #              implementing | failed
    plan_required: Mapped[bool] = mapped_column(default=False)
    plan_status: Mapped[str] = mapped_column(String(32), default="none")
    plan_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    criteria: Mapped[list["Criterion"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="Criterion.created_at"
    )
    context: Mapped[list["ContextRef"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="ContextRef.created_at"
    )
    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="Attempt.attempt_number"
    )
    sessions: Mapped[list["ExecutionSession"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="ExecutionSession.created_at"
    )
    audits: Mapped[list["AuditLog"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="AuditLog.ts"
    )

    def deps(self, db) -> list[Task]:
        rows = db.query(TaskDependency).filter(TaskDependency.task_id == self.id).all()
        ids = [r.dependency_id for r in rows]
        return db.query(Task).filter(Task.id.in_(ids)).all() if ids else []


class Criterion(Base):
    __tablename__ = "criteria"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    check_type: Mapped[str] = mapped_column(String(32))
    check_config: Mapped[str] = mapped_column(Text, default="{}")
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    task: Mapped[Task] = relationship(back_populates="criteria")


class ContextRef(Base):
    __tablename__ = "context_refs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    ref: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    task: Mapped[Task] = relationship(back_populates="context")


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    attempt_number: Mapped[int] = mapped_column()
    execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phase: Mapped[str] = mapped_column(String(16), default="execute")  # plan | implement | execute
    pr_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    agent_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    verification_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools_used: Mapped[str] = mapped_column(Text, default="[]")
    logs_ref: Mapped[str | None] = mapped_column(Text, nullable=True)

    task: Mapped[Task] = relationship(back_populates="attempts")


class ExecutionSession(Base):
    """A single agent session bound to a task execution step.

    One task can spawn many sessions (plan + implement phases, retries, etc.).
    All of them are captured here so a reviewer can jump straight to the
    original session (and its full transcript/logs) for any step.
    """

    __tablename__ = "execution_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    attempt_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("attempts.id"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(32))  # opencode | omnigent | simulated
    session_id: Mapped[str] = mapped_column(String(128))
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # running|finished|failed
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    task: Mapped[Task] = relationship(back_populates="sessions")
    attempt: Mapped[Attempt | None] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow)
    actor: Mapped[str] = mapped_column(String(128), default="system")
    action: Mapped[str] = mapped_column(String(64))
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    task: Mapped[Task] = relationship(back_populates="audits")


class PlaidAccount(Base):
    __tablename__ = "plaid_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plaid_account_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    access_token: Mapped[str] = mapped_column(Text)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_mask: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plaid_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("plaid_accounts.id"), nullable=True, index=True
    )
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(32), default="paid")
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)