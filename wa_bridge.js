
function cleanPakistaniNumber(jid) {
    if (!jid) return "";
    let digits = jid.replace(/\D/g, "");
    if (digits.startsWith("92") && digits.length === 12) {
        return "0" + digits.slice(2);
    }
    return jid;
}

/**
 * WhatsApp Baileys Bridge (wa_bridge.js)
 * -------------------------------------------------------------
 * Lightweight Node.js bridge using @whiskeysockets/baileys & Express:
 * 1) Displays terminal QR code for free WhatsApp Web session linking.
 * 2) Forwards all incoming WhatsApp messages to the Python backend webhook.
 * 3) Exposes POST /send-message ({ chatId, message }) on port 3001
 *    for unlimited free WhatsApp messaging.
 */

const express = require('express');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  downloadMediaMessage,
  normalizeMessageContent,
  extractMessageContent,
  Browsers
} = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const qrcodeTerminal = require('qrcode-terminal');
const qrcode = require('qrcode');
const pino = require('pino');
const path = require('path');
const fs = require('fs');
const { spawn, execSync } = require('child_process');

let ffmpegBinaryPath = null;
try {
  ffmpegBinaryPath = require('ffmpeg-static');
} catch (_) {}
if (!ffmpegBinaryPath || !fs.existsSync(ffmpegBinaryPath)) {
  try {
    ffmpegBinaryPath = execSync('where.exe ffmpeg').toString().trim().split(/\r?\n/)[0];
  } catch (_) {}
}

/**
 * Converts audio buffer (MP3/WAV/etc.) to OGG Opus suitable for WhatsApp PTT voice notes.
 * Command: ffmpeg -i pipe:0 -c:a libopus -b:a 32k -vbr on -compression_level 10 -frame_duration 60 -application voip -f ogg pipe:1
 */
function convertAudioToOggOpus(buffer) {
  return new Promise((resolve, reject) => {
    if (!ffmpegBinaryPath || !fs.existsSync(ffmpegBinaryPath)) {
      return reject(new Error('ffmpeg binary unavailable'));
    }
    const args = [
      '-i', 'pipe:0',
      '-c:a', 'libopus',
      '-b:a', '32k',
      '-vbr', 'on',
      '-compression_level', '10',
      '-frame_duration', '60',
      '-application', 'voip',
      '-f', 'ogg',
      'pipe:1'
    ];
    const proc = spawn(ffmpegBinaryPath, args, { stdio: ['pipe', 'pipe', 'pipe'] });
    const chunks = [];
    let err = '';
    proc.stdout.on('data', chunk => chunks.push(chunk));
    proc.stderr.on('data', d => { err += d.toString(); });
    proc.on('close', code => {
      if (code === 0 && chunks.length > 0) {
        resolve(Buffer.concat(chunks));
      } else {
        reject(new Error('ffmpeg conversion failed (code ' + code + '): ' + err));
      }
    });
    proc.on('error', reject);
    try {
      proc.stdin.write(buffer);
      proc.stdin.end();
    } catch (writeErr) {
      reject(writeErr);
    }
  });
}
// Configuration
const PORT = process.env.WA_BRIDGE_PORT || process.env.BRIDGE_PORT || 3001;
const PYTHON_PORT = process.env.PORT || 5000;
const PYTHON_WEBHOOK_URL = process.env.PYTHON_WEBHOOK_URL || `http://127.0.0.1:${PYTHON_PORT}/api/v1/webhooks/whatsapp`;

/**
 * Resolves the Baileys multi-file authentication storage path.
 * Supports explicit AUTH_DIR environment variable or detects persistent
 * disk mount directories on Render and container hosts (/var/data, /data, etc.)
 * to guarantee that sessions persist across restarts without re-scans.
 */
function resolveAuthDir() {
  if (process.env.AUTH_DIR && process.env.AUTH_DIR.trim()) {
    return path.resolve(process.env.AUTH_DIR.trim());
  }
  const candidateMounts = [
    process.env.RENDER_DISK_PATH,
    process.env.PERSISTENT_DATA_DIR,
    '/var/data',
    '/data',
    '/mnt/data'
  ].filter(Boolean);

  for (const mount of candidateMounts) {
    try {
      if (fs.existsSync(mount)) {
        const candidateAuth = path.join(mount, 'baileys_auth');
        return candidateAuth;
      }
    } catch (_) {}
  }
  return path.join(__dirname, 'baileys_auth');
}

const AUTH_DIR = resolveAuthDir();

function getBackendBaseUrl() {
  const envUrl = process.env.PYTHON_WEBHOOK_URL;
  if (envUrl && envUrl.includes('/api/v1/webhooks')) {
    return envUrl.split('/api/v1/webhooks')[0];
  }
  return `http://127.0.0.1:${PYTHON_PORT}`;
}

let sessionBackupDebounce = null;
function triggerSessionBackup() {
  if (sessionBackupDebounce) return;
  sessionBackupDebounce = setTimeout(async () => {
    sessionBackupDebounce = null;
    try {
      const backupUrl = `${getBackendBaseUrl()}/api/v1/whatsapp/session-backup`;
      const http = backupUrl.startsWith('https') ? require('https') : require('http');
      const u = new URL(backupUrl);
      const req = http.request({
        hostname: u.hostname,
        port: u.port,
        path: u.pathname,
        method: 'POST',
        timeout: 4000
      }, (res) => { res.resume(); });
      req.on('error', () => {});
      req.end();
    } catch (_) {}
  }, 2500);
}

function triggerSessionClear() {
  try {
    const clearUrl = `${getBackendBaseUrl()}/api/v1/whatsapp/session-clear`;
    const http = clearUrl.startsWith('https') ? require('https') : require('http');
    const u = new URL(clearUrl);
    const req = http.request({
      hostname: u.hostname,
      port: u.port,
      path: u.pathname,
      method: 'POST',
      timeout: 4000
    }, (res) => { res.resume(); });
    req.on('error', () => {});
    req.end();
  } catch (_) {}
}

async function tryRestoreFromPythonBackend() {
  return new Promise((resolve) => {
    try {
      const restoreUrl = `${getBackendBaseUrl()}/api/v1/whatsapp/session-restore`;
      const http = restoreUrl.startsWith('https') ? require('https') : require('http');
      const u = new URL(restoreUrl);
      const req = http.request({
        hostname: u.hostname,
        port: u.port,
        path: u.pathname,
        method: 'GET',
        timeout: 5000
      }, (res) => {
        let body = '';
        res.on('data', chunk => { body += chunk; });
        res.on('end', () => {
          try {
            const data = JSON.parse(body);
            resolve(!!data.restored);
          } catch (_) {
            resolve(false);
          }
        });
      });
      req.on('error', () => resolve(false));
      req.end();
    } catch (_) {
      resolve(false);
    }
  });
}

// Global socket state
let sock = null;
let isConnected = false;
let currentQr = null;
let currentQrUrl = null;
let currentQrSvg = null;
let isStarting = false;
let reconnectTimer = null;

// Process-wide guard against unhandled network crashes
process.on('uncaughtException', (err) => {
  console.error('[WhatsApp Bridge] Uncaught Exception (guarded):', err);
});
process.on('unhandledRejection', (reason, promise) => {
  console.error('[WhatsApp Bridge] Unhandled Rejection (guarded):', reason);
});

/**
 * Safely terminates and removes all event listeners from an existing socket
 * before initializing a new one to prevent memory leaks and file locks.
 */
function destroyOldSocket() {
  if (sock) {
    try {
      if (sock.ev && typeof sock.ev.removeAllListeners === 'function') {
        sock.ev.removeAllListeners();
      }
      if (sock.ws && typeof sock.ws.close === 'function') {
        sock.ws.close();
      }
      if (typeof sock.end === 'function') {
        sock.end(undefined);
      }
    } catch (_) {}
    sock = null;
  }
}

/**
 * Unwraps nested message structures (ephemeral, view-once, documentWithCaption, etc.)
 * to extract the raw underlying payload and media elements.
 */
