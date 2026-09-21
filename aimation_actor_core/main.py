"""AImation Actor Core — entry point and composition root (SDD §2.2).

Assembles modules using dependency injection. No module instantiates
concrete infrastructure internally (SDD §2.4). Binds to loopback only.
"""

from __future__ import annotations

import secrets
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aimation_actor_core.api.routers import generate, jobs, media, nodes, pose, sessions
from aimation_actor_core.infrastructure.ai_models.autokeyframe import AutoKeyframeBackend
from aimation_actor_core.infrastructure.ai_models.detection import (
    SingleFramePoseDetectorImpl,
)
from aimation_actor_core.infrastructure.ai_models.estimators import OnnxBackend
from aimation_actor_core.infrastructure.ai_models.mib_backend import MibBackend
from aimation_actor_core.infrastructure.video.frame_provider import OpenCvFrameProvider
from aimation_actor_core.infrastructure.virtual import (
    InMemoryJobStore,
    InMemorySessionStore,
    SynchronousGraphExecutor,
    seeded_node_registry,
)
from aimation_actor_core.shared.config import Settings, get_settings
from aimation_actor_core.shared.errors import AImationError, ModelIntegrityError
from aimation_actor_core.shared.media_security import MediaPathError


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
    app.state.motion_backend = None
    if settings.motion_backend == "autokeyframe" or settings.motion_backend == "auto":
        app.state.motion_backend = AutoKeyframeBackend(
            settings.autokeyframe_root,
            settings.autokeyframe_timeout_seconds,
            Path(__file__).resolve().parents[1] / "tools" / "autokeyframe_helper.py",
        )
    elif settings.motion_backend == "mib":
        app.state.motion_backend = MibBackend(
            settings.mib_root,
            settings.autokeyframe_root,
            settings.mib_timeout_seconds,
            Path(__file__).resolve().parents[1] / "tools" / "mib_helper.py",
        )

    # Dependency injection (SDD §2.4): concrete adapters assembled here, never
    # referenced by the API layer. The node registry is seeded with the three
    # built-in nodes, and the synchronous executor is injected into the job
    # store for GRAPH_EXECUTE jobs (ADR-002).
    app.state.session_store = InMemorySessionStore()
    node_registry = seeded_node_registry(media_root=settings.media_root)
    app.state.node_registry = node_registry
    app.state.job_store = InMemoryJobStore(
        executor=SynchronousGraphExecutor(),
        registry=node_registry,
    )

    # Phase A: frame provider and pose detector (decision D1, D3).
    app.state.frame_provider = OpenCvFrameProvider(settings.media_root)
    app.state.pose_detector = SingleFramePoseDetectorImpl(
        media_root=settings.media_root, backend=OnnxBackend("models")
    )

    # Restrictive CORS — only the Tauri origins (SDD §4.3).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Frame-Count"],
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

    @app.exception_handler(MediaPathError)
    async def _handle_media_path(request: Request, exc: MediaPathError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": exc.code, "detail": str(exc)},
        )

    # Routers (all behind the instance-token auth dependency).
    app.include_router(nodes.router)
    app.include_router(sessions.router)
    app.include_router(jobs.router)
    app.include_router(media.router)
    app.include_router(pose.router)
    app.include_router(generate.router)

    @app.get("/health", tags=["health"], summary="Health check")
    async def health() -> dict[str, str]:
        """Return service health and loaded model status."""
        # Detect pose backend availability (shared by pose-2d and pose-3d).
        try:
            import onnxruntime  # type: ignore[import-not-found]  # noqa: F401

            pose_backend = "onnx"
        except ImportError:
            pose_backend = "synthetic"

        return {
            "status": "ok",
            "instance_id": app.state.instance_id,
            "models": "none",
            "video": "loaded",
            "pose": pose_backend,
            "pose3d": pose_backend,
        }

    return app


app = create_app()
