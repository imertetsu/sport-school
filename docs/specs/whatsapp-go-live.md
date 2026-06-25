# Epic: whatsapp-go-live

> Roadmap de puesta en producción de WhatsApp (Meta Cloud API) para LATINASPORT. El
> **código de envío ya existe** (mock-first, puertos+adaptadores); este epic es
> mayormente **configuración en Meta + plantillas aprobadas + UN ajuste de código**
> (normalización E.164). Spec efímera: se borra en el commit que cierra el epic.

## Objetivo y valor
Que los 4 flujos de WhatsApp **ya construidos** dejen de ser mock y envíen mensajes
reales desde el número **WhatsApp Business +591 60792692**, beneficiando a tutores
(recordatorios de cobro y recibos) y entrenadores (digest de deudores, avisos del muro).
Arrancamos por **envío saliente** (sin webhook entrante todavía).

## Alcance MVP
- Encender los **4 flujos** (5 plantillas) en producción vía `WHATSAPP_PROVIDER=meta`.
- Alta del número en Meta Cloud API + token permanente + plantillas UTILITY aprobadas.
- **Track C (código):** normalizar teléfonos a **E.164** boliviano antes de llamar al puerto.
- Config de prod gateada (secrets), sin tocar la conciliación de pagos.

## Fuera de alcance (no en este epic)
- **Webhook entrante / conexión a `recordatorio_pago` por `message_id`** → Track E,
  **bloqueado por dominio+HTTPS** (hoy prod es IP:puerto). El handshake/firma ya están
  codificados pero requieren HTTPS público; se planifica aquí pero NO se ejecuta hasta
  que llegue el dominio.
- **QR como imagen** en la cabecera de las plantillas de cobro (TODO en `meta.py`,
  requiere subir media a Meta). Hoy el enlace de cobro va como **variable de texto**
  `{{5}}` y funciona; mejora opcional posterior.
- Chatbot entrante, portal tutor passwordless, factura SIN (Fase 2/3 — SRS §2).

## Estado actual (lo que YA existe en código)
- **Puerto** `WhatsAppPort` (`send_template`, `send_text`) en `backend/app/domain/ports/whatsapp.py`.
  `to` se documenta como **E.164 sin `+`**. `send_text` admite multilínea.
- **Adaptador real** `MetaCloudWhatsAppAdapter` (`backend/app/adapters/whatsapp/meta.py`):
  POST a `graph.facebook.com/{graph_version}/{phone_number_id}/messages`; arma
  `template` con `body` params posicionales; **no lanza**, reporta vía `ok`/`error`.
  Header con imagen está como **TODO** (omite la cabecera, no rompe el cuerpo).
- **Mock** `MockWhatsAppAdapter`. **Factory** `get_whatsapp_port()`
  (`backend/app/services/deps.py`): `WHATSAPP_PROVIDER=meta` **+** `phone_number_id` **y**
  `access_token` no vacíos ⇒ adaptador real; cualquier otro caso ⇒ mock (fail-safe, nunca
  tumba el arranque; loguea WARNING si era `meta` sin credenciales).
- **Webhook** `GET/POST /api/v1/webhooks/whatsapp` (`backend/app/api/v1/webhooks/whatsapp.py`):
  handshake `hub.challenge` contra `whatsapp_verify_token`; POST valida
  `X-Hub-Signature-256` (HMAC-SHA256) si hay `app_secret`; **solo loguea** estados y ACK 200.
  NO concilia pagos (el cobro lo concilia `POST /webhooks/openbcb`).
- **Env vars** ya definidas en `backend/app/core/config.py`: `whatsapp_provider`
  (default `noop`), `whatsapp_phone_number_id`, `whatsapp_access_token`, `whatsapp_waba_id`,
  `whatsapp_verify_token`, `whatsapp_app_secret`, `whatsapp_graph_version` (`v21.0`),
  `recordatorio_qr_dias_antes` (3).
