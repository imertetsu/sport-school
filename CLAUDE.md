# LATINASPORT

SaaS **multi-tenant** para gestión de escuelas/clubes deportivos (deportistas, asistencia,
cobranza automatizada y comunicación). Primer mercado: Bolivia; diseñado para cruzar
fronteras sin reescribir el núcleo. Documento de requisitos: `LATINASPORT_SRS_v2.md`.

## Stack

- **Backend:** Python · FastAPI · SQLAlchemy · Pydantic — en `backend/`
- **Base de datos:** PostgreSQL con **Row-Level Security (RLS)** por `org_id`
- **Migraciones:** Alembic + políticas RLS — en `migrations/`
- **Jobs:** Celery (worker + beat) para el cron diario de cuotas/recordatorios — en `backend/app/workers/`
- **Frontend:** React + Vite (SPA mobile-first, admin/entrenador) — en `frontend/`
- **Infra:** Docker / docker-compose / CI — en `infra/`
- **Integraciones (puertos+adaptadores):** OpenBCB (QR), WhatsApp (notificaciones), PDF (comprobantes), SIN (factura, fase 2)

> El repo arranca **vacío**. El primer epic es el *scaffolding*; hasta que exista código,
> los comandos de abajo son el **toolchain estándar del stack** (a confirmar/fijar en ese
> epic). La verdad operativa de comandos vive en `docs/HANDOFF.md`.

## Comandos (estándar del stack — fijar en el epic de scaffolding)

| Área | Comando |
|------|---------|
| Instalar backend | `cd backend && python -m venv .venv && pip install -e ".[dev]"` |
| Dev backend | `cd backend && uvicorn app.main:app --reload` |
| Test backend | `cd backend && pytest -q` |
| Lint backend | `cd backend && ruff check .` |
| Format backend | `cd backend && ruff format .` |
| Typecheck backend | `cd backend && mypy .` |
| Validación arquitectura | `cd backend && lint-imports` *(import-linter; contratos núcleo↛adaptadores)* |
| Migración nueva | `cd backend && alembic revision --autogenerate -m "<msg>"` |
| Aplicar migraciones | `cd backend && alembic upgrade head` |
| Instalar frontend | `cd frontend && npm install` |
| Dev frontend | `cd frontend && npm run dev` |
| Build frontend | `cd frontend && npm run build` |
| Test frontend | `cd frontend && npm run test` *(vitest)* |
| Lint frontend | `cd frontend && npm run lint` *(eslint)* |
| Typecheck frontend | `cd frontend && npm run typecheck` *(tsc --noEmit)* |
| Levantar todo (local) | `docker compose -f infra/docker-compose.yml up -d` |
| Worker / beat | `cd backend && celery -A app.workers.celery_app worker` · `... beat` |

## Agentes y skills

- Agentes en `.claude/agents/` — un **dueño por carpeta, sin solape** (ver tabla en la sección SSS).
- Skills en `.claude/skills/`: `add-feature`, `test-and-lint`, `run-local`, `before-merge`.

---

## Working methodology — SSS (Spec → Sketch → Ship)

Pensada para desarrollo con agentes de IA: rápidos, paralelos y sin memoria.

### 5 pilares

1. **Specs efímeras.** Al abrir un epic, `product-owner` escribe `docs/specs/<epic>.md`. La
   spec vive **solo** mientras el epic está en vuelo; cuando aterriza el último commit del
   epic, la spec **se borra EN ese mismo commit**. Sin carpeta `archive/`. La memoria
   institucional son el código, los commits y los tests.
2. **Envío single-pass por fase.** La unidad de trabajo es una **fase de la spec**, no una
   ventana de tiempo. Una fase = uno (o pocos) commits. Nunca acumules trabajo a medias.
3. **Hard constraints en cada brief.** Todo prompt a un agente termina con una sección
   **"Hard constraints"** con lo que NO se debe tocar. Usa **Edit (no Write)** en archivos
   compartidos. Los agentes driftean sin pines.
4. **Paralelo por defecto.** Si dos unidades no comparten archivo **Y** su contrato ya está
   definido, lánzalas en `Agent` calls **paralelos en un solo mensaje**. Serial solo si hay
   dependencia real, y justifícalo.
5. **Trust but verify.** El agente reporta lo que **intentó**. La sesión principal revisa
   `git status`, lee el diff y corre los gates **antes** de dar algo por hecho.

### Roster (dueño único por carpeta)

| Agente | Tipo | Posee | Nunca toca |
|--------|------|-------|------------|
| `prompt-engineer` | transversal (read-only) | — (refina y devuelve el prompt) | todo (no escribe) |
| `product-owner` | transversal | `docs/` | código |
| `platform-architect` | transversal (read-only) | — (planifica) | todo (no edita) |
| `backend-dev` | dev | `backend/` | `frontend/`, `migrations/`, `infra/` |
| `frontend-dev` | dev | `frontend/` | `backend/`, `migrations/`, `infra/` |
| `db-dev` | dev | `migrations/`, `alembic.ini` | `backend/` app, `frontend/`, `infra/` |
| `infra-dev` | dev | `infra/`, Dockerfiles, `.github/`, `docker-compose.yml`, `.env.example` | `backend/`, `frontend/`, `migrations/` |

