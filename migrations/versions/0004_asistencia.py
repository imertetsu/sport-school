"""asistencia: sesion / asistencia + RLS (NULLIF fail-closed) + GRANTs

Migracion del epic Asistencia de CanteraSport, escrita A MANO (no autogenerada):
- RLS / GRANTs no los detecta `--autogenerate`.
- Corre sobre la BD de los slices Alumnos (0001) + Cobranza (0002) + hardening
  RLS (0003) ya viva; main aplica el upgrade.

Contratos implementados (docs/specs/asistencia.md):
- C1: esquema de `sesion` y `asistencia` (tablas tenant con org_id) con tipos,
  FKs, CHECK de estado, UNIQUE e indice EXACTOS:
  - sesion: UNIQUE(categoria_id, fecha, hora) (no duplicar sesion; hora NULL
    cuenta como una por dia). Indice (org_id, categoria_id, fecha).
  - asistencia: sesion_id ON DELETE CASCADE, CHECK estado IN
    ('PRESENTE','AUSENTE'), UNIQUE(sesion_id, alumno_id) (idempotencia del
    guardado).

RLS: ambas tablas llevan ENABLE + FORCE + policy `org_isolation` con el patron
fail-closed NUEVO de 0003: `NULLIF(current_setting('app.current_org', true),
'')::uuid`. Asi tanto el caso "nunca seteado" (NULL) como el "reseteado a vacio"
('' tras SET LOCAL + commit en el pool) colapsan a NULL -> 0 filas. GRANTs DML a
`cantera_app` + USAGE/SELECT en secuencias.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas tenant (con org_id) de este epic: ambas llevan RLS habilitada + forzada
# y reciben GRANT de DML + USAGE/SELECT sobre sus secuencias.
TENANT_TABLES: tuple[str, ...] = (
    "sesion",
    "asistencia",
)

# Expresion fail-closed NUEVA (0003): '' (GUC reseteado) y NULL (nunca seteado)
# -> NULL -> 0 filas y no pasa WITH CHECK.
_EXPR = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def _uuid_pk() -> sa.Column:
    """PK UUID con default a nivel servidor via pgcrypto.gen_random_uuid()."""
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _org_fk() -> sa.Column:
    """Columna org_id NOT NULL -> organizacion(id), denormalizada para RLS."""
    return sa.Column(
        "org_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("organizacion.id", ondelete="CASCADE"),
        nullable=False,
    )


def _created_at() -> sa.Column:
    """created_at timestamptz con default now()."""
    return sa.Column(
        "created_at",
        sa.TIMESTAMP(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Tablas (C1) -- nombres/columnas/tipos/FKs/constraints EXACTOS.
    # ------------------------------------------------------------------ #

    # sesion -- categoria_id -> categoria, entrenador_id -> entrenador (null).
    # UNIQUE(categoria_id, fecha, hora) evita duplicar la misma sesion (hora
    # NULL cuenta como una por dia). created_at timestamptz now().
    op.create_table(
        "sesion",
        _uuid_pk(),
        _org_fk(),
        sa.Column(
            "categoria_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("categoria.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("hora", sa.Time(), nullable=True),
        sa.Column(
            "entrenador_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entrenador.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notas", sa.Text(), nullable=True),
        _created_at(),
        sa.UniqueConstraint(
            "categoria_id",
            "fecha",
            "hora",
            name="uq_sesion_categoria_fecha_hora",
        ),
    )

    # asistencia -- sesion_id -> sesion (ON DELETE CASCADE), alumno_id -> alumno,
    # registrado_por -> usuario (null). CHECK estado PRESENTE|AUSENTE.
    # UNIQUE(sesion_id, alumno_id) da idempotencia del guardado (upsert).
    # created_at + updated_at timestamptz now().
    op.create_table(
        "asistencia",
        _uuid_pk(),
        _org_fk(),
        sa.Column(
            "sesion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sesion.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "alumno_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alumno.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("estado", sa.Text(), nullable=False),
        sa.Column(
            "registrado_por",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "sesion_id",
            "alumno_id",
            name="uq_asistencia_sesion_alumno",
        ),
        sa.CheckConstraint(
            "estado IN ('PRESENTE','AUSENTE')",
            name="ck_asistencia_estado",
        ),
    )

    # ------------------------------------------------------------------ #
    # 2) Indices: el indicado por C1 (listado/roster por categoria+fecha) +
    #    FKs de acceso frecuente.
    # ------------------------------------------------------------------ #
    op.create_index(
        "ix_sesion_org_categoria_fecha",
        "sesion",
        ["org_id", "categoria_id", "fecha"],
    )
    op.create_index("ix_sesion_entrenador_id", "sesion", ["entrenador_id"])
    op.create_index("ix_asistencia_org_id", "asistencia", ["org_id"])
    op.create_index("ix_asistencia_sesion_id", "asistencia", ["sesion_id"])
    op.create_index("ix_asistencia_alumno_id", "asistencia", ["alumno_id"])
    op.create_index(
        "ix_asistencia_registrado_por", "asistencia", ["registrado_por"]
    )

    # ------------------------------------------------------------------ #
    # 3) RLS: por cada tabla tenant nueva, ENABLE + FORCE + policy
    #    org_isolation con el patron fail-closed NUEVO (0003):
    #    NULLIF(current_setting('app.current_org', true), '')::uuid
    #    -> sin contexto / GUC reseteado a '' -> NULL -> 0 filas (y NULL no
    #    pasa WITH CHECK).
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY org_isolation ON {table} "
            f"USING ({_EXPR}) WITH CHECK ({_EXPR});"
        )

    # ------------------------------------------------------------------ #
    # 4) GRANTs explicitos a cantera_app sobre las tablas nuevas (DML) y sus
    #    secuencias. 0001 ya fijo ALTER DEFAULT PRIVILEGES para objetos
    #    futuros, pero los hacemos explicitos aqui para no depender de ello.
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cantera_app;"
        )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cantera_app;"
    )


def downgrade() -> None:
    # Orden inverso. Empezar por las policies.
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Drop de tablas en orden inverso (respeta FKs):
    # asistencia (referencia sesion) -> sesion.
    op.drop_table("asistencia")
    op.drop_table("sesion")
