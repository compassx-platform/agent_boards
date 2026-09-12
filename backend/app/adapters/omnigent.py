from __future__ import annotations

import httpx

from app.adapters import AgentAdapter, ExecutionResult, ExecutionStatus
from app.config import settings
from app.models import Task


class OmnigentAgent(AgentAdapter):
    """Real Omnigent integration adapter.

    CONTRACT (matches the spec's illustrative interface):
      submit(task) -> execution_id
      poll(execution_id) -> status
      get_result(execution_id) -> Attempt payload

    This scaffolding assumes an async execution API at ``{settings.omnigent_api_url}``
    with deploy-style endpoints. Adjust URL paths + payload shapes to the real
    Omnigent contract, set ``TASKEXEC_ADAPTER=omnigent`` and provide
    ``TASKEXEC_OMNIGENT_API_URL`` / ``TASKEXEC_OMNIGENT_API_KEY``.
    """

    name = "omnigent"

    def supports_capability(self, capability: str) -> bool:
        return True

    async def submit(self, task: Task, attempt_number: int, attempt_id: str, artifacts_dir: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.omnigent_api_url}/v1/executions",
                headers=self._headers(),
                json={
                    "task": {
                        "id": task.id,
                        "title": task.title,
                        "intent": task.intent,
                        "capability": task.agent_capability,
                    },
                    "attempt": {"number": attempt_number, "id": attempt_id},
                },
            )
            resp.raise_for_status()
            return resp.json()["execution_id"]

    async def poll(self, execution_id: str) -> ExecutionStatus:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{settings.omnigent_api_url}/v1/executions/{execution_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return ExecutionStatus(
                running=data.get("status") not in {"finished", "failed", "cancelled"},
                state=data.get("status", "running"),
                detail=data.get("detail", ""),
                logs=data.get("logs", ""),
            )

    async def get_result(self, execution_id: str) -> ExecutionResult:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                f"{settings.omnigent_api_url}/v1/executions/{execution_id}/result",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return ExecutionResult(
                output=data.get("output", ""),
                tools_used=data.get("tools_used", []),
                logs_ref=data.get("logs_ref", ""),
                success=bool(data.get("success", True)),
            )

    async def cancel(self, execution_id: str) -> bool:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{settings.omnigent_api_url}/v1/executions/{execution_id}",
                headers=self._headers(),
            )
            return resp.status_code < 400

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {settings.omnigent_api_key}"}