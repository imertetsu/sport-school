"""horarios: tabla `horario_clase` + ALTER `sesion` (2 cols) + RLS (NULLIF) + GRANTs

Migracion del epic Programacion de clases (Fase 2) de LatinoSport. Escrita A MANO
(no autogenerada): RLS / GRANTs / ALTER de RLS-ajenos no los detecta
`--autogenerate`. Corre sobre la BD con Alumnos (0001) + Cobranza (0002) +
hardening RLS (0003) + Asistencia (0004) + Egresos (0005) + Avisos (0006) ya viva;
main aplica el upgrade en F4.

Contrato implementado (docs/specs/programacion-clases.md, C1):
- Tabla tenant `horario_clase` (NUEVA) -- horarios recurrentes de clase por
  categoria (dia/horas). `org_id` denormalizado (NOT NULL) para RLS.
  Columnas/tipos/FKs/constraints EXACTOS al modelo SQLAlchemy `HorarioClase`
  (backend->db es contrato compartido; si una columna cambia tras empezar,
  handoff y parar, no driftear el esquema en un solo lado):
  - id uuid PK gen_random_uuid()
  - org_id uuid -> organizacion(id) ON DELETE CASCADE, NOT NULL
  - categoria_id uuid -> categoria(id) ON DELETE CASCADE, NOT NULL
  - dia_semana smallint NOT NULL, CHECK dia_semana BETWEEN 0 AND 6
    (0=Lunes ... 6=Domingo, = date.weekday())
  - hora_inicio time NOT NULL
  - hora_fin time NOT NULL
  - entrenador_id uuid -> entrenador(id) ON DELETE SET NULL, NULLABLE
  - activo bool default true NOT NULL (soft-delete: DELETE => activo=false)
  - created_at timestamptz now() NOT NULL
  - UNIQUE(categoria_id, dia_semana, hora_inicio) `uq_horario_categoria_dia_inicio`
    (no duplicar el mismo bloque por categoria/dia/hora de inicio).
  - Indice (org_id, categoria_id) para los listados scoped por categoria.

  Nota: la validacion `hora_fin > hora_inicio` la hace el BACKEND (422 en C2),
  NO un CHECK de BD -- aqui solo el CHECK del rango de dia_semana.

- Tabla tenant `sesion` (EXISTE desde 0004) -- ALTER, columnas NULLABLE, NO rompe
  Asistencia (sus tests siguen verdes):
  - add `horario_id` uuid -> horario_clase(id) ON DELETE SET NULL, NULLABLE.
    Las sesiones generadas por el cron desde un horario lo enlazan; las creadas a
    mano (Asistencia) quedan NULL. SET NULL: borrar el horario no borra la sesion.
  - add `recordatorio_enviado_en` timestamptz NULLABLE. Marca de idempotencia del
    recordatorio (el cron solo notifica si IS NULL, luego setea now()).

RLS: `horario_clase` lleva ENABLE + FORCE + policy `org_isolation` con el patron
fail-closed de 0003: `NULLIF(current_setting('app.current_org', true), '')::uuid`.
Asi tanto el caso "nunca seteado" (NULL) como el "reseteado a vacio" ('' tras SET
LOCAL + commit en el pool) colapsan a NULL -> 0 filas y no pasan WITH CHECK. Las
columnas nuevas de `sesion` heredan la RLS ya existente de esa tabla (0004). GRANTs
DML a `latinosport_app` + USAGE/SELECT en secuencias (replica 0006; el PK usa
gen_random_uuid(), no secuencia, pero mantenemos el grant por consistencia e
idempotencia).

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas tenant (con org_id) NUEVAS de este epic: llevan RLS habilitada + forzada
# y reciben GRANT de DML + USAGE/SELECT sobre las secuencias del schema. `sesion`
# (0004) ya tiene su RLS/GRANTs; aqui solo le agregamos columnas (no se re-lista).
TENANT_TABLES: tuple[str, ...] = ("horario_clase",)

# Expresion fail-closed (0003): '' (GUC reseteado) y NULL (nunca seteado)
# -> NULL -> 0 filas y no pasa WITH CHECK.
_EXPR = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Tabla horario_clase (C1) -- nombre/columnas/tipos/FKs/constraints
    #    EXACTOS. org_id denormalizado (NOT NULL) para RLS. categoria_id NOT
    #    NULL (un horario siempre pertenece a una categoria). dia_semana con
    #    CHECK 0..6 (0=Lunes ... 6=Domingo = date.weekday()). entrenador_id
    #    NULLABLE (SET NULL: borrar el entrenador no borra el horario). activo
    #    soporta el soft-delete (DELETE => activo=false). UNIQUE por
    #    (categoria_id, dia_semana, hora_inicio) evita duplicar el bloque.
    # ------------------------------------------------------------------ #
    op.create_table(
        "horario_clase",
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
            "categoria_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("categoria.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dia_semana", sa.SmallInteger(), nullable=False),
        sa.Column("hora_inicio", sa.Time(), nullable=False),
        sa.Column("hora_fin", sa.Time(), nullable=False),
        sa.Column(
            "entrenador_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entrenador.id", ondelete="SET NULL"),
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
            "dia_semana BETWEEN 0 AND 6",
            name="ck_horario_dia_semana",
        ),
        sa.UniqueConstraint(
            "categoria_id",
            "dia_semana",
            "hora_inicio",
            name="uq_horario_categoria_dia_inicio",
        ),
    )

    # ------------------------------------------------------------------ #
    # 2) Indice indicado por C1: listados scoped por (org_id, categoria_id).
    # ------------------------------------------------------------------ #
    op.create_index(
        "ix_horario_clase_org_categoria",
        "horario_clase",
        ["org_id", "categoria_id"],
    )

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
    #    (replica 0006).
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO latinosport_app;"
        )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO latinosport_app;"
    )

    # ------------------------------------------------------------------ #
    # 5) ALTER sesion (EXISTE desde 0004) -- 2 columnas NULLABLE que NO rompen
    #    Asistencia. horario_id enlaza la sesion con el horario que la genero
    #    (ON DELETE SET NULL: borrar el horario no borra la sesion ni su
    #    asistencia). recordatorio_enviado_en es la marca de idempotencia del
    #    recordatorio del cron. Indexamos horario_id (el cron busca sesiones por
    #    horario al generar/enlazar).
    # ------------------------------------------------------------------ #
    op.add_column(
        "sesion",
        sa.Column(
            "horario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("horario_clase.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "sesion",
        sa.Column(
            "recordatorio_enviado_en",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.create_index("ix_sesion_horario_id", "sesion", ["horario_id"])


def downgrade() -> None:
    # Orden inverso y respetando la dependencia FK: la columna sesion.horario_id
    # apunta a horario_clase, asi que PRIMERO quitamos las columnas/FK de sesion
    # y LUEGO dropeamos horario_clase. Si no, el drop_table fallaria por la FK.

    # 5') Quitar las 2 columnas de sesion (y su indice). Esto elimina tambien la
    #     FK sesion.horario_id -> horario_clase.
    op.drop_index("ix_sesion_horario_id", table_name="sesion")
    op.drop_column("sesion", "recordatorio_enviado_en")
    op.drop_column("sesion", "horario_id")

    # 3'/4') Policies de horario_clase (el drop de tabla las eliminaria igual,
    #        pero somos explicitos como en 0006).
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # 1') Drop de la tabla (elimina su indice y la policy restante).
    op.drop_table("horario_clase")
