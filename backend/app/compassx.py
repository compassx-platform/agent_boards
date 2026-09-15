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
      create_workspace -> POST {base}/apps/{app_id}/dev/workspaces
                          {name, git_branch}
                          (workspace name == physical folder name;
                           idempotent via already_exists)
      dev_start        -> POST {base}/apps/{app_id}/dev/start
                          {workspace_name?} and/or {workspace_id?}
      dev_status       -> GET  {base}/apps/{app_id}/dev/status
      dev_publish      -> POST {base}/apps/{app_id}/dev/publish
                          {commit_message: str}
      dev_stop         -> POST {base}/apps/{app_id}/dev/stop

    Every request carries CompassX auth headers:
      Authorization: Bearer <token>
      X-Workspace-Id  / X-Workspace-Slug (from settings)

    Auth: a configured service-account token (TASKEXEC_COMPASSX_API_TOKEN) is
    used when present. Otherwise the client logs in via
    POST {root}/api/um/auth/login with the configured credentials
    (TASKEXEC_COMPASSX_LOGIN_EMAIL/PASSWORD) and caches the returned
    access_token for subsequent calls (re-logging in once if it gets a 401).
    """

    def __init__(
        self,
        api_url: str | None = None,
        token: str | None = None,
        workspace_id: str | None = None,
        workspace_slug: str | None = None,
        login_email: str | None = None,
        login_password: str | None = None,
    ) -> None:
        self.api_url = (api_url or settings.compassx_api_url).rstrip("/")
        self.token = (token if token is not None else settings.compassx_api_token).strip()
        self.login_email = (
            login_email if login_email is not None else settings.compassx_login_email
        ).strip()
        self.login_password = (
            login_password if login_password is not None else settings.compassx_login_password
        ).strip()
        self.workspace_id = (
            workspace_id if workspace_id is not None else settings.compassx_workspace_id
        ).strip()
        self.workspace_slug = (
            workspace_slug if workspace_slug is not None else settings.compassx_workspace_slug
        ).strip()
        # Login is scoped to the CompassX host (the API root minus "/api/v1").
        self._login_root = self.api_url.split("/api/v1", 1)[0]
        self._access_token: str | None = None
        self._verify_tls: bool = bool(settings.compassx_verify_tls)

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, verify=self._verify_tls)

    @property
    def enabled(self) -> bool:
        return bool(self.token) or (
            bool(self.login_email) and bool(self.login_password)
        )

    async def login(self) -> str:
        """Authenticate to CompassX and cache the access_token.

        Called automatically on first request when no service token is set.
        """
        if not self.login_email or not self.login_password:
            raise CompassXError(
                "CompassX not configured: set TASKEXEC_COMPASSX_API_TOKEN, or "
                "TASKEXEC_COMPASSX_LOGIN_EMAIL + TASKEXEC_COMPASSX_LOGIN_PASSWORD. "
                f"Base URL: {self.api_url}"
            )
        try:
            async with self._client(timeout=20) as client:
                resp = await client.post(
                    f"{self._login_root}/api/um/auth/login",
                    headers={"Content-Type": "application/json"},
                    json={"email": self.login_email, "password": self.login_password},
                )
        except Exception as exc:  # noqa: BLE001 - wrap transport errors
            raise CompassXError(f"CompassX login unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise CompassXError(
                f"CompassX login failed: {resp.status_code} {resp.text[:300]}"
            )
        data = resp.json()
        access_token = str(data.get("access_token") or "").strip()
        if not access_token:
            raise CompassXError("CompassX login returned no access_token")
        self._access_token = access_token
        logger.info(
            "CompassX authenticated as %s (account %s)",
            data.get("email"),
            data.get("account_id"),
        )
        return access_token

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        access = self.token or self._access_token
        if access:
            headers["Authorization"] = f"Bearer {access}"
        if self.workspace_id:
            headers["X-Workspace-Id"] = self.workspace_id
        if self.workspace_slug:
            headers["X-Workspace-Slug"] = self.workspace_slug
        return headers

    async def _request(
        self, method: str, path: str, *, json: dict | None = None, timeout: float = 30
    ) -> dict | list:
        if not self.enabled:
            raise CompassXError(
                "CompassX not configured: set TASKEXEC_COMPASSX_API_TOKEN, or "
                "TASKEXEC_COMPASSX_LOGIN_EMAIL + TASKEXEC_COMPASSX_LOGIN_PASSWORD. "
                f"Base URL: {self.api_url}"
            )
        if not self.token and not self._access_token:
            await self.login()
        request = lambda: client.request(  # noqa: E731 - shared retry callable
            method, f"{self.api_url}{path}", headers=self._headers(), json=json
        )
        try:
            async with self._client(timeout=timeout) as client:
                resp = await request()
                if (
                    resp.status_code == 401
                    and not self.token
                    and self._access_token is not None
                ):
                    logger.info("CompassX access token rejected; re-logging in")
                    await self.login()
                    resp = await request()
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

    async def create_dev_workspace(
        self, app_id: str, name: str, git_branch: str = "main"
    ) -> dict:
        """Pre-create a named dev workspace for an app.

        The workspace name and the physical folder on disk / Omnigent are
        identical. Idempotent: passing a name that already exists returns the
        existing workspace metadata with ``already_exists: true``.
        """
        data = await self._request(
            "POST",
            f"/apps/{app_id}/dev/workspaces",
            json={"name": name, "git_branch": git_branch},
        )
        return data if isinstance(data, dict) else {}

    async def dev_start(
        self,
        app_id: str,
        workspace_name: str | None = None,
        workspace_id: str | None = None,
    ) -> dict:
        payload: dict = {}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        if workspace_name:
            payload["workspace_name"] = workspace_name
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