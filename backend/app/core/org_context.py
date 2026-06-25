"""Contexto en-proceso del `org_id` de la operación en curso (epic whatsapp-multitenant).

Espejo **en-proceso** del GUC de PostgreSQL `app.current_org`: se setea en los MISMOS
dos puntos donde ya se fija ese GUC dentro de la transacción del request/job
(`core/tenant.py::set_tenant_context` y `workers/tasks.py::_set_org`). Sirve para que el
adaptador del gateway de WhatsApp sepa **de qué organización** debe enviar **sin** cambiar
la firma de `WhatsAppPort` (congelada): el adaptador lee `get_current_org_id()` y pega al
sidecar en `/sessions/{org_id}/send`.

Invariante **fail-closed**: `None` (no hay contexto de org) ⇒ el adaptador reporta
`ok=False` **sin** pegar al sidecar. El `ContextVar` aísla por tarea/hilo: dos orgs
consecutivas en el mismo proceso cron no fugan la una sobre la otra (cada `_set_org`
re-setea el valor).

`core` puro: **sin** dependencias de SQLAlchemy ni FastAPI (no debe romper import-linter;
el dominio no importa este módulo, sí el adaptador y el wiring de tenant/worker).
"""

from __future__ import annotations

from contextvars import ContextVar

_current_org_id: ContextVar[str | None] = ContextVar("current_org_id", default=None)


def set_current_org_id(org_id: str | None) -> None:
    """Fija el `org_id` de la operación en curso (o `None` para limpiar el contexto)."""
    _current_org_id.set(org_id)


def get_current_org_id() -> str | None:
    """Devuelve el `org_id` de la operación en curso, o `None` si no hay contexto."""
    return _current_org_id.get()
