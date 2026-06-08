"""aviso_notificacion: log idempotente del envio de WhatsApp por aviso del muro
(a ENTRENADORES / TUTORES) + RLS (NULLIF fail-closed) + GRANTs

Migracion del epic "avisos-whatsapp" (Fase F1) de LatinoSport. Cuando un ADMIN
publica un Aviso del muro y marca los flags opt-in (`notificar_entrenadores` /
`notificar_tutores`), el envio de WhatsApp se materializa por destinatario en
esta tabla. Es a la vez log de auditoria y ULTIMA LINEA DE DEFENSA de idempotencia
a nivel BD: UNIQUE(aviso_id, tipo_destinatario, destinatario_id) impide el doble
envio (el servicio inserta con ON CONFLICT DO NOTHING; reencolar la task no
duplica ni reenvia). Mock-first: con WHATSAPP_PROVIDER=noop/mock no hay envio real;
la fila queda ENVIADO con el provider_message_id del mock.

Escrita A MANO (no autogenerada): RLS / GRANTs no los detecta `--autogenerate`.
Corre sobre la BD con todo lo anterior (0001-0019) + 0020
(`deportista.activo` / `organizacion.color`) ya viva. `down_revision = "0020"`
(contrato C1 de docs/specs/avisos-whatsapp.md: el head de migraciones es 0020;
0020 vive en la rama paralela `feat/escuela-y-bajas` e integra en `staging` antes
que esta).

Contrato implementado -- CONTRATO C1 de docs/specs/avisos-whatsapp.md. El esquema
de columnas (tipos/nullability/defaults/constraints) es contrato compartido con
backend-dev (su modelo `AvisoNotificacion` en
`backend/app/models/aviso_notificacion.py` lo refleja EXACTAMENTE 1:1; el modelo
se crea EN PARALELO con estas mismas columnas/constraints. Si una columna cambia
tras empezar, handoff y parar, no driftear el esquema en un solo lado).

Tabla nueva tenant `aviso_notificacion` (org_id denormalizado NOT NULL para RLS):
  - id uuid PK gen_random_uuid()
  - org_id uuid -> organizacion(id) ON DELETE CASCADE, NOT NULL (columna de RLS)
  - aviso_id uuid -> aviso(id) ON DELETE CASCADE, NOT NULL
  - tipo_destinatario text NOT NULL, CHECK IN ('ENTRENADOR','TUTOR')
  - destinatario_id uuid NOT NULL (id del entrenador o tutor; SIN FK, polimorfico)
  - canal text NOT NULL DEFAULT 'WHATSAPP'
  - destino text NULL (telefono; NULL si SIN_TELEFONO)
  - estado text NOT NULL, CHECK IN ('ENVIADO','FALLIDO','SIN_TELEFONO')
  - provider_message_id text NULL (id del proveedor; auditoria)
  - error text NULL (descripcion del fallo cuando estado='FALLIDO')
  - created_at timestamptz NOT NULL DEFAULT now()
  - enviado_en timestamptz NULL (sello del envio efectivo)
  - Idempotencia: UNIQUE(aviso_id, tipo_destinatario, destinatario_id)
    `uq_aviso_notificacion_destinatario`. Re-correr la task del mismo aviso no
    reenvia (INSERT ... ON CONFLICT DO NOTHING en el servicio). Ultima linea de
    defensa a nivel BD.
  - INDEX (org_id, aviso_id) `ix_aviso_notificacion_org_aviso` para listar por aviso.

RLS de la tabla nueva: ENABLE + FORCE + policy `org_isolation` con el patron
fail-closed de 0003/0010/0011/0014:
`org_id = NULLIF(current_setting('app.current_org', true), '')::uuid` (USING +
WITH CHECK). Asi tanto el caso "nunca seteado" (NULL) como el "reseteado a vacio"
('' tras SET LOCAL + commit en el pool) colapsan a NULL -> 0 filas y no pasan
WITH CHECK. Sin `TO rol`. GRANTs DML a `latinosport_app` + USAGE/SELECT en
secuencias (replica 0014; el PK usa gen_random_uuid(), no secuencia, pero
mantenemos el grant de secuencias por consistencia/idempotencia con 0014).

Alcance acotado: NO toca el RLS de `aviso` ni de ninguna tabla preexistente; solo
crea la tabla nueva con su RLS propia.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tabla tenant (con org_id) NUEVA de este epic: lleva RLS habilitada + forzada y
# recibe GRANT de DML + USAGE/SELECT sobre las secuencias del schema.
TENANT_TABLES: tuple[str, ...] = ("aviso_notificacion",)

# Expresion fail-closed (0003/0010/0011/0014): '' (GUC reseteado) y NULL (nunca
# seteado) -> NULL -> 0 filas y no pasa WITH CHECK.
_EXPR = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Tabla nueva tenant `aviso_notificacion` -- log idempotente del envio de
    #    WhatsApp por aviso. org_id denormalizado (NOT NULL) para RLS. aviso_id ->
    #    CASCADE (borrar el aviso borra sus registros de envio). destinatario_id
    #    SIN FK (polimorfico: entrenador o tutor). tipo_destinatario / estado con
    #    CHECK del enum. canal con DEFAULT. destino / provider_message_id / error /
    #    enviado_en NULL (metadatos del envio que pueden faltar). created_at now().
    #    UNIQUE(aviso_id, tipo_destinatario, destinatario_id) = clave de
    #    idempotencia (no doble envio).
    # ------------------------------------------------------------------ #
    op.create_table(
        "aviso_notificacion",
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
            "aviso_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("aviso.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tipo_destinatario", sa.Text(), nullable=False),
        sa.Column(
            "destinatario_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "canal",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'WHATSAPP'"),
        ),
        sa.Column("destino", sa.Text(), nullable=True),
        sa.Column("estado", sa.Text(), nullable=False),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "enviado_en",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "tipo_destinatario IN ('ENTRENADOR','TUTOR')",
            name="ck_aviso_notificacion_tipo_destinatario",
        ),
        sa.CheckConstraint(
            "estado IN ('ENVIADO','FALLIDO','SIN_TELEFONO')",
            name="ck_aviso_notificacion_estado",
        ),
        sa.UniqueConstraint(
            "aviso_id",
            "tipo_destinatario",
            "destinatario_id",
            name="uq_aviso_notificacion_destinatario",
        ),
    )
    op.create_index(
        "ix_aviso_notificacion_org_aviso",
        "aviso_notificacion",
        ["org_id", "aviso_id"],
    )

    # ------------------------------------------------------------------ #
    # 2) RLS de la tabla nueva: ENABLE + FORCE + policy org_isolation con el patron
    #    fail-closed NULLIF (0003/0010/0011/0014) -> sin contexto / GUC reseteado a
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
    #    pero los hacemos explicitos aqui para no depender de ello (replica 0014).
    #    El PK usa gen_random_uuid() => no hay secuencia propia, pero mantenemos el
    #    grant de secuencias por consistencia e idempotencia con 0014.
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
    # eliminaria igual, pero somos explicitos como en 0010/0011/0014).
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Drop de la tabla nueva (elimina su indice, UNIQUE, CHECKs y policy restante).
    op.drop_table("aviso_notificacion")
