# HANDOFF — LATINASPORT

> Fuente única de estado del proyecto (junto con `CLAUDE.md`). Se **actualiza al cerrar
> cada epic**. Máx ~150 líneas; poda lo viejo. Esto NO es un changelog — es un snapshot
> de "cómo está el mundo hoy".

_Última actualización: 2026-06-07 — epic **personas-y-disciplinas** (S1–S4 + componente OCR) integrado en `main` (migraciones **0015→0018**): rename alumno→deportista, catálogo GLOBAL de disciplinas (superadmin), CI único por org + recuperar-por-CI (deportista/tutor/entrenador), entrenador multi-disciplina, y escaneo OCR on-device de cédula. Migraciones **0001→0018**. · **Fixes UX entrenador** (`6d5b9c2`, sin migración): el ENTRENADOR ahora ve **solo sus disciplinas asignadas** (deportistas + asistencia), Horarios muestra la sucursal de cada clase y los nombres ya no se cortan. · **OCR cédula a 2 fotos + 2 formatos (MRZ)** (sin migración, solo frontend), **validado con cédulas reales**: CI nuevo se lee (MRZ); CI antiguo NO es OCR-able on-device → manual; parser conservador (no mete basura). · **Campos opcionales deportista** (migración **0019**): `domicilio` + `lugar_nacimiento` (grupo sanguíneo ya en ficha médica) + **red de seguridad** en el scoping del entrenador (sin disciplinas → ve por sucursal; NULL visible). Migraciones **0001→0019**._

## Stack snapshot

- **Backend:** Python · FastAPI · SQLAlchemy · Pydantic → `backend/`
- **DB:** PostgreSQL + Row-Level Security (RLS) por `org_id`
- **Migraciones:** Alembic + políticas RLS → `migrations/`
- **Jobs:** Celery worker + beat (cron diario) → `backend/app/workers/`
- **Frontend:** React + Vite (SPA mobile-first) → `frontend/`
- **Infra:** Docker / docker-compose / CI → `infra/`
- **Integraciones:** OpenBCB (QR), WhatsApp, PDF, SIN (fase 2) — detrás de puertos/adaptadores.

**Roles del sistema (3):** **SUPERADMIN** (plataforma, sin org_id, fail-closed sobre tablas
tenant), **ADMIN** (escuela/org), **ENTRENADOR**. (Tutor = passwordless, fase 2; no es usuario con contraseña.)

## Estado actual — MVP fase 1 + fase 2 en curso

**MVP fase 1 COMPLETO** y verificado E2E: **Deportistas** (login, lista, perfil con ficha médica por rol, RLS),
**Cobranza** (cuotas FIJO/ANIVERSARIO, pago efectivo + QR sandbox OpenBCB con webhook idempotente + cola
`conciliacion_pendiente`, recibo PDF, cron diario, Panel KPIs/morosidad), **Asistencia** (`sesion`/`asistencia`,
roster get-or-create, guardar idempotente por `(sesion_id,deportista_id)`; entrenador ve solo las categorías de sus disciplinas asignadas, ver fixes 2026-06-07),
**Reportes** (solo ADMIN, sin migración: ingresos/mes + % asistencia), **Egresos** (0005, ADMIN), **Muro de
avisos** (0006, feed scoped por rol, CRUD ADMIN con soft-delete).

**Fase 2 (consolidada en `main`):** Programación de clases (0007, `horario_clase`/`sesion`, crons),
Auto-registro de deportista en sistema (0008, `solicitud_registro`, aprobar=ADMIN), Abonos/pagos parciales
(0009, `PARCIAL` + `credito`; parciales solo efectivo, QR siempre por el total), Recibo no-fiscal (0010,
`REC-NNNNNN` correlativo por org), WhatsApp Cobro saliente (0011, `recordatorio_pago` + `WhatsAppPort`),
Super Admin/consola de plataforma (0012, `plataforma_admin` sin org_id/RLS, `/plataforma`), Gestión de
Entrenadores con cuenta de login (0013), Sucursales/Categorías CRUD + Recibo por WhatsApp (sin migración,
enlace HMAC stateless), Recordatorio de deudores al entrenador (0014, `entrenador_sucursal` M:N + digest WhatsApp).

