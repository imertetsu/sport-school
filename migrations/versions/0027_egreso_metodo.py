"""egreso.metodo (EFECTIVO | QR) — desglose de salidas por método de pago

Migración del epic "Panel: egresos y utilidad del mes". ALTER-only,
DATA-PRESERVING: cabeza actual 0026; 0001-0026 quedan INTACTAS. SOLO añade una
columna a `egreso`.

Por qué
-------
El panel de cobranza ya desglosa los INGRESOS en efectivo/QR usando `pago.metodo`,
pero `egreso` no guardaba con qué se pagó el gasto, así que "Egresos del mes" y
"Utilidad del mes" no podían mostrar el mismo desglose. Esta columna es el dato
que faltaba; sin ella el desglose sería una suposición, no un hecho.

Qué hace
--------
1. `ALTER TABLE egreso ADD COLUMN metodo text NOT NULL DEFAULT 'EFECTIVO'`. El
   DEFAULT hace de backfill de las filas existentes en un solo paso: hasta ahora
   los gastos se cargaban sin método y en una escuela chica el gasto corriente se
   paga en efectivo, así que ese es el supuesto explícito para lo ya cargado.
2. `CHECK ck_egreso_metodo` con los MISMOS literales que `ck_pago_metodo`
   ('EFECTIVO','QR'), para que ingresos y egresos hablen el mismo vocabulario y
   el panel pueda cruzarlos sin traducir.

El DEFAULT se mantiene a nivel de servidor (no se dropea): el modelo declara el
mismo default de app, y dejarlo evita que un INSERT viejo que no conozca la
columna falle por NOT NULL.

RLS / GRANTs: SIN cambios. `egreso` ya tiene su policy `org_isolation` por
`org_id` y el GRANT DML de tabla a `latinosport_app` desde 0005; ambos cubren la
columna nueva (las policies son por FILA, no por columna).

downgrade(): inverso simétrico (drop del CHECK y de la columna). No toca datos de
otras columnas, RLS, policies ni GRANTs.

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "egreso",
        sa.Column("metodo", sa.Text(), nullable=False, server_default="EFECTIVO"),
    )
    op.create_check_constraint(
        "ck_egreso_metodo",
        "egreso",
        "metodo IN ('EFECTIVO', 'QR')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_egreso_metodo", "egreso", type_="check")
    op.drop_column("egreso", "metodo")
