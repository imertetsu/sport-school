"""whatsapp_sesion: sesion de WhatsApp por escuela (metadata best-effort) + RLS
(NULLIF fail-closed) + GRANTs

Migracion del epic `whatsapp-multitenant` (Fase 1, DB). Materializa la tabla
tenant `whatsapp_sesion` que define el modelo `WhatsAppSesion`
(`backend/app/models/whatsapp_sesion.py`, mixins UUIDPkMixin + OrgScoped +
TimestampMixin). UNA fila por organizacion (UNIQUE en org_id): metadata
best-effort de la sesion de WhatsApp de esa escuela para la UI de Ajustes. La
verdad LIVE (connected / QR vivo) es el sidecar (`Map<org_id, Session>` en
Baileys); el backend reconcilia `estado` en cada GET de estado -> es un cache.

Escrita A MANO (no autogenerada): RLS / GRANTs no los detecta `--autogenerate`,
y el CHECK del enum de `estado` el modelo lo delega EXPRESAMENTE a la migracion
(patron del repo: el CHECK enum-like vive en la migracion). Corre sobre la BD con
todo lo anterior (0001-0021) ya viva; `down_revision = "0021"` (head actual).

Contrato implementado -- contrato compartido 3 de docs/specs/whatsapp-multitenant.md.
El esquema de columnas (tipos/nullability/defaults/constraints) refleja
EXACTAMENTE 1:1 el modelo `WhatsAppSesion` en `Base.metadata` (backend->db es
contrato compartido; si una columna cambia tras empezar, handoff y parar, no
driftear el esquema en un solo lado):

Tabla nueva tenant `whatsapp_sesion` (org_id denormalizado NOT NULL para RLS):
  - id uuid PK gen_random_uuid()
  - org_id uuid -> organizacion(id) ON DELETE CASCADE, NOT NULL (columna de RLS).
    UNIQUE(org_id) `uq_whatsapp_sesion_org` => 1 fila por org. index ix sobre
    org_id (el mixin OrgScoped declara index=True; se reproduce para casar con
    Base.metadata, aunque el UNIQUE ya cubre el lookup).
  - estado varchar NOT NULL DEFAULT 'DESVINCULADA',
    CHECK estado IN ('DESVINCULADA','PENDIENTE_QR','CONECTADA')
    `ck_whatsapp_sesion_estado` (cache best-effort del estado de pairing).
  - numero varchar NULL (digitos E.164 del par; NULL hasta CONECTADA)
  - vinculado_en timestamptz NULL (sello del pairing efectivo)
  - created_at / updated_at timestamptz now() NOT NULL (TimestampMixin)

RLS de la tabla nueva: ENABLE + FORCE + policy `org_isolation` con el patron
fail-closed de 0003/0005/0011/0021:
`org_id = NULLIF(current_setting('app.current_org', true), '')::uuid` (USING +
WITH CHECK). Asi tanto el caso "nunca seteado" (NULL) como el "reseteado a vacio"
('' tras SET LOCAL + commit en el pool) colapsan a NULL -> 0 filas y no pasan
WITH CHECK. Sin `TO rol` en la policy. GRANTs DML a `latinosport_app` +
USAGE/SELECT en secuencias (replica 0021; el PK usa gen_random_uuid(), no
secuencia, pero mantenemos el grant de secuencias por consistencia/idempotencia).

Alcance acotado: NO toca el RLS de ninguna tabla preexistente; solo crea la tabla
nueva con su RLS propia. NO se anaden columnas a `organizacion` (que no tiene RLS).

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tabla tenant (con org_id) NUEVA de este epic: lleva RLS habilitada + forzada y
# recibe GRANT de DML + USAGE/SELECT sobre las secuencias del schema.
TENANT_TABLES: tuple[str, ...] = ("whatsapp_sesion",)

# Expresion fail-closed (0003/0005/0011/0021): '' (GUC reseteado) y NULL (nunca
# seteado) -> NULL -> 0 filas y no pasa WITH CHECK.
_EXPR = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Tabla nueva tenant `whatsapp_sesion` -- metadata best-effort de la sesion
    #    de WhatsApp por escuela. org_id denormalizado (NOT NULL) para RLS, ->
    #    organizacion CASCADE (borrar la org borra su sesion). UNIQUE(org_id) =>
    #    1 fila por org. estado con CHECK del enum y DEFAULT 'DESVINCULADA' (cache;
    #    la verdad LIVE es el sidecar). numero / vinculado_en NULL hasta el par.
    #    created_at / updated_at now() (TimestampMixin).
    # ------------------------------------------------------------------ #
    op.create_table(
        "whatsapp_sesion",
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
            sa.String(),
            nullable=False,
            server_default=sa.text("'DESVINCULADA'"),
        ),
        sa.Column("numero", sa.String(), nullable=True),
        sa.Column(
            "vinculado_en",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
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
        sa.CheckConstraint(
            "estado IN ('DESVINCULADA','PENDIENTE_QR','CONECTADA')",
            name="ck_whatsapp_sesion_estado",
        ),
        sa.UniqueConstraint("org_id", name="uq_whatsapp_sesion_org"),
    )

    # Indice del org_id (el mixin OrgScoped declara index=True; se reproduce para
    # casar 1:1 con Base.metadata, aunque el UNIQUE(org_id) ya cubre el lookup).
    op.create_index("ix_whatsapp_sesion_org_id", "whatsapp_sesion", ["org_id"])

    # ------------------------------------------------------------------ #
    # 2) RLS de la tabla nueva: ENABLE + FORCE + policy org_isolation con el patron
    #    fail-closed NULLIF (0003/0005/0011/0021) -> sin contexto / GUC reseteado a
    #    '' -> NULL -> 0 filas (y NULL no pasa WITH CHECK). Sin `TO rol`.
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY org_isolation ON {table} "
            f"USING ({_EXPR}) WITH CHECK ({_EXPR});"
        )

    # ------------------------------------------------------------------ #
    # 3) GRANTs explicitos a latinosport_app sobre la tabla nueva (DML) y las
    #    secuencias. 0001 ya fijo ALTER DEFAULT PRIVILEGES para objetos futuros,
    #    pero los hacemos explicitos aqui para no depender de ello (replica 0021).
    #    El PK usa gen_random_uuid() => no hay secuencia propia, pero mantenemos el
    #    grant de secuencias por consistencia e idempotencia con 0021.
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO latinosport_app;"
        )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO latinosport_app;"
    )


def downgrade() -> None:
    # Orden inverso. Empezar por la policy de la tabla nueva (el drop de tabla la
    # eliminaria igual, pero somos explicitos como en 0011/0021).
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Drop de la tabla nueva (elimina su indice, UNIQUE, CHECK y policy restante).
    op.drop_table("whatsapp_sesion")
