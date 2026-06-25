# Epic: whatsapp-gateway

> Gateway de WhatsApp **NO-OFICIAL** (Baileys, sidecar Node) como **un adaptador más**
> detrás del puerto `WhatsAppPort`, para enviar mensajes REALES **YA** sin esperar la
> verificación de negocio + plantillas + dominio/HTTPS que exige Meta Cloud API. El día
> que Meta esté listo, se flipa `WHATSAPP_PROVIDER` de vuelta a `meta`. Spec **efímera**:
> se borra en el commit que cierra el epic (SSS, pilar 1).

## Objetivo y valor
Que los **4 flujos de WhatsApp ya construidos** (recordatorios de cobro, recibos, digest de
deudores, avisos del muro) dejen de ser mock y envíen mensajes **reales** desde un **número
de prueba**, **sin tocar ni una línea** de los servicios ni del puerto. Beneficia a tutores
(recordatorios/recibos) y entrenadores (deudores/avisos). Además deja **abierto y probado**
el canal **entrante** (el sidecar reenvía lo que recibe a un webhook del backend que valida,
loguea y responde 200), como base para un chatbot futuro — **sin** implementar todavía la
lógica de auto-respuesta.

## Alcance MVP
- **Saliente production-ready:** sidecar Node (Baileys, WebSocket multidevice — **NO**
  Puppeteer) mantiene la sesión de **UN** número de prueba (pairing por QR) y expone HTTP
  `/send`, `/status`, `/qr`. Nuevo adaptador Python `GatewayWhatsAppAdapter` (detrás de
  `WhatsAppPort`) llama a `/send`. Con `WHATSAPP_PROVIDER=gateway` + URL/token, los 4 flujos
  envían **mensajes reales**.
- **Entrante (pipe probado, sin lógica):** el sidecar, al recibir un mensaje, hace `POST` al
  webhook nuevo `POST /api/v1/webhooks/whatsapp-inbound` con el token compartido; el backend
  **valida token → loguea → 200**. Canal bidireccional ABIERTO y demostrado.
- Persistencia de la sesión Baileys en un **volumen** (no re-escanear QR en cada reinicio).
- Patrón **fail-safe** de la fábrica: credenciales incompletas ⇒ mock, nunca tumba el arranque.

## Fuera de alcance (follow-up explícito — NO en este epic)
- **Lógica de auto-respuesta / chatbot / persistencia de conversaciones** del entrante. Por
  eso el entrante **solo recibe+loguea**: así NO se necesita migración ni resolver tenant/RLS
  del mensaje entrante todavía.
- **Multi-tenant real** del gateway (varios números/escuelas) y mapeo número→`org` del
  entrante. Hoy: **1 número de prueba**, 1 sesión.
- **Portal passwordless OTP** por este canal (Fase 2, SRS §2/§3).
- **Migración / cambio de esquema** (el entrante solo loguea; no persiste nada).
- No se toca la conciliación de pagos (eso es OpenBCB, `POST /webhooks/openbcb`), ni el
  webhook de **estados de Meta** existente (`/webhooks/whatsapp`), que es OTRA ruta.

## Reglas de negocio (RF / SRS)
- **RNF-01 / SRS §4.1 (RLS):** este epic **NO** cambia el modelo de tenancy ni añade
  migraciones. El saliente corre bajo el `app.current_org` del caller (los servicios ya lo
  hacen). El **entrante** NO escribe en BD, así que NO necesita contexto de tenant todavía.
- **RNF-05/06 (idempotencia/conciliación):** el saliente NO toca la conciliación; el webhook
  entrante **NUNCA** escribe pagos. El cobro QR se concilia por OpenBCB.
- **RNF-02 (privacidad menores):** no se envían datos de ficha médica; los mensajes llevan
  nombre del deportista, monto, escuela, enlaces tokenizados — igual que hoy.
- **Aislamiento de secretos:** `X-Gateway-Token` autentica **ambas** direcciones; nunca se
  commitea (placeholder en `.env.example`).

---

## CONTRATO CONGELADO (decisión de arquitectura de `main`)
> Este es el contrato entre **infra-dev** (posee el sidecar) y **backend-dev** (posee el
> adaptador + webhook). **Definido ANTES de paralelizar** → ambos agentes trabajan en
> paralelo (sin solape de archivos). Usar **Edit** en archivos compartidos existentes.

