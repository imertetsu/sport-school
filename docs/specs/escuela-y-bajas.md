# Epic: escuela-y-bajas

Spec efímera (SSS pilar 1). Se **borra en el commit que cierra el epic**; no hay archive.
Decisiones de producto YA tomadas con el usuario — no re-preguntar.

## Objetivo y valor
Que el ADMIN reconozca su escuela al entrar (nombre + monograma de iniciales con color) y
pueda **personalizarla** (nombre + color, sin logo de archivo); que ADMIN/coach puedan
**dar de baja y reactivar** deportistas y entrenadores conservando todo el historial
(soft-delete, nunca borrado físico); y que el ADMIN pueda **editar por completo** un
deportista (datos + tutores + ficha médica), no solo darlo de alta.

## Alcance MVP
1. **Nombre + monograma de la escuela** visibles tras el login (TopBar), sin llamada extra.
2. **Editar la escuela** (solo ADMIN): SOLO `nombre` + `color` del monograma.
3. **Baja/Reactivación (soft-delete)** de deportistas y entrenadores (reversible).
4. **Edición completa de deportista**: datos básicos + tutores + ficha médica.

## Fuera de alcance (no meter en este epic)
- **Logo de archivo / subida de imágenes**: el "logo" ES un monograma de iniciales con color
  elegible. No se almacenan imágenes (coherente con RNF-02 / privacidad).
- Borrado FÍSICO de deportistas/entrenadores (jamás).
- Editar otros campos de la organización (país, moneda, modo de cobro, estado SUSPENDIDA →
  esos los toca el Super Admin / otros epics).
- Portal del tutor, passwordless OTP, chatbot, factura SIN (Fase 2/3 del SRS §2).

## Reglas de negocio (RF-* y SRS §)
- **Multi-tenant / aislamiento** (SRS §4.1, RNF-01): toda lectura/escritura scopeada por
  `org_id`. `organizacion` **NO tiene RLS** (es la única tabla sin org_id/policy) → el
  scoping de `/mi-escuela` es **responsabilidad del endpoint**, server-side.
- **Roles** (SRS §3): editar escuela y bajas de entrenador = **solo ADMIN**. Baja de
  deportista = ADMIN (coach es lectura acotada por disciplina; no gestiona altas/bajas).
- **Menores / consentimiento** (RNF-02): no existe deportista sin ≥1 tutor + consentimiento;
  el editor de tutores NO puede dejar al deportista sin tutor ni quitar al del consentimiento.
- **Soft-delete** (espejo de entrenador, que ya usa `usuario.activo`): dar de baja oculta de
  los flujos activos pero conserva el registro y su historial; reactivar lo restaura.

## Cambios de BD (UNA sola migración, db-dev)
- `deportista.activo` — `BOOLEAN NOT NULL DEFAULT true` (para soft-delete del deportista).
- `organizacion.color` — `TEXT NULL` (color del monograma; null ⇒ el front usa un default).
- **RLS:** sin policies nuevas. `deportista` ya es `OrgScoped` → añadir una columna NO cambia
  su policy. `organizacion` sigue **SIN RLS** (igual que hoy).
- **Backstop:** si por lo que sea hiciera falta una policy nueva (no debería), usar el patrón
  `NULLIF(current_setting('app.current_org', true), '')::uuid` (gotcha del GUC vacío).
- **Índices únicos parciales de CI**: son PARCIALES y viven SOLO en migraciones; un
  `alembic --autogenerate` sugerirá dropearlos → **ignorar** (la migración es la verdad).

## Contratos compartidos (definir ANTES de paralelizar — Edit, nunca Write)

### C1 — Login: objeto `org` aditivo en `TokenOut`
`backend/app/schemas/auth.py` (backend produce) ↔ `frontend/src/api/types.ts` (front consume).
- Añadir a `TokenOut` un objeto **`org: { id: UUID, nombre: str, color: str | null }`** (aditivo,
  no rompe consumidores). El login ya consulta `organizacion` por `org_id` (lee `estado`); se
  amplía esa misma lectura a `nombre`+`color`. Así el TopBar pinta nombre+monograma **sin
  llamada extra ni parpadeo**.
- Espejo TS: extender `TokenOut` con `org: { id: string; nombre: string; color: string | null }`.
- `/auth/me` NO cambia su contrato (sigue devolviendo `UserOut`); la `org` viaja en el login y
  el front la persiste (mismo lugar donde guarda el token/usuario).

