"""AImation Actor Core — entry point and composition root (SDD §2.2).

Assembles modules using dependency injection. No module instantiates
concrete infrastructure internally (SDD §2.4). Binds to loopback only.
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aimation_actor_core.shared.config import Settings, get_settings
from aimation_actor_core.shared.errors import AImationError, ModelIntegrityError


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application (composition root)."""
    settings = settings or get_settings()

    # Per-instance session token (SDD §4.3: never hardcoded).
    if not settings.session_token or len(settings.session_token) < 16:
        settings.session_token = secrets.token_urlsafe(32)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
    )

    app.state.settings = settings
    app.state.instance_id = str(uuid.uuid4())

    # Restrictive CORS — only the Tauri origins (SDD §4.3).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost", "http://localhost"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Centralized error mapping (SDD §4.3 sanitized responses).
    @app.exception_handler(AImationError)
    async def _handle_aimation_error(request: Request, exc: AImationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": exc.code, "detail": str(exc)},
        )

    @app.exception_handler(ModelIntegrityError)
    async def _handle_integrity(request: Request, exc: ModelIntegrityError) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": exc.code, "detail": "Model integrity verification failed."},
        )

    @app.get("/health", tags=["health"], summary="Health check")
    async def health() -> dict[str, str]:
        """Return service health and loaded model status."""
        return {
            "status": "ok",
            "instance_id": app.state.instance_id,
            "models": "none",
        }

    return app


app = create_app()
