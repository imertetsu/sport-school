"""Factory de la aplicación FastAPI (LATINOSPORT).

Monta el router `/api/v1`, configura CORS desde settings y expone `/health`.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings


def _configurar_logging() -> None:
    """Deja visibles los logs de la app (nivel INFO).

    Sin esto, Python no configura ningún handler y solo el `lastResort` imprime,
    a partir de WARNING: los ~26 `logger.info` de la app (webhooks, envíos de
    WhatsApp, cron de cobranza) se descartaban en silencio y diagnosticar un
    envío fallido obligaba a adivinar. Los WARNING/ERROR sí salían, así que el
    hueco era justo el rastro del camino feliz.

    `force=True` porque uvicorn ya configuró el logging al arrancar; sin él,
    `basicConfig` no haría nada. httpx queda en WARNING: emite una línea INFO por
    cada request saliente (el sidecar de WhatsApp se consulta seguido) y ahogaría
    lo que sí importa.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def create_app() -> FastAPI:
    """Construye y configura la app FastAPI."""
    _configurar_logging()
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
