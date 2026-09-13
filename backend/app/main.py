from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import seed_demo  # noqa: F401
from app.config import settings
from app.db import Base, SessionLocal, engine, ensure_columns

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_columns()
    if settings.seed_on_startup:
        db = SessionLocal()
        from app.models import Task

        try:
            if db.query(Task).count() == 0:
                seed_demo(db)
        finally:
            db.close()

    from app.orchestrator import orchestrator

    await orchestrator.start()
    yield
    await orchestrator.stop()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8080", "http://127.0.0.1:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.router import router  # noqa: E402
from app.api.payments import router as payments_router  # noqa: E402

app.include_router(router, prefix=settings.api_prefix)
app.include_router(payments_router, prefix=settings.api_prefix)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": f"{settings.app_name} API — see /docs"}