**Personas y Disciplinas (epic más reciente, migraciones 0015→0018):**
- **S1 — rename alumno→deportista** (0015): renombrado data-preserving in-place (tabla/columnas/relaciones);
  **RLS preservada**. Campos texto legacy se conservan por simetría con el rename.
- **S2 — catálogo GLOBAL de disciplinas** (0016, gestionado por SUPERADMIN): tabla `disciplina`
  **SIN org_id y SIN RLS** (como `organizacion`/`plataforma_admin`); `GET /catalogo/disciplinas` (lectura) y
  CRUD en `/plataforma`. Se añaden `categoria.disciplina_id` y `deportista.disciplina_id` + data-migration
  texto→ref. **`disciplina_id` (FK al catálogo) es lo canónico**; `deportista.disciplina` (texto) se conserva.
- **Componente OCR on-device** (Tesseract.js, `DocumentScanner` + parser `parseCedula`/`mrz.ts`, spike `/dev/ocr`):
  **la imagen NO se sube ni se guarda** (privacidad RNF-02). **2 fotos (anverso+reverso) + 2 formatos**.
  **VALIDADO con cédulas reales (2026-06-07):** el **CI nuevo SÍ** se lee (MRZ TD1 con check digits → apellidos,
  nombres, CI, fecha). El **CI antiguo NO es OCR-able on-device** (tinta roja + fondo de microimpresión laminado;
  Tesseract no lee CI/nombre/fecha ni con preprocesado) → **se ingresa a mano**. Parser **conservador**: ante baja
  confianza deja el campo VACÍO en vez de rellenar basura (lista negra de palabras institucionales, fecha plausible
  1900..hoy, CI = dígitos contiguos 6–8, NUNCA el serial "NNNNNNN NN-XX"). Solo se guarda el **número** de CI
  (sin extensión). El escáner avisa "ingrésalos a mano" si no extrajo nada.
- **S3 — CI único por org + recuperar-por-CI** (0017, deportista y tutor): índices únicos **PARCIALES**
  `(org_id, ci) WHERE ci IS NOT NULL`; `GET /deportistas|tutores/por-ci/{ci}` (200|404); **409** al dar de alta
  con CI duplicado; tutor recuperar→actualizar teléfono. `NuevoDeportista` cablea OCR + recuperar + select de
  disciplina (`disciplina_id` FK).
- **S4 — entrenador CI + OCR + multi-disciplina** (0018, renumerada desde 0017 al integrar en staging):
  `entrenador.ci` (único parcial por org) + tabla **`entrenador_disciplina`** M:N con **RLS completa**
  (FORCE + policy `NULLIF`) + data-migration JSONB legacy→catálogo. `NuevoEntrenador` con OCR + CI +
  multi-select de disciplinas. `entrenador.disciplinas` (JSONB texto legacy) se conserva.

**Migraciones:** `0001→0018` (Egresos=0005, Muro=0006, Horarios=0007, Auto-registro=0008, Abonos=0009,
Recibo=0010, WhatsApp=0011, SuperAdmin=0012, Entrenadores=0013, Deudores=0014, **rename deportista=0015**,
**catálogo disciplinas=0016**, **CI deportista/tutor=0017**, **entrenador CI+disciplinas=0018**,
**deportista.domicilio+lugar_nacimiento=0019**; Reportes y Sucursales/Recibo sin migración).

