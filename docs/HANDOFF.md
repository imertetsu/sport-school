# HANDOFF — LATINASPORT

> Fuente única de estado del proyecto (junto con `CLAUDE.md`). Se **actualiza al cerrar
> cada epic**. Máx ~150 líneas; poda lo viejo. Esto NO es un changelog — es un snapshot
> de "cómo está el mundo hoy".

_Última actualización: 2026-06-25 — epic **whatsapp-multitenant** integrado en `main` y **VIVO EN PROD**
(migración **0022**): el **gateway de WhatsApp es MULTI-TENANT** — **un número por escuela**, cada ADMIN vincula
SU número por **QR desde Ajustes** (`features/escuela/WhatsAppVinculacion.tsx`). El sidecar Baileys es
**multi-sesión** (`Map<org_id, Session>`, auth-state por org en `SESSIONS_ROOT/${org_id}`, reconexión al
arranque). Tabla nueva `whatsapp_sesion` con **RLS** (metadata best-effort; la verdad LIVE es el sidecar). La org
en curso se resuelve por **`ContextVar`** (`app/core/org_context.py`), seteada **junto al GUC `app.current_org`**
en `core/tenant.py::set_tenant_context` y `workers/tasks.py::_set_org` — **sin** tocar la firma de `WhatsAppPort`
ni los 4 servicios de flujo. API `/mi-escuela/whatsapp/*` (solo ADMIN, el backend es el ÚNICO que habla con el
sidecar). **Normalizador internacional** (`core/phone.py::normalize_bo_phone`, Perú/Alemania, preserva BO 8
dígitos). Webhook entrante `/webhooks/whatsapp-inbound` trae `org_id` y **solo loguea** (no escribe BD).
Migraciones **0001→0022**. **PROD ya está en 0022** (se aplicó la cadena 0015→0022 en el deploy)._

## Stack snapshot

- **Backend:** Python · FastAPI · SQLAlchemy · Pydantic → `backend/`
- **DB:** PostgreSQL + Row-Level Security (RLS) por `org_id`
- **Migraciones:** Alembic + políticas RLS → `migrations/`
- **Jobs:** Celery worker + beat (cron diario) → `backend/app/workers/`
- **Frontend:** React + Vite (SPA mobile-first) → `frontend/`
- **Infra:** Docker / docker-compose / CI → `infra/`
- **Integraciones:** WhatsApp (adaptadores `gateway` Baileys no-oficial multi-tenant VIVO · `meta` Cloud API
  mono-número), OpenBCB (QR sandbox), PDF, SIN (fase 2) — detrás de puertos/adaptadores.

**Roles del sistema (3):** **SUPERADMIN** (plataforma, sin org_id, fail-closed sobre tablas tenant), **ADMIN**
(escuela/org), **ENTRENADOR**. (Tutor = passwordless, fase 2; no es usuario con contraseña.)

## Estado actual — MVP fase 1 completo + fase 2 en curso

**MVP fase 1 + buena parte de fase 2 COMPLETOS** y verificados E2E. Módulos vivos en `main`:
- **Deportistas** (login, lista, perfil/ficha médica por rol, RLS; edición completa datos+tutores+ficha;
  baja/reactivación soft-delete). **Asistencia** (`sesion`/`asistencia`, roster get-or-create, guardar idempotente
  por `(sesion_id,deportista_id)`; el entrenador ve solo categorías de sus disciplinas, con red de seguridad).
- **Cobranza** (cuotas FIJO/ANIVERSARIO, pago efectivo + QR sandbox OpenBCB con webhook idempotente + cola
  `conciliacion_pendiente`, recibo PDF, cron diario, Panel KPIs/morosidad; abonos `PARCIAL`+`credito`, recibo
  no-fiscal `REC-NNNNNN` correlativo por org, WhatsApp Cobro saliente + recordatorio de deudores al entrenador).
