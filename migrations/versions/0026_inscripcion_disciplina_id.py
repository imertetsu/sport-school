"""inscripcion.disciplina_id (FK al catálogo global de disciplinas)

Migración del epic "múltiples inscripciones por deportista" (una por disciplina, cada
una con su propia cuota). ALTER-only, DATA-PRESERVING: cabeza actual 0025; 0001-0025
quedan INTACTAS. SOLO añade una columna FK OPCIONAL a `inscripcion` y rellena las filas
existentes con la disciplina que tenía su deportista.

Qué hace
--------
1. `ALTER TABLE inscripcion ADD COLUMN disciplina_id uuid NULL REFERENCES disciplina(id)
   ON DELETE SET NULL` (espejo del FK `deportista.disciplina_id`). `disciplina` es catálogo
   GLOBAL (no tenant), como ya lo referencia `deportista`.
2. Índice `ix_inscripcion_disciplina_id`.
3. Backfill: cada inscripción hereda `deportista.disciplina_id` (la disciplina única que
   había hasta ahora). Corre como `postgres` (superusuario → bypassa FORCE RLS), así que
   toca todas las filas de todas las orgs.

RLS / GRANTs: SIN cambios. `inscripcion` ya tiene su policy `org_isolation` a nivel de
FILA (por `org_id`) y el GRANT DML de tabla a `latinosport_app` desde 0001; ambos cubren
la columna nueva. El FK apunta a `disciplina` (global, sin RLS), igual que `deportista`.

downgrade(): inverso simétrico (drop índice, FK y columna). No toca datos de otras
columnas, RLS, policies ni GRANTs.

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inscripcion",
        sa.Column("disciplina_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_inscripcion_disciplina",
        "inscripcion",
        "disciplina",
        ["disciplina_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_inscripcion_disciplina_id", "inscripcion", ["disciplina_id"])
    # Backfill: cada inscripción existente toma la disciplina de su deportista (la única
    # que había). Corre como superusuario => ignora FORCE RLS y cubre todas las orgs.
    op.execute(
        "UPDATE inscripcion i SET disciplina_id = d.disciplina_id "
        "FROM deportista d "
        "WHERE d.id = i.deportista_id AND d.disciplina_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_inscripcion_disciplina_id", table_name="inscripcion")
    op.drop_constraint("fk_inscripcion_disciplina", "inscripcion", type_="foreignkey")
    op.drop_column("inscripcion", "disciplina_id")
