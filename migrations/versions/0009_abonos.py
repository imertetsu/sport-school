"""abonos: pagos parciales -- cuota.monto_pagado, pago.credito_aplicado, tabla
`credito` + RLS (NULLIF fail-closed) + GRANTs + ampliacion del CHECK de estado

Migracion del epic Abonos (pagos parciales en efectivo sobre Cobranza) de
LatinoSport. Escrita A MANO (no autogenerada): RLS / GRANTs / CHECK no los
detecta `--autogenerate`. Corre sobre la BD con Alumnos (0001) + Cobranza
(0002) + hardening RLS (0003) + Asistencia (0004) + Egresos (0005) + Avisos
(0006) + Horarios (0007) + Auto-registro (0008) ya viva; main aplica el upgrade
en la fase de cierre.

Contrato implementado (docs/specs/abonos.md, C1) -- el esquema de columnas
(tipos/nullability/defaults) es contrato compartido con backend-dev (sus modelos
`cuota`/`pago`/`credito` deben reflejarlo; si una columna cambia tras empezar,
handoff y parar, no driftear el esquema en un solo lado):

- `cuota`: + `monto_pagado NUMERIC(10,2) NOT NULL DEFAULT 0`. El saldo es
  derivado (`monto - monto_pagado`), NO se persiste.
- `cuota.estado` CHECK: DROP `ck_cuota_estado` (original
  `IN ('PENDIENTE','PAGADO','VENCIDO')`) + ADD con
  `IN ('PENDIENTE','PARCIAL','PAGADO','VENCIDO')` (anade `PARCIAL`, cuota a
  medias sin vencer; `VENCIDO` tiene precedencia, RF-ABO-05).
- `pago`: + `credito_aplicado NUMERIC(10,2) NOT NULL DEFAULT 0`. `pago.monto` =
  solo efectivo/caja; `credito_aplicado` = saldo a favor consumido. Invariante
  (la valida el backend): Sum(pago_cuota.monto_aplicado) = monto + credito_aplicado.
- Tabla nueva tenant `credito` (un saldo a favor por inscripcion):
  - id uuid PK gen_random_uuid()
  - org_id uuid -> organizacion(id) ON DELETE CASCADE, NOT NULL (denormalizado RLS)
  - inscripcion_id uuid -> inscripcion(id) ON DELETE CASCADE, NOT NULL
  - saldo NUMERIC(10,2) NOT NULL DEFAULT 0
  - created_at / updated_at timestamptz now() NOT NULL
  - UNIQUE(inscripcion_id) -- un credito por inscripcion (upsert RF-ABO-06)
  - CHECK(saldo >= 0) `ck_credito_saldo_no_negativo`

- Data migration (retrocompat, RF-ABO-09 criterio 9):
  `UPDATE cuota SET monto_pagado = monto WHERE estado = 'PAGADO'`. El resto
  queda 0 (default). NO crea filas en `credito`.

RLS de `credito`: ENABLE + FORCE + policy `org_isolation` con el patron
fail-closed de 0003: `NULLIF(current_setting('app.current_org', true), '')::uuid`.
Asi tanto el caso "nunca seteado" (NULL) como el "reseteado a vacio" ('' tras
SET LOCAL + commit en el pool) colapsan a NULL -> 0 filas y no pasan WITH CHECK
(criterio 8). GRANTs DML a `latinosport_app` + USAGE/SELECT en secuencias
(replica 0008; el PK usa gen_random_uuid(), no secuencia, pero mantenemos el
grant por consistencia e idempotencia).

`cuota` y `pago` ya tienen RLS/GRANTs desde 0002; este epic solo les ANADE
columnas, no re-habilita RLS ni re-otorga DML.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas tenant (con org_id) NUEVAS de este epic: llevan RLS habilitada + forzada
# y reciben GRANT de DML + USAGE/SELECT sobre las secuencias del schema.
TENANT_TABLES: tuple[str, ...] = ("credito",)

# Expresion fail-closed (0003): '' (GUC reseteado) y NULL (nunca seteado)
# -> NULL -> 0 filas y no pasa WITH CHECK.
_EXPR = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Ampliar `cuota`: + monto_pagado (saldo derivado, no se persiste) y
    #    ampliar el CHECK de estado para incluir 'PARCIAL'. DROP + ADD del
    #    CHECK porque ALTER de un CHECK existente no es in-place.
    # ------------------------------------------------------------------ #
    op.add_column(
        "cuota",
        sa.Column(
            "monto_pagado",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.drop_constraint("ck_cuota_estado", "cuota", type_="check")
    op.create_check_constraint(
        "ck_cuota_estado",
        "cuota",
        "estado IN ('PENDIENTE','PARCIAL','PAGADO','VENCIDO')",
    )

    # ------------------------------------------------------------------ #
    # 2) Ampliar `pago`: + credito_aplicado (saldo a favor consumido; default 0
    #    => el polling de QR no se rompe, RF-ABO-09 criterio 10).
    # ------------------------------------------------------------------ #
    op.add_column(
        "pago",
        sa.Column(
            "credito_aplicado",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # ------------------------------------------------------------------ #
    # 3) Tabla nueva tenant `credito` -- nombre/columnas/tipos/FKs/constraints
    #    EXACTOS. org_id denormalizado (NOT NULL) para RLS. UNIQUE(inscripcion_id)
    #    => un solo credito por inscripcion (el upsert RF-ABO-06 se apoya aqui).
    #    CHECK(saldo >= 0) como ultima barrera de invariante.
    # ------------------------------------------------------------------ #
    op.create_table(
        "credito",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizacion.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "inscripcion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inscripcion.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "saldo",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "inscripcion_id", name="uq_credito_inscripcion_id"
        ),
        sa.CheckConstraint(
            "saldo >= 0", name="ck_credito_saldo_no_negativo"
        ),
    )

    # Indice del org_id (acceso scoped por tenant; KPI credito_total = Sum(saldo)
    # de la org). El UNIQUE(inscripcion_id) ya cubre el lookup por inscripcion.
    op.create_index("ix_credito_org_id", "credito", ["org_id"])

    # ------------------------------------------------------------------ #
    # 4) RLS de `credito`: ENABLE + FORCE + policy org_isolation con el patron
    #    fail-closed NULLIF (0003) -> sin contexto / GUC reseteado a '' -> NULL
    #    -> 0 filas (y NULL no pasa WITH CHECK). Sin `TO rol` en la policy.
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY org_isolation ON {table} "
            f"USING ({_EXPR}) WITH CHECK ({_EXPR});"
        )

    # ------------------------------------------------------------------ #
    # 5) GRANTs explicitos a latinosport_app sobre la tabla nueva (DML) y las
    #    secuencias. 0001 ya fijo ALTER DEFAULT PRIVILEGES para objetos futuros,
    #    pero los hacemos explicitos aqui para no depender de ello (replica 0008).
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO latinosport_app;"
        )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO latinosport_app;"
    )

    # ------------------------------------------------------------------ #
    # 6) Data migration (retrocompat, criterio 9): una cuota antigua PAGADO
    #    queda con monto_pagado = monto (saldo = 0). El resto se queda en 0 (el
    #    default de la columna). NO se crean filas en `credito`.
    # ------------------------------------------------------------------ #
    op.execute("UPDATE cuota SET monto_pagado = monto WHERE estado = 'PAGADO'")


def downgrade() -> None:
    # Orden inverso. Empezar por las policies de `credito` (el drop de tabla las
    # eliminaria igual, pero somos explicitos como en 0008).
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Drop de la tabla credito (elimina su indice, UNIQUE, CHECK y la policy).
    op.drop_table("credito")

    # Quitar pago.credito_aplicado.
    op.drop_column("pago", "credito_aplicado")

    # Quitar cuota.monto_pagado.
    op.drop_column("cuota", "monto_pagado")

    # Restaurar el CHECK original de estado (sin 'PARCIAL'). Nota: si quedaran
    # filas en estado 'PARCIAL' este ADD fallaria -- es correcto: el downgrade no
    # debe perder silenciosamente cuotas a medias.
    op.drop_constraint("ck_cuota_estado", "cuota", type_="check")
    op.create_check_constraint(
        "ck_cuota_estado",
        "cuota",
        "estado IN ('PENDIENTE','PAGADO','VENCIDO')",
    )
