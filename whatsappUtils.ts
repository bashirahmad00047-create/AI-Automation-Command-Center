import { proto, downloadMediaMessage, WASocket } from '@whiskeysockets/baileys';
import fs from 'fs';
import path from 'path';

export interface ExtractedSender {
  rawJid: string;
  cleanNumber: string | null;
  isGroup: boolean;
  groupId: string | null;
}

export interface ProcessedAudio {
  base64: string;
  dataUri: string;
  publicUrl: string;
  fileName: string;
  duration?: number;
}

/**
 * 1. REAL PHONE NUMBER EXTRACTION
 * Baileys ke complex JID formats se exact 10-15 digit real number nikaalta hai:
 * - Direct: "923001234567@s.whatsapp.net" -> "923001234567"
 * - Multi-Device: "923001234567:45@s.whatsapp.net" -> "923001234567"
 * - Group: "12036302@g.us" -> sender participant ka number nikaalega
 */
export function extractRealPhoneNumber(msg: proto.IWebMessageInfo): ExtractedSender {
  const remoteJid = msg.key.remoteJid || '';
  const isGroup = remoteJid.endsWith('@g.us');
  
  // Status broadcast ya newsletter ko ignore karein
  if (remoteJid.includes('@broadcast') || remoteJid.includes('@newsletter')) {
    return { rawJid: remoteJid, cleanNumber: null, isGroup: false, groupId: null };
  }

  // Agar group hai toh real sender 'participant' field mein hota hai
  const targetJid = isGroup 
    ? (msg.key.participant || (msg as any).participant || '') 
    : remoteJid;

  if (!targetJid) {
    return { rawJid: remoteJid, cleanNumber: null, isGroup, groupId: isGroup ? remoteJid : null };
  }

  // Multi-device identifier (:1, :2 etc.) aur domain (@s.whatsapp.net) ko strip karein
  const rawId = targetJid.split('@')[0];
  const withoutDevice = rawId.split(':')[0];

  // Sirf numbers filter karein
  const cleanDigits = withoutDevice.replace(/\D/g, '');

  // International standard E.164 phone numbers 10 se 15 digits ke hotay hain
  const isValidNumber = cleanDigits.length >= 10 && cleanDigits.length <= 15;

  return {
    rawJid: targetJid,
    cleanNumber: isValidNumber ? cleanDigits : null,
    isGroup,
    groupId: isGroup ? remoteJid : null,
  };
}

/**
 * 2. VOICE NOTE (OGG/OPUS) DOWNLOAD & CONVERSION
 * Voice notes ko buffer download karke Base64 aur Public Static storage dono banata hai
 */
export async function processVoiceNote(
  sock: WASocket,
  msg: proto.IWebMessageInfo,
  publicUploadsDir: string,
  baseUrl: string
): Promise<ProcessedAudio | null> {
  const audioMessage = msg.message?.audioMessage;
  if (!audioMessage) return null;

  try {
    // Media stream download karein Baileys ke native buffer downloader se
    const buffer = (await downloadMediaMessage(
      msg,
      'buffer',
      {},
      {
        logger: sock.logger,
        reuploadRequest: sock.updateMediaMessage,
      }
    )) as Buffer;

    if (!buffer || buffer.length === 0) {
      throw new Error('Downloaded audio buffer is empty.');
    }

    // Storage folder ensure karein
    if (!fs.existsSync(publicUploadsDir)) {
      fs.mkdirSync(publicUploadsDir, { recursive: true });
    }

    const messageId = msg.key.id || `vn_${Date.now()}`;
    const fileName = `${messageId}.ogg`;
    const filePath = path.join(publicUploadsDir, fileName);

    // Disk par save karein (Dashboard streaming ke liye)
    await fs.promises.writeFile(filePath, buffer);

    // Browser Base64 Data URI (Instant frontend play baghair storage delay ke)
    const base64Audio = buffer.toString('base64');
    const dataUri = `data:audio/ogg;codecs=opus;base64,${base64Audio}`;
    const publicUrl = `${baseUrl}/uploads/audio/${fileName}`;

    return {
      base64: base64Audio,
      dataUri,
      publicUrl,
      fileName,
      duration: audioMessage.seconds ? Number(audioMessage.seconds) : undefined,
    };
  } catch (error) {
    console.error('[Audio Processing Error]:', error);
    return null;
  }
}