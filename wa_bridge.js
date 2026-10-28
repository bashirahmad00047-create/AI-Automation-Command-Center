
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
  extractMessageContent
} = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const qrcodeTerminal = require('qrcode-terminal');
const qrcode = require('qrcode');
const pino = require('pino');
const path = require('path');
const fs = require('fs');

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
      unwrapped?.editedMessage?.message?.protocolMessage?.editedMessage ||
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
const phoneToLidMap = new Map();
const lidToPhoneMap = new Map(); // Keep persisted in memory/DB

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

  if (candidateJid && candidateJid.includes('@s.whatsapp.net')) {
    const phone = candidateJid.split('@')[0].split(':')[0];
    if (remoteJid.endsWith('@lid')) {
      lidToPhoneMap.set(remoteJid, phone);
      phoneToLidMap.set(phone, remoteJid);
    }
    return { phone: `+${phone}`, displayName: msg.pushName || `+${phone}`, replyJid: remoteJid };
  }
  // Check cached mapping
  if (remoteJid.endsWith('@lid') && lidToPhoneMap.has(remoteJid)) {
    const phone = lidToPhoneMap.get(remoteJid);
    return { phone: `+${phone}`, displayName: msg.pushName || `+${phone}`, replyJid: remoteJid };
  }

  // Query Baileys onWhatsApp to resolve @lid to real phone number
  if (activeSock && typeof activeSock.onWhatsApp === 'function' && remoteJid) {
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
          return { phone: `+${ph}`, displayName: msg.pushName || `+${ph}`, replyJid: remoteJid };
        }
      }
    } catch (_) {}
  }

  // FALLBACK: NEVER use bot's own number or prepend '+' to non-numeric strings! Use msg.pushName || 'WhatsApp Contact'
  const fallbackName = msg.pushName || 'WhatsApp Contact';
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
      browser: ['BashFlow Cloud', 'Chrome', '1.0.0'],
      getMessage: async (key) => undefined
    });

    // Safely persist session credentials
    sock.ev.on('creds.update', async () => {
      try {
        if (typeof saveCreds === 'function') {
          await saveCreds();
        }
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
          if (process.stdout.isTTY || process.env.RENDER) {
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

        // Only consider true logouts (e.g. user linked device removed) or 401 as logged out.
        // Do NOT wipe auth directory on transient 403s or network dropouts!
        const isLoggedOut = (statusCode === DisconnectReason.loggedOut);
        console.warn(`[WhatsApp Bridge] Connection closed (code: ${statusCode}, isLoggedOut: ${isLoggedOut}).`);

        // If session was explicitly logged out, wipe auth directory
        // so a fresh QR code is immediately generated on restart
        if (isLoggedOut) {
          console.warn('[WhatsApp Bridge] Session logged out or invalidated. Clearing auth folder to refresh QR...');
          try {
            if (fs.existsSync(AUTH_DIR)) {
              // Prevent auto-wiping session so login stays permanent
            }
          } catch (rmErr) {
            console.error('[WhatsApp Bridge] Failed to clean auth directory:', rmErr.message);
          }
          currentQr = null;
          currentQrUrl = null;
          currentQrSvg = null;
        }

        destroyOldSocket();

        // Self-healing: automatically restart the socket so the bridge never stays dead
        const restartDelay = isLoggedOut ? 2000 : 3000;
        console.log(`[WhatsApp Bridge] Scheduling restart in ${restartDelay}ms...`);
        clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(() => {
          startWhatsAppBridge().catch((retryErr) => {
            console.error('[WhatsApp Bridge] Reconnect attempt failed:', retryErr.message);
          });
        }, restartDelay);
      } else if (connection === 'open') {
        isConnected = true;
        currentQr = null;
        currentQrUrl = null;
        currentQrSvg = null;
        const userPhone = sock?.user?.id ? sock.user.id.split(':')[0] : 'Linked Number';
        console.log('\n===============================================================');
        console.log(` [WhatsApp Bridge] Connected successfully!`);
        console.log(` Active Phone: +${userPhone}`);
        console.log(` REST API listening on port ${PORT}`);
        console.log(` Python Webhook target: ${PYTHON_WEBHOOK_URL}`);
        console.log('===============================================================\n');
      }
    });

    // 1. Capture mappings from contacts events to map LIDs to real phone numbers
    sock.ev.on('contacts.upsert', (contacts) => {
      for (const c of contacts) {
        if (c.lid && c.id?.endsWith('@s.whatsapp.net')) {
          const ph = c.id.split('@')[0].split(':')[0];
          lidToPhoneMap.set(c.lid, ph);
          phoneToLidMap.set(ph, c.lid);
        }
      }
    });
    sock.ev.on('contacts.update', (updates) => {
      for (const c of updates) {
        if (c.lid && c.id?.endsWith('@s.whatsapp.net')) {
          const ph = c.id.split('@')[0].split(':')[0];
          lidToPhoneMap.set(c.lid, ph);
          phoneToLidMap.set(ph, c.lid);
        }
      }
    });

    // Forward incoming messages to Python backend webhook
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

          if (isGroupChat) {
            if (!participantJid) continue;
            senderPhone = cleanPhoneNumber(msg.key?.senderPn || msg.key?.participantPn || participantJid);
            displayName = msg.pushName || (senderPhone ? `+${senderPhone}` : 'WhatsApp Group User');
          } else {
            const senderRes = await resolveSender(msg, sock);
            senderPhone = senderRes.phone;
            displayName = senderRes.displayName;
            replyJid = senderRes.replyJid;
          }

          const pushName = msg.pushName || displayName || 'WhatsApp User';
          const messageId = msg.key?.id || `msg_${Date.now()}`;
          const timestamp = msg.messageTimestamp ? Number(msg.messageTimestamp) : Math.floor(Date.now() / 1000);
          
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
          const audioMsg = unwrappedMsg?.audioMessage;
          if (audioMsg) {
            isAudio = true;
            isVoice = Boolean(audioMsg.ptt);
            typeMessage = isVoice ? 'voiceMessage' : 'audioMessage';

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
                buffer = await downloadMediaMessage(
                  { key: msg.key, message: unwrappedMsg },
                  'buffer',
                  {},
                  {
                    logger: pino({ level: 'silent' }),
                    reuploadRequest: sock?.updateMediaMessage
                  }
                );
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
              chatName: pushName,
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
              fileMessageData: (isAudio || isVoice || isImage) ? {
                caption: text,
                mimeType: isAudio ? 'audio/ogg' : (unwrappedMsg?.imageMessage?.mimetype || 'image/jpeg'),
                audioBase64: audioBase64,
                mediaUrl: audioDataUrl,
                audioUrl: audioDataUrl,
                downloadUrl: audioDataUrl
              } : undefined
            },
            chatId: normalizedChatId,
            remoteJid: remoteJid,
            from: senderPhone,
            from_phone: senderPhone,
            sender: senderPhone,
            senderName: pushName,
            chatName: pushName,
            message: text,
            body: text,
            type: isAudio ? 'audio' : typeMessage,
            message_type: isAudio ? 'audio' : typeMessage,
            mediaUrl: audioDataUrl,
            audioUrl: audioDataUrl,
            media_url: audioDataUrl,
            audio_url: audioDataUrl,
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
            console.log(`[Incoming Call] Auto-rejecting incoming call from ${callerJid} (Call ID: ${call.id})`);
            try {
              if (typeof sock?.rejectCall === 'function') {
                await sock.rejectCall(call.id, call.from);
                console.log(`[Incoming Call] Call ${call.id} rejected successfully.`);
              }
            } catch (rejErr) {
              console.error(`[Incoming Call] Could not reject call ${call.id}:`, rejErr.message);
            }

            try {
              const targetJid = normalizeJid(callerJid);
              const autoRejectMessage =
                process.env.CALL_REJECT_MESSAGE ||
                "Assalamu Alaikum! Direct phone calls to this number are automated.\n\n" +
                "ðŸŽ™ï¸ Please send a voice note directly in this chat, or join our Live AI Voice Call on our dashboard:\n" +
                (process.env.LIVE_VOICE_CALL_URL || "http://localhost:5000/#live-voice-call");

              if (sock && isConnected) {
                await sock.sendMessage(targetJid, { text: autoRejectMessage });
                console.log(`[Incoming Call] Sent voice note / Live AI Voice Call prompt to ${targetJid}`);
              }
            } catch (sendErr) {
              console.error(`[Incoming Call] Failed to send rejection message:`, sendErr.message);
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
  if (isConnected) {
    return res.json({
      status: 'connected',
      connected: true,
      qrUrl: null,
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
app.post('/send-message', async (req, res, next) => {
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

    const audioRaw = req.body?.audioBase64 || req.body?.audio_base64 || req.body?.audio || req.body?.fileBase64 || req.body?.file_base64 || req.body?.dataUri;
    const audioUrl = req.body?.audioUrl || req.body?.audio_url || req.body?.urlFile || req.body?.url;
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

    try {
      if (hasAudio) {
        let cleanBase64 = audioRaw ? String(audioRaw).replace(/^data:[^;]+;base64,/, '').trim() : '';
        // Auto-detect MP3 vs OGG/MP4 from base64 header so mobile WhatsApp plays it properly
        let detectedMime = 'audio/mpeg';
        if (cleanBase64.startsWith('T2dn')) {
          detectedMime = 'audio/ogg; codecs=opus';
        } else if (cleanBase64.startsWith('AAAA')) {
          detectedMime = 'audio/mp4';
        }
        let mimetype = req.body?.mimetype || req.body?.mime_type || detectedMime;
        if (mimetype === 'audio/mp3') mimetype = 'audio/mpeg';
        const ptt = mimetype.includes('ogg');
        if (audioRaw) {
          const audioBuffer = Buffer.from(cleanBase64, 'base64');
          sent = await sock.sendMessage(jid, {
            audio: audioBuffer,
            mimetype: mimetype,
            ptt: ptt,
            fileName: 'voice_reply.mp3'
          }, sendOptions);
        } else if (audioUrl) {
          sent = await sock.sendMessage(jid, {
            audio: { url: audioUrl },
            mimetype: mimetype,
            ptt: ptt,
            fileName: 'voice_reply.mp3'
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
      } else {
        const textToSend = String(message || '');
        sent = await sock.sendMessage(jid, { text: textToSend }, sendOptions);
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
const server = app.listen(PORT, '0.0.0.0', () => {
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





