"""anular_pago: reversa con rastro de un pago en efectivo registrado por error
-- pago.{motivo_anulacion, anulado_por, anulado_en, credito_generado} +
ampliacion del CHECK de estado con 'ANULADO'

Migracion del epic anular-pago (anular pago en efectivo CON rastro, nunca
borrado) de LatinoSport. Escrita A MANO (no autogenerada): el CHECK enum no lo
detecta `--autogenerate`. Corre sobre la BD con todo hasta 0024
(`0024_deportista_mayusculas_ci_cero`) ya viva; main aplica el upgrade en la
fase de cierre del epic.

Contrato implementado (docs/specs/anular-pago.md, C1) -- el esquema de columnas
(tipos/nullability/defaults) es contrato compartido con backend-dev (su modelo
`Pago`, C2, debe reflejarlo EXACTO; si una columna cambia tras empezar, handoff
y parar, no driftear el esquema en un solo lado):

- `pago`: + `motivo_anulacion TEXT NULL` (motivo obligatorio que da el ADMIN al
  anular; NULL en pagos no anulados).
- `pago`: + `anulado_por UUID NULL` -> `usuario(id)` ON DELETE SET NULL (quien
  anulo; mismo patron de FK que `registrado_por` en 0002).
- `pago`: + `anulado_en TIMESTAMPTZ NULL` (cuando se anulo, UTC).
- `pago`: + `credito_generado NUMERIC(10,2) NOT NULL DEFAULT 0` (persiste el
  sobrepago->credito que genero cada pago, para revertir el saldo a favor con
  exactitud al anular; default 0 => los pagos existentes no rompen).
- `pago.estado` CHECK: DROP `ck_pago_estado` (original 0002
  `IN ('PENDIENTE','CONFIRMADO','FALLIDO')`) + ADD con
  `IN ('PENDIENTE','CONFIRMADO','FALLIDO','ANULADO')` (anade el estado de
  reversa con rastro; patron 0009 con `ck_cuota_estado`).

`pago` YA tiene RLS habilitada/forzada + GRANTs de DML desde 0002 (y el
hardening de 0003): este epic solo le ANADE columnas y amplia un CHECK, NO
re-habilita RLS ni re-otorga DML (patron 0010 add-column sin re-RLS). No crea
tablas nuevas => no hay nada tenant nuevo que aislar.

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Ampliar `pago` con las 4 columnas de auditoria/reversa. Todas son
    #    aditivas: las 3 de rastro son NULL (un pago vivo no tiene anulacion) y
    #    `credito_generado` arranca en 0 (server_default) => los pagos
    #    existentes y el polling de QR no se rompen. `pago` ya tiene RLS/GRANTs
    #    desde 0002 -> NO re-habilitar RLS ni re-GRANT aqui (patron 0010).
    # ------------------------------------------------------------------ #
    op.add_column(
        "pago",
        sa.Column("motivo_anulacion", sa.Text(), nullable=True),
    )
    op.add_column(
        "pago",
        sa.Column(
            "anulado_por",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "pago",
        sa.Column(
            "anulado_en",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "pago",
        sa.Column(
            "credito_generado",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # ------------------------------------------------------------------ #
    # 2) Ampliar el CHECK de estado para incluir 'ANULADO' (reversa con rastro).
    #    DROP + ADD porque ALTER de un CHECK existente no es in-place (patron
    #    0009 con `ck_cuota_estado`). Confirmado contra 0002: el CHECK actual es
    #    `estado IN ('PENDIENTE','CONFIRMADO','FALLIDO')`.
    # ------------------------------------------------------------------ #
    op.drop_constraint("ck_pago_estado", "pago", type_="check")
    op.create_check_constraint(
        "ck_pago_estado",
        "pago",
        "estado IN ('PENDIENTE','CONFIRMADO','FALLIDO','ANULADO')",
    )


def downgrade() -> None:
    # Orden inverso. Restaurar primero el CHECK original (sin 'ANULADO') y luego
    # dropear las 4 columnas en orden inverso al de creacion.
    #
    # Nota (igual que 0009 documenta con 'PARCIAL'): si quedaran filas en estado
    # 'ANULADO', este ADD del CHECK restaurado FALLARIA -- y es correcto: el
    # downgrade no debe perder silenciosamente la marca de un pago anulado. En
    # una BD recien migrada no hay filas 'ANULADO', asi que el downgrade corre
    # limpio; en una BD con anulaciones reales habria que resolver esas filas
    # antes de bajar la revision.
    op.drop_constraint("ck_pago_estado", "pago", type_="check")
    op.create_check_constraint(
        "ck_pago_estado",
        "pago",
        "estado IN ('PENDIENTE','CONFIRMADO','FALLIDO')",
    )

    op.drop_column("pago", "credito_generado")
    op.drop_column("pago", "anulado_en")
    op.drop_column("pago", "anulado_por")
    op.drop_column("pago", "motivo_anulacion")
