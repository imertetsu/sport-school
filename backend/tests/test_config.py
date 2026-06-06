"""Tests del guard de configuración de producción (`Settings._guard_prod`).

En `APP_ENV=production` la app debe FALLAR al construir Settings si hay config
insegura (secreto débil, credenciales de dev, sandbox on). En dev no aplica.
Tests puros (sin BD).
"""

from __future__ import annotations

import pytest
from app.core.config import Settings
from pydantic import ValidationError


def _prod(
    *,
    jwt_secret: str = "x" * 40,  # >= 32 y no está en _WEAK_SECRETS
    database_url: str = "postgresql+psycopg://app_prod:Str0ng-Pass@db:5432/latinosport",
    openbcb_sandbox: bool = False,
) -> Settings:
    return Settings(
        app_env="production",
        jwt_secret=jwt_secret,
        database_url=database_url,
        openbcb_sandbox=openbcb_sandbox,
    )


def test_produccion_con_config_segura_arranca() -> None:
    assert _prod().app_env == "production"


def test_produccion_rechaza_jwt_debil() -> None:
    with pytest.raises(ValidationError):
        _prod(jwt_secret="dev-change-me")


def test_produccion_rechaza_jwt_corto() -> None:
    with pytest.raises(ValidationError):
        _prod(jwt_secret="corto")


def test_produccion_rechaza_credenciales_dev() -> None:
    with pytest.raises(ValidationError):
        _prod(database_url="postgresql+psycopg://latinosport_app:devpass@db:5432/latinosport")


def test_produccion_rechaza_sandbox_on() -> None:
    with pytest.raises(ValidationError):
        _prod(openbcb_sandbox=True)


def test_dev_permite_defaults_inseguros() -> None:
    s = Settings(
        app_env="dev",
        jwt_secret="dev-change-me",
        database_url="postgresql+psycopg://latinosport_app:devpass@db:5432/latinosport",
        openbcb_sandbox=True,
    )
    assert s.app_env == "dev"