function unwrapMessage(msgContent) {
  if (!msgContent) return null;
  let unwrapped = msgContent;
  if (typeof normalizeMessageContent === 'function') {
    try {
      unwrapped = normalizeMessageContent(unwrapped) || unwrapped;
    } catch (_) {}
  }
  if (typeof extractMessageContent === 'function') {
    try {
      unwrapped = extractMessageContent(unwrapped) || unwrapped;
    } catch (_) {}
  }
  let depth = 0;
  while (depth < 8) {
    depth++;
    const next =
      unwrapped?.ephemeralMessage?.message ||
      unwrapped?.viewOnceMessage?.message ||
      unwrapped?.viewOnceMessageV2?.message ||
      unwrapped?.viewOnceMessageV2Extension?.message ||
      unwrapped?.documentWithCaptionMessage?.message ||
      unwrapped?.protocolMessage?.editedMessage ||
      unwrapped?.editedMessage?.message?.protocolMessage?.editedMessage ||
      unwrapped?.editedMessage?.message ||
      unwrapped?.associatedChildMessage?.message;
    if (!next) break;
    unwrapped = next;
  }
  return unwrapped;
}

/**
 * Cleans phone numbers / JIDs by stripping @lid, @s.whatsapp.net, @c.us,
 * and device indices like :0 or :1 to return clean numbers.
 * Strictly preserves and formats Pakistani mobile numbers while eliminating
 * incorrect foreign prefixes like +91.
 */
// Global mappings for contacts and groups
const contactNamesMap = new Map();  // JID / phone / LID -> Contact Name
const groupSubjectsMap = new Map(); // Group JID (@g.us) -> Group Subject/Name
const phoneToLidMap = new Map();
const lastSendTimeMap = new Map();
const lidToPhoneMap = new Map(); // Keep persisted in memory/DB

/**
 * Estimates audio duration in seconds from buffer headers (OGG Opus granule position or MP3 frame sync).
 */
function estimateAudioDuration(buf) {
  if (!buf || !Buffer.isBuffer(buf) || buf.length < 32) return 0;
  // OGG Opus: find last 'OggS' page header to extract exact granule position
  const oggHeader = Buffer.from('OggS');
  const lastOgg = buf.lastIndexOf(oggHeader);
  if (lastOgg >= 0 && lastOgg + 14 <= buf.length) {
    try {
      const granule = buf.readBigInt64LE(lastOgg + 6);
      if (granule > 0n) {
        return Math.max(1, Math.round(Number(granule) / 48000));
      }
    } catch (_) {}
  }
  // MP3: rough estimation (typical 64k-128kbps, average ~16KB/s)
  if (buf.slice(0, 3).toString('utf8') === 'ID3' || (buf[0] === 0xff && (buf[1] & 0xe0) === 0xe0)) {
    return Math.max(1, Math.round(buf.length / 16000));
  }
  return 1;
}

function cleanPhoneNumber(jid) {
  if (!jid) return '';
  let str = String(jid).trim();
  // NEVER format a JID as a phone number if it ends with @lid!
  if (str.endsWith('@lid') || str.includes('@lid')) return '';
  if (str.endsWith('@g.us') || str.endsWith('@broadcast')) return str;
  str = str.replace(/@s\.whatsapp\.net|@c\.us/gi, '');
  str = str.split(':')[0].trim();
  let digits = str.replace(/[^0-9]/g, '');
  // If digits > 13 (e.g. 14-digit LID masquerading as phone number), reject as fake number
  if (digits.length > 13) return '';
  // Pakistani local phone handling:
  // 03001234567 (11 digits with 03) -> 923001234567
  if (digits.startsWith('03') && digits.length === 11) {
    digits = '92' + digits.slice(1);
  } else if (digits.startsWith('3') && digits.length === 10) {
    // 3001234567 (10 digits starting with 3) -> 923001234567
    digits = '92' + digits;
  } else if (digits.startsWith('913') && digits.length === 12) {
    // Correct erroneously prefixed +91 to Pakistani +92 (913001234567 -> 923001234567)
    digits = '923' + digits.slice(3);
  } else if (digits.startsWith('00')) {
    digits = digits.slice(2);
  }
  return digits || str;
}

// Helper function to resolve sender identity accurately without fake +91/+98 LIDs
async function resolveSender(msg, activeSock) {
  const key = msg.key || {};
  const remoteJid = key.remoteJid || '';
  // Check all possible real phone fields in Baileys
  const candidateJid =
    key.remoteJidAlt ||
    key.senderPn ||
    msg.key?.senderPn ||
    msg.key?.participantPn ||
    (key.participant?.endsWith('@s.whatsapp.net') ? key.participant : null) ||
    msg.participant ||
    (remoteJid.endsWith('@s.whatsapp.net') ? remoteJid : null);

  let phone = null;
  if (candidateJid && candidateJid.includes('@s.whatsapp.net')) {
    phone = candidateJid.split('@')[0].split(':')[0];
    if (remoteJid.endsWith('@lid')) {
      lidToPhoneMap.set(remoteJid, phone);
      phoneToLidMap.set(phone, remoteJid);
    }
  } else if (remoteJid.endsWith('@lid') && lidToPhoneMap.has(remoteJid)) {
    phone = lidToPhoneMap.get(remoteJid);
  }

  // Query Baileys onWhatsApp to resolve @lid to real phone number
  if (!phone && activeSock && typeof activeSock.onWhatsApp === 'function' && remoteJid) {
    try {
      const results = await activeSock.onWhatsApp(remoteJid);
      const res = results?.[0];
      if (res && res.exists) {
        const ph = res.jid ? cleanPhoneNumber(res.jid) : '';
        const lid = res.lid || (remoteJid.endsWith('@lid') ? remoteJid : null);
        if (ph && lid) {
          lidToPhoneMap.set(lid, ph);
          phoneToLidMap.set(ph, lid);
        }
        if (ph) {
          phone = ph;
        }
      }
    } catch (_) {}
  }

  // Check cached contact names from Baileys events (contacts.upsert, chats.upsert)
  const cachedContactName =
    contactNamesMap.get(remoteJid) ||
    (candidateJid ? contactNamesMap.get(candidateJid) : null) ||
    (phone ? contactNamesMap.get(phone) : null) ||
    (phone ? contactNamesMap.get(`+${phone}`) : null);

  const bestName = msg.pushName || cachedContactName;

  if (phone) {
    return {
      phone: `+${phone}`,
      displayName: bestName || `+${phone}`,
      replyJid: remoteJid
    };
  }

  // FALLBACK: NEVER use bot's own number or prepend '+' to non-numeric strings!
  const fallbackName = bestName || (remoteJid && !remoteJid.endsWith('@lid') ? remoteJid.split('@')[0] : 'WhatsApp Contact');
  return {
    phone: fallbackName,
    displayName: fallbackName,
    replyJid: remoteJid
  };
}

/**
 * Normalizes phone numbers / chat IDs to Baileys JID format.
 * - Handles group chats: 12345-67890@g.us
 * - Handles Pakistani local numbers: 03209350858 -> 923209350858@s.whatsapp.net
 * - Strips accidental +91 prefixes from Pakistani numbers (913XXXXXXXXX -> 923XXXXXXXXX)
 * - Strips @c.us, @lid, :0 device indices
 * - Returns empty string if no valid digits exist
 */
function normalizeJid(chatId) {
  if (!chatId) return '';
  let jid = String(chatId).trim();

  if (jid.endsWith('@g.us') || jid.endsWith('@broadcast') || jid.endsWith('@lid')) {
    return jid;
  }
  // Strip all protocol suffixes and device ports (:0, :1, @c.us, @lid, @s.whatsapp.net)
  jid = jid.replace(/@c\.us|@lid|@s\.whatsapp\.net/gi, '');
  jid = jid.split(':')[0].trim();

  let cleanDigits = jid.replace(/[^0-9]/g, '');
  if (!cleanDigits) return '';

  if (cleanDigits.startsWith('03') && cleanDigits.length === 11) {
    cleanDigits = '92' + cleanDigits.slice(1);
  } else if (cleanDigits.startsWith('3') && cleanDigits.length === 10) {
    cleanDigits = '92' + cleanDigits;
  } else if (cleanDigits.startsWith('913') && cleanDigits.length === 12) {
    // Avoid wrong country code +91 for Pakistani 3xx mobile numbers
    cleanDigits = '923' + cleanDigits.slice(3);
  } else if (cleanDigits.startsWith('00')) {
    cleanDigits = cleanDigits.slice(2);
  }
  if (cleanDigits.length > 13) {
    if (lidToPhoneMap.has(`${cleanDigits}@lid`)) {
      return `${lidToPhoneMap.get(`${cleanDigits}@lid`)}@s.whatsapp.net`;
    }
    return `${cleanDigits}@lid`;
  }
  return `${cleanDigits}@s.whatsapp.net`;
}

