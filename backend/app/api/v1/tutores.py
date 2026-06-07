"""Router de Tutores (S3) — recuperar-por-CI.

`GET /tutores/por-ci/{ci}` recupera el tutor de la org del contexto con ese CI, o
404 si no existe. Scoped por org vía RLS (no hay chequeo cross-org: un mismo CI en
otra org es válido y no se revela). Alimenta el flujo de alta de deportista: el front
hace el lookup proactivo y, si encuentra el tutor, lo reutiliza (el alta también
recupera-por-CI y actualiza el teléfono en el backend, contrato #4).

Usa `Depends(set_tenant_context)` (token de escuela válido + GUC fijado, RLS real).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, set_tenant_context
from app.schemas.deportista import TutorByCiOut
from app.services import deportista as deportista_svc

router = APIRouter(prefix="/tutores", tags=["tutores"])


@router.get("/por-ci/{ci}", response_model=TutorByCiOut)
def get_tutor_por_ci(
    ci: str,
    _user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> TutorByCiOut:
    """Recupera el tutor de la org con ese CI (S3). 404 si no existe.

    Scoped por org vía RLS. El índice único parcial `(org_id, ci) WHERE ci IS NOT
    NULL` garantiza a lo sumo una fila por CI dentro de la org.
    """
    tutor = deportista_svc.buscar_tutor_por_ci(db, ci)
    if tutor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tutor no encontrado")
    return TutorByCiOut.model_validate(tutor)
