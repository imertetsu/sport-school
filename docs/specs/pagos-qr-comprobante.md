# Epic: pagos-qr-comprobante

> **Pagos v1 — QR estático por escuela + comprobante por WhatsApp con OCR e identificación
> automática del tutor.** Conciliación **asistida-manual** (sin API bancaria; OpenBCB queda
> FUERA). El ADMIN sube el QR de su escuela; el recordatorio de cobro lleva ese QR como imagen;
> el tutor paga directo a la escuela y responde por WhatsApp con la captura; el backend hace
> **OCR server-side**, identifica al tutor por su teléfono, empareja su cuota pendiente (FIFO) y
> deja una cola **"Pagos por verificar"** pre-llena; el admin **confirma en 1 clic** reusando
> `registrar_pago_efectivo` (idempotente). Spec **efímera**: se borra en el commit que cierra el
> epic (SSS, pilar 1).

## Objetivo y valor
Dar a cada escuela un **cobro real sin pasarela bancaria**: el ADMIN sube **su propio QR** (el
de su banco/billetera) y los tutores pagan directo. El sistema **automatiza el papeleo** del
cobro manual: el recordatorio por WhatsApp ya lleva el QR + monto + nombre del deportista; el
tutor responde con la captura del comprobante; el backend lo procesa (OCR + match por teléfono +
cuota FIFO) y se lo deja al ADMIN **pre-llenado para confirmar en 1 clic**. Beneficia al ADMIN
(deja de teclear pagos a mano, cero pagos perdidos) y al tutor (paga y avisa por el canal que ya
usa, sin app extra). **Nunca auto-confirma** en v1: el OCR solo pre-llena; el admin siempre cierra.

## Alcance MVP / Fuera de alcance

### En alcance (v1)
- **QR estático por escuela**: el ADMIN sube una **imagen** del QR en Ajustes (subir/ver/borrar);
  1 fila por org. El QR **no se decodifica**: se **reenvía** tal cual como imagen.
- **Recordatorio de cobro adjunta el QR** como imagen (vía `send_image`) + caption con
  deportista/monto/escuela/vence. Si la escuela **no** tiene QR ⇒ **degrada al texto actual**.
- **Comprobante entrante por WhatsApp**: el tutor responde al número de la escuela con la captura
  del pago; el sidecar reenvía la imagen al backend; el backend la guarda en
  `comprobante_pendiente`.
- **OCR server-side** del comprobante (monto + nº transacción + fecha), **best-effort**: si el OCR
  falla, la fila se crea igual con los campos en `null`.
- **Identificación automática**: por el **teléfono** del remitente → tutor → su **cuota pendiente
  más antigua (FIFO)** como sugerencia. Sin match de teléfono ⇒ comprobante **"sin identificar"**.
- **Cola "Pagos por verificar"** (UI ADMIN): lista pre-llena; ver imagen; elegir/ajustar cuota;
  **confirmar** (registra el pago reusando `registrar_pago_efectivo`) o **rechazar**.
- **Anti-fraude / anti-doble**: idempotencia por `message_id` (re-entrega del sidecar) y UNIQUE
  parcial por `transaccion_id_ocr` (un mismo comprobante no se confirma dos veces).

### Fuera de alcance (NO en este epic — follow-up)
- **OpenBCB / cualquier API bancaria / QR dinámico reconciliable**: FUERA. El recordatorio deja de
  crear el `crear_pago_qr` reconciliable OpenBCB. La conciliación de este epic es **asistida-manual**.
- **Auto-confirmación** (aunque el OCR matchee monto exacto): NO en v1 (ver Decisiones pendientes).
- **Multi-cuota en un mismo comprobante**: v1 confirma **1 cuota** (el servicio ya soporta varias).
- **Respuesta automática al tutor** ("recibimos tu comprobante, en revisión"): futuro.
- **Decodificar el QR** / validar su contenido / leer la cuenta destino: no se hace (se reenvía).
- Portal passwordless del tutor, chatbot entrante, factura SIN, rendimiento (SRS §2, fase 2/3).