- **4 flujos / 5 plantillas** (todos pasan `header_image=None` hoy):
  - `recordatorios.py` → `recordatorio_cuota_qr` (PROXIMO_VENCIMIENTO) y
    `morosidad_cuota_qr` (MOROSIDAD); destinatario = `tutor.telefono` (responsable_pago).
  - `recibo_envio.py` → `recibo_pago`; destinatario = `tutor.telefono`.
  - `recordatorio_deudores.py` → `resumen_deudores` (plantilla) **+ `send_text`** con el
    detalle multilínea; destinatario = `entrenador.telefono`.
  - `aviso_notificacion.py` → `nuevo_aviso`; destinatario = `tutor.telefono`/`entrenador.telefono`.

## Reglas de negocio (RF / SRS)
- **RNF-07 (plantillas + costo):** en frío SOLO plantillas pre-aprobadas; texto libre solo
  dentro de la ventana de servicio de 24h. Respetado por el código actual.
- **RNF-01 / SRS §4.1 (RLS):** los servicios corren bajo `app.current_org` del caller; este
  epic NO cambia el modelo de tenancy ni añade migraciones.
- **RNF-05/06 (idempotencia/conciliación):** el envío saliente NO toca la conciliación; el
  cobro QR se concilia por `POST /webhooks/openbcb` (idempotente por `transaccion_id`). El
  webhook de WhatsApp NO debe escribir pagos.
- **RNF-02 (privacidad menores):** no se envían datos de ficha médica por WhatsApp; los
  mensajes llevan nombre del deportista, monto, escuela, enlaces tokenizados.

---

## Tracks A–E (ordenados por dependencias y tiempos de espera)

```
Track A (alta Meta, usuario) ─┐
                              ├─> Track D (config prod, gated) ─> 4 flujos en vivo (saliente)
Track B (plantillas, Meta) ───┘
Track C (código E.164) ────── EN PARALELO a todo (backend-dev), prerrequisito de D
Track E (webhook) ──────────── BLOQUEADO por dominio+HTTPS (futuro)
```
**Empezar YA en paralelo:** Track A, Track B y Track C. (B tarda **días** en Meta; C es
código independiente; A tiene tiempos de espera de verificación.) D espera a A+B+C. E espera al dominio.

### Track A — Alta en Meta (lo ejecuta el USUARIO)
Estado en Meta **sin confirmar** → este track incluye descubrimiento. Salida: credenciales
para Track D (`phone_number_id`, `waba_id`, token permanente, `app_secret`).

**CHECKLIST (paso a paso):**
1. [ ] **Meta Business Manager** (business.facebook.com): tener/crear el Business Portfolio
   de la escuela. Anotar el **Business ID**.
2. [ ] **App de Meta for Developers** (developers.facebook.com): crear App tipo *Business* y
   **añadir el producto "WhatsApp"**. Vincular la App al Business Portfolio del paso 1.
3. [ ] **WhatsApp → API Setup:** se crea una **WABA** (WhatsApp Business Account). Anotar el
   **`waba_id`** (= `WHATSAPP_WABA_ID`).
4. [ ] **Añadir el número +591 60792692** a la Cloud API ("Add phone number").
   ⚠️ **El número NO puede estar activo en la app de WhatsApp / WhatsApp Business**: la Cloud
   API lo **consume**. Si ya está en uso en un teléfono, primero **borrar la cuenta de
   WhatsApp de ese número** (Ajustes → Cuenta → Eliminar cuenta) antes de registrarlo.
5. [ ] **Verificar el número** (código por SMS/llamada) y fijar el **display name** de la cuenta.
6. [ ] Anotar el **`phone_number_id`** (= `WHATSAPP_PHONE_NUMBER_ID`). ⚠️ NO confundir el
   `phone_number_id` (id interno de Meta) con el número en formato +591… .
7. [ ] **Token PERMANENTE (System User):** el token de prueba de la pantalla "API Setup"
   **caduca en 24h** y NO sirve para prod. Crear en Business Settings → **Users → System
   Users** un system user (rol Admin), asignarle la **App** y la **WABA** como assets, y
   **Generate Token** con permisos **`whatsapp_business_messaging`** y
   **`whatsapp_business_management`**, **sin expiración**. Ése es `WHATSAPP_ACCESS_TOKEN`.
