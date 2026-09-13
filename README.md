# TaskExec — Task Execution Platform

A standalone app where humans **define** tasks and an agent (via a pluggable
Omnigent adapter) **executes** them, with a board that reflects lifecycle state.

Backend: **FastAPI** (Python) · Frontend: **React + Vite + TypeScript**

## Lifecycle

Standard tasks:

```
backlog → queued → executing → verifying ─┬─→ done            (auto-approved)
                                          ├─→ executing       (verified fail, auto-retry w/ backoff)
                                          └─→ needs_review    (max attempts, high risk, or human criterion)
needs_review → done | executing (retry) | rejected
blocked → queued (manual unblock)
```

Plan-first tasks (`plan_required: true`) run **two agent phases** with a human gate
between them — plan first, approve it, then implement into a PR branch:

```
backlog → queued → executing(plan) → needs_review (plan_status=awaiting_approval)
                        │  approve_plan  │
                        ▼                │
                 queued → executing(implement) → verifying → done (+ pr_url)
            (plan failure ⇒ plan_status=failed, task escalates for review)
```

Review actions now include `approve_plan` (accept the agent's plan and start
implementation) in addition to `approve | retry | reject`. Plan text, phase, and
any PR URL are stored on the task and surfaced in the UI/API.

Risk gating (defaults, admin-configurable):

| Risk   | Auto-approve on pass | Max attempts | Requires human sign-off |
| ------ | -------------------- | ------------ | ----------------------- |
| low    | Yes                  | 3            | No                      |
| medium | Yes                  | 3            | Optional                |
| high   | No → `needs_review`  | 2            | Yes (enforced)          |

## Structure

```
backend/
├── main.py                 # uvicorn entrypoint: `uvicorn main:app`
└── app/
    ├── main.py             # FastAPI app, lifespan (db init + seed + orchestrator)
    ├── config.py           # pydantic-settings (TASKEXEC_* env vars)
    ├── db.py               # SQLAlchemy engine (SQLite default, Postgres-ready)
    ├── models.py           # Task, Criterion, ContextRef, Attempt, AuditLog
    ├── serialization.py    # API/event serializers
    ├── state_machine.py    # allowed transitions + audit logging
    ├── audit.py            # action log helper
    ├── events.py           # in-process pub/sub → SSE
    ├── orchestrator.py     # background worker: queue, attempts, verification, gating
    ├── verification.py     # automated_test / schema_check / output_match / human checks
    ├── adapters/
    │   ├── __init__.py     # AgentAdapter interface + factory (ExecutionResult: output/plan/pr_url)
    │   ├── simulated.py    # local deterministic agent (dev, phase-aware: plan → PR)
    │   └── omnigent.py     # real Omnigent adapter (submit/poll/get_result/cancel vs live server)
    └── api/router.py       # REST endpoints + SSE stream + demo seed
frontend/
└── src/
    ├── lib/api.ts          # types + client + SSE hook + status metadata
    ├── App.tsx             # board, new-task form (with conversational parse),
    │                       #   review queue, task detail drawer
    └── App.css
```

## Run

```bash
# Backend (:8000)
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# docs: http://localhost:8000/docs

# Frontend (:8080, dev server proxies /api → :8000)
cd frontend
npm install
npx vite --host 0.0.0.0 --port 8080 --cors
# app: http://localhost:8080
```

A demo set of tasks is seeded automatically on first start (`POST /api/v1/demo/seed`
to add more). To see the auto-retry path, put `(fail_once)` in a task's intent —
the simulated agent deliberately fails the first attempt.

## Plaid checkout

A "Pay with bank" button in the top bar runs a Plaid Link checkout so users can
pay from a connected bank account. The flow:

```
POST /api/v1/payments/plaid/link_token      → Plaid Link token
Plaid Link (user connects bank)             → public_token
POST /api/v1/payments/plaid/exchange        → access_token + linked account (stored)
POST /api/v1/payments/checkout              → records a Payment, returns status: success
```

