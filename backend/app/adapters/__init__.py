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
    session: dict | None = None  # {provider, session_id, link} when known


@dataclass
class ExecutionResult:
    output: str = ""
    tools_used: list[str] = field(default_factory=list)
    logs_ref: str = ""
    success: bool = True
    plan: str = ""
    pr_url: str = ""
    session_id: str = ""
    provider: str = ""
    session_link: str = ""


class AgentAdapter(abc.ABC):
    """Pluggable adapter between the orchestrator and an agent backend."""

    name: str = "base"

    @abc.abstractmethod
    def supports_capability(self, capability: str) -> bool: ...

    def is_planner(self) -> bool:
        """Whether this adapter can produce an implementation plan (phase=plan)."""
        return True

    def needs_provisioning(self, task: Task) -> bool:
        """Whether the task must pass through the host_provisioning stage
        (create the agent session / bring the execution host to readiness)
        before its first attempt may start. Default: no provisioning stage."""
        return False

    async def provision(self, task: Task, phase: str = "execute") -> str | None:
        """Bring the execution host to readiness, possibly creating the agent
        session. Return the session/execution id to REUSE once the host is
        ready, or None while the host is still being set up — the orchestrator
        re-invokes this on its escalating timer until it is ready or the task is
        blocked. Only called for tasks where needs_provisioning() is True.
        Raise on fatal errors; readiness-agnostic conditions return None."""
        return None

    @abc.abstractmethod
    async def submit(
        self,
        task: Task,
        attempt_number: int,
        attempt_id: str,
        artifacts_dir: str,
        phase: str = "execute",
        session_id: str | None = None,
    ) -> str:
        """Start execution, return opaque execution_id. phase ∈ plan|implement|execute.

        session_id, when given (task was provisioned), must be reused instead of
        creating a new session; the prompt is dispatched to that existing session.
        """

    async def create_session(
        self,
        task: Task,
        phase: str = "execute",
        attempt_number: int | None = None,
    ) -> str:
        """Create a fresh agent session for the task (explicit user request via
        the "new session" endpoint, or first-attempt fallback when no session
        exists yet). The orchestrator persists the returned session id on the
        task and reuses it for every subsequent attempt. Adapters without
        addressable sessions may raise NotImplementedError."""
        raise NotImplementedError(f"adapter {self.name} has no addressable sessions")

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
    if name == "opencode":
        from app.adapters.opencode import OpenCodeAgent

        return OpenCodeAgent()
    raise ValueError(f"Unknown adapter: {name}")