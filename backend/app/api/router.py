from __future__ import annotations

import json
import re
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.adapters import get_adapter
from app.audit import log_action
from app.compassx import compassx
from app.config import CHECK_TYPES, PRIORITIES, RISK_RULES, RISK_TIERS, settings
from app.db import get_session
from app.events import bus
from app.models import AuditLog, Attempt, ContextRef, Criterion, Task, TaskDependency
from app.orchestrator import orchestrator
from app.serialization import serialize_task
from app.state_machine import transition

router = APIRouter(prefix="", tags=["taskexec"])


class ContextRefIn(BaseModel):
    type: Literal["link", "file", "dataset", "prior_task_output"] = "link"
    ref: str
    description: str | None = None


class CriterionIn(BaseModel):
    description: str
    check_type: str
    check_config: dict = {}

    @field_validator("check_type")
    @classmethod
    def check_type_valid(cls, v: str) -> str:
        if v not in CHECK_TYPES:
            raise ValueError(f"check_type must be one of {CHECK_TYPES}")
        return v


class TaskCreate(BaseModel):
    title: str
    intent: str = ""
    priority: str = "normal"
    risk_tier: str = "low"
    agent_capability: str = "default"
    max_attempts: int | None = None
    plan_required: bool = False
    workspace: str | None = None
    harness: str | None = None
    compassx_app_id: str | None = None
    compassx_app_name: str | None = None
    compassx_workspace_id: str | None = None
    context: list[ContextRefIn] = []
    criteria: list[CriterionIn] = []
    depends_on: list[str] = []

    @field_validator("priority")
    @classmethod
    def priority_valid(cls, v: str) -> str:
        if v not in PRIORITIES:
            raise ValueError(f"priority must be one of {PRIORITIES}")
        return v

    @field_validator("risk_tier")
    @classmethod
    def risk_valid(cls, v: str) -> str:
        if v not in RISK_TIERS:
            raise ValueError(f"risk_tier must be one of {RISK_TIERS}")
        return v


class ParseRequest(BaseModel):
    text: str


class ReviewRequest(BaseModel):
    action: Literal["approve", "retry", "reject", "approve_plan"]
    note: str = ""


class NoteRequest(BaseModel):
    note: str = ""


def _current_user(request: Request) -> str:
    return request.headers.get("X-User", settings.default_user)


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _build_task(db: Session, payload: TaskCreate, user: str) -> Task:
    if payload.depends_on:
        existing = {r[0] for r in db.query(Task.id).filter(Task.id.in_(payload.depends_on)).all()}
        missing = [d for d in payload.depends_on if d not in existing]
        if missing:
            raise HTTPException(status_code=422, detail=f"unknown dependency ids: {missing}")

    risk = RISK_RULES.get(payload.risk_tier, RISK_RULES["low"])
    task = Task(
        title=payload.title,
        intent=payload.intent or payload.title,
        priority=payload.priority,
        risk_tier=payload.risk_tier,
        agent_capability=payload.agent_capability,
        created_by=user,
        max_attempts=payload.max_attempts or risk["max_attempts"],
        status="backlog",
        plan_required=payload.plan_required,
        plan_status="none",
        workspace=(payload.workspace or "").strip() or None,
        harness=(payload.harness or "").strip() or settings.omnigent_default_harness,
        compassx_app_id=(payload.compassx_app_id or "").strip() or None,
        compassx_app_name=(payload.compassx_app_name or "").strip() or None,
        compassx_workspace_id=(payload.compassx_workspace_id or "").strip() or None,
    )
    db.add(task)
    db.flush()

    for dep in payload.depends_on:
        db.add(TaskDependency(task_id=task.id, dependency_id=dep))

    if payload.criteria:
        for c in payload.criteria:
            db.add(
                Criterion(
                    task_id=task.id,
                    description=c.description,
                    check_type=c.check_type,
                    check_config=json.dumps(c.check_config),
                )
            )
        if payload.risk_tier == "high" and not any(
            c.check_type in {"human_approval", "manual_checklist"} for c in payload.criteria
        ):
            db.add(
                Criterion(
                    task_id=task.id,
                    description="Human sign-off (enforced for high-risk tasks)",
                    check_type="human_approval",
                    check_config="{}",
                )
            )
    else:
        db.add(
            Criterion(
                task_id=task.id,
                description="Output indicates success",
                check_type="output_match",
                check_config=json.dumps({"pattern": "success"}),
            )
        )

    for ctx in payload.context:
        db.add(
            ContextRef(
                task_id=task.id, type=ctx.type, ref=ctx.ref, description=ctx.description
            )
        )
    db.commit()
    return task


