"""Configuración de la aplicación leída del entorno (contrato C7).

Las variables de entorno son definidas por infra-dev en `.env.example`; aquí solo
las consumimos. No hardcodear el nombre del producto ni los secretos.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Secretos de DESARROLLO que jamás deben llegar a producción (ver _guard_prod).
_WEAK_SECRETS = {"", "dev-change-me", "ci-secret", "change-me", "secret"}


class Settings(BaseSettings):
    """Settings tipados. Se mapean 1:1 con las env de C7."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Entorno: "dev" | "production". En production se exige config segura (ver abajo).
    app_env: str = "dev"

    # Branding (C0)
    app_name: str = "LATINOSPORT"
    # Emisor del recibo no-fiscal (epic Recibo, C2): empresa - app. Un solo lugar,
    # no hardcodeado por el PDF. No es factura SIN (fase 2).
    recibo_emisor: str = "SnapCoding - LatinoSport"

    # Base de datos: la app corre como rol `latinosport_app` (NOBYPASSRLS).
    # Driver psycopg v3 -> postgresql+psycopg:// (C3).
    database_url: str = "postgresql+psycopg://latinosport_app:devpass@db:5432/latinosport"

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

    # Programación de clases (C3). Ventana de generación de sesiones (días hacia
    # adelante) y antelación del recordatorio (horas). env opcional; default seguro.
    generar_sesiones_dias: int = 7
    recordatorio_clase_horas: int = 2

    # Cobranza / OpenBCB (C8). `openbcb_sandbox` activa el adaptador simulado y el
    # endpoint `…/simular-confirmacion`. base_url/api_key se usarán con el BCB real.
    openbcb_sandbox: bool = True
    openbcb_base_url: str | None = None
    openbcb_api_key: str | None = None
    whatsapp_provider: str = "noop"

    # WhatsApp Cloud API (Meta) — epic WhatsApp Cobro. Credenciales y verificación
    # del webhook; el adaptador real las consume (`MetaCloudWhatsAppAdapter`). En
    # dev/CI quedan en None y se usa el adaptador mock (`whatsapp_provider=noop`).
    whatsapp_phone_number_id: str | None = None
    whatsapp_access_token: str | None = None
    whatsapp_waba_id: str | None = None
    whatsapp_verify_token: str | None = None
    whatsapp_app_secret: str | None = None
    whatsapp_graph_version: str = "v21.0"
    # Días antes del vencimiento en que el recordatorio adjunta el QR de cobro.
    recordatorio_qr_dias_antes: int = 3

    # Bootstrap del primer super admin de plataforma (Epic Super Admin). Las consume
    # `python -m app.seed_plataforma` (idempotente por email). En prod se inyectan vía
    # `.env` (infra-dev) y NUNCA se commitean secretos. Sin ellas, el seed no crea nada.
    platform_admin_email: str | None = None
    platform_admin_password: str | None = None

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

    @model_validator(mode="after")
    def _guard_prod(self) -> Settings:
        """En producción, falla rápido si la config es insegura (no arranca con
        secretos de dev). Evita desplegar con `JWT_SECRET` débil o credenciales
        `devpass`. En dev/CI no aplica."""
        if self.app_env.lower() in {"prod", "production"}:
            problemas: list[str] = []
            if self.jwt_secret in _WEAK_SECRETS or len(self.jwt_secret) < 32:
                problemas.append("JWT_SECRET debe ser aleatorio y >= 32 caracteres")
            if "devpass" in self.database_url or "postgres:postgres@" in self.database_url:
                problemas.append("DATABASE_URL usa credenciales de desarrollo")
            if self.openbcb_sandbox:
                problemas.append("OPENBCB_SANDBOX debe ser false en producción")
            if problemas:
                raise ValueError(
                    "Configuración insegura para APP_ENV=production: " + "; ".join(problemas)
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Singleton de settings (cacheado para no releer el entorno por request)."""
    return Settings()


settings = get_settings()