Próximos candidatos: resto de **Fase 2** (portal passwordless OTP/WhatsApp, chatbot WhatsApp entrante, factura
SIN, OpenBCB real; credenciales Meta reales + plantillas aprobadas). Fase 3: rendimiento, voz, analítica.
**Deuda menor:** `JUSTIFICADO` en asistencia; **Horarios aún muestra todas las clases de la org al entrenador**
(deportistas + asistencia se acotan por disciplina CON **red de seguridad**: entrenador sin disciplinas asignadas
ve por sucursal, no vacío, y deportista/categoría con disciplina NULL es visible); el gating fino de ficha médica
por sucursal es no-op hoy (el JWT del entrenador trae TODAS las sucursales — limitar el token es épica futura);
cosmético categoría duplicada ("Sub-10 Principiante Principiante").

## Active flags / config

### Cómo correr el slice en local (verificado en esta máquina)
Los puertos por defecto (5432/8000/5173) están **ocupados por otros proyectos** del usuario, así que se usan
overrides locales. El compose acepta `DB_PORT`/`REDIS_PORT`/`API_PORT`/`WEB_PORT`.
```
# 1) BD + redis (puerto host db = 5434 aquí)
DB_PORT=5434 docker compose -f infra/docker-compose.yml up -d --wait db redis
# 2) migraciones (rol OWNER):
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/latinosport \
  backend/.venv/Scripts/alembic upgrade head
# 3a) seed de datos de negocio (corre como OWNER, bypassa RLS):
cd backend && DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/latinosport \
  JWT_SECRET=... CORS_ORIGINS=http://localhost:5180 .venv/Scripts/python -m app.seed
# 3b) seed del PRIMER super admin (REEMPLAZA el viejo pendiente create-admin):
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
(ENTRENADOR). Org: `Academia Andina` (BO/BOB), 2 sucursales, 8 deportistas. Super admin gestiona el catálogo
GLOBAL de disciplinas en `/plataforma`. Super admin: el que pongas en
`PLATFORM_ADMIN_EMAIL`/`PLATFORM_ADMIN_PASSWORD` al correr `app.seed_plataforma` (consola en `/plataforma`).

### Flags de negocio (configurables por organización — aún sin implementar; SRS §4.2/§7)
- `ORGANIZACION.modo_cobro_default`: `FIJO` | `ANIVERSARIO`
- `ORGANIZACION.dia_corte_fijo`, `prorratea_primer_periodo` (bool) — **default sin decidir** (SRS §10.4)
- Recordatorio de pago: `N días antes`; toggles de notificación por organización (RNF-07)
- Env reales hoy: `APP_NAME, DATABASE_URL, MIGRATION_DATABASE_URL, JWT_SECRET, JWT_EXPIRE_MINUTES,
  CORS_ORIGINS, REDIS_URL, VITE_API_URL` (ver `.env.example`).
  **Super Admin / Recibo WhatsApp (nuevas):** `PLATFORM_ADMIN_EMAIL`, `PLATFORM_ADMIN_PASSWORD` (bootstrap
  del primer super admin vía `python -m app.seed_plataforma`), `PUBLIC_BASE_URL` (base del enlace público del recibo).
  **WhatsApp (epic 11):** `WHATSAPP_PROVIDER` (noop|mock|meta, default noop), `WHATSAPP_PHONE_NUMBER_ID`,
  `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_WABA_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`,
  `WHATSAPP_GRAPH_VERSION` (v21.0), `RECORDATORIO_QR_DIAS_ANTES` (3). Sin credenciales ⇒ cae al **mock**.
  Para enviar de verdad: `WHATSAPP_PROVIDER=meta` + credenciales Meta + plantillas aprobadas. Futuras: `OPENBCB_*`.
  **Nunca commitear secretos.**

## In-flight work

Nada en vuelo en código. El epic **personas-y-disciplinas** (S1–S4 + OCR) está **integrado en `main`**; sus specs
efímeras (`personas-y-disciplinas.md` roadmap, `disciplinas.md` S2, `entrenador-ci.md` S4) se borraron en este cierre.

**Pendientes operativos:**
- **Epics multi-sesión ahora se integran en rama `staging`** (no `main` directo) → validar → `staging`→`main`
  (decisión 2026-06-07). 0018 fue **renumerada desde 0017** al linealizar en staging.
- **Prod** (servidor `177.222.39.139`, `/opt/latinosport`) está ~**0014**: **pendiente desplegar** el chain
  **0015→0018**. Deploy **gateado** (`DEPLOY_ENABLED` off), manual: `pg_dump` → `git pull` → `bash infra/deploy.sh`.
  **Antes de aplicar 0017/0018 en prod: correr la detección de CI duplicados** en deportista/tutor/entrenador
  (si hay dup no-null, el índice único parcial falla al crearse).
- **OCR (validado 2026-06-07):** CI nuevo se lee por MRZ; CI antiguo NO es OCR-able on-device → **manual** (parser
  conservador, no mete basura). Confirmado E2E con cédulas reales (`9396529` rojo y nombre del antiguo no los lee
  Tesseract ni con preprocesado de canal rojo/binarización). El sufijo "08-L3" es **serial de tarjeta, NO el CI**
  (el CI real es el "No. #######"). No queda QA bloqueante de OCR. (Mejora futura opcional si el antiguo fuera
  mayoría: OCR en la nube con consentimiento — descartado hoy por RNF-02.)

Remoto `imertetsu/sport-school` (push vía `http.sslBackend=schannel` por el proxy TLS). Al abrir el próximo epic,
`product-owner` crea `docs/specs/<epic>.md`.

## Recent decisions

- **2026-06-07 Campos opcionales deportista + red de seguridad de scoping** (migración **0019**). Se añaden
  `domicilio` y `lugar_nacimiento` (columnas TEXT nullable; grupo sanguíneo ya vivía en `ficha_medica.tipo_sangre`);
  OCR best-effort conservador (reverso; casi siempre manual). **Red de seguridad** en la visibilidad del ENTRENADOR
  (refina la decisión estricta previa): si NO tiene disciplinas asignadas ve por **sucursal** (no vacío), y un
  deportista/categoría con `disciplina_id` **NULL** es **visible** (el filtro por disciplina solo aplica cuando el
  entrenador tiene disciplinas Y el registro tiene disciplina). El seed asigna Fútbol al coach y reparte disciplinas
  a los deportistas (Fútbol/Voleibol/NULL) para ejercitarlo. Verificado E2E con seed (271 passed).
- **2026-06-07 OCR cédula: 2 fotos + 2 formatos** (epic `ocr-cedula`, sin migración, solo `frontend/`). Motor
  **on-device** (Tesseract.js; la imagen nunca sale del navegador, RNF-02 — descartado cloud OCR). `DocumentScanner`
  captura **anverso + reverso** con preprocesado (grises/contraste/autorrotación OSD/banda MRZ). Parser por formato:
  **CI nuevo** → MRZ TD1 con **check digits** (si no validan, cae al anverso, no propaga basura); **CI antiguo** →
  nombre del reverso (orden nombres→apellidos) + CI del anverso (descarta el folio "No."). Solo 5 campos
  (ap_paterno/materno, nombres, ci, fecha_nac); la **extensión/complemento va DENTRO del string `ci`** (sin campo
  nuevo, sin tocar dedup). QA real-photo queda pendiente en `/dev/ocr`.
- **2026-06-07 Fixes UX + visibilidad del entrenador por DISCIPLINA** (`6d5b9c2`, sin migración). El ENTRENADOR
  queda acotado a las disciplinas de **`entrenador_disciplina`**: lista y detalle de deportistas (detalle → **404
  no-revelador** si es de otra disciplina) y categorías/roster/sesiones de asistencia (categoría ajena → **403**).
  Resuelto **server-side por request** (helper `disciplina_ids_de_usuario`; NO en el JWT, que sigue dando todas las
  sucursales); **aditivo** al filtro de sucursal existente. **Sin disciplinas asignadas ⇒ no ve nada** (el admin
  debe asignárselas). Esto **amplía** la decisión de epic-15 (que solo tocaba el recordatorio por sucursal): ahora la
  **disciplina** sí acota la vista de deportistas+asistencia (Horarios sigue mostrando todo). UX: nombre del
  deportista legible en Asistencia (envuelve) y Horarios muestra la sucursal de cada clase + chip de entrenador sin
  desbordar. **"Voleibol" es grafía correcta (RAE)**; lo que se ve en pantalla es dato de la escuela, no texto del código.
- **2026-06-07 Personas y Disciplinas (S1–S4 + OCR).** Decisiones de producto clave (detalle técnico en
  "Estado actual"): (1) catálogo de disciplinas es **GLOBAL** (gestionado por SUPERADMIN, no por tenant) — las
  orgs lo leen y referencian por FK `disciplina_id` (canónico). (2) **CI único por org** (no global) vía índices
  parciales que permiten varios sin CI; alta con CI dup → **409** + flujo "recuperar-por-CI". (3) **OCR de cédula
  on-device**: la imagen no sale del navegador (RNF-02 menores); el parser solo prerellena campos editables.
  (4) Entrenador multi-disciplina. **Integrado vía `staging`** → 0018 renumerada desde 0017. **Pendiente QA:**
  validar el parser con un CI boliviano real.
- **2026-06-07 Recordatorio de deudores al entrenador.** Deudor = deportista con ≥1 `cuota.estado='VENCIDO'`
  (no reimplementa la lógica de vencimiento; la mantiene `cobranza_diaria`). WhatsApp en **2 mensajes** (plantilla
  resumen + `send_text` con detalle). Idempotencia `recordatorio_deudores UNIQUE(entrenador,sucursal,periodo)`:
  cron usa semana ISO, botón usa `MANUAL-<ts>` (no colisionan; el botón permite reenvío). **Alcance acotado**
  (decisión de producto): la asignación SOLO alimenta el recordatorio; no cambia la vista del entrenador.
- **2026-06-07 Otras decisiones recientes (consolidadas en código).** Bugfix UI rol real (`viewRole = user.role`,
  sin toggle de prototipo; `RoleRoute` gatea sobre el rol real). **Tres epics en paralelo** (Super Admin /
  Entrenadores / Sucursales-Recibo) en worktrees+ramas+stacks docker aislados, integrados A→B→C linealizando la
  cadena Alembic → **lección: worktree propio por sesión** (una rama NO aísla el árbol). **Super Admin**:
  `plataforma_admin` sin org_id/RLS, fail-closed sobre tablas tenant, alta de escuela sin BYPASSRLS, bootstrap
  `seed_plataforma` (reemplaza el viejo `create-admin`). **Entrenadores**: CRUD ADMIN crea cuenta de login en una
  txn; selector real de entrenador en Horarios. **Sucursales/Recibo**: DELETE protegido (409), recibo por enlace
  HMAC stateless. **WhatsApp Cobro**: mock-first, solo saliente, idempotente, NO toca la conciliación. **Recibo**
  no-fiscal `REC-NNNNNN` atómico. **Abonos**: QR siempre por el total (parciales solo efectivo); sobrepago→crédito.
- **2026-06-06 Deploy + hardening (vigente).** Rename interno cantera→latinosport (BD `latinosport`, rol
  `latinosport_app` NO superusuario; recrear BD requiere `docker compose down -v`). Deploy en `177.222.39.139`
  (`/opt/latinosport`, IP:puerto, sin dominio/HTTPS aún). CI job `deploy` (push a `main`→SSH→`infra/deploy.sh`,
  build-on-server, **gateado por `vars.DEPLOY_ENABLED`**). Imagen autocontenida + **guard de prod** en `config.py`
  (`APP_ENV=production` ⇒ falla con JWT_SECRET débil/<32, `devpass` o `OPENBCB_SANDBOX=true`).
- **2026-06-05** Stack: **FastAPI + React (Vite) + PostgreSQL/RLS + Alembic + Celery** (elección del usuario).
  Producto **en español**. Diseño UI capturado en `docs/design/design-system.md`. Marca **LatinoSport** (acento
  azul oklch), desarrolla **SnapCoding**.
- Multi-tenancy = **RLS por `org_id`** (no negociable, SRS §4.1 / RNF-01).
- Cobranza/factura/notificación = **puertos + adaptadores** (SRS §4.2/§4.3); el núcleo no importa lo concreto.
- Idempotencia de webhooks por `transaccion_id` único (no negociable, RNF-05).

## Known gotchas (los bugs caros e invisibles de este dominio)

- **RLS + pooling:** el contexto de tenant (`SET LOCAL app.current_org`) se fija **por transacción/petición**;
  en conexiones reutilizadas (pool) un contexto sin resetear **fuga datos entre tenants**. Fail-closed si no hay contexto.
- **El rol de BD de la app debe ser NO-superusuario** (un superusuario **ignora RLS**). El **super admin de
  PLATAFORMA es ortogonal a RLS**: NO fija el GUC ⇒ es fail-closed sobre tablas tenant (no ve datos de negocio),
  y su tabla `plataforma_admin` vive **fuera** del modelo tenant (sin org_id, sin policy).
- **RLS fail-closed con GUC vacío:** un GUC custom tras `SET LOCAL`+commit revierte a **`''` (cadena vacía), NO
  a NULL** en conexiones del pool → toda policy debe usar `NULLIF(current_setting('app.current_org', true), '')::uuid`.
  Ya aplicado (migración 0003). **Cualquier policy nueva debe seguir este patrón.**
- **Cuotas:** nada de aritmética `+30 días`; usar "mismo día del mes" y *clamp* a 29/30/31 → último día del mes (SRS §7.2).
- **Pagos:** webhook duplicado ⇒ sin doble pago ni doble comprobante; monto que no cuadra ⇒ **cola de
  conciliación**, nunca se descarta un pago (RNF-06); multi-cuota ⇒ FIFO sobre vencidas más antiguas.
- **Menores:** no se guarda deportista sin ≥1 tutor + `CONSENTIMIENTO`; datos médicos cifrados en reposo; auditar
  pagos manuales / cambios de monto / emisión de comprobantes (RNF-02/03).
- **DELETE de sucursal/categoría:** protegido en API (409 si está en uso) aunque la BD tenga FKs CASCADE —
  no confíes en el CASCADE para decidir si se puede borrar.
- **Índices únicos de CI (deportista/tutor/entrenador) son PARCIALES y viven SOLO en las migraciones**
  (`(org_id, ci) WHERE ci IS NOT NULL`), NO como `Index` declarativo en los modelos → un `alembic
  --autogenerate` futuro sugeriría **dropearlos**: **ignorar**, la migración es la fuente de verdad.
- **`disciplina_id` (FK al catálogo global) es lo canónico.** Los textos legacy `deportista.disciplina` y
  `entrenador.disciplinas` (JSONB) **se conservan** (no se dropean), por simetría con el rename — no los uses
  como verdad; sirven solo de respaldo histórico.

### Gotchas de entorno / código
- **Worktree propio por sesión** al paralelizar: una rama NO aísla el árbol de trabajo; compartir el dir
  principal entre dos sesiones las pisa (lección de los 3 epics paralelos).
- **Puertos ocupados en esta máquina:** 5432 (`languageacademy-db`), 5433 (`ipc-db`), 8000 (Django ajeno),
  5173 (otro front). Usar los overrides (5434/8010/5180).
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
| UI admin/entrenador y consola super admin (`/plataforma`) | `frontend/src/` |
| Docker, CI, env, despliegue worker | `infra/` |
| Spec del epic activo | `docs/specs/<epic>.md` (efímera; hoy no hay ninguna) |
