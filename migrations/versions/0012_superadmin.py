"""superadmin: identidad de plataforma (plataforma_admin) + estado de escuela
(organizacion.estado) + auditoria de plataforma (plataforma_auditoria) + GRANTs

Migracion del epic Super Admin (consola de plataforma / onboarding del SaaS) de
LatinoSport. Escrita A MANO (no autogenerada): GRANTs no los detecta
`--autogenerate`. Corre sobre la BD con Alumnos (0001) + Cobranza (0002) +
hardening RLS (0003) + Asistencia (0004) + Egresos (0005) + Avisos (0006) +
Horarios (0007) + Auto-registro (0008) + Abonos (0009) + Recibo (0010) +
Recordatorio de pago (0011) ya viva; main aplica el upgrade en la fase de cierre.

Contrato implementado (docs/specs/super-admin.md, C1) -- el esquema de columnas
(tipos/nullability/defaults/constraints) es contrato compartido con backend-dev
(sus modelos `plataforma_admin` y `plataforma_auditoria` + el campo
`organizacion.estado` deben reflejarlo EXACTAMENTE; los modelos se crean EN
PARALELO con estas mismas columnas/constraints. La AUTORIDAD del esquema es esta
migracion. Si una columna cambia tras empezar, handoff y parar, no driftear el
esquema en un solo lado):

- Tabla nueva `plataforma_admin` -- identidad del operador de plataforma. SIN
  org_id y SIN RLS (como `organizacion`, la unica otra tabla sin RLS): el
  SUPERADMIN no tiene contexto de tenant; una tabla con RLS le quedaria
  inaccesible.
  - id uuid PK gen_random_uuid()
  - email text NOT NULL UNIQUE (`uq_plataforma_admin_email`) -- login de plataforma
  - password_hash text NOT NULL (bcrypt, security.hash_password)
  - nombre text NOT NULL
  - activo boolean NOT NULL DEFAULT true
  - created_at / updated_at timestamptz now() NOT NULL

- Columna nueva en `organizacion` (tabla sin RLS):
  - estado text NOT NULL DEFAULT 'ACTIVA', CHECK estado IN ('ACTIVA','SUSPENDIDA')
    (`ck_organizacion_estado`). NOT NULL + server_default => las filas existentes
    quedan 'ACTIVA' en el backfill implicito del ADD COLUMN. Mantenemos el
    server_default (inocuo y util para INSERTs futuros).

- Tabla nueva `plataforma_auditoria` -- log inmutable de acciones de plataforma.
  SIN RLS (la accion la ejecuta el SUPERADMIN, sin contexto de org; una tabla
  tenant con RLS le quedaria inaccesible). org_id es aqui solo un dato (escuela
  afectada), NO scope RLS.
  - id uuid PK gen_random_uuid()
  - admin_id uuid NOT NULL (plataforma_admin.id que ejecuto; sin FK cross-RLS
    obligatoria, decision de diseno -- el log sobrevive como dato historico)
  - accion text NOT NULL, CHECK accion IN
    ('CREAR_ESCUELA','SUSPENDER_ESCUELA','REACTIVAR_ESCUELA')
    (`ck_plataforma_auditoria_accion`)
  - org_id uuid NOT NULL (escuela afectada; dato, no scope RLS)
  - detalle text NULL (opcional, p.ej. nombre/email del admin creado)
  - created_at timestamptz now() NOT NULL

GRANTs explicitos de DML a `latinosport_app` sobre `plataforma_admin` y
`plataforma_auditoria` (replica el patron de 0010/0011). `organizacion` ya tiene
sus grants de 0001. Mantenemos `GRANT USAGE, SELECT ON ALL SEQUENCES` por
consistencia con 0010/0011 (los PK usan gen_random_uuid(), no secuencia).

NOTA RLS: NINGUNA de las dos tablas nuevas habilita RLS (son tablas de
plataforma, NO tenant). NO se toca el rol `latinosport_app` (sigue NOSUPERUSER
NOBYPASSRLS de 0001).

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas de plataforma (NO tenant): SIN org_id de scope y SIN RLS, como
# `organizacion`. Solo reciben GRANT de DML a latinosport_app.
PLATFORM_TABLES: tuple[str, ...] = ("plataforma_admin", "plataforma_auditoria")


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Tabla nueva `plataforma_admin` -- identidad del operador de plataforma.
    #    SIN org_id y SIN RLS (replica el patron de `organizacion` de 0001:
    #    PK gen_random_uuid() + created_at/updated_at now()). email UNIQUE para
    #    el login de plataforma.
    # ------------------------------------------------------------------ #
    op.create_table(
        "plataforma_admin",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
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
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_plataforma_admin_email"),
    )

    # ------------------------------------------------------------------ #
    # 2) Columna nueva `organizacion.estado` (tabla sin RLS). NOT NULL con
    #    server_default 'ACTIVA' => las filas existentes quedan 'ACTIVA' en el
    #    backfill implicito del ADD COLUMN. CHECK del enum del estado.
    # ------------------------------------------------------------------ #
    op.add_column(
        "organizacion",
        sa.Column(
            "estado",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'ACTIVA'"),
        ),
    )
    op.create_check_constraint(
        "ck_organizacion_estado",
        "organizacion",
        "estado IN ('ACTIVA','SUSPENDIDA')",
    )

    # ------------------------------------------------------------------ #
    # 3) Tabla nueva `plataforma_auditoria` -- log inmutable de acciones de
    #    plataforma. SIN RLS (el SUPERADMIN no tiene contexto de org). admin_id y
    #    org_id son datos (sin FK cross-RLS obligatoria). accion con CHECK del enum.
    # ------------------------------------------------------------------ #
    op.create_table(
        "plataforma_auditoria",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accion", sa.Text(), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("detalle", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "accion IN ('CREAR_ESCUELA','SUSPENDER_ESCUELA','REACTIVAR_ESCUELA')",
            name="ck_plataforma_auditoria_accion",
        ),
    )

    # ------------------------------------------------------------------ #
    # 4) GRANTs explicitos a latinosport_app sobre las tablas nuevas (DML) y las
    #    secuencias. 0001 ya fijo ALTER DEFAULT PRIVILEGES para objetos futuros,
    #    pero los hacemos explicitos aqui para no depender de ello (replica
    #    0010/0011). Los PK usan gen_random_uuid() => no hay secuencia propia, pero
    #    mantenemos el grant de secuencias por consistencia e idempotencia.
    #    NO se habilita RLS en estas tablas (son de plataforma, no tenant) y NO se
    #    toca el rol latinosport_app (sigue NOSUPERUSER NOBYPASSRLS).
    # ------------------------------------------------------------------ #
    for table in PLATFORM_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO latinosport_app;"
        )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO latinosport_app;"
    )


def downgrade() -> None:
    # Orden inverso. Sin policies que dropear (estas tablas no tienen RLS).
    op.drop_table("plataforma_auditoria")

    # Quitar el CHECK y la columna de `organizacion` (constraint antes que columna).
    op.drop_constraint("ck_organizacion_estado", "organizacion", type_="check")
    op.drop_column("organizacion", "estado")

    # Drop de plataforma_admin (elimina su UNIQUE).
    op.drop_table("plataforma_admin")
