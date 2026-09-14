from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

import httpx

from app.compassx import CompassXClient, CompassXError, compassx
from app.config import settings
from app.models import Task, utcnow

logger = logging.getLogger("taskexec.provisioning")

# Ordered checklist the UI shows while a CompassX dev host is brought up.
# Names are stable keys; labels live in the frontend's PROVISION_STEP_LABELS.
PROVISION_STEPS = (
    "resolve_workspace",
    "start_dev",
    "wait_host_ready",
    "verify_omnigent",
    "create_session",
)


def initial_provision_steps() -> list[dict]:
    """Full pending checklist persisted when a task enters host_provisioning."""
    stamp = utcnow().isoformat()
    return [
        {"name": name, "status": "pending", "detail": "", "updated_at": stamp}
        for name in PROVISION_STEPS
    ]


StepRecord = Callable[[str, str, str], Awaitable[None]]


class HostProvisioner:
    """Spin up / reuse a remote dev host for a CompassX-bound task.

    Flow (per compassx-api-contract.txt):
      1. If the task has no compassx_app_id, execution stays on the configured
         default host (settings.omnigent_host_id) — no provisioning.
      2. Otherwise determine the target dev workspace:
         - task.compassx_workspace_id is set (redo / reuse)  -> dev/start with
           that workspace_id.
         - otherwise pre-create a NAMED workspace via POST /dev/workspaces
           (workspace name == physical folder, e.g. app-{id}/{task-slug-xxxx}),
           then dev/start with that workspace_name. Idempotent across retries /
           plan→implement via already_exists.
      3. Reuse an already-active sandbox only when it already references the
         target workspace; otherwise dev/start attaches the workspace to the
         pod. Poll dev/status every ~2s until host_online: true.
      4. Verify the dev host is actually online on the Omnigent server
         (GET /v1/hosts). Omnigent registers the pod under a host_id that
         differs from CompassX's, so the match is by app NAME (== host name);
         execution never starts on a host that Omnigent has not seen.

    The caller persists the returned {host_id, host_name, workspace,
    workspace_id, workspace_name, dev_url} back onto the task row.
    """

    def __init__(self, client: CompassXClient | None = None) -> None:
        self.client = client or compassx

    # ------------------------------------------------------------ workspace

    @staticmethod
    def workspace_name_for(task_id: str, title: str) -> str:
        """Deterministic, human-readable workspace name for a task.

        The workspace name == physical folder name (no date/hash prefixes, per
        contract). The short task id is PREFIXED so distinct tasks can never
        collide: CompassX truncates workspace ids to 32 chars, and two
        similarly-titled tasks used to land on the same truncated id (the old
        `slug-{id}` format only differs past the 32-char boundary).
        """
        raw = (title or "task").strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:48]
        if not slug:
            slug = "task"
        prefix = (task_id or "")[:8] or "task"
        return f"{prefix}-{slug}"

    @staticmethod
    def _stored_workspace_is_foreign(task) -> bool:
        """True when the task's persisted dev workspace belongs to a DIFFERENT
        task (legacy truncated-id collision adopted it);
        re-using it would ride the wrong sandbox."""
        stored_name = (task.compassx_workspace_name or "").strip()
        short_id = (task.id or "")[:8]
        if not stored_name or not short_id:
            return False
        return not (
            stored_name.startswith(f"{short_id}-")
            or stored_name.endswith(f"-{short_id}")
        )

    # -------------------------------------------------------------- omnigent

    async def _omnigent_headers(self) -> dict[str, str]:
        if settings.omnigent_api_key:
            return {"Authorization": f"Bearer {settings.omnigent_api_key}"}
        return {}

    async def _omnigent_hosts(self) -> list[dict]:
        """Fetch the host list from the Omnigent server."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{settings.omnigent_api_url}/v1/hosts",
                    headers=await self._omnigent_headers(),
                )
            if resp.status_code >= 400:
                logger.warning("omnigent /v1/hosts failed: %s", resp.status_code)
                return []
            data = resp.json()
            return data.get("hosts", []) if isinstance(data, dict) else []
        except Exception as exc:  # noqa: BLE001
            logger.warning("omnigent /v1/hosts unreachable: %s", exc)
            return []

    async def omnigent_host(self, host_id: str, host_name: str = "") -> dict | None:
        """Return the Omnigent host record for a CompassX dev host.

        The Omnigent host_id for a dev pod differs from the id CompassX reports,
        so the host is matched by NAME (which equals the app name); the
        CompassX host_id is only used as a last-resort exact match.
        """
        hosts = await self._omnigent_hosts()
        name = (host_name or "").strip().lower()
        if name:
            for h in hosts:
                if str(h.get("name") or "").strip().lower() == name:
                    return h
        for h in hosts:
            if h.get("host_id") == host_id:
                return h
        return None

    async def verify_omnigent_host(self, host_id: str, host_name: str = "") -> dict | None:
        """Confirm the host is registered & online with Omnigent.

        Returns the online Omnigent host record (its host_id may differ from the
        CompassX-reported one) or None when absent / not online.
        """
        record = await self.omnigent_host(host_id, host_name)
        if not record:
            logger.error(
                "host %s (%s) not found on the Omnigent server — refusing to execute",
                host_id, host_name,
            )
            return None
        status = str(record.get("status") or "").lower()
        if status != "online":
            logger.error(
                "host %s (%s) is %r on the Omnigent server, not online",
                record.get("host_id"), host_name, status,
            )
            return None
        return record

    # ------------------------------------------------------------- compassx

    @staticmethod
    def _status_matches_target(
        status: dict, workspace_id: str | None, workspace_name: str | None
    ) -> bool:
        """True when an already-active sandbox references the target workspace."""
        id_ = str(status.get("workspace_id") or "").strip()
        name = str(status.get("workspace_name") or "").strip()
        if workspace_id:
            return bool(id_ == workspace_id or name == workspace_id)
        if workspace_name:
            return bool(name == workspace_name or id_ == workspace_name)
        return True

    async def _dev_status_ready(self, status: dict) -> bool:
        return (
            bool(status)
            and str(status.get("status") or "").lower() == "active"
            and bool(status.get("host_id"))
            and bool(status.get("host_online"))
            and bool(status.get("omnigent_server_connected"))
        )

    async def ensure_host(self, task: Task, record: StepRecord | None = None) -> dict:
        """Return provisioned host info for the task (or the local default).

        ``record`` is an optional ``record(name, status, detail)`` callback used
        to persist a live provisioning checklist onto the task (each host
        bring-up step with its current status). Pass one when the caller wants
        the UI to show the running checklist.
        """

        async def _noop(name: str, status: str, detail: str) -> None:
            return None

        if record is None:
            record = _noop
        app_id = (task.compassx_app_id or "").strip()
        if not app_id:
            return {
                "host_id": settings.omnigent_host_id,
                "host_name": task.host_name or "",
                "workspace_id": task.compassx_workspace_id or "",
                "workspace_name": task.compassx_workspace_name or "",
                "workspace": (task.workspace or "").strip() or settings.omnigent_workspace,
                "dev_url": "",
            }
        if not self.client.enabled:
            exc = CompassXError(
                "task is bound to CompassX app "
                f"{app_id!r} but TASKEXEC_COMPASSX_API_TOKEN is not configured"
            )
            await record("resolve_workspace", "failed", str(exc))
            raise exc

        # 1) Resolve the target dev workspace. A redo task reuses its stored
        #    workspace by id; otherwise a NAMED workspace is pre-created via the
        #    contract's POST /dev/workspaces (idempotent: already_exists=true on
        #    retries / plan→implement). Workspace name == physical folder name.
        workspace_id = (task.compassx_workspace_id or "").strip() or None
        if self._stored_workspace_is_foreign(task):
            logger.warning(
                "task %s stored dev workspace %r belongs to another task; "
                "dropping it and creating a fresh workspace",
                task.id, task.compassx_workspace_name,
            )
            workspace_id = None
        workspace_name = None
        await record("resolve_workspace", "running", "resolving target dev workspace")
        if not workspace_id:
            try:
                workspace_name = self.workspace_name_for(task.id, task.title)
                created = await self.client.create_dev_workspace(app_id, workspace_name)
            except Exception as exc:
                await record("resolve_workspace", "failed", str(exc)[:200])
                raise
            created_name = str(created.get("name") or "").strip()
            already = bool(created.get("already_exists", False))
            if already and created_name and created_name != workspace_name:
                # CompassX resolved our name to a DIFFERENT workspace (truncated
                # id collision). Never silently adopt another task's sandbox.
                msg = (
                    f"workspace '{workspace_name}' resolved to existing workspace "
                    f"'{created_name}' — refusing to reuse another task's dev workspace"
                )
                await record("resolve_workspace", "failed", msg)
                raise CompassXError(msg)
            if created_name:
                workspace_name = created_name
            await record(
                "resolve_workspace", "done",
                f"workspace '{workspace_name}' " + ("already exists" if already else "created"),
            )
            logger.info(
                "workspace for app %s -> %s (already_exists=%s)",
                app_id,
                workspace_name,
                str(already).lower(),
            )
        else:
            await record("resolve_workspace", "done", f"reusing stored workspace {workspace_id}")

        # 2) Reuse an already-active sandbox only when it already references
        #    this task's workspace; otherwise (re)attach it via dev/start.
        try:
            status = await self.client.dev_status(app_id)
        except Exception:
            logger.warning("dev/status failed for app %s; proceeding to dev/start", app_id)
            status = {}

        if not (
            await self._dev_status_ready(status)
            and self._status_matches_target(status, workspace_id, workspace_name)
        ):
            await record("start_dev", "running", "attaching workspace to dev sandbox")
            try:
                started = await self.client.dev_start(
                    app_id, workspace_name=workspace_name, workspace_id=workspace_id
                )
            except Exception as exc:
                await record("start_dev", "failed", str(exc)[:200])
                raise
            await record(
                "start_dev", "done",
                f"host {started.get('host_id')} ({started.get('host_name')})",
            )
            logger.info(
                "dev/start for app %s -> host %s (%s), workspace %s (%s)",
                app_id,
                started.get("host_id"),
                started.get("host_name"),
                started.get("workspace_name") or workspace_name,
                started.get("workspace_id"),
            )
            status = started
        else:
            await record("start_dev", "done", "dev sandbox already active for this workspace")

        # 3) Poll until the container is healthy + connected to Omnigent.
        max_wait = settings.host_start_max_wait_seconds
        started_at = asyncio.get_running_loop().time()
        polls = 0
        while not await self._dev_status_ready(status):
            polls += 1
            elapsed = asyncio.get_running_loop().time() - started_at
            await record(
                "wait_host_ready", "running",
                f"waiting for dev host… {elapsed:.1f}s elapsed (poll {polls})",
            )
            if elapsed > max_wait:
                await record(
                    "wait_host_ready", "failed",
                    f"dev host did not come online within {max_wait:.0f}s",
                )
                raise CompassXError(
                    f"dev host for app {app_id} did not come online within "
                    f"{max_wait}s — last status: {status}"
                )
            await asyncio.sleep(settings.host_start_poll_interval_seconds)
            try:
                status = await self.client.dev_status(app_id)
            except Exception as exc:
                await record("wait_host_ready", "failed", f"dev/status error: {str(exc)[:160]}")
                raise
        await record(
            "wait_host_ready", "done",
            f"dev host online ({polls} poll{'s' if polls != 1 else ''})",
        )

        host_id = str(status.get("host_id") or "").strip()
        if not host_id:
            await record("wait_host_ready", "failed", "dev/status returned no host_id")
            raise CompassXError(f"dev host for app {app_id} returned no host_id")

        # 4) Verify the host is visible & online on the Omnigent server. The
        #    Omnigent host_id differs from CompassX's, so the match is by app
        #    name; use the OMNIGENT host_id/name for the rest of the flow.
        await record(
            "verify_omnigent", "running",
            f"checking host {host_id} on the Omnigent server",
        )
        host_record = await self.verify_omnigent_host(
            host_id, str(status.get("host_name") or "")
        )
        if not host_record:
            await record(
                "verify_omnigent", "failed",
                f"host {host_id} not online on the Omnigent server",
            )
            raise CompassXError(
                f"host {host_id} not online on the Omnigent server — "
                f"rejecting execution for app {app_id}"
            )
        host_id = str(host_record.get("host_id") or host_id)
        host_name = str(host_record.get("name") or status.get("host_name") or "")
        await record(
            "verify_omnigent", "done",
            f"matched Omnigent host {host_id} ({host_name})",
        )

        # Workspace folder on the dev host. Prefer the contract's
        # workspace_folder (== app-{app_id}/{workspace_name}); fall back to the
        # older folder_path, then derive from the workspace name itself.
        folder = str(
            status.get("workspace_folder") or status.get("folder_path") or ""
        ).strip()
        workspace = task.workspace or settings.omnigent_workspace
        if folder:
            workspace = "/workspaces/" + folder.strip("/")
        elif workspace_name:
            workspace = f"/workspaces/app-{app_id}/{workspace_name}"

        return {
            "host_id": host_id,
            "host_name": host_name,
            "workspace_id": str(status.get("workspace_id") or workspace_id or ""),
            "workspace_name": str(status.get("workspace_name") or workspace_name or ""),
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