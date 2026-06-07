# HANDOFF — LATINASPORT

> Fuente única de estado del proyecto (junto con `CLAUDE.md`). Se **actualiza al cerrar
> cada epic**. Máx ~150 líneas; poda lo viejo. Esto NO es un changelog — es un snapshot
> de "cómo está el mundo hoy".

_Última actualización: 2026-06-07 — epic **Recordatorio de deudores al entrenador** integrado en `main` (migración **0014**): asignación entrenador↔sucursales (M:N) + teléfono y digest semanal de morosos por WhatsApp (cron lunes + botón a demanda). Migraciones **0001→0014**. Verificado: **214 tests** (BD real) + gates + frontend build, todo verde. (También: bugfix UI — se retiró el toggle de rol del prototipo que dejaba a un ENTRENADOR verse como ADMIN.)_

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

**MVP fase 1 COMPLETO** y verificado E2E:
1. **Deportistas**: login, lista, perfil (tabs + ficha médica por rol), RLS activa.
2. **Cobranza**: cuotas (FIJO/ANIVERSARIO), pago **efectivo** y **QR** (sandbox OpenBCB) con
   **webhook idempotente** + cola `conciliacion_pendiente`, **recibo PDF**, cron diario (beat),
   Panel de cobranza (KPIs + morosidad) + Registrar pago (QR vivo).
3. **Asistencia**: `sesion`/`asistencia`, API (roster get-or-create, guardar idempotente por
   `(sesion_id,deportista_id)`, historial) y pantalla **Tomar asistencia** (mobile-first). Entrenador ve solo sus sucursales.
4. **Reportes** (solo ADMIN, sin migración): ingresos por mes (pagos CONFIRMADO) + % asistencia.
5. **Egresos** (migración 0005, solo ADMIN): lista + filtros + total + alta auditada.
6. **Muro de avisos** (migración 0006): feed scoped por rol; CRUD solo ADMIN con soft-delete.

**Fase 2 (en curso):**
7. **Programación de clases** (migración 0007): `horario_clase` + `sesion` ampliada; CRUD ADMIN
   `/horarios` + `/horarios/semana`; crons `generar_sesiones_programadas` (reusa get-or-create de
   Asistencia) y `recordatorios_clase` (idempotente), ambos por org. Pantalla **Horarios**.
8. **Auto-registro de deportista** (migración 0008, **EN SISTEMA**, no link público): `solicitud_registro`;
   captura autenticada (ADMIN/ENTRENADOR scoped), cola, **aprobar** solo ADMIN (reusa `services/deportista.py`)
   o rechazar. Pantalla **Solicitudes**.
9. **Abonos** (pagos parciales, migración 0009): `cuota.monto_pagado`, estado **PARCIAL**,
   `pago.credito_aplicado`, tabla `credito`. Parciales **solo efectivo** (`monto_recibido`); sobrepago
   → crédito por inscripción. QR/webhook intactos (QR siempre por el total). KPI "Crédito a favor".
10. **Recibo** no-fiscal (migración 0010): cabecera "SnapCoding - LatinoSport" + nombre escuela,
    **N° correlativo por org** `REC-NNNNNN` (atómico vía `recibo_contador`, idempotente, efectivo+QR),
    leyenda "no válido como factura".
11. **WhatsApp Cobro (saliente)** (migración 0011): `recordatorio_pago` con `UNIQUE(cuota_id,tipo,ciclo)`
    (idempotencia). `WhatsAppPort` + adaptadores **mock** (default) y **Meta Cloud API** (esqueleto). Cron
    envía `PROXIMO_VENCIMIENTO` (N días antes) y `MOROSIDAD` (1×/mes/cuota); reusa `crear_pago_qr` (NO toca
    conciliación). Endpoint `POST /cobranza/cuotas/{id}/recordatorio` + botón en Panel. Webhook `whatsapp` solo ACK.
