"""Webhook OpenBCB (contrato C3/C4) — `POST /webhooks/openbcb`, SIN auth.

Idempotente por `transaccion_id`. Resuelve el pago con `webhook_resolver`
(SECURITY DEFINER) saltando RLS, fija `app.current_org` del pago y confirma. Si no
resuelve la referencia o el monto no cuadra, encola en `conciliacion_pendiente`
(nunca descarta el pago, RNF-06). Responde **200 siempre** (incluso al conciliar):
el proveedor no debe reintentar indefinidamente.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.cobranza import WebhookIn
from app.services import pagos as pagos_svc
from app.services.deps import get_comprobante_service, get_notification_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/openbcb")
def openbcb_webhook(body: WebhookIn, db: Session = Depends(get_db)) -> dict[str, str]:
    """Recibe la confirmación de pago de OpenBCB (sandbox/real). 200 siempre."""
    resultado = pagos_svc.procesar_webhook(
        db,
        transaccion_id=body.transaccion_id,
        referencia=body.referencia,
        monto=body.monto,
        comprobante=get_comprobante_service(),
        notifier=get_notification_service(),
    )
    # Commit lo hace get_db al cerrar sin excepción.
    return {"status": "ok", "resultado": resultado}
