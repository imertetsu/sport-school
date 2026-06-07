"""recordatorio_deudores: entrenador.telefono + entrenador_sucursal (M:N) +
recordatorio_deudores (log idempotente del digest de morosos al entrenador) +
RLS (NULLIF fail-closed) + GRANTs

Migracion del epic "Recordatorio de deudores al entrenador" (Epic 15) de
LatinoSport. Escrita A MANO (no autogenerada): RLS / GRANTs no los detecta
`--autogenerate`. Corre sobre la BD con Alumnos (0001) + Cobranza (0002) +
hardening RLS (0003) + Asistencia (0004) + Egresos (0005) + Avisos (0006) +
Horarios (0007) + Auto-registro (0008) + Abonos (0009) + Recibo (0010) +
Recordatorio de pago (0011) + Superadmin (0012) + Entrenadores (0013) ya viva.

Contrato implementado -- el esquema de columnas (tipos/nullability/defaults/
constraints) es contrato compartido con backend-dev (sus modelos
`EntrenadorSucursal` / `RecordatorioDeudores` y la columna `Entrenador.telefono`
deben reflejarlo EXACTAMENTE; los modelos se crean EN PARALELO con estas mismas
columnas/constraints. Si una columna cambia tras empezar, handoff y parar, no
driftear el esquema en un solo lado). Reproduce TAL CUAL el CONTRATO 1 de
docs/specs/deudores-entrenador.md:

- 1.a `entrenador.telefono`: ADD COLUMN text NULL. SIN RLS nueva: la tabla
  `entrenador` ya tiene su policy `org_isolation` (patron NULLIF fail-closed) y
  sus GRANTs DML desde 0001; aqui solo se ANADE una columna.

- 1.b `entrenador_sucursal` (M:N tenant; `org_id` denormalizado NOT NULL para RLS):
  - id uuid PK gen_random_uuid()
  - org_id uuid -> organizacion(id) ON DELETE CASCADE, NOT NULL
  - entrenador_id uuid -> entrenador(id) ON DELETE CASCADE, NOT NULL
  - sucursal_id uuid -> sucursal(id) ON DELETE CASCADE, NOT NULL
  - created_at timestamptz now() NOT NULL
  - UNIQUE(entrenador_id, sucursal_id) `uq_entrenador_sucursal`
  - INDEX (org_id, sucursal_id) `ix_entrenador_sucursal_org_suc`

- 1.c `recordatorio_deudores` (control/idempotencia del digest; `org_id`
  denormalizado NOT NULL para RLS):
  - id uuid PK gen_random_uuid()
  - org_id uuid -> organizacion(id) ON DELETE CASCADE, NOT NULL
  - entrenador_id uuid -> entrenador(id) ON DELETE CASCADE, NOT NULL
  - sucursal_id uuid -> sucursal(id) ON DELETE CASCADE, NOT NULL
  - periodo text NOT NULL (ISO week `%G-W%V` para CRON; `MANUAL-<ts>` a demanda)
  - origen text NOT NULL DEFAULT 'CRON', CHECK origen IN ('CRON','MANUAL')
  - canal text NOT NULL DEFAULT 'WHATSAPP'
  - destino text NULL
  - num_deudores integer NOT NULL DEFAULT 0
  - monto_total numeric(10,2) NOT NULL DEFAULT 0
  - provider_message_id text NULL
  - estado text NOT NULL DEFAULT 'ENVIADO',
    CHECK estado IN ('ENVIADO','FALLIDO','SIN_DEUDORES')
  - enviado_en timestamptz now() NOT NULL
  - Idempotencia: UNIQUE(entrenador_id, sucursal_id, periodo)
    `uq_recordatorio_deudores`. Re-correr el cron en el mismo periodo ISO no
    reenvia (INSERT ... ON CONFLICT DO NOTHING en el servicio). Ultima linea de
    defensa a nivel BD.
  - INDEX (org_id, entrenador_id) `ix_recordatorio_deudores_org_ent`.

RLS de las DOS tablas nuevas (`entrenador_sucursal`, `recordatorio_deudores`):
ENABLE + FORCE + policy `org_isolation` con el patron fail-closed de 0003/0010/
0011: `NULLIF(current_setting('app.current_org', true), '')::uuid`. Asi tanto el
caso "nunca seteado" (NULL) como el "reseteado a vacio" ('' tras SET LOCAL +
commit en el pool) colapsan a NULL -> 0 filas y no pasan WITH CHECK. Sin
`TO rol`. GRANTs DML a `latinosport_app` + USAGE/SELECT en secuencias (replica
0011; los PK usan gen_random_uuid(), no secuencia, pero mantenemos el grant de
secuencias por consistencia con 0011 e idempotencia).

Alcance acotado: NO toca el RLS de `entrenador` ni de ninguna tabla preexistente;
solo ANADE la columna `telefono` (sin policy nueva) y crea las dos tablas nuevas
con su RLS propia.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas tenant (con org_id) NUEVAS de este epic: llevan RLS habilitada + forzada
# y reciben GRANT de DML + USAGE/SELECT sobre las secuencias del schema. Orden de
# creacion (FKs entre ellas no las hay; ambas referencian tablas ya existentes).
TENANT_TABLES: tuple[str, ...] = ("entrenador_sucursal", "recordatorio_deudores")

# Expresion fail-closed (0003/0010/0011): '' (GUC reseteado) y NULL (nunca seteado)
# -> NULL -> 0 filas y no pasa WITH CHECK.
_EXPR = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1.a) entrenador.telefono: ADD COLUMN text NULL. E.164 sin '+'
    #      (validacion de forma en Pydantic). SIN RLS nueva: `entrenador` ya
    #      tiene su policy `org_isolation` y sus GRANTs DML desde 0001.
    # ------------------------------------------------------------------ #
    op.add_column(
        "entrenador",
        sa.Column("telefono", sa.Text(), nullable=True),
    )

    # ------------------------------------------------------------------ #
    # 1.b) Tabla nueva tenant `entrenador_sucursal` -- M:N entrenador<->sucursal.
    #      org_id denormalizado (NOT NULL) para RLS. entrenador_id / sucursal_id
    #      -> CASCADE (borrar el entrenador o la sucursal borra la asignacion).
    #      UNIQUE(entrenador_id, sucursal_id) impide duplicar la asignacion.
    # ------------------------------------------------------------------ #
    op.create_table(
        "entrenador_sucursal",
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
            "entrenador_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entrenador.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sucursal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sucursal.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "entrenador_id",
            "sucursal_id",
            name="uq_entrenador_sucursal",
        ),
    )
    op.create_index(
        "ix_entrenador_sucursal_org_suc",
        "entrenador_sucursal",
        ["org_id", "sucursal_id"],
    )

    # ------------------------------------------------------------------ #
    # 1.c) Tabla nueva tenant `recordatorio_deudores` -- log idempotente del
    #      digest de morosos enviado al entrenador por WhatsApp. org_id
    #      denormalizado (NOT NULL) para RLS. entrenador_id / sucursal_id ->
    #      CASCADE. periodo identifica la ventana (ISO week del cron o
    #      MANUAL-<ts> a demanda) y junto a (entrenador_id, sucursal_id) forma la
    #      clave de idempotencia. origen / estado con CHECK del enum. canal /
    #      origen / estado / num_deudores / monto_total con DEFAULT. destino /
    #      provider_message_id NULL (metadatos del envio que pueden faltar).
    # ------------------------------------------------------------------ #
    op.create_table(
        "recordatorio_deudores",
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
            "entrenador_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entrenador.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sucursal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sucursal.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("periodo", sa.Text(), nullable=False),
        sa.Column(
            "origen",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'CRON'"),
        ),
        sa.Column(
            "canal",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'WHATSAPP'"),
        ),
        sa.Column("destino", sa.Text(), nullable=True),
        sa.Column(
            "num_deudores",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "monto_total",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
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
            "origen IN ('CRON','MANUAL')",
            name="ck_recordatorio_deudores_origen",
        ),
        sa.CheckConstraint(
            "estado IN ('ENVIADO','FALLIDO','SIN_DEUDORES')",
            name="ck_recordatorio_deudores_estado",
        ),
        sa.UniqueConstraint(
            "entrenador_id",
            "sucursal_id",
            "periodo",
            name="uq_recordatorio_deudores",
        ),
    )
    op.create_index(
        "ix_recordatorio_deudores_org_ent",
        "recordatorio_deudores",
        ["org_id", "entrenador_id"],
    )

    # ------------------------------------------------------------------ #
    # 2) RLS de las DOS tablas nuevas: ENABLE + FORCE + policy org_isolation con
    #    el patron fail-closed NULLIF (0003/0010/0011) -> sin contexto / GUC
    #    reseteado a '' -> NULL -> 0 filas (y NULL no pasa WITH CHECK). Sin
    #    `TO rol`.
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY org_isolation ON {table} "
            f"USING ({_EXPR}) WITH CHECK ({_EXPR});"
        )

    # ------------------------------------------------------------------ #
    # 3) GRANTs explicitos a latinosport_app sobre las tablas nuevas (DML) y las
    #    secuencias. 0001 ya fijo ALTER DEFAULT PRIVILEGES para objetos futuros,
    #    pero los hacemos explicitos aqui para no depender de ello (replica 0011).
    #    Los PK usan gen_random_uuid() => no hay secuencia propia, pero mantenemos
    #    el grant de secuencias por consistencia e idempotencia con 0011.
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO latinosport_app;"
        )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO latinosport_app;"
    )


def downgrade() -> None:
    # Orden inverso. Empezar por las policies de las dos tablas nuevas (el drop
    # de tabla las eliminaria igual, pero somos explicitos como en 0010/0011).
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Drop de las tablas nuevas (elimina sus indices, UNIQUEs, CHECKs y policies
    # restantes). Orden inverso a la creacion.
    op.drop_table("recordatorio_deudores")
    op.drop_table("entrenador_sucursal")

    # 1.a inverso: quitar entrenador.telefono. La tabla `entrenador` conserva su
    # RLS/GRANTs preexistentes (no se tocaron en el upgrade).
    op.drop_column("entrenador", "telefono")
