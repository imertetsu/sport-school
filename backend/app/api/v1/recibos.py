"""Router del recibo PDF público tokenizado (epic Sucursales/Recibo).

`GET /api/v1/recibos/{org_id}/{pago_id}/{token}.pdf` — **sin auth**. Es el enlace
que se envía al tutor por WhatsApp. La seguridad es:
  1. El `token` HMAC prueba que el caller conoce el par (org, pago) firmado con el
     `jwt_secret` (RNF-02: enlace inadivinable). Validación en tiempo constante.
  2. Tras validar el token, se fija `app.current_org = org_id` en la transacción
     (mismo patrón `set_config(..., true)` que `set_tenant_context`) y el pago se
     consulta **bajo RLS normal** — NO se salta el aislamiento ni se usa SECURITY
     DEFINER. Si el org del token no es el del pago, RLS lo oculta (404).

Devuelve 404 (indistinguible) si: token inválido, pago inexistente bajo RLS, o
`pago.estado != "CONFIRMADO"` (solo hay recibo de pagos confirmados, espejo de
`cobranza.comprobante_pdf`).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.organizacion import Organizacion
from app.models.pago import Pago
from app.services import pagos as pagos_svc
from app.services import recibo_token
from app.services.deps import get_comprobante_service

router = APIRouter(prefix="/recibos", tags=["recibos"])

# 404 uniforme: token inválido, pago inexistente o no confirmado dan la MISMA
# respuesta para no filtrar si el (org, pago) existe.
_NO_ENCONTRADO = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recibo no encontrado")


@router.get("/{org_id}/{pago_id}/{token}.pdf")
def recibo_pdf(org_id: uuid.UUID, pago_id: uuid.UUID, token: str) -> Response:
    """Genera y devuelve el recibo PDF si el token es válido y el pago está CONFIRMADO.

    Abre su propia sesión/transacción (endpoint sin auth, no usa `get_db`): fija el
    contexto de tenant solo DESPUÉS de validar el token; sin token válido no se toca
    la BD.
    """
    if not recibo_token.token_valido(org_id, pago_id, token):
        raise _NO_ENCONTRADO

    db: Session = SessionLocal()
    try:
        # Fijar el contexto de tenant (RLS) para esta transacción, igual que
        # `set_tenant_context`. SET LOCAL: vive solo dentro de la transacción.
        db.execute(
            text("SELECT set_config('app.current_org', :org, true)"),
            {"org": str(org_id)},
        )
        pago = db.execute(select(Pago).where(Pago.id == pago_id)).scalar_one_or_none()
        if pago is None or pago.estado != "CONFIRMADO":
            raise _NO_ENCONTRADO

        org = db.execute(
            select(Organizacion).where(Organizacion.id == pago.org_id)
        ).scalar_one_or_none()
        if org is None:
            raise _NO_ENCONTRADO

        data = pagos_svc.construir_comprobante_data(db, pago=pago, org=org)
        pdf_bytes = get_comprobante_service().render_pdf(data)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="recibo_{pago_id}.pdf"'},
    )
