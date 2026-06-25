# WhatsApp Gateway (sidecar Baileys)

Gateway de WhatsApp **NO-OFICIAL** (Baileys, WebSocket multidevice — **NO** Puppeteer/Chrome)
que mantiene la sesion de **UN numero de prueba** (pairing por QR) y expone una HTTP API
detras del puerto `WhatsAppPort` del backend. Es **un adaptador mas**: el dia que Meta Cloud
API este listo, se flipa `WHATSAPP_PROVIDER` de vuelta a `meta` sin tocar este sidecar.

## HTTP API (contrato congelado — la consume el adaptador Python del backend)

Todas las rutas (salvo `/healthz`) requieren el header `X-Gateway-Token: <token>`
(== `GATEWAY_TOKEN` == `WHATSAPP_GATEWAY_TOKEN` del backend). Token incorrecto → **401**.

| Metodo | Ruta | Body / Respuesta |
|--------|------|------------------|
| `POST` | `/send` | `{ "to": "<digitos E.164 sin +>", "text": "<string, multilinea ok>" }` → **200** `{ "ok": true, "message_id": "<id>" }` o **200** `{ "ok": false, "error": "<msg>" }` |
| `GET`  | `/status` | `{ "connected": <bool>, "number": "<jid o null>" }` |
| `GET`  | `/qr` | `{ "connected": <bool>, "qr": "<data-url png o null>" }` (el QR tambien se loguea a stdout) |
| `GET`  | `/healthz` | **200** `{ "ok": true }` (liveness, sin token) |

> **Nunca 5xx por errores de negocio** (no conectado, numero invalido, numero no esta en
> WhatsApp): se reportan como **200 `{ ok:false, error }`** para que el adaptador los mapee.

**Entrante:** al recibir un mensaje de texto, hace `POST {INBOUND_CALLBACK_URL}` con header
`X-Gateway-Token` y body `{ "from", "text", "message_id", "timestamp" }`. Si el callback falla,
**loguea y sigue** (no crashea).

## Variables de entorno

| Var | Default | Para que |
|-----|---------|----------|
| `GATEWAY_TOKEN` | (requerido) | Token compartido en ambas direcciones. Sin el, el proceso aborta. |
| `GATEWAY_PORT` | `3000` | Puerto HTTP. |
| `INBOUND_CALLBACK_URL` | (vacio) | URL del webhook del backend (`http://api:8000/api/v1/webhooks/whatsapp-inbound`). |
| `SESSION_DIR` | `/data/session` | Ruta del auth-state de Baileys (montada en un **volumen** → no re-escanear QR). |

## Pairing (operador)

1. `docker compose -f infra/docker-compose.yml up -d whatsapp-gateway`
2. Mira los logs: `docker compose -f infra/docker-compose.yml logs -f whatsapp-gateway`
   → aparece el **QR ASCII**. Escanealo desde el WhatsApp del **numero de prueba**
   (Dispositivos vinculados → Vincular dispositivo). Alternativa: `GET /qr` (data-url png).
3. Verifica: `GET /status` → `{ "connected": true, "number": "<jid>" }`.
4. La sesion se persiste en el volumen → **sobrevive a reinicios** del contenedor sin re-parear.

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
