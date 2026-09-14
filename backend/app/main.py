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

import asyncio
import httpx
import websockets
from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.api.router import router
from app.api.payments import router as payments_router

app.include_router(router, prefix=settings.api_prefix)
app.include_router(payments_router, prefix=settings.api_prefix)


def _get_upstream_ws_url(path: str, query: str = "") -> str:
    base_url = settings.omnigent_api_url.rstrip("/")
    if base_url.startswith("https://"):
        ws_base = "wss://" + base_url[8:]
    elif base_url.startswith("http://"):
        ws_base = "ws://" + base_url[7:]
    else:
        ws_base = f"ws://{base_url}"
    url = f"{ws_base}/{path.lstrip('/')}"
    if query:
        url += f"?{query}"
    return url


@app.websocket("/v1/{path:path}")
async def proxy_omnigent_v1_ws(websocket: WebSocket, path: str):
    """Transparent bidirectional WebSocket proxy for /v1 to Omnigent Server (terminals, updates, etc.)."""
    await websocket.accept()
    query = websocket.scope.get("query_string", b"").decode("utf-8")
    target_url = _get_upstream_ws_url(f"v1/{path}", query)

    forward_headers = {}
    if settings.omnigent_api_key:
        forward_headers["authorization"] = f"Bearer {settings.omnigent_api_key}"
    for header_name in ("cookie", "x-forwarded-for", "x-forwarded-proto", "x-forwarded-email", "x-forwarded-user", "user-agent", "authorization"):
        val = websocket.headers.get(header_name)
        if val and header_name not in forward_headers:
            forward_headers[header_name] = val

    raw_proto = websocket.headers.get("sec-websocket-protocol")
    subprotocols = [p.strip() for p in raw_proto.split(",") if p.strip()] if raw_proto else None

    try:
        async with websockets.connect(
            target_url,
            additional_headers=forward_headers,
            subprotocols=subprotocols,
            max_size=None,
            ping_interval=None,
        ) as upstream_ws:

            async def client_to_upstream():
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg["type"] == "websocket.receive":
                            if "text" in msg and msg["text"] is not None:
                                await upstream_ws.send(msg["text"])
                            elif "bytes" in msg and msg["bytes"] is not None:
                                await upstream_ws.send(msg["bytes"])
                        elif msg["type"] == "websocket.disconnect":
                            break
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as e:
                    logging.debug("WS client_to_upstream closed: %s", e)

            async def upstream_to_client():
                try:
                    async for msg in upstream_ws:
                        if isinstance(msg, str):
                            await websocket.send_text(msg)
                        else:
                            await websocket.send_bytes(msg)
                except (WebSocketDisconnect, asyncio.CancelledError, websockets.ConnectionClosed):
                    pass
                except Exception as e:
                    logging.debug("WS upstream_to_client closed: %s", e)

            t1 = asyncio.create_task(client_to_upstream())
            t2 = asyncio.create_task(upstream_to_client())
            done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
    except (WebSocketDisconnect, websockets.ConnectionClosed):
        pass
    except Exception as e:
        logging.error("WebSocket proxy error for %s: %s", target_url, e)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def proxy_omnigent_v1(request: Request, path: str):
    """Transparent proxy for /v1 to Omnigent Server."""
    url = f"{settings.omnigent_api_url}/v1/{path}"
    headers = dict(request.headers)
    headers.pop("host", None)
    if settings.omnigent_api_key:
        headers["authorization"] = f"Bearer {settings.omnigent_api_key}"
    body = await request.body()
    params = dict(request.query_params)

    # SSE streaming for /stream
    if path.endswith("/stream") or "text/event-stream" in request.headers.get("accept", ""):
        async def event_generator():
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream(request.method, url, headers=headers, params=params) as resp:
                        async for chunk in resp.aiter_raw():
                            yield chunk
            except Exception as e:
                yield f"event: error\ndata: {str(e)}\n\n".encode()

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.request(request.method, url, headers=headers, params=params, content=body)
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={k: v for k, v in resp.headers.items() if k.lower() not in {"content-length", "content-encoding", "transfer-encoding"}},
        media_type=resp.headers.get("content-type"),
    )


from pathlib import Path
from fastapi.responses import FileResponse

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@app.api_route("/assets/{path:path}", methods=["GET"])
async def proxy_omnigent_assets(path: str):
    """Serve local frontend JS/CSS assets if present, otherwise proxy from Omnigent server."""
    local_file = FRONTEND_DIST / "assets" / path
    if local_file.is_file():
        return FileResponse(local_file)

    url = f"{settings.omnigent_api_url}/assets/{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
        media_type=resp.headers.get("content-type"),
    )


@app.api_route("/favicon.svg", methods=["GET"])
async def proxy_omnigent_favicon():
    url = f"{settings.omnigent_api_url}/favicon.svg"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
    return Response(content=resp.content, status_code=resp.status_code, media_type="image/svg+xml")


@app.api_route("/apple-touch-icon.png", methods=["GET"])
async def proxy_omnigent_touch_icon():
    url = f"{settings.omnigent_api_url}/apple-touch-icon.png"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
    return Response(content=resp.content, status_code=resp.status_code, media_type="image/png")


@app.api_route("/.well-known/{path:path}", methods=["GET"])
async def proxy_omnigent_well_known(path: str):
    url = f"{settings.omnigent_api_url}/.well-known/{path}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
    return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))


@app.api_route("/omnigent-app", methods=["GET"])
@app.api_route("/omnigent-app/{path:path}", methods=["GET"])
@app.api_route("/c/{path:path}", methods=["GET"])
async def proxy_omnigent_app(path: str = ""):
    """Serve the official Omnigent SPA HTML with client router bootstrapping."""
    url = f"{settings.omnigent_api_url}/{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)

    content = resp.content
    content_type = resp.headers.get("content-type", "")
    if "text/html" in content_type:
        html_str = content.decode("utf-8")
        shim = """<script>
(function() {
  try {
    if (window.location.pathname.startsWith('/omnigent-app')) {
      var realPath = window.location.pathname.replace(/^\\/omnigent-app/, '') || '/';
      window.history.replaceState(null, '', realPath + window.location.search + window.location.hash);
    }
  } catch (e) {
    console.error('Omnigent URL bootstrap error:', e);
  }
})();
</script>"""
        if "<head>" in html_str:
            html_str = html_str.replace("<head>", "<head>" + shim, 1)
        elif "<html" in html_str:
            html_str = html_str.replace(">", ">" + shim, 1)
        content = html_str.encode("utf-8")

    return Response(
        content=content,
        status_code=resp.status_code,
        headers={"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache"},
    )


@app.get("/board")
@app.get("/new")
@app.get("/reviews")
@app.get("/sessions")
@app.get("/sessions/{path:path}")
@app.get("/settings")
@app.get("/tasks/{path:path}")
async def serve_frontend_spa_routes():
    index_file = FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {"message": f"{settings.app_name} API"}


@app.get("/")
def root():
    index_file = FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {"message": f"{settings.app_name} API — see /docs"}