---
name: test-and-lint
description: Aplícala tras cambiar código en LATINASPORT para saber el check mínimo según el
  área tocada. Tabla "área cambiada → comando" con los comandos reales del stack
  (FastAPI/Alembic/React-Vite).
---
# Test & Lint — qué correr según lo que tocaste

> Comandos **estándar del stack**; confírmalos/píntalos en `docs/HANDOFF.md` una vez exista
> el scaffolding. Corre el check **mínimo** del área tocada antes de dar la fase por hecha;
> el gate completo está en `before-merge`.

| Área cambiada | Check mínimo |
|---------------|--------------|
| `backend/app/domain/`, `app/adapters/`, `app/api/`, `app/workers/` | `cd backend && ruff check . && mypy . && lint-imports && pytest -q` |
| Cobranza / webhooks (pagos, conciliación) | lo anterior **+** test de **idempotencia** (webhook duplicado ⇒ sin doble pago/comprobante) |
| Motor de cuotas (`app/domain/…cuota…`) | `cd backend && pytest -q tests/domain` (casos borde: 29/30/31, FIJO vs ANIVERSARIO, prorrateo) |
| Modelos SQLAlchemy (`backend/app/models/`) | lo de backend **+ handoff a db-dev** para la migración/RLS |
| `migrations/`, `alembic.ini` (db-dev) | `cd backend && alembic upgrade head && alembic downgrade -1 && alembic upgrade head` **+ verificación RLS** (sin contexto ⇒ 0 filas) |
| `frontend/src/` | `cd frontend && npm run lint && npm run typecheck && npm run test` |
| UI visible | lo de frontend **+** confirmar UX en navegador (main, no solo el reporte) |
| `frontend/package.json` o build | `cd frontend && npm run build` |
| `infra/`, Dockerfiles, compose, CI | `docker compose -f infra/docker-compose.yml config` y `up -d --build` + `docker compose ps` |
| `docs/` | sin checks (Read para coherencia; HANDOFF ≤ ~150 líneas) |

## Invariantes que un test "verde" no garantiza por sí solo
- **RLS**: que `pytest` pase no prueba aislamiento. Incluye un test que, con el rol de app y
  sin `app.current_org`, NO devuelva filas de otro `org_id`.
- **Idempotencia**: reenvía el mismo `transaccion_id` y verifica que no se duplica pago ni
  comprobante.
- **Tipos delta**: cuenta errores nuevos de `mypy`/`tsc` vs baseline (no totales).

## Baseline
Si hay fallos preexistentes conocidos, deben estar documentados en `docs/HANDOFF.md`; un
fallo **no** documentado bloquea.