- **Programación de clases** (`horario_clase`/`sesion`, crons), **Auto-registro** (`solicitud_registro`,
  aprobar=ADMIN), **Reportes** (solo ADMIN, sin migración), **Egresos** (ADMIN), **Muro de avisos** (feed scoped
  por rol, CRUD ADMIN soft-delete; notifica por WhatsApp opt-in con preview+confirmación, log idempotente
  `aviso_notificacion`).
- **Plataforma / Super Admin** (`plataforma_admin` sin org_id/RLS, consola `/plataforma`, alta de escuelas,
  catálogo GLOBAL de disciplinas), **Entrenadores** (CRUD con cuenta de login), **Sucursales/Categorías** CRUD.
- **Personas y disciplinas:** catálogo GLOBAL (`disciplina_id` FK canónico), CI único por org + recuperar-por-CI,
  entrenador multi-disciplina (`entrenador_disciplina` M:N RLS), `domicilio`/`lugar_nacimiento` opcionales.
- **OCR cédula on-device** (Tesseract.js, la imagen NUNCA sale del navegador — RNF-02): CI nuevo se extrae
  completo; CI antiguo (tinta roja) → manual; parser conservador (baja confianza ⇒ vacío). Solo en el alta.
- **Escuela:** nombre + monograma de color en el TopBar; `/ajustes` (ADMIN) edita nombre + color
  (`features/escuela/AjustesEscuela.tsx`).
- **WhatsApp gateway MULTI-TENANT (VIVO en prod, 0022):** un número por escuela; cada ADMIN lo vincula por QR
  desde Ajustes (`WhatsAppVinculacion.tsx`, API `/mi-escuela/whatsapp/*`). Sidecar Baileys multi-sesión
  (`infra/whatsapp-gateway/`, auth-state por org en `SESSIONS_ROOT/${org_id}`). Org por `ContextVar`
  (`core/org_context.py`) → los 4 flujos salen del número de SU escuela sin tocar el puerto. Entrante con `org_id`
  solo loguea (no escribe BD). Detalle en "Recent decisions".

**Migraciones:** `0001→0022`. Hitos: Egresos=0005, Muro=0006, Horarios=0007, Auto-registro=0008, Abonos=0009,
Recibo=0010, WhatsApp=0011, SuperAdmin=0012, Entrenadores=0013, Deudores=0014, rename deportista=0015, catálogo
disciplinas=0016, CI deportista/tutor=0017, entrenador CI+disciplinas=0018, deportista.domicilio+lugar_nacimiento=0019,
deportista.activo + organizacion.color=0020, aviso_notificacion=0021 (log idempotente WhatsApp del muro),
**whatsapp_sesion=0022** (sesión por escuela, RLS, metadata para la UI de vinculación por QR). **Head = 0022.**
Reportes y Sucursales/Recibo sin migración.

Próximos candidatos: **Pagos v1** (epic `pagos-qr-comprobante`, spec activa, migración **0023**): QR estático por
escuela + comprobante por WhatsApp con OCR + conciliación asistida-manual (OpenBCB fuera). Resto de **Fase 2**
(portal passwordless OTP/WhatsApp, chatbot WhatsApp entrante, factura SIN; credenciales Meta + plantillas
aprobadas). Fase 3: rendimiento, voz, analítica.
**Deuda menor:** `JUSTIFICADO` en asistencia; **Horarios aún muestra todas las clases de la org al entrenador**
(deportistas + asistencia sí se acotan por disciplina con red de seguridad: sin disciplinas asignadas ve por
sucursal, no vacío; disciplina NULL es visible); el gating fino de ficha médica por sucursal es no-op hoy (el JWT
trae TODAS las sucursales — limitar el token es épica futura); cosmético categoría duplicada.

## Active flags / config

