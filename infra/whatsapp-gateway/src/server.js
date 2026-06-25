// LatinoSport — WhatsApp Gateway (sidecar Baileys, WebSocket multidevice) MULTI-SESION.
//
// Un solo proceso mantiene un Map<org_id, Session>: CADA escuela (org) tiene su propio
// auth-state Baileys (${SESSIONS_ROOT}/${org_id}), su socket, su QR, su selfJid y su flag
// `connected`. Jamas se cruza un `sock` entre orgs — el aislamiento multi-tenant del envio
// vive aqui. NO usa Puppeteer/Chrome: Baileys habla el protocolo multidevice por WebSocket
// directo (sin navegador → sin OOM).
//
// HTTP API por-org (todas con header `X-Gateway-Token`, salvo /healthz):
//   GET    /healthz                  -> 200 { ok:true }                              (sin token)
//   GET    /sessions/:orgId/status   -> 200 { org_id, connected, number }
//   GET    /sessions/:orgId/qr       -> 200 { org_id, connected:false, qr:<data-url|null> [,error] }
//                                       | 200 { org_id, connected:true, number }   (lazy: crea la Session)
//   POST   /sessions/:orgId/send     { to, text }                  -> 200 { ok, message_id } | { ok:false }
//                                    { to, text, image, mime }     -> idem (envia imagen + caption)
//   DELETE /sessions/:orgId          -> 200 { org_id, ok:true }                     (desvincular, idempotente)
//
// Entrante: al llegar un mensaje a la Session de un org hace POST {INBOUND_CALLBACK_URL} con el
// mismo token (el org_id sale de la Session que recibio el mensaje). Dos formas:
//   - TEXTO:  { org_id, from, tipo:"text",  text, message_id, timestamp }
//   - IMAGEN: { org_id, from, tipo:"image", media:"<base64>", mime, caption, message_id, timestamp }
// (la imagen se descarga con downloadMediaMessage y se reenvia en base64). Tolera que el callback
// o la descarga del media fallen (loguea, no crashea).
//
// Persistencia: useMultiFileAuthState en ${SESSIONS_ROOT}/${org_id} (SESSIONS_ROOT montado en
// un volumen del compose) → no re-escanear QR en cada reinicio. Al arranque lista los
// subdirectorios de SESSIONS_ROOT y reconecta cada org (secuencial con pequeno backoff).
// Reconexion automatica al caerse.
//
// IMPORTANTE (contrato): los errores de NEGOCIO (no conectado, numero invalido, etc.)
// se reportan SIEMPRE como 200 { ok:false, error }. Nunca 5xx por ellos. El 5xx queda
// reservado a fallos verdaderamente inesperados del propio gateway.

import { existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import express from 'express';
import pino from 'pino';
import qrcode from 'qrcode';
// Baileys (ESM): `makeWASocket` es el default export; los helpers
// (useMultiFileAuthState, fetchLatestBaileysVersion, DisconnectReason, isJidUser) son
// named exports. Importarlos como named evita "X is not a function" al destructurar el default.
import makeWASocket, {
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
  isJidUser,
  downloadMediaMessage,
} from '@whiskeysockets/baileys';

// --- Config por entorno -----------------------------------------------------
const GATEWAY_TOKEN = process.env.GATEWAY_TOKEN || '';
const GATEWAY_PORT = parseInt(process.env.GATEWAY_PORT || '3000', 10);
const INBOUND_CALLBACK_URL = process.env.INBOUND_CALLBACK_URL || '';
// Raiz del auth-state multi-sesion: cada org vive en ${SESSIONS_ROOT}/${org_id}.
// Se monta en un volumen (ver docker-compose.yml). REEMPLAZA al antiguo SESSION_DIR.
const SESSIONS_ROOT = process.env.SESSIONS_ROOT || '/data/sessions';

const log = pino({
  level: process.env.LOG_LEVEL || 'info',
  transport: process.env.LOG_PRETTY ? { target: 'pino-pretty' } : undefined,
});

if (!GATEWAY_TOKEN) {
  // Sin token el endpoint quedaria abierto a internet. Fallar rapido es preferible.
  log.error('GATEWAY_TOKEN no esta definido. Aborta: la API requiere un token compartido.');
  process.exit(1);
}

if (!existsSync(SESSIONS_ROOT)) {
  mkdirSync(SESSIONS_ROOT, { recursive: true });
}

// --- Estado multi-sesion ----------------------------------------------------
// Map<org_id, Session>. Cada Session encapsula TODO el estado de un org: nunca se comparte
// `sock`, `connected`, `selfJid` ni `currentQr` entre orgs.
//   { orgId, sock, connected, selfJid, currentQr, starting }
const sessions = new Map();

// Valida que el orgId sea un identificador de directorio seguro (sin path traversal).
// Aceptamos lo tipico de un UUID/slug: letras, digitos, guion y guion-bajo.
function isValidOrgId(orgId) {
  return typeof orgId === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(orgId);
}

// Directorio de auth-state de un org dentro de SESSIONS_ROOT.
function sessionDir(orgId) {
  return join(SESSIONS_ROOT, orgId);
}

// Normaliza un JID a solo digitos (p.ej "59176123456@s.whatsapp.net:12" -> "59176123456").
function jidToDigits(jid) {
  if (!jid) return null;
  const user = jid.split('@')[0] || '';
  return user.split(':')[0] || null;
}

// Crea (si no existe) y devuelve la Session de un org. NO arranca el socket.
function getOrCreateSession(orgId) {
  let session = sessions.get(orgId);
  if (!session) {
    session = {
      orgId,
      sock: null,
      connected: false,
      selfJid: null,
      currentQr: null,
      starting: false,
    };
    sessions.set(orgId, session);
  }
  return session;
}

// --- Baileys: arranque, QR, reconexion, entrante (POR SESSION) --------------
async function startSession(session) {
  const { orgId } = session;
  if (session.starting) return session.sock;
  session.starting = true;

  try {
    const dir = sessionDir(orgId);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }
    const { state, saveCreds } = await useMultiFileAuthState(dir);
    const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));

    const sock = makeWASocket({
      version,
      auth: state,
      logger: log.child({ mod: 'baileys', org_id: orgId }),
      // markOnlineOnConnect:false evita "robar" las notificaciones push del telefono.
      markOnlineOnConnect: false,
      // Sin printQRInTerminal (deprecado): el QR lo logueamos/servimos nosotros.
    });
    session.sock = sock;

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        session.currentQr = qr;
        session.connected = false;
        // Loguear el QR a stdout para diagnostico (la UI lo obtiene via GET /sessions/:org/qr).
        try {
          const ascii = await qrcode.toString(qr, { type: 'terminal', small: true });
          log.info({ org_id: orgId },
            '\n========== ESCANEA ESTE QR (org ' + orgId + ') ==========\n' +
            ascii +
            '\n=======================================================\n' +
            '(o GET /sessions/' + orgId + '/qr para el data-url de la imagen)');
        } catch (err) {
          log.warn({ err: err.message, org_id: orgId }, 'no se pudo renderizar el QR ASCII; usa GET /sessions/:org/qr');
        }
      }

      if (connection === 'open') {
        session.connected = true;
        session.currentQr = null;
        session.selfJid = sock?.user?.id || null;
        log.info({ org_id: orgId, number: jidToDigits(session.selfJid) }, 'WhatsApp conectado');
      }

      if (connection === 'close') {
        session.connected = false;
        const statusCode = lastDisconnect?.error?.output?.statusCode;
        const loggedOut = statusCode === DisconnectReason.loggedOut;
        log.warn({ statusCode, loggedOut, org_id: orgId }, 'WhatsApp desconectado');
        // Si la Session ya fue eliminada del Map (DELETE), no reintentar: es un cierre deliberado.
        if (!sessions.has(orgId) || sessions.get(orgId) !== session) {
          return;
        }
        if (loggedOut) {
          // Sesion invalidada (logout desde el telefono): hay que re-parear (nuevo QR).
          session.selfJid = null;
          session.currentQr = null;
          session.starting = false;
          startSession(session).catch((e) => log.error({ err: e.message, org_id: orgId }, 'fallo re-arranque tras logout'));
        } else {
          // Caida transitoria: reconectar.
          session.starting = false;
          setTimeout(() => {
            if (sessions.get(orgId) === session) {
              startSession(session).catch((e) => log.error({ err: e.message, org_id: orgId }, 'fallo reconexion'));
            }
          }, 2000);
        }
      }
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
      if (type !== 'notify') return;
      for (const msg of messages) {
        try {
          await handleIncoming(orgId, msg);
        } catch (err) {
          log.error({ err: err.message, org_id: orgId }, 'error procesando mensaje entrante (ignorado)');
        }
      }
    });

    return sock;
  } finally {
    session.starting = false;
  }
}