## Reglas de negocio (RF / SRS §)
- **SRS §4.1 / RNF-01 (multi-tenant, RLS por `org_id`):** `qr_cobro` y `comprobante_pendiente` son
  tablas tenant con **RLS** (patrón 0022, fail-closed `NULLIF`). Toda ruta scopea al `org` del
  token, jamás del cliente. El comprobante/QR de la org A es **invisible** a la org B.
- **SRS §7–§8 (cobranza):** la confirmación reusa `registrar_pago_efectivo` (efectivo, idempotente,
  FIFO sobre vencidas). Estados de cuota PENDIENTE/PAGADO/VENCIDO no se tocan; el pago es de tipo
  EFECTIVO (caja). Sugerencia de cuota = la pendiente más antigua del tutor (FIFO).
- **RNF-05/06 (idempotencia / nunca se pierde un pago):** mismo `message_id` ⇒ 1 fila; confirmar 2x
  ⇒ 1 pago; mismo `transaccion_id_ocr` ⇒ bloqueado. Un comprobante que no matchea NO se descarta:
  cae como **"sin identificar"** y se puede asignar a cualquier cuota con saldo de la escuela.
- **SRS §4.2/§4.3 (puertos/adaptadores):** el envío de la imagen del QR va detrás de
  `WhatsAppPort.send_image` (puerto nuevo); el dominio no importa el adaptador ni httpx.
- **RNF-02 (privacidad menores):** el comprobante es un dato de pago (no ficha médica); se guarda
  como bytea en tabla con RLS. No se exponen datos de menores en los mensajes salientes.
- **Invariante anti-fuga (gotcha del repo):** el webhook entrante, al pasar a **escribir BD**, DEBE
  fijar `app.current_org` (`set_config` + `ContextVar`) **dentro de la tx** (hoy el inbound solo
  loguea y por eso no fijaba contexto). Sin esto, la inserción del comprobante fugaría/fallaría RLS.

---

## Contratos compartidos (CONGELADOS — definidos por platform-architect, verificados contra el código)
> Estos contratos permiten paralelizar las 4 áreas sin solape de archivos. Usar **Edit (no Write)**
> en archivos compartidos existentes (`models/__init__.py`, `api/v1/__init__.py`,
> `ports/whatsapp.py`, `recordatorios.py`, `whatsapp_inbound.py`, `docker-compose.yml`/
> `.env.example`, OpenAPI). Cambio cruzado ⇒ handoff y parar. **Head real de migraciones = 0022**.

### C1 — Tabla `qr_cobro` (migración **0023**, `down_revision='0022'`; RLS patrón 0022)
1 fila por org. Columnas:
- `id` uuid PK; `org_id` uuid FK `organizacion` ON DELETE CASCADE NOT NULL (columna de RLS, index);
  `imagen` bytea NOT NULL; `mime` varchar NOT NULL; `tamano_bytes` int NOT NULL;
  `created_at`/`updated_at`.
- `UNIQUE(org_id)` `uq_qr_cobro_org`.
- RLS: `ENABLE` + `FORCE` + policy `org_isolation` con `NULLIF(current_setting('app.current_org',
  true), '')::uuid` (USING + WITH CHECK) + GRANT DML a `latinosport_app`.

Modelo `QrCobro(UUIDPkMixin, OrgScoped, TimestampMixin, Base)` con
`imagen: Mapped[bytes] = mapped_column(LargeBinary)`. (`OrgScoped` ya aporta `org_id` FK + index;
el CASCADE y el UNIQUE/constraints físicos los materializa la migración, patrón del repo.)

