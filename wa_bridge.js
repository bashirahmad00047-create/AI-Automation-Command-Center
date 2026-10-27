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
  fetchLatestBaileysVersion
} = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const qrcodeTerminal = require('qrcode-terminal');
const qrcode = require('qrcode');
const pino = require('pino');
const path = require('path');
const fs = require('fs');

// Configuration
const PORT = process.env.WA_BRIDGE_PORT || process.env.BRIDGE_PORT || 3001;
const PYTHON_WEBHOOK_URL = process.env.PYTHON_WEBHOOK_URL || 'http://localhost:5000/api/v1/webhooks/whatsapp';
const AUTH_DIR = process.env.AUTH_DIR || path.join(__dirname, 'baileys_auth');

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
      if (typeof sock.end === 'function') {
        sock.end(undefined);
      }
    } catch (_) {}
    sock = null;
  }
}

/**
 * Normalizes phone numbers / chat IDs to Baileys JID format.
 * - Handles group chats: 12345-67890@g.us
 * - Handles legacy/Green-API chats: 923001234567@c.us -> 923001234567@s.whatsapp.net
 * - Handles plain numbers / international format: +92 300 1234567 -> 923001234567@s.whatsapp.net
 */
function normalizeJid(chatId) {
  if (!chatId) return '';
  let jid = String(chatId).trim();

  if (jid.endsWith('@g.us')) {
    return jid;
  }
  if (jid.endsWith('@c.us')) {
    return jid.replace('@c.us', '@s.whatsapp.net');
  }
  if (jid.endsWith('@s.whatsapp.net')) {
    return jid;
  }

  // Strip all non-digit characters
  const cleanDigits = jid.replace(/[^0-9]/g, '');
  return `${cleanDigits}@s.whatsapp.net`;
}

/**
 * Extracts plain text from various Baileys message types.
 */
function extractMessageText(message) {
  if (!message) return '';

  return (
    message.conversation ||
    message.extendedTextMessage?.text ||
    message.imageMessage?.caption ||
    message.videoMessage?.caption ||
    message.documentMessage?.caption ||
    message.buttonsResponseMessage?.selectedButtonId ||
    message.templateButtonReplyMessage?.selectedId ||
    message.listResponseMessage?.singleSelectReply?.selectedRowId ||
    message.interactiveResponseMessage?.nativeFlowResponseMessage?.paramsJson ||
    ''
  );
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
      console.error('[WhatsApp Bridge] Auth state corrupted or unreadable. Resetting auth directory:', authErr.message);
      try {
        if (fs.existsSync(AUTH_DIR)) {
          fs.rmSync(AUTH_DIR, { recursive: true, force: true });
          fs.mkdirSync(AUTH_DIR, { recursive: true });
        }
        const auth = await useMultiFileAuthState(AUTH_DIR);
        state = auth.state;
        saveCreds = auth.saveCreds;
      } catch (resetErr) {
        console.error('[WhatsApp Bridge] Fatal error resetting auth state:', resetErr);
        throw resetErr;
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
      browser: ['BashFlow Cloud', 'Chrome', '1.0.0']
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
          width: 320,
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
          width: 320
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

        const isLoggedOut = (statusCode === DisconnectReason.loggedOut || statusCode === 401 || statusCode === 403);
        console.warn(`[WhatsApp Bridge] Connection closed (code: ${statusCode}, isLoggedOut: ${isLoggedOut}).`);

        // If session was logged out or credentials became invalid, wipe auth directory
        // so a fresh QR code is immediately generated on restart
        if (isLoggedOut) {
          console.warn('[WhatsApp Bridge] Session logged out or invalidated. Clearing auth folder to refresh QR...');
          try {
            if (fs.existsSync(AUTH_DIR)) {
              fs.rmSync(AUTH_DIR, { recursive: true, force: true });
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

    // Forward incoming messages to Python backend webhook
    sock.ev.on('messages.upsert', async ({ messages, type }) => {
      try {
        if (type !== 'notify' || !messages || !Array.isArray(messages)) return;

        for (const msg of messages) {
          // Ignore outgoing messages sent from this phone
          if (msg.key?.fromMe) continue;

          // Ignore broadcast status stories
          if (msg.key?.remoteJid === 'status@broadcast') continue;

          const remoteJid = msg.key?.remoteJid || '';
          const senderPhone = remoteJid.replace(/@.*$/, '');
          const pushName = msg.pushName || senderPhone || 'WhatsApp User';
          const messageId = msg.key?.id || `msg_${Date.now()}`;
          const timestamp = msg.messageTimestamp ? Number(msg.messageTimestamp) : Math.floor(Date.now() / 1000);
          const text = extractMessageText(msg.message);

          console.log(`[Incoming Message] From: +${senderPhone} (${pushName}) | ID: ${messageId} | Text: "${text}"`);

          const payload = {
            typeWebhook: 'incomingMessageReceived',
            instanceData: {
              idInstance: 'baileys_bridge',
              wid: `${sock?.user?.id?.split(':')[0] || 'bridge'}@c.us`
            },
            timestamp,
            idMessage: messageId,
            senderData: {
              chatId: remoteJid,
              sender: remoteJid,
              chatName: pushName,
              senderName: pushName
            },
            messageData: {
              typeMessage: 'textMessage',
              textMessageData: {
                textMessage: text
              }
            },
            chatId: remoteJid,
            from: senderPhone,
            from_phone: senderPhone,
            senderName: pushName,
            message: text,
            body: text,
            rawMessage: msg
          };

          try {
            const response = await fetch(PYTHON_WEBHOOK_URL, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'User-Agent': 'WhatsApp-Baileys-Bridge/1.0'
              },
              body: JSON.stringify(payload)
            });

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
                "🎙️ Please send a voice note directly in this chat, or join our Live AI Voice Call on our dashboard:\n" +
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
        width: 320,
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
      svgData = await qrcode.toString(currentQr, { type: 'svg', margin: 2, width: 320 });
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
      width: 320
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
    const svg = await qrcode.toString(currentQr, { type: 'svg', margin: 2, width: 320 });
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
      chatId = req.body?.chatId || req.body?.to || req.body?.phone;
      message = req.body?.message !== undefined ? req.body.message : (req.body?.text !== undefined ? req.body.text : req.body?.body);
    } catch (parseErr) {
      return res.status(400).json({
        success: false,
        error: `Failed to parse request payload: ${parseErr.message}`
      });
    }

    if (!chatId || message === undefined || message === null) {
      return res.status(400).json({
        success: false,
        error: "Missing required fields. Please provide { chatId, message } in JSON body."
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

    if (!jid || jid.startsWith('@')) {
      return res.status(400).json({
        success: false,
        error: `Invalid chatId provided: '${chatId}'`
      });
    }

    const textToSend = String(message);
    let sent = null;
    try {
      sent = await sock.sendMessage(jid, { text: textToSend });
    } catch (sendErr) {
      console.error(`[Outbound Message Send Error to ${jid}]:`, sendErr);
      return res.status(500).json({
        success: false,
        error: `Failed to send WhatsApp message via Baileys socket: ${sendErr.message || 'Unknown socket error'}`
      });
    }

    console.log(`[Outbound Message] Sent to: ${jid} | Message ID: ${sent?.key?.id}`);

    return res.json({
      success: true,
      messageId: sent?.key?.id || null,
      status: 'sent',
      to: jid,
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
