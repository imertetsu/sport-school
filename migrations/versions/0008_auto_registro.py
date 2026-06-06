"""auto_registro: tabla `solicitud_registro` + RLS (NULLIF) + GRANTs

Migracion del epic Auto-registro de alumno (Fase 2, version EN SISTEMA) de
CanteraSport. Escrita A MANO (no autogenerada): RLS / GRANTs no los detecta
`--autogenerate`. Corre sobre la BD con Alumnos (0001) + Cobranza (0002) +
hardening RLS (0003) + Asistencia (0004) + Egresos (0005) + Avisos (0006) +
Horarios (0007) ya viva; main aplica el upgrade en F4.

CAMBIO de diseno (decision del usuario): la version EN SISTEMA NO tiene link
publico ni token. El entrenador/admin captura la solicitud logueado, queda en
cola PENDIENTE y el admin aprueba (crea el alumno real) o rechaza. Por eso esta
migracion crea SOLO `solicitud_registro` y NO toca `organizacion` (sin
`registro_token`).

Contrato implementado (docs/specs/auto-registro.md, C1):
- Tabla tenant `solicitud_registro` (NUEVA) -- cola de altas de alumno pendientes
  de aprobacion. `org_id` denormalizado (NOT NULL) para RLS.
  Columnas/tipos/FKs/constraints EXACTOS al modelo SQLAlchemy `SolicitudRegistro`
  (backend->db es contrato compartido; si una columna cambia tras empezar,
  handoff y parar, no driftear el esquema en un solo lado):
  - id uuid PK gen_random_uuid()
  - org_id uuid -> organizacion(id) ON DELETE CASCADE, NOT NULL
  - estado text NOT NULL default 'PENDIENTE',
    CHECK estado IN ('PENDIENTE','APROBADA','RECHAZADA')
  datos alumno:
  - ap_paterno text NOT NULL
  - ap_materno text NOT NULL
  - nombres text NOT NULL
  - ci text NOT NULL
  - disciplina text NOT NULL
  - fecha_nac date NOT NULL
  - contacto_emergencia text NULLABLE
  - ficha_medica jsonb NULLABLE
  datos tutor:
  - tutor_nombres text NOT NULL
  - tutor_telefono text NOT NULL
  - tutor_ci text NULLABLE
  - parentesco text NOT NULL
  consentimiento:
  - consent_version text NOT NULL
  - consent_canal text NOT NULL default 'SISTEMA'
  - consent_aceptado_en timestamptz NOT NULL
  sugerencia (lo administrativo lo decide el admin al aprobar; aqui solo se sugiere):
  - sucursal_sugerida_id uuid -> sucursal(id) ON DELETE SET NULL, NULLABLE
  - categoria_sugerida_id uuid -> categoria(id) ON DELETE SET NULL, NULLABLE
  captura:
  - creado_por uuid -> usuario(id) ON DELETE SET NULL, NULLABLE (quien la registro)
  resultado:
  - alumno_id uuid -> alumno(id) ON DELETE SET NULL, NULLABLE (alumno creado al aprobar)
  - motivo_rechazo text NULLABLE
  - revisado_por uuid -> usuario(id) ON DELETE SET NULL, NULLABLE
  - revisado_en timestamptz NULLABLE
  - created_at timestamptz now() NOT NULL
  - Indice (org_id, estado, created_at) `ix_solicitud_registro_org_estado_created`
    para la cola (filtra por estado dentro de la org + ordena por created_at).

  Nota: las validaciones duras (consentimiento aceptado, datos minimos del tutor,
  sucursal sugerida dentro del alcance del entrenador) las hace el BACKEND (422 /
  403 en C2), NO un CHECK de BD -- aqui solo el CHECK del enum de estado.

RLS: ENABLE + FORCE + policy `org_isolation` con el patron fail-closed de 0003:
`NULLIF(current_setting('app.current_org', true), '')::uuid`. Asi tanto el caso
"nunca seteado" (NULL) como el "reseteado a vacio" ('' tras SET LOCAL + commit en
el pool) colapsan a NULL -> 0 filas y no pasan WITH CHECK. GRANTs DML a
`cantera_app` + USAGE/SELECT en secuencias (replica 0007; el PK usa
gen_random_uuid(), no secuencia, pero mantenemos el grant por consistencia e
idempotencia).

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas tenant (con org_id) NUEVAS de este epic: llevan RLS habilitada + forzada
# y reciben GRANT de DML + USAGE/SELECT sobre las secuencias del schema. NO se
# toca `organizacion` (sin registro_token): la version EN SISTEMA no tiene link
# publico.
TENANT_TABLES: tuple[str, ...] = ("solicitud_registro",)

# Expresion fail-closed (0003): '' (GUC reseteado) y NULL (nunca seteado)
# -> NULL -> 0 filas y no pasa WITH CHECK.
_EXPR = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Tabla solicitud_registro (C1) -- nombre/columnas/tipos/FKs/constraints
    #    EXACTOS. org_id denormalizado (NOT NULL) para RLS. estado con CHECK del
    #    enum (def PENDIENTE). Datos de alumno/tutor/consentimiento NOT NULL
    #    (las validaciones de negocio las hace el backend, 422). Las FKs de
    #    sugerencia/captura/resultado van ON DELETE SET NULL para no perder la
    #    solicitud (auditoria) si se borra la sucursal/categoria/usuario/alumno.
    # ------------------------------------------------------------------ #
    op.create_table(
        "solicitud_registro",
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
            "estado",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'PENDIENTE'"),
        ),
        # datos alumno
        sa.Column("ap_paterno", sa.Text(), nullable=False),
        sa.Column("ap_materno", sa.Text(), nullable=False),
        sa.Column("nombres", sa.Text(), nullable=False),
        sa.Column("ci", sa.Text(), nullable=False),
        sa.Column("disciplina", sa.Text(), nullable=False),
        sa.Column("fecha_nac", sa.Date(), nullable=False),
        sa.Column("contacto_emergencia", sa.Text(), nullable=True),
        sa.Column(
            "ficha_medica",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        # datos tutor
        sa.Column("tutor_nombres", sa.Text(), nullable=False),
        sa.Column("tutor_telefono", sa.Text(), nullable=False),
        sa.Column("tutor_ci", sa.Text(), nullable=True),
        sa.Column("parentesco", sa.Text(), nullable=False),
        # consentimiento
        sa.Column("consent_version", sa.Text(), nullable=False),
        sa.Column(
            "consent_canal",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'SISTEMA'"),
        ),
        sa.Column(
            "consent_aceptado_en",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        # sugerencia (el admin decide lo administrativo al aprobar)
        sa.Column(
            "sucursal_sugerida_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sucursal.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "categoria_sugerida_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("categoria.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # captura
        sa.Column(
            "creado_por",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # resultado
        sa.Column(
            "alumno_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alumno.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("motivo_rechazo", sa.Text(), nullable=True),
        sa.Column(
            "revisado_por",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "revisado_en",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "estado IN ('PENDIENTE','APROBADA','RECHAZADA')",
            name="ck_solicitud_registro_estado",
        ),
    )

    # ------------------------------------------------------------------ #
    # 2) Indice indicado por C1: cola scoped por (org_id, estado, created_at)
    #    -- filtra por estado dentro de la org y ordena por created_at.
    # ------------------------------------------------------------------ #
    op.create_index(
        "ix_solicitud_registro_org_estado_created",
        "solicitud_registro",
        ["org_id", "estado", "created_at"],
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
    # 4) GRANTs explicitos a cantera_app sobre la tabla nueva (DML) y las
    #    secuencias. 0001 ya fijo ALTER DEFAULT PRIVILEGES para objetos
    #    futuros, pero los hacemos explicitos aqui para no depender de ello
    #    (replica 0007).
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cantera_app;"
        )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cantera_app;"
    )


def downgrade() -> None:
    # Orden inverso. Empezar por las policies (el drop de tabla las eliminaria
    # igual, pero somos explicitos como en 0007).
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Drop de la tabla (elimina su indice y la policy restante).
    op.drop_table("solicitud_registro")
