---
name: before-merge
description: Aplícala antes de cerrar una fase o un epic en LATINASPORT. Es el gate de
  Definition of Done - arquitectura, RLS, tipos, tests, lint/build, verify, idempotencia,
  borrado de la spec y actualización del HANDOFF.
---
# Before merge — Definition of Done (gate de fase/epic)

Lo corre **main** (Trust but verify): no basta el reporte del agente. Revisa `git status`,
lee el `git diff` y ejecuta los checks **tú mismo**.

## Checklist por fase
- [ ] **Arquitectura en verde** — `cd backend && lint-imports` (el núcleo no importa
      adaptadores concretos). Si no existe aún, queda como TODO documentado en HANDOFF.
- [ ] **Aislamiento RLS verificado** — con el rol de app y SIN `app.current_org`, un SELECT
      sobre tabla tenant no devuelve filas de otro `org_id`. (db-dev deja evidencia.)
- [ ] **Typecheck sin errores nuevos** (delta vs baseline) — `cd backend && mypy .` y
      `cd frontend && npm run typecheck`.
- [ ] **Tests rápidos en verde** — `cd backend && pytest -q` y `cd frontend && npm run test`
      (salvo fallos baseline documentados en HANDOFF).
- [ ] **Lint + build en verde** si tocó esa área — `ruff check .` / `npm run lint` /
      `npm run build`.
- [ ] **git diff revisado por main** (no solo el reporte del agente).
- [ ] **UX confirmada en navegador** si la fase tocó UI visible (ver `run-local`).
- [ ] **Idempotencia probada** si tocó cobranza/webhooks — reenvío del mismo
      `transaccion_id` ⇒ sin doble pago ni doble comprobante.
- [ ] **Casos borde de cuotas** cubiertos si tocó facturación — 29/30/31 → último día,
      FIJO vs ANIVERSARIO, prorrateo del primer período.
- [ ] **Consentimiento/menores** respetado si tocó deportistas — no se persiste deportista sin
      tutor + consentimiento; sin datos sensibles en logs.

## Solo en la última fase del epic
- [ ] **Borra `docs/specs/<epic>.md` en ESE commit** (specs efímeras; sin `docs/archive/`).
- [ ] **Actualiza `docs/HANDOFF.md`**: stack/flags si cambiaron, "In-flight work" → estado
      real, "Recent decisions", "Known gotchas" nuevos. Mantenlo ≤ ~150 líneas (poda).

## Comando único de verificación (backend + frontend)
```
cd backend  && ruff check . && mypy . && lint-imports && pytest -q
cd frontend && npm run lint && npm run typecheck && npm run test && npm run build
```

## Si algo falla
Para. Reporta la causa raíz. **Nunca** saltes los gates de arquitectura/RLS/lint/tipos ni
desactives RLS, ni "comentes" un test para que pase. Un pago jamás se descarta; una tabla
tenant jamás queda sin política RLS.