// Extrae el texto plano de un mensaje (texto simple o caption de media).
function extractText(message) {
  if (!message) return null;
  return (
    message.conversation ||
    message.extendedTextMessage?.text ||
    message.imageMessage?.caption ||
    message.videoMessage?.caption ||
    null
  );
}

// POST helper al webhook del backend (mismo token). Tolera fallos: el edge no debe
// perder el proceso por un callback caido (loguea y sigue).
async function postInbound(orgId, payload) {
  if (!INBOUND_CALLBACK_URL) {
    log.warn({ org_id: orgId }, 'INBOUND_CALLBACK_URL no configurado; no se reenvia el entrante');
    return;
  }
  try {
    const res = await fetch(INBOUND_CALLBACK_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Gateway-Token': GATEWAY_TOKEN,
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) {
      log.warn({ status: res.status, org_id: orgId }, 'el callback entrante respondio no-2xx (ignorado)');
    }
  } catch (err) {
    log.warn({ err: err.message, org_id: orgId }, 'fallo el POST al callback entrante (ignorado)');
  }
}

// Reenvia un mensaje entrante (texto o imagen) al webhook del backend, etiquetado con su
// org_id. Tolera fallos: el edge no debe perder el proceso por un callback (o una descarga
// de media) caidos.
//
// Contrato del body (C4):
//   - TEXTO: { org_id, from, tipo:"text", text, message_id, timestamp }
//     (el backend trata la ausencia de `tipo` como texto: retrocompat).
//   - IMAGEN: { org_id, from, tipo:"image", media:"<base64>", mime, caption:"<text|null>",
//              message_id, timestamp }
async function handleIncoming(orgId, msg) {
  // Ignorar lo que enviamos nosotros y lo que no es de un usuario (grupos, status, etc.).
  if (msg.key?.fromMe) return;
  const remoteJid = msg.key?.remoteJid;
  if (!remoteJid || !isJidUser(remoteJid)) return;

  const from = jidToDigits(remoteJid);
  const message_id = msg.key?.id || null;
  // messageTimestamp puede ser number o Long; lo normalizamos a epoch (segundos).
  const timestamp = Number(msg.messageTimestamp) || Math.floor(Date.now() / 1000);

  const imageMessage = msg.message?.imageMessage;

  // --- Comprobante (imagen): descarga el media, base64 -> callback tipo:"image" ----------
  if (imageMessage) {
    let mediaB64;
    try {
      const buffer = await downloadMediaMessage(
        msg,
        'buffer',
        {},
        { logger: log.child({ mod: 'media', org_id: orgId }), reuploadRequest: msg.sock?.updateMediaMessage },
      );
      mediaB64 = Buffer.from(buffer).toString('base64');
    } catch (err) {
      // Si la descarga del media falla, no revienta el sidecar: se ignora el entrante.
      log.warn({ err: err.message, org_id: orgId, message_id }, 'fallo descargando media (imagen entrante ignorada)');
      return;
    }
    const payload = {
      org_id: orgId,
      from,
      tipo: 'image',
      media: mediaB64,
      mime: imageMessage.mimetype || null,
      caption: imageMessage.caption || null,
      message_id,
      timestamp,
    };
    log.info({ org_id: orgId, from, message_id, bytes: mediaB64.length }, 'comprobante entrante (imagen)');
    await postInbound(orgId, payload);
    return;
  }

  // --- Texto (como hoy, ahora etiquetado tipo:"text") ------------------------------------
  const text = extractText(msg.message);
  if (!text) return; // ni texto ni imagen: nada que reenviar en este MVP

  const payload = {
    org_id: orgId,
    from,
    tipo: 'text',
    text,
    message_id,
    timestamp,
  };

  log.info({ org_id: orgId, from, message_id }, 'mensaje entrante');
  await postInbound(orgId, payload);
}

// Cierra y elimina la Session de un org (logout + borrar auth-state del disco + quitar del Map).
// Idempotente: si no habia Session en memoria, igual borra el dir del disco si existe.
async function destroySession(orgId) {
  const session = sessions.get(orgId);
  // Quitar del Map ANTES de cerrar el socket, para que el handler de 'close' no reconecte.
  sessions.delete(orgId);

  if (session?.sock) {
    try {
      await session.sock.logout();
    } catch (err) {
      log.warn({ err: err.message, org_id: orgId }, 'fallo logout (se continua con el cierre)');
    }
    try {
      session.sock.end?.(undefined);
    } catch {
      /* noop */
    }
  }

  // Borrar el auth-state del disco (rm -rf del dir del org), si existe.
  const dir = sessionDir(orgId);
  try {
    if (existsSync(dir)) {
      rmSync(dir, { recursive: true, force: true });
    }
  } catch (err) {
    log.warn({ err: err.message, org_id: orgId }, 'fallo borrando el auth-state del disco');
  }
}

