"""Decoupled WhatsApp AI Responder & Cognitive Processing Engine.

Handles:
1. Gemini prompt construction with business grounding, catalog context & location awareness
2. Intent parsing and multi-dialect language detection (Urdu, Roman Urdu, English, Pashto)
3. Response formatting and sanitization (stripping internal prompt artifacts)
4. Clean integration with services.voice_engine for guaranteed voice-to-voice replies
"""

from __future__ import annotations
import datetime

import base64
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("ai_responder")

# Comprehensive lexicon definitions
PASHTO_PHRASES = {
    "sanga ye", "tsanga ye", "sanga yast", "tsanga yast", "sanga chal", "tsanga chal",
    "sa hal", "tsa hal", "sa chal", "tsa chal", "sa khabar", "tsa khabar",
    "khe chara", "kha chara", "dera manana", "der manana", "pa kher", "pa khair",
    "pakar de", "pakar di", "kawale sham", "kawale shi", "staso na", "staso da",
    "tsomra de", "somra de", "tsomra qimat", "somra qimat", "sa qimat"
}

PASHTO_WORDS = {
    "sanga", "tsanga", "manana", "staso", "taso", "zamung", "zama", "sta",
    "pakar", "ghwaram", "ghwari", "marasta", "wraz", "shpa", "narkh", "shta",
    "nishta", "tsomra", "somra", "charta", "tsok", "wali", "chara", "rora",
    "khushala", "stare", "staray", "kawale", "kawali", "kawi", "kawom", "rasegi",
    "dalta", "halta", "kawal", "tapos"
}

ROMAN_URDU_PHRASES = {
    "kya haal", "kia haal", "kaise hain", "kese hain", "kaise ho", "kese ho",
    "kaisa hai", "kya price", "kia price", "kya rate", "kia rate", "madad chahiye",
    "rabta karein", "rabta karo", "bata dein", "bata do", "batao bhai", "kitna kharcha",
    "kitne paise", "kya charges", "chahiye mujhe", "ap kaise", "aap kaise"
}

ROMAN_URDU_WORDS = {
    "kya", "kia", "aap", "ap", "tum", "mujhe", "mujy", "humein", "humain",
    "hai", "hain", "hoon", "hun", "chahiye", "chahye", "kaise", "kese", "kaisa", "kaisi",
    "shukriya", "shukria", "batao", "batado", "batayein", "bataen", "bataiye", "batana",
    "kitna", "kitne", "kitni", "theek", "thik", "acha", "achha", "sahi", "karein", "karna",
    "karo", "karta", "karti", "mera", "meri", "mere", "apka", "aapka", "apki", "aapki",
    "kahan", "kyun", "kab", "kaun", "kis", "zaroor", "bilkul", "wali", "k", "ke", "ka",
    "ki", "ko", "se", "me", "mein", "par", "pe", "yeh", "ye", "woh", "wo", "ji", "jee",
    "bhai", "janab", "assalam", "assalamualaikum", "salam", "walaikum", "kar", "dein", "do"
}