12. **Super Admin** (consola de plataforma / onboarding del SaaS, **migración 0012**): tabla
    `plataforma_admin` (identidad de plataforma, **SIN org_id y SIN RLS**), `organizacion.estado`
    (ACTIVA/SUSPENDIDA), `plataforma_auditoria` (log de acciones). Login separado `POST /api/v1/plataforma/login`
    → JWT `role=SUPERADMIN` **sin org_id**; `require_superadmin` **NO fija el GUC** → el super admin es
    **fail-closed sobre tablas tenant** (no ve datos de negocio). Endpoints `/plataforma/escuelas` (alta de
    escuela + primer ADMIN fijando el GUC a la org nueva, **sin BYPASSRLS**; listar; suspender/reactivar) y
    `/plataforma/admins` (CRUD con guard ≥1 activo). Login de escuela SUSPENDIDA → **403**; el cron pausa
    orgs suspendidas. Consola frontend `/plataforma` (sesión/token separados).
13. **Gestión de Entrenadores** (**migración 0013**): `entrenador.disciplinas` (JSONB lista). CRUD ADMIN
    `/api/v1/entrenadores` que **crea la cuenta de login** del entrenador (usuario role=ENTRENADOR + perfil) en
    una transacción; listar (cualquier rol, pobla selectores); editar/baja. **Selector de entrenador real** en
    Horarios (resuelve la deuda del campo de texto). Pantalla **Entrenadores** (ADMIN).
14. **Sucursales/Categorías CRUD + Recibo por WhatsApp** (**SIN migración**): CRUD ADMIN de sucursales y
    categorías (POST/PUT/DELETE) con **DELETE protegido** (409 si está en uso; la BD tiene FKs CASCADE). Recibo
    por WhatsApp tras confirmar el pago (efectivo+QR): **enlace tokenizado HMAC stateless**
    `GET /api/v1/recibos/{org_id}/{pago_id}/{token}.pdf` (sin guardar token; reusa el `WhatsAppPort`, mock-first).
    Pantalla **Sucursales/Categorías** (ADMIN).
15. **Recordatorio de deudores al entrenador** (**migración 0014**): asignación **M:N** `entrenador_sucursal` (+RLS)
    y `entrenador.telefono`; tabla `recordatorio_deudores` (idempotencia por `(entrenador,sucursal,periodo)`). El
    entrenador recibe por WhatsApp el **digest de morosos** (deportista con ≥1 cuota `VENCIDO`) de cada sucursal donde
    trabaja: **plantilla resumen + `send_text` con el detalle** (nuevo método del `WhatsAppPort`). **Cron semanal**
    lunes 07:00 UTC (período `%G-W%V`) **+ botón a demanda** (`POST /entrenadores/{id}/recordatorio-deudores`, ADMIN,
    período `MANUAL-<ts>` que no colisiona con el cron). **Alcance acotado:** NO toca el JWT `sucursal_ids` ni el RLS
    de otras tablas. CRUD de Entrenadores extendido (teléfono + multiselect de sucursales + botón en la pantalla).

**Migraciones:** `0001→0014` (Egresos=0005, Muro=0006, Horarios=0007, Auto-registro=0008, Abonos=0009,
Recibo=0010, WhatsApp/recordatorio_pago=0011, **SuperAdmin=0012**, **Entrenadores=0013**, **Deudores/recordatorio_deudores=0014**;
Reportes y Sucursales/Recibo sin migración).

Próximos candidatos: resto de **Fase 2** (portal passwordless OTP/WhatsApp, **chatbot WhatsApp entrante**,
factura SIN, **OpenBCB real** con onboarding BCB; credenciales reales de Meta + plantillas aprobadas para
activar el envío WhatsApp). Fase 3: rendimiento, voz, analítica.
**Deuda menor:** `JUSTIFICADO` en asistencia; gating fino por categoría (hoy a nivel sucursal);
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
(ENTRENADOR). Org: `Academia Andina` (BO/BOB), 2 sucursales, 8 deportistas. Super admin: el que pongas en
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