8. [ ] **App Secret:** App → Settings → Basic → **App Secret** (= `WHATSAPP_APP_SECRET`,
   solo se necesita para el webhook entrante / Track E).
9. [ ] **Business Verification:** iniciar la verificación del negocio (documentos de la
   empresa). Sin verificar, el número queda en **límite bajo (~250 conversaciones/día)** y
   no puede subir de tier. Tarda; **arrancar pronto** (no bloquea el primer envío).

**Salida del Track A (entregar al usuario / a Track D):** `WHATSAPP_PHONE_NUMBER_ID`,
`WHATSAPP_WABA_ID`, `WHATSAPP_ACCESS_TOKEN` (permanente), `WHATSAPP_APP_SECRET`. Inventar un
`WHATSAPP_VERIFY_TOKEN` (string aleatorio nuestro, lo usaremos en Track E).

### Track B — Plantillas (crear en Meta y enviar a aprobar — tarda DÍAS, arrancar ya)
Crear en **WhatsApp Manager → Message Templates**. Las 5 son **categoría UTILITY**, idioma
**`es`** (coincide con `_LANG_CODE = "es"` en el código). Las variables son **posicionales
`{{1}}…{{n}}`** y deben respetar el **ORDEN EXACTO** con el que el código pasa `body_params`
(si no, el mensaje sale con los datos cruzados). Cuerpo sugerido editable; lo que NO se
puede cambiar es el **número y orden** de variables.

| Plantilla | Cat. | Vars (orden EXACTO = `body_params`) | Cuerpo sugerido |
|-----------|------|-------------------------------------|-----------------|
| `recordatorio_cuota_qr` | UTILITY | {{1}} deportista · {{2}} monto (Bs X.XX) · {{3}} escuela · {{4}} vence DD/MM/YYYY · {{5}} enlace de cobro | `Hola, recordatorio de cuota de {{1}} en {{3}}: {{2}}, vence el {{4}}. Pague aquí: {{5}}` |
| `morosidad_cuota_qr` | UTILITY | {{1}} deportista · {{2}} monto · {{3}} escuela · {{4}} vence DD/MM/YYYY · {{5}} enlace de cobro | `La cuota de {{1}} en {{3}} está vencida: {{2}} (venció el {{4}}). Regularice aquí: {{5}}` |
| `recibo_pago` | UTILITY | {{1}} deportista · {{2}} monto · {{3}} escuela · {{4}} N° recibo · {{5}} enlace PDF | `Pago recibido de {{1}} en {{3}}: {{2}}. Recibo {{4}}. Descárguelo aquí: {{5}}` |
| `resumen_deudores` | UTILITY | {{1}} entrenador · {{2}} sucursal · {{3}} nº deudores · {{4}} monto total | `Hola {{1}}, resumen de deudores en {{2}}: {{3}} deportistas, total Bs {{4}}. Detalle a continuación.` |
| `nuevo_aviso` | UTILITY* | {{1}} escuela · {{2}} título · {{3}} cuerpo | `{{1}} informa: {{2}}. {{3}}` |

\* **`nuevo_aviso`** puede clasificarse por Meta como **MARKETING** (no transaccional) →
requeriría **opt-in** y cuenta como conversación de marketing. Enviarla como UTILITY y, si
Meta la rechaza/reclasifica, **DECISIÓN DE PRODUCTO** (ver abajo): redactarla como
notificación de cuenta o aceptar MARKETING+opt-in.

**Notas Track B:**
- El código manda **monto pre-formateado** (`f"Bs {monto:.2f}"`) en `recordatorio/morosidad/recibo`,
  pero en `resumen_deudores` `{{4}}` llega como `f"Bs {monto_total:.2f}"` también. Mantener el
  literal "Bs" en el cuerpo o quitarlo de la variable es cosmético; **no cambia el código**.
