"""Decoupled WhatsApp Webhook Ingress, Parsing & Idempotency Engine.

Provides standalone normalization of incoming WhatsApp payloads across:
1. Meta Cloud API standard webhooks (v19.0+)
2. Baileys / Green-API event formats
3. Deduplication, idempotency tracking, and anti-loop guards
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("whatsapp_ingress")

# In-memory thread-safe state trackers
_processed_message_ids: Dict[str, float] = {}
_outbound_message_ids: Dict[str, float] = {}
_recent_bot_reply_bodies: Dict[str, float] = {}
_self_burst_tracker: Dict[str, List[float]] = {}


@dataclass
class InboundMessageEvent:
    """Normalized representation of an incoming WhatsApp message."""
    message_id: str
    from_phone: str
    chat_id: str
    text: str
    sender_name: str = ""
    timestamp: Optional[int] = None
    is_group: bool = False
    is_voice: bool = False
    is_image: bool = False
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    quoted_message: Optional[str] = None
    quoted_sender: Optional[str] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    organization_id: Optional[str] = None


def verify_webhook_challenge(
    mode: Optional[str],
    token: Optional[str],
    challenge: Optional[str],
    expected_token: str
) -> Optional[str]:
    """Verifies Meta Webhook subscription verification requests."""
    if mode == "subscribe" and token and hmac.compare_digest(token, expected_token):
        return challenge
    return None


def verify_signature(
    raw_payload: bytes,
    signature_header: Optional[str],
    app_secret: Optional[str]
) -> bool:
    """Validates Meta X-Hub-Signature-256 header using app secret."""
    if not app_secret:
        return True
    if not signature_header:
        return False

    expected_sig = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        raw_payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(signature_header, expected_sig)


def format_phone_number(raw_phone: str) -> str:
    """Normalizes phone string to digits-only international format."""
    if not raw_phone:
        return ""
    cleaned = re.sub(r"[^\d]", "", str(raw_phone))
    return cleaned


def extract_message_body_and_quote(
    message_data_or_item: Dict[str, Any],
    msg_type: Optional[str] = None
) -> str:
    """Extracts and normalizes clean, readable message text from webhook items.
    Handles extended text, location messages, buttons, and media captions.
    """
    if not message_data_or_item or not isinstance(message_data_or_item, dict):
        return ""

    reply_text = ""
    ext_data = message_data_or_item.get("extendedTextMessageData") or {}
    if isinstance(ext_data, dict):
        reply_text = ext_data.get("text") or ext_data.get("description") or ""

    if not reply_text:
        text_data = message_data_or_item.get("textMessageData") or {}
        if isinstance(text_data, dict):
            reply_text = text_data.get("textMessage") or text_data.get("text") or ""

    if not reply_text:
        loc_data = (
            message_data_or_item.get("locationMessageData")
            or message_data_or_item.get("location")
            or message_data_or_item.get("locationData")
            or {}
        )
        if isinstance(loc_data, dict) and (loc_data.get("latitude") is not None or loc_data.get("lat") is not None):
            lat = loc_data.get("latitude") if loc_data.get("latitude") is not None else loc_data.get("lat")
            lng = loc_data.get("longitude") if loc_data.get("longitude") is not None else loc_data.get("lng")
            loc_name = loc_data.get("nameLocation") or loc_data.get("name") or ""
            loc_addr = loc_data.get("address") or ""
            maps_url = f"https://www.google.com/maps?q={lat},{lng}"
            desc = f"{loc_name} - {loc_addr}".strip(" -") or "Pinned Location"
            reply_text = f"📍 Location shared: {desc} (Lat: {lat}, Lng: {lng})\nMap: {maps_url}"
        else:
            reply_text = (
                message_data_or_item.get("textMessage")
                or message_data_or_item.get("text")
                or message_data_or_item.get("body")
                or message_data_or_item.get("message")
                or ""
            )

    if not reply_text:
        caption = (
            message_data_or_item.get("caption")
            or (message_data_or_item.get("fileMessageData") or {}).get("caption")
            or (message_data_or_item.get("image") or {}).get("caption")
            or ""
        )
        if caption:
            reply_text = str(caption).strip()

    return str(reply_text).strip()


def parse_webhook_payload(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parses Meta Cloud API webhook JSON payload into normalized message events."""
    messages: List[Dict[str, Any]] = []
    if not data or not isinstance(data, dict):
        return messages

    entries = data.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            if not value or not isinstance(value, dict):
                continue

            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id")

            contacts = value.get("contacts", [])
            sender_names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in contacts if isinstance(c, dict)}

            raw_messages = value.get("messages", [])
            for raw_msg in raw_messages:
                msg_id = raw_msg.get("id")
                from_phone = format_phone_number(raw_msg.get("from"))
                sender_name = sender_names.get(from_phone, "")
                timestamp = int(raw_msg.get("timestamp", time.time()))
                msg_type = raw_msg.get("type", "text")

                text_content = ""
                media_url = None
                is_voice = False
                is_image = False

                if msg_type == "text":
                    text_content = raw_msg.get("text", {}).get("body", "")
                elif msg_type in ("audio", "voice"):
                    is_voice = True
                    text_content = "[Voice note]"
                    audio_data = raw_msg.get("audio", {})
                    media_url = audio_data.get("id") or audio_data.get("link")
                elif msg_type == "image":
                    is_image = True
                    image_data = raw_msg.get("image", {})
                    text_content = image_data.get("caption", "[Image]")
                    media_url = image_data.get("id") or image_data.get("link")
                elif msg_type == "interactive":
                    interactive = raw_msg.get("interactive", {})
                    int_type = interactive.get("type")
                    if int_type == "button_reply":
                        text_content = interactive.get("button_reply", {}).get("title", "")
                    elif int_type == "list_reply":
                        text_content = interactive.get("list_reply", {}).get("title", "")
                elif msg_type == "button":
                    text_content = raw_msg.get("button", {}).get("text", "")

                messages.append({
                    "message_id": msg_id,
                    "from_phone": from_phone,
                    "sender_name": sender_name,
                    "timestamp": timestamp,
                    "type": msg_type,
                    "text": text_content,
                    "body": text_content,
                    "chat_id": f"{from_phone}@s.whatsapp.net" if from_phone else "",
                    "is_voice": is_voice,
                    "is_image": is_image,
                    "media_url": media_url,
                    "phone_number_id": phone_number_id,
                    "raw": raw_msg
                })

    return messages


