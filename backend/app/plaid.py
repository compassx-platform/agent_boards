from __future__ import annotations

import uuid

from app.config import settings

PLAID_ENVS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


def _slug() -> str:
    return uuid.uuid4().hex[:16]


def _mock_account() -> dict:
    return {
        "account_id": f"account-{_slug()}",
        "name": "Mock Checking",
        "mask": "0000",
        "type": "depository",
        "subtype": "checking",
        "bank_name": "Mock Bank",
    }


class PlaidService:
    """Plaid Link flow (pay-from-bank checkout).

    Uses the real Plaid API when TASKEXEC_PLAID_CLIENT_ID / TASKEXEC_PLAID_SECRET
    are set; otherwise falls back to a deterministic sandbox mock so the checkout
    flow runs with zero external credentials. Every function returns a
    ``{"status": "success", ...}`` (or ``{"status": "error", ...}``) dict.
    """

    def __init__(self) -> None:
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(settings.plaid_client_id and settings.plaid_secret)

    def _api(self):
        if self._client is None:
            from plaid import ApiClient, Configuration
            from plaid.api import plaid_api

            host = PLAID_ENVS.get(settings.plaid_env, PLAID_ENVS["sandbox"])
            config = Configuration(
                host=host,
                api_key={
                    "clientId": settings.plaid_client_id,
                    "secret": settings.plaid_secret,
                    "plaidVersion": "2020-09-14",
                },
            )
            self._client = plaid_api.PlaidApi(ApiClient(config))
        return self._client

    def create_link_token(self, user: str = "", client_name: str = "TaskExec") -> dict:
        if not self.configured:
            return {
                "status": "success",
                "link_token": f"link-sandbox-{_slug()}",
                "environment": settings.plaid_env or "sandbox",
                "mode": "mock",
            }
        try:
            from plaid.model.country_code import CountryCode
            from plaid.model.link_token_create_request import LinkTokenCreateRequest
            from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
            from plaid.model.products import Products

            resp = self._api().link_token_create(
                LinkTokenCreateRequest(
                    client_name=client_name,
                    language="en",
                    country_codes=[CountryCode("US")],
                    user=LinkTokenCreateRequestUser(client_user_id=user or "taskexec-user"),
                    products=[Products("auth")],
                )
            )
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "detail": f"plaid link_token failed: {exc}", "mode": "live"}
        return {
            "status": "success",
            "link_token": resp.link_token,
            "environment": settings.plaid_env or "sandbox",
            "mode": "live",
        }

    def exchange_public_token(self, public_token: str) -> dict:
        if not self.configured:
            account = _mock_account()
            return {
                "status": "success",
                "access_token": f"access-sandbox-{_slug()}",
                "item_id": f"item-{_slug()}",
                "account": account,
                "mode": "mock",
            }
        try:
            from plaid.model.auth_get_request import AuthGetRequest
            from plaid.model.item_public_token_exchange_request import (
                ItemPublicTokenExchangeRequest,
            )

            api = self._api()
            exchanged = api.item_public_token_exchange(
                ItemPublicTokenExchangeRequest(public_token=public_token)
            )
            access_token = exchanged.access_token
            item_id = exchanged.item_id
            auth = api.auth_get(AuthGetRequest(access_token=access_token))
            account = auth.accounts[0] if auth.accounts else None
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "detail": f"plaid exchange failed: {exc}", "mode": "live"}
        return {
            "status": "success",
            "access_token": access_token,
            "item_id": item_id,
            "account": _account_to_dict(account),
            "mode": "live",
        }


def _account_to_dict(account) -> dict:
    if account is None:
        return _mock_account()
    name = getattr(account, "name", None) or "Bank account"
    mask = getattr(account, "mask", None)
    return {
        "account_id": getattr(account, "account_id", f"account-{_slug()}"),
        "name": name,
        "mask": mask,
        "type": getattr(account, "type", None),
        "subtype": getattr(account, "subtype", None),
        "bank_name": None,
    }


service = PlaidService()


def create_link_token(user: str = "", client_name: str = "TaskExec") -> dict:
    return service.create_link_token(user=user, client_name=client_name)


def exchange_public_token(public_token: str) -> dict:
    return service.exchange_public_token(public_token)