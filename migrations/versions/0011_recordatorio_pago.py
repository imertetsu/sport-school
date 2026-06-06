"""recordatorio_pago: log idempotente de recordatorios de cobro por WhatsApp +
RLS (NULLIF fail-closed) + GRANTs

Migracion del epic WhatsApp Cobro de LatinoSport. Escrita A MANO (no autogenerada):
RLS / GRANTs no los detecta `--autogenerate`. Corre sobre la BD con Alumnos (0001) +
Cobranza (0002) + hardening RLS (0003) + Asistencia (0004) + Egresos (0005) +
Avisos (0006) + Horarios (0007) + Auto-registro (0008) + Abonos (0009) +
Recibo (0010) ya viva; main aplica el upgrade en la fase de cierre.

Contrato implementado -- el esquema de columnas (tipos/nullability/defaults/
constraints) es contrato compartido con backend-dev (su modelo `RecordatorioPago`
debe reflejarlo EXACTAMENTE; el modelo se crea EN PARALELO con estas mismas
columnas/constraints. Si una columna cambia tras empezar, handoff y parar, no
driftear el esquema en un solo lado):

- Tabla nueva tenant `recordatorio_pago` (log de recordatorios de cobro enviados;
  `org_id` denormalizado NOT NULL para RLS):
  - id uuid PK gen_random_uuid()
  - org_id uuid -> organizacion(id) ON DELETE CASCADE, NOT NULL
  - cuota_id uuid -> cuota(id) ON DELETE CASCADE, NOT NULL
  - tutor_id uuid -> tutor(id) ON DELETE SET NULL, NULLABLE (a quien se notifico;
    null si el tutor se elimino o el destino fue ad-hoc)
  - tipo text NOT NULL, CHECK tipo IN ('PROXIMO_VENCIMIENTO','MOROSIDAD')
  - canal text NOT NULL DEFAULT 'WHATSAPP'
  - ciclo text NOT NULL (identifica la ronda/iteracion del recordatorio; parte de
    la clave de idempotencia)
  - destino text NULL (numero/identificador al que se envio)
  - qr_ref text NULL (referencia del QR de cobro adjunto, si aplica)
  - provider_message_id text NULL (id del mensaje devuelto por el proveedor WhatsApp)
  - estado text NOT NULL DEFAULT 'ENVIADO', CHECK estado IN ('ENVIADO','FALLIDO')
  - enviado_en timestamptz now() NOT NULL

- Idempotencia (ESTA es la clave): UNIQUE(cuota_id, tipo, ciclo)
  `uq_recordatorio_cuota_tipo_ciclo`. Un recordatorio de un tipo, para una cuota,
  en un ciclo dado se envia UNA sola vez (el job de cobranza puede reintentar sin
  duplicar el mensaje). Idempotencia a nivel BD (ultima linea de defensa), espejo
  de PAGO.transaccion_id en cobranza.
- Indice (org_id, cuota_id) `ix_recordatorio_org_cuota` para listar/consultar los
  recordatorios de una cuota dentro del tenant.

RLS de `recordatorio_pago`: ENABLE + FORCE + policy `org_isolation` con el patron
fail-closed de 0003/0010: `NULLIF(current_setting('app.current_org', true), '')::uuid`.
Asi tanto el caso "nunca seteado" (NULL) como el "reseteado a vacio" ('' tras
SET LOCAL + commit en el pool) colapsan a NULL -> 0 filas y no pasan WITH CHECK.
GRANTs DML a `latinosport_app` + USAGE/SELECT en secuencias (replica 0010; el PK usa
gen_random_uuid(), no secuencia, pero mantenemos el grant de secuencias por
consistencia con 0010 e idempotencia).

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas tenant (con org_id) NUEVAS de este epic: llevan RLS habilitada + forzada
# y reciben GRANT de DML + USAGE/SELECT sobre las secuencias del schema.
TENANT_TABLES: tuple[str, ...] = ("recordatorio_pago",)

# Expresion fail-closed (0003/0010): '' (GUC reseteado) y NULL (nunca seteado)
# -> NULL -> 0 filas y no pasa WITH CHECK.
_EXPR = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Tabla nueva tenant `recordatorio_pago` -- log de recordatorios de cobro
    #    enviados por WhatsApp. org_id denormalizado (NOT NULL) para RLS.
    #    cuota_id -> cuota (CASCADE: borrar la cuota borra su historial de
    #    recordatorios). tutor_id -> tutor (SET NULL: el log sobrevive aunque el
    #    tutor se elimine). tipo / estado con CHECK del enum. canal y estado con
    #    DEFAULT. ciclo identifica la ronda del recordatorio (clave de idempotencia
    #    junto a cuota_id + tipo). destino / qr_ref / provider_message_id NULL
    #    (metadatos del envio que pueden faltar).
    # ------------------------------------------------------------------ #
    op.create_table(
        "recordatorio_pago",
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
            "cuota_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cuota.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tutor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tutor.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column(
            "canal",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'WHATSAPP'"),
        ),
        sa.Column("ciclo", sa.Text(), nullable=False),
        sa.Column("destino", sa.Text(), nullable=True),
        sa.Column("qr_ref", sa.Text(), nullable=True),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column(
            "estado",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'ENVIADO'"),
        ),
        sa.Column(
            "enviado_en",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "tipo IN ('PROXIMO_VENCIMIENTO','MOROSIDAD')",
            name="ck_recordatorio_tipo",
        ),
        sa.CheckConstraint(
            "estado IN ('ENVIADO','FALLIDO')",
            name="ck_recordatorio_estado",
        ),
        sa.UniqueConstraint(
            "cuota_id",
            "tipo",
            "ciclo",
            name="uq_recordatorio_cuota_tipo_ciclo",
        ),
    )

    # ------------------------------------------------------------------ #
    # 2) Indice (org_id, cuota_id) para listar/consultar los recordatorios de una
    #    cuota dentro del tenant.
    # ------------------------------------------------------------------ #
    op.create_index(
        "ix_recordatorio_org_cuota",
        "recordatorio_pago",
        ["org_id", "cuota_id"],
    )

    # ------------------------------------------------------------------ #
    # 3) RLS de `recordatorio_pago`: ENABLE + FORCE + policy org_isolation con el
    #    patron fail-closed NULLIF (0003/0010) -> sin contexto / GUC reseteado a
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
    # 4) GRANTs explicitos a latinosport_app sobre la tabla nueva (DML) y las
    #    secuencias. 0001 ya fijo ALTER DEFAULT PRIVILEGES para objetos futuros,
    #    pero los hacemos explicitos aqui para no depender de ello (replica 0010).
    #    El PK usa gen_random_uuid() => no hay secuencia propia, pero mantenemos el
    #    grant de secuencias por consistencia e idempotencia con 0010.
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO latinosport_app;"
        )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO latinosport_app;"
    )


def downgrade() -> None:
    # Orden inverso. Empezar por las policies de `recordatorio_pago` (el drop de
    # tabla las eliminaria igual, pero somos explicitos como en 0010).
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Drop de la tabla (elimina su indice, su UNIQUE y la policy restante).
    op.drop_table("recordatorio_pago")