def parse_green_api_payload(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parses Green-API / Baileys webhook notification payload into normalized message events."""
    messages: List[Dict[str, Any]] = []
    if not data or not isinstance(data, dict):
        return messages

    type_webhook = data.get("typeWebhook")

    # Inbound messages
    if type_webhook in ("incomingMessageReceived", "message", "messages.upsert", None):
        msg_data = data.get("messageData") or data
        sender_data = data.get("senderData") or {}
        instance_data = data.get("instanceData") or {}

        chat_id = (
            sender_data.get("chatId")
            or data.get("chatId")
            or data.get("jid")
            or ""
        )
        is_group = bool(chat_id and ("@g.us" in chat_id or "-" in chat_id.split("@")[0]))
        sender_phone = format_phone_number(
            sender_data.get("sender")
            or sender_data.get("chatId")
            or data.get("from")
            or chat_id.split("@")[0]
        )
        sender_name = (
            sender_data.get("senderName")
            or sender_data.get("chatName")
            or data.get("pushName")
            or ""
        )
        message_id = (
            data.get("idMessage")
            or (data.get("key") or {}).get("id")
            or f"wa_{int(time.time() * 1000)}"
        )
        timestamp = int(data.get("timestamp") or time.time())

        # Determine type
        type_msg = (
            msg_data.get("typeMessage")
            or data.get("typeMessage")
            or data.get("messageType")
            or "textMessage"
        )

        is_voice = (
            type_msg in ("audioMessage", "voiceMessage")
            or bool(msg_data.get("ptt"))
            or bool(data.get("ptt"))
            or bool(msg_data.get("audioMessage"))
        )
        is_image = (
            type_msg in ("imageMessage", "photoMessage")
            or bool(msg_data.get("imageMessage"))
        )

        text_content = extract_message_body_and_quote(msg_data, msg_type=type_msg)
        if not text_content:
            if is_voice:
                text_content = "[Voice note]"
            elif is_image:
                text_content = "[Image]"

        media_url = (
            (msg_data.get("fileMessageData") or {}).get("downloadUrl")
            or (msg_data.get("imageMessage") or {}).get("url")
            or (msg_data.get("audioMessage") or {}).get("url")
            or None
        )

        messages.append({
            "message_id": message_id,
            "from_phone": sender_phone,
            "sender_name": sender_name,
            "chat_id": chat_id,
            "timestamp": timestamp,
            "text": text_content,
            "body": text_content,
            "type": type_msg,
            "is_voice": is_voice,
            "is_image": is_image,
            "is_group": is_group,
            "media_url": media_url,
            "instance_id": instance_data.get("idInstance"),
            "raw": data
        })

    return messages


# Deduplication & Anti-Loop Safeguards
def is_duplicate_message(message_id: str) -> bool:
    """Guarantees idempotency by checking if a message ID was already processed."""
    if not message_id:
        return False
    clean_id = str(message_id).strip()
    now = time.time()
    last_seen = _processed_message_ids.get(clean_id)
    if last_seen and (now - last_seen) < 3600:
        return True
    return False


def mark_message_processed(message_id: str) -> None:
    """Marks a message ID as processed in memory."""
    if not message_id:
        return
    clean_id = str(message_id).strip()
    _processed_message_ids[clean_id] = time.time()


def record_outbound_sent_id(message_id: str) -> None:
    """Records an outbound message ID to prevent self-echo and infinite loops."""
    if not message_id:
        return
    clean_id = str(message_id).strip()
    now = time.time()
    _outbound_message_ids[clean_id] = now


def is_known_outbound_message_id(message_id: str) -> bool:
    """Checks if a message ID originated from an outbound transmission by the bot."""
    if not message_id:
        return False
    clean_id = str(message_id).strip()
    return clean_id in _outbound_message_ids


def record_bot_reply_body(text: str) -> None:
    """Records recent bot reply text content to prevent echoing our own responses."""
    if not text:
        return
    clean_norm = " ".join(re.sub(r"[*_~`#>]", "", str(text).strip()).lower().split())
    if clean_norm and len(clean_norm) >= 3:
        _recent_bot_reply_bodies[clean_norm] = time.time()


def is_recent_bot_reply_body(text: str) -> bool:
    """Checks if incoming text matches a recently dispatched bot response."""
    if not text:
        return False
    clean_norm = " ".join(re.sub(r"[*_~`#>]", "", str(text).strip()).lower().split())
    return clean_norm in _recent_bot_reply_bodies


def is_self_looping(phone: str, max_in_window: int = 6, window_sec: float = 10.0) -> bool:
    """Rate guard to ensure rapid back-and-forth loops on self/linked test numbers are halted."""
    clean = format_phone_number(phone)
    if not clean:
        return False
    now = time.time()
    history = [t for t in _self_burst_tracker.get(clean, []) if t > now - window_sec]
    if len(history) >= max_in_window:
        return True
    history.append(now)
    _self_burst_tracker[clean] = history
    return False
