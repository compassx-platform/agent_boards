from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Payment, PlaidAccount, new_id
from app.plaid import create_link_token, exchange_public_token

router = APIRouter(prefix="/payments", tags=["payments"])


class LinkTokenRequest(BaseModel):
    user: str = ""
    client_name: str = "TaskExec"


class ExchangeRequest(BaseModel):
    public_token: str

    @field_validator("public_token")
    @classmethod
    def token_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("public_token is required")
        return v


class CheckoutRequest(BaseModel):
    access_token: str
    amount: float = Field(gt=0)
    currency: str = "USD"

    @field_validator("access_token")
    @classmethod
    def access_token_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("access_token is required")
        return v


@router.post("/plaid/link_token")
def plaid_link_token(payload: LinkTokenRequest | None = None) -> dict:
    payload = payload or LinkTokenRequest()
    return create_link_token(user=payload.user, client_name=payload.client_name)


@router.post("/plaid/exchange")
def plaid_exchange(payload: ExchangeRequest, db: Session = Depends(get_session)) -> dict:
    result = exchange_public_token(payload.public_token)
    if result.get("status") != "success":
        raise HTTPException(status_code=502, detail=result)
    account = result.get("account") or {}
    linked = PlaidAccount(
        plaid_account_id=account.get("account_id") or f"account-{new_id()}",
        item_id=result.get("item_id"),
        access_token=result["access_token"],
        bank_name=account.get("bank_name"),
        account_name=account.get("name"),
        account_mask=account.get("mask"),
    )
    db.add(linked)
    db.commit()
    db.refresh(linked)
    result["plaid_account_id"] = linked.id
    return result


@router.post("/checkout")
def checkout(payload: CheckoutRequest, db: Session = Depends(get_session)) -> dict:
    account = (
        db.query(PlaidAccount).filter(PlaidAccount.access_token == payload.access_token).first()
    )
    payment = Payment(
        plaid_account_id=account.id if account else None,
        amount=payload.amount,
        currency=payload.currency,
        status="paid",
        reference=f"checkout-{new_id()[:13]}",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return {
        "status": "success",
        "payment_id": payment.id,
        "payment_status": payment.status,
        "amount": payment.amount,
        "currency": payment.currency,
        "reference": payment.reference,
    }