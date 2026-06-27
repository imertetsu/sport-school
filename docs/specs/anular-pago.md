# Epic: anular-pago

> **Anular pago en efectivo registrado por error** (reversa CON rastro, nunca borrado) +
> **lista de pagos buscable** como punto de acceso. El ADMIN ve la lista de pagos, pulsa
> **"Anular"** sobre un pago de caja, da un **motivo obligatorio**, y el sistema **devuelve la
> cuota a cobrable** (PENDIENTE/VENCIDO/PARCIAL recomputado) y **deshace el saldo a favor** que
> ese pago generó — para luego registrar el pago correcto. **Solo `metodo=='EFECTIVO'`**; los
> QR/conciliados NO se anulan (no se toca la conciliación OpenBCB). Reversa = estado `ANULADO`
> + motivo + quién + cuándo (RNF-02/03). Spec **efímera**: se borra en el commit que cierra el
> epic (SSS, pilar 1).

## Objetivo y valor
Dar al **ADMIN** una salida limpia cuando registra un pago en efectivo **por error** (monto
equivocado, deportista equivocado, doble tecleo): en vez de quedar atrapado con una cuota
marcada pagada y un crédito fantasma, **anula** el pago (con auditoría completa) y la cuota
**vuelve a ser cobrable** para registrar el pago correcto. El acceso es una **lista de pagos
buscable** (vista nueva), que de paso da visibilidad de toda la caja de la escuela. Beneficia
al ADMIN (corrige errores sin tocar la BD, sin perder rastro) y a la integridad contable (cero
pagos perdidos, cero borrados físicos).

## Alcance MVP / Fuera de alcance

### En alcance (MVP)
- **Anular un pago efectivo CONFIRMADO**: reversa atómica con rastro (`estado='ANULADO'` +
  motivo + `anulado_por` + `anulado_en`). Nunca borrado físico.
- La anulación **revierte las cuotas** del pago (deshace `monto_pagado` aplicado vía
  `pago_cuota`, recomputa el estado de cada cuota → cobrable) y **revierte el crédito** que el
  pago generó/consumió (saldo a favor exacto).
- **Lista de pagos buscable** (vista nueva + endpoint `GET /cobranza/pagos`): punto de acceso al
  botón **"Anular"**, paginada, scoped por RLS, deportista en MAYÚSCULAS.
- **Modal de anulación** con motivo **obligatorio** + confirmación; tras anular, refresca la lista.
- **Solo ADMIN**. Solo `metodo=='EFECTIVO'`.

### Fuera de alcance (NO en este epic)
- **Anular pagos QR / conciliados** (`metodo!='EFECTIVO'`): RECHAZO (422). No se toca la
  conciliación OpenBCB ni la cola `conciliacion_pendiente`.
- **Cascada de anulaciones**: si el crédito que generó el pago ya fue consumido por un pago
  posterior, se **BLOQUEA** (409) — el admin anula primero el posterior. NO se anula en cascada.
- **Re-emitir / anular el recibo PDF**: el PDF ya gatea `estado!='CONFIRMADO'` → 404 tras anular;
  no se re-numera ni se borra `numero_recibo`.
- **Notificación al tutor** al anular (WhatsApp/PDF): NO se envía nada al anular.
- **Filtros avanzados / búsqueda full-text** de la lista: MVP = lista paginada simple (filtro
  opcional por estado a criterio del backend-dev). Búsqueda por nombre/fecha = follow-up.
- **Editar un pago** (corregir monto in-place): no existe; el flujo es anular + re-registrar.
- **Aviso de sobrepago al registrar** ("pagás de más, quedará saldo a favor"): ver decisión
  pendiente, fuera de este epic.

## Reglas de negocio (RF / SRS §)
- **SRS §4.1 / RNF-01 (multi-tenant, RLS por `org_id`):** anular y listar van **scoped por RLS**
  al `org` del token. Un pago de **otra org es invisible** → anularlo da **404** (no 403: no
  existe para este tenant). La lista solo trae pagos del org en contexto.
- **SRS §7–§8 (cobranza, estados de cuota):** al anular, cada cuota del pago se recomputa con el
  helper de estado existente → vuelve a **PENDIENTE / VENCIDO / PARCIAL** según corresponda (es
  cobrable de nuevo). El invariante de caja se mantiene:
  `Σ(pago_cuota.monto_aplicado de pagos VIVOS) == cuota.monto_pagado`.