- ⚠️ Meta **NO permite saltos de línea** dentro de una variable de plantilla. Ninguna de las 5
  mete texto multilínea en un `{{n}}` (el detalle de deudores va por `send_text`, no por la
  plantilla) → OK.
- Aprobación: tras enviar, Meta tarda de minutos a **días**. Mientras no estén **APPROVED**,
  los envíos reales fallan (el adaptador lo reporta como `error`, no rompe).

### Track C — Código: normalización E.164 boliviano (backend-dev, EN PARALELO)
**Problema:** hoy se pasa `tutor.telefono` / `entrenador.telefono` **crudo** al puerto (p.ej.
`"+591 76123456"`, `"76123456"`, `"591 7612-3456"`). Meta exige el `to` en **E.164 sin `+`
ni espacios ni guiones** (dígitos con código de país), p.ej. `59176123456`. Sin normalizar,
Meta **rechaza** el envío.

**Alcance del fix (solo `backend/`):**
- Un helper de normalización (sugerido `app.services` o `app.core`), p.ej.
  `to_e164_bolivia(telefono: str | None) -> str | None`:
  - Quita espacios, guiones, paréntesis y el `+`.
  - Si empieza con `591` y tiene largo de país → lo deja.
  - Si son **8 dígitos** (móvil BO, empieza con 6 o 7) → antepone `591`.
  - Acepta `00591…` → `591…`.
  - Entrada inválida/no normalizable → `None` (se trata como "sin teléfono": fila
    `FALLIDO`/`SIN_TELEFONO`, **nunca** se llama al puerto con basura).
- **Aplicarlo en los 4 servicios**, justo antes de construir `WhatsAppTemplateMessage`/
  `WhatsAppTextMessage` (es decir, sobre `telefono`/`destino`):
  `recordatorios.py`, `recibo_envio.py`, `recordatorio_deudores.py`, `aviso_notificacion.py`.
  La columna `destino` que se persiste debería guardar el **número normalizado** (auditoría
  coherente con lo enviado).
- **Tests** (mock): número crudo con espacios/`+` → normalizado; 8 dígitos → con `591`;
  inválido → `None` ⇒ ruta "sin teléfono" sin llamar al puerto. **No** romper la idempotencia
  ni el conteo `enviado_ahora`/`enviados` existentes.
- **Decisión técnica de backend-dev:** ubicación exacta del helper y si el invariante "móvil
  BO empieza con 6/7" se valida estricto o laxo (el reparto de decisiones técnicas es del agente).
- **Hard constraints:** NO tocar `frontend/`, `migrations/`, `infra/`; NO añadir migración (no
  se cambia el esquema; se normaliza al vuelo); NO cambiar el puerto ni el adaptador `meta.py`;
  usar **Edit** en los 4 servicios. No cambiar firmas públicas de las funciones de servicio.

### Track D — Config de producción (cuando A + B + C estén listos; GATED)
- Setear en prod (servidor `177.222.39.139`, `/opt/latinosport`, vía `.env` — **secrets, nunca
  commitear**): `WHATSAPP_PROVIDER=meta`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`,
  `WHATSAPP_WABA_ID`, `WHATSAPP_GRAPH_VERSION=v21.0`. (`_VERIFY_TOKEN`/`_APP_SECRET` solo si ya
  se hace Track E.)
- La factory `get_whatsapp_port()` pasa a real **automáticamente** con esas 3 (`provider=meta`
  + `phone_number_id` + `access_token`). Sin credenciales completas degrada al mock (no rompe).
- **El envío saliente YA funciona sin webhook** (los 4 flujos son salientes). No requiere Track E.
- Verificación: un envío de prueba a un número propio por cada flujo (idealmente con plantillas
  ya APPROVED). Si una plantilla aún no está aprobada, ese flujo reporta `error` y queda `FALLIDO`
  (auditado), sin romper el resto.
- **infra-dev** posee `.env.example`/compose: asegurar que las 7 vars whatsapp estén
  documentadas en `.env.example` (ya lo están como placeholders) y que el worker/API las lean.

### Track E — Webhook entrante (FUTURO: cuando llegue el dominio)
Bloqueado: **Meta exige HTTPS público** para el webhook; prod hoy es IP:puerto sin TLS.
1. [ ] **Dominio + HTTPS** (infra-dev): apuntar un dominio al servidor + **Caddy o nginx +
   Let's Encrypt** (TLS termina ahí; proxy a la API). (Coordinar con el fix del job de deploy
   pendiente en HANDOFF.)
2. [ ] **Configurar el webhook en Meta** (WhatsApp → Configuration): Callback URL
   `https://<dominio>/api/v1/webhooks/whatsapp`, **Verify Token** = `WHATSAPP_VERIFY_TOKEN`
   (el handshake `GET` ya está codificado), suscribir el campo **`messages`**. Setear en prod
   `WHATSAPP_VERIFY_TOKEN` y `WHATSAPP_APP_SECRET` (firma `X-Hub-Signature-256` ya validada).