### Cómo correr el slice en local (verificado en esta máquina)
Los puertos por defecto (5432/8000/5173) están **ocupados por otros proyectos**, así que se usan overrides locales.
El compose acepta `DB_PORT`/`REDIS_PORT`/`API_PORT`/`WEB_PORT`.
```
# 1) BD + redis (puerto host db = 5434 aquí)
DB_PORT=5434 docker compose -f infra/docker-compose.yml up -d --wait db redis
# 2) migraciones (rol OWNER):
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/latinosport \
  backend/.venv/Scripts/alembic upgrade head
# 3a) seed de datos de negocio (corre como OWNER, bypassa RLS):
cd backend && DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/latinosport \
  JWT_SECRET=... CORS_ORIGINS=http://localhost:5180 .venv/Scripts/python -m app.seed
# 3b) seed del PRIMER super admin:
cd backend && DATABASE_URL=...postgres...@localhost:5434/latinosport JWT_SECRET=... \
  PLATFORM_ADMIN_EMAIL=super@latinosport.bo PLATFORM_ADMIN_PASSWORD=<pass> \
  .venv/Scripts/python -m app.seed_plataforma
# 4) API (rol latinosport_app → RLS activa) en 8010 (OPENBCB_SANDBOX habilita "Simular pago"):
cd backend && DATABASE_URL=postgresql+psycopg://latinosport_app:devpass@localhost:5434/latinosport \
  JWT_SECRET=<32+ chars> CORS_ORIGINS=http://localhost:5180,http://127.0.0.1:5180 \
  OPENBCB_SANDBOX=true REDIS_URL=redis://localhost:6379/0 PUBLIC_BASE_URL=http://localhost:8010 \
  .venv/Scripts/python -m uvicorn app.main:app --port 8010
# 5) Frontend en 5180:
cd frontend && VITE_API_URL=http://localhost:8010 npm run dev -- --port 5180 --strictPort
```
**Credenciales de seed:** `admin@latinosport.bo / admin1234` (ADMIN) · `coach@latinosport.bo / coach1234`
(ENTRENADOR). Org: `Academia Andina` (BO/BOB), 2 sucursales, 8 deportistas; coach con Fútbol asignado y
deportistas repartidos (Fútbol/Voleibol/NULL). Super admin: el de `PLATFORM_ADMIN_EMAIL`/`_PASSWORD` (consola
`/plataforma`, gestiona el catálogo GLOBAL de disciplinas).

### Flags de negocio / env
- `ORGANIZACION.modo_cobro_default`: `FIJO` | `ANIVERSARIO`; `dia_corte_fijo`, `prorratea_primer_periodo` (bool,
  **default sin decidir**, SRS §10.4); recordatorio de pago `N días antes`; toggles de notificación por org (aún sin implementar).
- Env reales: `APP_NAME, DATABASE_URL, MIGRATION_DATABASE_URL, JWT_SECRET, JWT_EXPIRE_MINUTES, CORS_ORIGINS,
  REDIS_URL, VITE_API_URL` (ver `.env.example`). **Super Admin / Recibo:** `PLATFORM_ADMIN_EMAIL`,
  `PLATFORM_ADMIN_PASSWORD`, `PUBLIC_BASE_URL`. **WhatsApp:** `WHATSAPP_PROVIDER` (`noop|mock|meta|gateway`, default
  noop). **gateway (no-oficial, lo VIVO):** `WHATSAPP_GATEWAY_URL`, `WHATSAPP_GATEWAY_TOKEN` (== `GATEWAY_TOKEN` del
  sidecar; secreto) + del sidecar `GATEWAY_PORT`, `SESSIONS_ROOT` (auth-state multi-sesión por org, en volumen),
  `INBOUND_CALLBACK_URL`. **meta (oficial, mono-número):** `WHATSAPP_PHONE_NUMBER_ID/_ACCESS_TOKEN/_WABA_ID/
  _VERIFY_TOKEN/_APP_SECRET/_GRAPH_VERSION` (v21.0), `RECORDATORIO_QR_DIAS_ANTES` (3). Sin las vars del provider
  elegido ⇒ cae al **mock**. Futuras: `OPENBCB_*`. **Nunca commitear secretos.**

## In-flight work

**Epic `pagos-qr-comprobante` ABIERTO** — spec activa en `docs/specs/pagos-qr-comprobante.md` (Pagos v1: QR
estático por escuela + comprobante por WhatsApp con OCR e identificación automática del tutor; conciliación
asistida-manual, **OpenBCB fuera**; migración **0023**). Aún sin código.

