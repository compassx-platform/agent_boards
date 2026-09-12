from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path

from app.adapters import AgentAdapter, ExecutionResult, ExecutionStatus
from app.config import settings
from app.models import Task


class SimulatedAgent(AgentAdapter):
    """Deterministic in-process agent for local development.

    - Duration scales a little with priority so you can watch the queue move.
    - If intent contains "(fail_once)" the first attempt is guaranteed to fail,
      which exercises the automatic-retry path.
    - Writes an `artifact.txt` into the attempt's artifact directory so
      `automated_test` / `schema_check` / `output_match` criteria can operate on
      real files.
    """

    name = "simulated"

    def __init__(self) -> None:
        self._runs: dict[str, tuple[str, float, bool, str, str]] = {}
        self._seq = 0

    def supports_capability(self, capability: str) -> bool:
        return capability in {"default", "sim", "research", "build"}

    async def submit(self, task: Task, attempt_number: int, attempt_id: str, artifacts_dir: str) -> str:
        self._seq += 1
        execution_id = f"sim-{int(time.time())}-{self._seq}"
        duration = random.uniform(settings.simulator_min_seconds, settings.simulator_max_seconds)
        priority_bonus = {"low": 0.5, "normal": 0.0, "high": -0.4, "urgent": -0.8}.get(
            task.priority, 0.0
        )
        duration = max(0.6, duration + priority_bonus)
        fail_once = "fail_once" in (task.intent or "")
        fail = fail_once and attempt_number == 0
        artifact_dir = Path(artifacts_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        self._runs[execution_id] = (attempt_id, time.monotonic() + duration, fail, task.title, str(artifact_dir))
        return execution_id

    async def poll(self, execution_id: str) -> ExecutionStatus:
        entry = self._runs.get(execution_id)
        if not entry:
            return ExecutionStatus(running=False, state="finished", detail="unknown execution_id")
        _, finish_at, _, _, _ = entry
        if time.monotonic() >= finish_at:
            return ExecutionStatus(running=False, state="finished", detail="output ready")
        return ExecutionStatus(running=True, state="running", detail="working…")

    async def get_result(self, execution_id: str) -> ExecutionResult:
        entry = self._runs.pop(execution_id, None)
        if not entry:
            return ExecutionResult(success=False, output="missing execution")
        attempt_id, _, fail, title, artifact_dir = entry
        settings.artifacts_dir.mkdir(parents=True, exist_ok=True)

        output = (
            f"[sim:{execution_id}] task '{title}'\n"
            f"intent: {title}\n"
            f"attempt: {attempt_id}\n"
        )
        if fail:
            output += "result: FAILED (simulated failure – run again)\n"
        else:
            output += "result: success\nsummary: completed\n"

        artifact_path = Path(artifact_dir) / "artifact.txt"
        artifact_path.write_text(output)

        run_log = Path(artifact_dir) / "run.log"
        run_log.write_text(
            json.dumps(
                {
                    "execution_id": execution_id,
                    "artifact": str(artifact_path),
                    "tools": ["read_context", "write_artifact"],
                },
                indent=2,
            )
        )

        return ExecutionResult(
            output=output,
            tools_used=["read_context", "reason", "write_artifact"],
            logs_ref=str(run_log),
            success=not fail,
        )

    async def cancel(self, execution_id: str) -> bool:
        return self._runs.pop(execution_id, None) is not None