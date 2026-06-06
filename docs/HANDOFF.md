# HANDOFF — LATINASPORT

> Fuente única de estado del proyecto (junto con `CLAUDE.md`). Se **actualiza al cerrar
> cada epic**. Máx ~150 líneas; poda lo viejo. Esto NO es un changelog — es un snapshot
> de "cómo está el mundo hoy".

_Última actualización: 2026-06-06 — Fase 2: **Programación de clases** (7º) + **Auto-registro de alumno** en-sistema (8º). 8 epics en main._

## Stack snapshot

- **Backend:** Python · FastAPI · SQLAlchemy · Pydantic → `backend/`
- **DB:** PostgreSQL + Row-Level Security (RLS) por `org_id`
- **Migraciones:** Alembic + políticas RLS → `migrations/`
- **Jobs:** Celery worker + beat (cron diario) → `backend/app/workers/`
- **Frontend:** React + Vite (SPA mobile-first) → `frontend/`
- **Infra:** Docker / docker-compose / CI → `infra/`
- **Integraciones:** OpenBCB (QR), WhatsApp, PDF, SIN (fase 2) — detrás de puertos/adaptadores.

**Estado actual:** **MVP fase 1 COMPLETO** — seis epics entregados y verificados E2E:
1. **scaffolding + Alumnos**: login, lista, perfil (tabs + ficha médica por rol), RLS activa.
2. **Cobranza**: motor de cuotas (FIJO/ANIVERSARIO), pago **efectivo** y **QR** (sandbox
   OpenBCB) con **webhook idempotente** + cola `conciliacion_pendiente`, **comprobante PDF**,
   cron diario (Celery beat), **Panel de cobranza** (KPIs + morosidad) + Registrar pago (QR vivo).
3. **Asistencia**: tablas `sesion`/`asistencia`, API (categorías por rol, roster get-or-create,
   guardar **idempotente** por `(sesion_id,alumno_id)`, historial), y pantalla **Tomar asistencia**
   (toggles Presente/Ausente, contadores en vivo, Guardar, mobile-first). Entrenador ve solo sus
   sucursales. Probado en navegador + API: marcar → guardar → recargar refleja.
4. **Reportes** (RF-COM-02/03): **sin migración** (agrega Cobranza+Asistencia). API
   `GET /reportes/ingresos?anio=` (pagos CONFIRMADO por mes, 12 meses) y `GET /reportes/asistencia`
   (% presente global + por categoría), **solo ADMIN (403 entrenador)**. Pantalla **Reportes**
   (barras CSS de ingresos + tabla de asistencia con %, nav gateado a ADMIN). Verificado E2E.
5. **Egresos** (RF-FIN-07): tabla `egreso` (tenant, RLS NULLIF) + migración `0005`; API
   `/egresos` **solo ADMIN** (listar con filtros sucursal/categoría/fechas + `total_monto` del
   filtro, alta auditada con `registrado_por`), y pantalla **Egresos** (lista + filtros + total
   Bs + alta, gateada a ADMIN). Verificado API + navegador.
6. **Muro de avisos** (RF-COM-01): tabla `aviso` (tenant, RLS NULLIF) + migración `0006`; API
   `/avisos` (feed scoped por rol: ADMIN todo, ENTRENADOR ORG + sus sucursales/categorías, sin
   vencidos), CRUD **solo ADMIN** con **soft-delete** (`activo=false`) e invariante alcance↔id
   (422), y pantalla **Avisos** (muro de tarjetas + alta/edición ADMIN, toggle "mostrar vencidos").
   Verificado API + navegador (UTF-8/emoji OK).

**Deploy endurecido** (2026-06-06): imagen api/worker autocontenida + guard de prod; `docker compose
up --build` valida el stack desde cero. Ver "Recent decisions".

### Fase 2 (en curso)
7. **Programación de clases** (RF-DEP-03): tabla `horario_clase` (RLS NULLIF) + `sesion` ampliada
   (`horario_id`, `recordatorio_enviado_en`) — migración `0007`. API `/horarios` (CRUD ADMIN +
   `/horarios/semana` scoped por rol). Cron: `generar_sesiones_programadas` (1×/día, **reutiliza el
   get-or-create de Asistencia**, idempotente) + `recordatorios_clase` (cada hora, idempotente vía
   `recordatorio_enviado_en`, Noop). Pantalla **Horarios** (rejilla semanal Lun–Dom, alta/edición
   ADMIN). Verificado API + navegador.