### A) HTTP API del sidecar — la POSEE infra-dev; la CONSUME el adaptador Python
- **Auth en CADA request (ambas direcciones):** header `X-Gateway-Token: <token>`. Si no
  coincide → **401**.
- **`POST /send`** — body JSON
  `{ "to": "<dígitos E.164 sin +, ej 59176123456>", "text": "<string, puede ser multilínea>" }`.
  Respuesta **200** `{ "ok": true, "message_id": "<id>" }` **o** **200**
  `{ "ok": false, "error": "<msg legible>" }`.
  **Nunca 5xx por errores de negocio** (número inválido, no conectado, etc.): se reportan
  como `ok:false` para que el adaptador los mapee a `WhatsAppSendResult(ok=False, error=...)`.
- **`GET /status`** — `{ "connected": bool, "number": "<jid o null>" }` (healthcheck/pairing).
- **`GET /qr`** — devuelve el QR de pairing vigente (data-url o imagen) **y además** lo
  loguea a **stdout** para que el operador lo escanee. Si ya está conectado → indica conectado.
- **Entrante:** al llegar un mensaje, el sidecar hace
  `POST {INBOUND_CALLBACK_URL}` con header `X-Gateway-Token` y body
  `{ "from": "<dígitos>", "text": "<string>", "message_id": "<id>", "timestamp": <epoch> }`.
  El backend valida token, loguea y responde **200**.

### B) Env vars (contrato `backend/app/core/config.py` ↔ `.env.example` ↔ `docker-compose.yml`)
- **Backend** (`config.py`, propiedad de **backend-dev**):
  - `WHATSAPP_PROVIDER` → **extender** el set permitido con `gateway`
    (hoy `noop|mock|meta`; queda `noop|mock|meta|gateway`).
  - `WHATSAPP_GATEWAY_URL` (ej `http://whatsapp-gateway:3000`).
  - `WHATSAPP_GATEWAY_TOKEN`.
- **Sidecar** (compose/`.env.example`, propiedad de **infra-dev**):
  - `GATEWAY_TOKEN` (= `WHATSAPP_GATEWAY_TOKEN`).
  - `GATEWAY_PORT` (`3000`).
  - `INBOUND_CALLBACK_URL` (ej `http://api:8000/api/v1/webhooks/whatsapp-inbound` — `api` es
    el nombre del servicio interno del compose).
  - Ruta de almacenamiento de la sesión → **volumen** para persistir el auth-state de Baileys
    entre reinicios (si no, re-escanear QR en cada reinicio).

### C) Comportamiento del adaptador Python — lo POSEE backend-dev
- `GatewayWhatsAppAdapter` implementa `WhatsAppPort` (nuevo
  `backend/app/adapters/whatsapp/gateway.py`).
- **`send_text(msg)`** → normaliza `msg.to` con el helper **existente**
  `app.core.phone.normalize_bo_phone`; si da `None` → `WhatsAppSendResult(ok=False, error=...)`
  **SIN** llamar al sidecar; si no, `POST /send {to, text: msg.body}` y mapea la respuesta.
- **`send_template(msg)`** → el no-oficial **NO** tiene plantillas aprobadas, así que **el texto
  lo ponemos nosotros**: un **dict local** `template_name → plantilla de texto`, rellenado con
  `msg.body_params` posicionales (`{{1}}..{{n}}`). Luego `POST /send`. **`header_image` se
  ignora** (igual que en `meta.py`). El destino también se normaliza con `normalize_bo_phone`
  (mismo guard que `send_text`).
- **Fábrica `get_whatsapp_port()`** (`backend/app/services/deps.py`, **Edit**): si
  `provider == 'gateway'` **Y** `gateway_url`/`gateway_token` no vacíos → `GatewayWhatsAppAdapter`;
  si no, **degrada a mock** (fail-safe, **mismo patrón** que la rama `meta` actual — loguea
  WARNING si era `gateway` sin credenciales).

> Nota de implementación (no es contrato): `meta.py` normaliza el `to` **dentro** del
> adaptador (`_post` llama a `normalize_bo_phone`). El gateway hace lo mismo en
> `send_text`/`send_template`; **no se duplica** la normalización, se reusa el helper.

### D) Plantillas de texto (las pone backend-dev en el dict del adaptador — ORDEN EXACTO de params)
Idénticas en semántica a las de Meta, pero como **texto plano** (el no-oficial **SÍ** permite
multilínea, a diferencia de Meta). El **orden de `{{n}}` debe coincidir** con el `body_params`
que ya pasan los 4 servicios (no se tocan los servicios):

