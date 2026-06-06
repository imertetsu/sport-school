"""Factory de la aplicación FastAPI (LATINOSPORT).

Monta el router `/api/v1`, configura CORS desde settings y expone `/health`.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings


def create_app() -> FastAPI:
    """Construye y configura la app FastAPI."""
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness simple (no toca la BD)."""
        return {"status": "ok", "app": settings.app_name}

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