**Contratos compartidos (Edit, nunca Write; cambio cruzado → handoff y parar):** esquema
OpenAPI/Pydantic (backend produce → frontend consume), `Base.metadata` SQLAlchemy (backend
define → db-dev migra), `alembic.ini`/`migrations/env.py`, `docker-compose.yml`/`.env.example`.

### Pipeline

```
usuario → main → prompt-engineer (refina) → main → product-owner → spec
                     → platform-architect (opcional, decisiones técnicas duras)
                     → agentes en paralelo por fase → main verifica → commit
                       (borra la spec al cerrar el epic)
```

### Árbol de decisión de paralelismo

```
¿Tocan archivos compartidos? → Sí → SERIAL.
→ No → ¿La salida de uno es entrada del otro? → Sí → SERIAL.
       → No → ¿Hay contrato compartido (API/esquema/tipo)?
              → Ya definido → PARALELO.
              → Sin definir → DEFINIRLO primero (1 agente o main), luego PARALELO.
              → Sin contrato → PARALELO sin más.
```

### Epics multi-sesión (tareas largas) — integración en `staging`

Cuando una tarea es **demasiado grande** para una sola spec (varias áreas, dependencias
entre piezas, trabajo de varios días en paralelo), se parte en **Sesiones** coordinadas e
integradas en una rama `staging`, **NO en `main`**:

1. **Documento de coordinación.** Se crea `docs/specs/<epic>-roadmap.md` que parte el epic
   en Sesiones (S1, S2, …): qué cubre cada una, **dependencias** entre ellas, **propiedad
   de archivos**, **contratos compartidos** y orden. No es una spec efímera de fase: es el
   mapa del epic completo. Cada sesión, además, escribe su propia spec efímera
   `docs/specs/<sesion>.md`.
2. **Una rama (y worktree) por sesión.** Cada sesión trabaja en su **rama propia**
   (`feat/<sesion>`), en su **propio worktree** (una rama NO aísla el árbol de trabajo;
   compartir el dir principal entre sesiones las pisa), en paralelo cuando las dependencias
   lo permiten.
3. **`staging/<epic>` es el ÚNICO punto de integración.** Las ramas de sesión **NO se
   mergean a `main`**: se mergean a la rama **`staging/<epic>`** (creada desde `main`). Una
   sesión que depende de otra (p. ej. S4 reusa S2+S3) se construye **sobre `staging`**, que
   ya tiene a las anteriores — no espera a que cada una llegue a `main`.
4. **`main` solo al final, una sola vez.** Cuando **todas** las sesiones están terminadas,
   integradas en `staging` **y el conjunto funciona** (gates verdes + verificación E2E
   sobre `staging`), se hace **un único merge `staging → main`** → un solo deploy, un solo
   `pg_dump` de respaldo de prod si toca datos reales.
5. **Limpieza en el merge final.** En ese merge se **borra el documento de coordinación**
   (`<epic>-roadmap.md`) y las specs efímeras de las sesiones; se actualiza
   `docs/HANDOFF.md`. Sin carpeta `archive/`.

**Por qué `staging` y no "mergeando entre medias a `main`":** `main` queda estable y
desplegable durante todo el epic; las migraciones del epic se aplican a prod **una sola
vez** (al final, con respaldo), no N veces; y se evita que las sesiones aterricen en `main`
en orden arbitrario (S3 antes que S2, etc.).

### Reparto de decisiones

Las decisiones de **producto/alcance** se escalan al usuario. Las decisiones **puramente
técnicas** (organización de archivos dentro de las reglas de arquitectura, parámetros de
performance, fixtures, cortes MVP-vs-v2 técnicos) las dueñan los agentes.

### Definition of Done por fase

- Validación de arquitectura en verde (import-linter: núcleo no importa adaptadores concretos).
- **Aislamiento RLS verificado**: query sin contexto de tenant no devuelve filas de otro `org_id`.
- Typecheck sin errores nuevos (delta vs baseline: `mypy` / `tsc`).
- Tests rápidos en verde (salvo fallos baseline documentados en HANDOFF).
- Lint + build en verde si tocó esa área.
- `git diff` revisado por **main** (no solo el reporte del agente).
- UX confirmada en navegador si la fase tocó UI visible.
- Si tocó cobranza: **idempotencia** del webhook probada (webhook duplicado ⇒ sin doble pago/comprobante).
- Si fue la **última fase del epic**: la spec se borra en ese commit.
- `docs/HANDOFF.md` actualizado con el nuevo estado.

### Anti-patrones

Acumular specs viejas "por si acaso"; carpeta `docs/archive/`; sprints/standups/story
points; specs gigantes para features pequeñas; saltarse el verify; dejar que el agente
defina el alcance.

### Fuente única de estado — `docs/HANDOFF.md`

Único doc persistente además de este `CLAUDE.md`. Snapshot que se **actualiza al cerrar
cada epic**. Secciones: stack, flags/config, trabajo en vuelo, decisiones recientes,
gotchas, dónde mirar. Máx ~150 líneas. Lo viejo se poda.
