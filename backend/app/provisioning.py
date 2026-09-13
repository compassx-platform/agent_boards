from __future__ import annotations

import asyncio
import logging

import httpx

from app.compassx import CompassXClient, CompassXError, compassx
from app.config import settings
from app.models import Task

logger = logging.getLogger("taskexec.provisioning")


class HostProvisioner:
    """Spin up / reuse a remote dev host for a CompassX-bound task.

    Flow (per compassx-api-contract.txt):
      1. If the task has no compassx_app_id, execution stays on the configured
         default host (settings.omnigent_host_id) — no provisioning.
      2. Otherwise check the existing dev sandbox (dev/status). If it is already
         active and connected, reuse it (idempotent for retries / plan→implement).
      3. Else POST dev/start {workspace_id} (reuse a prior workspace or make a
         fresh clone) and poll dev/status every ~2s until host_online: true.
      4. Verify the returned host_id is actually online on the Omnigent server
         (GET /v1/hosts) before returning — execution never starts on a host
         that Omnigent has not seen.

    The caller persists the returned {host_id, host_name, workspace, dev_url,
    workspace_id} back onto the task row.
    """

    def __init__(self, client: CompassXClient | None = None) -> None:
        self.client = client or compassx

    # -------------------------------------------------------------- omnigent

    async def _omnigent_headers(self) -> dict[str, str]:
        if settings.omnigent_api_key:
            return {"Authorization": f"Bearer {settings.omnigent_api_key}"}
        return {}

    async def omnigent_host(self, host_id: str) -> dict | None:
        """Return the host record from the Omnigent server, or None."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{settings.omnigent_api_url}/v1/hosts",
                    headers=await self._omnigent_headers(),
                )
            if resp.status_code >= 400:
                logger.warning("omnigent /v1/hosts failed: %s", resp.status_code)
                return None
            data = resp.json()
            hosts = data.get("hosts", []) if isinstance(data, dict) else []
            for h in hosts:
                if h.get("host_id") == host_id:
                    return h
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("omnigent /v1/hosts unreachable: %s", exc)
            return None

    async def verify_omnigent_host(self, host_id: str, host_name: str = "") -> bool:
        """Confirm the host is registered and online with the Omnigent server."""
        record = await self.omnigent_host(host_id)
        if not record:
            logger.error(
                "host %s (%s) not found on the Omnigent server — refusing to execute",
                host_id, host_name,
            )
            return False
        status = str(record.get("status") or "").lower()
        if status != "online":
            logger.error(
                "host %s (%s) is %r on the Omnigent server, not online",
                host_id, host_name, status,
            )
            return False
        return True

    # ------------------------------------------------------------- compassx

    async def _dev_status_ready(self, status: dict) -> bool:
        return (
            bool(status)
            and str(status.get("status") or "").lower() == "active"
            and bool(status.get("host_id"))
            and bool(status.get("host_online"))
            and bool(status.get("omnigent_server_connected"))
        )

    async def ensure_host(self, task: Task) -> dict:
        """Return provisioned host info for the task (or the local default)."""
        app_id = (task.compassx_app_id or "").strip()
        if not app_id:
            return {
                "host_id": settings.omnigent_host_id,
                "host_name": task.host_name or "",
                "workspace_id": task.compassx_workspace_id or "",
                "workspace": (task.workspace or "").strip() or settings.omnigent_workspace,
                "dev_url": "",
            }
        if not self.client.enabled:
            raise CompassXError(
                "task is bound to CompassX app "
                f"{app_id!r} but TASKEXEC_COMPASSX_API_TOKEN is not configured"
            )

        # 1) Reuse an already-active sandbox (idempotent across retries/phases).
        try:
            status = await self.client.dev_status(app_id)
        except CompassXError:
            logger.warning("dev/status failed for app %s; proceeding to dev/start", app_id)
            status = {}

        if not await self._dev_status_ready(status):
            # 2) Start (or resume) the sandbox.
            started = await self.client.dev_start(app_id, workspace_id=task.compassx_workspace_id)
            logger.info(
                "dev/start for app %s -> host %s (%s), workspace %s",
                app_id,
                started.get("host_id"),
                started.get("host_name"),
                started.get("workspace_id"),
            )
            status = started

        # 3) Poll until the container is healthy + connected to Omnigent.
        max_wait = settings.host_start_max_wait_seconds
        started_at = asyncio.get_running_loop().time()
        polls = 0
        while not await self._dev_status_ready(status):
            if asyncio.get_running_loop().time() - started_at > max_wait:
                raise CompassXError(
                    f"dev host for app {app_id} did not come online within "
                    f"{max_wait}s — last status: {status}"
                )
            await asyncio.sleep(settings.host_start_poll_interval_seconds)
            status = await self.client.dev_status(app_id)
            polls += 1
            logger.info(
                "waiting for app %s dev host (poll %d) ... %s",
                app_id,
                polls,
                {k: status.get(k) for k in ("status", "host_online", "omnigent_server_connected")},
            )

        host_id = str(status.get("host_id") or "").strip()
        if not host_id:
            raise CompassXError(f"dev host for app {app_id} returned no host_id")

        # 4) Verify the host is visible & online on the Omnigent server.
        if not await self.verify_omnigent_host(host_id, str(status.get("host_name") or "")):
            raise CompassXError(
                f"host {host_id} not online on the Omnigent server — "
                f"rejecting execution for app {app_id}"
            )

        folder_path = str(status.get("folder_path") or "").strip()
        workspace = task.workspace or settings.omnigent_workspace
        if folder_path:
            workspace = "/workspaces/" + folder_path.strip("/")

        return {
            "host_id": host_id,
            "host_name": str(status.get("host_name") or ""),
            "workspace_id": str(status.get("workspace_id") or task.compassx_workspace_id or ""),
            "workspace": workspace,
            "dev_url": str(status.get("dev_url") or ""),
            "app_identifier": str(status.get("app_identifier") or ""),
        }

    # ---------------------------------------------------------------- publish

    async def publish(self, task: Task, commit_message: str, actor: str = "system") -> dict:
        """Commit & push the agent's changes to git via CompassX dev/publish."""
        app_id = (task.compassx_app_id or "").strip()
        if not app_id:
            return {}
        result = await self.client.dev_publish(app_id, commit_message)
        logger.info("dev/publish for app %s (task %s): %s", app_id, task.id, result)
        return result

    async def stop(self, app_id: str) -> dict:
        if not app_id:
            return {}
        return await self.client.dev_stop(app_id)


provisioner = HostProvisioner()