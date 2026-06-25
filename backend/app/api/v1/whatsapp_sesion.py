"""Router de `/mi-escuela/whatsapp/*` (contrato 4, epic whatsapp-multitenant).

Gestión de la sesión de WhatsApp **de la escuela del usuario** (un número por escuela):
ver estado de conexión, vincular por **QR** (lazy, con polling) y desvincular. **Solo
ADMIN**; la org sale SIEMPRE de `user.org_id` (del token), jamás del cliente — mismo
borde de seguridad que `/mi-escuela`.

El **backend es el ÚNICO** que habla con el sidecar multi-sesión: pega por `httpx` a
`{settings.whatsapp_gateway_url}/sessions/{org}/...` con el header `X-Gateway-Token`. El
**browser nunca** ve ese token ni la URL del sidecar; el QR data-url viaja
browser ← backend ← sidecar.

La tabla `whatsapp_sesion` (RLS por `org_id`) es **metadata best-effort** para la UI; la
**verdad LIVE** (connected / QR vivo) es el sidecar. Cada lectura **reconcilia** la fila
contra el estado real del sidecar. Si el sidecar no responde, `GET /estado` degrada al
**último estado conocido** de la BD (no 500); las acciones que necesitan al sidecar
(`vincular`, desvincular) sí propagan el fallo de red al cliente.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.tenant import CurrentUser, require_role
from app.models.whatsapp_sesion import WhatsAppSesion
from app.schemas.whatsapp_sesion import WhatsAppEstadoOut, WhatsAppQrOut

router = APIRouter(prefix="/mi-escuela/whatsapp", tags=["mi-escuela"])

_TIMEOUT_SECONDS = 15.0


# --------------------------------------------------------------------------- #
# Helper del sidecar (el browser NUNCA ve token/URL; este es el único punto)
# --------------------------------------------------------------------------- #
def _sidecar_request(method: str, org_id: str, path: str = "") -> dict[str, Any]:
    """Pega al sidecar `{method} {gateway_url}/sessions/{org_id}{path}` con el token.

    Devuelve el JSON del sidecar (siempre un dict). Lanza `httpx.HTTPError` si la red
    falla o el sidecar responde 5xx — el caller decide si degrada (estado) o propaga.
    El `X-Gateway-Token` se inyecta aquí y **nunca** sale hacia el browser.
    """
    base = (settings.whatsapp_gateway_url or "").rstrip("/")
    url = f"{base}/sessions/{org_id}{path}"
    headers = {"X-Gateway-Token": settings.whatsapp_gateway_token or ""}
    resp = httpx.request(method, url, headers=headers, timeout=_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------- #
# Fila de la org (lee/crea); reconciliación contra el sidecar
# --------------------------------------------------------------------------- #
def _get_or_create_fila(db: Session, org_id: str) -> WhatsAppSesion:
    """Devuelve la fila `whatsapp_sesion` de la org (RLS-scoped), creándola si falta."""
    fila = db.execute(
        select(WhatsAppSesion).where(WhatsAppSesion.org_id == uuid.UUID(org_id))
    ).scalar_one_or_none()
    if fila is None:
        fila = WhatsAppSesion(org_id=uuid.UUID(org_id), estado="DESVINCULADA")
        db.add(fila)
        db.flush()
    return fila


def _aplicar_conectada(fila: WhatsAppSesion, numero: str | None) -> None:
    """Marca la fila como CONECTADA con el número del sidecar (fija `vinculado_en`)."""
    fila.estado = "CONECTADA"
    if numero:
        fila.numero = str(numero)
    if fila.vinculado_en is None:
        fila.vinculado_en = datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get("/estado", response_model=WhatsAppEstadoOut)
def estado(
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> WhatsAppEstadoOut:
    """Estado reconciliado de la sesión de la escuela del usuario.

    Lee/crea la fila, consulta `GET /sessions/{org}/status` del sidecar y reconcilia. Si
    el sidecar no responde, degrada al **último estado conocido** de la BD (no 500).
    """
    fila = _get_or_create_fila(db, user.org_id)
    try:
        data = _sidecar_request("GET", user.org_id, "/status")
    except httpx.HTTPError:
        # Sidecar caído: respondemos el último estado conocido de la BD (no 500).
        return WhatsAppEstadoOut(
            estado=fila.estado,  # type: ignore[arg-type]
            numero=fila.numero,
            vinculado_en=fila.vinculado_en,
        )

    if data.get("connected"):
        _aplicar_conectada(fila, data.get("number"))
    else:
        # El sidecar la conoce pero no está conectada → DESVINCULADA salvo que esté
        # esperando QR (eso lo refleja /vincular|/qr); aquí cache best-effort a DESVINCULADA.
        if fila.estado == "CONECTADA":
            fila.estado = "DESVINCULADA"
            fila.numero = None
    db.flush()
    return WhatsAppEstadoOut(
        estado=fila.estado,  # type: ignore[arg-type]
        numero=fila.numero,
        vinculado_en=fila.vinculado_en,
    )


def _vincular_o_qr(db: Session, org_id: str) -> WhatsAppQrOut:
    """Lógica compartida de `POST /vincular` y `GET /qr` (lazy QR del sidecar).

    `GET /sessions/{org}/qr` (lazy: si no hay Session, el sidecar la crea y arranca el
    pairing). `connected` → fila CONECTADA + `{estado:'CONECTADA', numero}`; con `qr` →
    fila PENDIENTE_QR + `{estado:'PENDIENTE_QR', qr}`; `qr:null` → `{estado:'PENDIENTE_QR',
    qr:null}` (el front reintenta).
    """
    fila = _get_or_create_fila(db, org_id)
    data = _sidecar_request("GET", org_id, "/qr")

    if data.get("connected"):
        numero = data.get("number")
        _aplicar_conectada(fila, numero)
        db.flush()
        return WhatsAppQrOut(
            estado="CONECTADA", numero=str(numero) if numero else fila.numero, qr=None
        )

    qr = data.get("qr")
    fila.estado = "PENDIENTE_QR"
    db.flush()
    return WhatsAppQrOut(estado="PENDIENTE_QR", qr=str(qr) if qr else None, numero=None)


@router.post("/vincular", response_model=WhatsAppQrOut)
def vincular(
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> WhatsAppQrOut:
    """Arranca el pairing (lazy) y devuelve el QR (o CONECTADA si ya estaba pareada)."""
    return _vincular_o_qr(db, user.org_id)


@router.get("/qr", response_model=WhatsAppQrOut)
def qr(
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> WhatsAppQrOut:
    """Polling del QR mientras está PENDIENTE_QR (mismo shape que `vincular`)."""
    return _vincular_o_qr(db, user.org_id)


@router.delete("", response_model=WhatsAppEstadoOut)
def desvincular(
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> WhatsAppEstadoOut:
    """Desvincula: `DELETE /sessions/{org}` en el sidecar + fila → DESVINCULADA.

    El sidecar es idempotente (200 aunque no hubiera sesión). Tras la baja, la fila queda
    `DESVINCULADA` con `numero=null`.
    """
    fila = _get_or_create_fila(db, user.org_id)
    _sidecar_request("DELETE", user.org_id)
    fila.estado = "DESVINCULADA"
    fila.numero = None
    fila.vinculado_en = None
    db.flush()
    return WhatsAppEstadoOut(estado="DESVINCULADA", numero=None, vinculado_en=None)
