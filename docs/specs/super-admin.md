# Epic A: Super Admin (consola de plataforma / onboarding del SaaS)

> Spec efímera (SSS, pilar 1). Se **borra en el commit que cierra el epic**. Rama `epic/super-admin`.
> Diseño técnico ya decidido por `platform-architect`. Defaults de producto confirmados por el usuario.

## Objetivo y valor

Hoy la BD de producción arranca **vacía**: no hay forma de dar de alta una escuela (organización)
ni un super-administrador de plataforma, y por tanto **no existe primer login**. Este epic construye
el **onboarding del SaaS**: una consola de plataforma (`/plataforma`, rol `SUPERADMIN`) donde el
operador de LATINOSPORT crea escuelas con su primer admin, las lista, y las **suspende/reactiva**.
Beneficiado: el **operador de plataforma** (SnapCoding / LatinoSport), que necesita administrar
tenants sin tocar la BD a mano y sin ver datos de negocio de ninguna escuela.

## Alcance MVP / Fuera de alcance

**MVP (este epic):**
- Identidad de plataforma propia (`plataforma_admin`, sin `org_id`, sin RLS).
- Estado de escuela `ACTIVA` | `SUSPENDIDA`.
- Auth de plataforma (JWT `role="SUPERADMIN"` sin `org_id`) y `require_superadmin` **fail-closed**.
- Endpoints: listar / crear (org + primer admin) / suspender / reactivar escuelas.
- Suspensión = bloquea login de la escuela **y** pausa su cron.
- Bootstrap del 1er super admin por comando idempotente.
- **Gestión de super admins desde la consola** (listar / crear / activar-desactivar) — confirmado por el usuario.
- Auditoría mínima de crear / suspender / reactivar.
- Consola frontend `/plataforma` (login + lista/crear/suspender/reactivar escuelas + gestión de super admins).

**Fuera de alcance (no se construye):**
- **Impersonación** de escuelas (confirmado FUERA por el usuario).
- Self-service de signup público / billing / planes / facturación de la plataforma.
- Editar parámetros de negocio de la escuela desde la consola (modo cobro, sucursales, etc.).
- Recuperación de contraseña / 2FA del super admin.
- Portal tutor, chatbot, factura SIN, OpenBCB real (otras fases).

## Reglas de negocio

- **RF-PLT-01** La identidad de plataforma vive en `plataforma_admin` (email único, `password_hash`,
  `nombre`, `activo`). **Sin `org_id`, sin RLS** — como `organizacion`, la única otra tabla sin RLS (C1).
- **RF-PLT-02** El super admin **nunca** ve datos de negocio de ninguna escuela: `require_superadmin`
  **no fija** el GUC `app.current_org` → RLS fail-closed ⇒ 0 filas en cualquier tabla tenant.
- **RF-PLT-03** Crear escuela = crear `organizacion` + su **primer usuario ADMIN** en una sola operación.
  El INSERT del admin se hace **fijando el GUC a la org recién creada** (patrón `seed.py`/`services/pagos.py`),
  **sin BYPASSRLS** sobre `latinosport_app`.
- **RF-PLT-04** Suspender una escuela (`estado=SUSPENDIDA`): (a) **bloquea su login** y (b) **pausa su
  cron** (cuotas/recordatorios y demás tareas que recorren orgs). Reactivar (`estado=ACTIVA`) lo revierte.
- **RF-PLT-05** El login de **escuela** sigue exigiendo `org_id` en el token; **solo** `SUPERADMIN` puede
  venir sin `org_id`. Un token de escuela sin `org_id` sigue siendo 401 (sin cambios de comportamiento).
- **RF-PLT-06** Auditoría mínima: cada crear / suspender / reactivar deja un registro inmutable
  (quién = `plataforma_admin.id`, qué acción, sobre qué `org_id`, cuándo).
- SRS §3 (roles), §4.1 (aislamiento multi-tenant / RLS), §7–§8 (cobranza que el cron pausa).

## Contratos compartidos (definir ANTES de paralelizar)

### Esquema — migración `0012_superadmin` (`down_revision="0011"`)

