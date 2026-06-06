"""avisos: tabla `aviso` (muro de avisos) + RLS (NULLIF fail-closed) + GRANTs

Migracion del epic Muro de avisos (RF-COM-01) de LatinoSport -- ULTIMO epic del
MVP fase 1. Escrita A MANO (no autogenerada): RLS / GRANTs no los detecta
`--autogenerate`. Corre sobre la BD con Alumnos (0001) + Cobranza (0002) +
hardening RLS (0003) + Asistencia (0004) + Egresos (0005) ya viva; main aplica
el upgrade en F4.

Contrato implementado (docs/specs/muro-avisos.md, C1):
- Tabla tenant `aviso` (avisos administrados centralmente: clima, cancelaciones,
  convocatorias) con `org_id` denormalizado para RLS. Columnas/tipos/FKs EXACTOS
  al modelo SQLAlchemy `Aviso` (backend->db es contrato compartido; si una
  columna cambia tras empezar, handoff y parar, no driftear el esquema en un
  solo lado):
  - id uuid PK gen_random_uuid()
  - org_id uuid -> organizacion(id) ON DELETE CASCADE, NOT NULL
  - titulo text NOT NULL
  - cuerpo text NOT NULL
  - alcance text NOT NULL, CHECK alcance IN ('ORG','SUCURSAL','CATEGORIA')
  - sucursal_id uuid -> sucursal(id) ON DELETE SET NULL, NULLABLE
  - categoria_id uuid -> categoria(id) ON DELETE SET NULL, NULLABLE
  - publicado_en timestamptz now() NOT NULL
  - vigente_hasta date NULL (NULL = sin caducidad)
  - creado_por uuid -> usuario(id) ON DELETE SET NULL, NULL (auditoria RNF-03)
  - activo bool default true NOT NULL (soft-delete: DELETE => activo=false)
  - created_at timestamptz now() NOT NULL
- Indice (org_id, activo, publicado_en) `ix_aviso_org_activo_publicado` para el
  feed (filtra activo + ordena por publicado_en desc) + indices de FK de acceso
  frecuente (sucursal_id, categoria_id).

  Nota: la INVARIANTE de alcance (SUCURSAL => sucursal_id no nulo; CATEGORIA =>
  categoria_id no nulo; ORG => ambos nulos) la valida el BACKEND (422 en C1/C2),
  NO un CHECK de BD -- aqui solo el CHECK del enum de alcance.

RLS: ENABLE + FORCE + policy `org_isolation` con el patron fail-closed de 0003:
`NULLIF(current_setting('app.current_org', true), '')::uuid`. Asi tanto el caso
"nunca seteado" (NULL) como el "reseteado a vacio" ('' tras SET LOCAL + commit en
el pool) colapsan a NULL -> 0 filas y no pasan WITH CHECK. GRANTs DML a
`latinosport_app` + USAGE/SELECT en secuencias (replica 0005; el PK usa
gen_random_uuid(), no secuencia, pero mantenemos el grant de secuencias por
consistencia con 0005 e idempotencia).

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas tenant (con org_id) de este epic: lleva RLS habilitada + forzada y
# recibe GRANT de DML + USAGE/SELECT sobre las secuencias del schema.
TENANT_TABLES: tuple[str, ...] = ("aviso",)

# Expresion fail-closed (0003): '' (GUC reseteado) y NULL (nunca seteado)
# -> NULL -> 0 filas y no pasa WITH CHECK.
_EXPR = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Tabla (C1) -- nombre/columnas/tipos/FKs/constraints EXACTOS.
    # ------------------------------------------------------------------ #

    # aviso -- muro de avisos administrado centralmente. org_id denormalizado
    # (NOT NULL) para RLS. alcance ('ORG'|'SUCURSAL'|'CATEGORIA') con CHECK del
    # enum; sucursal_id / categoria_id NULLABLE (la invariante por alcance la
    # valida el backend, 422). creado_por -> usuario (null en SET NULL) para
    # auditoria (RNF-03). publicado_en = fecha de publicacion (distinta de
    # created_at). vigente_hasta NULL = sin caducidad. activo soporta el
    # soft-delete (DELETE => activo=false; sin borrado fisico).
    op.create_table(
        "aviso",
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
        sa.Column("titulo", sa.Text(), nullable=False),
        sa.Column("cuerpo", sa.Text(), nullable=False),
        sa.Column("alcance", sa.Text(), nullable=False),
        sa.Column(
            "sucursal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sucursal.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "categoria_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("categoria.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "publicado_en",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("vigente_hasta", sa.Date(), nullable=True),
        sa.Column(
            "creado_por",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "activo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "alcance IN ('ORG','SUCURSAL','CATEGORIA')",
            name="ck_aviso_alcance",
        ),
    )

    # ------------------------------------------------------------------ #
    # 2) Indices: el indicado por C1 (feed: filtra activo + ordena por
    #    publicado_en desc) + FKs de acceso frecuente.
    # ------------------------------------------------------------------ #
    op.create_index(
        "ix_aviso_org_activo_publicado",
        "aviso",
        ["org_id", "activo", "publicado_en"],
    )
    op.create_index("ix_aviso_sucursal_id", "aviso", ["sucursal_id"])
    op.create_index("ix_aviso_categoria_id", "aviso", ["categoria_id"])

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
    #    (replica 0005).
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
    # igual, pero somos explicitos como en 0005).
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Drop de la tabla (elimina sus indices y la policy restante).
    op.drop_table("aviso")
