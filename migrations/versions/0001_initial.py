"""initial schema + RLS + app role + login_lookup

Migracion INICIAL de CanteraSport, escrita A MANO (no autogenerada):
- RLS / roles / funciones SECURITY DEFINER no los detecta `--autogenerate`.
- Corre en paralelo con backend-dev (sin BD viva ni modelos importables).

Contratos implementados:
- C1: esquema (tablas, columnas, tipos, FKs, constraints UNIQUE).
- C2: RLS por `org_id` (ENABLE + FORCE + policy `org_isolation` con
  `current_setting('app.current_org', true)::uuid`), rol de app
  `cantera_app` NOSUPERUSER NOBYPASSRLS, y funcion `public.login_lookup`
  SECURITY DEFINER para el login (huevo-gallina).

Requiere la extension pgcrypto para `gen_random_uuid()` (la provee infra en
postgres/init.sql). Alembic corre como owner via MIGRATION_DATABASE_URL.

Revision ID: 0001
Revises:
Create Date: 2026-06-05

"""
import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Todas las tablas tenant (con org_id) que llevan RLS habilitada + forzada.
# `organizacion` es la UNICA excepcion (no tiene org_id ni RLS).
TENANT_TABLES: tuple[str, ...] = (
    "usuario",
    "sucursal",
    "categoria",
    "entrenador",
    "alumno",
    "tutor",
    "alumno_tutor",
    "consentimiento",
    "inscripcion",
)


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