```
-- tabla nueva: plataforma_admin  (SIN org_id, SIN RLS — como organizacion)
plataforma_admin
  id             uuid  PK  default gen_random_uuid()
  email          text  NOT NULL  UNIQUE        -- email único de login de plataforma
  password_hash  text  NOT NULL                -- bcrypt (security.hash_password)
  nombre         text  NOT NULL
  activo         boolean NOT NULL default true
  created_at / updated_at  (TimestampMixin)
-- SIN ALTER TABLE ... ENABLE ROW LEVEL SECURITY. GRANT SELECT/INSERT/UPDATE a latinosport_app.

-- columna nueva en organizacion (tabla sin RLS):
organizacion.estado  text NOT NULL default 'ACTIVA'
  CHECK (estado IN ('ACTIVA','SUSPENDIDA'))

-- auditoría mínima (tabla nueva). Decisión de producto: tabla ligera SIN RLS
-- (la acción la ejecuta el SUPERADMIN, que no tiene contexto de org → una tabla
--  tenant con RLS quedaría inaccesible para él). Mantener simple:
plataforma_auditoria
  id            uuid PK default gen_random_uuid()
  admin_id      uuid NOT NULL            -- plataforma_admin.id que ejecutó (sin FK cross-RLS obligatoria)
  accion        text NOT NULL CHECK (accion IN ('CREAR_ESCUELA','SUSPENDER_ESCUELA','REACTIVAR_ESCUELA'))
  org_id        uuid NOT NULL            -- escuela afectada (no es scope RLS aquí, solo dato)
  detalle       text NULL                -- opcional (p.ej. nombre/email del admin creado)
  created_at    timestamptz NOT NULL default now()
  -- SIN RLS. GRANT INSERT/SELECT a latinosport_app.
```
> Nota de coordinación: la **autoridad del esquema es la migración**. `models/plataforma_admin.py`
> (y el modelo de auditoría) deben quedar **alineados** con la migración (lección del epic WhatsApp:
> el modelo desalineado con 0011 costó un fix en main). `db-dev` no posee `models/`; el backend define
> `Base.metadata`, `db-dev` migra. En este epic A **posee ambos** (ver reparto), así que mantenerlos
> en sincronía es responsabilidad de la sesión A.

### JWT del super admin (claims)

`create_access_token` hoy **siempre** inyecta `org_id` (`security.py`). Se necesita un token
SUPERADMIN **sin** `org_id`. Contrato del token de plataforma:

```
{ "sub": <plataforma_admin.id>, "role": "SUPERADMIN", "exp": <...> }   # SIN org_id, SIN sucursal_ids
```

Cambio mínimo en `security.py`: permitir emitir token sin `org_id` (p.ej. nueva función
`create_platform_token(admin_id)` o hacer `org_id` opcional y **omitir** la clave si es None).
No romper la firma actual usada por el login de escuela.

Cambio en `tenant.py` (`get_current_user`): aceptar token **sin** `org_id` **solo si**
`role == "SUPERADMIN"`; en cualquier otro caso, falta `org_id` ⇒ 401 (comportamiento actual).
`CurrentUser.org_id` para SUPERADMIN = cadena vacía / `""` (nunca se usa como contexto).

`require_superadmin` (nueva dependencia): valida `role == "SUPERADMIN"` (403 si no) y
**NO** llama a `set_tenant_context` (NO fija el GUC) ⇒ fail-closed sobre tablas tenant.

### Endpoints (router nuevo `api/v1/plataforma.py`, prefix `/plataforma`)

