"""ci unico por organizacion para `deportista` y `tutor` (indices unicos PARCIALES)

Migracion del epic Identidad/CI-OCR (Sesion 3, rama `feat/identidad-ci-ocr`) de
LatinoSport. Escrita A MANO (no autogenerada): el `--autogenerate` no expresa
limpiamente un indice unico PARCIAL (`WHERE ci IS NOT NULL`) ni su semantica de
tenancy, y aqui la intencion es explicita. Es DATA-PRESERVING: prod tiene datos
reales (cabeza actual 0016). NO se reescribe historia: 0001-0016 quedan INTACTAS;
esta 0017 SOLO ANADE dos indices unicos parciales. Corre como OWNER (rol postgres)
via MIGRATION_DATABASE_URL (ver migrations/env.py).

Que hace
--------
Anade unicidad de CI POR ORGANIZACION sobre `deportista` y `tutor` mediante
INDICES UNICOS PARCIALES (no UniqueConstraint declarativo, para poder filtrar
`WHERE ci IS NOT NULL`):

    CREATE UNIQUE INDEX uq_deportista_org_ci ON deportista (org_id, ci)
        WHERE ci IS NOT NULL;
    CREATE UNIQUE INDEX uq_tutor_org_ci       ON tutor       (org_id, ci)
        WHERE ci IS NOT NULL;

Semantica (las tres reglas):
  (a) Multiples filas con `ci IS NULL` en la MISMA org -> PERMITIDO (el predicado
      parcial las excluye del indice; los NULL no participan de la unicidad).
  (b) El MISMO `ci` en orgs DISTINTAS -> PERMITIDO (la clave es `(org_id, ci)`,
      asi que dos orgs con el mismo CI son tuplas distintas).
  (c) `ci` DUPLICADO (no nulo) en la MISMA org -> RECHAZADO (viola el indice
      unico parcial; el INSERT/UPDATE falla con unique_violation 23505).

Tenancy: la clave incluye `org_id`, asi que la unicidad queda naturalmente
scoped por tenant. NO cambia RLS ni policies: los indices no alteran el
`org_isolation` (USING/WITH CHECK fail-closed) de 0001/0003 ni el GRANT a
`latinosport_app`. NO se toca el rol `latinosport_app` ni el GUC `app.current_org`.

Las columnas `deportista.ci` y `tutor.ci` (text NULL) YA EXISTEN desde 0001
(`alumno`/`tutor`; `alumno` renombrada a `deportista` en 0015). Esta revision NO
crea columnas ni toca tablas: solo ANADE indices. downgrade() los DROPea.

RIESGO A EVALUAR ANTES DE PROD
------------------------------
La creacion del indice FALLARA (unique_violation) si en la BD viva ya existen
filas con `(org_id, ci)` DUPLICADO y `ci NO null`. No se resuelve aqui: si hay
duplicados preexistentes en prod, deben sanearse (o decidir la politica de
dedupe) ANTES de aplicar 0017. Consulta de deteccion (correr en prod como owner
antes del upgrade):

    -- deportista: grupos (org_id, ci) con ci no nulo y mas de una fila
    SELECT org_id, ci, count(*)
    FROM deportista
    WHERE ci IS NOT NULL
    GROUP BY org_id, ci
    HAVING count(*) > 1;

    -- tutor: idem
    SELECT org_id, ci, count(*)
    FROM tutor
    WHERE ci IS NOT NULL
    GROUP BY org_id, ci
    HAVING count(*) > 1;

Si ambas devuelven 0 filas, 0017 aplica sin incidentes.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # Indices unicos PARCIALES `(org_id, ci) WHERE ci IS NOT NULL`.
    #
    # `op.create_index(..., unique=True, postgresql_where=...)` emite exactamente
    # `CREATE UNIQUE INDEX ... ON ... (org_id, ci) WHERE ci IS NOT NULL`. El
    # predicado parcial es lo que permite multiples NULL (los excluye del indice)
    # a la vez que fuerza unicidad de los CI no nulos DENTRO de cada org.
    # ------------------------------------------------------------------ #
    op.create_index(
        "uq_deportista_org_ci",
        "deportista",
        ["org_id", "ci"],
        unique=True,
        postgresql_where=sa.text("ci IS NOT NULL"),
    )
    op.create_index(
        "uq_tutor_org_ci",
        "tutor",
        ["org_id", "ci"],
        unique=True,
        postgresql_where=sa.text("ci IS NOT NULL"),
    )


def downgrade() -> None:
    # Inverso simetrico: DROP de ambos indices. No toca columnas, datos ni RLS.
    op.drop_index("uq_tutor_org_ci", table_name="tutor")
    op.drop_index("uq_deportista_org_ci", table_name="deportista")
