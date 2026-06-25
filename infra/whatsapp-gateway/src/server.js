// LatinoSport — WhatsApp Gateway (sidecar Baileys, WebSocket multidevice).
//
// Mantiene la sesion de UN numero de prueba (pairing por QR) y expone la HTTP API
// del CONTRATO CONGELADO (spec whatsapp-gateway, seccion A). NO usa Puppeteer/Chrome:
// Baileys habla el protocolo multidevice por WebSocket directo (sin navegador → sin OOM).
//
// HTTP API (todas con header `X-Gateway-Token`, salvo /qr/png que es para el operador):
//   POST /send    { to, text }            -> 200 { ok, message_id } | 200 { ok:false, error }
//   GET  /status                          -> 200 { connected, number }
//   GET  /qr                              -> 200 { connected, qr } (data-url) | { connected:true }
//   GET  /healthz                         -> 200 (liveness para el compose, sin token)
//
// Entrante: al llegar un mensaje de texto hace POST {INBOUND_CALLBACK_URL} con el mismo
// token y body { from, text, message_id, timestamp }. Tolera que el callback falle.
//
// Persistencia: useMultiFileAuthState en SESSION_DIR (montado en un volumen del compose)
// → no re-escanear QR en cada reinicio. Reconexion automatica al caerse.
//
// IMPORTANTE (contrato): los errores de NEGOCIO (no conectado, numero invalido, etc.)
// se reportan SIEMPRE como 200 { ok:false, error }. Nunca 5xx por ellos. El 5xx queda
// reservado a fallos verdaderamente inesperados del propio gateway.

import { existsSync, mkdirSync } from 'node:fs';
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
} from '@whiskeysockets/baileys';

// --- Config por entorno (contrato seccion B) -------------------------------
const GATEWAY_TOKEN = process.env.GATEWAY_TOKEN || '';
const GATEWAY_PORT = parseInt(process.env.GATEWAY_PORT || '3000', 10);
const INBOUND_CALLBACK_URL = process.env.INBOUND_CALLBACK_URL || '';
// Ruta del auth-state de Baileys. Se monta en un volumen (ver docker-compose.yml).
const SESSION_DIR = process.env.SESSION_DIR || '/data/session';

const log = pino({
  level: process.env.LOG_LEVEL || 'info',
  transport: process.env.LOG_PRETTY ? { target: 'pino-pretty' } : undefined,
});

if (!GATEWAY_TOKEN) {
  // Sin token el endpoint quedaria abierto a internet. Fallar rapido es preferible.
  log.error('GATEWAY_TOKEN no esta definido. Aborta: la API requiere un token compartido.');
  process.exit(1);
}

if (!existsSync(SESSION_DIR)) {
  mkdirSync(SESSION_DIR, { recursive: true });
}

// --- Estado en memoria de la conexion --------------------------------------
let sock = null;
let connected = false;
let selfJid = null; // JID propio del numero pareado, p.ej "59176123456@s.whatsapp.net"
let currentQr = null; // ultimo string de QR vigente (null si ya conectado / sin QR)

// Normaliza un JID a solo digitos (p.ej "59176123456@s.whatsapp.net:12" -> "59176123456").
function jidToDigits(jid) {
  if (!jid) return null;
  const user = jid.split('@')[0] || '';
  return user.split(':')[0] || null;
}

// --- Baileys: arranque, QR, reconexion, entrante ---------------------------
async function startSock() {
  const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));

  sock = makeWASocket({
    version,
    auth: state,
    logger: log.child({ mod: 'baileys' }),
    // markOnlineOnConnect:false evita "robar" las notificaciones push del telefono.
    markOnlineOnConnect: false,
    // Sin printQRInTerminal (deprecado): el QR lo logueamos/servimos nosotros.
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      currentQr = qr;
      connected = false;
      // Loguear el QR a stdout para que el operador lo escanee sin abrir /qr.
      try {
        const ascii = await qrcode.toString(qr, { type: 'terminal', small: true });
        log.info('\n========== ESCANEA ESTE QR CON EL NUMERO DE PRUEBA ==========\n' +
          ascii +
          '\n=============================================================\n' +
          '(o abre GET /qr para el data-url de la imagen)');
      } catch (err) {
        log.warn({ err: err.message }, 'no se pudo renderizar el QR ASCII; usa GET /qr');
      }
    }

    if (connection === 'open') {
      connected = true;
      currentQr = null;
      selfJid = sock?.user?.id || null;
      log.info({ number: jidToDigits(selfJid) }, 'WhatsApp conectado');
    }

    if (connection === 'close') {
      connected = false;
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = statusCode === DisconnectReason.loggedOut;
      log.warn({ statusCode, loggedOut }, 'WhatsApp desconectado');
      if (loggedOut) {
        // Sesion invalidada (logout desde el telefono): hay que re-parear (nuevo QR).
        // No reintentamos en bucle; el proximo arranque pedira QR de nuevo.
        selfJid = null;
        currentQr = null;
        startSock().catch((e) => log.error({ err: e.message }, 'fallo re-arranque tras logout'));
      } else {
        // Caida transitoria: reconectar.
        setTimeout(() => {
          startSock().catch((e) => log.error({ err: e.message }, 'fallo reconexion'));
        }, 2000);
      }
    }
  });

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    for (const msg of messages) {
      try {
        await handleIncoming(msg);
      } catch (err) {
        log.error({ err: err.message }, 'error procesando mensaje entrante (ignorado)');
      }
    }
  });

  return sock;
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