```
POST /api/v1/plataforma/login
  req:  { email: str, password: str }
  res:  { access_token: str, admin: { id, nombre, email } }
  401 si credenciales inválidas o admin inactivo. NO pasa por RLS (lee plataforma_admin directo).

GET /api/v1/plataforma/escuelas                      [require_superadmin]
  res:  [ { id, nombre, pais, moneda, estado, created_at } ]   # lista de orgs con estado

POST /api/v1/plataforma/escuelas                     [require_superadmin]
  req:  { nombre, pais?, moneda?, admin_nombre, admin_email, admin_password }
  res:  { id, nombre, estado, admin: { id, email } }            # 201
  Crea organizacion (estado=ACTIVA) + primer usuario ADMIN fijando el GUC a la org nueva.
  Registra auditoría CREAR_ESCUELA. 409 si admin_email ya existe.

POST /api/v1/plataforma/escuelas/{id}/suspender      [require_superadmin]
  res:  { id, estado: "SUSPENDIDA" }     # idempotente; 404 si no existe. Auditoría SUSPENDER_ESCUELA.

POST /api/v1/plataforma/escuelas/{id}/reactivar      [require_superadmin]
  res:  { id, estado: "ACTIVA" }         # idempotente; 404 si no existe. Auditoría REACTIVAR_ESCUELA.

-- Gestión de super admins (tabla plataforma_admin, sin RLS; no requiere GUC):
GET /api/v1/plataforma/admins                        [require_superadmin]
  res:  [ { id, nombre, email, activo, created_at } ]   # nunca expone password_hash

POST /api/v1/plataforma/admins                       [require_superadmin]
  req:  { nombre, email, password }
  res:  { id, nombre, email, activo }    # 201. 409 si email ya existe.

POST /api/v1/plataforma/admins/{id}/activar          [require_superadmin]
POST /api/v1/plataforma/admins/{id}/desactivar       [require_superadmin]
  res:  { id, activo }                   # idempotente; 404 si no existe.
  Salvaguarda: no permitir desactivar al ÚLTIMO super admin activo (409) ni a uno mismo
  quedando sin super admins activos → siempre debe quedar ≥1 activo.
```
> `organizacion` no tiene RLS ⇒ listar/leer/actualizar estado funciona sin GUC. El INSERT del
> **usuario ADMIN** sí necesita el GUC fijado a la org nueva (la tabla `usuario` tiene RLS).

### Login de escuela rechaza SUSPENDIDA (`auth.py`)

Tras `login_lookup`, antes de emitir token: si la org del usuario está `SUSPENDIDA` ⇒ 403
(mensaje genérico, p.ej. "Escuela suspendida, contacta al administrador"). `organizacion` no
tiene RLS ⇒ se puede consultar `estado` por `org_id` directo (o ampliar `login_lookup` para
devolver `estado`; decisión técnica de la sesión A — preferible consulta directa para no tocar
el contrato de `login_lookup` que pertenece a db).

### Cron pausa orgs suspendidas (`workers/tasks.py`)

Las 3 tasks (`cobranza_diaria`, `generar_sesiones_programadas`, `recordatorios_clase`) hoy listan
`select(Organizacion.id)`. Cambiar a `select(Organizacion.id).where(Organizacion.estado == "ACTIVA")`
(o filtrar en el bucle). Re-correr no debe procesar suspendidas.

### Frontend — consola `/plataforma` (sesión/token SEPARADOS)

- Storage del token de plataforma **distinto** del de escuela (p.ej. `latinosport.platform.token`
  vs el de escuela). NO mezclar el almacenamiento. El `api/client.ts` debe poder mandar el token
  de plataforma en las rutas `/plataforma/*` sin pisar la sesión de escuela.
- Pantallas: **Login de plataforma** + **Escuelas** (tabla con estado; botón Crear; acciones
  Suspender/Reactivar por fila). Gateada a `SUPERADMIN`.
- Tipos en `api/types.ts`: `Escuela`, `CrearEscuelaIn`, `PlatformLoginOut` (append-only con Edit).

## Fases

> Cada fase = uno o pocos commits. El contrato de arriba se define **antes** de paralelizar.

**Fase 0 — Contratos (esta spec).** Esquema 0012, claims JWT, formas de endpoints, storage de token.
Sin código. Habilita el paralelismo de la Fase 1.

**Fase 1 — Esquema + identidad (db + backend, paralelizable tras Fase 0).**
- (db/A) Migración `0012_superadmin`: `plataforma_admin`, `organizacion.estado`, `plataforma_auditoria`.
  GRANTs a `latinosport_app`, **sin** habilitar RLS en las tablas nuevas. **Sin BYPASSRLS.**
