# Plan de trabajo en paralelo — LATINOSPORT

> **Documento de coordinación TEMPORAL.** Define cómo dividir el trabajo pendiente en
> **sesiones paralelas e independientes**, en ramas separadas, sin pisarse. Se borra cuando
> los tres epics aterricen en `main`. La verdad del proyecto sigue en `CLAUDE.md` + `docs/HANDOFF.md`.
>
> **Base de todas las ramas:** `origin/main` = `d8f5be5` (migraciones `0001→0011`).
> **Última actualización del plan:** 2026-06-07.

---

## 0. Alcance confirmado por el usuario

**Construir (en paralelo, 3 sesiones):**
- **A · Super Admin** — alta/gestión de escuelas (onboarding del SaaS). *El diseño técnico ya lo hizo `platform-architect`; va directo a spec + build.*
- **B · Gestión de Entrenadores** — CRUD de profesores **+ sus cuentas de login**, disciplinas a cargo, y elegir al entrenador al armar horarios.
- **C · Sucursales/Categorías (CRUD) + Recibo por WhatsApp** — gestionar sucursales y categorías (hoy **solo se listan**), y **enviar el recibo (PDF) por WhatsApp al confirmar el pago**.

**Descartado por ahora (NO construir):** Ficha de Rendimiento · ChatBot WhatsApp entrante · recordatorio de *clase* por WhatsApp.

---

## 1. Reglas de oro del trabajo en paralelo (LEER antes de empezar)

1. **Aislamiento por sesión.** Cada sesión trabaja en su **propio git worktree** (carpeta separada) + **su rama** + **su stack docker** (project name + puertos propios). **Nunca** toques el worktree/contenedores/puertos de otra sesión. *(Una rama NO aísla el árbol de trabajo; el worktree sí — lección del epic Egresos.)*
2. **Ramas** (todas parten de `origin/main` = d8f5be5): `epic/super-admin`, `epic/entrenadores`, `epic/sucursales-recibo`.
3. **Migraciones = el recurso compartido frágil (cadena Alembic).** Solo **A** y **B** crean migración. Ambas con `down_revision="0011"` durante el desarrollo. **`main` resuelve la cadena al integrar** (ver §6): A aterriza primero como `0012`; al aterrizar B, `main` ajusta su `down_revision` a `0012` → cadena lineal `0011→0012→0013`. **C no crea migración.**
4. **Archivos compartidos = append-only + `Edit` (NUNCA `Write`).** Ver §4 (matriz). `main` resuelve los conflictos triviales al merge (suelen ser líneas distintas añadidas).
5. **El núcleo de auth es EXCLUSIVO de la Sesión A.** Ninguna otra sesión toca `backend/app/core/tenant.py`, `backend/app/core/security.py`, ni `backend/app/api/v1/auth.py`.
6. **CI en verde antes de pushear** (ruff · mypy · lint-imports · pytest · front lint/typecheck/build). El backend rojo **bloquea el deploy a prod**.
7. **`main` integra.** Cada sesión pushea su rama y reporta. `main` revisa el diff, corre los gates, resuelve los shared files + la cadena Alembic, mergea en el **orden de integración** (§6) y borra la spec efímera de cada epic en su commit de cierre.
8. **Cada sesión corre su propio flujo SSS** (product-owner → spec efímera `docs/specs/<epic>.md` → `platform-architect` si hay riesgo → dev agents en paralelo → verify de main). Este doc le da a cada sesión su **alcance, fronteras y constraints**; la spec la escribe la sesión.

---

## 2. Stacks aislados (puertos por sesión)

| Sesión | Rama | project compose (`-p`) | DB | Redis | API | Web |
|---|---|---|---|---|---|---|
| A · Super Admin | `epic/super-admin` | `latinosport_superadmin` | **5436** | **6381** | **8012** | **5182** |
| B · Entrenadores | `epic/entrenadores` | `latinosport_entrenadores` | **5437** | **6382** | **8013** | **5183** |
| C · Sucursales+Recibo | `epic/sucursales-recibo` | `latinosport_sucursales` | **5438** | **6383** | **8014** | **5184** |

El dev principal usa `5434/6379/8010/5180` y hay contenedores `cantera-*` en `5434/6379`: **no usar esos**. Levantar BD con, p.ej.: `DB_PORT=5436 docker compose -p latinosport_superadmin -f infra/docker-compose.yml up -d --wait db`.

---

## 3. Migraciones (asignación)

| Sesión | ¿Migración? | Revisión | `down_revision` en desarrollo | Contenido |
|---|---|---|---|---|
| A | **Sí** | `0012_superadmin` | `0011` | tabla `plataforma_admin` (**sin RLS**) + `organizacion.estado` (`ACTIVA`/`SUSPENDIDA`) |
| B | **Sí** | `0013_entrenadores` | `0011` *(main lo ajusta a `0012` al integrar)* | `entrenador.disciplinas` (texto/estructura que defina el diseño de B) |
| C | **No** | — | — | Sucursales/Categorías = solo **CRUD** sobre tablas existentes (DELETE protegido si están en uso; sin columna nueva). Recibo-WhatsApp = **sin esquema**. |