// Reenvia un mensaje entrante de texto al webhook del backend. Tolera fallos.
async function handleIncoming(msg) {
  // Ignorar lo que enviamos nosotros y lo que no es de un usuario (grupos, status, etc.).
  if (msg.key?.fromMe) return;
  const remoteJid = msg.key?.remoteJid;
  if (!remoteJid || !isJidUser(remoteJid)) return;

  const text = extractText(msg.message);
  if (!text) return; // solo texto en este MVP (entrante = recibir + loguear)

  const payload = {
    from: jidToDigits(remoteJid),
    text,
    message_id: msg.key?.id || null,
    // messageTimestamp puede ser number o Long; lo normalizamos a epoch (segundos).
    timestamp: Number(msg.messageTimestamp) || Math.floor(Date.now() / 1000),
  };

  log.info({ from: payload.from, message_id: payload.message_id }, 'mensaje entrante');

  if (!INBOUND_CALLBACK_URL) {
    log.warn('INBOUND_CALLBACK_URL no configurado; no se reenvia el entrante');
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
      log.warn({ status: res.status }, 'el callback entrante respondio no-2xx (ignorado)');
    }
  } catch (err) {
    // El edge no debe perder el proceso por un callback caido: loguear y seguir.
    log.warn({ err: err.message }, 'fallo el POST al callback entrante (ignorado)');
  }
}

// --- HTTP API --------------------------------------------------------------
const app = express();
app.use(express.json({ limit: '256kb' }));

// Liveness sin token (para el healthcheck del compose). NO revela estado de sesion.
app.get('/healthz', (_req, res) => res.status(200).json({ ok: true }));

// Guard de token para el resto de endpoints (ambas direcciones autentican igual).
function requireToken(req, res, next) {
  if (req.get('X-Gateway-Token') !== GATEWAY_TOKEN) {
    return res.status(401).json({ ok: false, error: 'token invalido' });
  }
  next();
}

// GET /status -> { connected, number }
app.get('/status', requireToken, (_req, res) => {
  res.status(200).json({ connected, number: connected ? selfJid : null });
});

// GET /qr -> { connected, qr } (data-url png) | { connected:true }
app.get('/qr', requireToken, async (_req, res) => {
  if (connected) {
    return res.status(200).json({ connected: true, number: selfJid });
  }
  if (!currentQr) {
    return res.status(200).json({ connected: false, qr: null, error: 'aun no hay QR; reintenta' });
  }
  try {
    const dataUrl = await qrcode.toDataURL(currentQr);
    res.status(200).json({ connected: false, qr: dataUrl });
  } catch (err) {
    res.status(200).json({ connected: false, qr: null, error: err.message });
  }
});

// POST /send { to, text } -> 200 { ok, message_id } | 200 { ok:false, error }
// Contrato: errores de negocio (no conectado, numero invalido, no esta en WhatsApp) =>
// 200 { ok:false, error }. NUNCA 5xx por ellos.
app.post('/send', requireToken, async (req, res) => {
  const { to, text } = req.body || {};

  if (typeof to !== 'string' || !/^\d{6,15}$/.test(to)) {
    return res.status(200).json({ ok: false, error: 'numero invalido (se esperan digitos E.164 sin +)' });
  }
  if (typeof text !== 'string' || text.length === 0) {
    return res.status(200).json({ ok: false, error: 'text vacio o no es string' });
  }
  if (!connected || !sock) {
    return res.status(200).json({ ok: false, error: 'gateway no conectado a WhatsApp' });
  }

  const jid = `${to}@s.whatsapp.net`;
  try {
    // Verifica que el destino existe en WhatsApp (numero invalido -> ok:false, no 5xx).
    const [exists] = await sock.onWhatsApp(jid).catch(() => [null]);
    if (!exists || !exists.exists) {
      return res.status(200).json({ ok: false, error: 'el numero no esta registrado en WhatsApp' });
    }
    const sent = await sock.sendMessage(exists.jid, { text });
    return res.status(200).json({ ok: true, message_id: sent?.key?.id || null });
  } catch (err) {
    log.warn({ err: err.message, to }, 'fallo el envio');
    // Tambien error de negocio/transporte: 200 ok:false para que el adaptador lo mapee.
    return res.status(200).json({ ok: false, error: err.message });
  }
});

app.listen(GATEWAY_PORT, '0.0.0.0', () => {
  log.info({ port: GATEWAY_PORT, sessionDir: SESSION_DIR }, 'HTTP gateway escuchando');
});

// Arranque de la sesion Baileys (no bloquea el HTTP server: el /status responde
// connected:false hasta que se parea; el /send responde ok:false mientras tanto).
startSock().catch((err) => {
  log.error({ err: err.message }, 'fallo el arranque inicial de Baileys; se reintentara al reconectar');
});

// Apagado limpio (compose stop): cerrar el socket sin marcar logout (mantiene sesion).
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    log.info({ sig }, 'apagando gateway');
    try {
      sock?.end?.(undefined);
    } catch {
      /* noop */
    }
    process.exit(0);
  });
}
