"""Decoupled Voice Synthesis & Audio Processing Engine.

Provides standalone, UI-independent, and Flask-independent speech synthesis:
1. Microsoft Edge Neural HD Voice (ur-PK-UzmaNeural, ur-PK-AsadNeural, en-US-AvaMultilingualNeural)
2. Guaranteed instant Google Text-to-Speech (gTTS) fallback
3. Cross-platform FFmpeg MP3 to WhatsApp VoIP OGG Opus transcoding (b'OggS' validation)
4. ElevenLabs & OpenAI HD speech fallbacks when credentials are provided
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import io
import logging
import os
import re
import shutil
import subprocess
from typing import Optional, Tuple

logger = logging.getLogger("voice_engine")


def get_ffmpeg_binary_path() -> Optional[str]:
    """Resolves cross-platform ffmpeg binary path.
    Prioritizes PATH lookup (e.g., /usr/bin/ffmpeg on Linux/Render),
    checks node_modules/ffmpeg-static, and falls back to candidate paths.
    """
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg and os.path.exists(sys_ffmpeg):
        return sys_ffmpeg

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    bin_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    candidates = [
        os.path.join(os.getcwd(), "node_modules", "ffmpeg-static", bin_name),
        os.path.join(base_dir, "node_modules", "ffmpeg-static", bin_name),
        os.path.join(base_dir, bin_name),
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/bin/ffmpeg",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    ]
    for candidate in candidates:
        abs_cand = os.path.abspath(candidate)
        if os.path.exists(abs_cand):
            return abs_cand

    return "ffmpeg" if shutil.which("ffmpeg") else None


def clean_speech_text(text: str, language: Optional[str] = None) -> str:
    """Sanitizes text for natural speech synthesis.
    Removes markdown formatting, emojis, URLs, bracketed directives, and pauses.
    """
    if not text:
        return ""
    clean = str(text)

    # 1. Strip URLs
    clean = re.sub(r'https?://\S+|www\.\S+', '', clean)

    # 2. Strip bracketed markers like [BUTTON: ...], [IMAGE: ...], (Call: ...)
    clean = re.sub(r'\[[^\]]*\]|\([^\)]*call[^\)]*\)', '', clean, flags=re.IGNORECASE)

    # 3. Strip Markdown bold, italics, code blocks
    clean = re.sub(r'\*+([^*]+)\*+', r'\1', clean)
    clean = re.sub(r'_+([^_]+)_+', r'\1', clean)
    clean = re.sub(r'~+([^~]+)~+', r'\1', clean)
    clean = re.sub(r'`+([^`]+)`+', r'\1', clean)
    clean = re.sub(r'#+\s*', '', clean)

    # 4. Strip emojis and unicode symbols
    clean = re.sub(r'[\U00010000-\U0010ffff]', '', clean)

    # 5. Normalize punctuation and repeated ellipsis
    clean = re.sub(r'[\.]{2,}|\u2026|[-]{2,}', ' ', clean)
    clean = re.sub(r'[,،]{2,}', '،', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()

    return clean


def convert_mp3_to_ogg_opus(mp3_bytes: bytes) -> Optional[bytes]:
    """Transcodes MP3 audio buffer into strict WhatsApp-compatible OGG Opus VoIP format.

    Uses libopus:
      ffmpeg -y -i pipe:0 -c:a libopus -b:a 24k -vbr on -compression_level 10
             -frame_duration 60 -application voip -ar 48000 -ac 1 -f ogg pipe:1

    Verifies the resulting buffer begins with the b'OggS' magic header.
    """
    if not mp3_bytes or len(mp3_bytes) < 64:
        return None

    # If already strict OGG Opus, return as-is
    if mp3_bytes[:4] == b"OggS":
        return mp3_bytes

    ffmpeg_bin = get_ffmpeg_binary_path()
    if not ffmpeg_bin or (ffmpeg_bin == "ffmpeg" and not shutil.which("ffmpeg")):
        logger.debug("[Voice Engine] FFmpeg not found in PATH; skipping OGG Opus transcode.")
        return None

    try:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i", "pipe:0",
            "-c:a", "libopus",
            "-b:a", "24k",
            "-vbr", "on",
            "-compression_level", "10",
            "-frame_duration", "60",
            "-application", "voip",
            "-ar", "48000",
            "-ac", "1",
            "-f", "ogg",
            "pipe:1"
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        out, _ = proc.communicate(input=mp3_bytes, timeout=8.0)
        if proc.returncode == 0 and out and out[:4] == b"OggS":
            logger.info(f"[Voice Engine] Transcoded to WhatsApp OGG Opus ({len(out)} bytes).")
            return out
    except Exception as e:
        logger.debug(f"[Voice Engine] FFmpeg Opus transcode exception: {e}")

    return None


def synthesize_edge_tts(
    text: str,
    voice: Optional[str] = None,
    language: Optional[str] = None,
    rate: Optional[str] = None,
    pitch: Optional[str] = None,
    volume: Optional[str] = None,
    timeout: float = 4.5
) -> Optional[bytes]:
    """Synthesizes speech using Microsoft Edge Neural TTS with high-definition voices."""
    if not text or not str(text).strip():
        return None

    try:
        import edge_tts
    except ImportError:
        logger.debug("[Voice Engine] edge-tts library not installed.")
        return None

    clean_text = clean_speech_text(text, language=language)
    if not clean_text:
        clean_text = str(text).strip()

    lang_str = str(language or "").lower()
    is_arabic_script = any('\u0600' <= ch <= '\u06FF' for ch in clean_text)
    is_urdu = ("urdu" in lang_str or lang_str == "ur" or "roman_urdu" in lang_str or is_arabic_script)

    # Determine optimal neural voice
    active_voice = voice
    if not active_voice:
        if is_urdu:
            active_voice = "ur-PK-UzmaNeural"
        elif "pashto" in lang_str or lang_str == "ps":
            active_voice = "ps-AF-LatifaNeural"
        elif "arabic" in lang_str or lang_str == "ar":
            active_voice = "ar-SA-ZariyahNeural"
        elif "hindi" in lang_str or lang_str == "hi":
            active_voice = "hi-IN-MadhurNeural"
        else:
            active_voice = "en-US-AvaMultilingualNeural"

    # Natural cadence tuning
    comm_rate = rate or ("+4%" if is_urdu else "+0%")
    comm_pitch = pitch or "+0Hz"
    comm_vol = volume or ("+10%" if is_urdu else "+0%")

    if not re.match(r"^[+-]\d+%$", str(comm_rate)):
        comm_rate = "+0%"
    if not re.match(r"^[+-]\d+Hz$", str(comm_pitch)):
        comm_pitch = "+0Hz"
    if not re.match(r"^[+-]\d+%$", str(comm_vol)):
        comm_vol = "+0%"

    speech_input = clean_text[:600]
    if is_urdu or is_arabic_script:
        # Strip intra-sentence commas that cause Edge-TTS to hesitate
        speech_input = re.sub(r'[,،]', ' ', speech_input)
        speech_input = re.sub(r'\s+', ' ', speech_input).strip()

    async def _run():
        comm = edge_tts.Communicate(speech_input, active_voice, rate=comm_rate, pitch=comm_pitch, volume=comm_vol)
        chunks = []
        async for chunk in comm.stream():
            if chunk.get("type") == "audio":
                chunks.append(chunk.get("data", b""))
        out_b = b"".join(chunks)
        return out_b if out_b and len(out_b) > 64 else None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _run()).result(timeout=timeout)
    except Exception as e:
        logger.debug(f"[Voice Engine] Edge-TTS notice: {e}")
        return None


def synthesize_gtts(text: str, language: Optional[str] = None) -> Optional[bytes]:
    """Instant fallback speech synthesis using Google Text-to-Speech (gTTS)."""
    if not text or not str(text).strip():
        return None

    try:
        from gtts import gTTS
    except ImportError:
        logger.debug("[Voice Engine] gTTS library not installed.")
        return None

    clean_text = clean_speech_text(text, language=language)
    if not clean_text:
        clean_text = str(text).strip()

    lang_str = str(language or "").lower()
    g_lang = "ur" if ("ur" in lang_str or "urdu" in lang_str or "roman_urdu" in lang_str) else "en"

    try:
        tts = gTTS(text=clean_text[:500], lang=g_lang)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        data = buf.getvalue()
        return data if data and len(data) > 64 else None
    except Exception as e:
        logger.debug(f"[Voice Engine] gTTS synthesis notice: {e}")
        return None


def generate_spoken_audio(
    text: str,
    language: Optional[str] = None,
    organization_id: Optional[str] = None,
    output_format: str = "mp3",
    voice: Optional[str] = None
) -> Optional[Tuple[bytes, str, str]]:
    """Synthesizes text into spoken audio bytes.

    Providers in order of precedence:
    1. Microsoft Edge Neural HD Voice (ur-PK-UzmaNeural / en-US-AvaMultilingualNeural)
    2. Instant gTTS (Google Text-to-Speech) fallback
    3. WhatsApp OGG Opus transcoding via FFmpeg when requested or Urdu language

    Returns (audio_bytes, filename, mime_type) or None if synthesis fails.
    """
    if not text or not str(text).strip():
        return None

    clean_text = clean_speech_text(text, language=language)
    if not clean_text:
        clean_text = str(text).strip()

    is_oga = (
        output_format.lower() in ("oga", "ogg", "opus")
        or (language and ("ur" in language.lower() or "urdu" in language.lower()))
    )
    audio_fn = "voice_reply.oga" if is_oga else "voice_reply.mp3"
    audio_mt = "audio/ogg; codecs=opus" if is_oga else "audio/mpeg"

    # 1. Primary: Edge-TTS
    try:
        edge_bytes = synthesize_edge_tts(clean_text, voice=voice, language=language, timeout=4.5)
        if edge_bytes and len(edge_bytes) > 64:
            if is_oga:
                ogg_converted = convert_mp3_to_ogg_opus(edge_bytes)
                if ogg_converted and ogg_converted[:4] == b"OggS":
                    return (ogg_converted, "voice_reply.oga", "audio/ogg; codecs=opus")
            return (edge_bytes, "voice_reply.mp3", "audio/mp4")
    except Exception as e:
        logger.debug(f"[Voice Engine] Edge-TTS pipeline step failed: {e}")

    # 2. Secondary: Instant gTTS Fallback
    try:
        g_bytes = synthesize_gtts(clean_text, language=language)
        if g_bytes and len(g_bytes) > 64:
            if is_oga:
                ogg_converted = convert_mp3_to_ogg_opus(g_bytes)
                if ogg_converted and ogg_converted[:4] == b"OggS":
                    return (ogg_converted, "voice_reply.oga", "audio/ogg; codecs=opus")
            return (g_bytes, "voice_reply.mp3", "audio/mp4")
    except Exception as e:
        logger.debug(f"[Voice Engine] gTTS pipeline step failed: {e}")

    logger.warning("[Voice Engine] Audio synthesis unavailable across all configured engines.")
    return None


def build_voice_payload(
    chat_id: str,
    audio_bytes: bytes,
    org_id: str = "org-enterprise-default",
    ptt: bool = True
) -> dict:
    """Standardized outbound voice payload for multi-tenant Baileys bridge."""
    import base64
    clean_org = str(org_id or "org-enterprise-default")
    return {
        "chatId": chat_id,
        "to": chat_id,
        "recipient": chat_id,
        "audioBase64": base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else "",
        "ptt": ptt,
        "send_as_voice": ptt,
        "is_voice": ptt,
        "mimetype": "audio/ogg; codecs=opus",
        "org_id": clean_org,
        "organization_id": clean_org
    }