| `template_name` | Params (orden EXACTO = `body_params`) | Texto |
|-----------------|----------------------------------------|-------|
| `recordatorio_cuota_qr` | {{1}} deportista · {{2}} monto (ya viene `"Bs X.XX"`) · {{3}} escuela · {{4}} vence DD/MM/YYYY · {{5}} enlace | `Hola, recordatorio de cuota de {{1}} en {{3}}: {{2}}, vence el {{4}}. Pague aquí: {{5}}` |
| `morosidad_cuota_qr` | mismos 5 (deportista, monto, escuela, vence, enlace) | `La cuota de {{1}} en {{3}} está vencida: {{2}} (venció el {{4}}). Regularice aquí: {{5}}` |
| `recibo_pago` | {{1}} deportista · {{2}} monto · {{3}} escuela · {{4}} N° recibo · {{5}} enlace PDF | `Pago recibido de {{1}} en {{3}}: {{2}}. Recibo {{4}}. Descárguelo aquí: {{5}}` |
| `resumen_deudores` | {{1}} entrenador · {{2}} sucursal · {{3}} nº deudores · {{4}} monto total | `Hola {{1}}, resumen de deudores en {{2}}: {{3}} deportistas, total Bs {{4}}. Detalle a continuación.` |
| `nuevo_aviso` | {{1}} escuela · {{2}} título · {{3}} cuerpo | `{{1}} informa: {{2}}. {{3}}` |

- `resumen_deudores`: el **detalle multilínea** sigue yendo por `send_text` **aparte** (como hoy)
  → con el gateway no-oficial el texto libre **SÍ** se entrega siempre (no hay ventana de 24h
  como en Meta) y **SÍ** admite saltos de línea.

---

## Fases
Cada fase = uno (o pocos) commits. **backend-dev ∥ infra-dev** trabajan en PARALELO (sin solape
de archivos, contrato congelado arriba). Fase 3 es verificación/operación.

### Fase 1 — Backend: adaptador + webhook entrante (backend-dev)
1. **Edit** `backend/app/core/config.py`: añadir `whatsapp_gateway_url` y
   `whatsapp_gateway_token` (`str | None = None`); **extender** el set permitido de
   `whatsapp_provider` para incluir `gateway` (si hay validación/comentario del set, ampliarlo).
2. **Nuevo** `backend/app/adapters/whatsapp/gateway.py`: `GatewayWhatsAppAdapter(WhatsAppPort)`
   con `send_text`/`send_template` según contrato C; dict local de plantillas según D;
   normaliza con `normalize_bo_phone`; `httpx` con header `X-Gateway-Token`; **no lanza**,
   reporta vía `ok`/`error`; mapea `ok:false` del sidecar a `WhatsAppSendResult(ok=False,...)`.
3. **Edit** `backend/app/services/deps.py`: registrar la rama `gateway` en `get_whatsapp_port()`
   con el fail-safe (incompleto ⇒ mock).
4. **Nuevo** `backend/app/api/v1/webhooks/whatsapp_inbound.py`:
   `POST /webhooks/whatsapp-inbound` que **valida `X-Gateway-Token`** contra
   `settings.whatsapp_gateway_token` (ausente/incorrecto → **401**), **loguea**
   `from`/`message_id`/`text` (info) y responde **200**. **NO** escribe en BD. **Edit**
   `backend/app/api/v1/__init__.py` para `include_router`.
5. **Tests** (`backend/tests/...`, httpx mockeado):
   - `get_whatsapp_port()` con `provider=gateway` + url/token → `GatewayWhatsAppAdapter`;
     sin ellos → mock.
   - `send_text` con número no normalizable → `ok=False` **sin** llamar al sidecar.
   - `send_template` renderiza el texto correcto de **cada una** de las 5 plantillas con sus
     params en orden.
   - `send_text`/`send_template` mapean `ok:false` del sidecar a `WhatsAppSendResult(ok=False)`.
   - Webhook entrante: token válido → 200 + loguea; token inválido/ausente → 401; verifica que
     **no** escribe pagos.

