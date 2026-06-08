"""deportista.activo (soft-delete) + organizacion.color (monograma)

Migracion del epic "escuela-y-bajas" (Fase 0) de LatinoSport. ALTER-only,
DATA-PRESERVING: prod tiene datos reales (cabeza actual 0019). NO reescribe
historia: 0001-0019 quedan INTACTAS; esta 0020 SOLO ANADE dos columnas.

Que hace
--------
1) `deportista.activo` -- BOOLEAN NOT NULL DEFAULT true (soft-delete del
   deportista). La tabla tenant `deportista` YA tiene filas en prod, asi que anadir
   una columna NOT NULL exige backfillear las filas existentes. Se usa el patron de
   `aviso.activo`: el modelo SQLAlchemy define `activo` con `server_default=func.true()`
   + `default=True`, y la columna fisica CONSERVA el `DEFAULT true`:

       ALTER TABLE deportista ADD COLUMN activo boolean NOT NULL DEFAULT true;

   El `server_default` backfillea las filas preexistentes, satisface el NOT NULL y
   ademas cubre los INSERT por SQL crudo (seed y tests insertan deportistas con
   `text("INSERT INTO deportista ...")` sin la columna `activo`); el `default=True`
   del ORM cubre los INSERT por objeto. Esquema fisico ↔ modelo COINCIDEN (ambos con
   server_default), asi que no hay drift de `--autogenerate`.

2) `organizacion.color` -- columna de texto OPCIONAL (NULLABLE), sin default: las
   filas existentes quedan con NULL (el front usa un default determinista). Simple,
   sin backfill.

       ALTER TABLE organizacion ADD COLUMN color varchar NULL;

Nombres EXACTOS de columna (contrato compartido con backend-dev, que en paralelo
anade `Deportista.activo` (Boolean NOT NULL, default=True, sin server_default) y
`Organizacion.color` (String NULL) al modelo SQLAlchemy con estos mismos nombres;
si algo difiere tras empezar: handoff y parar, no driftear el esquema en un solo
lado).

RLS / GRANTs: SIN cambios. SIN policies nuevas.
  - `deportista` ya tiene su policy `org_isolation` (USING/WITH CHECK fail-closed
    por `org_id`, desde 0001/0003). La RLS es a nivel de FILA: la columna nueva
    queda cubierta por el aislamiento por `org_id` existente. NO se toca su policy.
  - `organizacion` NO tiene RLS (es la unica tabla sin org_id/policy, igual que
    hoy). Su scoping es responsabilidad del endpoint (server-side). NO se anade
    RLS aqui.
  - El rol `latinosport_app` ya tiene GRANT DML a nivel de TABLA sobre ambas tablas
    (desde 0001), que cubre cualquier columna nueva. No se anade ni modifica GRANT.

downgrade(): inverso simetrico -- DROP de ambas columnas. No toca datos de otras
columnas, RLS, policies ni GRANTs.

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) deportista.activo BOOLEAN NOT NULL DEFAULT true (patron de aviso.activo).
    #    El server_default='true' backfillea las filas existentes, satisface el
    #    NOT NULL y cubre los INSERT por SQL crudo (seed/tests). Se CONSERVA (no se
    #    retira): el modelo tambien lleva server_default=func.true(), asi que esquema
    #    fisico ↔ modelo coinciden y no hay drift de --autogenerate.
    #    SIN RLS nueva ni GRANTs nuevos: la policy org_isolation (a nivel de fila por
    #    org_id) y el GRANT DML a tabla a latinosport_app ya existen desde 0001/0003.
    # ------------------------------------------------------------------ #
    op.add_column(
        "deportista",
        sa.Column(
            "activo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # ------------------------------------------------------------------ #
    # 2) organizacion.color: columna de texto OPCIONAL (NULLABLE), sin default. Las
    #    filas existentes quedan con NULL (el front aplica un default determinista).
    #    `organizacion` NO tiene RLS (igual que hoy): no se toca nada de RLS aqui.
    #    Tipo `sa.String()` (== VARCHAR sin longitud) para coincidir EXACTO con el
    #    modelo `Organizacion.color: Mapped[str | None] = mapped_column(String, ...)`.
    # ------------------------------------------------------------------ #
    op.add_column(
        "organizacion",
        sa.Column("color", sa.String(), nullable=True),
    )


def downgrade() -> None:
    # Inverso simetrico: DROP de ambas columnas (orden inverso al add). No toca
    # datos de otras columnas, RLS, policies ni GRANTs preexistentes.
    op.drop_column("organizacion", "color")
    op.drop_column("deportista", "activo")
