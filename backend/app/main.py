import asyncio
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config.settings import settings
from app.repositories.postgres_store import ensure_seed_data, init_db
from app.workers.analytics_prewarm import run_analytics_prewarm
from app.workers.report_scheduler import run_scheduler

app = FastAPI(title="ASoC ASPM API", version="1.3.0")


def _resolve_cors_origins() -> list[str]:
    origin = str(settings.frontend_origin or "http://localhost:5173").rstrip("/")
    parsed = urlparse(origin)
    origins = {origin}
    if parsed.scheme and parsed.hostname and parsed.port:
        if parsed.hostname == "localhost":
            origins.add(
                urlunparse(parsed._replace(netloc=f"127.0.0.1:{parsed.port}"))
            )
        elif parsed.hostname == "127.0.0.1":
            origins.add(
                urlunparse(parsed._replace(netloc=f"localhost:{parsed.port}"))
            )
    return sorted(origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolve_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    ensure_seed_data()
    app.state.scheduler_stop_event = asyncio.Event()
    app.state.scheduler_task = None
    if settings.report_scheduler_enabled:
        app.state.scheduler_task = asyncio.create_task(run_scheduler(app.state.scheduler_stop_event))

    app.state.analytics_prewarm_stop_event = asyncio.Event()
    app.state.analytics_prewarm_task = None
    if settings.analytics_prewarm_enabled:
        app.state.analytics_prewarm_task = asyncio.create_task(
            run_analytics_prewarm(app.state.analytics_prewarm_stop_event)
        )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    stop_event = getattr(app.state, "scheduler_stop_event", None)
    if stop_event is not None:
        stop_event.set()
    task = getattr(app.state, "scheduler_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            app.state.scheduler_task = None

    analytics_stop_event = getattr(app.state, "analytics_prewarm_stop_event", None)
    if analytics_stop_event is not None:
        analytics_stop_event.set()
    analytics_task = getattr(app.state, "analytics_prewarm_task", None)
    if analytics_task is not None:
        analytics_task.cancel()
        try:
            await analytics_task
        except asyncio.CancelledError:
            app.state.analytics_prewarm_task = None


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")

# ---------------------------------------------------------------------------
# Frontend static file serving (production)
# ---------------------------------------------------------------------------
# Serve the React app's built output from frontend/dist/ (one level up from backend/).
# Must be mounted AFTER the API router so /api/v1/* routes take priority.
# The catch-all route returns index.html for client-side (React Router) navigation.

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
_ASSETS = _DIST / "assets"
_INDEX = _DIST / "index.html"

# Mount /assets only when the directory exists (created by `npm run build`).
# The StaticFiles mount must come BEFORE the catch-all GET route.
if _ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS)), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str) -> FileResponse:
    """Return index.html for all unmatched paths (React Router SPA support).

    If the frontend has not been built yet, returns a 503 with instructions.
    """
    if not _INDEX.exists():
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Frontend not built. "
                    "Run: cd frontend && npm install && npm run build, "
                    "then restart the backend service."
                )
            },
        )
    return FileResponse(str(_INDEX))