- **RNF-02 / RNF-03 (auditoría, datos sensibles):** **nunca** borrado físico. La anulación
  **audita** motivo + quién (`anulado_por`) + cuándo (`anulado_en`). El pago anulado queda como
  registro histórico (rastro).
- **RNF-05/06 (idempotencia / nunca se pierde un pago):** anular un pago **ya ANULADO** es
  **idempotente** (200, sin doble reversa). Anular **no descarta** nada: revierte con exactitud
  el crédito (`credito_generado`/`credito_aplicado` persistidos por pago).
- **Atomicidad:** toda la reversa ocurre **dentro de la tx del request** (cuotas + puente +
  crédito + estado del pago). Si algo falla, no queda a medias. Anti-carrera: `SELECT ... FOR
  UPDATE` del pago.
- **NO se toca el QR/OpenBCB:** solo `metodo=='EFECTIVO'` es anulable; el resto rechaza. La
  conciliación bancaria queda intacta.

---

## Contratos compartidos (CONGELADOS — verificados contra el código por el arquitecto)
> Permiten paralelizar db / backend / frontend sin solape de archivos. **Edit (no Write)** en los
> compartidos existentes (`app/models/pago.py`, `app/api/v1/cobranza.py`, OpenAPI). Cambio cruzado
> ⇒ handoff y parar. **Head real de migraciones = 0024** (verificado: `0024_deportista_mayusculas_ci_cero.py`).
> CHECK actual `ck_pago_estado` (0002) = `estado IN ('PENDIENTE','CONFIRMADO','FALLIDO')` (SIN `ANULADO`).

### C1 — Migración **0025** (db-dev) — `0025_anular_pago.py`, `down_revision="0024"`
Sobre la tabla `pago` (YA tiene RLS/GRANTs desde 0002 → **NO** re-habilitar RLS, **NO** re-GRANT;
patrón 0010 add-column sin re-RLS). Añade columnas + amplía el CHECK:
- `motivo_anulacion` TEXT NULL
- `anulado_por` UUID NULL — FK `usuario.id` ON DELETE SET NULL
- `anulado_en` TIMESTAMPTZ NULL
- `credito_generado` NUMERIC(10,2) NOT NULL DEFAULT 0  (persiste el sobrepago→crédito de cada
  pago, para revertir el saldo a favor con exactitud)
- **Ampliar el CHECK** (patrón 0009 con `ck_cuota_estado`): `DROP CONSTRAINT ck_pago_estado` +
  `CREATE` `ck_pago_estado` = `estado IN ('PENDIENTE','CONFIRMADO','FALLIDO','ANULADO')`.
- `downgrade`: restaurar el CHECK original `('PENDIENTE','CONFIRMADO','FALLIDO')` + drop de las 4
  columnas. **Documentar** (como 0009 con PARCIAL) que filas con `estado='ANULADO'` romperían el
  CHECK restaurado al hacer downgrade.

### C2 — Modelo `Pago` (backend-dev, **Edit** `app/models/pago.py`) — espejo EXACTO de 0025
4 columnas nuevas:
- `motivo_anulacion: Mapped[str | None]`
- `anulado_por: Mapped[uuid.UUID | None]` (FK `usuario.id`)
- `anulado_en: Mapped[datetime | None]` (timezone-aware)
- `credito_generado: Mapped[Decimal]` (`server_default` `'0'`)
- Comentario de estado: `# PENDIENTE | CONFIRMADO | FALLIDO | ANULADO`.

### C3 — Servicio (backend-dev, `app/services/pagos.py`)
`def anular_pago(db, *, org_id, pago_id, anulado_por, motivo, hoy=None) -> Pago` —
**inverso de `_aplicar_pago_a_cuotas`**. **Reusa** los helpers existentes (NO duplicar
FIFO/estado/crédito): `_cuotas_de_pago`, `_estado_destino`, `saldo_credito_inscripcion`,
`_upsert_credito`. Algoritmo:
1. **Cargar** el pago bajo RLS (recomendado `SELECT ... FOR UPDATE`, anti-carrera). Validar:
   - no existe → `PagoError("no_encontrado")` (→404).
   - `metodo != 'EFECTIVO'` → `PagoError("no_anulable_qr")` (→422).
   - `estado == 'ANULADO'` → **no-op idempotente**: devuelve el pago tal cual (→200).
   - `estado in ('PENDIENTE','FALLIDO')` → `PagoError("estado_no_anulable")` (→422).
   - solo `estado == 'CONFIRMADO'` procede.