### C2 — `GET /mi-escuela` y `PUT /mi-escuela` (gated ADMIN)
`backend/app/api/v1/` nuevo router + schema en `backend/app/schemas/`.
- `GET /mi-escuela` → `{ nombre, color }` de la org del usuario.
- `PUT /mi-escuela` body `{ nombre, color }` → devuelve el recurso actualizado.
- **Hard:** `organizacion` no tiene RLS → ambos endpoints **scopean SIEMPRE a `user.org_id`
  server-side** e **IGNORAN cualquier id que venga del cliente**. Un ADMIN solo lee/edita SU
  escuela. ENTRENADOR → 403.
- `color`: validar formato server-side (p. ej. `#RRGGBB` o vacío/null); `nombre` no vacío.

### C3 — `DeportistaUpdate` extendido con `tutores`
`backend/app/schemas/deportista.py` + `backend/app/services/deportista.py`
(`actualizar_deportista`) ↔ `frontend/src/api/types.ts`.
- Extender `DeportistaUpdate` con `tutores: list[TutorUpsert] | None = None` (opcional: si no
  viene, NO se tocan los tutores — preserva el comportamiento actual).
- `TutorUpsert`: como `TutorIn` + **`id: UUID | None`** (lista **reconciliable por id**:
  con `id` ⇒ edita el vínculo/tutor existente; sin `id` ⇒ alta/recupera-por-CI). Para borrar
  un vínculo, se omite de la lista entrante (reconciliación: lo que no llega se desvincula).
- `ficha_medica` ya existe en `DeportistaUpdate` (no añadir).
- **Invariante de menores (server-side, no confiar en UI):**
  - No permitir que la lista resultante quede **vacía** (≥1 tutor siempre) → 422.
  - No permitir **quitar al tutor del consentimiento** → 422 (mantener la atadura del
    `Consentimiento` existente). Mensaje claro de negocio.
  - Reusar `_resolver_tutor` (recuperar-por-CI: tutor con CI existente se reusa, no se duplica).

### C4 — Baja/Reactivación de deportista
`backend/app/api/v1/deportistas.py` + `frontend/src/api/types.ts`.
- **Recomendado (claridad + auditoría):** `POST /deportistas/{id}/baja` y
  `POST /deportistas/{id}/reactivar` → devuelven el `DeportistaDetailOut` actualizado.
  (Alternativa aceptable: `activo` dentro del PUT; preferir endpoints dedicados por simetría
  con la intención de auditar bajas — decisión técnica del backend-dev, dentro de estas reglas.)
- `GET /deportistas` gana filtro **`solo_activos: bool = Query(False)`** (ESPEJO EXACTO del de
  `/entrenadores`: por defecto muestra todos; el front togglea). Default coherente con
  entrenadores (hoy `solo_activos=False`).
- `DeportistaDetailOut` / `DeportistaListItem` exponen **`activo: bool`** para que el front
  muestre el badge "Inactivo" y el botón correcto.
- Entrenador: **sin cambios de contrato** (ya soporta baja/reactivar vía `PUT` con `activo`).

## Fases

> Paralelismo: **Fase 0 primero** (define modelos + migración + contratos). **Fase 1 es
> independiente** y paralelizable con Fase 2/3. **Fases 2 y 3 comparten** `deportistas.py`,
> `DeportistaUpdate` y `NuevoDeportista.tsx`/perfil → **seriales entre sí** (2 luego 3, o
> coordinar por archivo). Cada fase = uno o pocos commits.

### Fase 0 — Cimientos (modelos + migración + contratos)
Establece `Base.metadata` y los contratos; nada de UI todavía.
- **backend-dev** (posee `backend/`): añadir `Deportista.activo` y `Organizacion.color` a los
  modelos; definir los schemas de los contratos C1/C2/C3/C4 (objeto `org` en `TokenOut`,
  schemas `MiEscuela*`, `TutorUpsert` + `tutores` en `DeportistaUpdate`, `activo` en las
  salidas de deportista). NO migrar (eso es db-dev).
  - *Hard constraints:* NO tocar `frontend/`, `migrations/`, `infra/`. En archivos compartidos
    de schema usar **Edit, nunca Write**. No inventar policies RLS.
