"""recibo: numeracion correlativa por org -- pago.numero_recibo +
UNIQUE(org_id, numero_recibo), tabla `recibo_contador` + RLS (NULLIF fail-closed)
+ GRANTs + data migration (retrocompat de pagos CONFIRMADO)

Migracion del epic Recibo (comprobante no-fiscal presentable) de LatinoSport.
Escrita A MANO (no autogenerada): RLS / GRANTs no los detecta `--autogenerate`.
Corre sobre la BD con Alumnos (0001) + Cobranza (0002) + hardening RLS (0003) +
Asistencia (0004) + Egresos (0005) + Avisos (0006) + Horarios (0007) +
Auto-registro (0008) + Abonos (0009) ya viva; main aplica el upgrade en la fase
de cierre.

Contrato implementado (docs/specs/recibo.md, C1) -- el esquema de columnas
(tipos/nullability/defaults/constraints) es contrato compartido con backend-dev
(sus modelos `recibo_contador` y `pago.numero_recibo` deben reflejarlo; si una
columna cambia tras empezar, handoff y parar, no driftear el esquema en un solo
lado):

- `pago`: + `numero_recibo TEXT NULL` (NULL hasta confirmar). Pagos
  PENDIENTE/FALLIDO quedan en NULL. + UNIQUE(org_id, numero_recibo)
  `uq_pago_org_numero_recibo` (NULLs multiples conviven en un UNIQUE compuesto).
  `pago` ya tiene RLS/GRANTs desde 0002; este epic solo le ANADE una columna,
  NO re-habilita RLS ni re-otorga DML.
- Tabla nueva tenant `recibo_contador` (un correlativo por org):
  - org_id uuid PRIMARY KEY -> organizacion(id) ON DELETE CASCADE, NOT NULL.
    El PK ES org_id (no hay columna `id` propia ni secuencia).
  - ultimo_numero integer NOT NULL DEFAULT 0
  - created_at / updated_at timestamptz now() NOT NULL
  - El incremento atomico (contrato de USO de backend, no parte del esquema):
      INSERT INTO recibo_contador (org_id, ultimo_numero) VALUES (:org_id, 1)
      ON CONFLICT (org_id) DO UPDATE
        SET ultimo_numero = recibo_contador.ultimo_numero + 1, updated_at = now()
      RETURNING ultimo_numero;

- Data migration (retrocompat, RF-REC-06 / criterio 5): a cada pago
  estado='CONFIRMADO' con numero_recibo IS NULL se le asigna
  'REC-' || lpad(n::text, 6, '0'), con n = row_number() OVER (PARTITION BY org_id
  ORDER BY created_at, id). El contador de cada org queda en el MAX(n) asignado
  para continuar la serie. Corre como owner de Alembic, FUERA de RLS (sin
  app.current_org): es un backfill global por particion explicita de org_id, no
  depende del GUC de tenant.

RLS de `recibo_contador`: ENABLE + FORCE + policy `org_isolation` con el patron
fail-closed de 0003/0009: `NULLIF(current_setting('app.current_org', true), '')::uuid`.
Asi tanto el caso "nunca seteado" (NULL) como el "reseteado a vacio" ('' tras
SET LOCAL + commit en el pool) colapsan a NULL -> 0 filas y no pasan WITH CHECK
(criterio 2). GRANTs DML a `latinosport_app` + USAGE/SELECT en secuencias
(replica 0009; el PK es org_id, no hay secuencia propia, pero mantenemos el grant
por consistencia e idempotencia).

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas tenant (con org_id) NUEVAS de este epic: llevan RLS habilitada + forzada
# y reciben GRANT de DML + USAGE/SELECT sobre las secuencias del schema.
TENANT_TABLES: tuple[str, ...] = ("recibo_contador",)

# Expresion fail-closed (0003/0009): '' (GUC reseteado) y NULL (nunca seteado)
# -> NULL -> 0 filas y no pasa WITH CHECK.
_EXPR = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Ampliar `pago`: + numero_recibo TEXT NULL (NULL hasta confirmar) y
    #    UNIQUE(org_id, numero_recibo). Postgres trata los NULL como distintos en
    #    un UNIQUE compuesto, asi que multiples pagos sin numero (NULL) conviven.
    #    `pago` ya tiene RLS/GRANTs desde 0002 -> NO re-habilitar RLS aqui.
    # ------------------------------------------------------------------ #
    op.add_column(
        "pago",
        sa.Column("numero_recibo", sa.Text(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_pago_org_numero_recibo",
        "pago",
        ["org_id", "numero_recibo"],
    )

    # ------------------------------------------------------------------ #
    # 2) Tabla nueva tenant `recibo_contador` -- el PK ES org_id (no columna `id`
    #    propia, no secuencia). Un correlativo por organizacion; el backend lo
    #    incrementa con INSERT ... ON CONFLICT ... RETURNING (atomico por org).
    # ------------------------------------------------------------------ #
    op.create_table(
        "recibo_contador",
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizacion.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "ultimo_numero",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
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
    )

    # ------------------------------------------------------------------ #
    # 3) RLS de `recibo_contador`: ENABLE + FORCE + policy org_isolation con el
    #    patron fail-closed NULLIF (0003/0009) -> sin contexto / GUC reseteado a
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
    #    pero los hacemos explicitos aqui para no depender de ello (replica 0009).
    #    El PK es org_id => no hay secuencia propia, pero mantenemos el grant de
    #    secuencias por consistencia e idempotencia con 0009.
    # ------------------------------------------------------------------ #
    for table in TENANT_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO latinosport_app;"
        )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO latinosport_app;"
    )

    # ------------------------------------------------------------------ #
    # 5) Data migration (retrocompat, RF-REC-06 / criterio 5): asignar
    #    numero_recibo correlativo POR org a los pagos CONFIRMADO sin numero,
    #    ordenando por created_at (desempate estable por id). Corre como owner de
    #    Alembic, FUERA de RLS: backfill global con particion explicita por org_id.
    # ------------------------------------------------------------------ #
    op.execute(
        """
        WITH numerados AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY org_id
                    ORDER BY created_at, id
                ) AS n
            FROM pago
            WHERE estado = 'CONFIRMADO'
              AND numero_recibo IS NULL
        )
        UPDATE pago p
        SET numero_recibo = 'REC-' || lpad(numerados.n::text, 6, '0')
        FROM numerados
        WHERE p.id = numerados.id
        """
    )

    # Sembrar `recibo_contador` con el MAX(n) por org (= cantidad de pagos
    # CONFIRMADO de esa org tras el backfill) para que la serie continue. Solo
    # orgs con pagos confirmados obtienen fila; el resto arranca implicitamente
    # via el INSERT ... ON CONFLICT del backend.
    op.execute(
        """
        INSERT INTO recibo_contador (org_id, ultimo_numero)
        SELECT org_id, count(*)
        FROM pago
        WHERE estado = 'CONFIRMADO'
          AND numero_recibo IS NOT NULL
        GROUP BY org_id
        """
    )


def downgrade() -> None:
    # Orden inverso. Empezar por las policies de `recibo_contador` (el drop de
    # tabla las eliminaria igual, pero somos explicitos como en 0009).
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Drop de la tabla recibo_contador (elimina su policy y el PK).
    op.drop_table("recibo_contador")

    # Quitar el UNIQUE y la columna de `pago` (orden: constraint antes que columna).
    op.drop_constraint("uq_pago_org_numero_recibo", "pago", type_="unique")
    op.drop_column("pago", "numero_recibo")
