# HANDOFF — LATINASPORT

> Fuente única de estado del proyecto (junto con `CLAUDE.md`). Se **actualiza al cerrar
> cada epic**. Máx ~150 líneas; poda lo viejo. Esto NO es un changelog — es un snapshot
> de "cómo está el mundo hoy".

_Última actualización: 2026-06-06 — epic **Egresos** construido y verificado E2E (4º epic), en rama `epic/egresos` (pendiente de merge a main)._

## Stack snapshot

- **Backend:** Python · FastAPI · SQLAlchemy · Pydantic → `backend/`
- **DB:** PostgreSQL + Row-Level Security (RLS) por `org_id`
- **Migraciones:** Alembic + políticas RLS → `migrations/`
- **Jobs:** Celery worker + beat (cron diario) → `backend/app/workers/`
- **Frontend:** React + Vite (SPA mobile-first) → `frontend/`
- **Infra:** Docker / docker-compose / CI → `infra/`
- **Integraciones:** OpenBCB (QR), WhatsApp, PDF, SIN (fase 2) — detrás de puertos/adaptadores.

**Estado actual:** cuatro epics entregados y verificados E2E:
1. **scaffolding + Alumnos**: login, lista, perfil (tabs + ficha médica por rol), RLS activa.
2. **Cobranza**: motor de cuotas (FIJO/ANIVERSARIO), pago **efectivo** y **QR** (sandbox
   OpenBCB) con **webhook idempotente** + cola `conciliacion_pendiente`, **comprobante PDF**,
   cron diario (Celery beat), **Panel de cobranza** (KPIs + morosidad) + Registrar pago (QR vivo).
3. **Asistencia**: tablas `sesion`/`asistencia`, API (categorías por rol, roster get-or-create,
   guardar **idempotente** por `(sesion_id,alumno_id)`, historial), y pantalla **Tomar asistencia**
   (toggles Presente/Ausente, contadores en vivo, Guardar, mobile-first). Entrenador ve solo sus
   sucursales. Probado en navegador + API: marcar → guardar → recargar refleja.
4. **Egresos** (RF-FIN-07): tabla `egreso` (tenant, RLS NULLIF) + migración `0005`; API
   `/egresos` **solo ADMIN** (listar con filtros sucursal/categoría/fechas + `total_monto` del
   filtro, alta auditada con `registrado_por`), y pantalla **Egresos** (lista + filtros + total
   Bs + alta, gateada a ADMIN). Verificado API + navegador. En rama `epic/egresos` (pendiente merge).

Próximos epics candidatos (SRS): **Muro de avisos** (RF-COM-01),
**Reportes** (ingresos/asistencia, RF-COM-02/03), y fase 2 (chatbot WhatsApp, portal tutor
passwordless, facturación SIN, **OpenBCB real** cuando haya onboarding BCB).

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

**Egresos** entregado en rama `epic/egresos`, **pendiente de merge a main** por la sesión
principal (su commit de cierre borra `docs/specs/egresos.md`). *(En paralelo se construyó
**Reportes** en otra sesión/rama — su estado lo reporta esa sesión. Al mergear ambas ramas,
**reconciliar los archivos compartidos**: `backend/app/api/v1/__init__.py`,
`backend/app/models/__init__.py`, `backend/app/seed.py`, `frontend/src/App.tsx`,
`frontend/src/components/shell/nav.ts` y `Sidebar.tsx`, `frontend/src/api/client.ts` y `types.ts`,
y este HANDOFF — ambos epics hicieron edits append; Alembic: dos hijos de `0004` → posible merge
de heads.)* Remoto `imertetsu/sport-school` (push vía `http.sslBackend=schannel` por el proxy TLS
corporativo). Migraciones: 0001→0005 (egresos = `0005`). Al abrir el próximo epic, `product-owner`
crea `docs/specs/<epic>.md`.

## Recent decisions

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
