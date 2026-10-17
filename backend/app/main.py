"""FastAPI application: JSON API under /api and (optionally) the built frontend."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import admin, core, customers, team, workflow
from app.config import get_settings

log = logging.getLogger("cac")


def create_app() -> FastAPI:
    s = get_settings()
    problems = s.startup_problems()
    if problems:
        # Fail closed: refuse to start with an unsafe configuration.
        raise RuntimeError("Unsafe configuration: " + " | ".join(problems))
    if not s.auth_mode:
        log.warning("AUTH_MODE is not set: every API request will be rejected (fail closed).")

    app = FastAPI(title="JC / PM Commercial Action Centre", version="0.1.0-prototype",
                  docs_url="/api/docs" if s.app_env != "production" else None, openapi_url="/api/openapi.json")
    if s.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
                           allow_methods=["GET", "POST", "PUT", "PATCH"], allow_headers=["Authorization", "Content-Type", "X-Demo-User"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content={"error": detail})

    for r in (core.router, customers.router, workflow.router, team.router, admin.router):
        app.include_router(r, prefix="/api")

    dist = (Path(__file__).resolve().parent.parent / s.frontend_dist).resolve()
    if dist.is_dir():
        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