3. [ ] **Conectar el webhook a `recordatorio_pago` por `message_id`** (backend-dev, futuro):
   hoy el POST **solo loguea**. Mapear estados (sent/delivered/read/failed) a la fila por
   `provider_message_id`. ⚠️ Necesita **contexto de tenant/RLS** o un resolver
   **SECURITY DEFINER** (como OpenBCB), porque el webhook no trae `org_id` ni JWT. Diseño
   técnico a cargo de `platform-architect` cuando se aborde. **NO** conciliar pagos aquí
   (eso es OpenBCB). Requiere migración solo si se persiste el estado de entrega.

---

## Contratos compartidos (definir ANTES de paralelizar)
- **`to` del puerto = E.164 sin `+`** (ya documentado en `domain/ports/whatsapp.py`). Track C
  es quien garantiza que lo que llega al puerto cumple ese contrato. Backend produce; el
  adaptador `meta.py` consume tal cual (no re-normaliza).
- **Nombres y orden de variables de las 5 plantillas** (tabla Track B) = contrato entre Meta
  (Track B) y los 4 servicios (código existente). Cambiar el orden de `body_params` en código
  **obliga** a re-aprobar la plantilla, y viceversa. **Congelado** por esta spec.
- **Nombres de plantilla** (literales en código): `recordatorio_cuota_qr`, `morosidad_cuota_qr`,
  `recibo_pago`, `resumen_deudores`, `nuevo_aviso`. Deben crearse en Meta con **ese mismo
  nombre exacto** e idioma `es`.
- **Env vars** (`config.py` ↔ `.env.example`): contrato infra-dev ↔ backend, ya existente.

## Criterios de aceptación (verificables)
- **C-A:** el número +591 60792692 aparece en la Cloud API con `phone_number_id` y `waba_id`
  anotados, y existe un **token permanente** (no caduca a 24h). (Track A.)
- **C-B:** las 5 plantillas aparecen **APPROVED** en WhatsApp Manager, idioma `es`, con el
  número/orden de variables de la tabla.
- **C-C1:** `to_e164_bolivia("+591 7612-3456") == "59176123456"`; `("76123456") == "59176123456"`;
  `("00591 76123456") == "59176123456"`; entrada inválida → `None`.
- **C-C2:** con `None` (teléfono no normalizable), cada uno de los 4 servicios sigue la ruta
  "sin teléfono" (`FALLIDO`/`SIN_TELEFONO`) **sin llamar al puerto**; idempotencia y conteos
  intactos (tests verdes, sin migración nueva).
- **C-D:** en prod con `WHATSAPP_PROVIDER=meta` + las 3 credenciales, `get_whatsapp_port()`
  devuelve `MetaCloudWhatsAppAdapter`; un envío de prueba de cada flujo llega al teléfono o se
  registra `FALLIDO` con `error` legible (sin romper). Sin credenciales → sigue en mock.
- **C-borde dominio:** un envío con teléfono ausente o basura **nunca** llama a Meta; un flujo
  con plantilla no aprobada falla **solo ese flujo** (los demás siguen). El webhook de WhatsApp
  **no** modifica pagos.
