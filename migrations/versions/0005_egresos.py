"""egresos: tabla `egreso` (modulo financiero) + RLS (NULLIF fail-closed) + GRANTs

Migracion del epic Egresos (RF-FIN-07) de LatinoSport, escrita A MANO (no
autogenerada): RLS / GRANTs no los detecta `--autogenerate`. Corre sobre la BD
con Alumnos (0001) + Cobranza (0002) + hardening RLS (0003) + Asistencia (0004)
ya viva; main aplica el upgrade en F4.

Contrato implementado (docs/specs/egresos.md, C1):
- Tabla tenant `egreso` (registro de gastos: alquiler, material, sueldos, etc.)
  con `org_id` denormalizado para RLS. Columnas/tipos/FKs EXACTOS al modelo
  SQLAlchemy `Egreso` (backend->db es contrato compartido; si una columna cambia
  tras empezar, handoff y parar, no driftear el esquema en un solo lado):
  - id uuid PK gen_random_uuid()
  - org_id uuid -> organizacion(id) ON DELETE CASCADE, NOT NULL
  - sucursal_id uuid -> sucursal(id) ON DELETE SET NULL, NULLABLE (gasto a nivel org)
  - categoria_gasto text NOT NULL (texto libre en MVP)
  - monto numeric(10,2) NOT NULL (regla monto > 0 se valida en API/422)
  - fecha date NOT NULL (fecha del gasto, distinta de created_at)
  - descripcion text NULL
  - registrado_por uuid -> usuario(id) ON DELETE SET NULL, NULL (auditoria RNF-03)
  - created_at timestamptz now() NOT NULL
- Indice (org_id, fecha) `ix_egreso_org_fecha` para el listado/filtro por rango +
  indices de FK de acceso frecuente (sucursal_id, registrado_por).

RLS: ENABLE + FORCE + policy `org_isolation` con el patron fail-closed de 0003:
`NULLIF(current_setting('app.current_org', true), '')::uuid`. Asi tanto el caso
"nunca seteado" (NULL) como el "reseteado a vacio" ('' tras SET LOCAL + commit en
el pool) colapsan a NULL -> 0 filas y no pasan WITH CHECK. GRANTs DML a
`latinosport_app` + USAGE/SELECT en secuencias (replica 0004; el PK usa
gen_random_uuid(), no secuencia, pero mantenemos el grant de secuencias por
consistencia con 0004 e idempotencia).

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas tenant (con org_id) de este epic: lleva RLS habilitada + forzada y
# recibe GRANT de DML + USAGE/SELECT sobre las secuencias del schema.
TENANT_TABLES: tuple[str, ...] = ("egreso",)

# Expresion fail-closed (0003): '' (GUC reseteado) y NULL (nunca seteado)
# -> NULL -> 0 filas y no pasa WITH CHECK.
_EXPR = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Tabla (C1) -- nombre/columnas/tipos/FKs/constraints EXACTOS.
    # ------------------------------------------------------------------ #

    # egreso -- registro de gastos de la escuela. org_id denormalizado (NOT NULL)
    # para RLS; sucursal_id NULLABLE (gasto a nivel org). registrado_por ->
    # usuario (null en SET NULL) para auditoria (RNF-03). fecha = fecha del gasto
    # (distinta de created_at). monto numeric(10,2); la regla monto > 0 vive en
    # la API (422).
    op.create_table(
        "egreso",
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
            "sucursal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sucursal.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("categoria_gasto", sa.Text(), nullable=False),
        sa.Column("monto", sa.Numeric(10, 2), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column(
            "registrado_por",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------ #
    # 2) Indices: el indicado por C1 (listado/filtro por rango de fechas) +
    #    FKs de acceso frecuente.
    # ------------------------------------------------------------------ #
    op.create_index("ix_egreso_org_fecha", "egreso", ["org_id", "fecha"])
    op.create_index("ix_egreso_sucursal_id", "egreso", ["sucursal_id"])
    op.create_index("ix_egreso_registrado_por", "egreso", ["registrado_por"])

    # ------------------------------------------------------------------ #
    # 3) RLS: ENABLE + FORCE + policy org_isolation con el patron fail-closed
    #    NULLIF (0003) -> sin contexto / GUC reseteado a '' -> NULL -> 0 filas
    #    (y NULL no pasa WITH CHECK).
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY org_isolation ON {table} "
            f"USING ({_EXPR}) WITH CHECK ({_EXPR});"
        )

    # ------------------------------------------------------------------ #
    # 4) GRANTs explicitos a latinosport_app sobre la tabla nueva (DML) y las
    #    secuencias. 0001 ya fijo ALTER DEFAULT PRIVILEGES para objetos
    #    futuros, pero los hacemos explicitos aqui para no depender de ello
    #    (replica 0004).
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO latinosport_app;"
        )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO latinosport_app;"
    )


def downgrade() -> None:
    # Orden inverso. Empezar por las policies (el drop de tabla las eliminaria
    # igual, pero somos explicitos como en 0004).
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Drop de la tabla (elimina sus indices y la policy restante).
    op.drop_table("egreso")