- **db-dev** (posee `migrations/`, `alembic.ini`): UNA migración que añada las 2 columnas
  (`deportista.activo` NOT NULL DEFAULT true; `organizacion.color` TEXT NULL). Sin policies
  nuevas. Numerar como **0020** (cabeza actual = 0019).
  - *Hard constraints:* NO tocar `backend/app/` ni `frontend/`. **Ignorar** sugerencias de
    `--autogenerate` de dropear los índices únicos parciales de CI. Modelo↔migración deben
    coincidir (el modelo lo define backend-dev; coordinar por handoff si difieren).
- **frontend-dev** (posee `frontend/`): espejar los tipos TS de C1/C3/C4 en
  `frontend/src/api/types.ts` (objeto `org` en `TokenOut`; `tutores`+`id` en el update; `activo`
  en deportista; cliente API de `/mi-escuela`, baja/reactivar, `solo_activos`). Solo tipos +
  cliente; la UI viene en sus fases.
  - *Hard constraints:* NO tocar `backend/`, `migrations/`, `infra/`. **Edit, nunca Write** en
    `types.ts` y `client`.

### Fase 1 — Escuela (independiente, paralelizable)
- **backend-dev** (`backend/`): implementar `GET/PUT /mi-escuela` (router nuevo, gated ADMIN,
  scope server-side a `user.org_id`, ignora id del cliente) + incluir el objeto `org`
  (`{id,nombre,color}`) en la respuesta del login (reusar la consulta de `organizacion` que ya
  existe en `login`).
  - *Hard constraints:* `PUT /mi-escuela` **NUNCA** confía en un id del cliente. ENTRENADOR →
    403. NO tocar `frontend/`/`migrations/`/`infra/`. Edit en `auth.py`/`schemas/auth.py`.
- **frontend-dev** (`frontend/`): TopBar muestra **nombre de la escuela + monograma**
  (iniciales en círculo con `color`, default si null), tomando `org` del login (sin fetch
  extra). Pantalla de **Ajustes/Escuela (solo ADMIN)** para editar nombre + selector de color
  (paleta acotada y/o input de color); guarda vía `PUT /mi-escuela` y refresca el TopBar.
  - *Hard constraints:* la ruta de Ajustes gated por rol ADMIN (`RoleRoute`). Sin subida de
    imágenes. NO tocar `backend/`/`migrations/`/`infra/`.

### Fase 2 — Bajas (soft-delete)
- **backend-dev** (`backend/`): endpoints `POST /deportistas/{id}/baja` y `/reactivar`
  (setean `activo`; ADMIN) + filtro `solo_activos` en `GET /deportistas` + `activo` en las
  salidas. Reusar el patrón del PUT de entrenador.
  - *Hard constraints:* **soft-delete, NUNCA DELETE físico**. Reversible. Scoped por RLS
    (deportista es OrgScoped). NO tocar `frontend/`/`migrations/`/`infra/`. Comparte
    `deportistas.py` con Fase 3 → **serial** o coordinar; **Edit, nunca Write**.
- **frontend-dev** (`frontend/`): en `DeportistaPerfil` botón **Dar de baja / Reactivar**
  (con confirmación) + badge "Inactivo"; en `DeportistasList` toggle **"Mostrar inactivos"**
  (espejo del de Entrenadores) cableado a `solo_activos`. En `Entrenadores.tsx`, sacar la baja
  del modal Editar a un **botón directo "Dar de baja/Reactivar"** en la fila/acciones.
  - *Hard constraints:* NO tocar `backend/`/`migrations/`/`infra/`. Comparte
    `DeportistaPerfil`/`NuevoDeportista` con Fase 3 → **serial**.

### Fase 3 — Edición completa de deportista
- **backend-dev** (`backend/`): ampliar `actualizar_deportista` para reconciliar `tutores`
  (alta/edición/baja por id; recuperar-por-CI vía `_resolver_tutor`) respetando el invariante
  de menores (≥1 tutor, no quitar el del consentimiento → 422). `ficha_medica` ya se aplica.
  - *Hard constraints:* validar el invariante **server-side** (no confiar en la UI). No tocar
    el dedup de CI del deportista en este slice (el índice único es backstop). NO tocar
    `frontend/`/`migrations/`/`infra/`. Comparte `deportistas.py`/`DeportistaUpdate` con Fase 2
    → **serial**; **Edit, nunca Write**.
