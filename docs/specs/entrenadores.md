# Epic B · Gestión de Entrenadores

> **Spec efímera (SSS, pilar 1).** Vive solo mientras el epic está en vuelo. Se **borra en
> el commit que cierra el epic** (último merge a `main`). No crear `docs/archive/`. La
> memoria institucional son el código, los commits y los tests.
>
> Rama: `epic/entrenadores` · Migración: `0013_entrenadores` · Stack aislado: `-p
> latinosport_entrenadores` (DB 5437 / Redis 6382 / API 8013 / Web 5183, ver plan §2).
> Base: `origin/main` = `d8f5be5` (migraciones `0001→0011`).

## Objetivo y valor

Que el **Administrador** gestione a sus entrenadores desde la app —crearlos con su **cuenta
de login** (sin sembrarlos a mano en `seed.py`), editarlos, darlos de baja/reactivar— y
declarar las **disciplinas a cargo** de cada uno. Como efecto, al armar **Horarios** el
entrenador se elige de una **lista real** (selector) en vez de teclear un UUID a mano.

Hoy `entrenador` ya existe como perfil pero **no hay endpoint** para listarlos ni crearlos;
el coach se siembra a mano. `usuario` (email UNIQUE global, role `ADMIN|ENTRENADOR`, `activo`)
ya existe. Este epic cierra ambos huecos (es la "deuda menor" del HANDOFF: `GET /entrenadores`
+ selector real en Horarios).

## Alcance MVP

- Columna `entrenador.disciplinas` (JSONB, lista de strings) + migración + modelo.
- API CRUD bajo `/api/v1/entrenadores` (listar para cualquier rol; alta/edición solo ADMIN).
- Servicio que crea `usuario`(ENTRENADOR) + `entrenador` en una sola transacción, reusando
  `hash_password` (sin tocar el auth core).
- Pantalla **Entrenadores** (ADMIN): lista + alta + edición + baja/reactivación.
- **Horarios:** selector real de entrenador (lista de activos) en `NuevoHorario.tsx`,
  conservando la opción "Sin entrenador".

## Fuera de alcance

- **No** se modifica el auth core (`core/tenant.py`, `core/security.py`, `api/v1/auth.py`).
- **No** hay borrado físico de entrenadores (la baja es `activo=false`; un entrenador con
  historial no se borra).
- **No** se gestiona la asignación entrenador↔sucursal/categoría aquí (el scoping del
  entrenador por sucursal vive en Asistencia/Horarios y no se toca).
- **No** se toca el login/JWT del entrenador (ya existe; este epic solo crea el `usuario`).
- Áreas de las sesiones paralelas: **A · Super Admin** y **C · Sucursales/Categorías + Recibo
  por WhatsApp** — fuera de alcance, no tocar.
- Cualquier feature de Fase 2/3 (portal tutor, chatbot, etc.).

## Reglas de negocio (RF-* y SRS §)

- **RF (B):** un entrenador = un `usuario`(role=ENTRENADOR) + un perfil `entrenador` ligado
  por `entrenador.usuario_id`. Crear/editar/listar/baja desde la app (no por seed).
- **Multi-tenant (SRS §4.1 / RNF-01):** `entrenador` y `usuario` son filas con `org_id`; el
  INSERT corre bajo el GUC `app.current_org` del admin que crea → RLS aísla por org. Un admin
  solo ve/gestiona entrenadores de su org.
- **Roles (SRS §3):** listar = cualquier rol autenticado (para poblar selectores). Alta/edición
  = **solo ADMIN**.
- **Baja lógica:** `activo=false` en el `usuario` (no borrado físico). Reactivar = `activo=true`.
- **Email UNIQUE global** en `usuario` (cruza orgs) → ver "GOTCHA crítico de RLS" abajo.

## Fases

Las tres fases se pueden construir **en paralelo** porque los contratos de esquema y API ya
están fijados por `main` (abajo). Reparto por dueño de carpeta (CLAUDE.md §Roster):