- **C-E (cuando aplique):** GET handshake responde el `hub.challenge`; POST con firma inválida
  → 403; POST válido → 200 y loguea (o actualiza `recordatorio_pago` si se hizo el paso E.3).

---

## Gotchas / riesgos
- **El número no puede estar activo en la app de WhatsApp normal.** La Cloud API lo consume;
  si está vivo en un teléfono hay que **borrar esa cuenta** antes de registrarlo (Track A.4).
- **E.164 obligatorio:** Meta rechaza números con `+`, espacios o guiones. Los datos actuales
  (`tutor.telefono`/`entrenador.telefono`) están crudos → **Track C lo resuelve**; sin Track C,
  el go-live envía a Meta números que rechaza.
- **Token de 24h:** el token de la pantalla "API Setup" caduca; usar **System User token sin
  expiración** o los envíos morirán al día siguiente del go-live (Track A.7).
- **Ventana de 24h en `resumen_deudores`:** el flujo manda **plantilla + un `send_text`** con
  el detalle multilínea. El **texto libre** solo se entrega si el entrenador escribió a la
  cuenta en las últimas 24h; si no, la **plantilla resumen igual llega** pero el detalle no.
  Meta **NO permite saltos de línea en variables de plantilla**, así que la lista multilínea
  **no** se puede meter como `{{param}}`. → **DECISIÓN ABIERTA** (abajo). NO resuelta en esta spec.
- **QR como imagen** en `recordatorio_cuota_qr`/`morosidad_cuota_qr`: hoy el enlace de cobro va
  como variable de texto `{{5}}` y funciona. Mandar el QR como **imagen en la cabecera** exige
  subir el media a Meta primero (TODO en `meta.py`, `header_image` se ignora) → opcional/posterior.
- **Webhook necesita HTTPS** (prod hoy IP:puerto) → Track E depende del dominio en camino.
- **Límite sin Business Verification:** ~**250 conversaciones/día**. Para una escuela con muchos
  tutores, el blast de avisos o el cron de morosidad podría toparlo. Iniciar verificación pronto
  (Track A.9). Los flujos son idempotentes, así que un fallo por límite queda `FALLIDO` y se
  reintenta el siguiente ciclo, sin duplicar.
- **`nuevo_aviso` puede caer en MARKETING** (no transaccional) → opt-in + categoría distinta.
  Ver decisión abierta de plantilla.

## Decisiones de producto YA tomadas
- Encender los **4 flujos** (5 plantillas).
- Arrancar por **envío saliente**; webhook entrante **después** (Track E).
- **Dominio en camino** → HTTPS y webhook se hacen cuando llegue.
- **Estado en Meta sin confirmar** → Track A incluye el descubrimiento/alta paso a paso.

## Decisiones de producto PENDIENTES (para el usuario — NO inventar)
1. **Detalle de deudores y la ventana de 24h** (`resumen_deudores`). El detalle multilínea no
   cabe en una variable de plantilla (Meta lo prohíbe) y como `send_text` solo se entrega si el
   entrenador escribió en las últimas 24h. Elegir una:
   - **(a)** Mandar el detalle como **PDF/documento** adjunto (entrega garantizada, pero
     requiere generar el PDF y subir el media a Meta → trabajo extra de código).
   - **(b)** **Aceptar la limitación de 24h**: la plantilla resumen **siempre** llega; el
     detalle por texto libre es **best-effort** (solo si hay sesión abierta). Cero trabajo extra.
   - **(c)** El entrenador ve el **detalle en la app** (la plantilla lo invita a abrirla); no se
     manda texto libre.
2. **Clasificación de `nuevo_aviso`** si Meta la marca como **MARKETING**: ¿reescribir el
   copy como notificación de cuenta para que pase como UTILITY, o **aceptar MARKETING + opt-in**
   de tutores? (Solo relevante si Meta la rechaza como UTILITY en Track B.)
3. **¿QR como imagen** en los recordatorios de cobro (mejora opcional, fuera del MVP de este
   epic) entra en este epic o se difiere?
