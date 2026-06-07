"""entrenador_ci_disciplinas: entrenador.ci (unico por org, indice parcial) +
entrenador_disciplina (M:N tenant entrenador<->catalogo disciplina) +
RLS (NULLIF fail-closed) + GRANTs + data-migration JSONB->refs catalogo

Migracion del epic "Entrenador con CI + OCR + multi-disciplina" (Sesion 4, rama
`feat/entrenador-ci`) de LatinoSport. Escrita A MANO (no autogenerada): RLS /
GRANTs / indices parciales / data-migrations no los detecta `--autogenerate`.
DATA-PRESERVING: prod tiene datos reales (entrenadores con `disciplinas` JSONB
texto-libre, sembrado en el catalogo `disciplina` por 0016). Corre sobre la BD
con todo lo anterior hasta 0016 (catalogo GLOBAL `disciplina` +
categoria/deportista.disciplina_id) ya vivo. La data-migration corre como OWNER
(rol postgres) via MIGRATION_DATABASE_URL => ve TODAS las orgs; el INSERT
preserva el `org_id` del entrenador (no cruza tenants: cada fila hereda el
org_id de su entrenador).

Contrato implementado (docs/specs/entrenador-ci.md, CONTRATO 1) -- contrato
compartido con backend-dev (su columna `Entrenador.ci` + el modelo
`EntrenadorDisciplina` deben reflejar EXACTAMENTE estos nombres de tabla/columna/
constraint; el indice parcial vive SOLO en esta migracion, no como
UniqueConstraint declarativo. Si algo difiere tras empezar, handoff y parar, no
driftear el esquema en un solo lado):

- 1.a `entrenador.ci`: ADD COLUMN text NULL + INDICE UNICO PARCIAL
  `uq_entrenador_org_ci ON entrenador (org_id, ci) WHERE ci IS NOT NULL`. CI
  unico POR ORGANIZACION; multiples NULL OK (el WHERE excluye los NULL del
  indice). SIN RLS nueva: la tabla `entrenador` ya tiene su policy
  `org_isolation` (patron NULLIF fail-closed) y sus GRANTs DML desde 0001; aqui
  solo se ANADE columna + indice.

- 1.b `entrenador_disciplina` (M:N tenant; `org_id` denormalizado NOT NULL para
  RLS; patron EXACTO de `entrenador_sucursal` en 0014):
  - id uuid PK gen_random_uuid()
  - org_id uuid -> organizacion(id) ON DELETE CASCADE, NOT NULL
  - entrenador_id uuid -> entrenador(id) ON DELETE CASCADE, NOT NULL
  - disciplina_id uuid -> disciplina(id) ON DELETE RESTRICT (default; como
    `categoria.disciplina_id` en 0016: retiro de disciplina = soft-delete, nunca
    hard delete; NO cascade)
  - created_at timestamptz now() NOT NULL
  - UNIQUE(entrenador_id, disciplina_id) `uq_entrenador_disciplina`
  - INDEX (org_id, disciplina_id) `ix_entrenador_disciplina_org_disc`
  RLS: ENABLE + FORCE + policy `org_isolation` con el patron fail-closed NULLIF
  (0003/0010/0011/0014): `org_id = NULLIF(current_setting('app.current_org',
  true), '')::uuid`. Sin contexto / GUC reseteado a '' => NULL => 0 filas (y NULL
  no pasa WITH CHECK). Sin `TO rol`. GRANTs DML a `latinosport_app` +
  USAGE/SELECT en secuencias (replica 0014).

- 1.c Data-migration idempotente (corre como OWNER; preserva el `org_id` del
  entrenador): enlaza la multi-disciplina legacy (`entrenador.disciplinas` JSONB
  texto-libre) al catalogo GLOBAL `disciplina` que 0016 ya sembro. Normalizacion
  identica a la del seed de 0016 (`regexp_replace(btrim(val), '\s+', ' ', 'g')`,
  NO solo btrim) para garantizar PARIDAD del match. ON CONFLICT
  (entrenador_id, disciplina_id) DO NOTHING => re-correr no duplica.

NOTA: `entrenador.disciplinas` (JSONB legacy) NO se toca ni en upgrade ni en
downgrade (decision D1 de la spec: se conserva, simetria con S2 que conservo
`deportista.disciplina`). La API deja de escribirlo; el dato historico queda.

downgrade(): orden inverso -- drop policy + NO FORCE + DISABLE RLS de
`entrenador_disciplina` + DROP TABLE `entrenador_disciplina` (arrastra sus
indices/UNIQUE/policy) + DROP INDEX `uq_entrenador_org_ci` + DROP COLUMN
`entrenador.ci`. NO toca `entrenador.disciplinas` (JSONB intacto) ni la RLS/
GRANTs preexistentes de `entrenador`.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Expresion fail-closed (0003/0010/0011/0014): '' (GUC reseteado) y NULL (nunca
# seteado) -> NULL -> 0 filas y no pasa WITH CHECK.
_EXPR = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1.a) entrenador.ci: ADD COLUMN text NULL + INDICE UNICO PARCIAL
    #      (org_id, ci) WHERE ci IS NOT NULL. CI unico POR ORGANIZACION;
    #      multiples NULL OK (el WHERE los excluye del indice). SIN RLS nueva:
    #      `entrenador` ya tiene su policy `org_isolation` y sus GRANTs DML desde
    #      0001; aqui solo se ANADE columna + indice.
    # ------------------------------------------------------------------ #
    op.add_column(
        "entrenador",
        sa.Column("ci", sa.Text(), nullable=True),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_entrenador_org_ci "
        "ON entrenador (org_id, ci) WHERE ci IS NOT NULL;"
    )

    # ------------------------------------------------------------------ #
    # 1.b) Tabla nueva tenant `entrenador_disciplina` -- M:N entrenador<->catalogo
    #      `disciplina`. org_id denormalizado (NOT NULL) para RLS. entrenador_id
    #      -> CASCADE (borrar el entrenador borra sus enlaces). disciplina_id ->
    #      RESTRICT (default; el catalogo nunca se hard-deleta si esta
    #      referenciado, como `categoria.disciplina_id` en 0016; NO cascade).
    #      UNIQUE(entrenador_id, disciplina_id) impide duplicar el enlace.
    # ------------------------------------------------------------------ #
    op.create_table(
        "entrenador_disciplina",
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
            "disciplina_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("disciplina.id"),  # ON DELETE RESTRICT (default)
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
            "disciplina_id",
            name="uq_entrenador_disciplina",
        ),
    )
    op.create_index(
        "ix_entrenador_disciplina_org_disc",
        "entrenador_disciplina",
        ["org_id", "disciplina_id"],
    )

    # ------------------------------------------------------------------ #
    # 2) RLS de la tabla nueva `entrenador_disciplina`: ENABLE + FORCE + policy
    #    org_isolation con el patron fail-closed NULLIF (0003/0010/0011/0014) ->
    #    sin contexto / GUC reseteado a '' -> NULL -> 0 filas (y NULL no pasa WITH
    #    CHECK). Sin `TO rol`.
    # ------------------------------------------------------------------ #
    op.execute("ALTER TABLE entrenador_disciplina ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE entrenador_disciplina FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY org_isolation ON entrenador_disciplina "
        f"USING ({_EXPR}) WITH CHECK ({_EXPR});"
    )

    # ------------------------------------------------------------------ #
    # 3) GRANTs explicitos a latinosport_app sobre la tabla nueva (DML) y las
    #    secuencias. 0001 ya fijo ALTER DEFAULT PRIVILEGES para objetos futuros,
    #    pero los hacemos explicitos aqui para no depender de ello (replica 0014).
    #    El PK usa gen_random_uuid() => no hay secuencia propia, pero mantenemos
    #    el grant de secuencias por consistencia e idempotencia con 0014.
    # ------------------------------------------------------------------ #
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON entrenador_disciplina "
        "TO latinosport_app;"
    )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO latinosport_app;"
    )

    # ------------------------------------------------------------------ #
    # 4) Data-migration idempotente (corre como OWNER; preserva el `org_id` del
    #    entrenador): enlaza la multi-disciplina legacy (`entrenador.disciplinas`
    #    JSONB texto-libre) al catalogo GLOBAL `disciplina` que 0016 ya sembro.
    #    Normalizacion IDENTICA al seed de 0016 (regexp_replace(btrim(val),
    #    '\s+', ' ', 'g'), NO solo btrim) => paridad del match case-insensitive.
    #    ON CONFLICT (entrenador_id, disciplina_id) DO NOTHING => re-correr no
    #    duplica. `entrenador.disciplinas` queda INTACTO (D1).
    # ------------------------------------------------------------------ #
    op.execute(
        r"""
        INSERT INTO entrenador_disciplina (org_id, entrenador_id, disciplina_id)
        SELECT DISTINCT e.org_id, e.id, x.id
        FROM entrenador e
        CROSS JOIN LATERAL jsonb_array_elements_text(e.disciplinas) AS val
        JOIN disciplina x ON lower(x.nombre) = lower(regexp_replace(btrim(val), '\s+', ' ', 'g'))
        WHERE e.disciplinas IS NOT NULL
          AND jsonb_typeof(e.disciplinas) = 'array'
          AND btrim(val) <> ''
        ON CONFLICT (entrenador_id, disciplina_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    # Orden inverso. NO se toca `entrenador.disciplinas` (JSONB legacy, se
    # conserva por D1) ni la RLS/GRANTs preexistentes de `entrenador`.

    # 2 inverso: policy + RLS de la tabla nueva (el DROP TABLE las eliminaria
    # igual, pero somos explicitos como en 0010/0011/0014).
    op.execute("DROP POLICY IF EXISTS org_isolation ON entrenador_disciplina;")
    op.execute("ALTER TABLE entrenador_disciplina NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE entrenador_disciplina DISABLE ROW LEVEL SECURITY;")

    # 1.b inverso: DROP TABLE (arrastra sus indices, UNIQUE y policy restante).
    op.drop_table("entrenador_disciplina")

    # 1.a inverso: indice parcial + columna de entrenador. La tabla `entrenador`
    # conserva su RLS/GRANTs preexistentes (no se tocaron en el upgrade).
    op.execute("DROP INDEX IF EXISTS uq_entrenador_org_ci;")
    op.drop_column("entrenador", "ci")