### Fase 1 — Esquema (dueño: **db-dev** + **backend-dev** para el modelo)
- **db-dev:** migración `0013_entrenadores` que añade `entrenador.disciplinas` JSONB. Sin RLS
  nueva (la tabla ya tiene su policy `org_isolation` con patrón NULLIF).
- **backend-dev:** añade la columna al modelo SQLAlchemy `Entrenador`.
- Ambos contra el **Contrato de esquema** de abajo.
- *Nota de cadena Alembic (plan §3/§6):* `down_revision="0011"` **durante el desarrollo**;
  `main` lo reajusta a `0012` al integrar (A aterriza primero como `0012` → cadena lineal
  `0011→0012→0013`). No tocar la cadena en la sesión.

### Fase 2 — API + servicio (dueño: **backend-dev**)
- `schemas/entrenador.py`, `services/entrenador.py`, `api/v1/entrenadores.py` (router nuevo).
- Registrar el router en `backend/app/api/v1/__init__.py` (**Edit, append-only**).
- Implementa los 3 endpoints del **Contrato de API** + la defensa del **GOTCHA de RLS**.

### Fase 3 — Frontend (dueño: **frontend-dev**)
- Pantalla **Entrenadores** en `frontend/src/features/entrenadores/*` (lista + alta + edición).
- Cliente y tipos: `frontend/src/api/client.ts`, `frontend/src/api/types.ts` (**Edit, append-only**).
- Ruta + nav: `frontend/src/App.tsx`, `frontend/src/components/shell/nav.ts`,
  `frontend/src/components/shell/Sidebar.tsx` si aplica (**Edit, append-only**, gateado ADMIN).
- **Selector en Horarios:** en `frontend/src/features/horarios/NuevoHorario.tsx` reemplazar
  el `<Field>` de texto "ID de entrenador" (hoy líneas ~222-228) por un `<SelectField>`
  poblado con `GET /entrenadores?solo_activos=true`, conservando "Sin entrenador" (`null`).

> Frontend depende del **contrato** de API, no de su implementación: por eso puede construir
> contra el contrato en paralelo con backend, y verificarse E2E cuando ambos aterricen.

## Contrato de esquema (fijado por main — implementar tal cual)

- Añadir a la tabla `entrenador` la columna **`disciplinas`** tipo **JSONB**, `NOT NULL`,
  `server_default '[]'::jsonb` (lista de strings; ej. `["Fútbol","Natación"]`).
  `especialidad` (texto libre) **ya existe y se mantiene**.
- Migración nueva **`0013_entrenadores`**, `down_revision="0011"` **durante el desarrollo**
  (main reajusta a `0012` al integrar — ver Fase 1). **Sin RLS nueva.**
- Modelo SQLAlchemy:
  ```python
  disciplinas: Mapped[list[str]] = mapped_column(
      JSONB, nullable=False, server_default=text("'[]'::jsonb")
  )
  ```

## Contratos compartidos — API (backend produce → frontend consume)

Prefijo: `/api/v1/entrenadores`.

### Schemas (Pydantic, `schemas/entrenador.py`)
- **`EntrenadorCreate`**:
  `{ nombres: str, email: EmailStr, password: str (min 8), especialidad: str|None=None, disciplinas: list[str]=[] }`
- **`EntrenadorUpdate`** (todos opcionales):
  `{ nombres: str|None, especialidad: str|None, disciplinas: list[str]|None, activo: bool|None, password: str|None (min 8 si viene) }`
- **`EntrenadorOut`**:
  `{ id: uuid, usuario_id: uuid, nombres: str, email: str, especialidad: str|None, disciplinas: list[str], activo: bool }`
  — `email` y `activo` provienen del `usuario` ligado (join por `entrenador.usuario_id`).

### Endpoints
- **`GET /entrenadores?solo_activos=bool` (default false)** → `200 list[EntrenadorOut]`.
  Autenticado, **cualquier rol** (`Depends(set_tenant_context)`), scoped por RLS (org).
  Pobla selectores (Horarios) y la pantalla de gestión. **Orden por `nombres`.**