### C2 — Tabla `comprobante_pendiente` (migración 0023; RLS patrón 0022)
Columnas:
- `id` uuid PK; `org_id` uuid FK CASCADE NOT NULL (RLS, index);
- `estado` varchar NOT NULL DEFAULT `'PENDIENTE'` CHECK IN (`'PENDIENTE'`,`'CONFIRMADO'`,`'RECHAZADO'`);
- `from_telefono` varchar NOT NULL;
- `message_id` varchar **NULL UNIQUE** (idempotencia ante re-entrega del sidecar);
- `imagen` bytea NOT NULL; `mime` varchar NOT NULL; `caption` text NULL;
- `tutor_id` uuid FK `tutor` ON DELETE SET NULL NULL;
- `cuota_sugerida_id` uuid FK `cuota` SET NULL NULL;
- `monto_ocr` numeric(10,2) NULL; `transaccion_id_ocr` varchar NULL; `fecha_ocr` date NULL;
  `ocr_texto_crudo` text NULL;
- `pago_id` uuid FK `pago` SET NULL NULL; `resuelto_por` uuid FK `usuario` SET NULL NULL;
- `created_at` NOT NULL; `resuelto_en` timestamptz NULL.
- **UNIQUE parcial** `(transaccion_id_ocr) WHERE transaccion_id_ocr IS NOT NULL`
  `uq_comprobante_transaccion_ocr` (anti-fraude). **index** `(org_id, estado)`.
- RLS igual que C1.
- **El UNIQUE parcial + el CHECK del enum van en la migración A MANO** (no declarativos; patrón del
  repo: el CHECK enum-like y los únicos parciales viven solo en la migración).

### C3 — Sidecar `POST /sessions/{org}/send` extendido (dueño: infra-dev)
Además del body de texto actual `{to, text}`, acepta:
`{to, text:"<caption|''>", image:"<base64 sin data-url>", mime:"image/png"}`.
- Si `image` presente ⇒ `sendMessage(jid, {image: Buffer.from(image,'base64'), caption: text||undefined,
  mimetype: mime})`; si no ⇒ texto como hoy.
- Respuesta igual (200 `ok`/`error`, nunca 5xx por negocio).
- **Subir el límite del body express de 256kb a 4mb** (`express.json({ limit: '4mb' })`).
- (Nota: hoy `/send` exige `text` no vacío; con `image` presente el `text` puede ser `""` → relajar
  esa validación cuando viene imagen.)

### C4 — Callback inbound extendido (dueño: infra-dev → consume backend)
- Texto actual `{org_id, from, text, message_id, timestamp}` SIN `tipo` (retrocompat: texto sigue igual).
- Imagen NUEVO: `{org_id, from, tipo:"image", media:"<base64>", mime, caption, message_id, timestamp}`.
- `handleIncoming`: si `imageMessage` ⇒ `downloadMediaMessage` ⇒ base64 ⇒ POST al callback con
  `tipo:"image"`. **Tolera fallos** (si la descarga del media falla, no revienta el sidecar).

### C5 — Puerto `WhatsAppPort.send_image` (dueño: backend-dev, Edit `domain/ports/whatsapp.py`)
- `WhatsAppImageMessage{to, image_b64, mime, caption}` (dataclass pura; el puerto vive en
  `app.domain.ports` ⇒ NO importa adaptadores/fastapi/sqlalchemy/httpx — lo verifica import-linter).
- Método `send_image(msg) -> WhatsAppSendResult` (reusa el `WhatsAppSendResult` existente).
- Implementaciones:
  - `gateway.py`: resuelve org por `ContextVar` (`get_current_org_id`, fail-closed sin contexto),
    normaliza `to` con `normalize_bo_phone`, `POST /sessions/{org}/send` con `image`/`mime` en el body.
  - `meta.py`: stub que degrada `ok=False` en v1 (Meta multi-imagen es futuro).
  - `mock.py`: registra el envío y devuelve `ok=True`.
- **NO tocar** `send_text` / `send_template`.

