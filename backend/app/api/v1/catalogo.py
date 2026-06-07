"""Router de catálogo de lectura para la ESCUELA (epic Disciplinas, S2).

`GET /catalogo/disciplinas` expone el catálogo GLOBAL de disciplinas a ADMIN y
ENTRENADOR. La respuesta es **solo el catálogo** (`DisciplinaOut {id, nombre}`): cero
datos de tenant → no debilita el aislamiento (la tabla `disciplina` no tiene `org_id`
ni RLS por diseño).

Usa `Depends(set_tenant_context)` para exigir un token de escuela válido (fija el GUC,
aunque la query a `disciplina` no lo necesita). NO se restringe a un rol concreto:
ADMIN y ENTRENADOR (cualquier usuario autenticado de una escuela) pueden leer el
catálogo para poblar selects.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, set_tenant_context
from app.schemas.disciplina import DisciplinaOut
from app.services import disciplina as disciplina_svc

router = APIRouter(prefix="/catalogo", tags=["catalogo"])


@router.get("/disciplinas", response_model=list[DisciplinaOut])
def listar_disciplinas_catalogo(
    solo_activas: bool = Query(default=True),
    _user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> list[DisciplinaOut]:
    """Lista el catálogo global de disciplinas (por defecto solo las activas).

    Respuesta = SOLO `{id, nombre}` (cero datos de tenant). ADMIN y ENTRENADOR.
    """
    rows = disciplina_svc.listar_disciplinas(db, solo_activas=solo_activas)
    return [DisciplinaOut.model_validate(d) for d in rows]