- **`POST /entrenadores`** → **SOLO ADMIN** (`Depends(require_role("ADMIN"))`). Crea, en la
  **misma transacción**:
  - `usuario`(role=`ENTRENADOR`, `activo=true`, `password_hash=hash_password(password)`)
  - `entrenador`(usuario_id, nombres, especialidad, disciplinas)
  - con `org_id` = la org del admin (el GUC `app.current_org` ya está fijado → RLS OK; mismo
    patrón que `_get_or_create_usuario` de `seed.py`).
  - Devuelve `EntrenadorOut` con **201**. Email ya en uso → **409** (ver GOTCHA).
- **`PUT /entrenadores/{id}`** → **SOLO ADMIN**. Actualiza `nombres/especialidad/disciplinas`
  en `entrenador`, y `activo` (+ `password` si viene) en el `usuario` ligado. La
  **baja/reactivación** es `activo=false/true`. No encontrado → **404**.
- **No hay DELETE** (la baja se hace con `PUT activo=false`).

### Códigos de estado (resumen)
| Situación | Código |
|---|---|
| GET lista OK / PUT OK | 200 |
| POST creado | 201 |
| Rol insuficiente (ENTRENADOR intenta POST/PUT) | 403 |
| `PUT /{id}` con id inexistente (en la org) | 404 |
| Email ya en uso (en esta org **o** en otra — ver GOTCHA) | 409 |
| Body inválido (password < 8, email mal formado, tipos) | 422 |

## GOTCHA crítico de RLS (Hard constraint para backend-dev)

`usuario.email` es **UNIQUE global** (cruza orgs), pero un `SELECT` de pre-chequeo corre bajo
RLS y **NO ve** usuarios de otras orgs. Un email ya usado en **OTRA** org pasaría el
pre-chequeo y reventaría en el INSERT con `IntegrityError` de la constraint global. Por eso el
servicio debe:

- **(a)** pre-chequear el email **dentro de la org** (da un mensaje mejor), **y además**
- **(b)** capturar el `IntegrityError`/violación de unicidad del INSERT y traducirlo a **409**
  (con `rollback`).

**No confiar solo en el pre-chequeo.** (Consistente con el gotcha de RLS+pooling y fail-closed
del HANDOFF: el contexto de tenant limita lo que el `SELECT` ve.)

## Criterios de aceptación / DoD

Funcionales:
- [ ] `GET /entrenadores` devuelve la lista de la org del usuario, ordenada por `nombres`;
      `?solo_activos=true` excluye los `activo=false`. Accesible por ADMIN y ENTRENADOR.
- [ ] `POST /entrenadores` (ADMIN) crea `usuario`(ENTRENADOR, activo) + `entrenador` en **una
      transacción**, devuelve `201 EntrenadorOut` con `email`/`activo` del usuario ligado, y el
      entrenador puede **hacer login** con el email+password dados.
- [ ] `POST` con email ya usado **en otra org** ⇒ **409** (no 500): se cazó por captura de
      `IntegrityError` + rollback, **no** solo por el pre-chequeo (GOTCHA verificado).
- [ ] `POST/PUT` por un ENTRENADOR ⇒ **403**. `GET` por ENTRENADOR ⇒ **200**.
- [ ] `PUT /{id}` edita nombres/especialidad/disciplinas y `activo` (+ password si viene);
      `activo=false` da de baja (el usuario ya no puede entrar) y `activo=true` reactiva;
      id inexistente ⇒ **404**; password < 8 ⇒ **422**.
- [ ] **Selector real en Horarios funcionando:** `NuevoHorario.tsx` muestra un `<select>` de
      entrenadores activos (`?solo_activos=true`) con la opción "Sin entrenador" (`null`);
      crear/editar un horario con un entrenador elegido persiste su `entrenador_id`, y "Sin
      entrenador" persiste `null`. Ya **no** se teclea el UUID a mano.
