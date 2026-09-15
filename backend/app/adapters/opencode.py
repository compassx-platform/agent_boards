from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

import httpx

from app.adapters import AgentAdapter, ExecutionResult, ExecutionStatus
from app.config import settings
from app.models import Task

logger = logging.getLogger("taskexec.opencode")

_PLAN_OPEN = "<<<PLAN>>>"
_PLAN_CLOSE = "<<<END_PLAN>>>"

PR_URL_RE = re.compile(
    r"https?://(?:www\.)?github\.com/[^\s)]+/pull/\d+",
    re.IGNORECASE,
)
BRANCH_RE = re.compile(r"^(?:branch|branch_name)\s*[::]\s*(\S+)", re.IGNORECASE | re.MULTILINE)
FAIL_SIGNALS = ("i could not", "i couldn't", "cannot complete", "unable to complete", "failed to")
FAIL_SIGNALS_RE = re.compile("|".join(map(re.escape, FAIL_SIGNALS)), re.IGNORECASE)


class OpenCodeAgent(AgentAdapter):
    """Headless opencode CLI agent (default model: opencode/big-pickle).

    Runs ``opencode run --auto`` in the task's workspace (processed via stdin),
    captures assistant text/tool events from ``--format json``, and — after an
    implementation attempt succeeds — opens a real pull request from the pushed
    branch via the GitHub API, returning its URL.
    """

    name = "opencode"

    def __init__(self) -> None:
        self._procs: dict[str, dict] = {}
        self._seq = 0

    @staticmethod
    def _session_id_from(line: str) -> str:
        try:
            ev = json.loads(line)
        except Exception:
            return ""
        sid = ev.get("sessionID") or (ev.get("part") or {}).get("sessionID") or ""
        return str(sid or "")

    async def _drain(self, entry: dict) -> None:
        try:
            while True:
                line = await entry["proc"].stdout.readline()
                if not line:
                    break
                entry["lines"].append(line)
        except Exception:
            pass

    def supports_capability(self, capability: str) -> bool:
        return True

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _workspace_for(task: Task) -> str:
        return (task.workspace or "").strip() or settings.opencode_workspace

    def _branch_for(self, task: Task, attempt_number: int) -> str:
        return f"{settings.opencode_branch_prefix}/{task.id[:8]}-{attempt_number}"

    def _model_flags(self) -> list[str]:
        flags = ["-m", settings.opencode_model]
        if settings.opencode_variant:
            flags += ["--variant", settings.opencode_variant]
        return flags

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
                f"You are the planning agent for TaskExec task '{task.title}'.\n\n"
                f"INTENT:\n{task.intent}\n\n"
                f"DEFINITION OF DONE (verification criteria):\n{criteria}\n\n"
                f"CONTEXT:\n{context or '(none)'}\n"
                f"WORKSPACE REPOSITORY: {ws}\n\n"
                "Produce a concise, actionable implementation plan. Do NOT modify "
                "any files yet. Wrap the plan between exactly these two markers:\n"
                f"{_PLAN_OPEN}\n<your plan>\n{_PLAN_CLOSE}\n"
                "The plan must name concrete files/changes and the verification "
                "steps that will satisfy the definition of done."
            )
        branch = self._branch_for(task, attempt_number)
        plan = (task.plan_text or "").strip()
        return (
            f"You are the implementation agent for TaskExec task '{task.title}'.\n\n"
            f"You are working inside the git repository at {ws} (the current checkout "
            "is on 'main').\n\n"
            f"INTENT:\n{task.intent}\n\n"
            f"~~ APPROVED PLAN ~~\n{plan}\n~~ END APPROVED PLAN ~~\n\n"
            f"DEFINITION OF DONE (verification criteria):\n{criteria}\n\n"
            f"CONTEXT:\n{context or '(none)'}\n\n"
            "Do this, in order:\n"
            f"1. git checkout -b {branch}\n"
            "2. Implement the approved plan exactly. Change only the files it requires.\n"
            "3. Run a quick local check that the change is correct.\n"
            f"4. git add -A && git commit -m '{task.title[:72]}'\n"
            f"5. git push -u origin {branch}\n"
            f"6. Then report the branch on its own line as: branch: {branch}\n\n"
            "A pull request will be opened from that branch automatically; you do "
            "not need to open one yourself.\n"
            "If you cannot complete the work, say so explicitly and state the reason."
        )

    @staticmethod
    def _parse_text_parts(events: list[dict]) -> tuple[str, list[str], list[str]]:
        """Collect assistant text, tool names, and error strings from JSON events."""
        text_parts: list[str] = []
        tools: list[str] = []
        errors: list[str] = []
        for ev in events:
            ev_type = ev.get("type")
            part = ev.get("part") or {}
            ptype = part.get("type") or ""
            if ev_type == "text" or ptype == "text":
                txt = (part.get("text") or "").strip()
                if txt:
                    text_parts.append(txt)
                continue
            if ptype in {"tool", "tool_call", "function-call", "function_call"}:
                name = part.get("name") or part.get("tool") or "tool"
                if name not in tools:
                    tools.append(name)
                continue
            if ptype == "reasoning":
                continue
        return "\n".join(text_parts), tools, errors

    @staticmethod
    def _repo_from(workspace: str) -> tuple[str, str] | None:
        try:
            import subprocess

            url = subprocess.run(
                ["git", "-C", workspace, "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        except Exception:
            return None
        if not url:
            return None
        url = re.sub(r"\.git$", "", url.strip())
        if url.startswith("git@github.com:"):
            url = url[len("git@github.com:"):]
        elif url.startswith("https://github.com/"):
            url = url[len("https://github.com/"):]
        elif url.startswith("http://github.com/"):
            url = url[len("http://github.com/"):]
        elif url.startswith("ssh://git@github.com/"):
            url = url[len("ssh://git@github.com/"):]
        parts = url.split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
        return None

    @staticmethod
    def _git_token() -> str:
        token = os.environ.get("GIT_TOKEN", "").strip()
        if token:
            return token
        store = Path.home() / ".git-credentials"
        with open(store, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if "://" not in line:
                    continue
                auth = line.split("://", 1)[1].split("@", 1)[0]
                if ":" in auth:
                    return auth.split(":", 1)[1]
        return ""

    async def _open_pr(self, workspace: str, branch: str, task: Task) -> str:
        token = self._git_token()
        repo = self._repo_from(workspace)
        if not repo:
            return ""
        if not token:
            logger.warning("no GIT_TOKEN available to open PR for task %s", task.id)
            return ""
        body = (
            "Automated by TaskExec (opencode agent).\n\n"
            f"Ticket: `{task.id[:8]}`\n"
            f"Title: {task.title}\n\n"
            "Definition of done:\n"
            + "\n".join(f"- {c.description}" for c in task.criteria)
        )
        payload = {
            "title": task.title,
            "head": branch,
            "base": settings.opencode_base_branch,
            "body": body,
        }
        try:
            headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"https://api.github.com/repos/{repo[0]}/{repo[1]}/pulls",
                    headers=headers,
                    json=payload,
                )
            if resp.status_code >= 400:
                # An open PR for the same head already exists? Then reuse it.
                async with httpx.AsyncClient(timeout=30) as client:
                    existing = await client.get(
                        f"https://api.github.com/repos/{repo[0]}/{repo[1]}/pulls?head={repo[0] or 'x'}:{branch}&state=open",
                        headers=headers,
                    )
                for pr in existing.json() if existing.status_code < 400 else []:
                    if pr.get("head", {}).get("ref") == branch:
                        return pr.get("html_url", "")
                logger.warning("PR open failed for task %s: %s %s", task.id, resp.status_code, resp.text[:300])
                return ""
            data = resp.json()
            return data.get("html_url", "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("PR open exception for task %s: %s", task.id, exc)
            return ""

    # ------------------------------------------------------------- interface

    async def submit(
        self,
        task: Task,
        attempt_number: int,
        attempt_id: str,
        artifacts_dir: str,
        phase: str = "execute",
        session_id: str | None = None,
    ) -> str:
        ws = self._workspace_for(task)
        workdir = Path(ws)
        if not workdir.is_dir():
            raise RuntimeError(f"workspace does not exist: {ws}")
        if phase == "implement":
            import subprocess

            chk = subprocess.run(["git", "-C", ws, "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, timeout=10)
            if chk.returncode != 0:
                raise RuntimeError(f"workspace is not a git repository: {ws}")
            out = subprocess.run(["git", "-C", ws, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
            base = settings.opencode_base_branch
            if out.startswith(settings.opencode_branch_prefix + "/"):
                # Stale taskexec branch from a previous run: reset to base first.
                subprocess.run(["git", "-C", ws, "fetch", "-q", "origin"], check=True, timeout=60)
                subprocess.run(["git", "-C", ws, "checkout", "-q", "-B", base, f"origin/{base}"], check=True, timeout=30)
                stale = subprocess.run(["git", "-C", ws, "branch", "--list", f"{settings.opencode_branch_prefix}/*"], capture_output=True, text=True, timeout=10).stdout.split()
                for b in stale:
                    subprocess.run(["git", "-C", ws, "branch", "-q", "-D", b], check=True, timeout=10)
                out = base
            if out not in {"main", "master", base}:
                raise RuntimeError(f"workspace HEAD is on '{out}', expected {base} to branch from")

        prompt = self._prompt_for(task, phase, attempt_number)
        cmd = [
            settings.opencode_bin, "run",
            *self._model_flags(),
            "--format", "json",
        ]
        if settings.opencode_auto:
            cmd.append("--auto")
        cmd += ["--dir", ws]

        env = os.environ.copy()
        env.setdefault("NO_COLOR", "1")
        env.setdefault("OPENCODE_DISABLE_AUTOUPDATE", "1")

        Path(artifacts_dir).mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=ws,
            env=env,
        )
        assert proc.stdin is not None and proc.stdout is not None, "pipe setup failed"
        proc.stdin.write(prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()

        execution_id = f"oc-{task.id[:8]}-{attempt_number}-{self._seq}"
        self._seq += 1
        entry: dict = {
            "proc": proc,
            "phase": phase,
            "task": task,
            "workspace": ws,
            "branch": self._branch_for(task, attempt_number),
            "artifacts_dir": artifacts_dir,
            "started": time.monotonic(),
            "lines": [],
            "session_id": "",
            "drain": None,
        }
        entry["drain"] = asyncio.create_task(self._drain(entry))
        self._procs[execution_id] = entry
        return execution_id

    async def poll(self, execution_id: str) -> ExecutionStatus:
        entry = self._procs.get(execution_id)
        if not entry:
            return ExecutionStatus(running=False, state="failed", detail="unknown execution")
        proc: asyncio.subprocess.Process = entry["proc"]
        if not entry["session_id"]:
            for line in (entry.get("lines") or []):
                sid = self._session_id_from(line.decode(errors="replace"))
                if sid:
                    entry["session_id"] = sid
                    break
        session = None
        if entry["session_id"]:
            session = {
                "provider": self.name,
                "session_id": entry["session_id"],
                "link": self._session_link(entry["session_id"]),
            }
        if proc.returncode is None:
            if time.monotonic() - entry["started"] > settings.max_execution_seconds:
                proc.kill()
                return ExecutionStatus(running=False, state="failed", detail="execution timeout", session=session)
            return ExecutionStatus(running=True, state="running", detail="opencode agent working…", session=session)
        state = "finished" if proc.returncode == 0 else "failed"
        return ExecutionStatus(running=False, state=state, detail=f"opencode exit {proc.returncode}", session=session)

    def _session_link(self, session_id: str) -> str:
        base = settings.opencode_session_link_base
        return (base.rstrip("/") + "/" + session_id) if base else ""

    async def get_result(self, execution_id: str) -> ExecutionResult:
        entry = self._procs.pop(execution_id, None)
        if not entry:
            return ExecutionResult(success=False, output="missing execution")
        proc: asyncio.subprocess.Process = entry["proc"]
        drain: asyncio.Task | None = entry.get("drain")
        if drain:
            try:
                await asyncio.wait_for(drain, timeout=settings.max_execution_seconds)
            except asyncio.TimeoutError:
                proc.kill()
        if proc.returncode is None:
            proc.kill()
            await drain

        raw_out = b"".join(entry.get("lines") or [])
        artifacts_dir = Path(entry["artifacts_dir"])
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        events_path = artifacts_dir / "events.jsonl"
        events_path.write_bytes(raw_out or b"")

        events: list[dict] = []
        for line in (raw_out or b"").decode(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass

        output, tools, _errors = self._parse_text_parts(events)
        exit_code = proc.returncode

        plan = ""
        if entry["phase"] == "plan":
            if _PLAN_OPEN in output and _PLAN_CLOSE in output:
                plan = output.split(_PLAN_OPEN, 1)[1].rsplit(_PLAN_CLOSE, 1)[0].strip()
            else:
                plan = output.strip()

        pr_url = ""
        m = PR_URL_RE.search(output)
        if m:
            pr_url = m.group(0)
        branch = ""
        m = BRANCH_RE.search(output)
        if m:
            branch = m.group(1)
        if not branch:
            branch = entry["branch"]

        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "artifact.txt").write_text(output or "(no assistant output)")

        # Open the PR for successful implementation attempts.
        if entry["phase"] == "implement" and not pr_url and not FAIL_SIGNALS_RE.search(output.lower()):
            pr_url = await self._open_pr(entry["workspace"], branch, entry["task"])

        fail_reason = ""
        if exit_code and exit_code != 0:
            fail_reason = f"agent process exited non-zero ({exit_code})"
        elif FAIL_SIGNALS_RE.search(output.lower()):
            fail_reason = "agent reported it could not complete the task"
        elif not output.strip():
            fail_reason = "agent produced no output"

        (artifacts_dir / "run.log").write_text(
            f"model: {settings.opencode_model}\nphase: {entry['phase']}\n"
            f"branch: {branch}\nexit: {exit_code}\n"
            f"tools: {tools}\nfailure: {fail_reason or '(none)'}\n"
            f"pr_url: {pr_url or '(none)'}\n"
        )

        if not entry["session_id"]:
            for line in (raw_out or b"").decode(errors="replace").splitlines():
                sid = self._session_id_from(line)
                if sid:
                    entry["session_id"] = sid
                    break

        return ExecutionResult(
            output=output,
            tools_used=tools,
            logs_ref=str(events_path),
            success=not fail_reason,
            plan=plan,
            pr_url=pr_url,
            session_id=entry["session_id"],
            provider=self.name,
            session_link=self._session_link(entry["session_id"]) if entry["session_id"] else "",
        )

    async def cancel(self, execution_id: str) -> bool:
        entry = self._procs.pop(execution_id, None)
        if not entry:
            return False
        entry["proc"].kill()
        return True