/**
 * Extracts plain text from various Baileys message types, unwrapping nested structures.
 */
function extractMessageText(message) {
  if (!message) return '';
  const unwrapped = unwrapMessage(message) || message;
  if (!unwrapped) return '';

  return (
    unwrapped.conversation ||
    unwrapped.extendedTextMessage?.text ||
    unwrapped.imageMessage?.caption ||
    unwrapped.videoMessage?.caption ||
    unwrapped.documentMessage?.caption ||
    unwrapped.documentWithCaptionMessage?.message?.documentMessage?.caption ||
    unwrapped.buttonsResponseMessage?.selectedDisplayText ||
    unwrapped.buttonsResponseMessage?.selectedButtonId ||
    unwrapped.templateButtonReplyMessage?.selectedDisplayText ||
    unwrapped.templateButtonReplyMessage?.selectedId ||
    unwrapped.listResponseMessage?.title ||
    unwrapped.listResponseMessage?.singleSelectReply?.selectedRowId ||
    unwrapped.interactiveResponseMessage?.body?.text ||
    unwrapped.interactiveResponseMessage?.nativeFlowResponseMessage?.paramsJson ||
    ''
  ).trim();
}

/**
 * Initializes and manages the Baileys WhatsApp Web socket.
 */
async function startWhatsAppBridge() {
  // GUARD: If WhatsApp is already connected and active, never destroy or recreate socket!
  if (isConnected && sock) {
    console.log('[WhatsApp Bridge] Guard active: WhatsApp is already connected. Skipping re-initialization.');
    return;
  }
  if (isStarting) {
    console.log('[WhatsApp Bridge] Connection initialization already in progress, skipping duplicate request.');
    return;
  }
  isStarting = true;

  try {
    destroyOldSocket();

    // Ensure auth storage directory exists
    if (!fs.existsSync(AUTH_DIR)) {
      fs.mkdirSync(AUTH_DIR, { recursive: true });
    }

    // Query DB for session credentials if local creds are absent
    const credsCheckPath = path.join(AUTH_DIR, 'creds.json');
    if (!fs.existsSync(credsCheckPath) || fs.statSync(credsCheckPath).size < 20) {
      try {
        console.log('[WhatsApp Bridge] Checking database for saved session credentials...');
        const restored = await tryRestoreFromPythonBackend();
        if (restored) {
          console.log('[WhatsApp Bridge] Restored permanent session from Database!');
        }
      } catch (_) {}
    }

    // Load or reset multi-file auth credentials safely
    let state, saveCreds;
    try {
      const auth = await useMultiFileAuthState(AUTH_DIR);
      state = auth.state;
      saveCreds = auth.saveCreds;
    } catch (authErr) {
      console.error('[WhatsApp Bridge] Auth state read error:', authErr.message);
      const credsFile = path.join(AUTH_DIR, 'creds.json');
      let isCorruptJson = false;
      if (fs.existsSync(credsFile)) {
        try {
          JSON.parse(fs.readFileSync(credsFile, 'utf8'));
        } catch (_) {
          isCorruptJson = true;
        }
      }
      if (isCorruptJson) {
        console.warn('[WhatsApp Bridge] creds.json is corrupted JSON. Resetting auth directory...');
        try {
          if (fs.existsSync(AUTH_DIR)) {
            // Prevent auto-wiping session so login stays permanent
            fs.mkdirSync(AUTH_DIR, { recursive: true });
          }
          const auth = await useMultiFileAuthState(AUTH_DIR);
          state = auth.state;
          saveCreds = auth.saveCreds;
        } catch (resetErr) {
          console.error('[WhatsApp Bridge] Fatal error resetting auth state:', resetErr);
          throw resetErr;
        }
      } else {
        // Transient filesystem access delay; wait briefly and retry once
        await new Promise(r => setTimeout(r, 1000));
        const auth = await useMultiFileAuthState(AUTH_DIR);
        state = auth.state;
        saveCreds = auth.saveCreds;
      }
    }

    // Version discovery with safe default fallback
    let version = [2, 3000, 1043857760];
    let isLatest = false;
    try {
      const vInfo = await fetchLatestBaileysVersion();
      if (vInfo && Array.isArray(vInfo.version)) {
        version = vInfo.version;
        isLatest = !!vInfo.isLatest;
      }
    } catch (vErr) {
      console.warn('[WhatsApp Bridge] Version check skipped, using standard version:', vErr.message);
    }
    console.log(`[WhatsApp Bridge] Using WA Web v${version.join('.')}, isLatest: ${isLatest}`);

    // Create Baileys socket with high resilience settings
    sock = makeWASocket({
      version,
      auth: state,
      logger: pino({ level: 'silent' }),
      printQRInTerminal: false,
      syncFullHistory: false,
      connectTimeoutMs: 60000,
      defaultQueryTimeoutMs: 60000,
      keepAliveIntervalMs: 25000,
      browser: Browsers.macOS('Desktop'),
      getMessage: async (key) => undefined
    });

    // Safely persist session credentials
    sock.ev.on('creds.update', async () => {
      try {
        if (typeof saveCreds === 'function') {
          await saveCreds();
        }
        triggerSessionBackup();
      } catch (saveErr) {
        console.error('[WhatsApp Bridge] Failed to save creds:', saveErr.message);
      }
    });

    // Connection life-cycle handler
    sock.ev.on('connection.update', (update) => {
      const { connection, lastDisconnect, qr } = update;

      // Display QR code in terminal when generated & pre-generate data URL and SVG
      if (qr) {
        currentQr = qr;
        console.log('\n===============================================================');
        console.log('  SCAN THIS QR CODE IN WHATSAPP TO LINK FOR FREE');
        console.log('  Steps: WhatsApp -> Settings/Menu -> Linked Devices -> Link a Device');
        console.log('===============================================================');
        try {
          if (process.stdout.isTTY && !process.env.RENDER) {
            qrcodeTerminal.generate(qr, { small: true });
          }
        } catch (tErr) {
          // ignore terminal write error in non-TTY environments
        }
        console.log('===============================================================\n');

        // Convert raw Baileys QR string into base64 Data URI using qrcode.toDataURL()
        qrcode.toDataURL(qr, {
          errorCorrectionLevel: 'M',
          type: 'image/png',
          margin: 2,
          width: 220,
          color: { dark: '#000000', light: '#ffffff' }
        }).then((url) => {
          currentQrUrl = url;
        }).catch((err) => {
          console.error('[Bridge QR] Error generating QR Data URL:', err);
        });

        // Pre-generate SVG string
        qrcode.toString(qr, {
          type: 'svg',
          margin: 2,
          width: 220
        }).then((svg) => {
          currentQrSvg = svg;
        }).catch((err) => {
          console.error('[Bridge QR] Error generating QR SVG:', err);
        });
      }

      if (connection === 'close') {
        isConnected = false;
        const statusCode =
          lastDisconnect?.error instanceof Boom
            ? lastDisconnect.error.output?.statusCode
            : lastDisconnect?.error?.output?.statusCode;

        const isLoggedOut = (statusCode === DisconnectReason.loggedOut);
        console.warn(`[WhatsApp Bridge] Connection closed (code: ${statusCode}, isLoggedOut: ${isLoggedOut}).`);

        if (isLoggedOut) {
          console.warn('[WhatsApp Bridge] True user logout detected (code 401). Clearing auth directory & DB store...');
          try {
            if (fs.existsSync(AUTH_DIR)) {
              fs.rmSync(AUTH_DIR, { recursive: true, force: true });
              fs.mkdirSync(AUTH_DIR, { recursive: true });
            }
          } catch (rmErr) {
            console.error('[WhatsApp Bridge] Failed to clean auth directory:', rmErr.message);
          }
          triggerSessionClear();
          currentQr = null;
          currentQrUrl = null;
          currentQrSvg = null;
        }

        destroyOldSocket();

        // Intelligent Auto-Recovery with smart backoff based on disconnect reason
        let restartDelay = 2000;
        if (statusCode === DisconnectReason.restartRequired) {
          restartDelay = 500;
          console.log('[WhatsApp Bridge Auto-Recovery] Server requested restart (code 515). Re-syncing immediately in 500ms...');
        } else if (statusCode === DisconnectReason.timedOut || statusCode === DisconnectReason.connectionLost) {
          restartDelay = 1500;
          console.log('[WhatsApp Bridge Auto-Recovery] Transient network loss/timeout (code 408). Re-syncing in 1.5s...');
        } else if (statusCode === DisconnectReason.connectionClosed) {
          restartDelay = 1500;
          console.log('[WhatsApp Bridge Auto-Recovery] Socket closed normally (code 428). Auto-recovering in 1.5s...');
        } else if (statusCode === DisconnectReason.connectionReplaced) {
          restartDelay = 4000;
          console.log('[WhatsApp Bridge Auto-Recovery] Socket connection replaced (code 440). Waiting 4s before re-sync...');
        } else if (isLoggedOut) {
          restartDelay = 2000;
        }

        console.log(`[WhatsApp Bridge Auto-Recovery] Scheduling socket re-sync in ${restartDelay}ms...`);
        clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(() => {
          startWhatsAppBridge().catch((retryErr) => {
            console.error('[WhatsApp Bridge Auto-Recovery] Reconnect attempt failed:', retryErr.message);
            // Continuous auto-recovery: never halts
            clearTimeout(reconnectTimer);
            reconnectTimer = setTimeout(() => {
              startWhatsAppBridge().catch(() => {});
            }, 5000);
          });
        }, restartDelay);
      } else if (connection === 'open') {
        isConnected = true;
        triggerSessionBackup();
        currentQr = null;
        currentQrUrl = null;
        currentQrSvg = null;
        const userPhone = sock?.user?.id ? sock.user.id.split(':')[0] : 'Linked Number';
        console.log('\n===============================================================');
        console.log(` [WhatsApp Bridge] Connected successfully! Auto-recovery active.`);
        console.log(` Active Phone: +${userPhone}`);
        console.log(` REST API listening on port ${PORT}`);
        console.log(` Python Webhook target: ${PYTHON_WEBHOOK_URL}`);
        console.log('===============================================================\n');
      }
    });

    // 0. History synchronization on initial connect or reconnect (auto-syncs contacts and groups)
    sock.ev.on('messaging-history.set', ({ chats, contacts, messages, isLatest }) => {
      console.log(`[WhatsApp Bridge Auto-Sync] Synchronized history: ${chats?.length || 0} chats, ${contacts?.length || 0} contacts (isLatest: ${Boolean(isLatest)})`);
      if (Array.isArray(contacts)) {
        for (const c of contacts) {
          const cName = c.name || c.notify || c.verifiedName;
          if (c.id && cName) {
            contactNamesMap.set(c.id, cName);
            const ph = cleanPhoneNumber(c.id);
            if (ph) {
              contactNamesMap.set(ph, cName);
              contactNamesMap.set(`+${ph}`, cName);
            }
          }
          if (c.lid && c.id && c.id.endsWith('@s.whatsapp.net')) {
            const ph = c.id.split('@')[0].split(':')[0];
            lidToPhoneMap.set(c.lid, ph);
            phoneToLidMap.set(ph, c.lid);
            if (cName) contactNamesMap.set(c.lid, cName);
          }
        }
      }
      if (Array.isArray(chats)) {
        for (const chat of chats) {
          const chName = chat.name || chat.subject || chat.notify;
          if (chat.id && chName) {
            groupSubjectMap.set(chat.id, chName);
            chatSubjectMap.set(chat.id, chName);
          }
        }
      }
    });

    // 1. Capture mappings from contacts events to map LIDs to real phone numbers
    sock.ev.on('contacts.upsert', (contacts) => {
      for (const c of contacts) {
        const cName = c.name || c.notify || c.verifiedName;
        if (c.id) {
          if (cName) {
            contactNamesMap.set(c.id, cName);
            const ph = cleanPhoneNumber(c.id);
            if (ph) {
              contactNamesMap.set(ph, cName);
              contactNamesMap.set(`+${ph}`, cName);
            }
          }
          if (c.lid && c.id.endsWith('@s.whatsapp.net')) {
            const ph = c.id.split('@')[0].split(':')[0];
            lidToPhoneMap.set(c.lid, ph);
            phoneToLidMap.set(ph, c.lid);
            if (cName) contactNamesMap.set(c.lid, cName);
          }
        }
      }
    });
    sock.ev.on('contacts.update', (updates) => {
      for (const c of updates) {
        const cName = c.name || c.notify || c.verifiedName;
        if (c.id) {
          if (cName) {
            contactNamesMap.set(c.id, cName);
            const ph = cleanPhoneNumber(c.id);
            if (ph) {
              contactNamesMap.set(ph, cName);
              contactNamesMap.set(`+${ph}`, cName);
            }
          }
          if (c.lid && c.id.endsWith('@s.whatsapp.net')) {
            const ph = c.id.split('@')[0].split(':')[0];
            lidToPhoneMap.set(c.lid, ph);
            phoneToLidMap.set(ph, c.lid);
            if (cName) contactNamesMap.set(c.lid, cName);
          }
        }
      }
    });

    // Capture chat and group events to cache real group subjects and chat titles
    sock.ev.on('chats.upsert', (chats) => {
      for (const chat of chats) {
        if (!chat.id) continue;
        if (chat.id.endsWith('@g.us')) {
          const subject = chat.name || chat.subject;
          if (subject) groupSubjectsMap.set(chat.id, subject);
        } else {
          if (chat.name) {
            contactNamesMap.set(chat.id, chat.name);
            const ph = cleanPhoneNumber(chat.id);
            if (ph) {
              contactNamesMap.set(ph, chat.name);
              contactNamesMap.set(`+${ph}`, chat.name);
            }
          }
        }
      }
    });
    sock.ev.on('chats.update', (updates) => {
      for (const chat of updates) {
        if (!chat.id) continue;
        if (chat.id.endsWith('@g.us')) {
          const subject = chat.name || chat.subject;
          if (subject) groupSubjectsMap.set(chat.id, subject);
        } else {
          if (chat.name) {
            contactNamesMap.set(chat.id, chat.name);
            const ph = cleanPhoneNumber(chat.id);
            if (ph) {
              contactNamesMap.set(ph, chat.name);
              contactNamesMap.set(`+${ph}`, chat.name);
            }
          }
        }
      }
    });
    sock.ev.on('groups.update', (groupUpdates) => {
      for (const g of groupUpdates) {
        if (g.id && (g.subject || g.name)) {
          groupSubjectsMap.set(g.id, g.subject || g.name);
        }
      }
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
      try {
        if (type !== 'notify' || !messages || !Array.isArray(messages)) return;

        for (const msg of messages) {
          const ownPhone = sock?.user?.id ? cleanPhoneNumber(sock.user.id.split(':')[0]) : '';
          const ownLid = sock?.user?.lid ? sock.user.lid.split(':')[0].split('@')[0] : '';
          const remoteJid = msg.key?.remoteJid || '';
          const remClean = remoteJid.split(':')[0].split('@')[0];
          const isSelfChat = (remClean === ownPhone || (ownLid && remClean === ownLid));
          // Allow self-chat messages from user for testing, but block bot echo loops
          if (msg.key?.fromMe && !isSelfChat) continue;
          if (msg.key?.fromMe && (msg.key?.id?.startsWith('BAE5') || msg.key?.id?.startsWith('3EB0'))) continue;
          if (remoteJid === 'status@broadcast') continue;

          const isGroupChat = remoteJid.endsWith('@g.us') || remoteJid.endsWith('@broadcast');
          const participantJid = msg.key?.participant || '';
          
          let senderPhone;
          let displayName;
          let replyJid = remoteJid;
          let groupSubject = null;

          if (isGroupChat) {
            if (!participantJid) continue;
            senderPhone = cleanPhoneNumber(msg.key?.senderPn || msg.key?.participantPn || participantJid);
            // Look up cached contact name for group participant
            const cachedParticipantName =
              contactNamesMap.get(participantJid) ||
              (senderPhone ? contactNamesMap.get(senderPhone) : null) ||
              (senderPhone ? contactNamesMap.get(`+${phone}`) : null);
            displayName = msg.pushName || cachedParticipantName || (senderPhone ? `+${senderPhone}` : 'WhatsApp Group User');

            // Look up cached group subject or fetch via groupMetadata
            groupSubject = groupSubjectsMap.get(remoteJid);
            if (!groupSubject && sock && typeof sock.groupMetadata === 'function' && remoteJid.endsWith('@g.us')) {
              try {
                const meta = await sock.groupMetadata(remoteJid);
                if (meta && meta.subject) {
                  groupSubject = meta.subject;
                  groupSubjectsMap.set(remoteJid, meta.subject);
                }
              } catch (_) {}
            }
          } else {
            const senderRes = await resolveSender(msg, sock);
            senderPhone = senderRes.phone;
            displayName = senderRes.displayName;
            replyJid = senderRes.replyJid;
          }

          const pushName = displayName || msg.pushName || (isGroupChat ? 'WhatsApp Group User' : 'WhatsApp User');
          const chatTitle = isGroupChat ? (groupSubject || 'WhatsApp Group') : pushName;
          const messageId = msg.key?.id || msg_;
          const timestamp = msg.messageTimestamp ? Number(msg.messageTimestamp) : Math.floor(Date.now() / 1000);

          // Anti-ban & Human feel: Blue tick (read receipt) and typing status upon receiving message
          if (!msg.key?.fromMe && remoteJid && remoteJid !== 'status@broadcast') {
            try {
              await sock.readMessages([msg.key]);
              await sock.sendPresenceUpdate('composing', remoteJid);
            } catch (presErr) {
              console.debug('[Presence Setup Notice]', presErr.message);
            }
          }
          
          // 1. Unwrap ephemeral/viewOnce wrappers first:
          const unwrappedMsg = msg.message?.ephemeralMessage?.message || msg.message?.viewOnceMessage?.message || unwrapMessage(msg.message) || msg.message;
          let text = extractMessageText(unwrappedMsg);
          let isVoice = false;
          let isAudio = false;
          let isImage = false;
          let typeMessage = 'textMessage';
          let audioBase64 = null;
          let audioDataUrl = null;

          // 2. Detect audio:
          let audioDuration = null;
          const audioMsg = unwrappedMsg?.audioMessage;
          if (audioMsg) {
            isAudio = true;
            isVoice = Boolean(audioMsg.ptt);
            typeMessage = isVoice ? 'voiceMessage' : 'audioMessage';
            audioDuration = audioMsg.seconds || audioMsg.duration || null;

            // 3. Download media and convert directly to a Base64 Data URL
            try {
              let buffer = null;
              try {
                buffer = await downloadMediaMessage(
                  msg,
                  'buffer',
                  {},
                  {
                    logger: pino({ level: 'silent' }),
                    reuploadRequest: sock?.updateMediaMessage
                  }
                );
              } catch (_) {
                try {
                  buffer = await downloadMediaMessage(
                    { key: msg.key, message: unwrappedMsg },
                    'buffer',
                    {},
                    {
                      logger: pino({ level: 'silent' }),
                      reuploadRequest: sock?.updateMediaMessage
                    }
                  );
                } catch (_2) {
                  try {
                    buffer = await downloadMediaMessage(
                      { key: msg.key, message: { audioMessage: audioMsg } },
                      'buffer',
                      {},
                      {
                        logger: pino({ level: 'silent' }),
                        reuploadRequest: sock?.updateMediaMessage
                      }
                    );
                  } catch (_3) {}
                }
              }

              // Before encryption keys expire, if download failed once, call sock.updateMediaMessage(msg) and retry immediately
              if (!buffer && sock && typeof sock.updateMediaMessage === 'function') {
                try {
                  console.log(`[Media Download] Retrying audio download via sock.updateMediaMessage for ${senderPhone}...`);
                  const refreshedMsg = await sock.updateMediaMessage(msg);
                  buffer = await downloadMediaMessage(
                    refreshedMsg || msg,
                    'buffer',
                    {},
                    {
                      logger: pino({ level: 'silent' }),
                      reuploadRequest: sock?.updateMediaMessage
                    }
                  );
                } catch (retryErr) {
                  console.warn('[Media Download] updateMediaMessage retry notice:', retryErr.message);
                }
              }

              if (buffer && buffer.length > 0) {
                audioBase64 = buffer.toString('base64');
                audioDataUrl = `data:audio/ogg; codecs=opus;base64,${buffer.toString('base64')}`;
                console.log(`[Media Download] Downloaded voice note (${buffer.length} bytes) for ${senderPhone}`);
              }
            } catch (dlErr) {
              console.warn('[Media Download Error] Could not download voice buffer:', dlErr.message);
            }
if (!text) text = '[Voice note]';
          } else if (unwrappedMsg?.imageMessage) {
            isImage = true;
            typeMessage = 'imageMessage';
            if (!text) text = unwrappedMsg.imageMessage.caption || '[Photo]';
          } else if (unwrappedMsg?.documentMessage) {
            typeMessage = 'documentMessage';
            if (!text) text = unwrappedMsg.documentMessage.fileName || '[Document]';
          }

          // Guard: Ignore empty or non-content message events (reactions, protocol acks, typing events)
          if (!text && !isAudio && !isImage && !unwrappedMsg?.documentMessage && !unwrappedMsg?.locationMessage) {
            console.log(`[WhatsApp Bridge] Ignoring empty/non-content message event (${messageId}) from ${senderPhone}`);
            continue;
          }

          let audioMimeType = unwrappedMsg?.audioMessage?.mimetype || 'audio/ogg';

          // Extract quoted parent message context if present
          const contextInfo = unwrappedMsg?.extendedTextMessage?.contextInfo ||
                              unwrappedMsg?.imageMessage?.contextInfo ||
                              unwrappedMsg?.videoMessage?.contextInfo ||
                              unwrappedMsg?.audioMessage?.contextInfo ||
                              unwrappedMsg?.documentMessage?.contextInfo;
          const quotedMessage = contextInfo?.quotedMessage || null;
          const quotedStanzaId = contextInfo?.stanzaId || null;
          const quotedParticipant = cleanPhoneNumber(contextInfo?.participant || '');

          let extendedData = undefined;
          if (quotedMessage || quotedStanzaId) {
            extendedData = {
              text: text,
              stanzaId: quotedStanzaId,
              participant: quotedParticipant,
              quotedMessage: quotedMessage
            };
          } else if (text) {
            extendedData = {
              text: text
            };
          }

          const normalizedChatId = remoteJid.endsWith('@g.us') ? remoteJid : (remoteJid.endsWith('@lid') ? remoteJid : normalizeJid(senderPhone || remoteJid));

          console.log(`[Incoming Message] From: ${senderPhone} (${pushName}) | ID: ${messageId} | Chat: ${normalizedChatId} | Type: ${typeMessage} | Audio: ${Boolean(audioDataUrl || audioBase64)} | Text: "${text}"`);

          const payload = {
            typeWebhook: 'incomingMessageReceived',
            instanceData: {
              idInstance: 'baileys_bridge',
              wid: `${cleanPhoneNumber(sock?.user?.id || 'bridge')}@c.us`
            },
            timestamp,
            idMessage: messageId,
            senderData: {
              chatId: normalizedChatId,
              sender: senderPhone,
              chatName: chatTitle,
              senderName: pushName
            },
            messageData: {
              typeMessage: isAudio ? 'audio' : typeMessage,
              textMessageData: {
                textMessage: text
              },
              extendedTextMessageData: extendedData,
              quotedMessage: quotedMessage,
              stanzaId: quotedStanzaId,
              fileData: (isAudio || isVoice || isImage) ? {
                downloadUrl: audioDataUrl,
                mediaUrl: audioDataUrl,
                audioUrl: audioDataUrl,
                mimeType: isAudio ? 'audio/ogg' : (unwrappedMsg?.imageMessage?.mimetype || 'image/jpeg'),
                caption: text,
                duration: audioDuration || undefined,
                seconds: audioDuration || undefined
              } : undefined,
              fileMessageData: (isAudio || isVoice || isImage) ? {
                caption: text,
                mimeType: isAudio ? 'audio/ogg' : (unwrappedMsg?.imageMessage?.mimetype || 'image/jpeg'),
                audioBase64: audioBase64,
                mediaUrl: audioDataUrl,
                audioUrl: audioDataUrl,
                downloadUrl: audioDataUrl,
                duration: audioDuration || undefined,
                seconds: audioDuration || undefined
              } : undefined
            },
            chatId: normalizedChatId,
            remoteJid: remoteJid,
            from: senderPhone,
            from_phone: senderPhone,
            sender: senderPhone,
            senderName: pushName,
            chatName: chatTitle,
            groupSubject: isGroupChat ? chatTitle : undefined,
            isGroup: isGroupChat,
            message: text,
            body: text,
            type: isAudio ? 'audio' : typeMessage,
            message_type: isAudio ? 'audio' : typeMessage,
            mediaUrl: audioDataUrl,
            audioUrl: audioDataUrl,
            media_url: audioDataUrl,
            audio_url: audioDataUrl,
            downloadUrl: audioDataUrl,
            download_url: audioDataUrl,
            duration: audioDuration || undefined,
            seconds: audioDuration || undefined,
            audio_duration: audioDuration || undefined,
            fileData: (isAudio || isVoice || isImage) ? {
              downloadUrl: audioDataUrl,
              mediaUrl: audioDataUrl,
              audioUrl: audioDataUrl,
              mimeType: isAudio ? 'audio/ogg' : (unwrappedMsg?.imageMessage?.mimetype || 'image/jpeg'),
              duration: audioDuration || undefined,
              seconds: audioDuration || undefined
            } : undefined,
            audio_base64: audioBase64,
            audioBase64: audioBase64,
            parent_msg_id: quotedStanzaId,
            parent_message_id: quotedStanzaId,
            is_voice: isVoice,
            is_audio: isAudio,
            mimetype: isAudio ? 'audio/ogg' : undefined,
            mime_type: isAudio ? 'audio/ogg' : undefined,
            rawMessage: msg
          };

          try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 15000);
            const response = await fetch(PYTHON_WEBHOOK_URL, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'User-Agent': 'WhatsApp-Baileys-Bridge/1.0'
              },
              body: JSON.stringify(payload),
              signal: controller.signal
            });
            clearTimeout(timeoutId);

            console.log(`[Webhook Forward] Dispatched to ${PYTHON_WEBHOOK_URL} -> HTTP ${response.status}`);
          } catch (err) {
            console.error(`[Webhook Forward Error] Could not forward message to ${PYTHON_WEBHOOK_URL}:`, err.message);
          }
        }
      } catch (upsertErr) {
        console.error('[WhatsApp Bridge] messages.upsert processing error:', upsertErr.message);
      }
    });

    // Auto-reject incoming calls and send guidance message
    sock.ev.on('call', async (callEvents) => {
      try {
        if (!callEvents || !Array.isArray(callEvents)) return;

        for (const call of callEvents) {
          if (call.status === 'offer') {
            const callerJid = call.from || call.chatId;
            console.log(`[Incoming Call] Incoming call from ${callerJid} (Call ID: ${call.id})`);
            try {
              if (typeof sock?.rejectCall === 'function') {
                await sock.rejectCall(call.id, call.from);
                console.log(`[Incoming Call] Call ${call.id} rejected cleanly.`);
              }
            } catch (rejErr) {
              console.error(`[Incoming Call] Could not reject call ${call.id}:`, rejErr.message);
            }

            const targetJid = normalizeJid(callerJid);
            const callerPhone = cleanPhoneNumber(callerJid);

            // 1. Log call to dashboard backend
            try {
              const callPayload = {
                typeWebhook: 'incomingCallReceived',
                idMessage: `call_${call.id || Date.now()}`,
                timestamp: Math.floor(Date.now() / 1000),
                chatId: callerJid,
                from_phone: callerPhone,
                sender: callerPhone,
                caller: callerJid,
                callId: call.id,
                isVideo: Boolean(call.isVideo),
                status: 'missed_call',
                message_type: 'call',
                type: 'call',
                body: '📞 Incoming WhatsApp Voice Call (Auto-responded with AI voice note)'
              };
              await fetch(PYTHON_WEBHOOK_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'User-Agent': 'WhatsApp-Baileys-Bridge/1.0' },
                body: JSON.stringify(callPayload)
              }).then(r => r.text()).catch(e => console.warn('[Incoming Call] Webhook log warning:', e.message));
            } catch (whErr) {
              console.warn('[Incoming Call] Webhook notice:', whErr.message);
            }

            // 2. Immediate automated text response
            try {
              const autoRejectMessage =
                process.env.CALL_REJECT_MESSAGE ||
                "Assalam-o-Alaikum! Aap ki voice call receive nahi ho saki kyun kay yeh automated AI assistance number hai.\n\n" +
                "🎙️ Barah-e-karam apna paigham isi chat mein voice note ya text mein bhejein, main foran jawab doon ga.";
              if (sock && isConnected) {
                await sock.sendMessage(targetJid, { text: autoRejectMessage });
                console.log(`[Incoming Call] Sent text response to caller ${targetJid}`);
              }
            } catch (sendErr) {
              console.error(`[Incoming Call] Failed to send rejection text:`, sendErr.message);
            }

            // 3. Immediate automated AI voice note (PTT voice note)
            try {
              const voiceMsgText = "Assalam-o-Alaikum! Aap ki voice call receive nahi ho saki. Barah-e-karam apna paigham voice note ya text mein bhejein, main aap ki foran madad karoon ga.";
              const backendUrl = getBackendBaseUrl();
              const voiceResp = await fetch(`${backendUrl}/api/v1/voice/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: voiceMsgText, language: 'ur' })
              });
              if (voiceResp.ok) {
                const voiceData = await voiceResp.json();
                const b64 = voiceData.audio_base64 || (voiceData.audio_data_uri ? voiceData.audio_data_uri.split('base64,')[1] : null);
                if (b64 && sock && isConnected) {
                  const rawBuf = Buffer.from(b64, 'base64');
                  const oggBuf = await convertAudioToOggOpus(rawBuf).catch(() => rawBuf);
                  await sock.sendMessage(targetJid, {
                    audio: oggBuf,
                    mimetype: 'audio/ogg; codecs=opus',
                    ptt: true,
                    fileName: 'voice_reply.oga'
                  });
                  console.log(`[Incoming Call] Dispatched automated AI PTT voice note to ${targetJid}`);
                }
              }
            } catch (pttErr) {
              console.warn('[Incoming Call] AI PTT voice note dispatch notice:', pttErr.message);
            }
          }
        }
      } catch (callErr) {
        console.error('[WhatsApp Bridge] call event error:', callErr.message);
      }
    });
  } catch (fatalInitErr) {
    console.error('[WhatsApp Bridge] startWhatsAppBridge fatal error:', fatalInitErr);
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => {
      startWhatsAppBridge().catch(() => {});
    }, 5000);
  } finally {
    isStarting = false;
  }
}

// -------------------------------------------------------------
// Express HTTP Server
// -------------------------------------------------------------
const app = express();
app.use(express.json());

/**
 * Health & status endpoint
 */
app.get(['/', '/status'], (req, res) => {
  res.json({
    bridge: 'WhatsApp Baileys Bridge',
    status: isConnected ? 'connected' : (currentQr ? 'waiting_for_qr_scan' : 'connecting'),
    connected: isConnected,
    qrUrl: currentQrUrl,
    qr: currentQr,
    user: sock?.user || null,
    target_webhook: PYTHON_WEBHOOK_URL,
    uptime_seconds: Math.floor(process.uptime())
  });
});

/**
 * QR Code status endpoint (for inspection and live dashboard linking)
 */
app.get('/qr', async (req, res) => {
  // GUARD: If WhatsApp is already connected, return connected status immediately without resetting
  if (isConnected || (sock?.user && !currentQr)) {
    return res.json({
      status: 'connected',
      connected: true,
      qrUrl: null,
      qr: null,
      message: 'WhatsApp is already linked and connected.',
      user: sock?.user || null
    });
  }
  if (!currentQr) {
    return res.json({
      status: 'waiting',
      connected: false,
      qrUrl: null,
      message: 'QR code not generated yet or renewing.'
    });
  }

  // Ensure currentQrUrl is ready (base64 Data URI)
  let dataUrl = currentQrUrl;
  if (!dataUrl) {
    try {
      dataUrl = await qrcode.toDataURL(currentQr, {
        errorCorrectionLevel: 'M',
        type: 'image/png',
        margin: 2,
        width: 220,
        color: { dark: '#000000', light: '#ffffff' }
      });
      currentQrUrl = dataUrl;
    } catch (e) {
      console.error('[Bridge QR] Inline data URL generation error:', e);
    }
  }

  let svgData = currentQrSvg;
  if (!svgData) {
    try {
      svgData = await qrcode.toString(currentQr, { type: 'svg', margin: 2, width: 220 });
      currentQrSvg = svgData;
    } catch (e) {
      // ignore
    }
  }

  res.json({
    status: 'qr_ready',
    connected: false,
    qrUrl: dataUrl,
    qrImageUrl: dataUrl,
    qr: currentQr,
    qrSvg: svgData
  });
});

/**
 * Raw PNG QR image endpoint (serves live image/png stream directly)
 */
app.get(['/qr.png', '/qr-image'], async (req, res) => {
  if (!currentQr) {
    return res.status(404).send('QR code not ready yet.');
  }
  try {
    const buffer = await qrcode.toBuffer(currentQr, {
      errorCorrectionLevel: 'M',
      type: 'png',
      margin: 2,
      width: 220
    });
    res.setHeader('Content-Type', 'image/png');
    res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
    res.send(buffer);
  } catch (err) {
    res.status(500).send('Error generating QR image buffer');
  }
});

/**
 * Raw SVG QR endpoint
 */
app.get('/qr.svg', async (req, res) => {
  if (!currentQr) {
    return res.status(404).send('QR code not ready yet.');
  }
  try {
    const svg = await qrcode.toString(currentQr, { type: 'svg', margin: 2, width: 220 });
    res.setHeader('Content-Type', 'image/svg+xml');
    res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
    res.send(svg);
  } catch (err) {
    res.status(500).send('Error generating QR SVG');
  }
});

/**
 * Send Message Endpoint:
 * POST /send-message
 * Body: { "chatId": "923001234567", "message": "Hello from Bridge!" }
 */
/**
 * Explicit disconnect / logout endpoint
 * Unlinks the device ONLY when user intentionally clicks Disconnect
 */
app.post(['/disconnect', '/logout'], async (req, res) => {
  console.log('[WhatsApp Bridge] Explicit logout requested by user.');
  try {
    if (sock && typeof sock.logout === 'function') {
      await sock.logout();
    }
  } catch (_) {}

  isConnected = false;
  currentQr = null;
  currentQrUrl = null;
  currentQrSvg = null;

  try {
    if (fs.existsSync(AUTH_DIR)) {
      fs.rmSync(AUTH_DIR, { recursive: true, force: true });
      fs.mkdirSync(AUTH_DIR, { recursive: true });
    }
  } catch (err) {
    console.error('[WhatsApp Bridge] Failed to clean auth directory on logout:', err.message);
  }

  triggerSessionClear();
  destroyOldSocket();

  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    startWhatsAppBridge().catch(() => {});
  }, 1000);

  return res.json({
    success: true,
    message: 'WhatsApp device logged out and session cleared.'
  });
});

app.post(['/send-message', '/send'], async (req, res, next) => {
  try {
    let chatId = null;
    let message = null;

    try {
      chatId = req.body?.chatId || req.body?.to || req.body?.recipient || req.body?.to_phone || req.body?.phone || req.body?.target || req.body?.contact;
      message = req.body?.message !== undefined ? req.body.message : (req.body?.text !== undefined ? req.body.text : (req.body?.body !== undefined ? req.body.body : req.body?.caption));
    } catch (parseErr) {
      return res.status(400).json({
        success: false,
        error: `Failed to parse request payload: ${parseErr.message}`
      });
    }

    const audioRaw = req.body?.audioBase64 || req.body?.audio_base64 || req.body?.audio || req.body?.fileBase64 || req.body?.file_base64 || req.body?.dataUri || (typeof req.body?.mediaUrl === 'string' && req.body.mediaUrl.startsWith('data:audio') ? req.body.mediaUrl : null) || (typeof req.body?.media_url === 'string' && req.body.media_url.startsWith('data:audio') ? req.body.media_url : null) || (typeof req.body?.audioUrl === 'string' && req.body.audioUrl.startsWith('data:audio') ? req.body.audioUrl : null);
    const audioUrl = req.body?.audioUrl || req.body?.audio_url || req.body?.mediaUrl || req.body?.media_url || req.body?.urlFile || req.body?.url;
    const hasAudio = Boolean(audioRaw || audioUrl);
    const hasImage = Boolean(req.body?.imageBase64 || req.body?.image || req.body?.imageUrl);
    const hasText = message !== undefined && message !== null && String(message).trim().length > 0;

    if (!chatId || (!hasAudio && !hasImage && !hasText)) {
      return res.status(400).json({
        success: false,
        error: "Missing required fields. Please provide recipient chatId (e.g. '923001234567@s.whatsapp.net') and either message text or audioBase64/imageBase64."
      });
    }

    if (!sock || !isConnected) {
      return res.status(400).json({
        success: false,
        connected: false,
        error: "WhatsApp bridge is not connected yet. Please click 'Link WhatsApp QR' on the dashboard and scan the QR code."
      });
    }

    let jid = '';
    try {
      jid = normalizeJid(chatId);
    } catch (normErr) {
      return res.status(400).json({
        success: false,
        error: `Invalid chatId formatting: ${normErr.message}`
      });
    }

    // Link phone to LID using sock.onWhatsApp
    if (sock && typeof sock.onWhatsApp === 'function' && jid) {
      try {
        const results = await sock.onWhatsApp(jid);
        const res = results?.[0];
        if (res && res.exists) {
          const ph = res.jid ? cleanPhoneNumber(res.jid) : cleanPhoneNumber(chatId);
          const lid = res.lid;
          if (ph && lid) {
            lidToPhoneMap.set(lid, ph);
            phoneToLidMap.set(ph, lid);
          }
        }
      } catch (_) {}
    }
    const mappedLid = phoneToLidMap.get(cleanPhoneNumber(chatId)) || (chatId.startsWith('+') ? phoneToLidMap.get(cleanPhoneNumber(chatId.slice(1))) : null);
    if (mappedLid) { jid = mappedLid; }
  if (!jid || jid.startsWith('@') || (!jid.endsWith('@s.whatsapp.net') && !jid.endsWith('@g.us') && !jid.endsWith('@lid'))) {
      return res.status(400).json({
        success: false,
        error: `Invalid recipient JID: '${chatId}' -> '${jid}'. Outbound replies must strictly target a valid @s.whatsapp.net or @g.us JID.`
      });
    }

    // Strict guard: Do not allow sending to the bot's own linked session JID as an accidental fallback
    const botPhone = cleanPhoneNumber(sock?.user?.id || '');
    const targetPhone = cleanPhoneNumber(jid);
    const allowSelf = true;
    if (botPhone && targetPhone && botPhone === targetPhone && !allowSelf) {
      return res.status(400).json({
        success: false,
        error: `Recipient '${jid}' matches the bot's own active WhatsApp session number (+${botPhone}). Outbound replies must strictly target customer JIDs to prevent echo loops.`
      });
    }

    let sent = null;
    const quotedMessageId = req.body?.quotedMessageId || req.body?.quoted_message_id || req.body?.quotedId || req.body?.replyTo || req.body?.reply_to;
    const sendOptions = {};
    if (quotedMessageId) {
      sendOptions.quoted = {
        key: {
          remoteJid: jid,
          id: String(quotedMessageId),
          fromMe: false
        },
        message: {
          conversation: ''
        }
      };
    }

    // Rate-limiting / Anti-spam guard: Ensure minimum 1.5s spacing between messages to the same JID
    const lastSent = lastSendTimeMap.get(jid) || 0;
    const timeSinceLast = Date.now() - lastSent;
    if (timeSinceLast < 1500) {
      await new Promise(r => setTimeout(r, 1500 - timeSinceLast));
    }
    lastSendTimeMap.set(jid, Date.now());

    try {
      if (hasAudio) {
        // Non-blocking recording presence
        try {
          sock.sendPresenceUpdate('recording', jid).catch(() => {});
        } catch (_) {}
        let cleanBase64 = audioRaw ? String(audioRaw).replace(/^data:[^;]+;base64,/, '').trim() : '';
        let audioBuffer = cleanBase64 ? Buffer.from(cleanBase64, 'base64') : null;
        if (!audioBuffer && audioUrl && typeof audioUrl === 'string' && audioUrl.startsWith('data:audio')) {
          const rawB64 = audioUrl.replace(/^data:[^;]+;base64,/, '').trim();
          audioBuffer = Buffer.from(rawB64, 'base64');
        }

        const isVoiceReq = req.body?.ptt !== undefined ? Boolean(req.body.ptt) : (req.body?.is_voice !== undefined ? Boolean(req.body.is_voice) : true);
        let ptt = isVoiceReq;
        let mimetype = 'audio/ogg; codecs=opus';
        let finalAudioPayload = audioBuffer || { url: audioUrl };

        if (ptt && audioBuffer && Buffer.isBuffer(audioBuffer)) {
          const isAlreadyOgg = audioBuffer.slice(0, 4).toString() === 'OggS';
          if (!isAlreadyOgg) {
            try {
              console.log('[WhatsApp Bridge] Converting MP3/WAV buffer to OGG Opus via ffmpeg for WhatsApp PTT voice delivery...');
              const oggBuffer = await convertAudioToOggOpus(audioBuffer);
              finalAudioPayload = oggBuffer;
              mimetype = 'audio/ogg; codecs=opus';
              ptt = true;
              console.log('[WhatsApp Bridge] Successfully converted audio (' + audioBuffer.length + 'b -> ' + oggBuffer.length + 'b OGG Opus).');
            } catch (convErr) {
              console.warn('[WhatsApp Bridge] ffmpeg conversion failed or unavailable, falling back to ptt: false with audio/mp4:', convErr.message);
              finalAudioPayload = audioBuffer;
              mimetype = 'audio/mp4';
              ptt = false;
            }
          } else {
            mimetype = 'audio/ogg; codecs=opus';
            ptt = true;
          }
        } else if (!ptt) {
          mimetype = req.body?.mimetype || (cleanBase64.startsWith('T2dn') ? 'audio/ogg; codecs=opus' : 'audio/mp4');
        }

        const dur = Number(req.body?.seconds || req.body?.duration || 0) || (Buffer.isBuffer(finalAudioPayload) ? estimateAudioDuration(finalAudioPayload) : 0);
        const audioFileName = ptt ? 'voice_message.oga' : 'audio.mp4';

        try {
          sent = await sock.sendMessage(jid, {
            audio: finalAudioPayload,
            mimetype: mimetype,
            ptt: ptt,
            seconds: dur > 0 ? dur : undefined,
            fileName: audioFileName
          }, sendOptions);
        } catch (firstAudioErr) {
          console.warn('[Audio Send Warning] First attempt failed, retrying with fallback audio/mp4 (ptt: false):', firstAudioErr.message);
          sent = await sock.sendMessage(jid, {
            audio: finalAudioPayload,
            mimetype: 'audio/mp4',
            ptt: false,
            seconds: dur > 0 ? dur : undefined,
            fileName: 'audio.mp4'
          }, sendOptions);
        }
      } else if (hasImage) {
        const imageRaw = req.body?.imageBase64 || req.body?.image;
        const imageUrl = req.body?.imageUrl;
        const caption = message ? String(message) : '';

        if (imageRaw) {
          const cleanBase64 = String(imageRaw).replace(/^data:[^;]+;base64,/, '').trim();
          const imageBuffer = Buffer.from(cleanBase64, 'base64');
          sent = await sock.sendMessage(jid, {
            image: imageBuffer,
            caption
          }, sendOptions);
        } else if (imageUrl) {
          sent = await sock.sendMessage(jid, {
            image: { url: imageUrl },
            caption
          }, sendOptions);
        }
        try { await sock.sendPresenceUpdate('paused', jid); } catch (_) {}
      } else {
        // Non-blocking composing presence
        try {
          sock.sendPresenceUpdate('composing', jid).catch(() => {});
        } catch (_) {}

        const textToSend = String(message || '');
        sent = await sock.sendMessage(jid, { text: textToSend }, sendOptions);
        try { await sock.sendPresenceUpdate('paused', jid); } catch (_) {}
      }
    } catch (sendErr) {
      console.error(`[Outbound Message Send Error to ${jid}]:`, sendErr);
      return res.status(500).json({
        success: false,
        error: `Failed to send WhatsApp message via Baileys socket: ${sendErr.message || 'Unknown socket error'}`
      });
    }

    console.log(`[Outbound Message] Delivered via WhatsApp network to: ${jid} | Message ID: ${sent?.key?.id}`);

    return res.json({
      success: true,
      messageId: sent?.key?.id || null,
      idMessage: sent?.key?.id || null,
      status: 'sent',
      to: jid,
      recipient: jid,
      timestamp: Math.floor(Date.now() / 1000)
    });
  } catch (err) {
    console.error('[Outbound Message Unexpected Endpoint Error]', err);
    return res.status(500).json({
      success: false,
      error: err.message || 'Internal error while processing WhatsApp message request'
    });
  }
});