### C6 — Endpoints API (dueño: backend-dev; TODOS `require_role("ADMIN")`, org del token)
**QR de cobro** (`routers/qr_cobro.py`, NUEVO):
- `POST /api/v1/qr-cobro` (multipart `file`) → `{tiene_qr, mime, tamano_bytes}`
- `GET /api/v1/qr-cobro` → imagen (bytes con su `mime`)
- `GET /api/v1/qr-cobro/meta` → `{tiene_qr, mime|null, tamano_bytes|null}`
- `DELETE /api/v1/qr-cobro` → `{tiene_qr:false}`

**Comprobantes** (`routers/comprobantes.py`, NUEVO):
- `GET /api/v1/comprobantes/pendientes?estado=&page=&page_size=` →
  `{items:[ComprobantePendienteItem], total, page, page_size}`
- `GET /api/v1/comprobantes/{id}/imagen` → imagen
- `GET /api/v1/comprobantes/{id}/cuotas` →
  `[{cuota_id, deportista_nombre, vence_el, saldo, estado}]` (cuotas con saldo de la escuela, para
  asignar un comprobante "sin identificar" o reasignar)
- `POST /api/v1/comprobantes/{id}/confirmar {cuota_id, monto}` → **PagoOut**
  (reusa `registrar_pago_efectivo`; marca el comprobante `CONFIRMADO`, fija `pago_id`,
  `resuelto_por`, `resuelto_en`)
- `POST /api/v1/comprobantes/{id}/rechazar {motivo?}` → `{id, estado:'RECHAZADO'}`

**Shape `ComprobantePendienteItem`** (contrato OpenAPI que consume el frontend):
```
ComprobantePendienteItem = {
  id, estado, from_telefono, created_at,
  tutor: {id, nombres} | null,
  cuota_sugerida: {cuota_id, deportista_nombre, vence_el, saldo, estado} | null,
  monto_ocr: Decimal | null,
  transaccion_id_ocr: str | null,
  fecha_ocr: date | null,
  imagen_url,
}
```

### C7 — Recordatorio adjunta el QR (dueño: backend-dev, Edit `services/recordatorios.py`)
- Leer `qr_cobro` de la org → si existe, enviar con
  `send_image(WhatsAppImageMessage(to, image_b64, mime, caption=<texto con deportista + monto +
  escuela + vence>))`.
- Si la escuela **no** tiene QR ⇒ **degrada al texto actual** (no rompe el flujo).
- **Deja de crear el `crear_pago_qr` reconciliable OpenBCB** (OpenBCB fuera de este epic). El enlace
  de cobro reconciliable ya no se genera aquí.

---

## Fases (cada fase = uno o pocos commits)

### Fase 1 — Cimientos (backend-dev) — ENTRADA de db-dev e infra-dev
- Modelos `qr_cobro` + `comprobante_pendiente` en `Base.metadata` (Edit `models/__init__.py` para
  registrarlos).
- Puerto `send_image` + `WhatsAppImageMessage` (Edit `domain/ports/whatsapp.py`) + implementación en
  `gateway.py` / `meta.py` / `mock.py`.
> Serial respecto a Fase 2: la migración 0023 (db-dev) **autogenera desde los modelos** y la pantalla
> de QR (frontend) e imagen del sidecar (infra) dependen de los shapes/puerto definidos aquí.

### Fase 2 — Paralelo (contratos congelados, sin solape de archivos)
- **db-dev** — migración **0023** desde los modelos (`down_revision='0022'`); añade A MANO el UNIQUE
  parcial de `transaccion_id_ocr`, el CHECK del enum de `estado`, el index `(org_id, estado)` y la
  RLS patrón 0022 (ENABLE+FORCE+policy `org_isolation` NULLIF + GRANT a `latinosport_app`).
- **infra-dev** — sidecar enviar/recibir imagen (C3 `/send` con `image`+`mime`, body 4mb; C4
  `handleIncoming` con `imageMessage`→`downloadMediaMessage`→base64→callback `tipo:"image"`) +
  **instalar `tesseract-ocr` + `tesseract-ocr-spa`** en la imagen del api (y worker) que corre el OCR.