@router.post("/tasks", status_code=201)
def create_task(payload: TaskCreate, request: Request, db: Session = Depends(get_session)) -> dict:
    if not payload.title.strip():
        raise HTTPException(status_code=422, detail="title is required")
    task = _build_task(db, payload, _current_user(request))
    log_action(db, task, "created", actor=task.created_by, to_status="backlog", reason="task created via API")
    db.commit()
    return serialize_task(db, task)


@router.get("/tasks")
def list_tasks(
    db: Session = Depends(get_session),
    status: str | None = Query(None),
    capability: str | None = Query(None),
    risk_tier: str | None = Query(None),
    creator: str | None = Query(None),
    limit: int = Query(200, le=1000),
) -> list[dict]:
    q = db.query(Task)
    if status:
        q = q.filter(Task.status == status)
    if capability:
        q = q.filter(Task.agent_capability == capability)
    if risk_tier:
        q = q.filter(Task.risk_tier == risk_tier)
    if creator:
        q = q.filter(Task.created_by == creator)
    q = q.order_by(Task.created_at.desc()).limit(limit)
    return [serialize_task(db, t) for t in q.all()]


@router.get("/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_session)) -> dict:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return serialize_task(db, task)


@router.get("/tasks/{task_id}/audit")
def task_audit(task_id: str, db: Session = Depends(get_session)) -> list[dict]:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return [
        {
            "id": a.id,
            "ts": _iso(a.ts),
            "actor": a.actor,
            "action": a.action,
            "from_status": a.from_status,
            "to_status": a.to_status,
            "reason": a.reason,
        }
        for a in task.audits
    ]


@router.post("/tasks/{task_id}/review")
async def review_task(
    task_id: str,
    payload: ReviewRequest,
    request: Request,
    db: Session = Depends(get_session),
) -> dict:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task.status != "needs_review":
        raise HTTPException(status_code=409, detail=f"task is {task.status!r}, not needs_review")
    user = _current_user(request)
    try:
        if payload.action == "approve":
            if task.plan_status == "awaiting_approval":
                await orchestrator.review_approve_plan(db, task, payload.note, user)
            else:
                await orchestrator.review_approve(db, task, payload.note, user)
        elif payload.action == "approve_plan":
            await orchestrator.review_approve_plan(db, task, payload.note, user)
        elif payload.action == "retry":
            await orchestrator.review_retry(db, task, payload.note, user)
        else:
            await orchestrator.review_reject(db, task, payload.note, user)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    db.refresh(task)
    return serialize_task(db, task)


@router.post("/tasks/{task_id}/approve_execution")
def approve_execution(
    task_id: str,
    payload: NoteRequest | None = None,
    request: Request = None,  # type: ignore[assignment]  # injected by FastAPI
    db: Session = Depends(get_session),
) -> dict:
    """Human gate: a task starts execution only after approval from backlog."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task.status != "backlog":
        raise HTTPException(status_code=409, detail=f"task is {task.status!r}; only backlog tasks can be approved for execution")
    deps = task.deps(db)
    unfinished = [d.id for d in deps if d.status != "done"]
    if unfinished:
        raise HTTPException(
            status_code=409,
            detail=f"dependencies not complete: {unfinished} — approve after they finish",
        )
    user = _current_user(request)
    note = (payload.note if payload else "").strip()
    transition(db, task, "queued", actor=user, reason=f"approved for execution: {note}".strip())
    log_action(db, task, "approved_for_execution", actor=user, to_status="queued", reason=note or "human approved start")
    db.commit()
    return serialize_task(db, task)


@router.post("/tasks/{task_id}/unblock")
def unblock_task(task_id: str, request: Request, db: Session = Depends(get_session)) -> dict:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task.status != "blocked":
        raise HTTPException(status_code=409, detail="task is not blocked")
    transition(db, task, "queued", actor=_current_user(request), reason="manually unblocked")
    db.commit()
    return serialize_task(db, task)


@router.get("/reviews")
def review_queue(db: Session = Depends(get_session)) -> list[dict]:
    tasks = (
        db.query(Task)
        .filter(Task.status == "needs_review")
        .order_by(Task.updated_at.desc())
        .all()
    )
    return [serialize_task(db, t) for t in tasks]


@router.get("/capabilities")
def capabilities() -> list[dict]:
    adapter = get_adapter(settings.adapter)
    if adapter.name == "simulated":
        pool = ["default", "sim", "research", "build"]
    elif adapter.name == "opencode":
        pool = ["default", "build", "research"]
    else:
        pool = ["default"]
    return [{"name": c, "adapter": adapter.name} for c in pool]


@router.get("/harnesses")
async def harnesses() -> dict:
    """Live harness list from the Omnigent server.

    harness is the stable per-task routing key (agent ids/names can change).
    The agent_id for a task's harness is re-resolved against this list at every
    submit, so the ids here are informational for the UI picker only.
    """
    headers = (
        {"Authorization": f"Bearer {settings.omnigent_api_key}"}
        if settings.omnigent_api_key
        else {}
    )
    rows: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{settings.omnigent_api_url}/v1/agents", headers=headers)
        if resp.status_code < 400:
            data = resp.json()
            rows = data if isinstance(data, list) else data.get("data", data.get("agents", []))
    except Exception:  # noqa: BLE001
        rows = []

    grouped: dict[str, list[dict]] = {}
    for a in rows:
        harness = str(a.get("harness") or "").strip()
        if not harness:
            continue
        grouped.setdefault(harness, []).append(
            {"id": a.get("id"), "name": a.get("name")}
        )
    return {
        "harnesses": [
            {"name": h, "agents": grouped[h]}
            for h in sorted(grouped)
        ],
        "default": settings.omnigent_default_harness,
        "adapter": settings.adapter,
        "source": "live" if rows else "unavailable",
    }


@router.get("/compassx/apps")
async def compassx_apps() -> dict:
    """CompassX applications (populates the per-task app picker).

    Execution of a task bound to one of these apps spins up the app's remote
    dev host first, verifies it is online on the Omnigent server, then runs the
    agent session on that host.
    """
    try:
        apps = await compassx.list_apps()
    except Exception as exc:  # noqa: BLE001 - surface reachability to the UI
        return {"apps": [], "error": str(exc), "configured": bool(settings.compassx_api_token)}
    return {"apps": apps, "error": None, "configured": bool(settings.compassx_api_token)}


@router.get("/compassx/apps/{app_id}/dev/workspaces")
async def compassx_dev_workspaces(app_id: str) -> dict:
    """Existing dev workspaces for an app (used to resume work instead of a fresh clone)."""
    try:
        workspaces = await compassx.list_dev_workspaces(app_id)
    except Exception as exc:  # noqa: BLE001
        return {"workspaces": [], "error": str(exc)}
    return {"workspaces": workspaces, "error": None}


@router.get("/compassx/apps/{app_id}/dev/status")
async def compassx_dev_status(app_id: str) -> dict:
    """Health of the app's dev sandbox + Omnigent host connection."""
    try:
        status = await compassx.dev_status(app_id)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return {"dev": status}


@router.post("/compassx/apps/{app_id}/dev/stop")
async def compassx_dev_stop(app_id: str) -> dict:
    """Stop the app's dev sandbox (frees cluster compute)."""
    try:
        result = await compassx.dev_stop(app_id)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return {"dev": result}


@router.post("/parse")
def parse_intent(payload: ParseRequest) -> dict:
    """Conversational task creation (heuristic stand-in — wire an LLM here for Phase 3)."""
    text = payload.text.strip()
    lowered = text.lower()
    title = text.splitlines()[0].strip().rstrip(".")[:120] if text else "Untitled task"

    if any(k in lowered for k in ["urgent", "asap", "now", "immediately"]):
        priority = "urgent"
    elif any(k in lowered for k in ["high", "critical", "important"]):
        priority = "high"
    elif any(k in lowered for k in ["low", "routine", "whenever"]):
        priority = "low"
    else:
        priority = "normal"

    if any(k in lowered for k in ["high risk", "risky", "approval", "sign-off", "production", "prod", "security"]):
        risk_tier = "high"
    elif any(k in lowered for k in ["low risk", "cosmetic", "documentation", "docs"]):
        risk_tier = "low"
    else:
        risk_tier = "medium"

    if any(k in lowered for k in ["json", "schema", "validate"]):
        criteria = [
            {
                "description": "Output is valid JSON with the expected keys",
                "check_type": "schema_check",
                "check_config": {"required_keys": ["status"]},
            }
        ]
    else:
        criteria = [
            {
                "description": "Agent output indicates success",
                "check_type": "output_match",
                "check_config": {"pattern": "success"},
            }
        ]
    if risk_tier == "high":
        criteria.append(
            {
                "description": "Human sign-off on the result",
                "check_type": "human_approval",
                "check_config": {},
            }
        )

    plan_required = any(k in lowered for k in ["plan first", "plan it", "plan then", "approach proposes", "propose an approach", "plan required", "with a plan"])

    ws = None
    m = re.search(r"(?:workspace|repo)\s*[:=]\s*(\S+)", text, re.IGNORECASE)
    if m:
        ws = m.group(1).strip("`\"'")
    else:
        m = re.search(r"\b(?:in|from|under)\s+(/[^\s,;.]+)", text)
        if m:
            ws = m.group(1)

    harness = None
    m = re.search(r"\bharness\s*[:=]\s*([A-Za-z0-9_-]+)", text, re.IGNORECASE)
    if m:
        harness = m.group(1).strip().lower()

    compassx_app_id = None
    m = re.search(r"\bapp\s*[:=]\s*(app_[A-Za-z0-9_-]+)", text, re.IGNORECASE)
    if m:
        compassx_app_id = m.group(1).strip()

    return {
        "parsed": {
            "title": title,
            "intent": text,
            "priority": priority,
            "risk_tier": risk_tier,
            "agent_capability": "default",
            "plan_required": plan_required,
            "workspace": ws,
            "harness": harness,
            "compassx_app_id": compassx_app_id,
            "criteria": criteria,
        },
        "confidence": 0.6,
        "note": "Parsed by heuristics (LLM parsing not wired up yet). Review before submitting.",
    }


@router.get("/metrics")
def metrics(db: Session = Depends(get_session)) -> dict:
    counts: dict[str, int] = {s: db.query(Task).filter(Task.status == s).count() for s in [
        "backlog", "queued", "executing", "verifying", "needs_review", "done", "rejected", "blocked"
    ]}
    escalations = db.query(AuditLog).filter(AuditLog.action == "escalation").count()
    attempts = db.query(Attempt).filter(Attempt.verification_result != None).all()  # noqa: E711
    avg_attempts = (
        round(sum(a.attempt_number for a in attempts) / len(attempts), 2) if attempts else None
    )
    capability_fail = {}
    for t in db.query(Task).all():
        fails = sum(1 for a in t.attempts if a.verification_result == "fail")
        if fails:
            capability_fail[t.agent_capability] = capability_fail.get(t.agent_capability, 0) + 1
    return {
        "total": sum(counts.values()),
        "by_status": counts,
        "escalation_count": escalations,
        "avg_attempts": avg_attempts,
        "capability_failures": capability_fail,
    }


@router.get("/stream")
async def stream_events() -> StreamingResponse:
    return StreamingResponse(
        bus.iterator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/demo/seed")
def seed_demo(db: Session = Depends(get_session)) -> dict:
    apps_enabled = bool((settings.compassx_api_token or "").strip())
    samples = [
        {
            "title": "Add plaid support to the checkout flow",
            "intent": "Integrate plaid into checkout so users can pay from a connected bank account. Plan first, then implement in a branch and open a PR.",
            "priority": "high",
            "risk_tier": "medium",
            "plan_required": True,
            "workspace": "/workspaces/app-59f99ff8a7854a50/ws_945bbda579d44d4d",
            "context": [
                {"type": "link", "ref": "https://github.com/compassx-platform/agent_boards", "description": "repo"},
            ],
        },
        {
            "title": "Bump checkout UI copy for v0.3",
            "intent": "Update the checkout page copy and empty-state text on the Agent Boards app deployed in the CompassX dev sandbox.",
            "priority": "normal",
            "risk_tier": "low",
            "compassx_app_id": "app_59f99ff8a7854a50" if apps_enabled else None,
            "compassx_app_name": "Agent Boards" if apps_enabled else None,
        },
        {
            "title": "Write release notes for v0.2",
            "intent": "Draft release notes summarizing the new board and review features.",
            "priority": "low",
            "risk_tier": "low",
        },
        {
            "title": "Compile weekly metrics report",
            "intent": "Build a summary of queue depth and escalation rate for the last 7 days.",
            "priority": "normal",
            "risk_tier": "medium",
            "criteria": [
                {
                    "description": "Report is valid JSON with a status key",
                    "check_type": "schema_check",
                    "check_config": {"required_keys": ["status"]},
                },
            ],
        },
        {
            "title": "Apply index migration to production",
            "intent": "Apply the pending index migration to the production database (fail_once).",
            "priority": "urgent",
            "risk_tier": "high",
            "criteria": [
                {
                    "description": "Migration applied successfully",
                    "check_type": "output_match",
                    "check_config": {"pattern": "success"},
                },
                {
                    "description": "Human sign-off before closing",
                    "check_type": "human_approval",
                    "check_config": {},
                },
            ],
        },
        {
            "title": "Update CI config to use Node 22",
            "intent": "Bump the CI build image to Node 22 and run the test suite.",
            "priority": "normal",
            "risk_tier": "low",
            "criteria": [
                {
                    "description": "Test suite passes",
                    "check_type": "automated_test",
                    "check_config": {"command": "grep -q success artifact.txt"},
                },
            ],
        },
        {
            "title": "Refresh staging dataset copy",
            "intent": "Refresh the staging dataset from the nightly export.",
            "priority": "high",
            "risk_tier": "medium",
        },
        {
            "title": "Investigate flaky e2e test",
            "intent": "Diagnose why the checkout e2e test flakes and propose a fix.",
            "priority": "high",
            "risk_tier": "medium",
            "criteria": [
                {
                    "description": "Root-cause written into output",
                    "check_type": "output_match",
                    "check_config": {"pattern": "success"},
                },
            ],
        },
    ]
    created: list[str] = []
    for s in samples:
        s_copy = dict(s)
        criteria = [CriterionIn(**c) for c in s_copy.pop("criteria", [])]
        task = _build_task(db, TaskCreate(**s_copy, criteria=criteria), settings.default_user)
        created.append(task.id)
    return {"created": len(created), "task_ids": created}