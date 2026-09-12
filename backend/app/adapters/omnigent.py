from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

import httpx

from app.adapters import AgentAdapter, ExecutionResult, ExecutionStatus
from app.config import settings
from app.models import Task

logger = logging.getLogger("taskexec.omnigent")

_PLAN_OPEN = "<<<PLAN>>>"
_PLAN_CLOSE = "<<<END_PLAN>>>"

PR_URL_RE = re.compile(
    r"https?://(?:www\.)?github\.com/[^\s)]+/pull/(\d+)",
    re.IGNORECASE,
)
PR_LINE_RE = re.compile(r"^(?:pr|pr_url|pull_request)\s*[::]\s*(\S+)", re.IGNORECASE | re.MULTILINE)


class OmnigentAgent(AgentAdapter):
    """Real Omnigent integration, matching the server's sessions API contract.

    Contract (validated against a live server at ``/v1``):
      submit   -> POST /v1/sessions            (agent_id, host_id, workspace, git?)
                  then POST /v1/sessions/{id}/events
                  {type: "message", data: {role: "user",
                   content: [{type: "input_text", text: prompt}]}}
      poll     -> GET /v1/sessions/{id}        (status: running/waiting/idle/failed)
      get_result -> GET /v1/sessions/{id}/items (assistant output_text, function_call)

    Phase handling:
      phase="plan"      -> run the planning agent; result.plan holds the plan, the
                           orchestrator parks the ticket at needs_review.
      phase="implement" -> run the implementation agent in a git worktree
                           (branch `{branch_prefix}/{attempt}-{slug}`); it pushes
                           and opens a PR whose URL is harvested back onto the
                           ticket.
    """

    name = "omnigent"

    def __init__(self) -> None:
        self._exec: dict[str, dict] = {}

    def supports_capability(self, capability: str) -> bool:
        return True

    # ---------------------------------------------------------------- helpers

    def _agent_for(self, phase: str) -> str:
        if phase == "plan":
            return settings.omnigent_plan_agent_id
        if phase == "implement":
            return settings.omnigent_implement_agent_id
        return settings.omnigent_implement_agent_id

    def _workspace_for(self, task: Task) -> str:
        return (task.workspace or "").strip() or settings.omnigent_workspace

    def _headers(self) -> dict[str, str]:
        if settings.omnigent_api_key:
            return {"Authorization": f"Bearer {settings.omnigent_api_key}"}
        return {}

    def _prompt_for(self, task: Task, phase: str, attempt_number: int) -> str:
        ws = self._workspace_for(task)
        criteria = "\n".join(
            f"- [{c.check_type}] {c.description}"
            + (f"  config: {c.check_config}" if c.check_config not in ("{}", "") else "")
            for c in task.criteria
        )
        context = "\n".join(f"- {r.type}: {r.ref}" + (f" — {r.description}" if r.description else "") for r in task.context)
        if phase == "plan":
            return (
                f"You are planning agent for TaskExec task '{task.title}'.\n\n"
                f"INTENT:\n{task.intent}\n\n"
                f"DEFINITION OF DONE (verification criteria):\n{criteria}\n\n"
                f"CONTEXT:\n{context or '(none)'}\n"
                f"PRIORITY: {task.priority}  RISK TIER: {task.risk_tier}  WORKSPACE: {ws}\n\n"
                "Produce a concise, actionable implementation plan. Do NOT change "
                "any files yet. Wrap the plan between exactly these two markers:\n"
                f"{_PLAN_OPEN}\n<your plan>\n{_PLAN_CLOSE}\n"
                "The plan must name concrete files/changes and the verification "
                "steps that will satisfy the definition of done."
            )
        plan = task.plan_text or ""
        branch = (
            f"{settings.omnigent_branch_prefix}/{task.id[:8]}-{attempt_number}"
        )
        return (
            f"You are the implementation agent for TaskExec task '{task.title}' "
            f"on host workspace {ws} (the source repository the worktree is "
            f"branched from).\n\n"
            f"INTENT:\n{task.intent}\n\n"
            f"~~ APPROVED PLAN ~~\n{plan}\n"
            f"~~ END APPROVED PLAN ~~\n\n"
            f"DEFINITION OF DONE (verification criteria):\n{criteria}\n\n"
            f"CONTEXT:\n{context or '(none)'}\n\n"
            f"Work on branch '{branch}' (already created as a worktree by the "
            "session runner). Implement the approved plan, satisfy the definition "
            "of done, and when finished push the branch and open a Pull Request to "
            "the repository's default branch. In your final reply include the PR "
            "URL on its own line as: pr_url: <url>. If you cannot complete the work, "
            "say so explicitly and state the reason."
        )

    def _items_summary(self, items: list[dict]) -> tuple[str, list[str], list[str]]:
        """Return (assistant_text, tool_names, errors)."""
        text_parts: list[str] = []
        tools: list[str] = []
        errors: list[str] = []
        for item in items:
            itype = item.get("type", "")
            if itype == "function_call":
                name = item.get("name") or "tool"
                if name not in tools:
                    tools.append(name)
                continue
            if itype == "error":
                text = str(item.get("content", item.get("error", "")) or "").strip()
                if text:
                    errors.append(text[:300])
                continue
            if itype != "message":
                continue
            content = item.get("content")
            if isinstance(content, str):
                text_parts.append(content)
                continue
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") in {
                        "output_text",
                        "text",
                    }:
                        text_parts.append(str(block.get("text", "")))
        return "\n".join(text_parts), tools, errors

    # ------------------------------------------------------------- interface

    async def submit(
        self,
        task: Task,
        attempt_number: int,
        attempt_id: str,
        artifacts_dir: str,
        phase: str = "execute",
    ) -> str:
        agent_id = self._agent_for(phase)
        body: dict = {
            "agent_id": agent_id,
            "title": f"[{phase}] {task.title} (task {task.id[:8]})",
            "host_id": settings.omnigent_host_id,
            "workspace": self._workspace_for(task),
        }
        if phase == "implement":
            body["git"] = {
                "branch_name": (
                    f"{settings.omnigent_branch_prefix}/{task.id[:8]}-{attempt_number}"
                ),
                "base_branch": "main",
            }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.omnigent_api_url}/v1/sessions",
                headers=self._headers(),
                json=body,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"omnigent session create failed: {resp.status_code} {resp.text[:300]}")
            session = resp.json()
            session_id = session["id"]

            event = {
                "type": "message",
                "data": {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self._prompt_for(task, phase, attempt_number),
                        }
                    ],
                },
            }
            eresp = await client.post(
                f"{settings.omnigent_api_url}/v1/sessions/{session_id}/events",
                headers=self._headers(),
                json=event,
            )
            if eresp.status_code >= 400:
                raise RuntimeError(f"omnigent message dispatch failed: {eresp.status_code} {eresp.text[:300]}")

        Path(artifacts_dir).mkdir(parents=True, exist_ok=True)
        self._exec[session_id] = {
            "attempt_id": attempt_id,
            "phase": phase,
            "artifacts_dir": artifacts_dir,
            "session_id": session_id,
            "agent_id": agent_id,
        }
        return session_id

    async def poll(self, execution_id: str) -> ExecutionStatus:
        entry = self._exec.get(execution_id)
        if not entry:
            return ExecutionStatus(running=False, state="finished", detail="unknown execution")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{settings.omnigent_api_url}/v1/sessions/{entry['session_id']}",
                    headers=self._headers(),
                )
            if resp.status_code >= 400:
                return ExecutionStatus(running=False, state="failed", detail=f"poll error {resp.status_code}")
            data = resp.json()
        except Exception as exc:  # transient network issue -> keep waiting
            return ExecutionStatus(running=True, state="running", detail=str(exc))
        state = data.get("status", "running")
        if state in {"idle", "failed"}:
            return ExecutionStatus(running=False, state=state, detail=f"session {state}")
        return ExecutionStatus(running=True, state=state, detail="…")

    async def get_result(self, execution_id: str) -> ExecutionResult:
        entry = self._exec.pop(execution_id, None)
        if not entry:
            return ExecutionResult(success=False, output="missing execution")
        session_id = entry["session_id"]
        output = ""
        tools: list[str] = []
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                f"{settings.omnigent_api_url}/v1/sessions/{session_id}/items",
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"omnigent items fetch failed: {resp.status_code} {resp.text[:300]}")
            output, tools, errors = self._items_summary(resp.json().get("data", []))

        artifacts_dir = Path(entry["artifacts_dir"])
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "artifact.txt").write_text(output or "(no assistant output)")

        plan = ""
        if entry["phase"] == "plan":
            if _PLAN_OPEN in output and _PLAN_CLOSE in output:
                plan = output.split(_PLAN_OPEN, 1)[1].rsplit(_PLAN_CLOSE, 1)[0].strip()
            else:
                plan = output.strip()

        pr_url = ""
        m = PR_LINE_RE.search(output)
        if m:
            pr_url = m.group(1)
        else:
            m = PR_URL_RE.search(output)
            if m:
                pr_url = f"https://github.com/{m.group(0).split('github.com/')[1].split('/pull/')[0]}/pull/{m.group(1)}"

        fail_msg = ""
        if errors:
            fail_msg = " | ".join(errors)[:500]
        elif "not logged in" in output.lower() or "please run /login" in output.lower():
            fail_msg = "agent runner is not authenticated on the host"
        elif not output.strip():
            fail_msg = "agent produced no output"

        log_path = artifacts_dir / "run.log"
        log_path.write_text(
            f"session: {session_id}\nphase: {entry['phase']}\nagent: {entry['agent_id']}\n"
            f"output_len: {len(output)}\ntools: {tools}\nfailure: {fail_msg or '(none)'}\n"
        )

        return ExecutionResult(
            output=output,
            tools_used=tools,
            logs_ref=str(log_path),
            success=not fail_msg,
            plan=plan,
            pr_url=pr_url,
        )

    async def cancel(self, execution_id: str) -> bool:
        entry = self._exec.pop(execution_id, None)
        if not entry:
            return False
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{settings.omnigent_api_url}/v1/sessions/{entry['session_id']}/events",
                    headers=self._headers(),
                    json={"type": "interrupt", "data": {}},
                )
            return resp.status_code < 400
        except Exception:
            return False