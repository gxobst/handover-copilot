from fastapi import FastAPI

from app.routers import health


def create_app() -> FastAPI:
    """Application factory for Shift Handover Copilot backend."""
    app = FastAPI(
        title="Shift Handover Copilot API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.include_router(health.router)

    return app


app = create_app()