8. **Auto-registro de alumno** (RF-USR) — **versión EN SISTEMA** (NO link/token público; decisión del
   usuario). Tabla `solicitud_registro` (RLS NULLIF) — migración `0008`. `POST /solicitudes`
   **autenticado** (ADMIN o ENTRENADOR captura; entrenador scoped a sus sucursales), cola
   `GET /solicitudes` (scoped por rol), **aprobar** (solo ADMIN → **reutiliza `services/alumno.py`**
   para crear alumno+tutor+consentimiento[+inscripción], 409 si resuelta) y **rechazar** (motivo).
   Pantalla **Solicitudes** (form "Nueva solicitud" + cola con Aprobar/Rechazar solo-admin). Verificado E2E.

Próximos candidatos: resto de **Fase 2** (portal passwordless OTP/WhatsApp, chatbot cobros, factura SIN,
**OpenBCB real** con onboarding BCB). Fase 3: rendimiento, voz, analítica.
**Deuda menor:** `GET /entrenadores` (selector de entrenador en Horarios usa campo de texto hoy);
nombre del UNIQUE de `horario_clase` difiere modelo↔migración (cosmético); cosmético categoría duplicada;
`JUSTIFICADO` en asistencia; gating fino por categoría; podar este HANDOFF.

## Active flags / config

### Cómo correr el slice en local (verificado en esta máquina)
Los puertos por defecto (5432/8000/5173) están **ocupados por otros proyectos** del usuario
(`languageacademy-db`, etc.), así que se usan overrides locales. El compose ahora acepta
`DB_PORT`/`REDIS_PORT`/`API_PORT`/`WEB_PORT`.
```
# 1) BD + redis (puerto host db = 5434 aquí)
DB_PORT=5434 docker compose -f infra/docker-compose.yml up -d --wait db redis
# 2) migraciones (rol OWNER):
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/cantera \
  backend/.venv/Scripts/alembic upgrade head
# 3) seed (corre como OWNER, bypassa RLS para sembrar):
cd backend && DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/cantera \
  JWT_SECRET=... CORS_ORIGINS=http://localhost:5180 .venv/Scripts/python -m app.seed
# 4) API (rol cantera_app → RLS activa) en 8010 (OPENBCB_SANDBOX habilita el "Simular pago"):
cd backend && DATABASE_URL=postgresql+psycopg://cantera_app:devpass@localhost:5434/cantera \
  JWT_SECRET=<32+ chars> CORS_ORIGINS=http://localhost:5180,http://127.0.0.1:5180 \
  OPENBCB_SANDBOX=true REDIS_URL=redis://localhost:6379/0 \
  .venv/Scripts/python -m uvicorn app.main:app --port 8010
# 5) Frontend en 5180:
cd frontend && VITE_API_URL=http://localhost:8010 npm run dev -- --port 5180 --strictPort
```
**Credenciales de seed:** `admin@cantera.bo / admin1234` (ADMIN) · `coach@cantera.bo /
coach1234` (ENTRENADOR). Org: `Academia Andina` (BO/BOB), 2 sucursales, 8 alumnos.

### Flags de negocio (configurables por organización — aún sin implementar; SRS §4.2/§7)
- `ORGANIZACION.modo_cobro_default`: `FIJO` | `ANIVERSARIO`
- `ORGANIZACION.dia_corte_fijo`, `prorratea_primer_periodo` (bool) — **default sin decidir** (SRS §10.4)
- Recordatorio de pago: `N días antes`; toggles de notificación por organización (RNF-07)
- Env reales hoy: `APP_NAME, DATABASE_URL, MIGRATION_DATABASE_URL, JWT_SECRET,
  JWT_EXPIRE_MINUTES, CORS_ORIGINS, REDIS_URL, VITE_API_URL` (ver `.env.example`).
  Futuras: `OPENBCB_*`, `WHATSAPP_*`. **Nunca commitear secretos.**

## In-flight work

**none** — 8 epics en `main` (MVP + deploy endurecido + Fase 2: Programación de clases, Auto-registro).
Migraciones `0001→0008` (Egresos=0005, Muro=0006, Horarios=0007, Auto-registro=0008; Reportes sin migración).
Gateo por rol unificado: `nav.ts` usa `roles?: Role[]` + `navGroupsForRole`; rutas solo-ADMIN usan
`RoleRoute allow={['ADMIN']}`. Remoto `imertetsu/sport-school` (push vía `http.sslBackend=schannel`
por el proxy TLS). Al abrir el próximo epic, `product-owner` crea `docs/specs/<epic>.md`.

