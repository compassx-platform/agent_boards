from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
from sqlalchemy.orm import Session

from app.models import Attempt, Criterion

VERIFYING = "verifying"
PASS = "pass"
FAIL = "fail"
PARTIAL = "partial"
PENDING = "pending"


@dataclass
class VerificationResult:
    verdict: str  # pass | fail | partial | requires_review | error
    criterion_results: list[dict[str, Any]] = field(default_factory=list)
    details: str = ""
    failure_reason: str | None = None


def _load_config(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


async def _run_command(cwd: Path, command: str, timeout: int = 60) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return 1, "", "command timed out"


@dataclass
class CriterionCheck:
    requires_review: bool = False
    result: str = PENDING
    detail: str = ""
    passed: bool = False


async def check_criterion(criterion: Criterion, artifact_dir: Path) -> CriterionCheck:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = artifact_dir / "artifact.txt"
    text = artifact.read_text() if artifact.exists() else ""
    cfg = _load_config(criterion.check_config)
    check = CriterionCheck()

    if criterion.check_type == "automated_test":
        command = cfg.get("command", "true").strip()
        code, out, err = await _run_command(artifact_dir, command)
        check.result = PASS if code == 0 else FAIL
        check.passed = code == 0
        check.detail = (out + err).strip()[:2000] or "command exited 0"

    elif criterion.check_type == "schema_check":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            check.result, check.detail = FAIL, f"artifact is not valid JSON: {exc}"
            return check
        schema = cfg.get("json_schema")
        required_keys = cfg.get("required_keys")
        if schema is not None:
            try:
                jsonschema.validate(data, schema)
                check.result, check.passed = PASS, True
                check.detail = "schema validation passed"
            except jsonschema.ValidationError as exc:
                check.result, check.detail = FAIL, f"schema mismatch: {exc.message}"
        elif required_keys:
            missing = [k for k in required_keys if k not in data]
            if missing:
                check.result, check.passed = FAIL, False
                check.detail = f"missing keys: {', '.join(missing)}"
            else:
                check.result, check.passed, check.detail = PASS, True, "all required keys present"
        else:
            check.result, check.detail = FAIL, "schema_check requires json_schema or required_keys"

    elif criterion.check_type == "output_match":
        pattern = cfg.get("pattern", "success")
        if re.search(pattern, text, re.MULTILINE):
            check.result, check.passed = PASS, True
            check.detail = "pattern matched"
        else:
            check.result, check.detail = FAIL, f"pattern did not match: {pattern!r}"

    elif criterion.check_type in {"human_approval", "manual_checklist"}:
        check.requires_review = True
        check.result = PENDING
        check.detail = "Awaiting reviewer"

    else:
        check.result, check.detail = FAIL, f"unknown check_type: {criterion.check_type}"

    return check


async def verify_attempt(db: Session, attempt: Attempt, criteria: list[Criterion]) -> VerificationResult:
    """Run every criterion against the attempt artifact and aggregate a verdict."""
    artifact_dir = Path(attempt.logs_ref or "").parent if attempt.logs_ref else Path(".")
    requires_review = False
    results: list[dict[str, Any]] = []
    failed_criteria: list[str] = []

    for c in criteria:
        check = await check_criterion(c, artifact_dir)
        c.result = check.result
        c.detail = check.detail
        results.append(
            {
                "id": c.id,
                "description": c.description,
                "check_type": c.check_type,
                "passed": check.passed,
                "result": check.result,
                "detail": check.detail,
            }
        )
        if check.requires_review:
            requires_review = True
        elif not check.passed:
            failed_criteria.append(f"{c.check_type}: {c.description or 'criterion'}")

    if requires_review:
        verdict = "requires_review"
        reason = "Task includes a human-approval / manual-checklist criterion."
    elif failed_criteria:
        verdict = "fail"
        reason = "; ".join(failed_criteria) or "verification failed"
    elif results:
        verdict = "pass"
        reason = None
    else:
        verdict = "fail"
        reason = "task has no criteria"

    return VerificationResult(
        verdict=verdict,
        criterion_results=results,
        details=f"{len(results)} criterion/criteria checked",
        failure_reason=reason,
    )