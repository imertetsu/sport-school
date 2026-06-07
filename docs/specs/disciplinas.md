# Epic: Disciplinas (Sesión 2 · `feat/disciplinas`)

> Spec efímera. Cubre puntos #3 + #7 del roadmap `personas-y-disciplinas.md` (coordinación
> multi-sesión — NO borrar ese roadmap; vive hasta S4). Esta spec se borra en el commit que
> cierra el epic. Worktree aislado: `D:\Imer\SportSchool-disciplinas` (rama `feat/disciplinas`,
> base = S1 con rename alumno→deportista + migración 0015).

## Objetivo y valor

Catálogo **GLOBAL** de disciplinas gestionado por **superadmin**, más `categoria.disciplina_id`
y `deportista.disciplina_id`, migrando los textos-libre existentes a referencias del catálogo.
Beneficia a superadmin (gobierna las disciplinas del SaaS) y a ADMIN/ENTRENADOR (selects
consistentes, sin "Voley" vs "Vóleibol" descontrolado). **Data-preserving**: prod tiene datos reales.

## Decisiones (técnicas resueltas — NO reabrir)

- `disciplina` = tabla **GLOBAL, SIN `org_id`, SIN RLS** (mismo patrón que `plataforma_admin` /
  `organizacion`). CRUD solo superadmin desde `/plataforma`. Lectura para escuela expone **solo**
  el catálogo (cero datos de tenant) → no rompe aislamiento (sub-duda #3 resuelta: tabla sin datos
  de tenant es segura de exponer).
