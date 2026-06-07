# Epic: Entrenador con CI + OCR + multi-disciplina (S4 · `feat/entrenador-ci`)

> Sesión 4 (última) del roadmap `docs/specs/personas-y-disciplinas.md` (punto #6).
> Base = `main` con S1 (rename deportista) + S2 (catálogo `disciplina`) + S3 (CI único / OCR).
> Esta spec es **efímera**: se borra en el commit que cierra el epic, **junto con el roadmap**.

## Objetivo y valor
Que **ADMIN/ENTRENADOR** registre entrenadores con **CI** (único por org, deduplicación) y
**OCR** del documento (reusa componente de S3), y que su **multi-disciplina** referencie el
**catálogo global de S2** (reemplaza el `disciplinas` JSONB texto libre). Data-preserving:
prod tiene datos reales.

## Alcance MVP / Fuera de alcance
- **MVP:** `entrenador.ci` + índice único parcial `(org_id, ci) WHERE ci IS NOT NULL`; tabla
  M:N `entrenador_disciplina` (tenant, RLS); data-migration JSONB→refs catálogo; API y form con
  CI + OCR + multiselect de disciplinas; lista con chips por `nombre`.
- **Fuera de alcance:** dropear el JSONB legacy (se conserva, ver D1); cambios en catálogo S2,
  en deportista/tutor (S3) o en categoría (S2); fases 2/3 (portal tutor, SIN, etc.).

## Decisiones de producto (tomadas — NO reabrir)
- **D1 — JSONB legacy se CONSERVA.** `entrenador.disciplinas` (JSONB) NO se dropea en 0017
  (data-preserving, simetría con S2 que conservó `deportista.disciplina`). La API **deja de
  escribirlo**.
- **D2 — Alta con CI duplicado → 409 RECHAZAR.** El entrenador **ES** cuenta de login: no se
  "recupera" ni se crea segundo login (a diferencia de tutor en S3). `ci=NULL` permitido
  múltiples veces. Mensaje guía a editar el entrenador existente.

## Reglas de negocio (SRS §3 roles · §4.1 multi-tenant)
- CI **único por organización** (índice parcial; múltiples NULL OK). Aislamiento por `org_id`.
- `entrenador_disciplina` es **tenant** (RLS por `org_id`); `disciplina` es **catálogo global**
  (sin org_id/RLS, de S2) — el join referencia el catálogo sin filtrarlo por tenant.
- Solo disciplinas **activas** del catálogo son enlazables (422 si inactiva/inexistente).

---

## Contratos compartidos (cerrados — reproducir TAL CUAL; Edit no Write en archivos cruzados)

### CONTRATO 1 — Migración 0017 (`down_revision="0016"`, a mano, data-preserving)
- `entrenador.ci`: `ALTER TABLE entrenador ADD COLUMN ci text NULL;` + índice único PARCIAL:
  `CREATE UNIQUE INDEX uq_entrenador_org_ci ON entrenador (org_id, ci) WHERE ci IS NOT NULL;`
  (múltiples NULL OK; único por org). **SIN RLS nueva** (entrenador ya la tiene).
- Tabla M:N **`entrenador_disciplina`** (tenant, RLS NULLIF fail-closed + GRANTs; patrón
  **EXACTO** de `entrenador_sucursal` en 0014): `id uuid PK gen_random_uuid()`,
  `org_id uuid NOT NULL FK organizacion ON DELETE CASCADE`,
  `entrenador_id uuid NOT NULL FK entrenador ON DELETE CASCADE`,
  `disciplina_id uuid NOT NULL FK disciplina(id) ON DELETE RESTRICT` (como `categoria.disciplina_id`),
  `created_at timestamptz now() NOT NULL`,
  `UNIQUE(entrenador_id, disciplina_id)` = `uq_entrenador_disciplina`,
  `INDEX ix_entrenador_disciplina_org_disc (org_id, disciplina_id)`.
  **ENABLE+FORCE RLS**; policy `org_isolation` USING/WITH CHECK =
  `org_id = NULLIF(current_setting('app.current_org', true), '')::uuid`;
  GRANT DML a `latinosport_app` + `GRANT USAGE,SELECT ON SEQUENCES`.
- **Data-migration idempotente** (corre como OWNER; preserva `org_id` del entrenador):
```sql
INSERT INTO entrenador_disciplina (org_id, entrenador_id, disciplina_id)
SELECT DISTINCT e.org_id, e.id, x.id
FROM entrenador e
CROSS JOIN LATERAL jsonb_array_elements_text(e.disciplinas) AS val
JOIN disciplina x ON lower(x.nombre) = lower(regexp_replace(btrim(val), '\s+', ' ', 'g'))
WHERE e.disciplinas IS NOT NULL AND jsonb_typeof(e.disciplinas) = 'array' AND btrim(val) <> ''
ON CONFLICT (entrenador_id, disciplina_id) DO NOTHING;
```
  Usa `regexp_replace('\s+',' ','g')` para **paridad con la normalización del seed de S2** (NO solo btrim).
- `downgrade`: drop policy/RLS + drop table `entrenador_disciplina`; drop index `uq_entrenador_org_ci`;
  drop column `entrenador.ci`. **NO toca `entrenador.disciplinas`** (JSONB intacto).

### CONTRATO 2 — Modelos (backend define `Base.metadata`; db-dev espeja)
- `models/entrenador.py` += `ci: Mapped[str | None]` (String, nullable). El índice parcial vive
  **SOLO** en la migración (no `UniqueConstraint` declarativo).
- Nuevo `models/entrenador_disciplina.py`: `EntrenadorDisciplina(UUIDPkMixin, OrgScoped, Base)`
  (sin `TimestampMixin`; solo `created_at`), **gemelo de `EntrenadorSucursal`**.
  Registrar en `models/__init__.py`.

### CONTRATO 3 — API (backend produce → frontend consume)
- `EntrenadorCreate`: += `ci: str|None=None`, += `disciplina_ids: list[uuid]=[]`.
  **ELIMINA** `disciplinas: list[str]`.
- `EntrenadorUpdate`: += `ci: str|None=None` (None=no tocar; string=set+valida unicidad),
  += `disciplina_ids: list[uuid]|None=None` (None=no tocar; `[]`=limpiar; lista=REEMPLAZA).
  **ELIMINA** `disciplinas`.
- `EntrenadorOut`: += `ci: str|None`; **CAMBIA** `disciplinas` de `list[str]` a
  `list[DisciplinaRef]` (`{id,nombre}`, importado de `schemas/disciplina.py`).
- Service:
  - Validación **CI único por org**: pre-chequeo bajo RLS excluyendo el propio id en edición →
    409 `CiEnUso`; **+ capturar `IntegrityError`** del índice en flush por carreras.
  - Resolución de `disciplina_ids` con **replace semantics** (clonar `_resolver_sucursales` →
    `_resolver_disciplinas`), validando que cada disciplina exista y esté activa vía
    `disciplina_svc.get_disciplina_activa_o_error` → 404/422.
  - **PRESERVAR la transacción que crea la cuenta de login**: chequeo CI **ANTES** de crear el
    usuario; ya **no** se escribe el JSONB.
  - `_to_out`/listar pueblan `disciplinas` (join `entrenador_disciplina ⨝ disciplina`, **sin
    N+1**: helper `disciplinas_por_entrenador`).
- **409 de CI**: `detail` string simple (`"Ya existe un entrenador con ese CI en tu
  organización"`). **NO** devolver id (no tocar `ApiError`).

### CONTRATO 4 — Frontend
- `api/types.ts`: `EntrenadorOut.disciplinas` → `DisciplinaRef[]`; `EntrenadorCreate`/`Update`
  += `ci?`, `disciplina_ids`. (`DisciplinaRef` y `api.disciplinasCatalogo()` YA existen de S2.)
- `features/entrenadores/NuevoEntrenador.tsx`: campo **CI** (opcional); integrar
  **`components/ocr/DocumentScanner`** (`onExtract` prellena ci/nombres; edición manual de
  respaldo; **la imagen NO se guarda**); **multiselect de disciplinas** poblado por
  `api.disciplinasCatalogo()` (reemplaza el tag-input de texto libre); precarga en edición desde
  `entrenador.disciplinas.map(d=>d.id)`; envía `disciplina_ids`. En catch 409 → marca el campo
  CI con "Ya existe un entrenador con ese CI" + guía a editar.
- `features/entrenadores/Entrenadores.tsx`: los chips de disciplinas leen `d.nombre` (objetos, no
  strings). Actualizar tests/mocks (`disciplinas: [{id,nombre}]`).

---

## Fases (árbol SSS)
- **Fase 0 (esta spec):** contratos fijados.
- **Fase 1 — PARALELO (carpetas disjuntas; contratos arriba ya cerrados):**
  - **(a) db-dev** → `migrations/`: migración 0017 (CONTRATO 1).
  - **(b) backend-dev** → `backend/`: modelos + schemas + service + router (CONTRATOS 2 y 3).
  - **(c) frontend-dev** → `frontend/`: tipos + form (CI+OCR+multiselect) + lista + tests (CONTRATO 4).
  - El esquema físico está 100% definido → **db-dev no espera a backend**.

## Criterios de aceptación (DoD)
- **CI único por org** verificado: no 2 con mismo CI no-nulo; múltiples NULL OK. Alta con CI
  duplicado → **409 SIN crear segundo usuario/login** (D2).
- **Data-migration data-preserving + idempotente**: todo valor JSONB no vacío mapeado al
  catálogo, sin huérfanos; `entrenador.disciplinas` **intacto**; roundtrip **0017↔0016** OK.
- **Flujo de alta con cuenta de login intacto**: test `crear` verde; `EmailEnUso` sigue.
- **RLS `entrenador_disciplina` fail-closed**: query sin contexto de tenant ⇒ 0 filas; catálogo
  global (`disciplina`) sin fuga de datos de tenant.
- **Gates:** backend `ruff` / `mypy` / `import-linter` / `pytest`; frontend `tsc` / `lint` /
  `build` / `test`. OCR **no sube imagen** (privacidad de menores, RNF-02).
- **Cierre del epic (lo hace main, S4 es la última sesión):** se borra `docs/specs/entrenador-ci.md`
  **Y** `docs/specs/personas-y-disciplinas.md`, y se actualiza `docs/HANDOFF.md`.

## Decisiones de producto pendientes (para el usuario)
— sin decisiones de producto pendientes (D1 y D2 ya cerradas; el diseño técnico lo fijó
`platform-architect`). —