## Recent decisions

- **2026-06-06 Rebrand → LATINOSPORT + acento AZUL.** Nombre oficial **LATINOSPORT** (antes
  CanteraSport) en `APP_NAME`/`VITE_APP_NAME`, config backend/frontend, `<title>`, seed (admin) y
  docstrings. **Acento por defecto = AZUL** en oklch (`--accent: oklch(0.58 0.16 250)` ≈ #2F6BD6,
  hover `0.50 0.17 252`, suave `0.95 0.03 250`, tinta `0.46 0.14 252`); verde pasa a alterno
  (`[data-accent='verde']`). Se renovaron las storage keys a `latinosport.*` para que el azul
  aplique aunque hubiera un acento viejo guardado. Badges de estado (verde/ámbar/rojo) NO cambian.
- **2026-06-06 CI/CD.** Job `deploy` en `.github/workflows/ci.yml`: en push a `main`, tras
  pasar backend+frontend, hace **SSH al servidor** (sshpass, user+pass) → `git reset --hard
  origin/main` + `bash infra/deploy.sh` (build-on-server: `docker compose up -d --build`, la
  imagen aplica migraciones). **Gateado por `vars.DEPLOY_ENABLED=='true'`** (se salta hasta que
  se active). **Secretos de repo requeridos** (Settings→Secrets→Actions): `SERVER_HOST`,
  `SERVER_USER`, `SERVER_PASSWORD`, `SERVER_PORT`, `DEPLOY_PATH`. El servidor necesita Docker +
  repo clonado + `.env` de **producción** (APP_ENV=production, secretos reales) en la raíz.
- **2026-06-06 Fase 2 — Auto-registro de alumno (EN SISTEMA).** El usuario descartó la 1ª versión
  con **link/token público** (se construyó y se **borró** antes de commitear); ahora el registro es
  una **pantalla autenticada**: entrenador/admin captura `POST /solicitudes` → cola → solo ADMIN
  aprueba (reutiliza `services/alumno.py`, factorizado desde el router de Alumnos) o rechaza.
  **Fix (main):** el modelo usaba `TimestampMixin` (created_at+updated_at) pero la migración/contrato
  solo tenían `created_at` → quitado el mixin (solo `created_at`, consistente con egreso/aviso); lo
  cazó el seed + 5 tests `db`.
- **2026-06-06 Fase 2 — Programación de clases** (RF-DEP-03). `horario_clase` + `sesion` ampliada
  (migración 0007). El cron `generar_sesiones_programadas` **reutiliza** `_get_or_create_sesion` de
  `app.services.asistencia` (no duplica; key `(categoria,fecha,hora_inicio)`); `recordatorios_clase`
  (cada hora) es idempotente vía `sesion.recordatorio_enviado_en`; ambos recorren orgs fijando
  contexto (patrón de `cobranza_diaria`). `dia_semana` 0=Lunes…6=Domingo (= `date.weekday()`).
- **2026-06-06 Hardening de deploy.** Validado `docker compose up --build` de punta a punta
  (db+redis+api+worker+beat+web) en proyecto/puertos aislados (`-p cantera_verify`): la imagen
  api aplica las 6 migraciones sobre BD vacía y arranca como `cantera_app`; web sirve la SPA.
  **Imagen api/worker AUTOCONTENIDA**: build context = raíz, copia `backend/`+`alembic.ini`+
  `migrations/` DENTRO (antes dependía de montar volúmenes → no desplegable fuera del repo);
  `.dockerignore` (raíz) mantiene el contexto liviano. **Guard de prod** en `config.py`
  (`APP_ENV=production` ⇒ FALLA al arrancar con JWT_SECRET débil/<32, credenciales `devpass`,
  o `OPENBCB_SANDBOX=true`); `.env.example` tiene checklist de producción. CI ya estaba correcto.
  El proxy TLS corporativo NO afecta builds dentro de Docker (solo npm/pip en el host).
- **2026-06-06 Epic Muro de avisos** (cierra el MVP). Tabla `aviso` + migración 0006 (RLS NULLIF).
  Feed scoped por rol; CRUD ADMIN con **soft-delete** (`activo=false`, sin borrado físico) e
  invariante alcance↔id validada en backend (422). Item "Avisos" visible a ambos roles (el feed
  filtra). Verificado E2E (incl. UTF-8/acentos/emoji — el `400` en curl era artefacto del shell Windows).
