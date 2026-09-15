from __future__ import annotations

import json
import logging
import math

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import AppSetting

logger = logging.getLogger("taskexec.settings")

# Canonical managed settings. Each definition carries validation + UI metadata;
# the actual value lives in the app_settings table (JSON), falling back to
# ``default`` here when unset.
SETTING_DEFS: dict[str, dict] = {
    "session_status_poll_interval_seconds": {
        "label": "Session status polling interval (seconds)",
        "type": "number",
        "min": 1,
        "max": 3600,
        "step": 1,
        "default": float(settings.poll_interval_seconds),
        "description": (
            "How often TaskExec checks each running Omnigent session for "
            "completion. Lower = quicker transition to the verification step "
            "after the agent finishes; higher = less backend polling load. "
            "Changes take effect on the next orchestrator tick."
        ),
    },
}


def _coerce(raw: str):
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return raw


def _validate(key: str, meta: dict, raw) -> object:
    typ = meta.get("type", "string")
    if typ == "number":
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a number") from exc
        if not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number")
        vmin, vmax = meta.get("min"), meta.get("max")
        if vmin is not None and value < vmin:
            raise ValueError(f"{key} must be >= {vmin}")
        if vmax is not None and value > vmax:
            raise ValueError(f"{key} must be <= {vmax}")
        return value
    if typ == "bool":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    return str(raw)


def get_settings(db: Session) -> dict[str, object]:
    """Current values for every managed setting (defaults merged with overrides)."""
    stored = {row.key: _coerce(row.value) for row in db.query(AppSetting).all()}
    out: dict[str, object] = {}
    for key, meta in SETTING_DEFS.items():
        out[key] = stored[key] if key in stored else meta["default"]
    for key, value in stored.items():
        if key not in out:
            out[key] = value
    return out


def definitions() -> dict[str, dict]:
    """UI/validator metadata for every managed setting (no ``default`` key)."""
    return {
        key: {k: value for k, value in meta.items() if k != "default"}
        for key, meta in SETTING_DEFS.items()
    }


def update_settings(db: Session, updates: dict) -> dict[str, object]:
    """Validate and persist setting overrides; returns the full current set."""
    for key, raw in (updates or {}).items():
        if key not in SETTING_DEFS:
            raise ValueError(f"unknown setting: {key}")
        value = _validate(key, SETTING_DEFS[key], raw)
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value = json.dumps(value)
        else:
            db.add(AppSetting(key=key, value=json.dumps(value)))
        logger.info("setting %s updated to %r", key, value)
    db.commit()
    return get_settings(db)


def get_poll_interval_seconds() -> float:
    """Read the live session-status polling interval from the DB (best-effort)."""
    try:
        db = SessionLocal()
        try:
            value = get_settings(db).get("session_status_poll_interval_seconds")
            return float(value)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — never let a config lookup stop the loop
        logger.warning("could not read poll interval setting: %s", exc)
        return float(settings.poll_interval_seconds)