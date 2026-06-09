# HANDOFF — LATINASPORT

> Fuente única de estado del proyecto (junto con `CLAUDE.md`). Se **actualiza al cerrar
> cada epic**. Máx ~150 líneas; poda lo viejo. Esto NO es un changelog — es un snapshot
> de "cómo está el mundo hoy".

_Última actualización: 2026-06-09 — epic **escuela-y-bajas** integrado en `main` (migración **0020**):
(1) login devuelve `org {id,nombre,color}` → TopBar pinta nombre + monograma de iniciales; (2) **editar
escuela** (solo ADMIN, `GET/PUT /mi-escuela`: solo nombre + color, sin logo de archivo); (3) **baja/reactivación
soft-delete reversible** de deportistas (`POST /deportistas/{id}/baja|reactivar` + `solo_activos` + `activo` en
salidas) y entrenadores (botón directo en la fila); (4) **edición completa de deportista** (datos + tutores +
ficha médica, `PUT /deportistas/{id}` reconcilia tutores con invariante de menores 422). · **avisos-whatsapp**
(migración **0021**): los Avisos del muro pueden **notificar por WhatsApp** a entrenadores/tutores según el alcance
del aviso (opt-in con checkboxes + preview con conteo + confirmación; mock-first). Migraciones **0001→0021**._

## Stack snapshot

- **Backend:** Python · FastAPI · SQLAlchemy · Pydantic → `backend/`
- **DB:** PostgreSQL + Row-Level Security (RLS) por `org_id`
- **Migraciones:** Alembic + políticas RLS → `migrations/`
- **Jobs:** Celery worker + beat (cron diario) → `backend/app/workers/`
- **Frontend:** React + Vite (SPA mobile-first) → `frontend/`
- **Infra:** Docker / docker-compose / CI → `infra/`
- **Integraciones:** OpenBCB (QR), WhatsApp, PDF, SIN (fase 2) — detrás de puertos/adaptadores.

**Roles del sistema (3):** **SUPERADMIN** (plataforma, sin org_id, fail-closed sobre tablas tenant), **ADMIN**
(escuela/org), **ENTRENADOR**. (Tutor = passwordless, fase 2; no es usuario con contraseña.)

## Estado actual — MVP fase 1 completo + fase 2 en curso

**MVP fase 1 + buena parte de fase 2 COMPLETOS** y verificados E2E. Módulos vivos en `main`:
- **Deportistas** (login, lista, perfil con ficha médica por rol, RLS; edición completa de datos+tutores+ficha;
  baja/reactivación soft-delete).
- **Cobranza** (cuotas FIJO/ANIVERSARIO, pago efectivo + QR sandbox OpenBCB con webhook idempotente + cola
  `conciliacion_pendiente`, recibo PDF, cron diario, Panel KPIs/morosidad; abonos/`PARCIAL`+`credito`, recibo
  no-fiscal `REC-NNNNNN` correlativo por org, WhatsApp Cobro saliente + recordatorio de deudores al entrenador).
- **Asistencia** (`sesion`/`asistencia`, roster get-or-create, guardar idempotente por `(sesion_id,deportista_id)`;
  el entrenador ve solo categorías de sus disciplinas asignadas, con red de seguridad).
- **Programación de clases** (`horario_clase`/`sesion`, crons), **Auto-registro** (`solicitud_registro`,
  aprobar=ADMIN), **Reportes** (solo ADMIN, sin migración: ingresos/mes + % asistencia), **Egresos** (ADMIN),
  **Muro de avisos** (feed scoped por rol, CRUD ADMIN con soft-delete; opcionalmente **notifica por WhatsApp** a
  entrenadores/tutores según alcance, opt-in con checkboxes + preview + confirmación, mock-first, log idempotente
  `aviso_notificacion`).
- **Plataforma / Super Admin** (`plataforma_admin` sin org_id/RLS, consola `/plataforma`, alta de escuelas,
  catálogo GLOBAL de disciplinas), **Gestión de entrenadores** con cuenta de login, **Sucursales/Categorías** CRUD.
- **Personas y disciplinas:** rename alumno→deportista, catálogo GLOBAL de disciplinas (`disciplina_id` FK es lo
  canónico), CI único por org + recuperar-por-CI (deportista/tutor/entrenador), entrenador multi-disciplina
  (`entrenador_disciplina` M:N con RLS), campos opcionales `domicilio`/`lugar_nacimiento`.
