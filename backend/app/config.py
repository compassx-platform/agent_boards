from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

RISK_RULES: dict[str, dict] = {
    "low": {"max_attempts": 3, "auto_approve": True, "require_human_approval": False},
    "medium": {"max_attempts": 3, "auto_approve": True, "require_human_approval": False},
    "high": {"max_attempts": 2, "auto_approve": False, "require_human_approval": True},
}

STATUSES = [
    "backlog",
    "queued",
    "executing",
    "verifying",
    "needs_review",
    "done",
    "rejected",
    "blocked",
]

CHECK_TYPES = [
    "automated_test",
    "schema_check",
    "output_match",
    "human_approval",
    "manual_checklist",
]

PRIORITIES = ["low", "normal", "high", "urgent"]
RISK_TIERS = ["low", "medium", "high"]


class Settings(BaseSettings):
    app_name: str = "TaskExec"
    environment: str = "development"
    api_prefix: str = "/api/v1"

    # NOTE: the /workspaces mount is CIFS/SMB where SQLite file-locking is
    # unreliable, so structured state lives on the local overlay filesystem
    # by default. Point DATABASE_URL at Postgres for a production deployment.
    database_url: str = "sqlite:////root/.taskexec/taskexec.db"
    data_dir: Path = Path("/root/.taskexec")
    artifacts_dir: Path = Path("/root/.taskexec/artifacts")

    agent_capacity: int = 5
    poll_interval_seconds: float = 1.0
    max_execution_seconds: int = 600

    # Adapter: "opencode" (real headless opencode CLI agent, the default) or
    # "simulated" (deterministic demo backend, no real work) / "omnigent"
    # (Omnigent server sessions — needs authenticated model creds on the host).
    # The lifecycle is identical either way: a plan_required task goes
    # backlog (human approval gate) → queued → executing(plan) →
    # needs_review(plan approval) → queued → executing(implement) →
    # verifying → done/needs_review.
    adapter: str = "opencode"

    # Headless opencode CLI execution backend (real work, real PRs).
    opencode_bin: str = "opencode"
    opencode_model: str = "opencode/big-pickle"
    opencode_variant: str = ""  # e.g. "high" reasoning effort
    opencode_auto: bool = True  # --auto: auto-approve agent tool permissions
    opencode_workspace: str = "/workspaces/app-59f99ff8a7854a50/ws_945bbda579d44d4d"
    opencode_branch_prefix: str = "taskexec"
    opencode_base_branch: str = "main"
    # Deep-link base for opencode sessions captured against a task (the CLI
    # session id is appended). Leave empty to capture session ids only.
    opencode_session_link_base: str = "opencode://session/"

    omnigent_api_url: str = "http://compassx-omnigent-server.compassx.svc.cluster.local:6767"
    omnigent_api_key: str = ""
    # Session binding: this host + repo dir the Omnigent agent runs in.
    omnigent_host_id: str = "97e1d6b0299b58a7b4b8a7f1eeafaaf1"
    omnigent_workspace: str = "/workspaces/app-59f99ff8a7854a50/ws_945bbda579d44d4d"
    omnigent_branch_prefix: str = "taskexec"
    # Per-phase agent mapping (ids from GET /v1/agents on the server).
    omnigent_plan_agent_id: str = "eac9e787e68ae6774d77e618031c287a"  # debby
    omnigent_implement_agent_id: str = "faa173dc95dad9c41a2c36b8fcbb9ce2"  # jcode

    robot_pr_url: str = "https://github.com/compassx-platform/agent_boards/pull/"
    simulator_min_seconds: float = 1.5
    simulator_max_seconds: float = 4.0

    default_user: str = "creator@example.com"
    seed_on_startup: bool = True
    seed_ui_task_count: int = 6

    model_config = SettingsConfigDict(env_file=".env", env_prefix="TASKEXEC_", extra="ignore")


settings = Settings()

settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.artifacts_dir.mkdir(parents=True, exist_ok=True)