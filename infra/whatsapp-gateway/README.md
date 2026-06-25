# WhatsApp Gateway (sidecar Baileys, MULTI-SESION)

Gateway de WhatsApp **NO-OFICIAL** (Baileys, WebSocket multidevice — **NO** Puppeteer/Chrome)
**multi-tenant**: un solo proceso mantiene un `Map<org_id, Session>`, **un numero por escuela**
(pairing por QR por org), y expone una HTTP API **por-org** detras del puerto `WhatsAppPort` del
backend. Cada org tiene su propio auth-state (`${SESSIONS_ROOT}/${org_id}`), socket, QR y flag
`connected`: el `sock` **jamas** se cruza entre orgs (ahi vive el aislamiento del envio). Es **un
adaptador mas**: el dia que Meta Cloud API este listo, se flipa `WHATSAPP_PROVIDER` de vuelta a
`meta` sin tocar este sidecar.

## HTTP API (contrato congelado — la consume el adaptador Python del backend)

Todas las rutas (salvo `/healthz`) requieren el header `X-Gateway-Token: <token>`
(== `GATEWAY_TOKEN` == `WHATSAPP_GATEWAY_TOKEN` del backend). Token incorrecto → **401**.
El `org_id` va SIEMPRE en la ruta (`/sessions/{org_id}/...`); el backend usa el del token,
nunca lo elige el cliente. La vieja ruta global `/send` (mono-numero) **ya no existe**.

| Metodo   | Ruta | Body / Respuesta |
|----------|------|------------------|
| `GET`    | `/healthz` | **200** `{ "ok": true }` (liveness, sin token) |
| `GET`    | `/sessions/{org_id}/status` | **200** `{ "org_id", "connected": <bool>, "number": "<digitos o null>" }` |
| `GET`    | `/sessions/{org_id}/qr` | **lazy** (crea la Session y arranca el pairing si no existe). **200** `{ "org_id", "connected": false, "qr": "<data-url png>" }` · o `{ ..., "qr": null, "error": "aun no hay QR; reintenta" }` · o `{ "org_id", "connected": true, "number": "<digitos>" }` |
| `POST`   | `/sessions/{org_id}/send` | `{ "to": "<digitos E.164 sin +, 8-15>", "text": "<string, multilinea ok>" }` → **200** `{ "ok": true, "message_id": "<id>" }` o **200** `{ "ok": false, "error": "<msg>" }` |
| `DELETE` | `/sessions/{org_id}` | desvincular (logout + cerrar socket + `rm -rf` del auth-state + quitar del Map). **200** `{ "org_id", "ok": true }` (**idempotente**: sin sesion previa, igual 200) |

> **Nunca 5xx por errores de negocio** (sesion no conectada para esa org, numero invalido,
> numero no esta en WhatsApp): se reportan como **200 `{ ok:false, error }`** para que el
> adaptador los mapee.

**Entrante:** al recibir un mensaje de texto en la Session de un org, hace
`POST {INBOUND_CALLBACK_URL}` con header `X-Gateway-Token` y body
`{ "org_id", "from", "text", "message_id", "timestamp" }` (el `org_id` es el de la sesion que
recibio el mensaje). Si el callback falla, **loguea y sigue** (no crashea).

## Variables de entorno

| Var | Default | Para que |
|-----|---------|----------|
| `GATEWAY_TOKEN` | (requerido) | Token compartido en ambas direcciones. Sin el, el proceso aborta. |
| `GATEWAY_PORT` | `3000` | Puerto HTTP. |
| `INBOUND_CALLBACK_URL` | (vacio) | URL del webhook del backend (`http://api:8000/api/v1/webhooks/whatsapp-inbound`). El body lleva `org_id`. |
| `SESSIONS_ROOT` | `/data/sessions` | Raiz del auth-state **multi-sesion**: un subdir por org (`${SESSIONS_ROOT}/${org_id}`), montada en un **volumen** → no re-escanear QR. Al arranque lista estos subdirs y reconecta cada org. (Reemplaza al antiguo `SESSION_DIR`.) |

## Pairing (operador, por escuela)

El pairing es **por org**. Normalmente lo dispara el ADMIN desde la UI de Ajustes (el backend
llama a `GET /sessions/{org}/qr`); a mano, para una org `<org_id>`:

1. `docker compose -f infra/docker-compose.yml up -d whatsapp-gateway`
2. `GET /sessions/<org_id>/qr` (con `X-Gateway-Token`) → arranca el pairing (lazy) y devuelve el
   data-url del QR; o mira los logs
   (`docker compose -f infra/docker-compose.yml logs -f whatsapp-gateway`) para el **QR ASCII**.
   Escanealo desde el WhatsApp **de esa escuela** (Dispositivos vinculados → Vincular dispositivo).
3. Verifica: `GET /sessions/<org_id>/status` → `{ "org_id": "<org_id>", "connected": true, "number": "<digitos>" }`.
4. La sesion se persiste en `${SESSIONS_ROOT}/<org_id>` (volumen) → **sobrevive a reinicios** sin
   re-parear; al arrancar, el sidecar reconecta todas las orgs ya pareadas.
5. Desvincular: `DELETE /sessions/<org_id>` (o el boton "Desvincular" de la UI) → borra el
   auth-state de esa org y la quita del proceso.

## Notas

- **Riesgo de baneo:** un numero no-oficial puede ser baneado por volumen. El throttling/tope
  diario es una decision de producto pendiente (ver la spec del epic). No envies blast masivo
  sin definirlo.
- **Sin Puppeteer:** Baileys es WebSocket puro; nada de Chromium headless → imagen ligera, sin OOM.

### Proxy TLS del equipo (gotcha del HANDOFF)

En la maquina de dev hay un proxy TLS corporativo que intercepta `registry.npmjs.org`, los
repos de apt y **tambien el WebSocket a WhatsApp** (`UNABLE_TO_VERIFY_LEAF_SIGNATURE` /
`unable to verify the first certificate`). Por defecto la imagen NO debilita TLS.

- **Build local detras del proxy:** `docker build --build-arg INSECURE_TLS=true ...`
  (o `GATEWAY_BUILD_INSECURE_TLS=true docker compose ... build whatsapp-gateway`,
  ver el `args` del compose). Desactiva la verificacion de certificado SOLO en el build.
- **Pairing en RUNTIME detras del proxy:** Baileys abre un WebSocket TLS a WhatsApp; con el
  proxy interceptando, falla a menos que el contenedor confie en la CA corporativa. Opciones:
  montar la CA y `NODE_EXTRA_CA_CERTS=/ruta/ca.pem` (recomendado), o en una maquina sin el
  proxy (lo normal en prod/operador) parea sin tocar nada. **No** se hornea inseguridad TLS
  de runtime en la imagen.
- **CI/prod:** usar una CA/registry confiable; NO pasar `INSECURE_TLS=true`.
