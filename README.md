# TaskExec — Task Execution Platform

A standalone app where humans **define** tasks and an agent (via a pluggable
Omnigent adapter) **executes** them, with a board that reflects lifecycle state.

Backend: **FastAPI** (Python) · Frontend: **React + Vite + TypeScript**

## Lifecycle

```
backlog → queued → executing → verifying ─┬─→ done            (auto-approved)
                                          ├─→ executing       (verified fail, auto-retry w/ backoff)
                                          └─→ needs_review    (max attempts, high risk, or human criterion)
needs_review → done | executing (retry) | rejected
blocked → queued (manual unblock)
```

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
    │   ├── __init__.py     # AgentAdapter interface + factory
    │   ├── simulated.py    # local deterministic agent (dev)
    │   └── omnigent.py     # real Omnigent adapter skeleton (set TASKEXEC_ADAPTER=omnigent)
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

## API (all under `/api/v1`)

- `GET/POST /tasks`, `GET /tasks/{id}`, `GET /tasks/{id}/audit`
- `POST /tasks/{id}/review` `{action: approve|retry|reject, note}` (status must be `needs_review`)
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
| `TASKEXEC_OMNIGENT_API_URL` | (Omnigent adapter)      |
| `TASKEXEC_OMNIGENT_API_KEY` | (Omnigent adapter)      |
| `TASKEXEC_DATABASE_URL`     | `sqlite:////root/.taskexec/taskexec.db` |
| `TASKEXEC_AGENT_CAPACITY`   | `5`                     |

Note: the default SQLite DB lives under `/root/.taskexec` because the
`/workspaces` mount in this environment is CIFS/SMB where SQLite file-locking is
unreliable. Point `TASKEXEC_DATABASE_URL` at Postgres for production.

## Swapping the agent

Implement `AgentAdapter` (`submit` / `poll` / `get_result` / `cancel`) in
`backend/app/adapters/` and set `TASKEXEC_ADAPTER=<name>`.
`backend/app/adapters/omnigent.py` is a ready skeleton for the real Omnigent API.