---

## 4. Matriz de colisiones (archivos compartidos)

**Backend — append-only, `Edit`:**
- `backend/app/api/v1/__init__.py` (registrar router nuevo)
- `backend/app/models/__init__.py` (registrar modelo nuevo)
- `backend/app/core/config.py` (vars de entorno nuevas — solo A)

**Frontend — append-only, `Edit`:**
- `frontend/src/api/client.ts` · `frontend/src/api/types.ts`
- `frontend/src/components/shell/nav.ts` · `frontend/src/components/shell/Sidebar.tsx`
- `frontend/src/App.tsx` (rutas)

**EXCLUSIVO de A (nadie más los toca):** `backend/app/core/tenant.py`, `backend/app/core/security.py`, `backend/app/api/v1/auth.py`.

> Cada sesión **añade** sus líneas en los compartidos; `main` resuelve al merge. No reescribir el archivo entero.

---

## 5. Briefs por sesión

### Sesión A · Super Admin (gestión de escuelas / onboarding del SaaS)
**Rama:** `epic/super-admin` · **Migración:** `0012_superadmin`
**El diseño ya está hecho por `platform-architect`** — esta sesión va a product-owner (spec) + build directo. Defaults de producto (confirmados como base): impersonación **fuera**; **misma app** con área `/plataforma` gateada a `SUPERADMIN`; suspender = **bloquea login + pausa el cron** de esa escuela; **auditoría mínima sí** (log de crear/suspender/reactivar).

**Construir:**
- **Identidad:** tabla nueva `plataforma_admin` (email, password_hash, nombre, activo) **sin `org_id` y SIN RLS**. Modelo + migración `0012`.
- **Suspensión:** `organizacion.estado` (`ACTIVA`|`SUSPENDIDA`, default ACTIVA, CHECK).
- **Auth de plataforma:** `POST /api/v1/plataforma/login` → JWT con `role="SUPERADMIN"` **sin `org_id`**. Ajustar `get_current_user` para aceptar token sin `org_id` **solo** si `role=="SUPERADMIN"`; el login de escuelas sigue exigiendo `org_id`. Nueva dependencia `require_superadmin` que **NO** fija el GUC (→ el super admin no ve datos de negocio: fail-closed).
- **Endpoints** (router nuevo `plataforma.py`, `Depends(require_superadmin)`): `GET /plataforma/escuelas`, `POST /plataforma/escuelas` (crea org + primer admin fijando el GUC a la org nueva durante el INSERT del admin — patrón de `seed.py`/`pagos.py`, **sin BYPASSRLS**), `POST /plataforma/escuelas/{id}/suspender` y `/reactivar`.
- **Login de escuela:** rechazar si la org está `SUSPENDIDA` (en `auth.py`). *(Pausa del cron para orgs suspendidas en `workers/tasks.py`.)*
- **Bootstrap del 1er super admin:** comando `python -m app.seed_plataforma` (idempotente por email, lee `PLATFORM_ADMIN_EMAIL`/`PLATFORM_ADMIN_PASSWORD`). **Reemplaza el pendiente `create-admin`.**
- **Frontend:** consola `/plataforma` (login de plataforma + lista/crear/suspender escuelas), sesión/token separados del de escuela.
- **Infra:** `PLATFORM_ADMIN_EMAIL`/`PLATFORM_ADMIN_PASSWORD` en `.env.example`.

**Posee:** `core/tenant.py`, `core/security.py`, `api/v1/auth.py`, `api/v1/plataforma.py`, `services/plataforma.py`, `models/plataforma_admin.py`, `models/organizacion.py`, `seed_plataforma.py`, migración `0012`, consola frontend de plataforma.
**Hard constraints:** NUNCA dar BYPASSRLS al rol `latinosport_app` ni debilitar el RLS fail-closed por escuela. `require_superadmin` nunca fija el GUC. No tocar `frontend`/`backend` de las otras sesiones.

### Sesión B · Gestión de Entrenadores
**Rama:** `epic/entrenadores` · **Migración:** `0013_entrenadores`