- **frontend-dev** — pantallas contra los shapes congelados: **subir/ver/borrar QR en Ajustes**
  (`features/escuela/`) + cola **"Pagos por verificar"** (lista pre-llena, ver imagen, elegir cuota,
  confirmar/rechazar) + métodos de cliente en `api/client.ts`.
> Paralelizable: ninguna de las 3 áreas comparte archivo con otra y los contratos están congelados.

### Fase 3 — Lógica de OCR y conciliación (backend-dev)
- `app/services/ocr.py` (NUEVO; `pytesseract` + regex, **espejo de `parseCedula.ts`**: función
  best-effort, no lanza, deja `null` ante baja confianza). Extrae monto + nº transacción + fecha.
- `app/services/comprobantes.py` (NUEVO; procesar inbound: guardar comprobante, OCR, match por
  teléfono → tutor → cuota FIFO; y confirmar: reusa `registrar_pago_efectivo`, marca CONFIRMADO).
- **Edit** `api/v1/webhooks/whatsapp_inbound.py`: al recibir `tipo:"image"`, **fija el contexto org**
  (`set_config('app.current_org')` + `set_current_org_id`) **dentro de la tx** y procesa la imagen.
- Routers `comprobantes.py` + `qr_cobro.py` (Edit `api/v1/__init__.py` para registrarlos).
- **Edit** `services/recordatorios.py` (C7: adjunta QR / degrada a texto; quita el `crear_pago_qr`).
- Schemas Pydantic (`ComprobantePendienteItem`, salidas de QR) + tests.

### Fase 4 — Verificación E2E (main + operador)
- RLS: comprobante/QR de org A invisible a org B; sin contexto ⇒ 0 filas.
- Idempotencia: mismo `message_id` 2x ⇒ 1 fila; confirmar 2x ⇒ 1 pago; mismo `transaccion_id_ocr`
  ⇒ bloqueado.
- OCR degrada: si el OCR falla, la fila se crea igual con campos `null`.
- Confirmar reusa `registrar_pago_efectivo` (idempotente, FIFO).
- Gates verdes. **Última fase del epic ⇒ borrar esta spec en ese commit** + actualizar `HANDOFF.md`.

---

## Criterios de aceptación (verificables — incluyen casos borde de dominio)
- **C-QR:** un ADMIN sube su QR (multipart) → `GET /qr-cobro` devuelve la imagen; `GET .../meta`
  refleja `tiene_qr/mime/tamano_bytes`; `DELETE` lo borra (`tiene_qr:false`). El recordatorio de
  cobro **adjunta ese QR** como imagen con caption; **sin QR → degrada al texto** sin romper.
- **C-Inbound:** el tutor responde al número de la escuela con la captura → cae en "Pagos por
  verificar" **identificado** (tutor por teléfono + cuota FIFO) con OCR pre-lleno (monto / nº
  transacción / fecha cuando se leen).
- **C-Confirmar:** el admin confirma en 1 clic → **pago registrado** reusando
  `registrar_pago_efectivo`; el comprobante pasa a `CONFIRMADO` con `pago_id`/`resuelto_por`/
  `resuelto_en`. **Rechazar** marca `RECHAZADO` (con `motivo?`).
- **C-RLS:** comprobante/QR de la org A son **invisibles** a la org B; query **sin contexto de
  tenant ⇒ 0 filas**.
- **C-Idem:** mismo `message_id` entregado 2x ⇒ **1 fila**; confirmar el mismo comprobante 2x ⇒
  **1 pago**; un comprobante con el **mismo `transaccion_id_ocr`** que otro ⇒ **bloqueado** (UNIQUE
  parcial).
- **C-OCR-degrada:** si el OCR no lee nada, la fila se crea **igual** con `monto_ocr`/
  `transaccion_id_ocr`/`fecha_ocr` en `null` (el admin completa a mano).
