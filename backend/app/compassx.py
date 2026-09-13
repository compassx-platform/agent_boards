from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger("taskexec.compassx")


class CompassXError(RuntimeError):
    """Raised when a CompassX API call fails (transport or non-2xx status)."""


class CompassXClient:
    """Client for the CompassX platform API (apps / dev sandboxes / publish).

    Contract (see compassx-api-contract.txt):
      list_apps        -> GET  {base}/apps
      list_workspaces  -> GET  {base}/apps/{app_id}/dev/workspaces
      dev_start        -> POST {base}/apps/{app_id}/dev/start
                          {workspace_id: str|null}   (null => fresh clone)
      dev_status       -> GET  {base}/apps/{app_id}/dev/status
      dev_publish      -> POST {base}/apps/{app_id}/dev/publish
                          {commit_message: str}
      dev_stop         -> POST {base}/apps/{app_id}/dev/stop

    Every request carries CompassX auth headers:
      Authorization: Bearer <token>
      X-Workspace-Id  / X-Workspace-Slug (from settings)
    """

    def __init__(
        self,
        api_url: str | None = None,
        token: str | None = None,
        workspace_id: str | None = None,
        workspace_slug: str | None = None,
    ) -> None:
        self.api_url = (api_url or settings.compassx_api_url).rstrip("/")
        self.token = (token if token is not None else settings.compassx_api_token).strip()
        self.workspace_id = (
            workspace_id if workspace_id is not None else settings.compassx_workspace_id
        ).strip()
        self.workspace_slug = (
            workspace_slug if workspace_slug is not None else settings.compassx_workspace_slug
        ).strip()

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.workspace_id:
            headers["X-Workspace-Id"] = self.workspace_id
        if self.workspace_slug:
            headers["X-Workspace-Slug"] = self.workspace_slug
        return headers

    async def _request(
        self, method: str, path: str, *, json: dict | None = None, timeout: float = 30
    ) -> dict | list:
        if not self.token:
            raise CompassXError(
                "CompassX not configured: set TASKEXEC_COMPASSX_API_TOKEN "
                f"(or provide a client token). Base URL: {self.api_url}"
            )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(
                    method, f"{self.api_url}{path}", headers=self._headers(), json=json
                )
            if resp.status_code >= 400:
                detail = (resp.text or "")[:300]
                raise CompassXError(
                    f"CompassX {method} {path} failed: {resp.status_code} {detail}"
                )
            if not resp.content:
                return {}
            data = resp.json()
            return data if isinstance(data, (dict, list)) else {}
        except CompassXError:
            raise
        except Exception as exc:  # noqa: BLE001 - wrap transport errors
            raise CompassXError(f"CompassX {method} {path} unreachable: {exc}") from exc

    async def list_apps(self) -> list[dict]:
        data = await self._request("GET", "/apps")
        return data if isinstance(data, list) else data.get("data", data.get("apps", []))

    async def list_dev_workspaces(self, app_id: str) -> list[dict]:
        data = await self._request("GET", f"/apps/{app_id}/dev/workspaces")
        return data if isinstance(data, list) else data.get("data", data.get("workspaces", []))

    async def dev_start(self, app_id: str, workspace_id: str | None = None) -> dict:
        payload: dict = {}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        data = await self._request("POST", f"/apps/{app_id}/dev/start", json=payload)
        return data if isinstance(data, dict) else {}

    async def dev_status(self, app_id: str) -> dict:
        data = await self._request("GET", f"/apps/{app_id}/dev/status")
        return data if isinstance(data, dict) else {}

    async def dev_publish(self, app_id: str, commit_message: str) -> dict:
        data = await self._request(
            "POST", f"/apps/{app_id}/dev/publish", json={"commit_message": commit_message}
        )
        return data if isinstance(data, dict) else {}

    async def dev_stop(self, app_id: str) -> dict:
        data = await self._request("POST", f"/apps/{app_id}/dev/stop", json={})
        return data if isinstance(data, dict) else {}


compassx = CompassXClient()