**Construir:**
- **Migración/modelo:** añadir **`disciplinas`** al `entrenador` (texto o estructura que defina el diseño de B) para "disciplinas a cargo". *(`especialidad` ya existe.)*
- **Cuentas de entrenador (login):** servicio + endpoint ADMIN para **crear un entrenador = crea su `usuario`(role=ENTRENADOR) + su perfil `entrenador`** (email único, password inicial, especialidad, disciplinas). Reusar el hashing de `security.py` (sin modificar auth core) y el patrón de creación de usuarios del seed. CRUD: alta, edición, listar, baja (activo/inactivo).
- **API:** `GET /api/v1/entrenadores` (lista, para poblar selectores), `POST/PUT` (alta/edición), y lo que el CRUD requiera. Schemas Pydantic propios.
- **Horarios:** que `NuevoHorario` elija al entrenador de **una lista real** (`GET /entrenadores`) en vez del campo de texto actual.
- **Frontend:** pantalla **Entrenadores** (lista + alta/edición con especialidad y disciplinas), gateada a ADMIN; y el selector en horarios.

**Posee:** `models/entrenador.py`, `api/v1/entrenadores.py` (nuevo), `services/entrenador*.py`, `schemas/entrenador*.py`, migración `0013`, `api/v1/horarios.py` (solo el selector), `frontend/src/features/entrenadores/*`, y el cambio del selector en `frontend/src/features/horarios/NuevoHorario.tsx`.
**Hard constraints:** **No** tocar `core/tenant.py`/`security.py`/`auth.py` (crear `usuario` se hace por servicio, no modificando auth). No tocar las áreas de A ni de C. Crear entrenador respeta RLS (usuario es tenant: el INSERT corre bajo el `app.current_org` del admin que lo crea).

### Sesión C · Sucursales/Categorías (CRUD) + Recibo por WhatsApp
**Rama:** `epic/sucursales-recibo` · **Sin migración**

**Construir — Sucursales/Categorías:**
- Extender `api/v1/sucursales.py` y `api/v1/categorias.py` (hoy solo `GET`) con **`POST`/`PUT`/`DELETE`** (solo ADMIN). DELETE **protegido**: 409/400 si la sucursal/categoría está en uso (alumnos/categorías/horarios) — **no** borrar en cascada. Sin columna nueva (sin migración).
- **Frontend:** pantalla **Sucursales** (lista + alta/edición/baja) y gestión de **Categorías** (con `nivel` y `rango_edad`), gateadas a ADMIN.

**Construir — Recibo por WhatsApp:**
- Al **confirmar un pago** (efectivo inmediato; QR vía webhook existente), **enviar el recibo al tutor por WhatsApp** reusando el `WhatsAppPort` (mock-first) y el recibo PDF existente.
- **Decisión a resolver en el flujo de C (architect):** cómo entregar el PDF por WhatsApp dado que Meta no manda binarios arbitrarios sin media-upload/URL pública. **Recomendado:** mandar un **enlace** al recibo (requiere una **ruta pública/tokenizada** del PDF, ya que `/cobranza/comprobantes/{pago_id}.pdf` hoy exige auth) en un mensaje de plantilla. Mock-first: verificable sin credenciales.
- Idempotencia: no reenviar el mismo recibo dos veces (marcar envío).

**Posee:** `api/v1/sucursales.py`, `api/v1/categorias.py`, `services/*` de sucursal/categoría, `schemas/catalogo.py`, el servicio de envío de recibo (`services/recordatorios.py` o uno nuevo `services/recibo_envio.py`), `frontend/src/features/sucursales/*` (y categorías).
**Hard constraints:** **No** tocar `procesar_webhook`/`crear_pago_qr`/conciliación de pago (solo *engancharse* tras la confirmación para enviar el recibo). No tocar áreas de A ni de B. Reusar el `WhatsAppPort` y el adaptador existentes (no duplicar).

---

## 6. Orden de integración (lo hace `main`)

A y B se **desarrollan 100% en paralelo**; solo el **aterrizaje** se serializa por la cadena Alembic:

1. **A → `main`** (aplica `0012`). Gates + RLS (super admin sin GUC = 0 filas en tablas tenant; crear-escuela inserta el admin con el `org_id` correcto).
2. **B → `main`.** `main` ajusta `down_revision` de `0013` a `0012`, resuelve los shared files (router/model/nav/rutas). Gates.
3. **C → `main`.** Sin migración. Resuelve shared files. Gates (incl. que el recibo-WhatsApp no toca la conciliación de pago).

Cada merge: CI completo en verde + revisión de diff por `main` + actualización de `HANDOFF.md` + borrado de la spec efímera del epic. Tras los tres, se borra **este** documento.

---

## 7. Checklist de arranque para cada sesión

- [ ] Crear worktree + rama desde `origin/main`: `git worktree add ../SportSchool-<sesion> -b epic/<rama> origin/main`.
- [ ] Levantar stack aislado con los puertos de §2.
- [ ] `product-owner` escribe `docs/specs/<epic>.md` (alcance de §5).
- [ ] (A y C) `platform-architect` para las decisiones marcadas; (B) opcional.
- [ ] Dev agents en paralelo por fase. Respetar §1, §3, §4.
- [ ] Gates verdes → push de la rama → reportar a `main` para integrar en el orden de §6.