- **C-Sin-identificar:** teléfono que **no matchea** ningún tutor ⇒ comprobante **"sin identificar"**
  (`tutor:null`, `cuota_sugerida:null`); se puede asignar a **cualquier cuota con saldo** de la
  escuela vía `GET /comprobantes/{id}/cuotas` + confirmar.
- **C-Contexto:** el webhook inbound, al escribir el comprobante, fija `app.current_org`
  (`set_config` + `ContextVar`) dentro de la tx (invariante anti-fuga verificado).
- **C-Gates:** `pytest` (con BD), `ruff`, `mypy`, **import-linter** (dominio no importa adaptadores/
  api; el puerto sigue siendo dataclasses puras), `build` del frontend.

## Hard constraints (lo que NO se toca)
- Migración nueva = **0023** (`down_revision='0022'`; head real verificado = 0022). RLS **patrón
  0022**: `NULLIF` fail-closed, `ENABLE`+`FORCE`, policy `org_isolation`, GRANT DML a
  `latinosport_app`. UNIQUE parcial + CHECK enum + index `(org_id,estado)` **a mano** en la migración.
- **Reusar `registrar_pago_efectivo`** al confirmar (idempotente, FIFO). **NO** abrir un segundo
  camino de registro de pago.
- **NO romper** los 4 flujos de WhatsApp existentes ni el envío de **texto** (`send_text`/
  `send_template` intactos; `send_image` es aditivo).
- El **webhook inbound**, al pasar a escribir BD, **DEBE** fijar `app.current_org` (`set_config` +
  `ContextVar`) **dentro de la tx** — invariante anti-fuga (hoy el inbound solo loguea, por eso no
  fija contexto).
- **Edit (no Write)** en compartidos: `models/__init__.py`, `api/v1/__init__.py`,
  `domain/ports/whatsapp.py`, `services/recordatorios.py`, `webhooks/whatsapp_inbound.py`,
  `docker-compose.yml`/`.env.example`. **Secrets nunca** commiteados.
- **import-linter:** el dominio (`app.domain`) NO importa adaptadores/api/fastapi/sqlalchemy/httpx;
  el OCR (`app.services.ocr`) vive en la capa de servicios (pytesseract ahí no rompe el contrato).
- El **sidecar Node** lo posee **infra-dev** (`infra/whatsapp-gateway/`); backend-dev NO escribe Node.
- **OpenBCB fuera:** el recordatorio deja de crear `crear_pago_qr` reconciliable; nada de API bancaria.

## Decisiones de producto YA tomadas (no re-preguntar)
- **Nunca auto-confirma en v1**: el OCR solo pre-llena; el admin siempre confirma (1 clic).
- Un comprobante **"sin identificar"** (teléfono no matchea) se puede asignar a **cualquier cuota
  con saldo** de la escuela.
- El **QR se sube como imagen y se reenvía** (no se decodifica). **OCR server-side** (la imagen llega
  por WhatsApp, no por el navegador del admin).
- Conciliación **asistida-manual** (sin API bancaria; OpenBCB FUERA).
- Sugerencia de cuota = **FIFO** (la pendiente más antigua del tutor).

## Decisiones de producto PENDIENTES (para el usuario — NO inventar)
1. **Auto-confirmación por match exacto** (futuro): cuando el OCR matchea monto exacto + cuota +
   transacción no vista, ¿se auto-confirma con más verificación, o sigue requiriendo el clic del
   admin? (v1: siempre manual.)
2. **Multi-cuota en un mismo comprobante** (v1 = 1 cuota): `registrar_pago_efectivo` **ya soporta
   varias** (`cuota_ids: list`). ¿Se permite repartir un comprobante entre varias cuotas en la UI?
3. **Respuesta automática al tutor** ("recibimos tu comprobante, en revisión") al recibir la captura
   — útil para UX, pero gasta un mensaje saliente (anti-baneo del número no-oficial). ¿Se implementa
   y con qué texto?