Nada en vuelo. El epic **Recordatorio de deudores al entrenador** está **integrado en `main`** y su spec efímera
(`docs/specs/deudores-entrenador.md`) se borró en este cierre. Gateo por rol unificado: `nav.ts` usa
`roles?: Role[]` + `navGroupsForRole`; rutas solo-ADMIN usan `RoleRoute allow={['ADMIN']}`. La consola super
admin usa **sesión/token separados** en `/plataforma`. Remoto `imertetsu/sport-school` (push vía
`http.sslBackend=schannel` por el proxy TLS). Al abrir el próximo epic, `product-owner` crea `docs/specs/<epic>.md`.

## Recent decisions

- **2026-06-07 Recordatorio de deudores al entrenador.** `entrenador_sucursal` (M:N, RLS) + `entrenador.telefono`;
  deudor = deportista con ≥1 `cuota.estado='VENCIDO'` (NO se reimplementa la lógica de vencimiento; la mantiene
  `cobranza_diaria`); ruta de joins `cuota→inscripcion→deportista.sucursal_id` (**FK directa**, sin categoría); saldo =
  `SUM(monto - monto_pagado)`. WhatsApp en **2 mensajes**: plantilla `resumen_deudores` (resumen+conteo, inicia la
  conversación) + nuevo `WhatsAppPort.send_text` (detalle multilínea; texto libre no cabe en params de plantilla
  Meta). Idempotencia `recordatorio_deudores` `UNIQUE(entrenador,sucursal,periodo)`: cron usa **semana ISO**
  (`%G-W%V`), botón usa `MANUAL-<ts>` → no colisionan y el botón permite reenvío intencional. **Alcance acotado**
  (decisión de producto): la asignación SOLO alimenta el recordatorio; no cambia la vista del entrenador.
- **2026-06-07 Bugfix UI: rol real, sin toggle de prototipo.** El chip de usuario alternaba `viewRole`
  ADMIN⇄ENTRENADOR para cualquiera (exponía ítems solo-ADMIN a un ENTRENADOR). Ahora `viewRole = user.role`
  (no modificable), el chip es estático y `RoleRoute` gatea sobre el **rol real**. El backend ya bloqueaba los datos
  (`require_role`); esto cierra la fuga de UI.
- **2026-06-07 Tres epics en PARALELO (3 sesiones).** Super Admin, Entrenadores y Sucursales/Recibo se
  construyeron simultáneamente en **worktrees + ramas + stacks docker aislados** según un plan de coordinación
  (`docs/plan-paralelo.md`, ya borrado). Main los integró en orden **A→B→C** resolviendo los **appends compartidos**
  (`types.ts`/`client.ts`/`App.tsx`/`__init__.py`) y **linealizando la cadena Alembic** (0013 `down_revision`
  0011→0012). Verificación de integración: **215 tests** (suite completa) + gates (ruff/mypy/import-linter) +
  frontend build, todo verde; migración **roundtrip OK**; **RLS del super admin fail-closed verificado** (sin GUC
  ⇒ 0 filas de negocio). **Gotcha/lección:** (1) una sesión corrió `ruff format` sobre TODO el backend (normalizó
  ~18 archivos ajenos al epic, cosmético pero ruidoso en el diff); (2) colisión por compartir el **dir principal**
  entre sesiones → **regla firme: worktree propio por sesión** (una rama NO aísla el árbol de trabajo).
- **2026-06-07 Super Admin (consola de plataforma).** Identidad de plataforma `plataforma_admin` **SIN org_id
  y SIN RLS** (no es tenant); login `POST /api/v1/plataforma/login` → JWT `role=SUPERADMIN` sin org_id;
  `require_superadmin` **NO fija el GUC** ⇒ fail-closed sobre tablas tenant. Alta de escuela crea org + primer
  ADMIN fijando el GUC a la org nueva (**sin BYPASSRLS**). `organizacion.estado` ACTIVA/SUSPENDIDA: login de
  escuela suspendida → 403 y el cron la pausa. Bootstrap del primer super admin = `python -m app.seed_plataforma`
  (env `PLATFORM_ADMIN_EMAIL`/`PASSWORD`) — **esto resuelve el viejo pendiente `create-admin`** (ya no aplica).