- **2026-06-06 Epic Egresos** construido en **paralelo** con Reportes (sesiones separadas).
  Aislamiento: rama `epic/egresos` en un **git worktree** hermano + stack docker propio
  (`-p cantera_egresos`, db 5435 / redis 6380, API 8011 / web 5181). **Lección:** una rama NO
  aísla el árbol de trabajo — dos sesiones en el mismo working dir se pisan; el worktree sí.
  **Fix de integración (main, trust-but-verify):** `total_monto` de `/egresos` sumaba con
  **producto cartesiano** (`SUM(Egreso.monto)` con `FROM subquery` → suma × nº filas); corregido
  agregando sobre `sub.c.monto`. Lo cazó un test `@pytest.mark.db`. (2 agentes dev se cortaron por
  socket transitorio → reconciliados; literal de rol ADMIN real = `"ADMIN"`.)
- **2026-06-05** Stack confirmado: **FastAPI + React (Vite) + PostgreSQL/RLS + Alembic + Celery** (elección del usuario sobre el SRS §11, que lo dejaba abierto).
- **2026-06-05** Producto **en español** (UI y artefactos).
- **2026-06-05** Recibido el **diseño UI** (prototipo claude.ai, efímero) → capturado en
  `docs/design/design-system.md`. 4 pantallas: Panel de cobranza, Registrar pago (QR/efectivo),
  Perfil del deportista (tabs), Asistencia (entrenador). Tokens: Space Grotesk + Hanken Grotesk,
  acento verde/azul, badges verde/ámbar/rojo, modo claro plano.
- **2026-06-05** Desarrolla **SnapCoding**. **Nombre = CanteraSport** (decidido por el
  usuario), configurable vía `APP_NAME`/`VITE_APP_NAME`.
- **2026-06-05** Slice construido por 4 agentes en paralelo (backend/db/frontend/infra).
  **Fixes de integración (trust-but-verify, hechos por main):**
  - `login_lookup` devolvía 5 columnas; backend leía 7 → añadidas `nombre,email` (migración 0001).
  - `cors_origins` rompía el parseo de env (pydantic-settings JSON-decode) → `NoDecode` + validador.
  - **passlib 1.7.4 incompatible con bcrypt ≥4.1** → reemplazado por `bcrypt` directo en `security.py`.
  - Puertos del host del compose parametrizados (`DB_PORT`…) por colisiones en la máquina.
- Decisión técnica (agente): acceso a ficha médica gateado a **nivel sucursal** en este slice
  (el diseño pide nivel categoría → refinar en epic posterior).
- **2026-06-05 Epic Cobranza** construido por 4 agentes (2 se cortaron por error de socket
  transitorio → relanzados en background con "reconciliar y completar"). **Fixes de
  integración (main):**
  - **RLS no era fail-closed con GUC vacío**: un GUC custom tras `SET LOCAL`+commit vuelve a
    `''` (no NULL) en la conexión del pool → `''::uuid` lanzaba error en vez de 0 filas.
    Migración **0003** endurece las 12 políticas con `NULLIF(current_setting(...), '')::uuid`.
  - **Drift de contrato QR**: el frontend asumía `qr.pago.id`/`png_data_url`; el backend
    devuelve plano `{pago_id, estado, qr_png_data_url, …}` → alineado `QrResponse` + 3 usos
    en `RegistrarPago.tsx` (crasheaba la app al "Generar QR").
- Decisión (agente): OpenBCB en **sandbox** (genera QR + endpoint `simular-confirmacion`);
  integración real pendiente de onboarding BCB (SRS §10.3). `prorratea_primer_periodo` del seed = true.
- **2026-06-05 Epic Asistencia** (3 agentes: db/backend/frontend; sin infra). Migración 0004
  (`sesion`/`asistencia`, RLS con patrón NULLIF). Scoping ENTRENADOR por **sucursal** (categoría
  fina = futuro). Default UI = **todos Presente al abrir** (móvil: solo tocas ausentes); backend
  devuelve `estado=null` para no marcados y deja la UX al frontend.
  **Fix (main):** un test de asistencia accedía `sesion.id` fuera de la `Session` (DetachedInstanceError
  por `expire_on_commit`) → capturar el id antes del commit + reforzado con re-chequeo de no-duplicación.
