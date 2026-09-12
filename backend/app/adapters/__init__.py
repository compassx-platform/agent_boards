from __future__ import annotations

import abc
from dataclasses import dataclass, field

from app.models import Task


@dataclass
class ExecutionStatus:
    running: bool
    state: str = "running"
    detail: str = ""
    logs: str = ""


@dataclass
class ExecutionResult:
    output: str = ""
    tools_used: list[str] = field(default_factory=list)
    logs_ref: str = ""
    success: bool = True
    plan: str = ""
    pr_url: str = ""


class AgentAdapter(abc.ABC):
    """Pluggable adapter between the orchestrator and an agent backend."""

    name: str = "base"

    @abc.abstractmethod
    def supports_capability(self, capability: str) -> bool: ...

    def is_planner(self) -> bool:
        """Whether this adapter can produce an implementation plan (phase=plan)."""
        return True

    @abc.abstractmethod
    async def submit(
        self,
        task: Task,
        attempt_number: int,
        attempt_id: str,
        artifacts_dir: str,
        phase: str = "execute",
    ) -> str:
        """Start execution, return opaque execution_id. phase ∈ plan|implement|execute."""

    @abc.abstractmethod
    async def poll(self, execution_id: str) -> ExecutionStatus:
        """Return current progress of a previously submitted execution."""

    @abc.abstractmethod
    async def get_result(self, execution_id: str) -> ExecutionResult:
        """Fetch final output + tool/log references for a finished execution."""

    @abc.abstractmethod
    async def cancel(self, execution_id: str) -> bool: ...


def get_adapter(name: str) -> AgentAdapter:
    if name == "simulated":
        from app.adapters.simulated import SimulatedAgent

        return SimulatedAgent()
    if name == "omnigent":
        from app.adapters.omnigent import OmnigentAgent

        return OmnigentAgent()
    raise ValueError(f"Unknown adapter: {name}")