- **frontend-dev** (`frontend/`): **modo edición** del formulario `NuevoDeportista` (hoy solo
  alta+recuperar) accesible desde `DeportistaPerfil` con botón **"Editar"**: precarga datos +
  tutores + ficha; al guardar usa `PUT /deportistas/{id}` con `tutores`. UI debe permitir
  añadir/editar/quitar tutores pero NO romper el invariante (deshabilitar quitar el último /
  el del consentimiento; el server es la red de seguridad real).
  - *Hard constraints:* NO tocar `backend/`/`migrations/`/`infra/`. Comparte
    `NuevoDeportista`/perfil con Fase 2 → **serial**.

## Criterios de aceptación (verificables, con bordes de dominio)
- **Login:** la respuesta incluye `org {id,nombre,color}`; el TopBar pinta nombre + monograma
  (iniciales con color, default si `color` null) sin segunda llamada ni parpadeo.
- **Editar escuela:** un ADMIN cambia `nombre` y `color` y lo ve reflejado tras refrescar el
  login/estado; un ENTRENADOR recibe **403**; un ADMIN que envíe un `id` de OTRA org en el body
  **NO** afecta a esa org (el endpoint scopea a su `org_id` e ignora el id) — borde clave.
- **Baja deportista:** dar de baja oculta al deportista de `GET /deportistas?solo_activos=true`,
  pero sigue accesible por id con `activo=false`; reactivar lo restaura; el historial (pagos,
  asistencia, tutores) se conserva. **No existe** ruta de borrado físico.
- **Baja entrenador:** botón directo de baja/reactivar funciona (contrato existente, sin cambios).
- **Edición de deportista — invariante de menores:**
  - Quitar TODOS los tutores → **422** (queda ≥1).
  - Quitar al tutor del consentimiento → **422**.
  - Editar datos + añadir un tutor nuevo + tutor con CI existente reusado (no duplicado) → OK.
  - Editar ficha médica vía el mismo PUT → OK (ya soportado).
- **Aislamiento RLS:** una query de deportistas sin contexto de tenant no devuelve filas de
  otro `org_id` (incluye los inactivos).

## DoD por fase (de CLAUDE.md)
- Validación de arquitectura en verde (import-linter: núcleo no importa adaptadores concretos).
- **Aislamiento RLS verificado**: query sin contexto de tenant no devuelve filas de otro org.
- Typecheck sin errores nuevos (delta vs baseline: `mypy` / `tsc`).
- Tests rápidos en verde (salvo baseline documentado en HANDOFF).
- Lint + build en verde si tocó esa área.
- `git diff` revisado por **main** (no solo el reporte del agente).
- UX confirmada en navegador si la fase tocó UI visible (Fases 1/2/3 tocan UI).
- Cobranza: N/A en este epic (no se toca el webhook); aun así, baja ≠ borrado de cuotas.
- **Última fase del epic:** la spec (`docs/specs/escuela-y-bajas.md`) se **borra en ese commit**
  y se actualiza `docs/HANDOFF.md` (estado + nueva migración 0020 + gotchas).

## Riesgos / gotchas a vigilar
- `organizacion` SIN RLS → el único guardián de `/mi-escuela` es el código: scope a
  `user.org_id`, ignorar id del cliente. Es el borde de seguridad más fácil de romper.
- Tres fases tocan `frontend/src/api/types.ts` y `deportistas.py`/`DeportistaUpdate`:
  respetar **Edit, nunca Write** y la serialidad Fase 2↔3.
- Reconciliación de tutores: cuidado con romper la atadura del `Consentimiento` al editar
  (es un FK a un tutor concreto). El invariante se valida server-side.
- `--autogenerate` querrá dropear los índices únicos parciales de CI → ignorar.
- Monograma con `color` null: el front necesita un default determinista (no romper UI vieja
  ni tokens existentes mientras no exista color).

## Decisiones de producto pendientes (para el usuario)
- **Ninguna bloqueante.** Las 4 features y sus cortes están decididos. (Si surge: paleta exacta
  de colores del monograma — fija o libre — es decisión menor delegable al frontend dentro del
  design-system; escalar solo si el usuario quiere una paleta de marca concreta.)
