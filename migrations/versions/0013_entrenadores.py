"""entrenadores: + entrenador.disciplinas (JSONB lista de strings) -- sin RLS nueva

Migracion del epic Gestion de Entrenadores (Epic B) de LatinoSport. Escrita A
MANO (no autogenerada en su intencion; el `--autogenerate` no debe detectar
diferencia frente al modelo): solo ANADE una columna a la tabla `entrenador`
ya existente.

Contrato de esquema (docs/specs/entrenadores.md, "Contrato de esquema") --
fijado por main, implementar tal cual; es contrato compartido con backend-dev
(su modelo `Entrenador` lleva EN PARALELO la misma columna; si el tipo /
nullability / server_default cambia tras empezar, handoff y parar, no driftear
el esquema en un solo lado):

- `entrenador`: + `disciplinas JSONB NOT NULL DEFAULT '[]'::jsonb` (lista de
  strings; ej. `["Futbol","Natacion"]`). El default vacio hace el ADD seguro
  sobre filas existentes. `especialidad` (texto libre) YA existe y se mantiene
  intacta. El modelo SQLAlchemy lo refleja como:
      disciplinas: Mapped[list[str]] = mapped_column(
          JSONB, nullable=False, server_default=text("'[]'::jsonb")
      )

Sin RLS nueva: `entrenador` ya tiene su policy `org_isolation` (patron NULLIF
fail-closed) y sus GRANTs DML desde su migracion de origen; aqui solo se ANADE
una columna, no se re-habilita RLS ni se re-otorga DML.

Cadena Alembic (plan §3/§6): `down_revision="0011"` DURANTE EL DESARROLLO; main
lo reajusta a `0012` al integrar (A aterriza primero como `0012` => cadena
lineal `0011->0012->0013`). No tocar la cadena en la sesion.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # Anadir `entrenador.disciplinas`: JSONB NOT NULL con DEFAULT '[]'::jsonb
    # (lista de strings vacia). El server_default hace el ADD seguro sobre las
    # filas existentes. Mismo tipo/nullability/default que el modelo SQLAlchemy
    # `Entrenador` (contrato compartido) para que `--autogenerate` no detecte
    # diferencia. Sin RLS nueva: la tabla ya tiene su policy `org_isolation`.
    # ------------------------------------------------------------------ #
    op.add_column(
        "entrenador",
        sa.Column(
            "disciplinas",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    # Quitar entrenador.disciplinas.
    op.drop_column("entrenador", "disciplinas")