- (backend/A) `models/plataforma_admin.py` + modelo de auditoría, alineados a la migración;
  registrarlos en `models/__init__.py` (**Edit, append-only**).
- Contrato compartido: `Base.metadata` (backend define) ↔ migración (db migra) deben coincidir.

**Fase 2 — Auth de plataforma + fail-closed (backend/A).**
- `security.py`: emitir token SUPERADMIN sin `org_id` (sin romper firma actual).
- `tenant.py`: `get_current_user` acepta token sin `org_id` solo si `SUPERADMIN`; nueva
  `require_superadmin` que **NO** fija el GUC.
- `services/plataforma.py`: lógica de login de plataforma (consulta directa a `plataforma_admin`).

**Fase 3 — Endpoints de plataforma (backend/A).**
- Router `api/v1/plataforma.py`: login, listar/crear/suspender/reactivar escuelas (org + admin con
  GUC a la org nueva), y **gestión de super admins** (listar/crear/activar/desactivar, con la
  salvaguarda de ≥1 super admin activo). Registrarlo en `api/v1/__init__.py` (**Edit, append-only**).
- `services/plataforma.py`: crear-escuela (org + admin + auditoría), suspender/reactivar (+ auditoría),
  y CRUD de super admins (reusa `hash_password`).
- Esquemas Pydantic de request/response (incl. los de super admin; nunca serializar `password_hash`).

**Fase 4 — Integración con escuela + cron (backend/A).**
- `auth.py` (login de escuela): rechazar org `SUSPENDIDA` con 403.
- `workers/tasks.py`: las 3 tasks saltan orgs `SUSPENDIDA`.

**Fase 5 — Bootstrap (backend/A).**
- `seed_plataforma.py`: comando `python -m app.seed_plataforma`, **idempotente por email**
  (`INSERT ... ON CONFLICT (email) DO NOTHING` o equivalente), lee `PLATFORM_ADMIN_EMAIL` /
  `PLATFORM_ADMIN_PASSWORD`. **Reemplaza** el pendiente histórico `create-admin` (ver HANDOFF
  "Pendiente: comando create-admin").
- (infra/A) `.env.example`: `PLATFORM_ADMIN_EMAIL`, `PLATFORM_ADMIN_PASSWORD` + nota de prod
  (no commitear secretos; el guard de prod ya falla con credenciales débiles).

**Fase 6 — Consola frontend (frontend/A, paralelizable con Fase 4/5 una vez los contratos están firmes).**
- Login de plataforma + pantalla Escuelas (lista/crear/suspender/reactivar) + pantalla
  **Super Admins** (lista/crear/activar-desactivar, con la salvaguarda de ≥1 activo).
- Token/sesión separados; rutas `/plataforma/*` gateadas a SUPERADMIN.
- Edits append-only en `api/client.ts`, `api/types.ts`, `nav.ts`, `Sidebar.tsx`, `App.tsx`.

## Criterios de aceptación (verificables; con casos borde de dominio)

**RLS / aislamiento (lo crítico):**
- Con token SUPERADMIN, cualquier endpoint que consulte una tabla **tenant** (p.ej. alumnos, cuotas)
  devuelve **0 filas** (GUC no fijado) — fail-closed. Test `@db` que lo prueba.
- `require_superadmin` **no** ejecuta `set_config('app.current_org', ...)` (verificable leyendo
  la dependencia y/o test que confirma 0 filas).
- Crear escuela inserta el usuario ADMIN con **exactamente** el `org_id` de la org recién creada
  (verificable: el admin puede luego loguearse en esa org y ver solo esa org).
- `latinosport_app` **sigue sin** BYPASSRLS (no se altera el rol). El aislamiento por escuela no se debilita.

**Funcionales:**
- `POST /plataforma/login` con credenciales válidas ⇒ token con `role="SUPERADMIN"` y **sin** `org_id`.
  Credenciales inválidas o `activo=false` ⇒ 401.
- `GET /plataforma/escuelas` ⇒ lista todas las orgs con su `estado`. Requiere SUPERADMIN (401 sin token,
  403 si rol de escuela).
