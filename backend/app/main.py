from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import http_exception_handler, request_validation_exception_handler
from app.routers import events, health, reports


def create_app() -> FastAPI:
    """Application factory for Shift Handover Copilot backend."""
    app = FastAPI(
        title="Shift Handover Copilot API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Register RFC 9457 exception handlers
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # Mount routers
    app.include_router(health.router)
    app.include_router(events.router)
    app.include_router(reports.router)

    return app


app = create_app()
