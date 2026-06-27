"""deportista: nombres en MAYUSCULAS (backfill) + CI "0" como placeholder no-unico

Dos cambios de negocio sobre `deportista` (solo deportistas; tutores/entrenadores no
se tocan):

1. **Nombres en MAYUSCULAS.** Backfill de los deportistas YA existentes
   (`ap_paterno`, `ap_materno`, `nombres` -> `upper(...)`). Los nuevos/editados los
   normaliza el modelo (`@validates`), esta migracion cubre los previos.

2. **CI "0" = "presentara luego".** El CI del deportista es obligatorio, pero a veces
   aun no se tiene el documento y se teclea "0" como marcador. "0" puede repetirse
   entre deportistas, asi que se EXCLUYE del indice unico parcial. El indice pasa de
   `(org_id, ci) WHERE ci IS NOT NULL` a `(org_id, ci) WHERE ci IS NOT NULL AND ci <> '0'`.
   (El servicio `buscar_deportista_por_ci` ya trata "0" como no-identificable.)

No toca columnas, FKs ni RLS.

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Backfill: deportistas existentes a MAYUSCULAS. upper() respeta acentos
    #    (a -> A) y deja NULL como NULL.
    op.execute(
        "UPDATE deportista SET "
        "ap_paterno = upper(ap_paterno), "
        "ap_materno = upper(ap_materno), "
        "nombres = upper(nombres)"
    )

    # 2) Recrear el indice unico parcial de CI excluyendo el placeholder "0", de modo
    #    que varios deportistas puedan compartir CI = '0' ("pendiente") sin colisionar,
    #    pero los CI reales sigan siendo unicos por org.
    op.drop_index("uq_deportista_org_ci", table_name="deportista")
    op.create_index(
        "uq_deportista_org_ci",
        "deportista",
        ["org_id", "ci"],
        unique=True,
        postgresql_where=sa.text("ci IS NOT NULL AND ci <> '0'"),
    )


def downgrade() -> None:
    # Inverso del indice (vuelve a incluir '0' en la unicidad). El backfill de
    # mayusculas NO es reversible (no se conserva el casing original) -> no-op.
    op.drop_index("uq_deportista_org_ci", table_name="deportista")
    op.create_index(
        "uq_deportista_org_ci",
        "deportista",
        ["org_id", "ci"],
        unique=True,
        postgresql_where=sa.text("ci IS NOT NULL"),
    )
