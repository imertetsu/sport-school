"""deportista.domicilio + deportista.lugar_nacimiento (dos columnas TEXT NULLABLE)

Migracion del epic "campos opcionales del deportista" (rama
`feat/campos-opcionales`) de LatinoSport. ALTER-only, DATA-PRESERVING: prod tiene
datos reales (cabeza actual 0018). NO reescribe historia: 0001-0018 quedan
INTACTAS; esta 0019 SOLO ANADE dos columnas opcionales a `deportista`.

Que hace
--------
Anade a la tabla tenant `deportista` dos columnas de texto OPCIONALES (NULLABLE),
ambas sin valor por defecto (las filas existentes quedan con NULL):

    ALTER TABLE deportista ADD COLUMN domicilio        text NULL;
    ALTER TABLE deportista ADD COLUMN lugar_nacimiento text NULL;

Nombres EXACTOS de columna (contrato compartido con backend-dev, que en paralelo
anade los atributos `Deportista.domicilio` y `Deportista.lugar_nacimiento` al
modelo SQLAlchemy con estos mismos nombres; si algo difiere tras empezar: handoff
y parar, no driftear el esquema en un solo lado).

RLS / GRANTs: SIN cambios.
  - `deportista` ya tiene su policy `org_isolation` (USING/WITH CHECK fail-closed
    por `org_id`, desde 0001/0003). La RLS es a nivel de FILA: las columnas nuevas
    quedan automaticamente cubiertas por el aislamiento por `org_id` existente; no
    requiere tocar ninguna policy.
  - El rol `latinosport_app` ya tiene GRANT DML a nivel de TABLA sobre
    `deportista` (desde 0001), que cubre cualquier columna nueva. No se anade ni
    modifica ningun GRANT.

downgrade(): inverso simetrico -- DROP de ambas columnas. No toca datos de otras
columnas, RLS, policies ni GRANTs.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # Dos columnas TEXT NULLABLE en `deportista`. Sin server_default: las filas
    # preexistentes quedan con NULL (campos opcionales). SIN RLS nueva ni GRANTs
    # nuevos: la policy `org_isolation` (a nivel de fila por org_id) y el GRANT
    # DML a nivel de tabla a `latinosport_app` ya existen desde 0001/0003 y
    # cubren columnas nuevas.
    # ------------------------------------------------------------------ #
    op.add_column(
        "deportista",
        sa.Column("domicilio", sa.Text(), nullable=True),
    )
    op.add_column(
        "deportista",
        sa.Column("lugar_nacimiento", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # Inverso simetrico: DROP de ambas columnas (orden inverso al add). No toca
    # datos de otras columnas, RLS, policies ni GRANTs preexistentes.
    op.drop_column("deportista", "lugar_nacimiento")
    op.drop_column("deportista", "domicilio")
