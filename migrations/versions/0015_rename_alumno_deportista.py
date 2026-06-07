"""rename core entity alumno -> deportista (DATA-PRESERVING, in-place)

Migracion del epic "Refactor deportistas" (rama refactor/deportistas) de
LatinoSport. Escrita A MANO (no autogenerada): un autogenerate de un rename de
tabla/columna se interpreta como drop+create (PERDERIA DATOS) y nunca toca
constraints/indices/policies por nombre. Esta revision renombra el entity core
`alumno` -> `deportista` PRESERVANDO TODAS LAS FILAS, FKs y RLS sobre la BD viva
(prod esta en 0014: 2 orgs, usuarios y datos reales).

NO se reescribe historia: 0001-0014 quedan INTACTAS. Esta 0015 SOLO ANADE
`ALTER ... RENAME` in-place. No hay drop/create de tablas con datos.

Contrato de nombres (case-sensitive, EXACTO) -- contrato compartido con
backend-dev (sus modelos `Deportista` / `DeportistaTutor` y la columna
`deportista_id` en TODAS las tablas hijas deben reflejarlo TAL CUAL):
- tabla `alumno`        -> `deportista`
- tabla `alumno_tutor`  -> `deportista_tutor`
- columna `alumno_id`   -> `deportista_id` en TODAS las tablas que la tengan.

Inventario EXHAUSTIVO (escaneado en 0001-0014; 0009-0013 no tocan `alumno`):

  Tablas renombradas:
    - alumno        -> deportista                 (0001)
    - alumno_tutor  -> deportista_tutor           (0001)

  Columnas alumno_id -> deportista_id:
    - deportista_tutor.alumno_id  -> deportista_id   (0001, tras rename de tabla)
    - consentimiento.alumno_id    -> deportista_id   (0001)
    - inscripcion.alumno_id       -> deportista_id   (0001)
    - asistencia.alumno_id        -> deportista_id   (0004)
    - solicitud_registro.alumno_id-> deportista_id   (0008)

  Constraints auto-nombrados por Postgres (<tabla>_pkey, <tabla>_<col>_fkey):
    - alumno_pkey                       -> deportista_pkey
    - alumno_org_id_fkey                -> deportista_org_id_fkey
    - alumno_sucursal_id_fkey           -> deportista_sucursal_id_fkey
    - alumno_categoria_id_fkey          -> deportista_categoria_id_fkey
    - alumno_tutor_pkey                 -> deportista_tutor_pkey
    - alumno_tutor_org_id_fkey          -> deportista_tutor_org_id_fkey
    - alumno_tutor_alumno_id_fkey       -> deportista_tutor_deportista_id_fkey
    - alumno_tutor_tutor_id_fkey        -> deportista_tutor_tutor_id_fkey
    - consentimiento_alumno_id_fkey     -> consentimiento_deportista_id_fkey
    - inscripcion_alumno_id_fkey        -> inscripcion_deportista_id_fkey
    - asistencia_alumno_id_fkey         -> asistencia_deportista_id_fkey
    - solicitud_registro_alumno_id_fkey -> solicitud_registro_deportista_id_fkey

  Constraints UNIQUE con nombre explicito:
    - uq_alumno_tutor_alumno_tutor      -> uq_deportista_tutor (alinea con el modelo)
    - uq_asistencia_sesion_alumno       -> uq_asistencia_sesion_deportista

  Indices:
    - ix_alumno_org_id                  -> ix_deportista_org_id
    - ix_alumno_sucursal_id             -> ix_deportista_sucursal_id
    - ix_alumno_categoria_id            -> ix_deportista_categoria_id
    - ix_alumno_tutor_org_id            -> ix_deportista_tutor_org_id
    - ix_alumno_tutor_alumno_id         -> ix_deportista_tutor_deportista_id
    - ix_alumno_tutor_tutor_id          -> ix_deportista_tutor_tutor_id
    - ix_consentimiento_alumno_id       -> ix_consentimiento_deportista_id
    - ix_inscripcion_alumno_id          -> ix_inscripcion_deportista_id
    - ix_asistencia_alumno_id           -> ix_asistencia_deportista_id

RLS: al renombrar la tabla con ALTER TABLE ... RENAME, Postgres conserva las
policies (incl. `org_isolation`) y los GRANTs adheridos por OID -> la RLS sigue
ACTIVA bajo el nombre nuevo, con el mismo patron fail-closed
`org_id = NULLIF(current_setting('app.current_org', true), '')::uuid`. Las
policies de 0001/0003 no referencian el nombre de la tabla en su expresion (solo
`org_id`), asi que no requieren recrearse. NO se toca el rol `latinosport_app`
ni el GUC `app.current_org`. Esta migracion deja constancia en un comentario de
verificacion (ver bloque al final de upgrade()).

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-07

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (tabla, columna_vieja, columna_nueva) -- columnas alumno_id -> deportista_id.
# `deportista_tutor` se nombra ya con su nombre NUEVO porque la columna se
# renombra DESPUES del rename de la tabla (ver upgrade()).
_COL_RENAMES: tuple[tuple[str, str, str], ...] = (
    ("deportista_tutor", "alumno_id", "deportista_id"),
    ("consentimiento", "alumno_id", "deportista_id"),
    ("inscripcion", "alumno_id", "deportista_id"),
    ("asistencia", "alumno_id", "deportista_id"),
    ("solicitud_registro", "alumno_id", "deportista_id"),
)

# (tabla, nombre_constraint_viejo, nombre_constraint_nuevo).
# Tablas YA con su nombre NUEVO (los renames de constraint van tras el rename de
# tabla). Cubre PKs y FKs auto-nombrados por Postgres + UNIQUEs explicitos.
_CONSTRAINT_RENAMES: tuple[tuple[str, str, str], ...] = (
    # deportista (ex-alumno): PK + FKs
    ("deportista", "alumno_pkey", "deportista_pkey"),
    ("deportista", "alumno_org_id_fkey", "deportista_org_id_fkey"),
    ("deportista", "alumno_sucursal_id_fkey", "deportista_sucursal_id_fkey"),
    ("deportista", "alumno_categoria_id_fkey", "deportista_categoria_id_fkey"),
    # deportista_tutor (ex-alumno_tutor): PK + FKs + UNIQUE
    ("deportista_tutor", "alumno_tutor_pkey", "deportista_tutor_pkey"),
    (
        "deportista_tutor",
        "alumno_tutor_org_id_fkey",
        "deportista_tutor_org_id_fkey",
    ),
    (
        "deportista_tutor",
        "alumno_tutor_alumno_id_fkey",
        "deportista_tutor_deportista_id_fkey",
    ),
    (
        "deportista_tutor",
        "alumno_tutor_tutor_id_fkey",
        "deportista_tutor_tutor_id_fkey",
    ),
    (
        "deportista_tutor",
        "uq_alumno_tutor_alumno_tutor",
        "uq_deportista_tutor",
    ),
    # hijas con alumno_id: FK auto-nombrado
    (
        "consentimiento",
        "consentimiento_alumno_id_fkey",
        "consentimiento_deportista_id_fkey",
    ),
    (
        "inscripcion",
        "inscripcion_alumno_id_fkey",
        "inscripcion_deportista_id_fkey",
    ),
    (
        "asistencia",
        "asistencia_alumno_id_fkey",
        "asistencia_deportista_id_fkey",
    ),
    (
        "asistencia",
        "uq_asistencia_sesion_alumno",
        "uq_asistencia_sesion_deportista",
    ),
    (
        "solicitud_registro",
        "solicitud_registro_alumno_id_fkey",
        "solicitud_registro_deportista_id_fkey",
    ),
)

# (nombre_indice_viejo, nombre_indice_nuevo). Independiente del nombre de tabla.
_INDEX_RENAMES: tuple[tuple[str, str], ...] = (
    ("ix_alumno_org_id", "ix_deportista_org_id"),
    ("ix_alumno_sucursal_id", "ix_deportista_sucursal_id"),
    ("ix_alumno_categoria_id", "ix_deportista_categoria_id"),
    ("ix_alumno_tutor_org_id", "ix_deportista_tutor_org_id"),
    ("ix_alumno_tutor_alumno_id", "ix_deportista_tutor_deportista_id"),
    ("ix_alumno_tutor_tutor_id", "ix_deportista_tutor_tutor_id"),
    ("ix_consentimiento_alumno_id", "ix_consentimiento_deportista_id"),
    ("ix_inscripcion_alumno_id", "ix_inscripcion_deportista_id"),
    ("ix_asistencia_alumno_id", "ix_asistencia_deportista_id"),
)


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) Rename de las DOS tablas core. ALTER TABLE ... RENAME es in-place:
    #    preserva filas, datos, FKs entrantes/salientes, policies RLS y GRANTs
    #    (adheridos por OID). Las FKs de las tablas hijas hacia `alumno.id`
    #    siguen apuntando por OID -> tras el rename apuntan a `deportista.id`
    #    sin tocar las hijas.
    # ------------------------------------------------------------------ #
    op.rename_table("alumno", "deportista")
    op.rename_table("alumno_tutor", "deportista_tutor")

    # ------------------------------------------------------------------ #
    # 2) Rename de columnas alumno_id -> deportista_id en TODAS las tablas que
    #    la tengan (incluida la propia deportista_tutor, ya con nombre nuevo).
    #    ALTER COLUMN ... RENAME preserva datos y la FK (que se renombra aparte).
    # ------------------------------------------------------------------ #
    for table, old_col, new_col in _COL_RENAMES:
        op.alter_column(table, old_col, new_column_name=new_col)

    # ------------------------------------------------------------------ #
    # 3) Rename de constraints (PKs, FKs auto-nombrados y UNIQUEs explicitos)
    #    para que el nombre quede coherente con `deportista`/`deportista_id`.
    #    Postgres NO los auto-renombra al renombrar la tabla; lo hacemos
    #    explicito para que el downgrade pueda revertirlos por nombre.
    # ------------------------------------------------------------------ #
    for table, old_name, new_name in _CONSTRAINT_RENAMES:
        op.execute(
            f'ALTER TABLE {table} RENAME CONSTRAINT "{old_name}" TO "{new_name}";'
        )

    # ------------------------------------------------------------------ #
    # 4) Rename de indices (no asociados a constraint). ALTER INDEX ... RENAME.
    # ------------------------------------------------------------------ #
    for old_name, new_name in _INDEX_RENAMES:
        op.execute(f'ALTER INDEX "{old_name}" RENAME TO "{new_name}";')

    # ------------------------------------------------------------------ #
    # 5) RLS: NO se recrea nada. El rename de tabla conserva las policies
    #    `org_isolation` (USING + WITH CHECK con NULLIF fail-closed) y los GRANTs
    #    DML a latinosport_app, adheridos por OID. Las policies de 0001/0003 NO
    #    referencian el nombre de la tabla en su expresion (solo `org_id`), asi
    #    que siguen validas tras el rename. NO se toca el rol ni el GUC.
    #
    #    Verificacion sugerida (CI / manual, con el rol latinosport_app):
    #      -- sin contexto: 0 filas (fail-closed)
    #      SET ROLE latinosport_app; RESET app.current_org;
    #      SELECT count(*) FROM deportista;          -- => 0
    #      SELECT count(*) FROM deportista_tutor;    -- => 0
    #      -- con contexto de una org: solo sus filas
    #      SET app.current_org = '<org-A-uuid>';
    #      SELECT count(*) FROM deportista;          -- => filas de org A
    #    `\d deportista` debe mostrar la policy org_isolation y rowsecurity=t.
    # ------------------------------------------------------------------ #


def downgrade() -> None:
    # Simetrico e inverso. Revertir en orden inverso: indices, constraints,
    # columnas, y por ultimo las tablas (los nombres de constraint/columna deben
    # existir bajo su forma NUEVA antes de revertir la tabla, igual que el
    # upgrade los renombro DESPUES del rename de tabla).

    # 4 inverso: indices.
    for old_name, new_name in _INDEX_RENAMES:
        op.execute(f'ALTER INDEX "{new_name}" RENAME TO "{old_name}";')

    # 3 inverso: constraints (las tablas siguen con nombre NUEVO en este punto).
    for table, old_name, new_name in _CONSTRAINT_RENAMES:
        op.execute(
            f'ALTER TABLE {table} RENAME CONSTRAINT "{new_name}" TO "{old_name}";'
        )

    # 2 inverso: columnas deportista_id -> alumno_id (tablas aun con nombre nuevo).
    for table, old_col, new_col in _COL_RENAMES:
        op.alter_column(table, new_col, new_column_name=old_col)

    # 1 inverso: tablas. RLS/GRANTs vuelven adheridos por OID al nombre viejo.
    op.rename_table("deportista_tutor", "alumno_tutor")
    op.rename_table("deportista", "alumno")
