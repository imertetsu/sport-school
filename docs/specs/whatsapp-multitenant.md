# Epic: whatsapp-multitenant

> WhatsApp gateway **MULTI-TENANT**: **un número por escuela**, vinculado por **QR desde la
> UI** por cada ADMIN. Supersede al MVP `whatsapp-gateway` (un solo número global, ya en
> `main`). Hace multi-tenant los **4 flujos salientes existentes** **sin tocar** ni el puerto
> `WhatsAppPort` (firma CONGELADA) ni los 4 servicios; añade la **UI de vinculación por QR**
> (solo ADMIN, en Ajustes) e **internacionaliza el normalizador** (Perú/Alemania). Spec
> **efímera**: se borra en el commit que cierra el epic (SSS, pilar 1).

## Objetivo y valor
Hoy todas las escuelas comparten **un número global** de prueba (MVP anterior). Este epic da a
**cada escuela su propio número de WhatsApp**: el **ADMIN** lo vincula por **QR desde Ajustes**
y, a partir de ahí, los recordatorios de cobro, recibos, digest de deudores y avisos del muro
salen **desde el número de SU escuela**, con **aislamiento por tenant**. Beneficia a los
tutores y entrenadores (reciben mensajes del número de su propia escuela, no de uno genérico)
y a los ADMIN (autoservicio: vinculan/desvinculan sin pasar por soporte). El normalizador deja
de ser sólo-Bolivia para soportar destinos de Perú/Alemania (preservando el caso BO de 8 dígitos).

## Alcance MVP / Fuera de alcance

### En alcance
- **Sidecar multi-sesión:** un solo proceso mantiene `Map<org_id, Session>`; cada org tiene su
  auth-state Baileys propio (`SESSIONS_ROOT/${org_id}`), su socket, su QR. API HTTP **por-org**.
- **Resolución de org por `ContextVar`** (NO se toca la firma del puerto ni los 4 servicios).
- **Tabla nueva `whatsapp_sesion`** con **RLS por `org_id`** (metadata para la UI; la verdad
  LIVE de connected/QR es el sidecar). Migración **0022**.
- **API backend `/mi-escuela/whatsapp/*`** (solo ADMIN; el backend es el ÚNICO que habla con el
  sidecar; el browser nunca ve token ni URL del sidecar).
- **UI en Ajustes** (solo ADMIN): estado de conexión, generar/vincular QR (polling), desvincular.
- **Normalizador internacional** `normalize_bo_phone(raw, *, default_country_code="591")`
  (compat total con quienes lo llaman con 1 arg; preserva BO 8 dígitos).
- **Webhook entrante con `org_id`**: el sidecar incluye `org_id` en el callback; el backend lo
  recibe y loguea (igual que el MVP, ahora por-org).

### Fuera de alcance (NO en este epic — follow-up)
- **Lógica de auto-respuesta / chatbot / persistencia de conversaciones** del entrante. El
  entrante sigue siendo **recibir + loguear** (ahora con `org_id`). (SRS §2, fase 2/3.)
