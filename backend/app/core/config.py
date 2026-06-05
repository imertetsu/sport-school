"""Configuración de la aplicación leída del entorno (contrato C7).

Las variables de entorno son definidas por infra-dev en `.env.example`; aquí solo
las consumimos. No hardcodear el nombre del producto ni los secretos.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Settings tipados. Se mapean 1:1 con las env de C7."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Branding (C0)
    app_name: str = "CanteraSport"

    # Base de datos: la app corre como rol `cantera_app` (NOBYPASSRLS).
    # Driver psycopg v3 -> postgresql+psycopg:// (C3).
    database_url: str = "postgresql+psycopg://cantera_app:devpass@db:5432/cantera"

    # Auth / JWT (C4)
    jwt_secret: str = "dev-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # CORS (C7): lista separada por comas en la env -> list[str].
    # `NoDecode` evita que pydantic-settings intente JSON-decodificar la env
    # ANTES del validador (rompía con `CORS_ORIGINS=a,b`); el validador parsea.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # Celery (workers). Broker/backend Redis desde el entorno.
    redis_url: str = "redis://redis:6379/0"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        """Permite `CORS_ORIGINS=a,b,c` (string) además de JSON/list."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                return json.loads(stripped)  # JSON array explícito
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Singleton de settings (cacheado para no releer el entorno por request)."""
    return Settings()


settings = get_settings()
