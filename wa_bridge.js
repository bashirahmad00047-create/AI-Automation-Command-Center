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
const qrcode = require('qrcode-terminal');
const pino = require('pino');
const path = require('path');
const fs = require('fs');

// Configuration
const PORT = process.env.PORT || 3001;
const PYTHON_WEBHOOK_URL = process.env.PYTHON_WEBHOOK_URL || 'http://localhost:5000/api/v1/webhooks/whatsapp';
const AUTH_DIR = process.env.AUTH_DIR || path.join(__dirname, 'baileys_auth');

// Global socket state
let sock = null;
let isConnected = false;
let currentQr = null;

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
  // Ensure auth storage directory exists
  if (!fs.existsSync(AUTH_DIR)) {
    fs.mkdirSync(AUTH_DIR, { recursive: true });
  }

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version, isLatest } = await fetchLatestBaileysVersion();
  console.log(`[WhatsApp Bridge] Using WA Web v${version.join('.')}, isLatest: ${isLatest}`);

  // Create socket with silent logger to keep terminal QR clean
  sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: 'silent' }),
    printQRInTerminal: false,
    syncFullHistory: false
  });

  // Persist session credentials
  sock.ev.on('creds.update', saveCreds);

  // Connection life-cycle handler
  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;

    // Display QR code in terminal when generated
    if (qr) {
      currentQr = qr;
      console.log('\n===============================================================');
      console.log('  SCAN THIS QR CODE IN WHATSAPP TO LINK FOR FREE');
      console.log('  Steps: WhatsApp -> Settings/Menu -> Linked Devices -> Link a Device');
      console.log('===============================================================');
      qrcode.generate(qr, { small: true });
      console.log('===============================================================\n');
    }

    if (connection === 'close') {
      isConnected = false;
      const statusCode =
        lastDisconnect?.error instanceof Boom
          ? lastDisconnect.error.output?.statusCode
          : lastDisconnect?.error?.output?.statusCode;

      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      console.warn(`[WhatsApp Bridge] Connection closed (code: ${statusCode}). Reconnecting: ${shouldReconnect}`);

      if (shouldReconnect) {
        setTimeout(startWhatsAppBridge, 3000);
      } else {
        console.error('[WhatsApp Bridge] Session logged out. Remove "baileys_auth" folder to generate a new QR.');
        currentQr = null;
      }
    } else if (connection === 'open') {
      isConnected = true;
      currentQr = null;
      const userPhone = sock.user?.id ? sock.user.id.split(':')[0] : 'Linked Number';
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
    if (type !== 'notify') return;

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

      // Prepare payload: includes standard Green-API / OpsFlow ingress format & flat properties
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
        // Flat properties for direct consumption
        chatId: remoteJid,
        from: senderPhone,
        from_phone: senderPhone,
        senderName: pushName,
        message: text,
        body: text,
        rawMessage: msg
      };

      // Forward to Python backend
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
  });

  // -----------------------------------------------------------
  // Auto-reject incoming calls and send guidance message
  // -----------------------------------------------------------
  sock.ev.on('call', async (callEvents) => {
    for (const call of callEvents) {
      if (call.status === 'offer') {
        const callerJid = call.from || call.chatId;
        console.log(`[Incoming Call] Auto-rejecting incoming call from ${callerJid} (Call ID: ${call.id})`);
        try {
          await sock.rejectCall(call.id, call.from);
          console.log(`[Incoming Call] Call ${call.id} rejected successfully.`);
        } catch (rejErr) {
          console.error(`[Incoming Call] Could not reject call ${call.id}:`, rejErr.message);
        }

        // Send message asking caller to send a voice note or join the Live AI Voice Call
        try {
          const targetJid = normalizeJid(callerJid);
          const autoRejectMessage =
            process.env.CALL_REJECT_MESSAGE ||
            "Assalamu Alaikum! Direct phone calls to this number are automated.\n\n" +
            "🎙️ Please send a voice note directly in this chat, or join our Live AI Voice Call on our dashboard:\n" +
            (process.env.LIVE_VOICE_CALL_URL || "http://localhost:5000/#live-voice-call");

          await sock.sendMessage(targetJid, { text: autoRejectMessage });
          console.log(`[Incoming Call] Sent voice note / Live AI Voice Call prompt to ${targetJid}`);
        } catch (sendErr) {
          console.error(`[Incoming Call] Failed to send rejection message:`, sendErr.message);
        }
      }
    }
  });
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
 * QR Code status endpoint (for inspection if terminal is not visible)
 */
app.get('/qr', (req, res) => {
  if (isConnected) {
    return res.json({ status: 'connected', message: 'WhatsApp is already linked and connected.' });
  }
  if (!currentQr) {
    return res.json({ status: 'waiting', message: 'QR code not generated yet or renewing.' });
  }
  res.json({ status: 'qr_ready', qr: currentQr });
});

/**
 * Send Message Endpoint:
 * POST /send-message
 * Body: { "chatId": "923001234567", "message": "Hello from Bridge!" }
 */
app.post('/send-message', async (req, res) => {
  try {
    const chatId = req.body.chatId || req.body.to || req.body.phone;
    const message = req.body.message || req.body.text || req.body.body;

    if (!chatId || message === undefined || message === null) {
      return res.status(400).json({
        success: false,
        error: "Missing required fields. Please provide { chatId, message } in JSON body."
      });
    }

    if (!sock || !isConnected) {
      return res.status(503).json({
        success: false,
        error: "WhatsApp bridge is not connected. Please scan the QR code in the terminal to link your WhatsApp."
      });
    }

    const jid = normalizeJid(chatId);
    if (!jid || jid.startsWith('@')) {
      return res.status(400).json({
        success: false,
        error: `Invalid chatId provided: '${chatId}'`
      });
    }

    const textToSend = String(message);
    const sent = await sock.sendMessage(jid, { text: textToSend });

    console.log(`[Outbound Message] Sent to: ${jid} | Message ID: ${sent?.key?.id}`);

    return res.json({
      success: true,
      messageId: sent?.key?.id || null,
      status: 'sent',
      to: jid,
      timestamp: Math.floor(Date.now() / 1000)
    });
  } catch (err) {
    console.error('[Outbound Message Error]', err);
    return res.status(500).json({
      success: false,
      error: err.message || 'Internal error while sending WhatsApp message'
    });
  }
});

// Start Express server & WhatsApp bridge
app.listen(PORT, () => {
  console.log(`[Bridge Server] HTTP API server listening on http://localhost:${PORT}`);
  console.log(`[Bridge Server] Endpoint available: POST http://localhost:${PORT}/send-message`);
  console.log(`[Bridge Server] Initializing Baileys WhatsApp connection...`);
  startWhatsAppBridge().catch((err) => {
    console.error('[WhatsApp Bridge] Fatal startup error:', err);
  });
});