- **Portal passwordless OTP** del tutor por este canal (SRS §2/§3, fase 2).
- **Multi-tenant para el adaptador OFICIAL de Meta** (`meta.py` sigue mono-número) — futuro.
- **Throttling / tope diario anti-baneo** (ver Decisiones pendientes #2 — NO se implementa aquí).
- No se toca la conciliación de pagos (OpenBCB), ni el webhook de **estados de Meta**
  (`/webhooks/whatsapp`, ruta distinta).

## Reglas de negocio (RF / SRS §)
- **SRS §4.1 / RNF-01 (multi-tenant, RLS por `org_id`):** la sesión de una escuela es **suya**;
  ninguna ruta deja al cliente elegir `org_id` (siempre el del token). La tabla `whatsapp_sesion`
  aísla por `org_id` con el patrón fail-closed (`NULLIF`). El sidecar protege `/sessions/{org}/*`
  con token + topología de red (no se publica al exterior).
- **SRS §4.2/§4.3 (puertos/adaptadores):** el envío sigue detrás de `WhatsAppPort` (firma
  congelada). La multi-tenencia se resuelve por **contexto** (ContextVar), no cambiando el puerto.
- **RNF-02 (privacidad menores):** los mensajes siguen sin datos de ficha médica; el QR de
  pairing **no** es dato personal de menor. Sin cambios respecto al MVP.
- **RNF-05/06 (idempotencia/conciliación):** el saliente NO toca la conciliación; el webhook
  entrante NUNCA escribe pagos. Idempotencia de los 4 flujos se mantiene (no se editan).
- **Aislamiento de secretos:** `X-Gateway-Token` autentica backend↔sidecar; el browser **nunca**
  ve token ni URL del sidecar; nunca se commitean secretos (placeholder en `.env.example`).

---

## Contratos compartidos (CONGELADOS — definidos ANTES de paralelizar)
> Estos contratos son lo que permite lanzar las 4 áreas en paralelo sin solape de archivos.
> Usar **Edit (no Write)** en archivos compartidos existentes. Cambio cruzado → handoff y parar.

### 1) Sidecar multi-sesión (dueño: infra-dev)
Un solo proceso sidecar mantiene `Map<org_id, Session>`; cada Session tiene su
`useMultiFileAuthState(${SESSIONS_ROOT}/${org_id})`, su `sock`, `connected`, `currentQr`,
`selfJid`. Al arranque lista subdirectorios de `SESSIONS_ROOT` y **reconecta cada org**
(secuencial con pequeño backoff). **Se ROMPE el `/send` global** y se reemplaza por la API
por-org (el MVP no está en prod real → sin consumidor que preservar). `/healthz` se mantiene
idéntico (sin token). HTTP API (todas con `X-Gateway-Token` salvo `/healthz`):
```
GET    /healthz                          -> 200 {ok:true}
GET    /sessions/{org_id}/status         -> 200 {org_id, connected:bool, number:string|null}
GET    /sessions/{org_id}/qr             (lazy: si no hay Session, la crea y arranca pairing)
       -> 200 {org_id, connected:false, qr:"data:image/png;base64,..."}
       -> 200 {org_id, connected:false, qr:null, error:"aun no hay QR; reintenta"}
       -> 200 {org_id, connected:true, number:"<digitos>"}
POST   /sessions/{org_id}/send  body {to:"<digitos E.164 sin +>", text:"<no vacío>"}
       -> 200 {ok:true, message_id:"<id>"} | 200 {ok:false, error:"<msg>"}
       ok:false si: número inválido / no registrado en WhatsApp / "sesión no conectada para esta organización".
       NUNCA 5xx por errores de negocio.
DELETE /sessions/{org_id}                (desvincular: sock.logout() + cerrar socket + rm -rf del auth-state + quitar del Map)
       -> 200 {org_id, ok:true}  (idempotente: si no había sesión, igual 200)
```
**Entrante:** el `POST {INBOUND_CALLBACK_URL}` ahora incluye `org_id`: body
`{org_id, from, text, message_id, timestamp}`. Env del sidecar: `SESSIONS_ROOT`
(default `/data/sessions`, **reemplaza `SESSION_DIR`**, en volumen) + los existentes
(`GATEWAY_TOKEN`, `GATEWAY_PORT`, `INBOUND_CALLBACK_URL`).

### 2) Resolución de org SIN tocar la firma del puerto (dueño: backend-dev) — EL PUNTO DELICADO
Módulo NUEVO `backend/app/core/org_context.py` con un `ContextVar[str|None]`:
```
_current_org_id: ContextVar[str|None] = ContextVar("current_org_id", default=None)
def set_current_org_id(org_id: str|None) -> None
def get_current_org_id() -> str|None
```
Se setea en los MISMOS dos puntos donde ya se fija el GUC `app.current_org` (ediciones de
1 línea, **NO** tocan los 4 servicios):
- `backend/app/core/tenant.py::set_tenant_context` (línea ~105, tras el `set_config`):
  `set_current_org_id(str(user.org_id))`.
- `backend/app/workers/tasks.py::_set_org` (línea ~45, tras el `set_config`):
  `set_current_org_id(str(org_id))`.
El adaptador `gateway.py` en `_send()`: lee `org_id = get_current_org_id()`; si `None` →
`WhatsAppSendResult(ok=False, error="sin contexto de organización")` **SIN pegar al sidecar**
(fail-closed); si no, pega a `POST {gateway_url}/sessions/{org_id}/send`. **`meta.py`, el mock
y los 4 servicios NO se tocan.** El puerto NO cambia de firma.

### 3) Persistencia — tabla `whatsapp_sesion` (dueños: backend-dev modelo + db-dev migración)
Tabla NUEVA `whatsapp_sesion` con **RLS por `org_id`** (NO columnas en `organizacion`, que no
tiene RLS). Verdad LIVE (connected/QR) = el sidecar; la BD = metadata para mostrar. Modelo
`backend/app/models/whatsapp_sesion.py` (backend-dev) define la tabla en `Base.metadata`;
**migración `0022_whatsapp_sesion.py`** (db-dev) la materializa + RLS. (El head actual es **0021**
→ la nueva es **0022**.) Forma:
```
whatsapp_sesion: id uuid PK; org_id uuid NOT NULL FK organizacion(id) UNIQUE;
  estado varchar NOT NULL DEFAULT 'DESVINCULADA' CHECK IN ('DESVINCULADA','PENDIENTE_QR','CONECTADA');
  numero varchar NULL (dígitos E.164); vinculado_en timestamptz NULL; created_at/updated_at.
RLS (patrón exacto de 0005_egresos.py): ENABLE+FORCE; policy org_isolation USING/WITH CHECK
  "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid";
  GRANT SELECT,INSERT,UPDATE,DELETE TO latinosport_app.
```
**Serial:** modelo antes que migración (db-dev autogenera desde el modelo). `estado` en BD es
**cache best-effort**; se reconcilia en cada GET status del backend.

### 4) API backend para la UI (dueño: backend-dev)
Router NUEVO `backend/app/api/v1/whatsapp_sesion.py` (prefix `/mi-escuela/whatsapp`, TODOS
`require_role("ADMIN")`, **org SIEMPRE del token**, jamás del cliente — patrón `/mi-escuela`).
El backend es el ÚNICO que habla con el sidecar (el browser nunca ve `X-Gateway-Token` ni la
URL del sidecar; el QR data-url viaja browser←backend←sidecar):
```
GET  /mi-escuela/whatsapp/estado   -> reconcilia y responde
     200 {estado:'DESVINCULADA'|'PENDIENTE_QR'|'CONECTADA', numero:str|null, vinculado_en:datetime|null}
POST /mi-escuela/whatsapp/vincular -> backend->GET sidecar /sessions/{org}/qr (lazy)
     200 {estado:'PENDIENTE_QR', qr:'data:...'|null} | 200 {estado:'CONECTADA', numero:'<digitos>'}
GET  /mi-escuela/whatsapp/qr       -> polling del QR mientras PENDIENTE_QR (mismo shape que vincular)
DELETE /mi-escuela/whatsapp        -> backend->DELETE sidecar; estado='DESVINCULADA', numero=null
     200 {estado:'DESVINCULADA'}
```
Schemas Pydantic NUEVOS `backend/app/schemas/whatsapp_sesion.py` (contrato OpenAPI que consume
el frontend):
- `WhatsAppEstadoOut {estado: Literal['DESVINCULADA','PENDIENTE_QR','CONECTADA'], numero: str|None, vinculado_en: datetime|None}`
- `WhatsAppQrOut {estado: Literal['PENDIENTE_QR','CONECTADA'], qr: str|None, numero: str|None}`

Registrar el router en `backend/app/api/v1/__init__.py` (**Edit**, archivo compartido).

**Frontend (dueño: frontend-dev):** pantalla en **Ajustes** (componente nuevo en
`frontend/src/features/escuela/`), **solo ADMIN**, con: estado de conexión, botón
"Generar/Vincular QR" → muestra el QR (img del data-url) → **polling de `GET /estado` cada ~3s**
hasta CONECTADA (timeout ~2min → "QR expiró, reintenta"); si `qr:null` reintentar `GET /qr`
cada ~2s; botón "Desvincular". Métodos nuevos en `frontend/src/api/client.ts`. (Nota: hay un bug
preexistente menor `'\mi-escuela'` con backslash en `client.ts` ~línea 680; **NO es de este
epic**, dejarlo salvo que rompa.)

### 5) Normalizador internacional (dueño: backend-dev)
**NO renombrar.** `normalize_bo_phone(raw, *, default_country_code="591")` con 2º parámetro
keyword opcional (compat total con `meta.py`/`gateway.py` que la llaman con 1 arg). Reglas:
- limpia no-dígitos y `+`;
- si empieza por **código de país conocido** (mínimo `591`, `51`, `49`, ampliable) y largo E.164
  plausible (8–15 dígitos) → tal cual (idempotente);
- si **no** empieza por código conocido pero tiene **exactamente 8 dígitos** → antepone
  `default_country_code` (preserva BO de 8 dígitos);
- no plausible (<8 o >15, vacío, no numérico) → `None`.

Tests a CONGELAR: `+51 987654321→51987654321`, `+49 1512 3456789→4915123456789`,
`76123456→59176123456`, `59176123456→idempotente`, basura→`None`. El sidecar valida
`^\d{6,15}$` (relajar su regex actual a E.164 si hace falta — infra-dev).

### 6) Seguridad / RLS (transversal)
`org_id` al sidecar = SIEMPRE el del token; ninguna ruta lo expone editable. El sidecar
`/sessions/{org}/*` lo protege `X-Gateway-Token` + topología de red (no se publica al exterior;
solo el backend lo alcanza). RLS de `whatsapp_sesion` aísla por org (fail-closed con `NULLIF`).
`require_role("ADMIN")` en todos los endpoints.

---

## Fases y propiedad de archivos
Cada fase = uno (o pocos) commits.

### Fase 0 — Fundacionales (SERIAL, backend-dev) — son ENTRADA de los demás
- **Nuevo** `backend/app/core/org_context.py` (el `ContextVar` + getters/setters).
- **Nuevo** `backend/app/models/whatsapp_sesion.py` (modelo en `Base.metadata`).
> Serial porque: la migración (Fase 1, db-dev) **autogenera desde el modelo**, y el adaptador
> (Fase 1, backend-dev) **importa el contextvar**. Hasta que existan, los demás no arrancan.

### Fase 1 — Construcción en PARALELO (contratos congelados, sin solape de archivos)
- **infra-dev** — sidecar multi-sesión (`Map<org_id, Session>`, API por-org, callback con
  `org_id`, regex E.164) + **Edit** `docker-compose.yml` (volumen → `SESSIONS_ROOT`) +
  **Edit** `.env.example` (`SESSIONS_ROOT`, doc del cambio de API por-org).
- **db-dev** — migración **`0022_whatsapp_sesion`** + RLS (patrón `0005_egresos.py`). Depende del
  modelo de Fase 0.
- **backend-dev** — wiring del contextvar (2 ediciones de 1 línea: `tenant.py`, `workers/tasks.py`)
  + adaptador multi-tenant (`gateway.py::_send` lee el contextvar, fail-closed) + normalizador
  internacional (`app/core/phone.py`) + webhook entrante con `org_id` + API
  `/mi-escuela/whatsapp/*` (router + schemas) + **Edit** `app/api/v1/__init__.py` (registro) +
  tests.
- **frontend-dev** — pantalla Ajustes WhatsApp (componente nuevo en `features/escuela/`) +
  métodos de cliente en `api/client.ts` (contra los shapes congelados).

> Paralelizable porque ninguna de las 4 áreas comparte archivo con otra y los contratos están
> congelados arriba. Compartidos (`__init__.py`, `Base.metadata`, `docker-compose.yml`/
> `.env.example`, OpenAPI) tienen dueño único por área.

### Fase 2 — Integración E2E (SERIAL, main + operador)
1. Vincular QR REAL desde la UI (ADMIN) de la escuela A → CONECTADA con número.
2. Disparar un cron/flujo de A → confirmar que el mensaje **sale del número de A**.
3. **Aislamiento:** dos orgs consecutivas en el mismo proceso cron → cada una envía desde SU
   número (invariante anti-fuga del contextvar). Org B no ve/usa la sesión de A.
4. Desvincular A → DESVINCULADA; el auth-state de A se borra; A vuelve a `ok:false` al enviar.
5. Gates verdes. Cerrar epic: **borrar esta spec** en el commit final + actualizar `HANDOFF.md`.

**Contratos compartidos (Edit, nunca Write):** `app/api/v1/__init__.py`, `Base.metadata`
(modelo↔migración), `docker-compose.yml`/`.env.example`, OpenAPI (backend produce → frontend
consume).

---

## Criterios de aceptación (verificables — incluyen el invariante de aislamiento)
- **C1:** Vincular por QR desde la UI (ADMIN) → estado `PENDIENTE_QR` con data-url → tras parear,
  `CONECTADA` con número; desvincular → `DESVINCULADA`.
- **C2 (invariante anti-fuga del contextvar — TEST explícito):** un cron/flujo de la escuela A
  envía desde el número de A; **dos orgs consecutivas en el mismo proceso cron envían cada una
  desde SU número** (el `ContextVar` no fuga entre orgs ni queda pegado tras procesar A).
- **C3:** `get_whatsapp_port()`/adaptador **sin contexto de org** → `ok=False` **sin** pegar al
  sidecar (fail-closed, verificado con httpx mockeado: cero requests).
- **C4:** RLS `whatsapp_sesion`: query **sin** contexto → **0 filas**; org B no lee/escribe la
  fila de A.
- **C5:** Normalizador: casos congelados verdes (`+51…`, `+49…`, BO 8 dígitos→`591…`, idempotente,
  basura→`None`); **BO de 8 dígitos intacto**; `meta.py` sigue compilando (firma compat, 1 arg).
- **C6:** El **browser nunca** recibe `X-Gateway-Token` ni la URL del sidecar (el QR viaja
  browser←backend←sidecar).
- **C7:** El sidecar reporta errores de negocio (número inválido / no conectado / sesión no
  conectada para la org) como **200 `ok:false`** (nunca 5xx) → el adaptador los mapea a
  `WhatsAppSendResult(ok=False, error=...)`.
- **C8 (no-regresión):** los **4 flujos existentes intactos** (no se editó ni el puerto, ni
  `meta.py`, ni el mock, ni los 4 servicios); el entrante ahora trae `org_id` y sólo loguea.
- **C9 (gates):** pytest (nuevos + sin romper baseline), ruff, mypy, **import-linter** (el dominio
  NO importa el contextvar ni el adaptador), build front.

## Hard constraints (lo que NO se toca)
- **NO** tocar la firma de `WhatsAppPort`, ni los **4 servicios** de flujo (`recordatorios.py`,
  `recibo_envio.py`, `recordatorio_deudores.py`, `aviso_notificacion.py`), ni `meta.py`, ni el
  mock. El `org` se resuelve por **contextvar**, no por el puerto.
- Migración nueva = **0022** (head actual **0021**). Patrón RLS de **`0005_egresos.py`**
  (`NULLIF`, `FORCE`, policy `org_isolation`, GRANT a `latinosport_app`).
- **NO** añadir columnas a `organizacion` (no tiene RLS): la sesión vive en su propia tabla con RLS.
- **Edit (no Write)** en archivos compartidos: `app/api/v1/__init__.py`, `docker-compose.yml`,
  `.env.example`, `tenant.py`, `workers/tasks.py`. **Secrets nunca** commiteados.
- Mantener el **fail-safe de la fábrica** (`get_whatsapp_port`: credenciales incompletas ⇒ mock,
  nunca tumba el arranque) y la **idempotencia / no-regresión** de los 4 flujos.
- El **sidecar Node** lo posee **infra-dev** (vive en `infra/`); backend-dev **NO** escribe Node.
- `normalize_bo_phone` **NO se renombra**; el 2º parámetro es **keyword-only y opcional** (compat
  con los call-sites de 1 arg).

## Decisiones de producto YA tomadas (no re-preguntar)
- Ir **directo** al epic multi-tenant (no spike).
- **Normalizador internacional SÍ** (Perú/Alemania), preservando BO de 8 dígitos.
- **QR gestionado por cada ADMIN** en Ajustes (autoservicio).
- **Entrante = recibir + loguear con `org_id`** (chatbot/persistencia = futuro).
- Sesión persistida por org en **volumen** (`SESSIONS_ROOT`), reconexión al arranque.

## Decisiones de producto PENDIENTES (para el usuario — NO inventar)
1. **Escuela SIN número vinculado/conectado cuando corre un cron** (recordatorios/deudores): hoy
   el adaptador devuelve `ok:false` → la fila queda `FALLIDO`. ¿Se **reintenta**? ¿Se **avisa al
   ADMIN** de que su WhatsApp está caído (p. ej. **badge** en la UI de Ajustes / banner)? Decisión
   de producto.
2. **Throttling / tope diario anti-baneo** antes de envío masivo con números **no-oficiales**
   (arrastrada del MVP `whatsapp-gateway`): definir **ritmo de envío**, **tope diario**, **jitter**.
   Los 4 flujos ya son idempotentes, pero un número no-oficial puede ser **baneado por volumen**
   (cron de morosidad / blast de avisos). Ahora es **más urgente** que en el MVP porque es el
   **número real de la escuela** el que está en riesgo, no uno de prueba descartable. **No se
   implementa en este epic** hasta decidir los parámetros — escalar a `platform-architect` para
   el diseño técnico (cola con rate-limit en el sidecar vs. en Celery).
3. **Multi-tenant para el adaptador OFICIAL de Meta** (`meta.py` sigue mono-número): futuro; el
   día que Meta esté verificado por escuela, replicar el patrón de contextvar en ese adaptador.