- `POST /plataforma/escuelas` ⇒ 201, crea org `ACTIVA` + admin; `admin_email` duplicado ⇒ 409;
  deja registro `CREAR_ESCUELA` en auditoría.
- Suspender ⇒ `estado=SUSPENDIDA` + auditoría; reactivar ⇒ `estado=ACTIVA` + auditoría; ambos
  **idempotentes** (repetir no falla, no duplica efecto); `{id}` inexistente ⇒ 404.
- **Login de escuela con org SUSPENDIDA ⇒ 403** (no emite token). Reactivar ⇒ vuelve a loguear.
- **Cron sobre org SUSPENDIDA no genera cuotas ni recordatorios** (test: org suspendida no aparece
  en el conteo de `cobranza_diaria`). Reactivar ⇒ vuelve a procesarse.
- El login de **escuela** sigue exigiendo `org_id`: token de escuela sin `org_id` ⇒ 401 (sin regresión).
- `python -m app.seed_plataforma` es **idempotente**: correrlo 2× no duplica ni falla; crea el admin
  si no existe a partir de las env.
- **Gestión de super admins:** `GET /plataforma/admins` lista sin `password_hash`; `POST` crea
  (409 si email duplicado); activar/desactivar es idempotente; **desactivar al último super admin
  activo ⇒ 409** (siempre queda ≥1 activo). Requiere SUPERADMIN (401/403).

**Gates (DoD por fase):**
- import-linter en verde (núcleo no importa adaptadores concretos; el módulo de plataforma respeta
  puertos/adaptadores donde aplique).
- `mypy` / `tsc` sin errores nuevos vs baseline.
- `pytest -q` en verde (incluye los tests `@db` de RLS/idempotencia de arriba).
- `ruff` + build frontend en verde si la fase tocó esa área.
- `git diff` revisado por main (no solo el reporte del agente).
- UX confirmada en navegador si la fase tocó UI (login de plataforma + crear/suspender escuela).
- En la **última fase del epic**: esta spec (`docs/specs/super-admin.md`) **se borra en ese commit**
  y se actualiza `docs/HANDOFF.md` (migración 0012, comando `seed_plataforma`, env nuevas).

## Hard constraints

- **NUNCA** dar `BYPASSRLS` al rol `latinosport_app` ni debilitar el RLS fail-closed por escuela.
- `require_superadmin` **NUNCA** fija el GUC `app.current_org`.
- Las tablas nuevas sin RLS (`plataforma_admin`, `plataforma_auditoria`) y `organizacion` son las
  **únicas** sin RLS; **toda tabla tenant nueva** (ninguna en este epic) seguiría usando el patrón
  `NULLIF(current_setting('app.current_org', true), '')::uuid`.
- El login de **escuela** sigue exigiendo `org_id`; **solo** `SUPERADMIN` puede venir sin él.
- **Archivos compartidos = Edit (append-only), nunca Write:** `api/v1/__init__.py`, `models/__init__.py`,
  `core/config.py`, y en frontend `api/client.ts`, `api/types.ts`, `nav.ts`, `Sidebar.tsx`, `App.tsx`.
  Un cambio cruzado en estos ⇒ handoff y parar.
- **No tocar** las áreas de las sesiones paralelas: **B (Entrenadores)** ni **C (Sucursales/Recibo)**.
- **No commitear secretos** (`PLATFORM_ADMIN_PASSWORD` real va al `.env` de prod, no al repo).
- `product-owner` no escribe código; esta spec describe, no implementa.

## Decisiones de producto (resueltas por el usuario, 2026-06-07)

1. **Auditoría** = tabla nueva ligera `plataforma_auditoria` sin RLS. **CONFIRMADO** (default).
2. **Gestión de super admins desde la consola** = **SÍ** (el usuario lo pidió). Se añade CRUD
   (listar/crear/activar/desactivar) en API + consola, con salvaguarda de ≥1 super admin activo.
   El bootstrap por `seed_plataforma` se mantiene para el primer admin.
3. **Mensaje al login de escuela suspendida** = genérico: **"Escuela suspendida, contacta al
   administrador"**. **CONFIRMADO** (default).