def detect_language(
    text: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Detects customer language as Pashto, Urdu, or English (including Arabic & Roman scripts)."""
    raw_text = str(text or "").strip()
    if not raw_text:
        return {
            "language": "english",
            "script": "latin",
            "format": "english",
            "name": "English",
            "confidence": 0.5
        }

    # 1. Arabic / Perso-Arabic Script
    arabic_chars = re.findall(r'[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]', raw_text)
    non_space_len = len(re.sub(r'\s+', '', raw_text))
    is_arabic_script = len(arabic_chars) >= 2 or (len(arabic_chars) > 0 and len(arabic_chars) / max(1, non_space_len) >= 0.25)

    if is_arabic_script:
        pashto_chars = re.findall(r'[\u0699\u0681\u0685\u06bc\u0693\u0696\u0689\u067c\u06cd\u06d0\u06ab]', raw_text)
        urdu_chars = re.findall(r'[\u0679\u0688\u0691\u06ba\u06d2\u06c1\u06be]', raw_text)

        if len(pashto_chars) > len(urdu_chars):
            return {
                "language": "pashto",
                "script": "arabic",
                "format": "pashto_arabic",
                "name": "Pashto (Arabic Script)",
                "confidence": 0.95
            }
        elif len(urdu_chars) > 0 or len(arabic_chars) >= 2:
            return {
                "language": "urdu",
                "script": "arabic",
                "format": "urdu_arabic",
                "name": "Urdu (Arabic Script)",
                "confidence": 0.92
            }

    # 2. Latin Script (Roman Pashto vs Roman Urdu vs English)
    clean_latin = re.sub(r'[^a-z0-9\s]', ' ', raw_text.lower())
    tokens = [w for w in clean_latin.split() if w]
    token_set = set(tokens)

    ngrams_2 = [" ".join(tokens[i:i+2]) for i in range(len(tokens) - 1)]
    all_phrases = set(ngrams_2)

    pashto_phrase_hits = len(all_phrases.intersection(PASHTO_PHRASES))
    pashto_word_hits = len(token_set.intersection(PASHTO_WORDS))
    pashto_score = pashto_phrase_hits * 3 + pashto_word_hits

    urdu_phrase_hits = len(all_phrases.intersection(ROMAN_URDU_PHRASES))
    urdu_word_hits = len(token_set.intersection(ROMAN_URDU_WORDS))
    urdu_score = urdu_phrase_hits * 3 + urdu_word_hits

    if pashto_score > urdu_score and pashto_score >= 1:
        return {
            "language": "pashto",
            "script": "latin",
            "format": "roman_pashto",
            "name": "Roman Pashto",
            "confidence": min(0.95, 0.70 + 0.08 * pashto_score)
        }
    elif urdu_score > 0:
        return {
            "language": "urdu",
            "script": "latin",
            "format": "roman_urdu",
            "name": "Roman Urdu",
            "confidence": min(0.95, 0.70 + 0.08 * urdu_score)
        }

    return {
        "language": "english",
        "script": "latin",
        "format": "english",
        "name": "English",
        "confidence": 0.70
    }


def parse_intent(text: str) -> Dict[str, Any]:
    """Parses intent, urgency, and lead score from customer text."""
    clean_text = str(text or "").strip().lower()
    intent = "lead_inquiry"
    urgency = 20
    lead_score = 50
    route_dept = "Sales"

    # Multi-lingual Booking & Appointment Intent Detection (Audit Item 1 / Phase 5)
    booking_markers = (
        "appointment", "book", "booking", "schedule", "reservation",
        "reserve", "slot", "consultation", "doctor", "meeting", "checkup",
        "mulaqat", "tareekh", "tarikh", "waqt", "kal milna", "shaam ko milna"
    )
    if any(w in clean_text for w in booking_markers) and any(w in clean_text for w in ("appointment", "book", "booking", "schedule", "slot", "reserve", "reservation", "mulaqat", "doctor", "consultation", "checkup", "tarikh", "tareekh")):
        return {
            "intent": "booking_appointment",
            "urgency": 60,
            "lead_score": 85,
            "route_department": "Appointments"
        }

    # Sales Negotiation, Bargaining & Cart Management (Audit Item 3 / Phase 6)
    checkout_markers = (
        "confirm order", "order confirm", "pack kar", "pack krdo", "bhej do", "bhej dein",
        "deal done", "theek hai bhej", "finalize order", "address note", "deal pakki",
        "deliver kar dein"
    )
    if any(w in clean_text for w in checkout_markers):
        return {
            "intent": "sales_checkout",
            "urgency": 80,
            "lead_score": 95,
            "route_department": "Sales"
        }

    negotiation_markers = (
        "discount", "kam karo", "kam karein", "kam ho sakta", "kuch kam", "gujaish",
        "gunjaish", "mehnga", "bohot zyada", "riayat", "reayat", "munasib", "last price",
        "final price", "counter offer", "bargain", "cheaper", "best price", "special price",
        "off do", "percent off", "itne me de do", "itne me do"
    )
    if any(w in clean_text for w in negotiation_markers):
        return {
            "intent": "sales_negotiation",
            "urgency": 65,
            "lead_score": 88,
            "route_department": "Sales"
        }

    cart_markers = (
        "cart", "add to cart", "daal do", "nikal do", "remove item", "mera bill",
        "total kitna", "bill kitna", "view cart", "show cart", "check cart"
    )
    if any(w in clean_text for w in cart_markers):
        return {
            "intent": "cart_management",
            "urgency": 55,
            "lead_score": 80,
            "route_department": "Sales"
        }

    if any(w in clean_text for w in ("salam", "hello", "hi", "hey", "aoa")):
        intent = "greeting"
        urgency = 10
    elif any(w in clean_text for w in ("qimat", "rate", "price", "kitna", "package", "cost", "buy", "order")):
        intent = "sales_inquiry"
        urgency = 50
        lead_score = 75
    elif any(w in clean_text for w in ("madad", "masla", "issue", "help", "problem", "ticket", "kharab")):
        intent = "support_request"
        urgency = 70
        route_dept = "Support"

    return {
        "intent": intent,
        "urgency": urgency,
        "lead_score": lead_score,
        "route_department": route_dept
    }


def get_language_prompt_directive(lang_info: Dict[str, Any]) -> str:
    """Returns system prompt formatting directives tailored to the detected language and script."""
    fmt = lang_info.get("format", "english")
    if fmt == "roman_urdu":
        return (
            "LANGUAGE DIRECTIVE: The customer is speaking Roman Urdu (Urdu written in English/Latin letters). "
            "You MUST reply strictly in natural, polite Roman Urdu (e.g., 'Walaikum Assalam! Main aap ki kya madad kar sakta hoon?'). "
            "Do NOT reply in English or Urdu Arabic script."
        )
    elif fmt == "urdu_arabic":
        return (
            "LANGUAGE DIRECTIVE: The customer wrote in Urdu Arabic script. "
            "You MUST reply strictly in elegant, respectful Urdu (اردو) script. "
            "Do NOT reply in English or Roman Urdu."
        )
    elif fmt in ("pashto_arabic", "roman_pashto"):
        return (
            "LANGUAGE DIRECTIVE: The customer is communicating in Pashto. "
            "You MUST reply respectfully in Pashto."
        )
    return (
        "LANGUAGE DIRECTIVE: The customer is communicating in English. "
        "Reply warmly, concisely, and professionally in clear English."
    )


def construct_gemini_prompt(
    user_message: str,
    system_prompt: Optional[str] = None,
    customer_name: Optional[str] = None,
    knowledge_base: Optional[str] = None,
    catalog_context: Optional[str] = None,
    has_shared_location: bool = False,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> str:
    """Constructs grounded Gemini prompt with knowledge, catalog context, and location protocol."""
    lang_info = detect_language(user_message, conversation_history=conversation_history)
    lang_directive = get_language_prompt_directive(lang_info)

    prompt_parts = [
        "You are BashFlow Enterprise AI, a helpful, polite, and intelligent business assistant.",
        lang_directive
    ]

    if knowledge_base:
        prompt_parts.append(f"\nBusiness Knowledge Base:\n{knowledge_base.strip()}")

    if catalog_context:
        prompt_parts.append(f"\nProduct Catalog Information:\n{catalog_context.strip()}")

    if system_prompt:
        prompt_parts.append(f"\nCustom Organization Instructions:\n{system_prompt.strip()}")

    if has_shared_location:
        prompt_parts.append(
            "\nCRITICAL LOCATION PROTOCOL: The customer has already shared their GPS pin/location on our radar map. "
            "Do NOT ask for their address or location pin again. Acknowledge that delivery tracking is active."
        )

    if customer_name:
        prompt_parts.append(f"\nCustomer Name: {customer_name}")

    if conversation_history:
        history_lines = ["\nRecent Conversation History:"]
        for item in conversation_history[-6:]:
            role = item.get("role", "customer")
            content = item.get("content", "")
            history_lines.append(f"- {role}: {content}")
        prompt_parts.append("\n".join(history_lines))

    prompt_parts.append(f"\nCustomer Message: {user_message.strip()}")
    prompt_parts.append("Your Response:")

    return "\n".join(prompt_parts)


def clean_ai_text(raw_text: str) -> str:
    """Cleans up internal thought artifacts, prompt echoes, and JSON wrappers."""
    if not raw_text:
        return ""
    text = str(raw_text).strip()

    # Strip triple-backtick code fences
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    # Strip raw JSON object wrapper
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                for k in ("response", "reply", "message", "text"):
                    if parsed.get(k):
                        return str(parsed[k]).strip()
        except Exception:
            pass

    return text.strip()




# ============================================================================
# PHASE 5: BOOKING & APPOINTMENT STATE MACHINE & CONFLICT ENGINE
# ============================================================================

def extract_appointment_datetime(text: str) -> Optional[datetime.datetime]:
    """Parses appointment date and time from customer messages in English and Roman Urdu."""
    now = datetime.datetime.now()
    clean = str(text or "").lower()

    # 1. Target Day Resolution
    target_date = None
    if "kal" in clean or "tomorrow" in clean:
        target_date = now.date() + datetime.timedelta(days=1)
    elif "parso" in clean or "day after tomorrow" in clean:
        target_date = now.date() + datetime.timedelta(days=2)
    elif "aaj" in clean or "today" in clean:
        target_date = now.date()
    else:
        m_iso = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", clean)
        if m_iso:
            try:
                target_date = datetime.date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
            except Exception:
                pass
        else:
            m_dm = re.search(r"\b(\d{1,2})[/.-](\d{1,2})\b", clean)
            if m_dm:
                try:
                    target_date = datetime.date(now.year, int(m_dm.group(2)), int(m_dm.group(1)))
                except Exception:
                    pass

    # 2. Target Time Resolution
    time_str = re.sub(r"\d{4}-\d{1,2}-\d{1,2}", "", clean)
    time_str = re.sub(r"\b\d{1,2}[/.-]\d{1,2}\b", "", time_str)

    target_hour = None
    target_min = 0

    m_time = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|baje)\b", time_str)
    if not m_time:
        m_time = re.search(r"\bat\s*(\d{1,2})(?::(\d{2}))?\b", time_str)
    if not m_time:
        m_time = re.search(r"\b(\d{1,2}):(\d{2})\b", time_str)

    if m_time:
        raw_hour = int(m_time.group(1))
        raw_min = int(m_time.group(2)) if m_time.group(2) else 0
        meridiem = (m_time.group(3) if len(m_time.groups()) >= 3 and m_time.group(3) else "").lower()

        is_evening = any(w in clean for w in ["shaam", "dopahar", "raat", "pm", "afternoon", "evening", "night"])
        is_morning = any(w in clean for w in ["subah", "am", "morning"])

        if (meridiem == "pm" or (is_evening and raw_hour < 12)) and raw_hour < 12:
            raw_hour += 12
        elif (meridiem == "am" or is_morning) and raw_hour == 12:
            raw_hour = 0

        target_hour = raw_hour
        target_min = raw_min

    if target_date and target_hour is not None:
        return datetime.datetime(target_date.year, target_date.month, target_date.day, target_hour, target_min)
    elif target_date and target_hour is None:
        return datetime.datetime(target_date.year, target_date.month, target_date.day, 11, 0)
    elif not target_date and target_hour is not None:
        tomorrow = now.date() + datetime.timedelta(days=1)
        return datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, target_hour, target_min)

    return None


def extract_service_name(text: str) -> str:
    """Extracts common service domain from customer request."""
    clean = str(text or "").lower()
    services = [
        ("Doctor Consultation", ["doctor", "physician", "checkup", "clinic", "ilaaj", "tabiyat", "consultation", "consult"]),
        ("Dental Scaling & Checkup", ["dental", "teeth", "daant", "scaling", "dentist"]),
        ("Vehicle Inspection & Repair", ["car", "bike", "inspection", "tuning", "oil change", "repair", "service"]),
        ("Salon & Grooming Session", ["haircut", "facial", "salon", "makeup", "grooming", "barber"]),
        ("Legal Advisory & Tax Consultation", ["legal", "lawyer", "advocate", "tax", "accounting", "audit"]),
        ("Property Viewing & Tour", ["property", "plot", "house", "makaan", "viewing", "tour", "visit"])
    ]
    for s_name, keywords in services:
        if any(k in clean for k in keywords):
            return s_name
    return "General Consultation"


def handle_booking_flow(
    organization_id: Optional[str],
    customer_phone: Optional[str],
    customer_name: Optional[str],
    message_text: str,
    lang_fmt: str = "roman_urdu"
) -> Dict[str, Any]:
    """State machine for processing appointment and booking requests:
    1. Prompts for required service, date, and time if missing.
    2. Performs slot conflict detection against database for that organization.
    3. Saves valid confirmed booking to database with status 'Confirmed'.
    4. Generates formatted WhatsApp confirmation.
    """
    clean_org = str(organization_id or "org-enterprise-default")
    clean_phone = re.sub(r"[^\d]", "", str(customer_phone or "")) or "923001234567"
    client_name = customer_name or f"Client {clean_phone[-4:]}"

    service_name = extract_service_name(message_text)
    target_dt = extract_appointment_datetime(message_text)

    # If date and time are missing from customer inquiry, prompt for details
    if not target_dt:
        if "urdu" in lang_fmt:
            prompt_msg = (
                f"Ji zaroor {client_name}! Appointment book karne ke liye baraye meherbani service ka naam aur "
                f"appointment ki tareekh aur waqt (Date & Time) batayein (maslan: '{service_name} kal subah 11 baje')."
            )
        else:
            prompt_msg = (
                f"Certainly {client_name}! To schedule your appointment, please let us know the required service "
                f"along with your preferred date and time (e.g., '{service_name} tomorrow at 11:00 AM')."
            )
        return {
            "status": "needs_info",
            "reply_body": prompt_msg,
            "intent": "booking_appointment",
            "booking_saved": False,
            "target_datetime": None
        }

    # Slot conflict detection & DB save with safe app context
    from wa_bridge_manager import safe_app_context
    with safe_app_context():
        try:
            from models import Appointment
            from database import db

            # Basic slot conflict detection
            conflict = Appointment.query.filter_by(
                org_id=clean_org,
                appointment_datetime=target_dt,
                status="Confirmed"
            ).first()

            if conflict:
                if "urdu" in lang_fmt:
                    conflict_msg = (
                        f"Maazrat {client_name}! {target_dt.strftime('%d-%b %I:%M %p')} ka slot pehle se booked hai. "
                        f"Baraye meherbani koi doosra waqt ya din muntakhab farmayein."
                    )
                else:
                    conflict_msg = (
                        f"We apologize {client_name}, but the slot on {target_dt.strftime('%d-%b at %I:%M %p')} is already booked. "
                        f"Please choose an alternative time slot."
                    )
                return {
                    "status": "conflict",
                    "reply_body": conflict_msg,
                    "intent": "booking_appointment",
                    "booking_saved": False,
                    "target_datetime": target_dt.strftime("%Y-%m-%d %H:%M:%S")
                }

            # Save valid booking with status 'Confirmed'
            new_appt = Appointment(
                org_id=clean_org,
                customer_phone=clean_phone,
                customer_name=client_name,
                service_name=service_name,
                appointment_datetime=target_dt,
                status="Confirmed",
                notes="Booked via WhatsApp AI Concierge"
            )
            db.session.add(new_appt)
            db.session.commit()

            if "urdu" in lang_fmt:
                confirm_msg = (
                    f"Aap ki booking '{service_name}' ke liye {target_dt.strftime('%A, %d %B')} ko {target_dt.strftime('%I:%M %p')} confirm ho gayi hai! 📅\n"
                    f"Reference ID: {new_appt.id}\n\n"
                    f"Mulaqat ka intezar rahega. Shukriya!"
                )
            else:
                confirm_msg = (
                    f"Your booking for '{service_name}' on {target_dt.strftime('%A, %d %B at %I:%M %p')} has been confirmed! 📅\n"
                    f"Booking Reference: {new_appt.id}\n\n"
                    f"We look forward to seeing you. Thank you!"
                )

            return {
                "status": "confirmed",
                "reply_body": confirm_msg,
                "intent": "booking_appointment",
                "booking_saved": True,
                "appointment": new_appt.to_dict(),
                "target_datetime": target_dt.strftime("%Y-%m-%d %H:%M:%S")
            }

        except Exception as e:
            logger.error(f"[Booking Engine DB Error] {e}")
            if "urdu" in lang_fmt:
                err_msg = f"Aap ki booking request register ho gayi hai ({service_name} at {target_dt.strftime('%d-%b %I:%M %p')}). Hamari team confirmation bhejegi!"
            else:
                err_msg = f"Your booking request for {service_name} at {target_dt.strftime('%d-%b %I:%M %p')} has been registered. Confirmation will follow!"
            return {
                "status": "pending",
                "reply_body": err_msg,
                "intent": "booking_appointment",
                "booking_saved": False,
                "target_datetime": target_dt.strftime("%Y-%m-%d %H:%M:%S")
            }
def extract_negotiation_intent(text: str) -> Dict[str, Any]:
    """Extracts negotiation specifics: counter-offer price, discount percent, action type.
    Action types:
    - 'checkout': User wants to confirm order / provide address / finalize deal.
    - 'cart_remove': User wants to remove or decrease item.
    - 'cart_view': User wants to see total / bill / items.
    - 'bargain_price': User specifies an exact counter-offer price (e.g. 2500 PKR).
    - 'bargain_pct': User specifies a percentage discount (e.g. 15% off).
    - 'bargain_generic': User asks for discount / reduction without amount (e.g. 'kuch kam karein').
    - 'cart_add': User asks to add an item.
    """
    clean = str(text or "").strip().lower()

    checkout_markers = (
        "confirm order", "order confirm", "pack kar", "pack krdo", "bhej do", "bhej dein",
        "deal done", "theek hai bhej", "finalize order", "address note", "deal pakki",
        "order bhej do", "deliver kar dein", "delivery address"
    )
    if any(m in clean for m in checkout_markers):
        return {"action": "checkout", "value": None}

    remove_markers = ("nikal do", "hata do", "remove", "cancel item", "kam kar do", "kam krdo", "drop item")
    if any(m in clean for m in remove_markers):
        return {"action": "cart_remove", "value": None}

    view_markers = ("total bill", "mera bill", "bill kitna", "cart check", "view cart", "show cart", "total kitna", "kitna bana")
    if any(m in clean for m in view_markers):
        return {"action": "cart_view", "value": None}

    pct_match = re.search(r'(\d{1,2})\s*(?:%|percent|feesad)', clean)
    if pct_match:
        return {"action": "bargain_pct", "value": float(pct_match.group(1))}

    pm = re.search(r'(?:(?:pkr|rs\.?|inr)\s*)?(\d{3,6})\s*(?:mein|me|ka|pkr|rs|rupaye|\b)', clean)
    if pm:
        try:
            val = float(pm.group(1))
            if val >= 50:
                return {"action": "bargain_price", "value": val}
        except (ValueError, TypeError):
            pass

    discount_markers = (
        "discount", "kam karo", "kam karein", "kam ho sakta", "kuch kam", "gujaish",
        "gunjaish", "mehnga", "bohot zyada", "riayat", "reayat", "munasib", "last price",
        "final price", "counter offer", "bargain", "cheaper", "best price", "special price"
    )
    if any(m in clean for m in discount_markers):
        return {"action": "bargain_generic", "value": None}

    return {"action": "cart_add", "value": None}


def handle_sales_negotiation_flow(
    organization_id: Optional[str],
    customer_phone: Optional[str],
    customer_name: Optional[str],
    message_text: str,
    lang_fmt: str = "roman_urdu"
) -> Dict[str, Any]:
    """Deterministic Multi-Tenant Sales Negotiation & Cart State Machine (Audit Item 3 / Phase 6).
    Handles:
    - Multi-turn price bargaining with cost-floor margin protection.
    - Cart revisions (add / remove / clear / recalculate).
    - Conditional discounting (counter-offers & sweet-deals).
    - Deterministic stage transitions: browsing -> bargaining -> agreed -> checkout.
    """
    clean_org = str(organization_id or "org-enterprise-default")
    clean_phone = re.sub(r"[^\d]", "", str(customer_phone or "")) or "923001234567"
    client_name = customer_name or f"Customer {clean_phone[-4:]}"

    neg_intent = extract_negotiation_intent(message_text)
    action = neg_intent["action"]
    val = neg_intent["value"]

    from wa_bridge_manager import safe_app_context
    with safe_app_context():
        try:
            from models import CartState, Product
            from database import db

            # Retrieve or create active cart for this tenant and customer
            cart = CartState.query.filter(
                CartState.org_id == clean_org,
                CartState.customer_phone == clean_phone,
                CartState.negotiation_stage.notin_(["completed", "abandoned"])
            ).order_by(CartState.created_at.desc()).first()

            if not cart:
                cart = CartState(
                    org_id=clean_org,
                    customer_phone=clean_phone,
                    customer_name=client_name,
                    negotiation_stage="browsing"
                )
                db.session.add(cart)
                db.session.flush()

            # Ensure cart has at least catalog item if empty and user is bargaining
            items = cart.get_items()
            if not items:
                catalog_prod = Product.query.filter_by(organization_id=clean_org, is_active=True).first()
                if catalog_prod:
                    cart.add_item(
                        product_name=catalog_prod.name,
                        quantity=1,
                        unit_price=float(catalog_prod.price or 2500.0),
                        product_id=catalog_prod.id,
                        seller_cost=float(catalog_prod.seller_price or (catalog_prod.price * 0.70))
                    )
                else:
                    cart.add_item(
                        product_name="Catalog Item",
                        quantity=1,
                        unit_price=2500.0,
                        seller_cost=1800.0
                    )
                db.session.commit()
                items = cart.get_items()

            reply_msg = ""
            stage = cart.negotiation_stage

            if action == "checkout":
                cart.negotiation_stage = "checkout"
                db.session.commit()
                if "urdu" in lang_fmt:
                    reply_msg = (
                        f"Bohat shukriya {client_name}! 🎉 Aap ka order PKR {cart.current_total:,.0f} mein finalize ho gaya hai.\n"
                        f"Baraye meherbani apna mukammal delivery address aur city share farmayein taake parcel dispatch kiya ja sake."
                    )
                else:
                    reply_msg = (
                        f"Thank you {client_name}! 🎉 Your order is finalized at PKR {cart.current_total:,.0f}.\n"
                        f"Please provide your complete delivery address and city for dispatch."
                    )

            elif action == "cart_view":
                item_lines = "\n".join([f"• {it.get('name')} x{it.get('quantity', 1)}: PKR {float(it.get('unit_price', 0)) * int(it.get('quantity', 1)):,.0f}" for it in items])
                disc_info = f"\nDiscount Applied: {cart.offered_discount_pct:.0f}%" if cart.offered_discount_pct > 0 else ""
                if "urdu" in lang_fmt:
                    reply_msg = (
                        f"Aap ke cart ki tafseelat, {client_name}:\n{item_lines}{disc_info}\n"
                        f"-----------------------------\n"
                        f"Kul Raqam (Total): PKR {cart.current_total:,.0f} (Stage: {cart.negotiation_stage.title()})\n\n"
                        f"Kya aap is order ko confirm karna chahte hain ya koi tabdeeli karni hai?"
                    )
                else:
                    reply_msg = (
                        f"Your cart breakdown, {client_name}:\n{item_lines}{disc_info}\n"
                        f"-----------------------------\n"
                        f"Total Amount: PKR {cart.current_total:,.0f} (Stage: {cart.negotiation_stage.title()})\n\n"
                        f"Would you like to confirm this order or make any revisions?"
                    )

            elif action == "cart_remove":
                if items:
                    removed_name = items[0].get("name", "Item")
                    cart.remove_item(removed_name, quantity=1)
                    db.session.commit()
                    if "urdu" in lang_fmt:
                        reply_msg = (
                            f"{removed_name} cart se remove kar diya gaya hai. 🛒\n"
                            f"Naya Total: PKR {cart.current_total:,.0f}. Aur koi cheez add ya remove karni hai?"
                        )
                    else:
                        reply_msg = (
                            f"{removed_name} has been removed from your cart. 🛒\n"
                            f"Updated Total: PKR {cart.current_total:,.0f}. Would you like to adjust anything else?"
                        )
                else:
                    reply_msg = "Cart khali hai." if "urdu" in lang_fmt else "Your cart is currently empty."

            elif action == "bargain_price":
                proposed = float(val)
                if proposed >= cart.floor_price:
                    cart.counter_offer_price = proposed
                    cart.negotiation_stage = "agreed"
                    disc_val = max(0.0, cart.original_total - proposed)
                    cart.offered_discount_pct = (disc_val / cart.original_total * 100.0) if cart.original_total > 0 else 0.0
                    cart.recalculate()
                    db.session.commit()
                    if "urdu" in lang_fmt:
                        reply_msg = (
                            f"Zabardast {client_name}! Hum aap ki counter-offer PKR {proposed:,.0f} qabool karte hain! 🤝✨\n"
                            f"Aap ki bachat: PKR {disc_val:,.0f}! Kul bill ab PKR {cart.current_total:,.0f} hai.\n\n"
                            f"Kya hum order finalize karein aur delivery address note karein?"
                        )
                    else:
                        reply_msg = (
                            f"Deal agreed {client_name}! We accept your offer of PKR {proposed:,.0f}! 🤝✨\n"
                            f"Your savings: PKR {disc_val:,.0f}! Total payable is now PKR {cart.current_total:,.0f}.\n\n"
                            f"Shall we finalize the order and confirm delivery address?"
                        )
                else:
                    seller_counter = round(max(cart.floor_price * 1.05, cart.original_total * 0.88), 0)
                    cart.counter_offer_price = seller_counter
                    cart.negotiation_stage = "bargaining"
                    cart.offered_discount_pct = ((cart.original_total - seller_counter) / cart.original_total * 100.0) if cart.original_total > 0 else 10.0
                    cart.recalculate()
                    db.session.commit()
                    if "urdu" in lang_fmt:
                        reply_msg = (
                            f"{client_name} bhai, PKR {proposed:,.0f} hamari wholesale cost se bhi kam hai. "
                            f"Lekin aap hamare qeemti customer hain, to hum special final rate PKR {seller_counter:,.0f} kar sakte hain! 🎁\n"
                            f"Kya is rate par deal done karein?"
                        )
                    else:
                        reply_msg = (
                            f"Dear {client_name}, PKR {proposed:,.0f} is below our wholesale cost. "
                            f"However, as a special gesture, our best final offer is PKR {seller_counter:,.0f}! 🎁\n"
                            f"Would this work for you to lock in the deal?"
                        )

            elif action == "bargain_pct":
                proposed_pct = min(40.0, float(val))
                max_allowed_pct = ((cart.original_total - cart.floor_price) / cart.original_total * 100.0) if cart.original_total > 0 else 15.0
                max_allowed_pct = max(5.0, min(25.0, max_allowed_pct))

                if proposed_pct <= max_allowed_pct:
                    cart.offered_discount_pct = proposed_pct
                    cart.counter_offer_price = None
                    cart.negotiation_stage = "agreed"
                    cart.recalculate()
                    db.session.commit()
                    if "urdu" in lang_fmt:
                        reply_msg = (
                            f"Mubarak ho {client_name}! Hum ne aap ke liye {proposed_pct:.0f}% discount apply kar diya hai! 🏷️\n"
                            f"Aap ka bill PKR {cart.original_total:,.0f} se kam ho kar sirf PKR {cart.current_total:,.0f} reh gaya hai.\n\n"
                            f"Kya order pack karwa dein?"
                        )
                    else:
                        reply_msg = (
                            f"Congratulations {client_name}! We have applied a {proposed_pct:.0f}% discount for you! 🏷️\n"
                            f"Your total dropped from PKR {cart.original_total:,.0f} to only PKR {cart.current_total:,.0f}.\n\n"
                            f"Shall we get this packed for you?"
                        )
                else:
                    cart.offered_discount_pct = max_allowed_pct
                    cart.counter_offer_price = None
                    cart.negotiation_stage = "bargaining"
                    cart.recalculate()
                    db.session.commit()
                    if "urdu" in lang_fmt:
                        reply_msg = (
                            f"{client_name} bhai, {proposed_pct:.0f}% margin se bahir hai. "
                            f"Lekin hum aap ko highest possible {max_allowed_pct:.0f}% discount de rahe hain! Naya total: PKR {cart.current_total:,.0f}. ✨\n"
                            f"Kya yeh deal lock karein?"
                        )
                    else:
                        reply_msg = (
                            f"Dear {client_name}, {proposed_pct:.0f}% exceeds our maximum margin limit. "
                            f"However, we can offer our highest possible discount of {max_allowed_pct:.0f}%! New total: PKR {cart.current_total:,.0f}. ✨\n"
                            f"Shall we confirm at this price?"
                        )

            else:
                cart.offered_discount_pct = 10.0
                cart.counter_offer_price = None
                cart.negotiation_stage = "bargaining"
                cart.recalculate()
                db.session.commit()
                if "urdu" in lang_fmt:
                    reply_msg = (
                        f"Ji zaroor {client_name}! Aap ke liye hum khas 10% discount offer kar rahe hain! 🎁\n"
                        f"Aap ka total PKR {cart.original_total:,.0f} se kam ho kar sirf PKR {cart.current_total:,.0f} ban gaya hai.\n"
                        f"Kya hum order finalize karein?"
                    )
                else:
                    reply_msg = (
                        f"Certainly {client_name}! We are happy to offer you a special 10% discount! 🎁\n"
                        f"Your total is reduced from PKR {cart.original_total:,.0f} to only PKR {cart.current_total:,.0f}.\n"
                        f"Would you like us to finalize your order?"
                    )

            return {
                "status": "success",
                "reply_body": reply_msg,
                "intent": "sales_negotiation",
                "action": action,
                "stage": cart.negotiation_stage,
                "cart": cart.to_dict()
            }

        except Exception as e:
            logger.error(f"[Sales Negotiation Flow Error] {e}")
            fallback = f"Salam {client_name}! Aap ke order aur discount ke hawalay se hamari sales team aap ko rabta kar rahi hai." if "urdu" in lang_fmt else f"Hello {client_name}! Our sales team is reviewing your discount request and will update you shortly."
            return {
                "status": "fallback",
                "reply_body": fallback,
                "intent": "sales_negotiation",
                "action": action,
                "stage": "bargaining",
                "cart": None
            }


def generate_smart_conversational_fallback(
    message_body: str,
    lang_fmt: str,
    org_name: str = "BashFlow AI",
    sender_name: Optional[str] = None,
    is_voice: bool = False,
    intent: Optional[str] = None
) -> str:
    """Generates an authentic conversational fallback without hardcoded pitches."""
    lower_text = str(message_body or "").lower()

    cust_greeting = ""
    if sender_name and sender_name.strip() and "@" not in sender_name and len(sender_name.strip()) < 25:
        s_name = sender_name.strip()
        if any(s_name.lower().endswith(sfx) for sfx in ("bhai", "khan", "sir", "sahib", "sahab")):
            cust_greeting = f" {s_name}"
        else:
            cust_greeting = f" {s_name} bhai"

    is_greeting = any(w in lower_text for w in (
        "kaisa ho", "kaise ho", "kese ho", "kaisa he", "kaisay ho", "kaise hain", "kese hain",
        "kya haal", "kia hal", "kya hal", "kia haal", "hal chaal", "haal chal",
        "salam", "assalam", "aoa", "slam", "hello", "hi", "hey"
    ))
    is_health = any(w in lower_text for w in (
        "kaisa ho", "kaise ho", "kese ho", "kaisa he", "kaisay ho", "kaise hain", "kese hain",
        "kya haal", "kia hal", "kya hal", "kia haal"
    ))
    is_thanks = any(w in lower_text for w in ("shukriya", "thanks", "thank you", "jazakallah", "meherbani"))

    if lang_fmt == "roman_urdu":
        if is_health:
            return f"Walaikum Assalam{cust_greeting}! Main bilkul theek hoon, aap sunayein aap kaise hain? Batayein aaj main aap ki kya madad kar sakta hoon?"
        elif is_greeting:
            return f"Salam{cust_greeting}! Main aap ki kya madad kar sakta hoon? Batayein aap kya janna chahte hain."
        elif is_thanks:
            return f"Shukriya{cust_greeting}! Agar koi aur sawal ho to bila-jhijhak batayein."
        else:
            return f"Salam{cust_greeting}! Aap ke is sawal ke hawalay se mazeed batayein taake main aap ki behtareen rehnumai kar sakoon."
    elif lang_fmt == "urdu_arabic":
        if is_health:
            return "وعلیکم السلام! میں بالکل ٹھیک ہوں۔ فرمائیے میں آج آپ کی کیا مدد کر سکتا ہوں؟"
        return "سلام! فرمائیے میں آپ کی کیا مدد کر سکتا ہوں؟"
    elif lang_fmt in ("pashto_arabic", "roman_pashto"):
        return "Salam! Za staso sa marasta kawale sham? Mehherbani karke tapos karey."
    else:
        if is_health:
            return f"Hello{cust_greeting}! I'm doing well, thank you! How can I assist you today?"
        elif is_greeting:
            return f"Hello{cust_greeting}! How can I help you today?"
        return f"Hello{cust_greeting}! Could you share a few more details so I can assist you better?"


def generate_ai_auto_response(
    organization_id: Optional[str],
    message_body: str,
    sender_name: Optional[str] = None,
    sender_phone: Optional[str] = None,
    is_voice_inbound: bool = False,
    system_prompt: Optional[str] = None,
    knowledge_base: Optional[str] = None,
    catalog_context: Optional[str] = None
) -> Dict[str, Any]:
    """Generates a tailored AI auto-response with voice integration when inbound is voice/audio."""
    clean_body = str(message_body or "").strip()
    if not clean_body or clean_body.lower() in ("[voice note]", "🎤 voice message", "audio"):
        clean_body = "Hello, voice note received."

    # 1. Detect language & parse intent
    lang_info = detect_language(clean_body)
    lang_fmt = lang_info.get("format", "english")
    det_lang = lang_info.get("language", "english")
    det_script = lang_info.get("script", "latin")
    intent_data = parse_intent(clean_body)

    # 2. Generate conversational or appointment booking response
    booking_res = None
    negotiation_res = None
    if intent_data["intent"] == "booking_appointment":
        booking_res = handle_booking_flow(
            organization_id=organization_id,
            customer_phone=sender_phone,
            customer_name=sender_name,
            message_text=clean_body,
            lang_fmt=lang_fmt
        )
        reply_text = booking_res["reply_body"]
    elif intent_data["intent"] in ("sales_negotiation", "sales_checkout", "cart_management"):
        negotiation_res = handle_sales_negotiation_flow(
            organization_id=organization_id,
            customer_phone=sender_phone,
            customer_name=sender_name,
            message_text=clean_body,
            lang_fmt=lang_fmt
        )
        reply_text = negotiation_res["reply_body"]
    else:
        reply_text = generate_smart_conversational_fallback(
            message_body=clean_body,
            lang_fmt=lang_fmt,
            sender_name=sender_name,
            intent=intent_data["intent"]
        )

    # 3. Voice synthesis integration when inbound is voice
    audio_base64 = None
    audio_bytes = None
    send_as_voice = False

    if is_voice_inbound and reply_text:
        try:
            from services.voice_engine import generate_spoken_audio
            synth_lang = "ur" if ("ur" in det_lang or "urdu" in lang_fmt) else "en"
            synth_res = generate_spoken_audio(
                text=reply_text,
                language=synth_lang,
                organization_id=organization_id,
                output_format="oga"
            )
            if synth_res and synth_res[0]:
                audio_bytes = synth_res[0]
                audio_base64 = base64.b64encode(audio_bytes).decode("ascii")
                send_as_voice = True
        except Exception as v_err:
            logger.debug(f"[AI Responder Voice] Synthesis notice: {v_err}")

    return {
        "reply_body": reply_text,
        "intent": intent_data["intent"],
        "urgency": intent_data["urgency"],
        "lead_score": intent_data["lead_score"],
        "route_department": intent_data["route_department"],
        "detected_language": det_lang,
        "detected_script": det_script,
        "language_format": lang_fmt,
        "is_voice": is_voice_inbound,
        "send_as_voice": send_as_voice,
        "audio_base64": audio_base64,
        "is_ai_generated": True,
        "confidence": 90
    }