2. **Guard crédito consumido:** si `pago.credito_generado > 0` y
   `saldo_credito_inscripcion(insc) < pago.credito_generado` → `PagoError("credito_consumido")`
   (→409, "anulá primero el pago posterior"). NO cascada.
3. **Revertir cuotas:** por cada fila `pago_cuota`: `cuota.monto_pagado -= pc.monto_aplicado`;
   `cuota.estado = _estado_destino(cuota, hoy)`; **borrar** la fila puente `pago_cuota`.
4. **Revertir crédito:** `nuevo_saldo = saldo_actual − pago.credito_generado + pago.credito_aplicado`
   vía `_upsert_credito` (respeta el CHECK `saldo >= 0`).
5. **Marcar el pago:** `estado='ANULADO'`, `motivo_anulacion=motivo`, `anulado_por`,
   `anulado_en = now(UTC)`. **NO** tocar `numero_recibo` (el PDF ya gatea `estado!='CONFIRMADO'`
   → 404). **NO** enviar WhatsApp ni generar PDF al anular.
- **Edición de 1 línea en `registrar_pago_efectivo`:** persistir el remanente del sobrepago en el
  campo nuevo: `pago.credito_generado = <el valor que hoy se calcula y va al crédito>` (hoy se
  computa pero no se guarda por pago). **No cambia el contrato externo** salvo el campo nuevo.

### C4 — Endpoints API (backend-dev, **Edit** `app/api/v1/cobranza.py`) — ambos `require_role("ADMIN")`, RLS
**Anular:**
`POST /api/v1/cobranza/pagos/{pago_id}/anular`, body `AnularPagoIn {motivo: str (min_length=1)}`
(vacío → 422). Mapeo `PagoError` → HTTP: `no_encontrado`→404, `no_anulable_qr`→422,
`estado_no_anulable`→422, `credito_consumido`→409; ya ANULADO → 200 idempotente. → `PagoAnuladoOut`.

**Lista (NUEVO — punto de acceso):**
`GET /api/v1/cobranza/pagos?page=1&page_size=20`, scoped por RLS. Orden `created_at DESC` (más
reciente primero). → `PagosListOut {items: list[PagoListItem], total, page, page_size}`.
`PagoListItem`:
```
PagoListItem = {
  id, fecha: datetime (= created_at), metodo, estado,
  monto: Decimal,
  deportista_nombre: str | null,   # vía _deportista_de_cuotas; va en MAYÚSCULAS
  numero_recibo: str | null,
  anulable: bool,                   # = (metodo == 'EFECTIVO' and estado == 'CONFIRMADO')
  motivo_anulacion: str | null,
  anulado_en: datetime | null,
}
```
(Paginación/filtros = decisión técnica del backend-dev; MVP: lista paginada simple, sin filtros,
o con filtro opcional por estado.)

### C5 — Schemas Pydantic (backend-dev, `app/schemas/cobranza.py`)
- `AnularPagoIn {motivo: str (min_length=1)}`
- `CuotaRevertida {cuota_id, saldo_restante: Decimal, estado: str}`
- `PagoAnuladoOut {id, estado: 'ANULADO', motivo_anulacion, anulado_en: datetime,
  credito_revertido: Decimal, cuotas_revertidas: list[CuotaRevertida]}`
- `PagoListItem` y `PagosListOut` (ver C4).

### C6 — Frontend (frontend-dev)
- **Vista nueva "Pagos"** (lista paginada de `GET /cobranza/pagos`): por cada pago muestra
  deportista, monto, método, estado, fecha, N° recibo. Si `anulable` → botón **"Anular"**; si ya
  anulado → muestra "Anulado" + motivo. **Solo ADMIN**. Ubicación: ruta nueva en el nav, junto a
  Cobranza. **Reusa el patrón de listas existentes** (`DataTable`/tablas del repo).