// --- HTTP API --------------------------------------------------------------
const app = express();
// 4mb: cubre la imagen del QR saliente (image base64 en /send) y el comprobante entrante
// reenviado por el callback. El base64 infla ~33% sobre el binario original.
app.use(express.json({ limit: '4mb' }));

// Liveness sin token (para el healthcheck del compose). NO revela estado de sesion.
app.get('/healthz', (_req, res) => res.status(200).json({ ok: true }));

// Guard de token para el resto de endpoints (ambas direcciones autentican igual).
function requireToken(req, res, next) {
  if (req.get('X-Gateway-Token') !== GATEWAY_TOKEN) {
    return res.status(401).json({ ok: false, error: 'token invalido' });
  }
  next();
}

// Guard de orgId valido (evita path traversal en el auth-state).
function requireValidOrg(req, res, next) {
  const { orgId } = req.params;
  if (!isValidOrgId(orgId)) {
    return res.status(200).json({ ok: false, error: 'org_id invalido' });
  }
  next();
}

// GET /sessions/:orgId/status -> { org_id, connected, number }
app.get('/sessions/:orgId/status', requireToken, requireValidOrg, (req, res) => {
  const { orgId } = req.params;
  const session = sessions.get(orgId);
  const connected = !!session?.connected;
  res.status(200).json({
    org_id: orgId,
    connected,
    number: connected ? jidToDigits(session.selfJid) : null,
  });
});

// GET /sessions/:orgId/qr (lazy: si no hay Session, la crea y arranca pairing)
//   -> { org_id, connected:false, qr:<data-url> }
//   -> { org_id, connected:false, qr:null, error:'aun no hay QR; reintenta' }
//   -> { org_id, connected:true, number:'<digitos>' }
app.get('/sessions/:orgId/qr', requireToken, requireValidOrg, async (req, res) => {
  const { orgId } = req.params;
  let session = sessions.get(orgId);
  if (!session) {
    // Lazy: crear la Session y arrancar el pairing. El QR aparecera en proximos polls.
    session = getOrCreateSession(orgId);
    startSession(session).catch((err) =>
      log.error({ err: err.message, org_id: orgId }, 'fallo arranque lazy de la sesion'));
  }

  if (session.connected) {
    return res.status(200).json({ org_id: orgId, connected: true, number: jidToDigits(session.selfJid) });
  }
  if (!session.currentQr) {
    return res.status(200).json({ org_id: orgId, connected: false, qr: null, error: 'aun no hay QR; reintenta' });
  }
  try {
    const dataUrl = await qrcode.toDataURL(session.currentQr);
    res.status(200).json({ org_id: orgId, connected: false, qr: dataUrl });
  } catch (err) {
    res.status(200).json({ org_id: orgId, connected: false, qr: null, error: err.message });
  }
});