- [ ] Pantalla **Entrenadores** (ruta `/entrenadores`, gateada ADMIN con `RoleRoute
      allow={['ADMIN']}` + item en `nav.ts` con `roles:['ADMIN']`): lista (nombres, email,
      especialidad, chips de disciplinas, badge activo/inactivo), "Nuevo entrenador" (form:
      nombres, email, password, especialidad, disciplinas multi-tag) y edición (mismos campos
      **salvo email**; toggle activo; password opcional para reset).

Dominio / gates (DoD de CLAUDE.md):
- [ ] **Aislamiento RLS verificado**: un `GET /entrenadores` sin contexto de tenant (o de otra
      org) **no** devuelve entrenadores de otro `org_id`; el `POST` inserta con el `org_id` del
      admin (no de otra org). Test `@pytest.mark.db`.
- [ ] Validación de arquitectura en verde (`lint-imports`: el núcleo no importa adaptadores
      concretos; el servicio usa `hash_password` de `core/security.py`, no lo reimplementa).
- [ ] Typecheck sin errores nuevos (`mypy` backend / `tsc` frontend).
- [ ] Tests rápidos en verde (`pytest -q`); lint + build en verde donde se tocó (ruff, eslint,
      vite build).
- [ ] `git diff` revisado por **main** (no solo el reporte del agente).
- [ ] UX confirmada en navegador: alta de entrenador → aparece en la lista → aparece en el
      selector de Horarios → login con sus credenciales.
- [ ] **Última fase del epic** ⇒ la spec (`docs/specs/entrenadores.md`) **se borra en ese
      commit** y `docs/HANDOFF.md` se actualiza (poda la "deuda menor" de `GET /entrenadores`).

> Cobranza/idempotencia de webhook: **no aplica** (este epic no toca pagos).

## Hard constraints (NO tocar)

- **No tocar** `backend/app/core/tenant.py`, `backend/app/core/security.py`,
  `backend/app/api/v1/auth.py`. La creación de `usuario` se hace por **servicio** reusando
  `hash_password`, sin modificar el auth core.
- **No tocar** las áreas de las sesiones paralelas: **A · Super Admin** y **C ·
  Sucursales/Categorías + Recibo por WhatsApp**.
- **No tocar** la cadena Alembic más allá de la migración `0013` (main resuelve `down_revision`).
- **Crear entrenador respeta RLS:** el INSERT corre bajo el `app.current_org` del admin. Sin
  BYPASSRLS, sin debilitar el fail-closed.
- **Archivos compartidos = append-only con `Edit` (NUNCA `Write`):**
  - `backend/app/api/v1/__init__.py` (registrar el router)
  - `backend/app/models/__init__.py` (registrar el modelo si aplica)
  - `frontend/src/api/client.ts`, `frontend/src/api/types.ts`
  - `frontend/src/components/shell/nav.ts`, `frontend/src/components/shell/Sidebar.tsx` (si aplica)
  - `frontend/src/App.tsx`
  Cada sesión **añade** sus líneas; **main** resuelve los conflictos triviales al merge.

## Decisiones de producto pendientes (para el usuario)

Ninguna bloqueante: `main` ya fijó esquema, API, alcance y fronteras. Posibles pulidos a
confirmar **después** del MVP (no bloquean el epic, no especificar como hecho):

1. **¿Disciplinas libres o de un catálogo cerrado?** Hoy `disciplinas` es lista de strings
   libres (multi-tag). Si en el futuro se quiere un catálogo por org (selección, no texto),
   sería un epic aparte. *(Asumido para el MVP: texto libre.)*
2. **¿Mostrar al entrenador su propio perfil/editarse a sí mismo?** El MVP solo da gestión a
   ADMIN; el entrenador puede listar pero no editar. *(Asumido: sí, solo ADMIN gestiona.)*
3. **¿Notificar al entrenador sus credenciales** (email/WhatsApp) al crearlo? Fuera de alcance
   del MVP; el admin las comunica manualmente. *(Asumido: manual.)*