- **Modal de anulación**: motivo **obligatorio** + confirmación; al confirmar llama `anularPago`.
  Tras anular, **refresca la lista** (la cuota vuelve a cobrable).
- `frontend/src/api/types.ts`: ampliar `EstadoPago` con `'ANULADO'`; añadir `AnularPagoBody
  {motivo}`, `CuotaRevertida`, `PagoAnuladoOut`, `PagoListItem`, `PagosListOut`.
- `frontend/src/api/client.ts`: `anularPago(pagoId, motivo, signal?)` y
  `listarPagos(page, pageSize, signal?)`.

### Contratos compartidos (Edit, nunca Write)
`app/models/pago.py` (`Base.metadata` ↔ migración 0025), `app/api/v1/cobranza.py` (backend
produce → frontend consume), **OpenAPI** (shapes de `PagoListItem`/`PagoAnuladoOut`). Cambio
cruzado ⇒ handoff y parar.

---

## Fases (cada fase = uno o pocos commits)

### Fase 1 — Implementación (PARALELO; contratos C1–C6 congelados, sin solape de archivos)
Las tres áreas no comparten archivo entre sí y los contratos están definidos → **paralelo**:
- **db-dev** — `migrations/versions/0025_anular_pago.py` (C1): 4 columnas + ampliar `ck_pago_estado`
  con `ANULADO` (patrón 0009 DROP+CREATE), sin re-RLS / sin re-GRANT (patrón 0010); `downgrade`
  documentado.
- **backend-dev** — **Edit** `app/models/pago.py` (4 cols, C2) · `app/services/pagos.py`
  (`anular_pago` + 1 línea en `registrar_pago_efectivo`, C3) · **Edit** `app/api/v1/cobranza.py`
  (2 endpoints, C4) · `app/schemas/cobranza.py` (C5) · tests en `backend/tests/`.
- **frontend-dev** — vista de pagos + modal + `api/types.ts` + `api/client.ts` + ruta en el nav (C6).
> El modelo (C2) es contrato compartido con la migración (C1): db-dev migra a mano sobre el
> esquema congelado (no autogenera ciego). Si el modelo y 0025 divergen → handoff y parar.

### Fase 2 — Verificación E2E (main, serial)
- **Aplicar 0025** sobre la BD local (rol OWNER) → `alembic upgrade head` llega a 0025.
- **Gates verdes:** `pytest` (con BD; nuevos tests + sin romper baseline), `ruff`, `mypy`,
  **import-linter** (`anular_pago` vive en `services`, no en `domain`), `npm build`/`lint`/
  `typecheck` del front.
- **Verificación E2E** de los criterios de aceptación (abajo): anular efectivo, rechazo QR,
  inexistente 404, idempotencia, crédito consumido 409, RLS, multi-cuota, lista correcta.
- **Idempotencia** del flujo de reversa (anular 2x → sin doble reversa).
- **UX** confirmada en navegador (la vista de pagos toca UI visible).
- **Última fase del epic** ⇒ borrar **esta spec** en ese commit + actualizar `docs/HANDOFF.md`.

---

## Criterios de aceptación (verificables — incluyen casos borde de dominio)
- **C-Anular-OK:** anular un pago efectivo **CONFIRMADO** → `estado='ANULADO'` con
  motivo/quién/cuándo; sus cuotas vuelven a **PENDIENTE/VENCIDO/PARCIAL** (recomputado vía
  `_estado_destino`) y son **cobrables**; las filas `pago_cuota` se borran; el crédito se revierte
  **exacto**. `PagoAnuladoOut` lista `cuotas_revertidas` y `credito_revertido`.
- **C-QR-rechazo:** anular un pago con `metodo!='EFECTIVO'` (QR/conciliado) → **422**
  (`no_anulable_qr`). La conciliación OpenBCB / `conciliacion_pendiente` no se tocan.
- **C-404:** anular un pago **inexistente** (o de **otra org**, invisible por RLS) → **404**.
- **C-Idempotente:** anular un pago **ya ANULADO** → **200** (no-op, sin doble reversa: cuotas y
  crédito no cambian).