// POST /sessions/:orgId/send { to, text } | { to, text, image, mime } -> 200 { ok, message_id }
//   | 200 { ok:false, error }
// Contrato: errores de negocio (org sin sesion conectada, numero invalido, no esta en
// WhatsApp) => 200 { ok:false, error }. NUNCA 5xx por ellos.
//
// Dos modos (C3):
//   - TEXTO (como hoy): { to, text } -> sendMessage(jid, { text }).
//   - IMAGEN (nuevo): { to, text:"<caption|''>", image:"<base64 sin data-url>", mime } ->
//     sendMessage(jid, { image: Buffer.from(image,'base64'), caption: text||undefined, mimetype }).
// Con `image` presente el `text` actua como caption y PUEDE venir vacio (se relaja la
// validacion de text). Sin `image`, el path de texto queda intacto (text obligatorio).
app.post('/sessions/:orgId/send', requireToken, requireValidOrg, async (req, res) => {
  const { orgId } = req.params;
  const { to, text, image, mime } = req.body || {};

  // Validacion del `to`: E.164 internacional (8-15 digitos, sin +). Relajado desde el BO previo.
  if (typeof to !== 'string' || !/^\d{8,15}$/.test(to)) {
    return res.status(200).json({ ok: false, error: 'numero invalido (se esperan digitos E.164 sin +)' });
  }
  // ¿Viene imagen? (base64 string no vacio). Si la hay, `text` actua como caption opcional.
  const hasImage = typeof image === 'string' && image.length > 0;
  if (!hasImage && (typeof text !== 'string' || text.length === 0)) {
    // Path de texto puro: text sigue siendo obligatorio (no rompemos el flujo actual).
    return res.status(200).json({ ok: false, error: 'text vacio o no es string' });
  }

  const session = sessions.get(orgId);
  if (!session || !session.connected || !session.sock) {
    return res.status(200).json({ ok: false, error: 'sesion no conectada para esta organizacion' });
  }

  const jid = `${to}@s.whatsapp.net`;
  try {
    // Verifica que el destino existe en WhatsApp (numero invalido -> ok:false, no 5xx).
    const [exists] = await session.sock.onWhatsApp(jid).catch(() => [null]);
    if (!exists || !exists.exists) {
      return res.status(200).json({ ok: false, error: 'el numero no esta registrado en WhatsApp' });
    }
    // El caption solo aplica si hay texto no vacio (Baileys no quiere caption:'' suelto).
    const caption = typeof text === 'string' && text.length > 0 ? text : undefined;
    const content = hasImage
      ? { image: Buffer.from(image, 'base64'), caption, mimetype: mime }
      : { text };
    const sent = await session.sock.sendMessage(exists.jid, content);
    return res.status(200).json({ ok: true, message_id: sent?.key?.id || null });
  } catch (err) {
    log.warn({ err: err.message, to, org_id: orgId }, 'fallo el envio');
    // Tambien error de negocio/transporte: 200 ok:false para que el adaptador lo mapee.
    return res.status(200).json({ ok: false, error: err.message });
  }
});

// DELETE /sessions/:orgId (desvincular) -> 200 { org_id, ok:true } (idempotente)
app.delete('/sessions/:orgId', requireToken, requireValidOrg, async (req, res) => {
  const { orgId } = req.params;
  try {
    await destroySession(orgId);
  } catch (err) {
    // Idempotente: incluso si algo falla en el cierre, respondemos ok:true (la Session
    // ya fue quitada del Map). El operador puede reintentar el DELETE sin efectos.
    log.warn({ err: err.message, org_id: orgId }, 'incidencia al desvincular (se reporta ok:true igualmente)');
  }
  res.status(200).json({ org_id: orgId, ok: true });
});

app.listen(GATEWAY_PORT, '0.0.0.0', () => {
  log.info({ port: GATEWAY_PORT, sessionsRoot: SESSIONS_ROOT }, 'HTTP gateway multi-sesion escuchando');
});

// --- Reconexion al arranque -------------------------------------------------
// Lista los subdirectorios de SESSIONS_ROOT (un dir por org ya pareado) y reconecta cada
// org de forma SECUENCIAL con un pequeno backoff entre ellas (evita un pico de WebSockets).
async function reconnectExistingSessions() {
  let orgIds = [];
  try {
    orgIds = readdirSync(SESSIONS_ROOT, { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .map((d) => d.name)
      .filter(isValidOrgId);
  } catch (err) {
    log.error({ err: err.message }, 'no se pudo listar SESSIONS_ROOT; sin reconexion al arranque');
    return;
  }

  if (orgIds.length === 0) {
    log.info('no hay sesiones previas en SESSIONS_ROOT; esperando pairing por GET /sessions/:org/qr');
    return;
  }

  log.info({ count: orgIds.length, orgs: orgIds }, 'reconectando sesiones existentes al arranque');
  for (const orgId of orgIds) {
    const session = getOrCreateSession(orgId);
    try {
      await startSession(session);
    } catch (err) {
      log.error({ err: err.message, org_id: orgId }, 'fallo el arranque de la sesion (se reintentara al reconectar)');
    }
    // Pequeno backoff entre orgs.
    await new Promise((r) => setTimeout(r, 750));
  }
}

reconnectExistingSessions().catch((err) =>
  log.error({ err: err.message }, 'fallo la reconexion inicial de sesiones'));

// Apagado limpio (compose stop): cerrar todos los sockets SIN marcar logout (mantiene sesiones).
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    log.info({ sig, sessions: sessions.size }, 'apagando gateway multi-sesion');
    for (const session of sessions.values()) {
      try {
        session.sock?.end?.(undefined);
      } catch {
        /* noop */
      }
    }
    process.exit(0);
  });
}