**whatsapp-multitenant CERRADO** (0022): integrado en `main` y **desplegado en prod, funcionando**; su spec
efímera `docs/specs/whatsapp-multitenant.md` **se borra en el commit que cierra el epic** (SSS, pilar 1).

**Pendientes operativos:**
- **Epics multi-sesión se integran en rama `staging`** (no `main` directo) → validar → `staging`→`main`.
- **Prod** (servidor `177.222.39.139`, `/opt/latinosport`) **ya está en migración 0022** (se aplicó la cadena
  **0015→0022** en el deploy del gateway multi-tenant). Deploy **gateado** (`DEPLOY_ENABLED` off), manual:
  `pg_dump` → `git pull` → `bash infra/deploy.sh`. (La detección de CI duplicados pre-0017/0018 ya se corrió como
  parte de ese chain.) El próximo deploy aplicará **0023** (epic Pagos v1) — un solo `pg_dump` de respaldo antes.
- **Job de deploy (CI) roto:** la sesión SSH se cae a mitad del build-on-server (`Broken pipe`, exit 255) —
  probable OOM al buildear web+api+worker en paralelo o timeout SSH. Fix pendiente en `infra/deploy.sh` + workflow
  (builds secuenciales / swap / SSH keepalive). NO es código de la app.
- **WhatsApp envío REAL:** el **gateway no-oficial Baileys** (`WHATSAPP_PROVIDER=gateway`) envía de verdad por
  número propio por escuela (vinculado por QR), sin esperar a Meta. El adaptador **Meta** (`provider=meta`) sigue
  mono-número y necesita plantillas aprobadas + credenciales; hoy mock-first si no hay credenciales.

Remoto `imertetsu/sport-school` (push vía `http.sslBackend=schannel` por el proxy TLS).

## Recent decisions

- **2026-06-25 WhatsApp MULTI-TENANT (epic cerrado, migración 0022, VIVO en prod).** Un **número por escuela**:
  cada ADMIN vincula el suyo por **QR desde Ajustes** (autoservicio; el browser nunca ve token/URL del sidecar —
  el QR viaja browser←backend←sidecar). El sidecar Baileys pasó a **multi-sesión** (`Map<org_id,Session>`,
  auth-state por org en `SESSIONS_ROOT/${org_id}` en volumen, reconexión al arranque; la vieja ruta global `/send`
  se eliminó). La multi-tenencia se resolvió por **`ContextVar`** (`core/org_context.py`), seteado en los MISMOS
  dos puntos que el GUC `app.current_org` (`tenant.py`, `workers/tasks.py`) → **NO** se tocó la firma de
  `WhatsAppPort` ni los 4 servicios de flujo. Sin contexto de org ⇒ `ok=False` **sin** pegar al sidecar
  (fail-closed, invariante anti-fuga entre orgs consecutivas en un mismo cron). Tabla `whatsapp_sesion` con RLS
  (metadata; verdad LIVE = sidecar). Normalizador **internacional** (`normalize_bo_phone`, Perú/Alemania, preserva
  BO 8 dígitos; firma compat 1-arg). Entrante con `org_id` = **recibir + loguear** (chatbot/persistencia = futuro).
- **2026-06-09 Avisos por WhatsApp (epic, migración 0021).** Al crear un Aviso, el ADMIN puede notificar por
  WhatsApp a **Entrenadores y/o Tutores** (opt-in con checkboxes desmarcados) según el **alcance** del aviso
  (ORG/SUCURSAL/CATEGORIA; en CATEGORIA entrenadores por `entrenador_disciplina`). **Preview con conteo +
  confirmación** antes de enviar. Task Celery a demanda, **idempotente** (`aviso_notificacion`
  UNIQUE(aviso_id,tipo_destinatario,destinatario_id); sin teléfono → SIN_TELEFONO). Plantilla `nuevo_aviso`.
  **Editar un aviso NO notifica** (solo el alta).