- **C-Estado:** anular un pago `PENDIENTE`/`FALLIDO` → **422** (`estado_no_anulable`).
- **C-Crédito-consumido:** si el `credito_generado` del pago **ya fue consumido** por un pago
  posterior (`saldo_credito_inscripcion < pago.credito_generado`) → **409** (bloquea; "anulá
  primero el posterior"). **NO cascada.**
- **C-Motivo:** `motivo` vacío / ausente → **422**.
- **C-RLS:** un pago de **otra org** no es visible → anularlo da **404**; la **lista** solo trae
  pagos del org en contexto; query **sin contexto de tenant ⇒ 0 filas**. Aislamiento verificado.
- **C-Multi-cuota:** un pago que cubrió **varias cuotas** → revertir **todas** las filas
  `pago_cuota`; tras anular se cumple
  `Σ(pago_cuota.monto_aplicado de pagos VIVOS) == cuota.monto_pagado` por cada cuota.
- **C-Atómico:** la reversa es atómica (todo en la tx del request); un fallo a mitad no deja
  estado parcial.
- **C-Lista:** `GET /cobranza/pagos` devuelve los pagos del org (RLS), paginados, `created_at
  DESC`, con `anulable` correcto (efectivo+CONFIRMADO ⇒ true) y `deportista_nombre` en
  **MAYÚSCULAS**.
- **C-Gates:** `pytest` (con BD; nuevos + baseline), `ruff`, `mypy`, **import-linter**
  (`anular_pago` en `services`, no en `domain`), `build`/`lint`/`typecheck` del front.

## Hard constraints (lo que NO se toca)
- **Solo `metodo=='EFECTIVO'` es anulable**; QR/conciliado → error (no se toca la conciliación
  OpenBCB ni `conciliacion_pendiente`).
- **Reusar los helpers de pagos** (`_cuotas_de_pago`, `_estado_destino`, `saldo_credito_inscripcion`,
  `_upsert_credito`); **NO** duplicar FIFO/estado/crédito. **NO romper** `registrar_pago_efectivo`
  (solo **+1 línea**: persistir `credito_generado`).
- **Migración 0025**, `down_revision='0024'` (head real verificado = 0024). Patrón **0009** para
  el CHECK (DROP+CREATE de `ck_pago_estado`) y **0010** para add-column. **NO** re-habilitar RLS
  ni re-GRANT en `pago` (ya los tiene desde 0002).
- **Atómico** (todo en la tx del request) e **idempotente** (anular 2x → sin doble reversa).
- **Edit (no Write)** en `app/models/pago.py` y `app/api/v1/cobranza.py` (compartidos).
- **Auditoría obligatoria:** motivo + quién (`anulado_por`) + cuándo (`anulado_en`). **Nunca**
  borrado físico (RNF-02/03). **NO** tocar `numero_recibo`. **NO** enviar WhatsApp ni PDF al anular.
- **import-linter:** `anular_pago` vive en `app/services`, NO en `app/domain` (el dominio no
  importa servicios/adaptadores/api).
- Ownership por carpeta: db-dev solo `migrations/`; backend-dev solo `backend/`; frontend-dev solo
  `frontend/`. Sin solape.

## Decisiones de producto YA tomadas (no re-preguntar)
- Solo se anulan pagos con `metodo == 'EFECTIVO'` (los QR/conciliados → rechazo 422). *(Nota: el
  brief escribió `'EJECTIVO'`; el valor correcto del enum es `'EFECTIVO'`.)*
- Reversa **con rastro**: `estado='ANULADO'` + motivo + quién + cuándo. **Nunca** borrado físico
  (RNF-02/03).
- Crédito **ya consumido** por un pago posterior → **BLOQUEAR** (409); **NO** cascada.
- Pago **ya anulado** → **idempotente** (200).
- **Lista de pagos buscable** (`GET /cobranza/pagos` + vista) es el punto de acceso al botón "Anular".
- **Solo ADMIN**; **motivo obligatorio**.

## Decisiones de producto PENDIENTES (para el usuario — NO inventar)
1. **Aviso de sobrepago al registrar** ("estás pagando de más, quedará saldo a favor — ¿confirmás?"):
   propuesto pero **fuera de este epic**. Decisión del usuario para una iteración futura: ¿se
   añade ese aviso/confirmación al registrar un pago en efectivo que excede el saldo de la cuota?
