from pathlib import Path
from urllib.parse import quote_plus
from pydantic import AliasChoices, Field, model_validator
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
    "host_provisioning",
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

    # PostgreSQL Connection Parameters & URL
    pg_host: str = Field(
        default="",
        validation_alias=AliasChoices(
            "pg_host", "PG_HOST", "pghost", "PGHOST", "postgres_host", "POSTGRES_HOST", "TASKEXEC_PG_HOST"
        ),
    )
    pg_port: str = Field(
        default="",
        validation_alias=AliasChoices(
            "pg_port", "PG_PORT", "pgport", "PGPORT", "postgres_port", "POSTGRES_PORT", "TASKEXEC_PG_PORT"
        ),
    )
    pg_user: str = Field(
        default="",
        validation_alias=AliasChoices(
            "pg_user", "PG_USER", "pguser", "PGUSER", "postgres_user", "POSTGRES_USER", "TASKEXEC_PG_USER"
        ),
    )
    pg_password: str = Field(
        default="",
        validation_alias=AliasChoices(
            "pg_password", "PG_PASSWORD", "pgpassword", "PGPASSWORD", "postgres_password", "POSTGRES_PASSWORD", "TASKEXEC_PG_PASSWORD"
        ),
    )
    pg_database: str = Field(
        default="",
        validation_alias=AliasChoices(
            "pg_database", "PG_DATABASE", "pg_db", "PG_DB", "pgdatabase", "PGDATABASE", "postgres_db", "POSTGRES_DB", "TASKEXEC_PG_DATABASE"
        ),
    )
    database_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "database_url", "DATABASE_URL", "postgres_url", "POSTGRES_URL", "TASKEXEC_DATABASE_URL"
        ),
    )

    data_dir: Path = Field(
        default=BASE_DIR / "data",
        validation_alias=AliasChoices("data_dir", "DATA_DIR", "TASKEXEC_DATA_DIR"),
    )
    artifacts_dir: Path = Field(
        default=BASE_DIR / "data" / "artifacts",
        validation_alias=AliasChoices("artifacts_dir", "ARTIFACTS_DIR", "TASKEXEC_ARTIFACTS_DIR"),
    )

    @model_validator(mode="after")
    def assemble_database_url(self) -> "Settings":
        if self.pg_host or self.pg_user or self.pg_port or self.pg_database or self.pg_password:
            host = self.pg_host or "localhost"
            port = str(self.pg_port or "5432")
            user = quote_plus(self.pg_user or "postgres")
            password = quote_plus(self.pg_password or "")
            db = self.pg_database or "taskexec"
            auth = f"{user}:{password}@" if user or password else ""
            self.database_url = f"postgresql+psycopg2://{auth}{host}:{port}/{db}"
        elif self.database_url:
            url = self.database_url.strip()
            if url.startswith("postgres://"):
                url = "postgresql+psycopg2://" + url[len("postgres://"):]
            elif url.startswith("postgresql://"):
                url = "postgresql+psycopg2://" + url[len("postgresql://"):]
            self.database_url = url
        else:
            self.database_url = "postgresql+psycopg2://postgres:postgres@localhost:5432/taskexec"
        return self

    agent_capacity: int = 5
    # Baseline for the runtime "session status polling interval" setting (in the
    # app_settings table). Raise it to cut orchestrator polling load — no agent
    # finishes inside a second anyway; the default 10s cadence is fine.
    poll_interval_seconds: float = 10.0
    max_execution_seconds: int = 600

    # Adapter: "omnigent" (Omnigent server sessions, the default) or
    # "opencode" (real headless opencode CLI agent) / "simulated"
    # (deterministic demo backend, no real work).
    adapter: str = "omnigent"

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

    omnigent_api_url: str = "https://devstudio.135.13.180.167.nip.io"
    omnigent_api_key: str = ""

    # CompassX platform integration. Execution of a task bound to a CompassX
    # app first spins up a remote dev host via these endpoints ("dev/start"),
    # waits for it to come online, verifies it is registered with the Omnigent
    # server, and only then runs the task's agent session on that host.
    compassx_api_url: str = "https://compassx.135.13.180.167.nip.io/api/v1"
    compassx_api_token: str = ""
    # Fallback auth when no service-account token is set: the client logs in via
    # POST {root}/api/um/auth/login and caches the access_token as a Bearer.
    # Temporary hardcoded credentials — rotate / move to env-config later.
    compassx_login_email: str = "vishalgvora@gmail.com"
    compassx_login_password: str = "12345678"
    # The nip.io CompassX host serves a self-signed TLS cert; disable verification
    # by default and flip on once a proper cert is installed (or ignore for HTTPS).
    compassx_verify_tls: bool = False
    compassx_workspace_id: str = ""
    compassx_workspace_slug: str = "default"
    # Host bring-up polling when dev/start returns host_online: false.
    host_start_poll_interval_seconds: float = 2.0
    host_start_max_wait_seconds: float = 30.0
    # Dedicated host_provisioning stage (between queued and executing): before
    # any attempt runs, the orchestrator creates the Omnigent session and keeps
    # probing host readiness on an escalating timer — the first check fires
    # after first_check_seconds, and every subsequent check doubles the delay
    # (capped at max_check_seconds) until the dev host's workspace folder
    # actually exists. Provisioning is free of the attempt budget, so slow host
    # bring-up (CompassX can take minutes to materialize a fresh workspace)
    # never consumes a retry. Gives up and blocks after max_checks attempts.
    host_provisioning_first_check_seconds: float = 10.0
    host_provisioning_max_check_seconds: float = 60.0
    host_provisioning_max_checks: int = 180
    # Session binding: this host + repo dir the Omnigent agent runs in.
    omnigent_host_id: str = "97e1d6b0299b58a7b4b8a7f1eeafaaf1"
    omnigent_workspace: str = "/workspaces/app-59f99ff8a7854a50/ws_945bbda579d44d4d"
    # Per-task harness (execution engine family). This is the stable reference
    # for routing: agent ids and display names can change on the server, but the
    # harness of an agent stays put. The agent_id used at execution time is
    # resolved fresh from GET /v1/agents by filtering on the task's harness.
    # NOTE: the server has 15 harnesses; its opencode one is "opencode-native"
    # (there is no harness literally named "opencode").
    omnigent_default_harness: str = "opencode-native"
    omnigent_branch_prefix: str = "taskexec"
    # Per-phase agent mapping (ids from GET /v1/agents on the server).
    omnigent_plan_agent_id: str = "eac9e787e68ae6774d77e618031c287a"  # debby
    omnigent_implement_agent_id: str = "faa173dc95dad9c41a2c36b8fcbb9ce2"  # jcode

    robot_pr_url: str = "https://github.com/compassx-platform/agent_boards/pull/"
    simulator_min_seconds: float = 1.5
    simulator_max_seconds: float = 4.0

    # Plaid bank-account checkout. Leave the client id/secret unset to run the
    # deterministic sandbox mock so the whole flow works with zero keys.
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"  # sandbox | development | production

    default_user: str = "creator@example.com"
    seed_on_startup: bool = True
    seed_ui_task_count: int = 6

    model_config = SettingsConfigDict(env_file=".env", env_prefix="TASKEXEC_", extra="ignore")


settings = Settings()

settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.artifacts_dir.mkdir(parents=True, exist_ok=True)