- **2026-06-09 Escuela + bajas (epic, migración 0020).** Borrado = **dar de baja** (soft-delete reversible; nunca
  borrado físico de deportistas/entrenadores). Editar escuela = **solo nombre + color** del monograma (sin
  almacenar imágenes, RNF-02). Editar deportista = **completo** (datos+tutores+ficha); reconciliar tutores respeta
  el invariante de menores **server-side** (lista vacía / quitar al tutor del consentimiento → **422**). Login
  devuelve `org {id,nombre,color}` → TopBar pinta nombre + monograma sin llamada extra.
- **2026-06-09 Frontend/landing (vigente).** Sidebar = **drawer off-canvas** en ≤768px (AppShell). Cuotas sin
  categoría/sucursal (disciplina NULL) → tipos del front a `…|null` + `?.` (evita crash de pantalla). **Landing**
  estática en la RAÍZ vía nginx (`location = / → landing.html`; resto → SPA); en dev (Vite) `/` es la SPA.
- **2026-06-07 Personas y Disciplinas + Fase 2 consolidada (vía `staging`).** Catálogo de disciplinas **GLOBAL**
  (SUPERADMIN); orgs referencian por FK `disciplina_id` (canónico). **CI único por org** (índices parciales; dup →
  409 + recuperar-por-CI). **OCR cédula on-device** (no sale del navegador). Entrenador multi-disciplina; la
  disciplina acota deportistas+asistencia (server-side, helper `disciplina_ids_de_usuario`, NO en el JWT). Campos
  opcionales `domicilio`/`lugar_nacimiento` (0019); red de seguridad de scoping del entrenador. **Super Admin**
  (`plataforma_admin` sin org_id/RLS). **Recibo** no-fiscal `REC-NNNNNN` atómico, enlace HMAC stateless.
  **Abonos** (QR siempre por el total; parciales solo efectivo; sobrepago→crédito). **Recordatorio de deudores**
  (idempotente). **Lección:** worktree propio por sesión al paralelizar.
- **2026-06-06 Deploy + hardening (vigente).** Rename interno cantera→latinosport (BD `latinosport`, rol
  `latinosport_app` NO superusuario; recrear BD requiere `docker compose down -v`). Deploy en `177.222.39.139`
  (IP:puerto, sin dominio/HTTPS aún). CI job `deploy` (push a `main`→SSH→`infra/deploy.sh`, build-on-server,
  **gateado por `vars.DEPLOY_ENABLED`**). **Guard de prod** en `config.py` (`APP_ENV=production` ⇒ falla con
  JWT_SECRET débil/<32, `devpass` o `OPENBCB_SANDBOX=true`).
- **2026-06-05 Fundacionales.** Stack: **FastAPI + React (Vite) + PostgreSQL/RLS + Alembic + Celery**. Producto
  **en español**; diseño UI en `docs/design/design-system.md`; marca **LatinoSport** (acento azul oklch), por
  **SnapCoding**. Multi-tenancy = **RLS por `org_id`** (no negociable, SRS §4.1 / RNF-01). Cobranza/factura/
  notificación = **puertos + adaptadores** (el núcleo no importa lo concreto). Idempotencia de webhooks por
  `transaccion_id` único (RNF-05).

## Known gotchas (los bugs caros e invisibles de este dominio)

- **RLS + pooling:** el contexto de tenant (`SET LOCAL app.current_org`) se fija **por transacción/petición**; en
  conexiones reutilizadas (pool) un contexto sin resetear **fuga datos entre tenants**. Fail-closed si no hay contexto.
- **El rol de BD de la app debe ser NO-superusuario** (un superusuario **ignora RLS**). El **super admin de
  PLATAFORMA es ortogonal a RLS**: NO fija el GUC ⇒ fail-closed sobre tablas tenant; su tabla `plataforma_admin`
  vive **fuera** del modelo tenant (sin org_id, sin policy).
