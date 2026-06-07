"""disciplinas: catalogo GLOBAL `disciplina` + categoria/deportista.disciplina_id

Migracion del epic Disciplinas (Sesion 2, rama `feat/disciplinas`) de
LatinoSport. Escrita A MANO (no autogenerada): el `--autogenerate` no detecta
indices funcionales (`lower(nombre)`), GRANTs ni data-migrations; ademas esta
revision SIEMBRA datos a partir de los textos-libre existentes. Es
DATA-PRESERVING: prod tiene datos reales (deportistas con `disciplina` texto y
entrenadores con `disciplinas` JSONB). Corre como OWNER (rol postgres) via
MIGRATION_DATABASE_URL => ve TODAS las orgs; el match es por texto, NO cruza
orgs (cada disciplina es un valor de catalogo global, no un dato de tenant).

Contrato implementado (docs/specs/disciplinas.md, CONTRATO 1) -- contrato
compartido con backend-dev (su modelo `Disciplina` + las FKs en `categoria` /
`deportista` deben reflejar EXACTAMENTE estos nombres de tabla/columna/indice;
si algo difiere tras empezar, handoff y parar, no driftear el esquema):

- Tabla nueva `disciplina` -- catalogo GLOBAL. SIN org_id y SIN RLS (mismo
  patron que `organizacion` / `plataforma_admin`): no contiene datos de tenant,
  es seguro exponerla. Unicidad case-insensitive via INDICE FUNCIONAL
  `uq_disciplina_nombre_lower ON disciplina (lower(nombre))`, NO UniqueConstraint
  declarativo. GRANT de DML a latinosport_app (CRUD lo hace el superadmin desde
  /plataforma; lectura de catalogo la hace la escuela).
    - id uuid PK gen_random_uuid()
    - nombre text NOT NULL
    - activo boolean NOT NULL DEFAULT true
    - created_at / updated_at timestamptz now() NOT NULL

- Columna nueva `categoria.disciplina_id` uuid NULL REFERENCES disciplina(id)
  (ON DELETE RESTRICT por default: retiro de disciplina = soft-delete, nunca
  hard delete). `categoria` sigue siendo tenant con RLS INTACTA; solo se ANADE
  columna + indice `ix_categoria_disciplina_id`.

- Columna nueva `deportista.disciplina_id` uuid NULL REFERENCES disciplina(id)
  ON DELETE SET NULL (FK propia del deportista; la columna texto legacy
  `deportista.disciplina` se CONSERVA, no se dropea). + `ix_deportista_disciplina_id`.

- Data-migration idempotente (1.d):
    1) Sembrar `disciplina` con valores DISTINTOS no vacios de
       `deportista.disciplina` (texto) y `entrenador.disciplinas` (JSONB,
       desanidado con jsonb_array_elements_text). Filtro
       `IS NOT NULL AND btrim(x) <> ''`. Nombre canonico = btrim + colapsar
       espacios internos (regexp_replace '\\s+' -> ' '); NO initcap (preserva
       acentos/escritura original). Dedupe via el indice funcional:
       `INSERT ... ON CONFLICT (lower(nombre)) DO NOTHING`. NO se fusionan
       sinonimos ("Voley" != "Voleibol").
    2) Enlazar `deportista.disciplina_id` por match
       `lower(btrim(d.disciplina)) = lower(x.nombre)`.
    3) Enlazar `categoria.disciplina_id` por MODA NO AMBIGUA de las disciplinas
       de sus deportistas: si todos los deportistas de la categoria (con
       disciplina_id no nulo) comparten UNA sola disciplina => asignarla; si 0 o
       hay mezcla => dejar NULL (count(distinct disciplina_id) = 1).
    4) `entrenador` NO se enlaza (su multi-disciplina es S4). Solo se usa para
       SEMBRAR el catalogo; `entrenador.disciplinas` queda INTACTO.

  Idempotencia: re-ejecutar el seed no duplica (ON CONFLICT lower(nombre)); los
  UPDATE son deterministas (re-aplicarlos da el mismo resultado).

NOTA RLS: `disciplina` NO habilita RLS (tabla de plataforma, no tenant). NO se
toca el rol latinosport_app (sigue NOSUPERUSER NOBYPASSRLS de 0001) ni las
policies de `categoria` / `deportista` (intactas; siguen fail-closed por org).

downgrade(): orden inverso -- drop indices + columnas `disciplina_id` (deportista,
categoria) + DROP TABLE disciplina (lo que arrastra su indice funcional y los
grants adheridos por OID). NO toca `deportista.disciplina` (texto legacy).

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1.a) Tabla `disciplina` -- catalogo GLOBAL. SIN org_id y SIN RLS (replica
    #      el patron de `organizacion` / `plataforma_admin`: PK gen_random_uuid()
    #      + created_at/updated_at now()). La unicidad case-insensitive vive como
    #      INDICE FUNCIONAL (no UniqueConstraint), creado abajo.
    # ------------------------------------------------------------------ #
    op.create_table(
        "disciplina",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column(
            "activo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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

    # Unicidad case-insensitive via indice funcional (NO UniqueConstraint
    # declarativo). Tambien es el target del `ON CONFLICT (lower(nombre))` del seed.
    op.execute(
        "CREATE UNIQUE INDEX uq_disciplina_nombre_lower "
        "ON disciplina (lower(nombre));"
    )

    # GRANT de DML a la app. `disciplina` es de plataforma (no tenant): NO se
    # habilita RLS. El CRUD lo hace el superadmin; la escuela solo lee catalogo.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON disciplina TO latinosport_app;"
    )

    # ------------------------------------------------------------------ #
    # 1.b) `categoria.disciplina_id` -- FK al catalogo, ON DELETE RESTRICT (por
    #      default): no se puede hard-deletar una disciplina referenciada; el
    #      retiro es soft-delete (activo=false). `categoria` sigue tenant con RLS
    #      intacta; solo se ANADE columna + indice.
    # ------------------------------------------------------------------ #
    op.add_column(
        "categoria",
        sa.Column(
            "disciplina_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("disciplina.id"),  # ON DELETE RESTRICT (default)
            nullable=True,
        ),
    )
    op.create_index(
        "ix_categoria_disciplina_id", "categoria", ["disciplina_id"]
    )

    # ------------------------------------------------------------------ #
    # 1.c) `deportista.disciplina_id` -- FK propia del deportista, ON DELETE SET
    #      NULL (si se borrara una disciplina, el deportista queda sin ella, no
    #      bloquea). La columna texto legacy `deportista.disciplina` se CONSERVA.
    # ------------------------------------------------------------------ #
    op.add_column(
        "deportista",
        sa.Column(
            "disciplina_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("disciplina.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_deportista_disciplina_id", "deportista", ["disciplina_id"]
    )

    # ------------------------------------------------------------------ #
    # 1.d.1) SEMBRAR el catalogo con los valores DISTINTOS no vacios de
    #        `deportista.disciplina` (texto) Y `entrenador.disciplinas` (JSONB
    #        desanidado). Nombre canonico = btrim + colapsar espacios internos
    #        (regexp_replace '\\s+' -> ' '); NO initcap. Dedupe case-insensitive
    #        via el indice funcional => ON CONFLICT (lower(nombre)) DO NOTHING.
    #        NO se fusionan sinonimos. Corre como OWNER => ve todas las orgs; el
    #        valor de catalogo es global, no un dato de tenant.
    #
    #        Idempotente: el ON CONFLICT garantiza que re-correr no duplica.
    # ------------------------------------------------------------------ #
    op.execute(
        r"""
        INSERT INTO disciplina (nombre)
        SELECT DISTINCT regexp_replace(btrim(src.val), '\s+', ' ', 'g') AS nombre
        FROM (
            -- valores texto de deportista.disciplina
            SELECT d.disciplina AS val
            FROM deportista d
            WHERE d.disciplina IS NOT NULL
              AND btrim(d.disciplina) <> ''
            UNION ALL
            -- valores desanidados de entrenador.disciplinas (JSONB array de texto)
            SELECT e_val AS val
            FROM entrenador e
            CROSS JOIN LATERAL jsonb_array_elements_text(e.disciplinas) AS e_val
            WHERE e.disciplinas IS NOT NULL
              AND jsonb_typeof(e.disciplinas) = 'array'
              AND e_val IS NOT NULL
              AND btrim(e_val) <> ''
        ) AS src
        WHERE btrim(src.val) <> ''
        ON CONFLICT (lower(nombre)) DO NOTHING;
        """
    )

    # ------------------------------------------------------------------ #
    # 1.d.2) Enlazar `deportista.disciplina_id` por match case-insensitive
    #        `lower(btrim(d.disciplina)) = lower(x.nombre)`. Solo filas con
    #        disciplina texto no vacia. Idempotente (UPDATE determinista).
    # ------------------------------------------------------------------ #
    op.execute(
        """
        UPDATE deportista d
        SET disciplina_id = x.id
        FROM disciplina x
        WHERE x.id IS NOT NULL
          AND d.disciplina IS NOT NULL
          AND btrim(d.disciplina) <> ''
          AND lower(btrim(d.disciplina)) = lower(x.nombre);
        """
    )

    # ------------------------------------------------------------------ #
    # 1.d.3) Enlazar `categoria.disciplina_id` por MODA NO AMBIGUA: si todos los
    #        deportistas de la categoria (con disciplina_id no nulo) comparten UNA
    #        sola disciplina => asignarla; si 0 o mezcla => NULL (no se toca).
    #        count(distinct disciplina_id) = 1 sobre el grupo por categoria_id.
    #        Idempotente (UPDATE determinista; subconsulta recalcula el mismo set).
    # ------------------------------------------------------------------ #
    op.execute(
        """
        UPDATE categoria c
        SET disciplina_id = sub.disc_id
        FROM (
            SELECT
                d.categoria_id AS cat_id,
                -- PostgreSQL no tiene min(uuid); el HAVING garantiza 1 sola
                -- disciplina distinta, asi que tomamos ese unico valor.
                (array_agg(DISTINCT d.disciplina_id))[1] AS disc_id
            FROM deportista d
            WHERE d.categoria_id IS NOT NULL
              AND d.disciplina_id IS NOT NULL
            GROUP BY d.categoria_id
            HAVING count(DISTINCT d.disciplina_id) = 1
        ) AS sub
        WHERE c.id = sub.cat_id;
        """
    )

    # ------------------------------------------------------------------ #
    # 1.d.4) `entrenador` NO se enlaza (multi-disciplina es S4). Solo se uso
    #        arriba para SEMBRAR el catalogo; `entrenador.disciplinas` queda
    #        INTACTO. (Sin operacion aqui.)
    #
    #        Verificacion sugerida (CI / manual):
    #          -- catalogo sin huerfanos: todo texto distinto no vacio quedo
    #          SELECT count(*) FROM disciplina;          -- >= n. de textos distintos
    #          -- toda FK no nula apunta a fila existente (FK lo garantiza)
    #          -- RLS de categoria/deportista intacta (con rol latinosport_app,
    #          --   sin app.current_org => 0 filas; disciplina => todas, es global)
    # ------------------------------------------------------------------ #


def downgrade() -> None:
    # Orden inverso. NO se toca `deportista.disciplina` (texto legacy, se conserva).
    # Las filas sembradas en `disciplina` desaparecen con el DROP TABLE (el
    # downgrade revierte el esquema; los datos derivados no se "des-siembran" a
    # mano porque la tabla destino se elimina).

    # 1.c inverso: indice + columna de deportista.
    op.drop_index("ix_deportista_disciplina_id", table_name="deportista")
    op.drop_column("deportista", "disciplina_id")

    # 1.b inverso: indice + columna de categoria.
    op.drop_index("ix_categoria_disciplina_id", table_name="categoria")
    op.drop_column("categoria", "disciplina_id")

    # 1.a inverso: DROP TABLE disciplina. Arrastra su indice funcional
    # `uq_disciplina_nombre_lower` y los GRANTs adheridos por OID. No hay policy
    # RLS que dropear (la tabla nunca la habilito).
    op.drop_table("disciplina")
