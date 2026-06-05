"""cobranza: cuota / pago / pago_cuota / conciliacion_pendiente + RLS + webhook_resolver

Migracion del epic Cobranza de CanteraSport, escrita A MANO (no autogenerada):
- RLS / GRANTs / funciones SECURITY DEFINER no los detecta `--autogenerate`.
- Corre sobre la BD del slice Alumnos (0001) ya viva; main aplica el upgrade.

Contratos implementados (docs/specs/cobranza.md):
- C1: esquema de `cuota`, `pago`, `pago_cuota` (tablas tenant con org_id) y
  `conciliacion_pendiente` (cola dead-letter SIN org_id NI RLS), con tipos,
  FKs, numeric(10,2), CHECK de enums, UNIQUE e indice exactos.
- C3: funcion `public.webhook_resolver(p_qr_ref text)` SECURITY DEFINER que
  resuelve el `pago` por `qr_ref` saltando RLS (mismo patron que `login_lookup`).

RLS: las tablas tenant nuevas llevan ENABLE + FORCE + policy `org_isolation`
con `current_setting('app.current_org', true)::uuid` (fail-closed). La cola
`conciliacion_pendiente` queda EXPLICITAMENTE exenta (ops/vendor), pero
`cantera_app` recibe GRANT SELECT/INSERT/UPDATE sobre ella.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas tenant (con org_id) de este epic que llevan RLS habilitada + forzada.
# `conciliacion_pendiente` es la UNICA excepcion (cola ops/vendor: sin org_id
# ni RLS, pero con GRANT explicito a cantera_app mas abajo).
TENANT_TABLES: tuple[str, ...] = (
    "cuota",
    "pago",
    "pago_cuota",
)

# Tablas nuevas (tenant + cola) que necesitan GRANT de DML a cantera_app y
# USAGE/SELECT sobre sus secuencias.
NEW_TABLES: tuple[str, ...] = (
    "cuota",
    "pago",
    "pago_cuota",
    "conciliacion_pendiente",
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

    # cuota -- inscripcion_id -> inscripcion. UNIQUE(inscripcion_id, periodo_inicio)
    # da idempotencia de generacion. Indice (org_id, estado, vence_el) para el cron.
    op.create_table(
        "cuota",
        _uuid_pk(),
        _org_fk(),
        sa.Column(
            "inscripcion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inscripcion.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("periodo_inicio", sa.Date(), nullable=False),
        sa.Column("periodo_fin", sa.Date(), nullable=False),
        sa.Column("vence_el", sa.Date(), nullable=False),
        sa.Column("monto", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "estado",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'PENDIENTE'"),
        ),
        sa.Column(
            "es_prorrateo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "generada_en",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "inscripcion_id",
            "periodo_inicio",
            name="uq_cuota_inscripcion_periodo_inicio",
        ),
        sa.CheckConstraint(
            "estado IN ('PENDIENTE','PAGADO','VENCIDO')",
            name="ck_cuota_estado",
        ),
    )

    # pago -- registrado_por -> usuario (null; solo efectivo). transaccion_id y
    # qr_ref UNIQUE (idempotencia y resolucion del webhook). created_at.
    op.create_table(
        "pago",
        _uuid_pk(),
        _org_fk(),
        sa.Column("metodo", sa.Text(), nullable=False),
        sa.Column(
            "estado",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'PENDIENTE'"),
        ),
        sa.Column("monto", sa.Numeric(10, 2), nullable=False),
        sa.Column("transaccion_id", sa.Text(), nullable=True),
        sa.Column("qr_ref", sa.Text(), nullable=True),
        sa.Column("pagado_en", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "registrado_por",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("comprobante_url", sa.Text(), nullable=True),
        _created_at(),
        sa.UniqueConstraint("transaccion_id", name="uq_pago_transaccion_id"),
        sa.UniqueConstraint("qr_ref", name="uq_pago_qr_ref"),
        sa.CheckConstraint(
            "metodo IN ('EFECTIVO','QR')",
            name="ck_pago_metodo",
        ),
        sa.CheckConstraint(
            "estado IN ('PENDIENTE','CONFIRMADO','FALLIDO')",
            name="ck_pago_estado",
        ),
    )

    # pago_cuota (puente N:M) -- UNIQUE(pago_id, cuota_id).
    op.create_table(
        "pago_cuota",
        _uuid_pk(),
        _org_fk(),
        sa.Column(
            "pago_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pago.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cuota_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cuota.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("monto_aplicado", sa.Numeric(10, 2), nullable=False),
        sa.UniqueConstraint(
            "pago_id", "cuota_id", name="uq_pago_cuota_pago_cuota"
        ),
    )

    # conciliacion_pendiente (cola dead-letter) -- SIN org_id, SIN RLS.
    # Nunca se pierde un pago: el webhook que no resuelve/cuadra escribe aqui.
    op.create_table(
        "conciliacion_pendiente",
        _uuid_pk(),
        sa.Column("transaccion_id", sa.Text(), nullable=True),
        sa.Column("referencia", sa.Text(), nullable=True),
        sa.Column("monto", sa.Numeric(10, 2), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column(
            "resuelto",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        _created_at(),
    )

    # ------------------------------------------------------------------ #
    # 2) Indices: el indicado por C1 para el cron + FKs de acceso frecuente.
    # ------------------------------------------------------------------ #
    op.create_index(
        "ix_cuota_org_estado_vence_el",
        "cuota",
        ["org_id", "estado", "vence_el"],
    )
    op.create_index("ix_cuota_inscripcion_id", "cuota", ["inscripcion_id"])
    op.create_index("ix_pago_org_id", "pago", ["org_id"])
    op.create_index("ix_pago_registrado_por", "pago", ["registrado_por"])
    op.create_index("ix_pago_cuota_org_id", "pago_cuota", ["org_id"])
    op.create_index("ix_pago_cuota_pago_id", "pago_cuota", ["pago_id"])
    op.create_index("ix_pago_cuota_cuota_id", "pago_cuota", ["cuota_id"])

    # ------------------------------------------------------------------ #
    # 3) RLS: por cada tabla tenant nueva, ENABLE + FORCE + policy
    #    org_isolation. `current_setting('app.current_org', true)` ->
    #    fail-closed: sin contexto -> NULL -> 0 filas (y NULL no pasa
    #    WITH CHECK). `conciliacion_pendiente` queda EXPLICITAMENTE fuera.
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
    # 4) GRANTs explicitos a cantera_app sobre las tablas nuevas (DML) y sus
    #    secuencias. 0001 ya fijo ALTER DEFAULT PRIVILEGES para objetos
    #    futuros, pero los hacemos explicitos aqui para no depender de ello
    #    (y para cubrir `conciliacion_pendiente`, exenta de RLS pero operada
    #    por la app: el webhook encola conciliaciones con cantera_app).
    # ------------------------------------------------------------------ #
    for table in NEW_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cantera_app;"
        )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cantera_app;"
    )

    # ------------------------------------------------------------------ #
    # 5) Funcion webhook_resolver SECURITY DEFINER (C3). El owner la ejecuta
    #    saltando RLS de forma controlada: resuelve el `pago` por `qr_ref`
    #    (referencia interna del QR) ANTES de conocer/fijar app.current_org.
    #    Mismo patron que login_lookup. Devuelve monto como `monto_esperado`.
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.webhook_resolver(p_qr_ref text)
        RETURNS TABLE (
            pago_id uuid,
            org_id uuid,
            monto_esperado numeric,
            estado text
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT p.id, p.org_id, p.monto, p.estado
            FROM public.pago p
            WHERE p.qr_ref = p_qr_ref;
        $$;
        """
    )
    # Bloquear EXECUTE a PUBLIC y concederlo solo a cantera_app.
    op.execute(
        "REVOKE ALL ON FUNCTION public.webhook_resolver(text) FROM PUBLIC;"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.webhook_resolver(text) TO cantera_app;"
    )


def downgrade() -> None:
    # Orden inverso. Empezar por la funcion y las policies.
    op.execute("DROP FUNCTION IF EXISTS public.webhook_resolver(text);")

    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Drop de tablas en orden inverso (respeta FKs):
    # pago_cuota (referencia pago y cuota) -> cuota / pago -> conciliacion.
    op.drop_table("pago_cuota")
    op.drop_table("cuota")
    op.drop_table("pago")
    op.drop_table("conciliacion_pendiente")