- **RLS fail-closed con GUC vacío:** tras `SET LOCAL`+commit el GUC revierte a **`''` (cadena vacía), NO a NULL** →
  toda policy debe usar `NULLIF(current_setting('app.current_org', true), '')::uuid`. **Cualquier policy nueva debe
  seguir este patrón.**
- **`organizacion` NO tiene RLS** (única tabla tenant sin org_id/policy, como `disciplina`/`plataforma_admin`): los
  endpoints `/mi-escuela` scopean SIEMPRE a `user.org_id` del token e **IGNORAN cualquier id del cliente** — el
  **código es el único guardián** (cubierto por test: PUT de org A con id de B en el body no afecta a B).
- **`deportista.activo` usa `server_default=func.true()`** (patrón de `aviso.activo`, NO el de `usuario.activo` que
  no lo tiene): la migración 0020 conserva el DEFAULT físico porque el seed y los tests insertan deportistas con SQL
  crudo (sin la columna); sin server_default violarían el NOT NULL.
- **Cuotas:** nada de aritmética `+30 días`; usar "mismo día del mes" y *clamp* a último día del mes (SRS §7.2).
- **Pagos:** webhook duplicado ⇒ sin doble pago ni doble comprobante; monto que no cuadra ⇒ **cola de
  conciliación**, nunca se descarta (RNF-06); multi-cuota ⇒ FIFO sobre vencidas más antiguas.
- **Menores:** no se guarda deportista sin ≥1 tutor + `CONSENTIMIENTO`; al editar tutores, el server bloquea (422)
  dejar lista vacía o quitar al tutor atado al `Consentimiento` (es un FK a un tutor concreto); datos médicos
  cifrados en reposo; auditar pagos manuales / cambios de monto / comprobantes (RNF-02/03).
- **DELETE de sucursal/categoría:** protegido en API (409 si está en uso) aunque la BD tenga FKs CASCADE.
- **Índices únicos de CI (deportista/tutor/entrenador) son PARCIALES y viven SOLO en migraciones**
  (`(org_id, ci) WHERE ci IS NOT NULL`), NO como `Index` declarativo → un `alembic --autogenerate` sugerirá
  **dropearlos**: **ignorar**, la migración es la verdad.
- **`disciplina_id` (FK al catálogo global) es lo canónico.** Los textos legacy `deportista.disciplina` y
  `entrenador.disciplinas` (JSONB) **se conservan** (no se dropean), solo respaldo histórico — no los uses como verdad.

### Gotchas de entorno / código
- **Worktree propio por sesión** al paralelizar: una rama NO aísla el árbol; compartir el dir principal pisa.
- **Puertos ocupados en esta máquina:** 5432/5433 (otras DB), 8000 (Django ajeno), 5173 (otro front). Usar los
  overrides (5434/8010/5180).
- **`JWT_SECRET` corto** avisa (PyJWT exige ≥32 bytes para HS256). En prod usar uno largo.
- **Seed corre como OWNER** (postgres bypassa RLS) a propósito; la **app** corre como `latinosport_app` (RLS activa).
- **npm install** se cuelga con el proxy TLS del equipo (`UNABLE_TO_VERIFY_LEAF_SIGNATURE`); workaround dev:
  `npm_config_strict_ssl=false`. CI/Docker deben usar una CA/registry confiable.

## Where to look for things

| Necesitas… | Mira en… |
|------------|----------|
| Requisitos / reglas de negocio | `LATINASPORT_SRS_v2.md` |
| Diseño UI (pantallas, tokens, datos ejemplo) | `docs/design/design-system.md` |
| Metodología, roster, DoD, comandos | `CLAUDE.md` |
| Lógica de dominio, API, adaptadores, workers | `backend/app/` |
| Esquema físico, RLS, migraciones | `migrations/` + `alembic.ini` |
| UI admin/entrenador, consola super admin (`/plataforma`), ajustes escuela (`/ajustes`) | `frontend/src/` |
| Docker, CI, env, despliegue worker | `infra/` |
| Spec del epic activo | `docs/specs/pagos-qr-comprobante.md` (efímera; epic Pagos v1 en vuelo) |