- **OCR cédula on-device** (Tesseract.js, la imagen NUNCA sale del navegador — RNF-02): **CI nuevo se extrae
  COMPLETO** (CI, nombres del anverso, apellidos, fecha + opcionales domicilio/lugar/grupo); **CI antiguo NO es
  OCR-able on-device** (tinta roja + fondo) → **manual**. Parser conservador (ante baja confianza deja vacío;
  nunca el serial de tarjeta, solo el "No. #######"). Guía de captura colapsable en el escáner. OCR solo en el alta.
- **Escuela (epic más reciente):** nombre + monograma de iniciales con color en el TopBar tras el login; pantalla
  `/ajustes` (solo ADMIN) para editar nombre + color (`frontend/src/features/escuela/AjustesEscuela.tsx`,
  componente `Monogram`).

**Migraciones:** `0001→0020`. Hitos: Egresos=0005, Muro=0006, Horarios=0007, Auto-registro=0008, Abonos=0009,
Recibo=0010, WhatsApp=0011, SuperAdmin=0012, Entrenadores=0013, Deudores=0014, rename deportista=0015, catálogo
disciplinas=0016, CI deportista/tutor=0017, entrenador CI+disciplinas=0018, deportista.domicilio+lugar_nacimiento=0019,
deportista.activo + organizacion.color=0020, **aviso_notificacion=0021** (log idempotente WhatsApp del muro).
Reportes y Sucursales/Recibo sin migración.

Próximos candidatos: resto de **Fase 2** (portal passwordless OTP/WhatsApp, chatbot WhatsApp entrante, factura SIN,
OpenBCB real; credenciales Meta reales + plantillas aprobadas). Fase 3: rendimiento, voz, analítica.
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
  `PLATFORM_ADMIN_PASSWORD`, `PUBLIC_BASE_URL`. **WhatsApp:** `WHATSAPP_PROVIDER` (noop|mock|meta, default noop),
  `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_WABA_ID`, `WHATSAPP_VERIFY_TOKEN`,
  `WHATSAPP_APP_SECRET`, `WHATSAPP_GRAPH_VERSION` (v21.0), `RECORDATORIO_QR_DIAS_ANTES` (3). Sin credenciales ⇒
  cae al **mock**; para enviar de verdad: `WHATSAPP_PROVIDER=meta` + credenciales Meta + plantillas aprobadas.
  Futuras: `OPENBCB_*`. **Nunca commitear secretos.**

## In-flight work

Nada en vuelo en código. **escuela-y-bajas** (0020) y **avisos-whatsapp** (0021) están **integrados en `main`**
(escuela-y-bajas mergeó directo; avisos encadenó su 0021 sobre 0020 — cadena 0019→0020→0021 verificada + gates);
sus specs efímeras (`escuela-y-bajas.md`, `avisos-whatsapp.md`) se borraron en el cierre.

**Pendientes operativos:**
- **Epics multi-sesión se integran en rama `staging`** (no `main` directo) → validar → `staging`→`main`.
- **Prod** (servidor `177.222.39.139`, `/opt/latinosport`) sigue ~**0014**: **pendiente desplegar** el chain
  **0015→0021** (0019/0020/0021 son aditivos y seguros). Deploy **gateado** (`DEPLOY_ENABLED` off), manual: `pg_dump`
  → `git pull` → `bash infra/deploy.sh`. **Antes de aplicar 0017/0018 en prod: correr la detección de CI
  duplicados** en deportista/tutor/entrenador (si hay dup no-null, el índice único parcial falla al crearse).
- **Job de deploy (CI) roto:** la sesión SSH se cae a mitad del build-on-server (`Broken pipe`, exit 255) —
  probable OOM al buildear web+api+worker en paralelo o timeout SSH. Fix pendiente en `infra/deploy.sh` + workflow
  (builds secuenciales / swap / SSH keepalive). NO es código de la app.
- **WhatsApp avisos:** la entrega REAL necesita la plantilla `nuevo_aviso` aprobada en Meta + `WHATSAPP_PROVIDER=meta`
  + credenciales; hoy mock-first (noop/mock no envía nada real). Mismo estado que cobro/deudores.

Remoto `imertetsu/sport-school` (push vía `http.sslBackend=schannel` por el proxy TLS). Al abrir el próximo epic,
`product-owner` crea `docs/specs/<epic>.md`.

## Recent decisions

- **2026-06-09 Landing page de marketing en la RAÍZ (`/`).** Página estática (HTML+CSS, sin build extra) en
  `frontend/public/landing.html` + `landing.css` + `logo.png` (lockup LatinoSport). **nginx** (`infra/Dockerfile.web`):
  `location = /` → `landing.html`; el resto (`/login`, `/panel`, assets) → SPA. Los CTA "Probar demo"/"Iniciar
  sesión" entran a `/login`. El **logo** se usa en el **Login** (`login__logo-img`, fondo blanco se funde con la
  tarjeta) y como **favicon** (`frontend/index.html`). Pendiente de reemplazo en la landing: WhatsApp real
  (`59170000000`), email (`hola@snapcoding.bo`), ciudad, e imágenes (`.img-ph` placeholders). En **dev (Vite)** `/`
  sigue siendo la SPA; el ruteo `/`→landing es solo del nginx de prod. Sin migración.