def _timestamps() -> list[sa.Column]:
    """created_at / updated_at timestamptz con default now()."""
    return [
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
    ]


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 0) Extension pgcrypto (idempotente). Infra tambien la asegura en
    #    init.sql; aqui la garantizamos para gen_random_uuid().
    # ------------------------------------------------------------------ #
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    # ------------------------------------------------------------------ #
    # 1) Tablas (C1) -- nombres/columnas/tipos/FKs/constraints EXACTOS.
    # ------------------------------------------------------------------ #

    # organizacion -- UNICA tabla sin org_id ni RLS.
    op.create_table(
        "organizacion",
        _uuid_pk(),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("pais", sa.Text(), nullable=False, server_default=sa.text("'BO'")),
        sa.Column("moneda", sa.Text(), nullable=False, server_default=sa.text("'BOB'")),
        sa.Column("regimen_fiscal", sa.Text(), nullable=True),
        sa.Column(
            "modo_cobro_default",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'ANIVERSARIO'"),
        ),
        sa.Column("dia_corte_fijo", sa.Integer(), nullable=True),
        sa.Column(
            "prorratea_primer_periodo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "modo_cobro_default IN ('FIJO','ANIVERSARIO')",
            name="ck_organizacion_modo_cobro_default",
        ),
    )

    # usuario -- email UNIQUE GLOBAL.
    op.create_table(
        "usuario",
        _uuid_pk(),
        _org_fk(),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_timestamps(),
        sa.UniqueConstraint("email", name="uq_usuario_email"),
        sa.CheckConstraint(
            "role IN ('ADMIN','ENTRENADOR')", name="ck_usuario_role"
        ),
    )

    # sucursal
    op.create_table(
        "sucursal",
        _uuid_pk(),
        _org_fk(),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("direccion", sa.Text(), nullable=True),
        *_timestamps(),
    )

    # categoria -- sucursal_id -> sucursal.
    op.create_table(
        "categoria",
        _uuid_pk(),
        _org_fk(),
        sa.Column(
            "sucursal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sucursal.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("nivel", sa.Text(), nullable=False),
        sa.Column("rango_edad", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "nivel IN ('PRINCIPIANTE','INTERMEDIO','AVANZADO')",
            name="ck_categoria_nivel",
        ),
    )

    # entrenador -- usuario_id -> usuario.
    op.create_table(
        "entrenador",
        _uuid_pk(),
        _org_fk(),
        sa.Column(
            "usuario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nombres", sa.Text(), nullable=False),
        sa.Column("especialidad", sa.Text(), nullable=True),
        *_timestamps(),
    )

    # alumno -- sucursal_id -> sucursal, categoria_id -> categoria (nullable).
    op.create_table(
        "alumno",
        _uuid_pk(),
        _org_fk(),
        sa.Column(
            "sucursal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sucursal.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "categoria_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("categoria.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ap_paterno", sa.Text(), nullable=True),
        sa.Column("ap_materno", sa.Text(), nullable=True),
        sa.Column("nombres", sa.Text(), nullable=False),
        sa.Column("ci", sa.Text(), nullable=True),
        sa.Column("fecha_nac", sa.Date(), nullable=True),
        sa.Column("disciplina", sa.Text(), nullable=True),
        sa.Column("contacto_emergencia", sa.Text(), nullable=True),
        sa.Column("ficha_medica", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_timestamps(),
    )

    # tutor
    op.create_table(
        "tutor",
        _uuid_pk(),
        _org_fk(),
        sa.Column("nombres", sa.Text(), nullable=False),
        sa.Column("telefono", sa.Text(), nullable=True),
        sa.Column("ci", sa.Text(), nullable=True),
        *_timestamps(),
    )

    # alumno_tutor (N:M) -- UNIQUE(alumno_id, tutor_id).
    op.create_table(
        "alumno_tutor",
        _uuid_pk(),
        _org_fk(),
        sa.Column(
            "alumno_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alumno.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tutor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tutor.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parentesco", sa.Text(), nullable=True),
        sa.Column(
            "responsable_pago",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "alumno_id", "tutor_id", name="uq_alumno_tutor_alumno_tutor"
        ),
    )

    # consentimiento -- tutor_id -> tutor, alumno_id -> alumno.
    op.create_table(
        "consentimiento",
        _uuid_pk(),
        _org_fk(),
        sa.Column(
            "tutor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tutor.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "alumno_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alumno.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_terminos", sa.Text(), nullable=False),
        sa.Column("canal", sa.Text(), nullable=True),
        sa.Column(
            "aceptado_en",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *_timestamps(),
    )

    # inscripcion -- alumno_id -> alumno.
    op.create_table(
        "inscripcion",
        _uuid_pk(),
        _org_fk(),
        sa.Column(
            "alumno_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alumno.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("disciplina", sa.Text(), nullable=True),
        sa.Column("fecha_inscripcion", sa.Date(), nullable=True),
        sa.Column("monto_mensual", sa.Numeric(10, 2), nullable=True),
        sa.Column("modo_cobro", sa.Text(), nullable=True),
        sa.Column("dia_corte", sa.Integer(), nullable=True),
        sa.Column(
            "estado", sa.Text(), nullable=False, server_default=sa.text("'ACTIVA'")
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "modo_cobro IS NULL OR modo_cobro IN ('FIJO','ANIVERSARIO')",
            name="ck_inscripcion_modo_cobro",
        ),
        sa.CheckConstraint(
            "estado IN ('ACTIVA','INACTIVA')", name="ck_inscripcion_estado"
        ),
    )

    # ------------------------------------------------------------------ #
    # 2) Indices utiles para accesos frecuentes (listados por sucursal,
    #    categoria; busqueda de usuario por email; FKs de hijos).
    # ------------------------------------------------------------------ #
    op.create_index("ix_usuario_org_id", "usuario", ["org_id"])
    op.create_index("ix_sucursal_org_id", "sucursal", ["org_id"])
    op.create_index("ix_categoria_org_id", "categoria", ["org_id"])
    op.create_index("ix_categoria_sucursal_id", "categoria", ["sucursal_id"])
    op.create_index("ix_entrenador_org_id", "entrenador", ["org_id"])
    op.create_index("ix_entrenador_usuario_id", "entrenador", ["usuario_id"])
    op.create_index("ix_alumno_org_id", "alumno", ["org_id"])
    op.create_index("ix_alumno_sucursal_id", "alumno", ["sucursal_id"])
    op.create_index("ix_alumno_categoria_id", "alumno", ["categoria_id"])
    op.create_index("ix_tutor_org_id", "tutor", ["org_id"])
    op.create_index("ix_alumno_tutor_org_id", "alumno_tutor", ["org_id"])
    op.create_index("ix_alumno_tutor_alumno_id", "alumno_tutor", ["alumno_id"])
    op.create_index("ix_alumno_tutor_tutor_id", "alumno_tutor", ["tutor_id"])
    op.create_index("ix_consentimiento_org_id", "consentimiento", ["org_id"])
    op.create_index("ix_consentimiento_alumno_id", "consentimiento", ["alumno_id"])
    op.create_index("ix_inscripcion_org_id", "inscripcion", ["org_id"])
    op.create_index("ix_inscripcion_alumno_id", "inscripcion", ["alumno_id"])

    # ------------------------------------------------------------------ #
    # 3) RLS: por cada tabla tenant, ENABLE + FORCE + policy org_isolation.
    #    `current_setting('app.current_org', true)` -> fail-closed:
    #    sin contexto -> NULL -> 0 filas (y NULL no pasa WITH CHECK).
    #    `organizacion` queda EXPLICITAMENTE fuera (sin RLS).
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY org_isolation ON {table}
                USING (org_id = current_setting('app.current_org', true)::uuid)
                WITH CHECK (org_id = current_setting('app.current_org', true)::uuid);
            """
        )

    # ------------------------------------------------------------------ #
    # 4) Rol de app `cantera_app`: LOGIN, NOSUPERUSER, NOBYPASSRLS.
    #    Password configurable por env APP_DB_PASSWORD (default 'devpass' para dev/CI).
    #    En PRODUCCIÓN: setea APP_DB_PASSWORD fuerte y úsalo igual en DATABASE_URL
    #    (cantera_app:<APP_DB_PASSWORD>). Idempotente (DO $$ ... IF NOT EXISTS): solo
    #    crea el rol si no existe; para rotar la clave luego usa ALTER ROLE a mano.
    # ------------------------------------------------------------------ #
    _app_db_pw = os.environ.get("APP_DB_PASSWORD", "devpass").replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT FROM pg_roles WHERE rolname = 'cantera_app'
            ) THEN
                CREATE ROLE cantera_app LOGIN PASSWORD '{_app_db_pw}'
                    NOSUPERUSER NOBYPASSRLS;
            END IF;
        END
        $$;
        """
    )

    # Privilegios sobre objetos existentes en el schema public.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON ALL TABLES IN SCHEMA public TO cantera_app;"
    )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cantera_app;"
    )
    op.execute("GRANT USAGE ON SCHEMA public TO cantera_app;")

    # Privilegios por defecto para objetos FUTUROS creados por el owner.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cantera_app;"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO cantera_app;"
    )

    # ------------------------------------------------------------------ #
    # 5) Funcion login_lookup SECURITY DEFINER (huevo-gallina del login).
    #    El owner (postgres) la ejecuta saltando RLS de forma controlada:
    #    devuelve (id, org_id, password_hash, role, activo, nombre, email)
    #    por email. El backend la usa SOLO en /login (antes de conocer org_id).
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.login_lookup(p_email text)
        RETURNS TABLE (
            id uuid,
            org_id uuid,
            password_hash text,
            role text,
            activo boolean,
            nombre text,
            email text
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT u.id, u.org_id, u.password_hash, u.role, u.activo, u.nombre, u.email
            FROM public.usuario u
            WHERE u.email = p_email;
        $$;
        """
    )
    # Bloquear EXECUTE a PUBLIC y concederlo solo a cantera_app.
    op.execute(
        "REVOKE ALL ON FUNCTION public.login_lookup(text) FROM PUBLIC;"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.login_lookup(text) TO cantera_app;"
    )


def downgrade() -> None:
    # Orden inverso. Empezar por la funcion y las policies.
    op.execute("DROP FUNCTION IF EXISTS public.login_lookup(text);")

    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Revertir privilegios por defecto (best-effort; no falla si no existen).
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM cantera_app;"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM cantera_app;"
    )

    # Drop de tablas en orden inverso de creacion (respeta FKs).
    op.drop_table("inscripcion")
    op.drop_table("consentimiento")
    op.drop_table("alumno_tutor")
    op.drop_table("tutor")
    op.drop_table("alumno")
    op.drop_table("entrenador")
    op.drop_table("categoria")
    op.drop_table("sucursal")
    op.drop_table("usuario")
    op.drop_table("organizacion")

    # El rol cantera_app puede quedarse (compartido con la app). Se dropea
    # solo si no tiene objetos/dependencias; best-effort sin romper el down.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cantera_app') THEN
                BEGIN
                    DROP ROLE cantera_app;
                EXCEPTION WHEN OTHERS THEN
                    -- El rol tiene dependencias (objetos/privilegios por
                    -- defecto, posiblemente en otra BD); se deja en pie.
                    -- No es un fallo de la migracion.
                    NULL;
                END;
            END IF;
        END
        $$;
        """
    )
