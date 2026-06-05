"""rls hardening: fail-closed con GUC vacío ('' -> NULL) en todas las políticas

Fix de integración (cazado por el test de aislamiento al correr la suite completa).

Causa raíz (PostgreSQL): un GUC personalizado como `app.current_org`, tras un
`SET LOCAL`/`set_config(..., true)` y el commit de esa transacción, **no vuelve a
NULL sino a cadena vacía `''`** en la conexión (que el pool reutiliza). Entonces
`current_setting('app.current_org', true)::uuid` recibe `''` y lanza
`invalid input syntax for type uuid: ""` en vez de hacer fail-closed limpio.

En producción, con pooling, cualquier request que NO fije el contexto sobre una
conexión ya usada daría error 500 en vez de devolver 0 filas. La corrección
robusta es envolver con `NULLIF(..., '')` para que tanto el caso "nunca seteado"
(NULL) como el "reseteado a vacío" ('') colapsen a NULL -> 0 filas.

Recrea la policy `org_isolation` (USING + WITH CHECK) en TODAS las tablas tenant
de 0001 y 0002 con `NULLIF(current_setting('app.current_org', true), '')::uuid`.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-05

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Todas las tablas tenant (con org_id + RLS) creadas en 0001 y 0002.
# `organizacion` (sin RLS) y `conciliacion_pendiente` (cola exenta) NO están aquí.
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
    "cuota",
    "pago",
    "pago_cuota",
)

_EXPR_NEW = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"
_EXPR_OLD = "org_id = current_setting('app.current_org', true)::uuid"


def _recreate_policies(expr: str) -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(
            f"CREATE POLICY org_isolation ON {table} "
            f"USING ({expr}) WITH CHECK ({expr});"
        )


def upgrade() -> None:
    # Endurece: '' (GUC reseteado) y NULL (nunca seteado) -> 0 filas (fail-closed).
    _recreate_policies(_EXPR_NEW)


def downgrade() -> None:
    # Vuelve a la expresión original (sin NULLIF).
    _recreate_policies(_EXPR_OLD)