### Fase 2 — Infra: sidecar Baileys + compose (infra-dev) — EN PARALELO con Fase 1
1. **Nuevo** `infra/whatsapp-gateway/`: servicio Node con Baileys (WebSocket multidevice, **no**
   Puppeteer) que implementa `/send`, `/status`, `/qr`, el `POST` entrante a
   `INBOUND_CALLBACK_URL`, persistencia de la sesión en volumen, y `Dockerfile`. Auth
   `X-Gateway-Token` en cada request entrante; lo añade en el callback saliente.
2. **Edit** `docker-compose.yml`: añadir servicio `whatsapp-gateway` (puerto `GATEWAY_PORT`,
   `env_file: ../.env`, `restart: unless-stopped`, volumen de sesión declarado en la sección
   `volumes:`), y que `api` no dependa del gateway (el saliente tolera gateway caído →
   `ok:false`).
3. **Edit** `.env.example`: documentar `WHATSAPP_GATEWAY_URL`, `WHATSAPP_GATEWAY_TOKEN`
   (placeholder), y las del sidecar (`GATEWAY_TOKEN`, `GATEWAY_PORT`, `INBOUND_CALLBACK_URL`,
   ruta de sesión). **Nunca** valores reales de secretos.

### Fase 3 — Integración y pairing (main + operador)
1. `docker compose up` levanta `whatsapp-gateway`; escanear el QR (de `/qr` o stdout) con el
   **número de prueba** para parear; `GET /status` → `connected: true`.
2. En `.env` (no commiteado): `WHATSAPP_PROVIDER=gateway` + `WHATSAPP_GATEWAY_URL` +
   `WHATSAPP_GATEWAY_TOKEN` (= `GATEWAY_TOKEN`). Reiniciar api/worker.
3. Envío de prueba de cada flujo a un número propio; probar el entrante (mandar un WhatsApp al
   número de prueba → ver el log del webhook). Gates verdes (pytest + ruff). Cerrar epic:
   **borrar esta spec** en el commit final + actualizar `docs/HANDOFF.md`.

---

## Contratos compartidos (definidos ANTES de paralelizar)
1. **HTTP API del sidecar** (sección A): `POST /send` / `GET /status` / `GET /qr` / callback
   entrante, con `X-Gateway-Token`. infra-dev produce, backend-dev (adaptador) consume.
2. **Env vars** (sección B): `config.py` (backend-dev) ↔ `.env.example` + `docker-compose.yml`
   (infra-dev). `WHATSAPP_GATEWAY_TOKEN` (backend) **===** `GATEWAY_TOKEN` (sidecar).
3. **Nombres y orden de params de las 5 plantillas** (sección D): los `body_params` que ya
   pasan los 4 servicios = el orden que el dict del adaptador debe respetar. **No** se tocan los
   servicios; el contrato lo garantiza el adaptador.
4. **Ruta del webhook entrante** `POST /api/v1/webhooks/whatsapp-inbound` (DISTINTA de
   `/api/v1/webhooks/whatsapp`, que es el webhook de **estados de Meta** — no se toca).
   `INBOUND_CALLBACK_URL` (infra) apunta a ella.
5. **Contrato del puerto `WhatsAppPort`** (existente): `to` = E.164 sin `+`; `send_template`
   con `body_params` posicionales; `header_image` se ignora. **Congelado, no se modifica.**

## Criterios de aceptación (verificables)
- **C1:** con `WHATSAPP_PROVIDER=gateway` + `WHATSAPP_GATEWAY_URL`/`_TOKEN`, `get_whatsapp_port()`
  devuelve `GatewayWhatsAppAdapter`; sin esas vars (o incompletas) **degrada a mock** (no rompe).
- **C2:** `send_text` con número **no normalizable** → `ok=False` **sin** pegar al sidecar
  (verificado con httpx mockeado: cero requests).
- **C3:** `send_template` renderiza el **texto correcto** de cada una de las **5 plantillas** con
  sus params en el **orden** de la tabla D.
- **C4:** el sidecar reporta errores de negocio (número inválido / no conectado) como **200
  `ok:false`** (nunca 5xx) → el adaptador los mapea a `WhatsAppSendResult(ok=False, error=...)`.
- **C5:** webhook `POST /api/v1/webhooks/whatsapp-inbound` con token **válido** → **200** y
  loguea; con token **inválido/ausente** → **401**; **nunca** escribe pagos.
- **C6:** `docker compose up` levanta `whatsapp-gateway`; `GET /status` responde; el **QR**
  aparece en logs/`/qr` para parear el número de prueba; la sesión **sobrevive a un reinicio**
  del contenedor (volumen) sin re-escanear.