Set `TASKEXEC_PLAID_CLIENT_ID`, `TASKEXEC_PLAID_SECRET`, and
`TASKEXEC_PLAID_ENV` (default `sandbox`) to hit the real Plaid API. When the
credentials are left unset the backend serves a **deterministic sandbox mock**
(returns a fake link/access token and a sample account), so the entire flow
works with zero external keys. Plaid Link loads in the browser from
`https://cdn.plaid.com/link/v2/stable/link-stable.min.js` (no npm dependency).

## Plan-first flow

Create a task with `plan_required: true` (the UI has a toggle; `/parse` and the
seed also detect it) and it runs the two-phase lifecycle above. The simulated
adapter produces a placeholder plan and a fake PR URL out of the box; the
Omnigent adapter runs a real planning agent, then a real coding agent that opens
a PR on `git@github.raw:compassx-platform/agent_boards`-style branches
(`taskexec/{task_id[:8]}-{attempt}`).

## API (all under `/api/v1`)

- `GET/POST /tasks`, `GET /tasks/{id}`, `GET /tasks/{id}/audit`
- `POST /tasks/{id}/review` `{action: approve_plan|approve|retry|reject, note}` (status must be `needs_review`; `approve_plan` requires plan_status `awaiting_approval`)
- `POST /tasks/{id}/unblock`
- `GET /reviews` — tasks awaiting human sign-off
- `POST /parse` — heuristic conversational task parsing (LLM plug-in point for Phase 3)
- `GET /metrics`, `GET /capabilities`
- `GET /stream` — SSE live board events
- `POST /demo/seed`

## Configuration (env)

| Var                         | Default                 |
| --------------------------- | ----------------------- |
| `TASKEXEC_ADAPTER`          | `simulated`             |
| `TASKEXEC_OMNIGENT_API_URL` | `http://…:6767`         |
| `TASKEXEC_OMNIGENT_API_KEY` | (Omnigent adapter)      |
| `TASKEXEC_OMNIGENT_HOST_ID` | (host running agents)   |
| `TASKEXEC_OMNIGENT_WORKSPACE` | (frontend workspace)  |
| `TASKEXEC_OMNIGENT_PLAN_AGENT_ID` | (planning agent)   |
| `TASKEXEC_OMNIGENT_IMPLEMENT_AGENT_ID` | (coding agent)   |
| `TASKEXEC_OMNIGENT_ROBOT_PR_URL` | `https://github.com/compassx-platform/agent_boards/pull/` |
| `TASKEXEC_DATABASE_URL`     | `sqlite:////root/.taskexec/taskexec.db` |
| `TASKEXEC_AGENT_CAPACITY`   | `5`                     |

Note: the default SQLite DB lives under `/root/.taskexec` because the
`/workspaces` mount in this environment is CIFS/SMB where SQLite file-locking is
unreliable. Point `TASKEXEC_DATABASE_URL` at Postgres for production.

## Git identity check

A pre-commit hook (`.githooks/pre-commit`) rejects commits made with a missing
or placeholder `user.name`/`user.email`. Set a real identity before committing:

```bash
git config user.name "Your Name"
git config user.email "you@example.com"
```

The hook is already wired via `core.hooksPath` in this repo; it activates on
`git commit` for anyone who clones it.

## Swapping the agent

Implement `AgentAdapter` (`submit(task, attempt, attempt_id, artifacts_dir, phase)` /
`poll` / `get_result` / `cancel`) in `backend/app/adapters/` and set
`TASKEXEC_ADAPTER=<name>`. `phase` is `"plan"`, `"implement"`, or `"execute"`;
`run_status` (`running`/`failed`/`succeeded`) drives polling, and
`ExecutionResult` carries `output`, optional `plan`, and optional `pr_url`.
`backend/app/adapters/omnigent.py` is a complete implementation against the real
Omnigent API (session create + user event + `items` harvest; plan/PR markers
`<<<PLAN>>>…<<<END_PLAN>>>` and `pr_url:`). Note: the agent harness on the target
host must be authenticated (CLI `/login`) or runs fail with
`Not logged in · Please run /login`.