- **2026-06-09 Avisos por WhatsApp (epic, migración 0021, integrado vía staging junto a escuela-y-bajas).** Al
  crear un Aviso, el ADMIN puede notificar por WhatsApp a **Entrenadores y/o Tutores** (opt-in con checkboxes,
  desmarcados) a los destinatarios del **alcance** del aviso (ORG / SUCURSAL / CATEGORIA). En CATEGORIA los
  entrenadores salen por `entrenador_disciplina` de la disciplina de la categoría (tutores = los de deportistas de
  esa categoría). **Preview con conteo + confirmación** antes de enviar (evita blasts accidentales). Envío en
  segundo plano (task Celery a demanda), **idempotente** (`aviso_notificacion` UNIQUE(aviso_id,tipo_destinatario,
  destinatario_id); sin teléfono → SIN_TELEFONO). `send_template` plantilla `nuevo_aviso`. **Mock-first** (sin
  envíos reales hasta Meta + plantilla aprobada). **Editar un aviso NO notifica** (solo el alta).
- **2026-06-09 Escuela + bajas (epic, migración 0020).** (1) Borrado = **dar de baja** (soft-delete reversible,
  conserva historial); **nunca borrado físico** de deportistas/entrenadores. (2) Editar escuela = **solo nombre +
  color** del monograma; el "logo" es un monograma de iniciales, **sin almacenar imágenes** (RNF-02). (3) Editar
  deportista = **completo** (datos + tutores + ficha médica); la reconciliación de tutores respeta el invariante
  de menores **server-side** (lista vacía o quitar al tutor del consentimiento → **422**). (4) El login devuelve
  `org {id,nombre,color}` reusando la consulta que ya hacía → TopBar pinta nombre + monograma sin llamada extra.
- **2026-06-07 Campos opcionales deportista + red de seguridad de scoping** (migración 0019). `domicilio` y
  `lugar_nacimiento` (TEXT nullable; grupo sanguíneo ya en `ficha_medica.tipo_sangre`). **Red de seguridad** en la
  visibilidad del ENTRENADOR: si NO tiene disciplinas asignadas ve por **sucursal** (no vacío), y un
  deportista/categoría con `disciplina_id` **NULL** es **visible** (el filtro por disciplina solo aplica cuando el
  entrenador tiene disciplinas Y el registro tiene disciplina).
- **2026-06-07 Personas y Disciplinas (S1–S4 + OCR), integrado vía `staging`.** (1) catálogo de disciplinas es
  **GLOBAL** (gestionado por SUPERADMIN); orgs lo leen y referencian por FK `disciplina_id` (canónico). (2) **CI
  único por org** (no global) vía índices parciales; alta con CI dup → **409** + flujo "recuperar-por-CI". (3) **OCR
  de cédula on-device**: la imagen no sale del navegador (RNF-02); CI nuevo se extrae completo, CI antiguo → manual,
  parser conservador. (4) Entrenador multi-disciplina. La **disciplina** acota la vista de deportistas+asistencia
  del entrenador (server-side por request, helper `disciplina_ids_de_usuario`; NO en el JWT). 0018 renumerada
  desde 0017 al linealizar la cadena Alembic en staging.
- **2026-06-07 Fase 2 consolidada (varios epics).** **Super Admin**: `plataforma_admin` sin org_id/RLS,
  fail-closed sobre tablas tenant, alta de escuela sin BYPASSRLS, bootstrap `seed_plataforma`. **Entrenadores**:
  CRUD ADMIN crea cuenta de login en una txn. **Sucursales/Recibo**: DELETE protegido (409), recibo por enlace
  HMAC stateless. **WhatsApp Cobro**: mock-first, solo saliente, idempotente, NO toca la conciliación. **Recibo**
  no-fiscal `REC-NNNNNN` atómico. **Abonos**: QR siempre por el total (parciales solo efectivo); sobrepago→crédito.
  **Recordatorio de deudores**: deudor = ≥1 `cuota.estado='VENCIDO'`, WhatsApp en 2 mensajes, idempotente.
  **Lección:** **worktree propio por sesión** al paralelizar (una rama NO aísla el árbol).
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
| Spec del epic activo | `docs/specs/<epic>.md` (efímera; hoy no hay ninguna) |