- **C7 (no-regresión):** los **4 flujos existentes intactos** (no se editó ni el puerto, ni
  `meta.py`, ni el mock, ni los 4 servicios); gates verdes (pytest con los nuevos tests + sin
  romper baseline, ruff). Con `WHATSAPP_PROVIDER` ≠ `gateway` el comportamiento de hoy no cambia.

---

## Hard constraints (lo que NO se toca)
- **NO** tocar `frontend/` ni `migrations/`. **SIN migración** en este epic (no se cambia el
  esquema; el entrante solo loguea).
- **NO** modificar los **4 servicios** de flujo (`recordatorios.py`, `recibo_envio.py`,
  `recordatorio_deudores.py`, `aviso_notificacion.py`), ni el puerto
  `backend/app/domain/ports/whatsapp.py`, ni `backend/app/adapters/whatsapp/meta.py`, ni el
  mock. El adaptador nuevo se enchufa **solo** por la fábrica.
- **NO** tocar el webhook de **estados de Meta** existente (`backend/app/api/v1/webhooks/whatsapp.py`).
  El entrante del gateway es una **ruta nueva y distinta** (`whatsapp-inbound`).
- Usar **Edit (no Write)** en archivos compartidos existentes: `config.py`, `deps.py`,
  `backend/app/api/v1/__init__.py`, `docker-compose.yml`, `.env.example`.
- **Reusar** `app.core.phone.normalize_bo_phone` (ya existe); **no duplicar** la normalización.
- El **sidecar Node** lo posee **infra-dev** (vive en `infra/`, es contenedorizado); backend-dev
  **NO** escribe Node.
- **Secrets** (`WHATSAPP_GATEWAY_TOKEN`/`GATEWAY_TOKEN`) **nunca** se commitean; en `.env.example`
  van como **placeholder**.
- Mantener el patrón **fail-safe** de la fábrica: credenciales incompletas ⇒ mock, **nunca**
  tumbar el arranque.

## Propiedad de archivos (sin solape → backend-dev ∥ infra-dev)
- **backend-dev** (`backend/`):
  - **Nuevo** `backend/app/adapters/whatsapp/gateway.py`.
  - **Nuevo** `backend/app/api/v1/webhooks/whatsapp_inbound.py`.
  - **Edit** `backend/app/services/deps.py` (rama `gateway` en la fábrica).
  - **Edit** `backend/app/core/config.py` (3 vars + extender el set de provider).
  - **Edit** `backend/app/api/v1/__init__.py` (`include_router` del nuevo webhook).
  - **Tests** del adaptador + webhook.
- **infra-dev** (`infra/` + raíz):
  - **Nuevo** `infra/whatsapp-gateway/` (sidecar Baileys: `/send`, `/status`, `/qr`, callback
    entrante, persistencia en volumen, `Dockerfile`).
  - **Edit** `docker-compose.yml` (servicio `whatsapp-gateway` + volumen de sesión).
  - **Edit** `.env.example` (`WHATSAPP_GATEWAY_*` + vars del sidecar).

## Decisiones de producto YA tomadas (no re-preguntar)
- **Baileys** (Node sidecar, **no** Puppeteer). **Construir production-ready directo** (sin spike).
- **Un solo número de prueba** al inicio (no el de la escuela).
- **Entrante = recibir + loguear**; chatbot/persistencia = **follow-up**.
- **Sin migración** en este epic.

## Decisiones de producto PENDIENTES (para el usuario — NO inventar)
1. **Multi-tenant real del gateway** (varios números/escuelas) y **mapeo número→`org`** del
   entrante: diseño futuro (hoy 1 número, 1 sesión). Cuando se aborde, el entrante necesitará
   resolver tenant/RLS (un resolver SECURITY DEFINER o equivalente, como OpenBCB) y
   probablemente migración para persistir conversaciones → **escalar a `platform-architect`**.
2. **Auto-respuesta / chatbot / portal passwordless OTP** por este canal: follow-up (define el
   alcance y las plantillas de respuesta).
3. **Riesgo de baneo en envío masivo** (cron de morosidad / blast de avisos por un número
   no-oficial): **antes de apuntar a números reales**, definir **throttling/volumen** (ritmo de
   envío, tope diario, jitter). Los flujos ya son idempotentes, pero un número no-oficial puede
   ser baneado por volumen — decisión de producto/operación, no se inventa aquí.