- **Redundancia `deportista.disciplina` (sub-duda #2):** el deportista guarda su disciplina
  **directo** vía `deportista.disciplina_id` (FK propia, `ON DELETE SET NULL`), NO derivada de la
  categoría. La columna texto `deportista.disciplina` se **conserva como legacy** (no se dropea).
  Contrato que S3 consumirá en el form de alta de deportista.
- Unicidad case-insensitive vía **índice funcional** `lower(nombre)` en la migración, NO
  `UniqueConstraint` declarativo. NO se fusionan sinónimos ("Voley" ≠ "Vóleibol").
- Retiro de una disciplina = **soft-delete** (`activo=false` vía PUT), nunca hard delete (FK RESTRICT
  desde categoría).
- `entrenador.disciplinas` (JSONB texto) se usa **solo para sembrar** el catálogo; NO se enlaza ni se
  toca (su relación multi-disciplina es S4).

## CONTRATO 1 — Esquema (migración 0016, `down_revision="0015"`, a mano, data-preserving)

**1.a Tabla `disciplina` (GLOBAL, SIN org_id, SIN RLS):**
```sql
CREATE TABLE disciplina (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  nombre text NOT NULL,
  activo boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_disciplina_nombre_lower ON disciplina (lower(nombre));  -- dedupe case-insensitive
GRANT SELECT, INSERT, UPDATE, DELETE ON disciplina TO latinosport_app;
-- NO ENABLE/FORCE ROW LEVEL SECURITY (tabla de plataforma, no tenant).
```
Modelo `Disciplina(UUIDPkMixin, TimestampMixin, Base)` — **SIN `OrgScoped`**. La unicidad
`lower(nombre)` vive en la migración (índice funcional), no como UniqueConstraint declarativo.

**1.b `categoria.disciplina_id`** (categoria sigue siendo tenant con RLS intacta; solo se añade columna):
```sql
ALTER TABLE categoria ADD COLUMN disciplina_id uuid NULL REFERENCES disciplina(id);  -- ON DELETE RESTRICT (default)
CREATE INDEX ix_categoria_disciplina_id ON categoria (disciplina_id);
```

**1.c `deportista.disciplina_id`** (FK propia; se CONSERVA `deportista.disciplina` texto como legacy):
```sql
ALTER TABLE deportista ADD COLUMN disciplina_id uuid NULL REFERENCES disciplina(id) ON DELETE SET NULL;
CREATE INDEX ix_deportista_disciplina_id ON deportista (disciplina_id);
```

**1.d Migración de datos (idempotente, corre como OWNER → ve todas las orgs; match por texto, NO cruza orgs):**
- **Sembrar `disciplina`** con valores DISTINTOS no vacíos de `deportista.disciplina` (texto) Y
  `entrenador.disciplinas` (JSONB; desanidar con `jsonb_array_elements_text`). Filtro:
  `IS NOT NULL AND trim() <> ''`. Nombre canónico = **primera aparición tras trim + colapsar
  espacios** (NO `initcap`; preserva acentos/escritura original). Dedupe lo hace el índice
  `lower(nombre)`: `INSERT ... ON CONFLICT (lower(nombre)) DO NOTHING`. **NO fusionar sinónimos.**
- **Enlazar `deportista.disciplina_id`:** `UPDATE deportista SET disciplina_id = (match por
  lower(trim(disciplina)) = lower(nombre))`.
- **Enlazar `categoria.disciplina_id`:** por **moda NO ambigua** de las disciplinas de sus
  deportistas (una sola disciplina entre ellos → asignar; 0 o mezcla → NULL).
- **`entrenador` NO se enlaza** (multi-disciplina es S4). Solo se usa para SEMBRAR. `entrenador.disciplinas` intacto.
- **`downgrade`:** drop columnas `disciplina_id` (categoria, deportista) + índices + grants + tabla
  `disciplina`, en orden inverso. **NO toca** `deportista.disciplina` texto.

## CONTRATO 2 — API (backend produce → frontend consume)

- **CRUD superadmin** (en `api/v1/plataforma.py`, reusa `require_superadmin`, prefijo `/plataforma`):
  - `GET /plataforma/disciplinas` → todas (activas + inactivas).
  - `POST /plataforma/disciplinas` → 409 si `lower(nombre)` ya existe.
  - `PUT /plataforma/disciplinas/{id}` → renombrar y/o `activo`; 409 colisión, 404 no existe.
  - Retiro = **soft-delete vía PUT `activo=false`** (NO hard delete, por FK RESTRICT de categoría).
- **Lectura para escuela:** `GET /catalogo/disciplinas?solo_activas=true` con
  `Depends(set_tenant_context)` (ADMIN y ENTRENADOR). Respuesta = SOLO catálogo, cero datos de
  tenant: `DisciplinaOut {id, nombre}`.
- **Categoría:** `CategoriaCreate` / `CategoriaUpdate` += `disciplina_id: uuid | None = None`
  (validar que exista y esté activa → 404/422); `CategoriaOut` += `disciplina_id` y nested
  `disciplina: {id, nombre} | None`.
- **Schemas nuevos** en `schemas/disciplina.py`: `DisciplinaOut{id,nombre}`,
  `DisciplinaAdminOut{id,nombre,activo,created_at}`, `DisciplinaCreate{nombre}`,
  `DisciplinaUpdate{nombre?,activo?}`.

## CONTRATO 3 — Frontend

- **Consola `/plataforma`** (sesión superadmin separada, `platformApi`): pantalla
  `features/plataforma/Disciplinas.tsx` + `NuevaDisciplina.tsx` (espejo de
  `SuperAdmins.tsx` / `NuevoSuperAdmin.tsx`), tab en `PlataformaShell.tsx`, ruta en `App.tsx`.
  `platformApi` += `disciplinas()` / `crearDisciplina()` / `actualizarDisciplina()`.
- **Select de disciplina** (opcional, "— Sin disciplina —") en el form de **categoría**
  (`features/sucursales/NuevaCategoria.tsx`), poblado por `api.disciplinasCatalogo()` →
  `GET /catalogo/disciplinas`.
- **Tipos** en `api/types.ts`: `DisciplinaRef{id,nombre}`, `Disciplina{+activo,created_at}`,
  `DisciplinaCreate`, `DisciplinaUpdate`; `Categoria*` += `disciplina_id?` / `disciplina?`.
- **Fuera de S2:** el select de disciplina en el form de ALTA DE PERSONA (deportista/entrenador) es
  S3/S4. Aquí solo el de categoría.

## Fases

- **Fase 0 (esta spec):** contratos fijados. ✓
- **Fase 1 — PARALELO** (carpetas disjuntas, contratos fijos arriba; árbol SSS → PARALELO):
  - **(a) db-dev** (`migrations/`): migración 0016 — esquema (1.a/1.b/1.c) + data-migration
    idempotente (1.d) + downgrade.
  - **(b) backend-dev** (`backend/`): modelo `Disciplina` + FKs en categoria/deportista + schemas
    (`schemas/disciplina.py`) + CRUD superadmin en `plataforma.py` + endpoint lectura
    `/catalogo/disciplinas` + `disciplina_id` en CRUD categoría (`services/categoria.py`) + registro
    de routers.
  - **(c) frontend-dev** (`frontend/`): consola disciplinas + select en categoría + tipos/client.

  > Contrato compartido `Base.metadata` (backend define modelo → db-dev migra): backend-dev y db-dev
  > acuerdan nombres de columna/tabla/índice **exactamente como en el Contrato 1**. Si algo difiere →
  > handoff y parar (no driftear).

## Definition of Done

- **Migración data-preserving:** conteos pre/post iguales; ningún `org_id` cambia; todo texto
  distinto no vacío quedó en el catálogo (sin huérfanos); todo `disciplina_id` no nulo apunta a fila
  existente; **idempotente** (re-ejecutar el seed no duplica — gracias al `ON CONFLICT lower(nombre)`);
  roundtrip up/down OK sin perder `deportista.disciplina` texto. **`pg_dump` de respaldo antes de
  aplicar en prod.**
- **RLS:** tablas tenant (`categoria`, `deportista`) INTACTA (query sin contexto de tenant → 0 filas).
  `disciplina` SIN RLS pero con grants correctos (SELECT devuelve todas; global por diseño).
  Aislamiento: respuesta de `/catalogo/disciplinas` sin `org_id`.
- **Gates:** import-linter (núcleo no importa adaptadores), mypy y pytest verdes. Tests nuevos:
  CRUD superadmin incluyendo 409 "Voley"/"voley"; lectura por admin/entrenador; categoría con
  `disciplina_id` inválido → 404/422; data-migration idempotente. Frontend tsc/lint/build verdes.
- **Cierre del epic (lo hace main):** la spec `disciplinas.md` se borra en ese commit; `HANDOFF.md`
  se actualiza (≤ ~150 líneas). **NO borrar** `personas-y-disciplinas.md` (vive hasta S4).

## Fuera de alcance

- OCR / CI (`(org_id, ci)` único parcial, recuperar-por-CI) → S3.
- Entrenador: `entrenador.ci`, multi-disciplina referenciando el catálogo, deprecar `disciplinas`
  JSONB → S4. Aquí `entrenador.disciplinas` solo SEMBRA el catálogo; no se enlaza ni se modifica.
- Select de disciplina en formularios de alta de **persona** (deportista/entrenador) → S3/S4.
- Fusión de sinónimos en el catálogo (decisión manual del superadmin, no automática).

## Decisiones de producto pendientes (para el usuario)

— sin decisiones de producto pendientes — (las sub-dudas #2 y #3 del roadmap quedaron resueltas
arriba como decisiones técnicas; la #1 OCR es de S3).
