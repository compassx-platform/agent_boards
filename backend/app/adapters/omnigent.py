from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

import httpx

from app.adapters import AgentAdapter, ExecutionResult, ExecutionStatus, ProgressCallback
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

    async def _session_request(self, task: Task, phase: str, attempt_number: int) -> dict:
        """Resolve agent/host/workspace and build the POST /v1/sessions body."""
        agent_id, agent_name = await self._agent_for(task, phase)
        harness = (task.harness or "").strip() or settings.omnigent_default_harness
        host_id = (task.host_id or "").strip() or settings.omnigent_host_id
        if (task.compassx_app_id or "").strip():
            logger.info(
                "task %s executes on CompassX host %s (%s, app %s)",
                task.id, host_id, task.host_name, task.compassx_app_id,
            )
        elif host_id != settings.omnigent_host_id:
            logger.info("task %s executes on host %s", task.id, host_id)
        body: dict = {
            "agent_id": agent_id,
            "title": f"[{harness}] {task.title} (task {task.id[:8]})",
            "host_id": host_id,
            "workspace": self._workspace_for(task),
        }
        if phase == "implement":
            body["git"] = {
                "branch_name": (
                    f"{settings.omnigent_branch_prefix}/{task.id[:8]}-{attempt_number}"
                ),
                "base_branch": "main",
            }
        return {
            "body": body,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "harness": harness,
        }

    async def _list_agents(self) -> list[dict]:
        """Live GET /v1/agents. Return [] and warn when unreachable."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{settings.omnigent_api_url}/v1/agents",
                    headers=self._headers(),
                )
            if resp.status_code >= 400:
                logger.warning("omnigent /v1/agents failed: %s %s", resp.status_code, resp.text[:200])
                return []
            data = resp.json()
            rows = data if isinstance(data, list) else data.get("data", data.get("agents", []))
            return rows or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("omnigent /v1/agents unreachable: %s", exc)
            return []

    async def _agent_for(self, task: Task, phase: str) -> tuple[str, str]:
        """Resolve a fresh agent_id for the task's harness from the live server.

        harness is the stable reference — agent ids/names can change between
        releases, so we re-query on every submit. Falls back to the configured
        plan/implement agent ids if no harness match is found.
        """
        harness = (task.harness or "").strip() or settings.omnigent_default_harness
        preferred = (
            settings.omnigent_plan_agent_id
            if phase == "plan"
            else settings.omnigent_implement_agent_id
        )
        rows = await self._list_agents()
        matches = [a for a in rows if (a.get("harness") or "") == harness]
        if matches:
            for a in matches:
                if a.get("id") == preferred:
                    return a["id"], a.get("name", "")
            first = matches[0]
            logger.info(
                "harness %r resolved to agent %s (%s) for phase=%s",
                harness, first.get("id"), first.get("name"), phase,
            )
            return first["id"], first.get("name", "")
        for a in rows:
            if a.get("id") == preferred:
                return preferred, a.get("name", "")
        logger.warning(
            "no live agent for harness %r; falling back to configured %s (%s)",
            harness, preferred, phase,
        )
        return preferred, ""

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

    async def _message_arrived(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        prompt: str,
    ) -> bool:
        """Return True if a user message with our prompt text reached the session."""
        resp = await client.get(
            f"{settings.omnigent_api_url}/v1/sessions/{session_id}/items",
            headers=self._headers(),
        )
        if resp.status_code >= 400:
            return False
        needle = (prompt or "").strip()[:120]
        if not needle:
            return False
        for item in resp.json().get("data", []):
            if item.get("type") != "message" or item.get("role") != "user":
                continue
            content = item.get("content")
            text = content if isinstance(content, str) else ""
            if isinstance(content, list):
                text = "\n".join(
                    str(b.get("text", ""))
                    for b in content
                    if isinstance(b, dict) and b.get("text")
                )
            if needle in (text or ""):
                return True
        return False

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

    def needs_provisioning(self, task: Task) -> bool:
        """CompassX-bound tasks run a remote dev host that needs to be brought
        up and confirmed ready before any attempt starts."""
        return bool((task.compassx_app_id or "").strip())

    async def provision(
        self,
        task: Task,
        phase: str = "execute",
        progress: ProgressCallback | None = None,
    ) -> str:
        """Create the execution session during host bring-up. This doubles as
        the host-readiness check: the dev host's workspace folder materializes
        asynchronously (dev/start can return before mkdir + git clone finish on
        the runner), so this delegates to create_session's bounded
        workspace-ready retry. ``progress`` is forwarded to create_session so
        every retry is surfaced live on the provisioning checklist. Once
        created, the session is reused by later attempts (the orchestrator
        guards against double-create via task.session_id).
        """
        return await self.create_session(
            task, phase, task.current_attempt, progress=progress
        )

    async def create_session(
        self,
        task: Task,
        phase: str = "execute",
        attempt_number: int | None = None,
        progress: ProgressCallback | None = None,
    ) -> str:
        """Create exactly ONE fresh Omnigent session for the task (with the
        workspace-materialization retry). Used on the first attempt and by the
        explicit "new session" endpoint; every later attempt reuses the session
        the orchestrator persists on the task. Returns the new session id.

        The Omnigent dev host's workspace folder materializes asynchronously —
        dev/start returns before the runner's mkdir + clone finish — so a
        session create that hits "workspace path does not exist" is retried
        until the deadline. ``progress`` (when given) pushes each retry's state:
        attempt number, elapsed time, and the underlying reason, so the UI can
        explain why this step is slow instead of sitting on a generic spinner.
        """
        req = await self._session_request(
            task, phase,
            attempt_number if attempt_number is not None else task.current_attempt,
        )
        body = req["body"]
        host_id = body["host_id"]
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        deadline = started_at + settings.host_start_max_wait_seconds
        last_error: str | None = None
        retries = 0
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                resp = await client.post(
                    f"{settings.omnigent_api_url}/v1/sessions",
                    headers=self._headers(),
                    json=body,
                )
                if resp.status_code < 400:
                    session_id = resp.json()["id"]
                    logger.info(
                        "task %s created session %s on host %s (phase=%s, retries=%d)",
                        task.id, session_id, host_id, phase, retries,
                    )
                    return session_id
                detail = f"{resp.status_code} {resp.text[:300]}"
                last_error = f"omnigent session create failed: {detail}"
                retryable = (
                    "workspace path does not exist" in resp.text
                    and loop.time() < deadline
                )
                if not retryable:
                    break
                retries += 1
                elapsed = loop.time() - started_at
                logger.warning(
                    "task %s workspace path not ready on host %s; retrying session create: %s",
                    task.id, host_id, resp.text[:200],
                )
                if progress is not None:
                    await progress(
                        "create_session", "running",
                        f"workspace folder not materialized on the dev host yet "
                        f"(attempt {retries}) — dev/start returns before the runner's "
                        f"mkdir + clone finish; retrying… {elapsed:.0f}s elapsed",
                    )
                if (task.compassx_app_id or "").strip():
                    try:
                        from app.compassx import compassx

                        status = await compassx.dev_status(task.compassx_app_id)
                        if str(status.get("status") or "").lower() != "active":
                            msg = (
                                f"dev sandbox status={status.get('status')}, "
                                f"host_online={status.get('host_online')} — waiting for it "
                                "to recover before the next session-create attempt"
                            )
                            logger.warning("task %s %s", task.id, msg)
                            if progress is not None:
                                await progress("create_session", "running", msg)
                    except Exception as exc:  # noqa: BLE001 — dev/status is best-effort here
                        logger.warning("task %s dev/status refresh failed: %s", task.id, exc)
                await asyncio.sleep(settings.host_start_poll_interval_seconds)
        raise RuntimeError(last_error)

    async def submit(
        self,
        task: Task,
        attempt_number: int,
        attempt_id: str,
        artifacts_dir: str,
        phase: str = "execute",
        session_id: str | None = None,
    ) -> str:
        req = await self._session_request(task, phase, attempt_number)
        agent_id = req["agent_id"]
        agent_name = req["agent_name"]
        harness = req["harness"]
        body = req["body"]
        host_id = body["host_id"]

        if session_id is None:
            session_id = await self.create_session(task, phase, attempt_number)

        prompt = self._prompt_for(task, phase, attempt_number)
        event = {
            "type": "message",
            "data": {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            dispatch_error: Exception | None = None
            for _ in range(2):
                dispatch_error = None
                try:
                    eresp = await client.post(
                        f"{settings.omnigent_api_url}/v1/sessions/{session_id}/events",
                        headers=self._headers(),
                        json=event,
                    )
                except httpx.HTTPError as exc:
                    dispatch_error = exc
                else:
                    if eresp.status_code < 400:
                        break
                    dispatch_error = RuntimeError(
                        f"omnigent message dispatch failed: {eresp.status_code} {eresp.text[:300]}"
                    )
                # A transport-level timeout/error is ambiguous: the server may
                # have accepted the event anyway. Verify delivery before
                # resending or failing, so a slow-but-successful dispatch is
                # never double-sent nor counted as a failed attempt.
                try:
                    arrived = await self._message_arrived(client, session_id, prompt)
                except Exception as exc:  # noqa: BLE001 — verification is best-effort
                    logger.warning(
                        "task %s dispatch verification failed for session %s: %s",
                        task.id, session_id, exc,
                    )
                    arrived = False
                if arrived:
                    logger.warning(
                        "task %s events dispatch to session %s reported failure (%s) "
                        "but the message was delivered; continuing",
                        task.id, session_id, dispatch_error,
                    )
                    dispatch_error = None
                    break
                await asyncio.sleep(2)
            if dispatch_error:
                raise dispatch_error

        Path(artifacts_dir).mkdir(parents=True, exist_ok=True)
        self._exec[session_id] = {
            "attempt_id": attempt_id,
            "phase": phase,
            "artifacts_dir": artifacts_dir,
            "session_id": session_id,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "harness": harness,
        }
        return session_id

    async def poll(self, execution_id: str) -> ExecutionStatus:
        entry = self._exec.get(execution_id)
        if not entry:
            return ExecutionStatus(running=False, state="finished", detail="unknown execution")
        session = {
            "provider": self.name,
            "session_id": entry["session_id"],
            "link": f"{settings.omnigent_api_url}/sessions/{entry['session_id']}",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{settings.omnigent_api_url}/v1/sessions/{entry['session_id']}",
                    headers=self._headers(),
                )
            if resp.status_code >= 400:
                return ExecutionStatus(running=False, state="failed", detail=f"poll error {resp.status_code}", session=session)
            data = resp.json()
        except Exception as exc:  # transient network issue -> keep waiting
            return ExecutionStatus(running=True, state="running", detail=str(exc), session=session)
        state = data.get("status", "running")
        if state in {"idle", "failed"}:
            return ExecutionStatus(running=False, state=state, detail=f"session {state}", session=session)
        return ExecutionStatus(running=True, state=state, detail="…", session=session)

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
            f"session: {session_id}\nphase: {entry['phase']}\n"
            f"harness: {entry.get('harness')}\nagent: {entry.get('agent_id')} ({entry.get('agent_name', '')})\n"
            f"output_len: {len(output)}\ntools: {tools}\nfailure: {fail_msg or '(none)'}\n"
        )

        return ExecutionResult(
            output=output,
            tools_used=tools,
            logs_ref=str(log_path),
            success=not fail_msg,
            plan=plan,
            pr_url=pr_url,
            session_id=session_id,
            provider=self.name,
            session_link=f"{settings.omnigent_api_url}/sessions/{session_id}",
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