- **2026-06-06 Epics en paralelo (2 sesiones):** Reportes (esta sesión, sin migración) + Egresos
  (sesión aparte, rama `epic/egresos`, BD/puertos aislados). Split elegido para evitar el choque de
  la **cadena Alembic**: solo el epic con tabla nueva (Egresos) crea migración (0005); Reportes solo
  lee. Reportes = **solo ADMIN** (gerencial); ingresos cuenta el `pago` CONFIRMADO (no las cuotas)
  para no doblar.
- Multi-tenancy = **RLS por `org_id`** (no negociable, SRS §4.1 / RNF-01).
- Cobranza/factura/notificación = **puertos + adaptadores** (SRS §4.2/§4.3); el núcleo no importa lo concreto.
- Idempotencia de webhooks por `transaccion_id` único (no negociable, RNF-05).

## Known gotchas (los bugs caros e invisibles de este dominio)

- **RLS + pooling:** el contexto de tenant (`SET LOCAL app.current_org`) se fija **por
  transacción/petición**; en conexiones reutilizadas (pool) un contexto sin resetear
  **fuga datos entre tenants**. Fail-closed si no hay contexto.
- **El rol de BD de la app debe ser NO-superusuario**: un superusuario **ignora RLS** por
  completo. (decisión infra + db)
- **RLS fail-closed con GUC vacío:** un GUC custom (`app.current_org`) tras `SET LOCAL`+commit
  revierte a **`''` (cadena vacía), NO a NULL** en conexiones del pool → la policy debe usar
  `NULLIF(current_setting('app.current_org', true), '')::uuid` o `''::uuid` lanza error.
  Ya aplicado (migración 0003). **Cualquier policy nueva debe seguir este patrón.**
- **Cuotas:** nada de aritmética `+30 días`; usar "mismo día del mes" y *clamp* a 29/30/31 → último día del mes (SRS §7.2).
- **Pagos:** webhook duplicado ⇒ sin doble pago ni doble comprobante; monto que no cuadra ⇒ **cola de conciliación**, nunca se descarta un pago (RNF-06); multi-cuota ⇒ FIFO sobre vencidas más antiguas.
- **Menores:** no se guarda alumno sin ≥1 tutor + `CONSENTIMIENTO`; datos médicos cifrados en reposo; auditar pagos manuales / cambios de monto / emisión de comprobantes (RNF-02/03).

### Gotchas de entorno / código (este slice)
- **Puertos ocupados en esta máquina:** 5432 (`languageacademy-db`), 5433 (`ipc-db`), 8000
  (un Django ajeno), 5173 (otro front). Usar los overrides de arriba (5434/8010/5180).
- **`JWT_SECRET` corto** avisa (PyJWT exige ≥32 bytes para HS256). En prod usar uno largo.
- **Seed corre como OWNER** (postgres bypassa RLS) a propósito; la **app** corre como
  `cantera_app` (RLS activa). No conectes la app como postgres.
- **npm install** se cuelga con el proxy TLS del equipo (`UNABLE_TO_VERIFY_LEAF_SIGNATURE`);
  workaround dev: `npm_config_strict_ssl=false`. CI/Docker deben usar una CA/registry confiable.
- **`Dockerfile.api` necesita** `alembic.ini` + `migrations/` (viven en la raíz, fuera del
  build context `backend/`): en dev se montan como volúmenes; para imagen autocontenida hay
  que extender el context (ver nota en `infra/Dockerfile.api`). El stack E2E se validó con
  procesos locales, **no** con `docker compose up` completo (build de imágenes pendiente).
- **Cosmético:** la categoría se muestra duplicada ("Sub-10 Principiante Principiante")
  porque `categoria.nombre` ya incluye el nivel y la UI añade `nivel` otra vez → pulir en frontend.
- **Drift a confirmar:** `inscripcion.monto_mensual` se serializa como número (no string);
  los tipos del frontend lo asumían string (su `formatMoney` acepta ambos, no bloquea).

## Where to look for things

| Necesitas… | Mira en… |
|------------|----------|
| Requisitos / reglas de negocio | `LATINASPORT_SRS_v2.md` |
| Diseño UI (pantallas, tokens, datos ejemplo) | `docs/design/design-system.md` |
| Metodología, roster, DoD, comandos | `CLAUDE.md` |
| Lógica de dominio, API, adaptadores, workers | `backend/app/` |
| Esquema físico, RLS, migraciones | `migrations/` + `alembic.ini` |
| UI admin/entrenador | `frontend/src/` |
| Docker, CI, env, despliegue worker | `infra/` |
| Spec del epic activo | `docs/specs/<epic>.md` (efímera) |
