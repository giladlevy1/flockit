from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from flockit_server import __version__, db
from flockit_server.queries import sweep_abandoned
from flockit_server.routers import (
    agents,
    auth,
    connect,
    environments,
    ingest,
    machines,
    people,
    search,
    sessions,
    slack,
    tasks,
    tokens,
    workflows,
)
from flockit_server.settings import get_settings

log = logging.getLogger("flockit")


async def _sweeper() -> None:
    interval = get_settings().sweep_interval_seconds
    while True:
        try:
            async with db.sessionmaker()() as session:
                n = await sweep_abandoned(session)
                if n:
                    log.info("marked %d inactive session(s) abandoned", n)
            n = await machines.fail_stuck_tasks()
            if n:
                log.info("failed %d stuck task(s)", n)
        except Exception:  # noqa: BLE001 - keep sweeping; the next run may succeed
            log.exception("maintenance sweep failed")
        await asyncio.sleep(interval)


async def _scheduler() -> None:
    """Start scheduled workflows. Checks every 20 seconds; cron has minute resolution."""
    while True:
        try:
            n = await workflows.run_due_schedules()
            if n:
                log.info("started %d scheduled workflow(s)", n)
        except Exception:  # noqa: BLE001
            log.exception("workflow scheduler failed")
        await asyncio.sleep(20)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    tasks = [asyncio.create_task(_sweeper()), asyncio.create_task(_scheduler())] if app.state.run_sweeper else []
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await db.dispose()


def create_app(run_sweeper: bool = True) -> FastAPI:
    app = FastAPI(
        title="Flockit",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.run_sweeper = run_sweeper

    for module in (auth, ingest, search, sessions, people, tokens, connect, tasks, workflows, machines, agents,
                   environments, slack):
        app.include_router(module.router)

    @app.get("/api/health", tags=["meta"])
    async def health() -> dict:
        async with db.sessionmaker()() as session:
            await session.execute(text("select 1"))
        return {"ok": True, "version": __version__}

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        # Everything the UI needs ships inside this server. The browser is told
        # so, which also blocks any accidental outbound request from the page.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
        )
        return response

    _mount_web(app)
    return app


def _mount_web(app: FastAPI) -> None:
    """Serve the built React app. Unknown non-API paths fall back to index.html."""
    dist = get_settings().web_dist.resolve()
    index = dist / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        if path:
            candidate = (dist / path).resolve()
            if candidate.is_file() and dist in candidate.parents:
                headers = {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else {}
                return FileResponse(candidate, headers=headers)
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse(
            {"detail": "The web UI is not built. Run `npm run build` in web/ or use the Docker image."},
            status_code=503,
        )


app = create_app()
