---
name: add-feature
description: Aplícala al agregar una funcionalidad a LATINASPORT. Define el orden real de
  capas/módulos (contrato → datos → dominio → API → frontend) y qué agente toca cada paso,
  para no romper RLS, los adaptadores ni la idempotencia.
---
# Agregar una feature a LATINASPORT (orden de capas)

El stack es FastAPI + SQLAlchemy + PostgreSQL/RLS + Alembic + React/Vite. Una feature casi
nunca vive en una sola capa; síguelas en este orden y reparte por agente. Cada feature
arranca con una **spec efímera** (`product-owner` → `docs/specs/<epic>.md`) y, si tiene
riesgo arquitectónico, un **plan** del `platform-architect`.

## 0. Spec y contrato (antes de tocar código)
1. `product-owner` escribe `docs/specs/<epic>.md` (objetivo, alcance MVP, RF tocados, fases).
2. Si hay decisión técnica dura (RLS, nuevo adaptador, motor de cuotas, idempotencia) →
   `platform-architect` define el **contrato compartido**: firmas de puertos, esquema
   Pydantic y forma de tabla. **Sin contrato no se paraleliza.**

## 1. Datos / esquema  → db-dev (+ modelo: backend-dev)
1. `backend-dev` define/ajusta el modelo SQLAlchemy en `backend/app/models/`.
2. `backend-dev` se **detiene** y entrega a `db-dev`: éste crea la migración Alembic
   (`cd backend && alembic revision --autogenerate -m "<msg>"`), **añade a mano la política
   RLS** (`ENABLE/FORCE ROW LEVEL SECURITY` + `CREATE POLICY … USING/WITH CHECK`) y
   constraints/índices (recuerda `UNIQUE` en `PAGO.transaccion_id`).
3. `db-dev` aplica (`alembic upgrade head`) y **verifica RLS** (sin contexto → 0 filas).

## 2. Dominio  → backend-dev
- Lógica pura y testeable en `backend/app/domain/` (p.ej. motor de cuotas: "mismo día del
  mes", clamp 29/30/31, FIJO/ANIVERSARIO). Si toca un proveedor, define/usa el **puerto** en
  `app/domain/ports/` — **nunca** importes el adaptador concreto desde el dominio.

## 3. Adaptadores  → backend-dev
- Implementa el puerto en `backend/app/adapters/` (OpenBCB/WhatsApp/PDF/SIN). Para pagos:
  webhook **idempotente** por `transaccion_id`, validación de referencia/monto, cola de
  conciliación para lo que no cuadra.

## 4. API / Workers  → backend-dev
- Router en `backend/app/api/v1/<recurso>.py` con la **dependencia de tenant** (setea
  `SET LOCAL app.current_org` en la transacción). Webhooks en `app/api/v1/webhooks/`.
- Jobs de cron en `backend/app/workers/` (idempotentes).
- Esto **fija/extiende el contrato OpenAPI** que consumirá el frontend.

## 5. Frontend  → frontend-dev
- Pantallas/flows en `frontend/src/features/<dominio>/`, consumiendo el **cliente tipado**
  generado del OpenAPI. Respeta alcance por rol y formato de moneda/fecha por organización.
- Si el endpoint/campo no existe → **handoff a backend-dev**, no parchees el backend.

## 6. Infra (si aplica)  → infra-dev
- Nueva env var/servicio/worker → `infra/` y `.env.example`. Coordina el rol de BD no
  superusuario con `db-dev`.

## Paralelizar
Una vez los **contratos están definidos** (paso 0), las capas sin archivos compartidos van
en **paralelo** (p.ej. frontend contra un contrato API ya fijado mientras backend lo
implementa). Sigue el árbol de decisión de paralelismo de `CLAUDE.md`.

## Al cerrar el epic
Corre `before-merge`. En la **última fase**, borra `docs/specs/<epic>.md` en ese mismo
commit y actualiza `docs/HANDOFF.md`.
