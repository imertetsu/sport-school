"""pagos_qr_comprobante: tablas tenant `qr_cobro` + `comprobante_pendiente` + RLS
(NULLIF fail-closed) + GRANTs

Migracion del epic `pagos-qr-comprobante` (Fase 2, DB). Materializa las DOS tablas
tenant que definen los modelos `QrCobro` (`backend/app/models/qr_cobro.py`,
mixins UUIDPkMixin + OrgScoped + TimestampMixin) y `ComprobantePendiente`
(`backend/app/models/comprobante_pendiente.py`, mixins UUIDPkMixin + OrgScoped,
SIN TimestampMixin: `created_at` propio + `resuelto_en`, como `pago`/
`conciliacion_pendiente`).

Escrita A MANO (no autogenerada): RLS / GRANTs no los detecta `--autogenerate`,
y el CHECK del enum de `estado` + el UNIQUE PARCIAL de `transaccion_id_ocr`
el modelo los delega EXPRESAMENTE a la migracion (patron del repo: el CHECK
enum-like y los unicos parciales viven solo en la migracion). Corre sobre la BD
con todo lo anterior (0001-0022) ya viva; `down_revision = "0022"` (head actual).

Contratos implementados -- C1 (`qr_cobro`) y C2 (`comprobante_pendiente`) de
docs/specs/pagos-qr-comprobante.md. El esquema de columnas (tipos/nullability/
defaults/constraints) refleja EXACTAMENTE 1:1 los modelos en `Base.metadata`
(backend->db es contrato compartido; si una columna cambia tras empezar, handoff
y parar, no driftear el esquema en un solo lado):

Tabla nueva tenant `qr_cobro` (C1) -- UNA fila por organizacion:
  - id uuid PK gen_random_uuid()
  - org_id uuid -> organizacion(id) ON DELETE CASCADE, NOT NULL (columna de RLS).
    UNIQUE(org_id) `uq_qr_cobro_org` => 1 fila por org. index ix sobre org_id
    (el mixin OrgScoped declara index=True; se reproduce para casar con
    Base.metadata, aunque el UNIQUE ya cubre el lookup).
  - imagen bytea NOT NULL (el QR como bytes; se reenvia tal cual, no se decodifica)
  - mime varchar NOT NULL; tamano_bytes int NOT NULL
  - created_at / updated_at timestamptz now() NOT NULL (TimestampMixin)

Tabla nueva tenant `comprobante_pendiente` (C2) -- cola "Pagos por verificar":
  - id uuid PK gen_random_uuid()
  - org_id uuid -> organizacion(id) ON DELETE CASCADE, NOT NULL (columna de RLS),
    index ix sobre org_id (mixin OrgScoped).
  - estado varchar NOT NULL DEFAULT 'PENDIENTE',
    CHECK estado IN ('PENDIENTE','CONFIRMADO','RECHAZADO')
    `ck_comprobante_pendiente_estado` (CHECK enum-like A MANO, patron repo).
  - from_telefono varchar NOT NULL (remitente; match por telefono -> tutor)
  - message_id varchar NULL, UNIQUE `uq_comprobante_pendiente_message`
    (idempotencia ante re-entrega del sidecar; el modelo lo declara, se materializa
    aqui sin duplicar a mano: una sola constraint con ese nombre).
  - imagen bytea NOT NULL; mime varchar NOT NULL; caption text NULL
  - tutor_id uuid -> tutor(id) ON DELETE SET NULL, NULL
  - cuota_sugerida_id uuid -> cuota(id) ON DELETE SET NULL, NULL
  - monto_ocr numeric(10,2) NULL; transaccion_id_ocr varchar NULL;
    fecha_ocr date NULL; ocr_texto_crudo text NULL
  - pago_id uuid -> pago(id) ON DELETE SET NULL, NULL
  - resuelto_por uuid -> usuario(id) ON DELETE SET NULL, NULL
  - created_at timestamptz now() NOT NULL; resuelto_en timestamptz NULL
  - UNIQUE PARCIAL (transaccion_id_ocr) WHERE transaccion_id_ocr IS NOT NULL
    `uq_comprobante_transaccion_ocr` (anti-fraude: un mismo comprobante no se
    confirma dos veces; A MANO, patron repo).
  - index (org_id, estado) `ix_comprobante_pendiente_org_estado` (cola por estado).

RLS de las DOS tablas nuevas: ENABLE + FORCE + policy `org_isolation` con el
patron fail-closed de 0003/0005/0011/0021/0022:
`org_id = NULLIF(current_setting('app.current_org', true), '')::uuid` (USING +
WITH CHECK). Asi tanto el caso "nunca seteado" (NULL) como el "reseteado a vacio"
('' tras SET LOCAL + commit en el pool) colapsan a NULL -> 0 filas y no pasan
WITH CHECK. Sin `TO rol` en la policy. GRANTs DML a `latinosport_app` +
USAGE/SELECT en secuencias (replica 0022; los PK usan gen_random_uuid(), no
secuencia, pero mantenemos el grant de secuencias por consistencia/idempotencia).

Alcance acotado: NO toca el RLS de ninguna tabla preexistente; solo crea las dos
tablas nuevas con su RLS propia.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas tenant (con org_id) NUEVAS de este epic: llevan RLS habilitada + forzada
# y reciben GRANT de DML + USAGE/SELECT sobre las secuencias del schema.
TENANT_TABLES: tuple[str, ...] = ("qr_cobro", "comprobante_pendiente")

# Expresion fail-closed (0003/0005/0011/0021/0022): '' (GUC reseteado) y NULL
# (nunca seteado) -> NULL -> 0 filas y no pasa WITH CHECK.
_EXPR = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Tabla nueva tenant `qr_cobro` (C1) -- UNA fila por escuela. org_id
    #    denormalizado (NOT NULL) para RLS, -> organizacion CASCADE (borrar la
    #    org borra su QR). UNIQUE(org_id) => 1 fila por org. imagen bytea (se
    #    reenvia tal cual, no se decodifica). created_at / updated_at now()
    #    (TimestampMixin).
    # ------------------------------------------------------------------ #
    op.create_table(
        "qr_cobro",
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
        sa.Column("imagen", sa.LargeBinary(), nullable=False),
        sa.Column("mime", sa.String(), nullable=False),
        sa.Column("tamano_bytes", sa.Integer(), nullable=False),
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
        sa.UniqueConstraint("org_id", name="uq_qr_cobro_org"),
    )
    # Indice del org_id (el mixin OrgScoped declara index=True; se reproduce para
    # casar 1:1 con Base.metadata, aunque el UNIQUE(org_id) ya cubre el lookup).
    op.create_index("ix_qr_cobro_org_id", "qr_cobro", ["org_id"])

    # ------------------------------------------------------------------ #
    # 2) Tabla nueva tenant `comprobante_pendiente` (C2) -- cola "Pagos por
    #    verificar". org_id denormalizado (NOT NULL) para RLS, -> organizacion
    #    CASCADE. estado con CHECK del enum y DEFAULT 'PENDIENTE'. FKs a tutor /
    #    cuota / pago / usuario con ON DELETE SET NULL (no se pierde el
    #    comprobante si se borra el referenciado). OCR best-effort (NULL si no se
    #    leyo). created_at now(); resuelto_en NULL hasta resolver. NO updateat
    #    (NO hereda TimestampMixin).
    # ------------------------------------------------------------------ #
    op.create_table(
        "comprobante_pendiente",
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
            server_default=sa.text("'PENDIENTE'"),
        ),
        sa.Column("from_telefono", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("imagen", sa.LargeBinary(), nullable=False),
        sa.Column("mime", sa.String(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column(
            "tutor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tutor.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "cuota_sugerida_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cuota.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("monto_ocr", sa.Numeric(10, 2), nullable=True),
        sa.Column("transaccion_id_ocr", sa.String(), nullable=True),
        sa.Column("fecha_ocr", sa.Date(), nullable=True),
        sa.Column("ocr_texto_crudo", sa.Text(), nullable=True),
        sa.Column(
            "pago_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pago.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "resuelto_por",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "resuelto_en",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # CHECK enum-like del estado A MANO (patron repo).
        sa.CheckConstraint(
            "estado IN ('PENDIENTE','CONFIRMADO','RECHAZADO')",
            name="ck_comprobante_pendiente_estado",
        ),
        # UNIQUE simple de message_id (idempotencia ante re-entrega del sidecar).
        # El modelo lo declara con este mismo nombre: se materializa aqui una sola
        # vez (no se duplica a mano).
        sa.UniqueConstraint("message_id", name="uq_comprobante_pendiente_message"),
    )

    # Indice del org_id (mixin OrgScoped index=True).
    op.create_index(
        "ix_comprobante_pendiente_org_id", "comprobante_pendiente", ["org_id"]
    )
    # Index (org_id, estado) para la cola por estado.
    op.create_index(
        "ix_comprobante_pendiente_org_estado",
        "comprobante_pendiente",
        ["org_id", "estado"],
    )
    # UNIQUE PARCIAL de transaccion_id_ocr (anti-fraude) A MANO (patron repo):
    # solo aplica cuando el OCR leyo una transaccion (no-null). Dos comprobantes
    # con el mismo numero de transaccion no pueden coexistir; multiples NULL si.
    op.create_index(
        "uq_comprobante_transaccion_ocr",
        "comprobante_pendiente",
        ["transaccion_id_ocr"],
        unique=True,
        postgresql_where=sa.text("transaccion_id_ocr IS NOT NULL"),
    )

    # ------------------------------------------------------------------ #
    # 3) RLS de las DOS tablas nuevas: ENABLE + FORCE + policy org_isolation con
    #    el patron fail-closed NULLIF (0003/0005/0011/0021/0022) -> sin contexto /
    #    GUC reseteado a '' -> NULL -> 0 filas (y NULL no pasa WITH CHECK).
    #    Sin `TO rol`.
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY org_isolation ON {table} "
            f"USING ({_EXPR}) WITH CHECK ({_EXPR});"
        )

    # ------------------------------------------------------------------ #
    # 4) GRANTs explicitos a latinosport_app sobre las tablas nuevas (DML) y las
    #    secuencias. 0001 ya fijo ALTER DEFAULT PRIVILEGES para objetos futuros,
    #    pero los hacemos explicitos aqui para no depender de ello (replica 0022).
    #    Los PK usan gen_random_uuid() => no hay secuencia propia, pero mantenemos
    #    el grant de secuencias por consistencia e idempotencia con 0022.
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO latinosport_app;"
        )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO latinosport_app;"
    )


def downgrade() -> None:
    # Orden inverso. Empezar por la policy de las tablas nuevas (el drop de tabla
    # las eliminaria igual, pero somos explicitos como en 0011/0021/0022).
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Drop de las tablas nuevas (elimina sus indices, UNIQUE, CHECK, FKs y la
    # policy restante). Orden: comprobante_pendiente primero (sin dependencias
    # entrantes), luego qr_cobro.
    op.drop_table("comprobante_pendiente")
    op.drop_table("qr_cobro")