- **2026-06-07 Gestión de Entrenadores.** `entrenador.disciplinas` (JSONB). El CRUD ADMIN crea la **cuenta de
  login** (usuario ENTRENADOR + perfil) en una transacción; el listar lo consume cualquier rol para poblar
  selectores → **selector real de entrenador en Horarios** (resuelve la deuda del campo de texto).
- **2026-06-07 Sucursales/Categorías + Recibo WhatsApp.** CRUD ADMIN con **DELETE protegido** (409 si está en
  uso; FKs CASCADE en BD). Recibo por WhatsApp = **enlace tokenizado HMAC stateless**
  `GET /api/v1/recibos/{org_id}/{pago_id}/{token}.pdf` (no se persiste token; se valida por HMAC), reusa el
  `WhatsAppPort` (mock-first) y `PUBLIC_BASE_URL` para el enlace público.
- **2026-06-06 Epic WhatsApp Cobro (saliente).** Recordatorio de cuota con **QR de pago** por WhatsApp; Meta
  Cloud API directo, número único de plataforma, **mock-first**, solo saliente. Idempotencia = `recordatorio_pago`
  `UNIQUE(cuota_id,tipo,ciclo)` + `ON CONFLICT DO NOTHING`. **NO toca la conciliación**: reusa `crear_pago_qr`; el
  pago sigue por `POST /webhooks/openbcb` (idempotente por `transaccion_id`). QR como **link de texto** en el body
  (base64 no enviable; `header_image` opcional para migrar a imagen sin re-romper contrato).
- **2026-06-06 Epic Recibo.** Recibo no-fiscal: cabecera "SnapCoding - LatinoSport", N° correlativo por org
  `REC-NNNNNN` (incremento atómico `INSERT … ON CONFLICT DO UPDATE … RETURNING`), efectivo+QR comparten
  `_asignar_numero_recibo` (idempotente), leyenda "no válido como factura". NO es factura SIN (fase 2).
- **2026-06-06 Epic Abonos (pagos parciales).** QR **siempre por el total** (webhook/conciliación intactos) →
  parciales solo por efectivo; sobrepago → crédito por inscripción consumido en el siguiente pago; cuota a medias
  → **PARCIAL** con precedencia de VENCIDO. Tests `@db` con `Session(expire_on_commit=False)`.
- **2026-06-06 Rename interno cantera→latinosport + primer deploy real.** Todo `cantera`→`latinosport`: BD
  `latinosport`, rol `latinosport_app` (NO superusuario), connection strings, imagen, emails de seed. ⚠️ **Recrear
  la BD (`docker compose down -v`)**: nombre/rol se hornean al inicializar el volumen de Postgres. Deploy en
  `177.222.39.139`, repo en `/opt/latinosport` (IP:puerto, sin dominio/HTTPS aún) vía `infra/bootstrap.sh`.
- **2026-06-06 CI/CD.** Job `deploy` en `.github/workflows/ci.yml`: push a `main` → SSH → `git reset --hard` +
  `bash infra/deploy.sh` (build-on-server; la imagen aplica migraciones). **Gateado por `vars.DEPLOY_ENABLED=='true'`**.
- **2026-06-06 Hardening de deploy.** Imagen api/worker **autocontenida** (context=raíz, copia `backend/`+
  `alembic.ini`+`migrations/`); **guard de prod** en `config.py` (`APP_ENV=production` ⇒ falla con JWT_SECRET
  débil/<32, `devpass`, o `OPENBCB_SANDBOX=true`).
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