// Express global error-handling middleware (prevents any uncaught route exceptions from crashing Node)
app.use((err, req, res, next) => {
  console.error('[Bridge Server Global Error Handler]', err);
  if (!res.headersSent) {
    res.status(500).json({
      success: false,
      error: err.message || 'Internal bridge server error'
    });
  }
});

// Start Express server & WhatsApp bridge
const BIND_HOST = process.env.WA_BRIDGE_HOST || '127.0.0.1';
const server = app.listen(PORT, BIND_HOST, () => {
  console.log(`[Bridge Server] HTTP API server listening on http://localhost:${PORT}`);
  console.log(`[Bridge Server] Endpoint available: POST http://localhost:${PORT}/send-message`);
  console.log(`[Bridge Server] Initializing Baileys WhatsApp connection...`);
  startWhatsAppBridge().catch((err) => {
    console.error('[WhatsApp Bridge] Fatal startup error:', err);
  });
});

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    console.warn(`[Bridge Server] Port ${PORT} already bound by an active bridge instance.`);
  } else {
    console.error('[Bridge Server] Server error:', err);
  }
});






// Automated Socket Heartbeat & Recovery Monitor (checks every 20 seconds)
setInterval(() => {
  if (isConnected && sock) {
    const wsState = sock.ws?.readyState;
    // WebSocket readyState: 0=CONNECTING, 1=OPEN, 2=CLOSING, 3=CLOSED
    if (wsState !== undefined && wsState > 1) {
      console.warn(`[WhatsApp Bridge Heartbeat] Dead socket detected (readyState=${wsState}). Auto-recovering...`);
      isConnected = false;
      destroyOldSocket();
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(() => {
        startWhatsAppBridge().catch(() => {});
      }, 1000);
    }
  }
}, 20000);
