import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.errors import http_exception_handler, request_validation_exception_handler
from app.routers import admin, events, health, relay, reports
from app.telemetry import TelemetryMiddleware, get_logger, init_telemetry


def create_app() -> FastAPI:
    """Application factory for Shift Handover Copilot backend."""
    init_telemetry()

    settings = get_settings()
    logger = get_logger("startup")
    logger.info(
        "app_startup",
        llm_backend=settings.llm_backend,
        gcp_location=settings.gcp_location,
        active_model=settings.active_model,
        fallback_model=settings.fallback_model,
    )

    app = FastAPI(
        title="Shift Handover Copilot API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Mount TelemetryMiddleware for Cloud Run force_flush and W3C trace correlation
    app.add_middleware(TelemetryMiddleware)

    # Register RFC 9457 exception handlers
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # Mount routers
    app.include_router(health.router)
    app.include_router(events.router)
    app.include_router(reports.router)
    app.include_router(admin.router)
    app.include_router(relay.router)

    # Mount static frontend files if directory exists
    static_dirs = [
        Path(os.environ.get("FRONTEND_DIR", "")),
        Path(__file__).resolve().parent.parent / "static",
        Path(__file__).resolve().parent.parent / "frontend_dist",
        Path(__file__).resolve().parent.parent.parent / "frontend" / "dist",
    ]

    static_path = None
    for p in static_dirs:
        if str(p) and p.is_dir() and (p / "index.html").is_file():
            static_path = p
            break

    if static_path:
        logger.info("serving_frontend_static_files", path=str(static_path))
        assets_dir = static_path / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_frontend(full_path: str):
            if full_path.startswith("api/") or full_path == "api":
                raise HTTPException(status_code=404, detail="Not Found")
            file = static_path / full_path
            if file.is_file():
                return FileResponse(file)
            return FileResponse(static_path / "index.html")

    return app


app = create_app()

