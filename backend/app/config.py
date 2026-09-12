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

    adapter: str = "simulated"
    omnigent_api_url: str = "https://api.omnigent.example.com"
    omnigent_api_key: str = ""

    simulator_min_seconds: float = 1.5
    simulator_max_seconds: float = 4.0

    default_user: str = "creator@example.com"
    seed_on_startup: bool = True
    seed_ui_task_count: int = 6

    model_config = SettingsConfigDict(env_file=".env", env_prefix="TASKEXEC_", extra="ignore")


settings = Settings()

settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.artifacts_dir.mkdir(parents=True, exist_ok=True)